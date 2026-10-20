"""Cache HTTP da API (L1): middleware ASGI na frente das rotas.

Pra cada ``GET`` a :data:`REGRAS` decide o ESCOPO e o TTL:

* ``publico``       — ``/v1/publico/*`` e ``/v1/horarios/*``: sem login, uma cópia pra todo mundo;
* ``compartilhado`` — ``/v1/consultas/*``, calendário: exige login válido, mas a cópia é a mesma
  pra todos os alunos (dado público visto de dentro do portal);
* ``aluno``         — o resto: a chave leva HMAC(segredo, hash do aluno) — um aluno nunca vê o
  dado de outro, e dois tokens do MESMO aluno dividem o cache.

Comportamento:

* fresco (idade < TTL) → ``X-Cache: HIT``, sem tocar no SIGAA;
* vencido mas dentro do *stale-while-revalidate* → ``X-Cache: STALE``: responde na hora e
  atualiza em segundo plano;
* ``?fresco=true``, ``Cache-Control: no-cache`` ou ``Pragma: no-cache`` → ``X-Cache: BYPASS``:
  vai ao SIGAA e atualiza o cache (``no-store`` = nem grava);
* *singleflight*: N pedidos iguais simultâneos = 1 navegação no SIGAA;
* ``ETag`` + ``If-None-Match`` → 304; gzip quando o cliente aceita (comprimido UMA vez por entrada);
  ``Age`` e ``X-Cache-Gerado-Em`` dizem a idade do dado;
* após ``POST /v1/auth/login``: PRÉ-AQUECIMENTO em segundo plano (portal, turmas, histórico,
  matrícula...), sempre cedendo a vez às requisições do próprio aluno;
* ``DELETE /v1/auth/sessao`` apaga o cache do aluno.

Só respostas 200 sem ``Set-Cookie`` entram no cache. Erros (401, 502...) passam direto.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter

from sigaa.pool import prioridade_baixa
from sigaa.cache import Entrada, cache

from .deps import SessaoAtual

log = logging.getLogger("sigaa_api.cache")

PUBLICO, COMPARTILHADO, ALUNO = "publico", "compartilhado", "aluno"
M, H, D = 60.0, 3600.0, 86400.0
MAX_ENTRADA = 8 * 1024 * 1024  # resposta maior que isso é servida, mas não guardada


@dataclass(frozen=True)
class Politica:
    escopo: str | None  # None = não cacheia
    ttl: float = 0.0
    swr: float = 0.0


NAO = Politica(None)
Regra = Politica | Callable[[dict[str, str]], Politica]


def _calendario(q: dict[str, str]) -> Politica:
    # sem ano/período o SIGAA usa o semestre ATUAL do aluno → por aluno; com eles é o mesmo pra todos
    if q.get("id") or (q.get("ano") and q.get("periodo")):
        return Politica(COMPARTILHADO, 24 * H, 7 * D)
    return Politica(ALUNO, 6 * H, 7 * D)


#: (regex do caminho, política) — a PRIMEIRA que casar vale.
REGRAS: list[tuple[re.Pattern[str], Regra]] = [
    (re.compile(p), pol)
    for p, pol in [
        # ---- nunca
        (r"^/v1/(auth|status|cache)(/|$)", NAO),
        (r"^/(docs|redoc|openapi\.json)", NAO),
        # ---- público (sem login)
        (r"^/v1/horarios/", Politica(PUBLICO, 7 * D, 30 * D)),
        (r"^/v1/publico/(cursos/\d+/)?turmas", Politica(PUBLICO, 10 * M, 1 * H)),
        (r"^/v1/publico/cursos/\d+/noticias", Politica(PUBLICO, 1 * H, 1 * D)),
        (r"^/v1/publico/biblioteca/", Politica(PUBLICO, 1 * H, 1 * D)),
        (r"^/v1/publico/(processos-seletivos|extensao|pesquisa|cursos-abertos|acordos-mobilidade)", Politica(PUBLICO, 6 * H, 1 * D)),
        (r"^/v1/publico/programas-pos/\d+/(noticias|processos-seletivos)", Politica(PUBLICO, 6 * H, 1 * D)),
        (r"^/v1/publico/", Politica(PUBLICO, 24 * H, 7 * D)),  # cursos, estruturas, componentes, docentes, unidades...
        # ---- compartilhado entre alunos (precisa de login)
        (r"^/v1/consultas/estruturas/\d+/declaracao", Politica(ALUNO, 1 * H, 1 * H)),  # documento emitido
        (r"^/v1/consultas/turmas/\d+", Politica(COMPARTILHADO, 5 * M, 30 * M)),  # vagas/solicitações
        (r"^/v1/consultas/turmas$", Politica(COMPARTILHADO, 10 * M, 1 * H)),
        (r"^/v1/consultas/", Politica(COMPARTILHADO, 24 * H, 7 * D)),
        (r"^/v1/calendario/lista", Politica(COMPARTILHADO, 24 * H, 7 * D)),
        (r"^/v1/calendario$", _calendario),
        # ---- por aluno
        (r"^/v1/(me/foto|foto)", Politica(ALUNO, 1 * D, 7 * D)),
        (r"^/v1/me/(dados-pessoais|perfil)", Politica(ALUNO, 1 * H, 1 * D)),
        (r"^/v1/(me|portal)$", Politica(ALUNO, 5 * M, 6 * H)),
        (r"^/v1/(turmas|grade-horaria(\.ics)?)$", Politica(ALUNO, 30 * M, 1 * D)),
        (r"^/v1/turmas/\d+/(notas|frequencia)$", Politica(ALUNO, 10 * M, 6 * H)),
        (r"^/v1/turmas/\d+/(arquivos|forum/\d+/topicos/\d+/anexos)/\d+$", Politica(ALUNO, 1 * H, 1 * D)),
        (r"^/v1/turmas/", Politica(ALUNO, 5 * M, 6 * H)),
        (r"^/v1/(notas|frequencia|tarefas|avaliacoes)$", Politica(ALUNO, 10 * M, 6 * H)),
        (r"^/v1/(historico|indices|integralizacao|pendencias)(/|$)", Politica(ALUNO, 30 * M, 1 * D)),
        (r"^/v1/(grade-curricular|carga-horaria|planejamento/)", Politica(ALUNO, 30 * M, 1 * D)),
        (r"^/v1/matricula", Politica(ALUNO, 5 * M, 6 * H)),
        (r"^/v1/documentos/", Politica(ALUNO, 1 * H, 1 * H)),
        (r"^/v1/(mensagens|atualizacoes|atividades|forum-curso)", Politica(ALUNO, 2 * M, 1 * H)),
        (r"^/v1/", Politica(ALUNO, 1 * M, 30 * M)),  # padrão das rotas logadas novas
    ]
]

_VERDADE = {"1", "true", "sim", "yes", "on", ""}


def politica(path: str, q: dict[str, str]) -> Politica:
    for rx, pol in REGRAS:
        if rx.search(path):
            return pol(q) if callable(pol) else pol
    return NAO


def montar_chave(pol: Politica, path: str, q: list[tuple[str, str]], usuario_hash: str | None) -> str:
    qs = urlencode(sorted((k, v) for k, v in q if k != "fresco"))
    if pol.escopo == ALUNO:
        return f"u:{cache.aluno(usuario_hash or '')}:{path}?{qs}"
    return f"{'p' if pol.escopo == PUBLICO else 'c'}:{path}?{qs}"


# ------------------------------------------------------------------ identidade
async def identificar(headers: dict[str, str], *, tocar: bool = True) -> str | None:
    """Hash do aluno dono do ``Authorization`` — só se a sessão existe e é válida."""
    from . import sessions as S

    esquema, _, valor = (headers.get("authorization") or "").partition(" ")
    esquema, valor = esquema.lower(), valor.strip()
    if not valor:
        return None
    ger = S.gerenciador
    if esquema == "bearer":
        sess = await ger.obter(valor) if tocar else ger.espiar(valor)  # espiar: valida também a ociosidade
        return getattr(sess, "usuario_hash", None)
    if esquema == "basic":
        try:
            usuario, _, senha = base64.b64decode(valor).decode("utf-8").partition(":")
        except Exception:  # noqa: BLE001
            return None
        sess = ger.espiar_basic(usuario, senha)  # só se a senha já foi validada (chave = HMAC do processo)
        return getattr(sess, "usuario_hash", None)
    return None


# ----------------------------------------------------------------------- ASGI
@dataclass
class Capturada:
    status: int
    headers: list[tuple[bytes, bytes]] = field(repr=False)
    corpo: bytes = field(repr=False)  # resposta do aluno: não vai pra repr/traceback


_GUARDAR = {"content-type", "content-disposition", "content-language"}
_TIRAR_REQ = {b"if-none-match", b"if-modified-since", b"cache-control", b"pragma", b"accept-encoding", b"content-length", b"content-type"}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def _forcar(q: dict[str, str], h: dict[str, str]) -> tuple[bool, bool]:
    """(ignorar o cache na leitura?, não gravar?)"""
    cc = (h.get("cache-control") or "").lower()
    no_store = "no-store" in cc
    fresco = q.get("fresco")
    forcar = (fresco is not None and fresco.strip().lower() in _VERDADE) or "no-cache" in cc or "max-age=0" in cc or no_store
    forcar = forcar or "no-cache" in (h.get("pragma") or "").lower()
    return forcar, no_store


def _scope_interno(base: dict, path: str, qs: str, headers: list[tuple[bytes, bytes]]) -> dict:
    sc = {k: v for k, v in base.items() if k not in ("state", "app", "router", "endpoint", "path_params", "route")}
    sc.update(method="GET", path=path, raw_path=path.encode(), query_string=qs.encode(), headers=headers)
    sc["state"] = {}
    return sc


class CacheHTTP:
    """Middleware ASGI puro (sem ``BaseHTTPMiddleware``: o HIT não cria task nem stream)."""

    def __init__(self, app) -> None:
        self.app = app
        self.ativos: dict[str, int] = {}  # aluno → requisições DELE em andamento (o pré-aquecimento cede)
        self.ultimo_fim: dict[str, float] = {}  # aluno sendo aquecido → monotonic() do fim da última requisição dele
        self._tarefas: set[asyncio.Task] = set()
        self._passo: dict[str, tuple[str, asyncio.Task]] = {}  # aluno → (chave, tarefa) do passo de aquecimento em curso
        self.preaquecer = os.getenv("SIGAA_API_PREAQUECER", "true").strip().lower() in _VERDADE - {""}
        self.rotas_preaquecer = [r.strip() for r in os.getenv("SIGAA_API_PREAQUECER_ROTAS", ",".join(ROTAS_PREAQUECER)).split(",") if r.strip()]
        self.espera_preaquecer = float(os.getenv("SIGAA_API_PREAQUECER_ESPERA", "0.4"))
        #: o aquecimento só usa a sessão depois de o aluno ficar esse tempo sem requisição (s)
        self.silencio_preaquecer = float(os.getenv("SIGAA_API_PREAQUECER_SILENCIO", "0.3"))

    # ------------------------------------------------------------------ entrada
    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not cache.ligado:
            return await self.app(scope, receive, send)
        metodo, path = scope["method"], scope["path"]
        if metodo == "POST" and path == "/v1/auth/login":
            return await self._login(scope, receive, send)
        if metodo == "DELETE" and path == "/v1/auth/sessao":
            return await self._logout(scope, receive, send)
        if metodo != "GET":
            return await self.app(scope, receive, send)

        ql = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        q = dict(ql)
        pol = politica(path, q)
        if pol.escopo is None:
            return await self.app(scope, receive, send)
        h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        uh = None
        if pol.escopo != PUBLICO:
            uh = await identificar(h)
            if uh is None:  # sem sessão válida: a própria rota responde (401, ou cria a sessão Basic)
                return await self.app(scope, receive, send)
        chave = montar_chave(pol, path, ql, uh)
        forcar, no_store = _forcar(q, h)

        if forcar:
            cache.stats["bypass"] += 1
        else:
            e = await cache.backend.obter(chave)
            if e is not None:
                agora = time.time()
                if e.fresca(agora):
                    cache.stats["hit"] += 1
                    return await self._responder(send, e, "HIT", h, pol)
                if e.servivel(agora):
                    cache.stats["stale"] += 1
                    self._revalidar(scope, chave, pol)
                    return await self._responder(send, e, "STALE", h, pol)
            f = cache.sf.em_voo(chave)
            if f is not None:
                try:
                    e = await asyncio.shield(f)
                except Exception:  # noqa: BLE001
                    e = None
                if e is not None:
                    cache.stats["juntou"] += 1
                    return await self._responder(send, e, "HIT", h, pol, extra=[("x-cache-singleflight", "seguiu")])

        cache.stats["miss"] += 0 if forcar else 1
        if uh:
            self.ativos[uh] = self.ativos.get(uh, 0) + 1
            passo = self._passo.get(uh)
            if passo is not None and passo[0] != chave and not passo[1].done():
                passo[1].cancel()  # o aluno chegou: o aquecimento solta a sessão e tenta essa rota depois
                cache.stats["preaquecimento_cedeu"] = cache.stats.get("preaquecimento_cedeu", 0) + 1
        try:
            cap, e = await self._buscar(scope, receive, chave, pol, gravar=not no_store)
        finally:
            if uh:
                if uh in self.ultimo_fim:
                    self.ultimo_fim[uh] = time.monotonic()
                n = self.ativos.get(uh, 1) - 1
                if n > 0:
                    self.ativos[uh] = n
                else:
                    self.ativos.pop(uh, None)
        if e is None:
            return await self._cru(send, cap)
        return await self._responder(send, e, "BYPASS" if forcar else "MISS", h, pol)

    # ------------------------------------------------------------ busca (líder)
    async def _executar(self, scope, receive) -> Capturada:
        partes: list[bytes] = []
        inicio: dict[str, Any] = {}

        async def capturar(msg):
            if msg["type"] == "http.response.start":
                inicio.update(msg)
            elif msg["type"] == "http.response.body":
                partes.append(msg.get("body", b""))

        if receive is None:
            primeira = True

            async def receive():  # noqa: F811 - requisição interna, sem corpo
                nonlocal primeira
                if primeira:
                    primeira = False
                    return {"type": "http.request", "body": b"", "more_body": False}
                await asyncio.Event().wait()

        await self.app(scope, receive, capturar)
        return Capturada(inicio.get("status", 500), list(inicio.get("headers", [])), b"".join(partes))

    async def _buscar(self, scope, receive, chave: str, pol: Politica, *, gravar: bool = True, f: asyncio.Future | None = None) -> tuple[Capturada, Entrada | None]:
        """Roda a rota de verdade (o SIGAA) como LÍDER do singleflight e grava se der 200."""
        f = f or cache.sf.iniciar(chave)
        e = None
        try:
            cap = await self._executar(scope, receive)
            hs = [(k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in cap.headers]
            if cap.status == 200 and len(cap.corpo) <= MAX_ENTRADA and not any(k == "set-cookie" for k, _ in hs):
                e = Entrada(
                    corpo=cap.corpo, criado=time.time(), ttl=pol.ttl, swr=pol.swr,
                    headers=[(k, v) for k, v in hs if k in _GUARDAR], sensivel=pol.escopo == ALUNO,
                )
                # comprime JÁ (uma vez só, antes de gravar: o tamanho na memória fica certo)
                await asyncio.to_thread(e.gz) if len(e.corpo) > 256 * 1024 else e.gz()
                if gravar:
                    await cache.backend.gravar(chave, e)
        except BaseException:
            cache.sf.terminar(chave, f, None)  # seguidores vão por conta própria
            raise
        cache.sf.terminar(chave, f, e)
        return cap, e

    def _tarefa(self, coro, chave: str | None = None, voo: asyncio.Future | None = None) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tarefas.add(t)
        t.add_done_callback(self._tarefas.discard)
        if voo is not None:  # cancelada antes de começar: não deixa seguidor esperando pra sempre
            t.add_done_callback(lambda _t: cache.sf.terminar(chave, voo, None))
        return t

    def _revalidar(self, scope, chave: str, pol: Politica) -> None:
        if cache.sf.em_voo(chave):
            return
        hs = [(k, v) for k, v in scope["headers"] if k.lower() not in _TIRAR_REQ]
        sc = _scope_interno(scope, scope["path"], scope.get("query_string", b"").decode("latin-1"), hs)

        voo = cache.sf.iniciar(chave)  # já em voo: STALEs seguidos no mesmo instante não disparam outra

        async def rodar():
            try:
                _, e = await self._buscar(sc, None, chave, pol, f=voo)
                if e is not None:
                    cache.stats["revalidou"] += 1
            except Exception as ex:  # noqa: BLE001 - segue servindo o velho
                log.info("revalidação de %s falhou: %s", scope["path"], ex)

        self._tarefa(rodar(), chave, voo)

    # ----------------------------------------------------------------- resposta
    async def _responder(self, send, e: Entrada, estado: str, h: dict[str, str], pol: Politica, extra: list | None = None) -> None:
        agora = time.time()
        idade = int(e.idade(agora))
        resta = max(0, int(e.ttl - idade))
        tipo = "public" if pol.escopo == PUBLICO else "private"
        cc = f"{tipo}, max-age={resta if estado != 'STALE' else 0}, stale-while-revalidate={int(pol.swr)}"
        hs = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in e.headers]
        hs += [
            (b"etag", e.etag.encode()),
            (b"cache-control", cc.encode()),
            (b"age", str(idade).encode()),
            (b"x-cache", estado.encode()),
            (b"x-cache-gerado-em", _iso(e.criado).encode()),
            (b"vary", b"Accept-Encoding" if pol.escopo == PUBLICO else b"Authorization, Accept-Encoding"),
        ]
        hs += [(k.encode(), v.encode()) for k, v in extra or []]
        inm = h.get("if-none-match")
        if inm and (inm.strip() == "*" or e.etag in {t.strip().removeprefix("W/") for t in inm.split(",")}):
            await send({"type": "http.response.start", "status": 304, "headers": hs})
            await send({"type": "http.response.body", "body": b""})
            return
        corpo = e.corpo
        if "gzip" in (h.get("accept-encoding") or ""):
            gz = e.gz() if (e._gz is not None or len(corpo) <= 256 * 1024) else await asyncio.to_thread(e.gz)
            if gz:
                corpo = gz
                hs.append((b"content-encoding", b"gzip"))
        hs.append((b"content-length", str(len(corpo)).encode()))
        await send({"type": "http.response.start", "status": e.status, "headers": hs})
        await send({"type": "http.response.body", "body": corpo})

    @staticmethod
    async def _cru(send, cap: Capturada) -> None:
        hs = [(k, v) for k, v in cap.headers if k.lower() != b"content-length"]
        hs.append((b"content-length", str(len(cap.corpo)).encode()))
        await send({"type": "http.response.start", "status": cap.status, "headers": hs})
        await send({"type": "http.response.body", "body": cap.corpo})

    # ------------------------------------------------------- login / logout
    async def _login(self, scope, receive, send) -> None:
        cap = await self._executar(scope, receive)
        await self._cru(send, cap)
        if cap.status != 200 or not self.preaquecer or not self.rotas_preaquecer:
            return
        try:
            token = json.loads(cap.corpo).get("token")
        except Exception:  # noqa: BLE001
            token = None
        if token:
            self._tarefa(self._preaquecer(scope, token))

    async def _logout(self, scope, receive, send) -> None:
        h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        uh = await identificar(h, tocar=False)
        await self.app(scope, receive, send)
        if uh:
            # o passo de pré-aquecimento em curso morre aqui (senão terminava DEPOIS da limpeza e regravava
            # dado do aluno); a fila dele vê a sessão encerrada e para
            passo = self._passo.get(uh)
            if passo is not None and not passo[1].done():
                passo[1].cancel()
                await asyncio.gather(passo[1], return_exceptions=True)
            await cache.limpar_aluno(uh)

    async def _preaquecer(self, base: dict, token: str) -> None:
        """Em segundo plano, logo após o login: busca as rotas mais usadas pro cache já estar quente
        quando o app pedir. Cede a vez ao aluno: (1) antes de cada passo espera ele ficar
        ``silencio_preaquecer`` s sem requisição; (2) se ele pedir OUTRA rota no meio de um passo, o
        passo é cancelado (solta a trava da sessão na hora) e volta pro fim da fila; (3) se ele pedir
        a MESMA rota que está sendo aquecida, entra no singleflight e recebe o resultado dela."""
        await asyncio.sleep(self.espera_preaquecer)
        auth = {"authorization": f"Bearer {token}"}
        hs = [(k, v) for k, v in base["headers"] if k.lower() in (b"host", b"user-agent")] + [(b"authorization", auth["authorization"].encode())]
        uh = await identificar(auth, tocar=False)
        if not uh or uh in self.ultimo_fim:
            return  # sem sessão, ou já tem um aquecimento rodando pra esse aluno (dois logins seguidos)
        self.ultimo_fim[uh] = 0.0
        try:
            # trabalho de FUNDO: só usa sessão do pool que sobra (deixa uma livre pro aluno) e nunca
            # abre sessão nova — as tarefas criadas dentro herdam o contexto
            with prioridade_baixa():
                await self._aquecer(base, auth, hs, uh)
        finally:
            self.ultimo_fim.pop(uh, None)

    async def _aquecer(self, base: dict, auth: dict[str, str], hs: list, uh: str) -> None:
        fila = [(r, 0) for r in self.rotas_preaquecer]
        while fila:
            rota, tentativa = fila.pop(0)
            path, _, qs = rota.partition("?")
            ql = parse_qsl(qs, keep_blank_values=True)
            pol = politica(path, dict(ql))
            if pol.escopo is None:
                continue
            chave = montar_chave(pol, path, ql, uh)
            t0 = time.monotonic()
            while time.monotonic() - t0 < 120 and (
                self.ativos.get(uh) or time.monotonic() - self.ultimo_fim.get(uh, 0) < self.silencio_preaquecer
            ):
                await asyncio.sleep(0.05)
            if await identificar(auth, tocar=False) is None:
                return  # logout no meio
            e = await cache.backend.obter(chave)
            if (e is not None and e.fresca()) or cache.sf.em_voo(chave):  # sem await entre o teste e o início
                continue
            voo = cache.sf.iniciar(chave)  # já em voo ANTES da tarefa começar: quem chegar agora se junta
            passo = asyncio.create_task(self._buscar(_scope_interno(base, path, qs, hs), None, chave, pol, f=voo))
            passo.add_done_callback(lambda _t, c=chave, v=voo: cache.sf.terminar(c, v, None))
            self._passo[uh] = (chave, passo)
            try:
                cap, e = await passo
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise  # o próprio aquecimento foi cancelado (desligando)
                if tentativa < 2:
                    fila.append((rota, tentativa + 1))  # cedeu a vez ao aluno: tenta no fim da fila
                continue
            except Exception as ex:  # noqa: BLE001
                log.info("pré-aquecimento de %s falhou: %s", path, ex)
                continue
            finally:
                if self._passo.get(uh, (None, None))[1] is passo:
                    del self._passo[uh]
            if e is not None:
                cache.stats["preaquecido"] = cache.stats.get("preaquecido", 0) + 1
            elif cap.status == 401:
                return

    async def fechar(self) -> None:
        for t in list(self._tarefas):
            t.cancel()


#: o que o app costuma pedir logo depois do login (na ordem)
ROTAS_PREAQUECER = [
    "/v1/portal",
    "/v1/me",
    "/v1/turmas",
    "/v1/grade-horaria",
    "/v1/historico",
    "/v1/indices",
    "/v1/integralizacao",
    "/v1/matricula",
]


# ----------------------------------------------------------------------- rotas
router = APIRouter(prefix="/v1/cache", tags=["Sistema"])


@router.get("/estatisticas", summary="Contadores do cache (HIT/MISS/STALE...) e uso de memória")
async def estatisticas():
    st = cache.info()
    c = st["contadores"]
    servidos = c["hit"] + c["stale"] + c["juntou"]
    total = servidos + c["miss"] + c["bypass"]
    st["taxa_acerto"] = round(servidos / total, 4) if total else None
    return st


@router.delete("/meu", status_code=204, summary="Apagar o MEU cache (a próxima consulta vai ao SIGAA)")
async def limpar_meu(sess: SessaoAtual):
    await cache.limpar_aluno(sess.usuario_hash)
