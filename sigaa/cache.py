"""Cache do sigaa-api: backends (memória / Redis), *singleflight* e o cache COMPARTILHADO
de serviço (dado público reaproveitado entre alunos).

Duas camadas usam este módulo:

* **L1 — resposta HTTP** (``api/cache.py``): guarda o corpo pronto de cada GET, por aluno
  ou compartilhado, com TTL + stale-while-revalidate, ETag e gzip.
* **L2 — serviço** (:func:`compartilhado` / :func:`instalar`): guarda o RESULTADO de funções
  de navegação de dado público (estrutura curricular, componente e pré-requisitos, oferta
  de turmas, calendário, unidades...). Quem ganha é a rota composta: o ``/planejamento`` do
  aluno B reaproveita a oferta e os pré-requisitos que o aluno A do mesmo curso já buscou.

Backends:

* :class:`Memoria` (padrão): LRU com limite de bytes, por processo.
* :class:`Redis` (``SIGAA_API_CACHE_URL=redis://...``): compartilhado entre workers. Entrada
  marcada ``sensivel`` (dado de aluno) só vai pro Redis CIFRADA (Fernet com chave derivada de
  ``SIGAA_API_CACHE_SEGREDO``); sem segredo configurado, dado de aluno fica só na memória local.

Chaves de aluno usam HMAC(segredo, hash do usuário) — nunca o login nem o token em claro.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import gzip
import hashlib
import hmac
import inspect
import json
import logging
import os
import secrets
import time
import typing
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("sigaa_api.cache")

#: tipos de conteúdo que valem a pena comprimir
COMPRIMIVEIS = ("json", "text/", "xml", "javascript", "calendar")


# ====================================================================== entrada
@dataclass
class Entrada:
    """Uma resposta (L1) ou um valor serializado (L2) guardado no cache."""

    corpo: bytes = field(repr=False)  # pode ser dado de aluno: não vai pra repr/traceback
    criado: float  # time.time() de quando o dado veio do SIGAA
    ttl: float  # segundos de "fresco"
    swr: float = 0.0  # segundos extras em que ainda serve STALE (e revalida em 2º plano)
    status: int = 200
    headers: list[tuple[str, str]] = field(default_factory=list)
    etag: str = ""
    sensivel: bool = False
    _gz: bytes | None = field(default=None, repr=False)
    _tam: int = field(default=0, repr=False)  # tamanho contabilizado quando entrou na memória

    def __post_init__(self) -> None:
        if not self.etag:
            self.etag = '"' + hashlib.blake2b(self.corpo, digest_size=12).hexdigest() + '"'

    # ------------------------------------------------------------ estado
    def idade(self, agora: float | None = None) -> float:
        return max(0.0, (agora or time.time()) - self.criado)

    def fresca(self, agora: float | None = None) -> bool:
        return self.idade(agora) < self.ttl

    def servivel(self, agora: float | None = None) -> bool:
        return self.idade(agora) < self.ttl + self.swr

    @property
    def tamanho(self) -> int:
        return len(self.corpo) + (len(self._gz) if self._gz else 0) + 200

    def header(self, nome: str) -> str | None:
        nome = nome.lower()
        return next((v for k, v in self.headers if k.lower() == nome), None)

    def gz(self) -> bytes | None:
        """Corpo comprimido (calculado uma vez e guardado). ``None`` = não compensa."""
        if self._gz is None:
            ct = (self.header("content-type") or "").lower()
            if len(self.corpo) < 800 or not any(t in ct for t in COMPRIMIVEIS):
                self._gz = b""
            else:
                self._gz = gzip.compress(self.corpo, compresslevel=6, mtime=0)
                if len(self._gz) >= len(self.corpo):
                    self._gz = b""
        return self._gz or None

    # ------------------------------------------------------ serialização
    def para_bytes(self) -> bytes:
        cab = json.dumps(
            {"c": self.criado, "t": self.ttl, "s": self.swr, "st": self.status, "h": self.headers, "e": self.etag, "x": self.sensivel},
            separators=(",", ":"),
        ).encode()
        return len(cab).to_bytes(4, "big") + cab + self.corpo

    @classmethod
    def de_bytes(cls, dados: bytes) -> "Entrada":
        n = int.from_bytes(dados[:4], "big")
        cab = json.loads(dados[4 : 4 + n])
        return cls(
            corpo=dados[4 + n :], criado=cab["c"], ttl=cab["t"], swr=cab["s"], status=cab["st"],
            headers=[tuple(h) for h in cab["h"]], etag=cab["e"], sensivel=cab["x"],
        )


# ===================================================================== backends
class Backend:
    nome = "?"

    async def obter(self, chave: str) -> Entrada | None:  # pragma: no cover - interface
        raise NotImplementedError

    async def gravar(self, chave: str, e: Entrada) -> None:  # pragma: no cover
        raise NotImplementedError

    async def apagar_prefixo(self, prefixo: str) -> int:  # pragma: no cover
        raise NotImplementedError

    async def limpar(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def info(self) -> dict[str, Any]:
        return {"backend": self.nome}

    async def fechar(self) -> None:
        pass


class Memoria(Backend):
    """LRU por bytes. Leitura/escrita O(1), sem lock (asyncio é single-thread)."""

    nome = "memoria"

    def __init__(self, max_bytes: int = 256 * 1024 * 1024, max_itens: int = 100_000) -> None:
        self.max_bytes, self.max_itens = max_bytes, max_itens
        self._d: OrderedDict[str, Entrada] = OrderedDict()
        self.bytes = 0
        self.despejos = 0

    async def obter(self, chave: str) -> Entrada | None:
        e = self._d.get(chave)
        if e is None:
            return None
        if not e.servivel():
            self._remover(chave)
            return None
        self._d.move_to_end(chave)
        return e

    def obter_sync(self, chave: str) -> Entrada | None:
        e = self._d.get(chave)
        if e is not None and e.servivel():
            self._d.move_to_end(chave)
            return e
        return None

    async def gravar(self, chave: str, e: Entrada) -> None:
        e._tam = e.tamanho
        if e._tam > self.max_bytes // 4:
            return
        self._remover(chave)
        self._d[chave] = e
        self.bytes += e._tam
        while self._d and (self.bytes > self.max_bytes or len(self._d) > self.max_itens):
            velho, ev = self._d.popitem(last=False)
            self.bytes -= ev._tam
            self.despejos += 1

    def _remover(self, chave: str) -> None:
        ev = self._d.pop(chave, None)
        if ev is not None:
            self.bytes -= ev._tam

    async def apagar_prefixo(self, prefixo: str) -> int:
        alvo = [k for k in self._d if k.startswith(prefixo)]
        for k in alvo:
            self._remover(k)
        return len(alvo)

    async def limpar(self) -> None:
        self._d.clear()
        self.bytes = 0

    def info(self) -> dict[str, Any]:
        return {"backend": self.nome, "itens": len(self._d), "bytes": self.bytes, "max_bytes": self.max_bytes, "despejos": self.despejos}


class Redis(Backend):
    """Redis (``redis.asyncio``) com cifragem das entradas sensíveis.

    Por cima dele fica uma :class:`Memoria` pequena (L0, por processo) pra que o HIT quente não
    pague nem a ida ao Redis; o L0 vive pouco (``l0_ttl``) pra não divergir entre workers."""

    nome = "redis"

    def __init__(self, url: str, *, segredo: bytes | None, prefixo: str = "sigaa:", l0_bytes: int = 64 * 1024 * 1024, l0_ttl: float = 5.0) -> None:
        import redis.asyncio as aioredis  # dependência opcional

        self._r = aioredis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
        self.prefixo = prefixo
        self._fernet = None
        if segredo:
            from cryptography.fernet import Fernet

            chave = base64.urlsafe_b64encode(hashlib.sha256(b"sigaa-cache-fernet\x00" + segredo).digest())
            self._fernet = Fernet(chave)
        self.l0 = Memoria(l0_bytes)
        self.l0_ttl = l0_ttl
        self._l0_quando: dict[str, float] = {}
        self.erros = 0
        self.local_sensivel = Memoria(l0_bytes)  # dado de aluno quando não há segredo

    async def obter(self, chave: str) -> Entrada | None:
        e = await self.l0.obter(chave)
        if e is not None and time.monotonic() - self._l0_quando.get(chave, 0) < self.l0_ttl:
            return e
        if self._fernet is None:
            e2 = await self.local_sensivel.obter(chave)
            if e2 is not None:
                return e2
        try:
            dados = await self._r.get(self.prefixo + chave)
        except Exception as ex:  # noqa: BLE001 - Redis fora do ar não derruba a API
            self.erros += 1
            log.warning("redis get falhou: %s", ex)
            return e
        if dados is None:
            return None
        if dados[:1] == b"F":
            if self._fernet is None:
                return None
            try:
                dados = self._fernet.decrypt(dados[1:])
            except Exception:  # noqa: BLE001 - segredo trocado: trata como ausente
                return None
        else:
            dados = dados[1:]
        e = Entrada.de_bytes(dados)
        if not e.servivel():
            return None
        await self.l0.gravar(chave, e)
        self._l0_quando[chave] = time.monotonic()
        return e

    async def gravar(self, chave: str, e: Entrada) -> None:
        await self.l0.gravar(chave, e)
        self._l0_quando[chave] = time.monotonic()
        if e.sensivel and self._fernet is None:
            await self.local_sensivel.gravar(chave, e)  # nunca vai pro Redis em claro
            return
        dados = e.para_bytes()
        dados = (b"F" + self._fernet.encrypt(dados)) if e.sensivel else (b"P" + dados)
        try:
            await self._r.set(self.prefixo + chave, dados, ex=max(1, int(e.ttl + e.swr) + 1))
        except Exception as ex:  # noqa: BLE001
            self.erros += 1
            log.warning("redis set falhou: %s", ex)

    async def apagar_prefixo(self, prefixo: str) -> int:
        n = await self.l0.apagar_prefixo(prefixo) + await self.local_sensivel.apagar_prefixo(prefixo)
        try:
            async for k in self._r.scan_iter(match=self.prefixo + prefixo + "*", count=500):
                await self._r.delete(k)
                n += 1
        except Exception as ex:  # noqa: BLE001
            self.erros += 1
            log.warning("redis delete falhou: %s", ex)
        return n

    async def limpar(self) -> None:
        await self.apagar_prefixo("")

    def info(self) -> dict[str, Any]:
        return {"backend": self.nome, "cifrado": self._fernet is not None, "l0": self.l0.info(), "erros": self.erros}

    async def fechar(self) -> None:
        try:
            await self._r.aclose()
        except Exception:  # noqa: BLE001
            pass


# ================================================================== singleflight
_FALHOU = object()


class Singleflight:
    """Pedidos iguais ao mesmo tempo = UMA execução; os outros esperam o mesmo resultado."""

    def __init__(self) -> None:
        self._voo: dict[str, asyncio.Future] = {}
        self.juntados = 0

    def em_voo(self, chave: str) -> asyncio.Future | None:
        f = self._voo.get(chave)
        return f if f is not None and not f.done() else None

    def iniciar(self, chave: str) -> asyncio.Future:
        f = asyncio.get_running_loop().create_future()
        self._voo[chave] = f
        return f

    def terminar(self, chave: str, f: asyncio.Future, valor: Any = None, erro: BaseException | None = None) -> None:
        if self._voo.get(chave) is f:
            del self._voo[chave]
        if not f.done():
            if isinstance(erro, Exception):
                f.set_exception(erro)
                f.exception()  # marca como "lida" (sem warning se ninguém esperava)
            else:  # sucesso, ou o líder foi cancelado (BaseException): seguidores recebem o valor/_FALHOU
                f.set_result(_FALHOU if erro is not None else valor)

    async def fazer(self, chave: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        f = self.em_voo(chave)
        if f is not None:
            self.juntados += 1
            try:
                v = await asyncio.shield(f)
                if v is not _FALHOU:
                    return v
            except Exception:  # noqa: BLE001 - o líder falhou (ex.: a sessão DELE caiu): tenta por conta própria
                pass
        f = self.iniciar(chave)
        try:
            v = await fn()
        except BaseException as e:
            self.terminar(chave, f, erro=e)
            raise
        self.terminar(chave, f, v)
        return v


# ==================================================================== o cache
def _bool(nome: str, padrao: bool) -> bool:
    v = os.getenv(nome)
    return padrao if v is None else v.strip().lower() in ("1", "true", "sim", "yes", "on")


class Cache:
    """Instância do processo (``cache``). Configurada por variáveis de ambiente:

    * ``SIGAA_API_CACHE`` (padrão ``true``) — liga/desliga tudo;
    * ``SIGAA_API_CACHE_URL`` — ``redis://...`` pra compartilhar entre workers (padrão: memória);
    * ``SIGAA_API_CACHE_SEGREDO`` — segredo do HMAC das chaves de aluno e da cifra no Redis
      (sem ele: aleatório por processo e dado de aluno nunca sai da memória local);
    * ``SIGAA_API_CACHE_MAX_MB`` (padrão 256) — teto da memória.
    """

    def __init__(self) -> None:
        self.ligado = _bool("SIGAA_API_CACHE", True)
        seg = os.getenv("SIGAA_API_CACHE_SEGREDO")
        self.segredo_configurado = bool(seg)
        self.segredo = seg.encode() if seg else secrets.token_bytes(32)
        url = os.getenv("SIGAA_API_CACHE_URL", "").strip()
        max_b = int(float(os.getenv("SIGAA_API_CACHE_MAX_MB", "256")) * 1024 * 1024)
        self.backend: Backend = Memoria(max_b)
        if url:
            try:
                self.backend = Redis(url, segredo=seg.encode() if seg else None)
            except Exception as e:  # noqa: BLE001 - sem o pacote redis: segue na memória
                log.warning("SIGAA_API_CACHE_URL ignorado (%s); usando memória", e)
        self.sf = Singleflight()
        self.stats: dict[str, int] = {"hit": 0, "miss": 0, "stale": 0, "bypass": 0, "juntou": 0, "revalidou": 0, "l2_hit": 0, "l2_miss": 0}

    def usar(self, backend: Backend) -> None:
        self.backend = backend

    def aluno(self, usuario_hash: str) -> str:
        """Parte da chave que identifica o aluno: HMAC, não reversível sem o segredo."""
        return hmac.new(self.segredo, usuario_hash.encode(), hashlib.sha256).hexdigest()[:32]

    async def limpar_aluno(self, usuario_hash: str) -> int:
        return await self.backend.apagar_prefixo(f"u:{self.aluno(usuario_hash)}:")

    def info(self) -> dict[str, Any]:
        return {"ligado": self.ligado, **self.backend.info(), "contadores": dict(self.stats), "singleflight_juntados": self.sf.juntados}


cache = Cache()


# ======================================================= L2: cache compartilhado
_adaptadores: dict[Any, Any] = {}


def _adaptador(tipo):
    from pydantic import TypeAdapter

    a = _adaptadores.get(tipo)
    if a is None:
        a = _adaptadores[tipo] = TypeAdapter(tipo)
    return a


def _arg_chave(v: Any) -> str:
    if v is None or isinstance(v, (str, int, float, bool)):
        return repr(v)
    return repr(sorted(v.items())) if isinstance(v, dict) else repr(v)


def compartilhado(ttl: float, *, nome: str | None = None, swr: float = 0.0):
    """Decorator pra ``async def servico(c: SigaaClient, *args)`` de DADO PÚBLICO: o resultado
    é guardado sem o aluno na chave (o primeiro argumento, a sessão, é ignorado) e devolvido pra
    qualquer aluno. Serializado em JSON pelo tipo de retorno anotado — cada HIT devolve um objeto
    NOVO (ninguém altera o objeto do outro) e o mesmo valor serve no Redis.

    Só use em função cuja resposta NÃO depende de quem está logado."""

    def deco(fn):
        if getattr(fn, "__cache_compartilhado__", False):
            return fn
        sig = inspect.signature(fn)
        try:
            tipo = typing.get_type_hints(fn).get("return", Any)
        except Exception:  # noqa: BLE001
            tipo = Any
        rotulo = nome or f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__name__}"

        @functools.wraps(fn)
        async def wrapper(c, *args, **kwargs):
            if not cache.ligado or getattr(c, "_sem_cache_compartilhado", False):
                return await fn(c, *args, **kwargs)
            ba = sig.bind(c, *args, **kwargs)
            ba.apply_defaults()
            partes = [f"{k}={_arg_chave(v)}" for k, v in list(ba.arguments.items())[1:]]
            chave = f"s:{rotulo}:" + hashlib.blake2b("|".join(partes).encode(), digest_size=12).hexdigest()
            e = await cache.backend.obter(chave)
            if e is not None and e.fresca():
                cache.stats["l2_hit"] += 1
                return _adaptador(tipo).validate_json(e.corpo)

            async def buscar():
                v = await fn(c, *args, **kwargs)
                corpo = _adaptador(tipo).dump_json(v)
                await cache.backend.gravar(chave, Entrada(corpo=corpo, criado=time.time(), ttl=ttl, swr=swr, headers=[("content-type", "application/json")]))
                return corpo

            cache.stats["l2_miss"] += 1
            corpo = await cache.sf.fazer(chave, buscar)
            return _adaptador(tipo).validate_json(corpo)

        wrapper.__cache_compartilhado__ = True
        wrapper.__wrapped_original__ = fn
        return wrapper

    return deco


#: (módulo, função, TTL em segundos). Só funções cujo resultado é igual pra qualquer aluno.
H = 3600.0
REGISTRO_COMPARTILHADO: list[tuple[str, str, float]] = [
    # consultas gerais (logadas, mas dado público)
    ("sigaa.services.consultas", "estrutura", 24 * H),
    ("sigaa.services.consultas", "buscar_estruturas", 24 * H),
    ("sigaa.services.consultas", "componente", 24 * H),
    ("sigaa.services.consultas", "buscar_componentes", 12 * H),
    ("sigaa.services.consultas", "opcoes_componentes", 24 * H),
    ("sigaa.services.consultas", "opcoes_turmas", 24 * H),
    ("sigaa.services.consultas", "cursos_com_id", 24 * H),
    ("sigaa.services.consultas", "buscar_cursos", 24 * H),
    ("sigaa.services.consultas", "buscar_turmas", 10 * 60),  # vagas mudam na matrícula
    ("sigaa.services.consultas", "turma", 5 * 60),
    ("sigaa.services.consultas", "listar_calendarios", 24 * H),
    ("sigaa.services.consultas", "buscar_unidades", 24 * H),
    ("sigaa.services.consultas", "tipos_unidade", 24 * H),
]


def instalar(registro: list[tuple[str, str, float]] | None = None) -> list[str]:
    """Liga o cache compartilhado nas funções de serviço do ``REGISTRO_COMPARTILHADO``
    (troca o atributo do módulo pelo wrapper — quem chama ``consultas.estrutura(...)`` passa
    a usar o cache sem mudar uma linha). Idempotente. Devolve o que foi instalado."""
    import importlib

    feitos = []
    for mod_nome, fn_nome, ttl in registro or REGISTRO_COMPARTILHADO:
        try:
            mod = importlib.import_module(mod_nome)
        except ModuleNotFoundError:
            continue
        fn = getattr(mod, fn_nome, None)
        if fn is None or not inspect.iscoroutinefunction(fn):
            continue
        setattr(mod, fn_nome, compartilhado(ttl)(fn))
        feitos.append(f"{mod_nome.rsplit('.', 1)[-1]}.{fn_nome}")
    return feitos
