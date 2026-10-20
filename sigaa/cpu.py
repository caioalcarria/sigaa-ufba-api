"""Trabalho de CPU (parse de HTML/PDF) FORA do event loop, num pool de PROCESSOS.

Por que processos e não threads: o BeautifulSoup (e o layout do PDF) são Python puro e
seguram o GIL — em thread eles só disputam a CPU com o event loop. Num pool de processos
o parse roda em paralelo nos outros núcleos e o event loop fica livre pra I/O, mantendo
UM processo de API (as sessões continuam em memória, sem mudar nada no modelo delas).

Uso (os parsers são funções puras: html/bytes → modelo pydantic, que é picklável)::

    from sigaa.cpu import rodar
    return await rodar(P.parse_portal, page.html)

Sem :func:`iniciar` (biblioteca, testes) ``rodar`` executa na hora, no mesmo processo —
exatamente o comportamento antigo. A API chama ``iniciar()`` no boot.
"""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import functools
import logging
import multiprocessing as mp
import os
import pickle  # só pra pegar PicklingError; nada vem de fora (o L2 é JSON)  # nosec B403
from datetime import date, datetime
from typing import Any, Callable, TypeVar

log = logging.getLogger("sigaa.cpu")

T = TypeVar("T")

#: um parse que não volta em tanto tempo = pool travado: recria e faz aqui
PRAZO_S = float(os.getenv("SIGAA_PARSE_PRAZO_S", "30"))

#: abaixo disso (soma dos str/bytes dos argumentos) o parse é tão rápido que ir e voltar
#: do outro processo custa mais do que parsear aqui
LIMIAR_BYTES = int(os.getenv("SIGAA_PARSE_LIMIAR_BYTES", "1500"))

_pool: cf.ProcessPoolExecutor | None = None
_processos = 0
_SIMPLES = (str, bytes, int, float, bool, type(None), date, datetime)


def nucleos() -> int:
    """Núcleos que ESTE processo pode usar: afinidade e a cota do cgroup (Docker ``--cpus``) —
    o ``os.cpu_count()`` devolve os do host inteiro."""
    try:
        n = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        n = os.cpu_count() or 1
    try:
        cota, periodo = open("/sys/fs/cgroup/cpu.max").read().split()
        if cota != "max":
            n = min(n, max(1, -(-int(cota) // int(periodo))))
    except (OSError, ValueError):
        pass
    return n


def _vigiar_pai(pid: int) -> None:
    """Thread do processo do pool: a API morreu (kill, OOM, crash)? Sai junto — senão os
    processos do pool (filhos do forkserver, não da API) ficavam órfãos pra sempre."""
    import time

    while True:
        time.sleep(2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            os._exit(0)
        except PermissionError:
            pass


def _aquecer(pid_api: int | None = None) -> None:
    """Roda em cada processo do pool ao nascer: importa os parsers uma vez só."""
    import importlib
    import threading

    if pid_api:
        threading.Thread(target=_vigiar_pai, args=(pid_api,), daemon=True).start()

    for m in ("portal", "academico", "turma_virtual", "consultas", "consultas_publico", "historico_pdf"):
        try:
            importlib.import_module(f"sigaa.parsers.{m}")
        except Exception:  # noqa: BLE001 - parser ausente/quebrado não impede o pool  # nosec B110
            pass


def iniciar(processos: int | None = None, *, aquecer: bool = True, cancelar: bool = True) -> int:
    """Liga o pool. ``processos`` None = ``SIGAA_PARSE_PROCESSOS`` ou (núcleos - 1, de 1 a 8).
    0 = desligado (parse no event loop, como antes). Devolve o nº de processos."""
    global _pool, _processos
    if processos is None:
        env = os.getenv("SIGAA_PARSE_PROCESSOS")
        processos = int(env) if env not in (None, "") else max(1, min(8, nucleos() - 1))
    parar(cancelar=cancelar)
    if processos <= 0:
        return 0
    # forkserver: não herda as threads/loop do processo da API (fork com threads é frágil)
    ctx = mp.get_context("forkserver") if "forkserver" in mp.get_all_start_methods() else mp.get_context("spawn")
    _pool = cf.ProcessPoolExecutor(processos, mp_context=ctx, initializer=_aquecer, initargs=(os.getpid(),))
    # (sem max_tasks_per_child: no 3.12 a reciclagem de processo trava o pool — futures que
    # nunca voltam, visto sob carga aqui. Os parsers são puros, não há o que vazar.)
    _processos = processos
    # sobe os processos já (o 1º parse não paga o boot)
    for f in [] if not aquecer else [_pool.submit(_nada) for _ in range(processos)]:
        f.result()
    log.info("pool de parse: %d processo(s)", processos)
    return processos


def _nada() -> None:
    return None


def parar(*, esperar: bool = False, cancelar: bool = True) -> None:
    global _pool, _processos
    if _pool is not None:
        _pool.shutdown(wait=esperar, cancel_futures=cancelar)
    _pool, _processos = None, 0


def ativo() -> int:
    """Nº de processos do pool (0 = desligado)."""
    return _processos


def _importavel(fn: Callable) -> bool:
    """O processo do pool só acha função de módulo importável (não lambda/local/__main__) —
    mandar outra coisa derrubaria o pool inteiro."""
    mod, nome = getattr(fn, "__module__", None), getattr(fn, "__qualname__", "")
    return bool(mod) and mod != "__main__" and "<" not in nome


def _vale_a_pena(args: tuple, kw: dict) -> bool:
    tam = 0
    for v in (*args, *kw.values()):
        if isinstance(v, (dict, list, tuple)):
            continue  # pequenos (extra de formulário, botão): vão no pickle
        if not isinstance(v, _SIMPLES):
            return False  # soup/Page/objeto qualquer: não manda pro outro processo
        if isinstance(v, (str, bytes)):
            tam += len(v)
    return tam >= LIMIAR_BYTES


async def rodar(fn: Callable[..., T], *args: Any, **kw: Any) -> T:
    """``fn(*args, **kw)`` no pool de processos (se ligado e se compensa); senão aqui mesmo.

    Mesma semântica da chamada direta: o resultado ou a exceção do parser. Se o pool
    quebrar (processo morto, algo não picklável), refaz a chamada aqui — o parser é puro,
    então refazer dá o mesmo resultado."""
    pool = _pool
    if pool is None or not _importavel(fn) or not _vale_a_pena(args, kw):
        return fn(*args, **kw)
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(pool, functools.partial(fn, *args, **kw)), PRAZO_S)
    except (cf.process.BrokenProcessPool, TimeoutError) as e:
        log.warning("pool de parse %s; recriando", "travou" if isinstance(e, TimeoutError) else "quebrou")
        _recriar(pool)
    except pickle.PicklingError:
        pass  # argumento/resultado não picklável: faz aqui
    return fn(*args, **kw)


def _recriar(quebrado: cf.ProcessPoolExecutor) -> None:
    if _pool is quebrado:
        n = _processos
        try:
            # sem bloquear o event loop esperando o boot, e sem cancelar o que as OUTRAS requisições
            # mandaram pro pool velho (elas caem no próprio prazo e fazem aqui)
            iniciar(n, aquecer=False, cancelar=False)
        except Exception:  # noqa: BLE001
            log.exception("não deu pra recriar o pool de parse; seguindo sem ele")
            parar()
