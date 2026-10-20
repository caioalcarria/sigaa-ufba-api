"""SIGAA UFBA API — servidor FastAPI.

Rodar:  uvicorn api.main:app --reload
Docs:   http://localhost:8000/docs  (Swagger)  ·  /redoc
"""

from __future__ import annotations

import asyncio
import gc
import importlib
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from sigaa import cpu
from sigaa import errors as E
from sigaa import __version__
from sigaa.client import _ssl_ctx

from sigaa import cache as sigaa_cache

from . import cache as cache_http
from .config import config
from .sessions import gerenciador

log = logging.getLogger("sigaa_api")

DESCRICAO = """
API **não oficial** e de **somente leitura** pros dados do aluno no SIGAA da UFBA.

Ela entra no SIGAA com o login do próprio aluno e devolve tudo **já estruturado em JSON**:
perfil, turmas, turma virtual (notícias, aulas, notas, frequência, tarefas...), histórico
escolar extraído do PDF, índices com a evolução do CR, integralização, matrícula do semestre,
documentos e as consultas públicas (cursos, componentes, turmas ofertadas, calendário).

### Como usar
1. `POST /v1/auth/login` com `{"usuario": "...", "senha": "..."}` → recebe um `token`.
2. Mande `Authorization: Bearer <token>` nas outras rotas.
3. Rotas em `/v1/publico/...` não precisam de login.

A senha nunca é gravada. Com `"lembrar": true` ela fica cifrada só na memória do servidor
pra API relogar sozinha quando o SIGAA derrubar a sessão por inatividade.

### Erros
Todo erro vem como `{"erro": {"codigo": "...", "mensagem": "..."}}` — `credenciais_invalidas` (401),
`sessao_expirada` (401), `token_invalido` (401), `acesso_negado` (403), `nao_encontrado` (404),
`muitas_tentativas` (429), `sigaa_erro` / `navegacao_invalida` (502), `sigaa_indisponivel` / `sigaa_ocupado` (503,
com `Retry-After`), `tempo_esgotado` (504).
"""

#: módulos de rota (cada frente do projeto tem o seu); ausentes são ignorados com aviso
ROTAS = ["auth", "portal", "midia", "turma_virtual", "academico", "planejamento", "consultas"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # parse de HTML/PDF fora do event loop, nos outros núcleos (ver sigaa/cpu.py e docs/servidor.md)
    await asyncio.to_thread(cpu.iniciar, config.PARSE_PROCESSOS)
    # GC: o que já está carregado (módulos, rotas, modelos) vai pra geração "permanente" e não é
    # mais varrido; e a geração 0 roda bem menos vezes — as varreduras completas com centenas de
    # sessões em memória chegavam a 100–200 ms com o servidor inteiro parado.
    gc.collect()
    gc.freeze()
    gc.set_threshold(*config.GC_LIMIARES)
    gerenciador.iniciar()
    yield
    await gerenciador.parar()
    await sigaa_cache.cache.backend.fechar()
    await asyncio.to_thread(cpu.parar, esperar=True)


class Prazo:
    """Prazo total por requisição (ASGI puro): estourou, cancela a navegação e responde 504."""

    def __init__(self, app, segundos: float) -> None:
        self.app, self.segundos = app, segundos

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.segundos <= 0:
            return await self.app(scope, receive, send)
        iniciou = False

        async def enviar(msg):
            nonlocal iniciou
            iniciou = iniciou or msg["type"] == "http.response.start"
            await send(msg)

        try:
            async with asyncio.timeout(self.segundos):
                await self.app(scope, receive, enviar)
        except TimeoutError:
            if iniciou:
                raise
            msg = f"A consulta passou de {self.segundos:g} s (o SIGAA está lento). Tente de novo."
            await JSONResponse(status_code=504, content={"erro": {"codigo": "tempo_esgotado", "mensagem": msg}})(scope, receive, send)


app = FastAPI(
    title="SIGAA UFBA API (não oficial)",
    version=__version__,
    description=DESCRICAO,
    lifespan=lifespan,
    contact={"name": "sigaa-api", "url": "https://github.com/"},
    license_info={"name": "MIT"},
)
# limites de concorrência (anti-DoS por token/IP) — INNERMOST: um cache HIT (barato, não toca o
# SIGAA) passa livre; só as requisições que de fato vão trabalhar contam contra os tetos. As respostas
# 429/503 ainda saem pelo CORS (que é mais externo). Ver api/limites.py.
from . import limites as _limites  # noqa: E402

_limites.instalar(app)
# cache HTTP (L1) por DENTRO do CORS: o HIT sai com os cabeçalhos de CORS também
app.add_middleware(cache_http.CacheHTTP)
# gzip por FORA do cache: o cache comprime o que ele serve (e marca Content-Encoding, então o GZip
# deixa passar); o GZip pega as rotas que o cache não cobre. Por DENTRO ele quebrava: o cache guardava
# o corpo já comprimido sem o cabeçalho. JSON do histórico: 27 KB → 4,7 KB por ~0,2 ms de CPU
if config.GZIP_MIN_BYTES > 0:
    app.add_middleware(GZipMiddleware, minimum_size=config.GZIP_MIN_BYTES, compresslevel=5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cache", "Age", "X-Cache-Gerado-Em", "ETag"],
)
app.add_middleware(Prazo, segundos=config.TIMEOUT_REQUISICAO_S)

for nome in ROTAS:
    try:
        mod = importlib.import_module(f"api.routes.{nome}")
        app.include_router(mod.router)
    except ModuleNotFoundError as e:
        if e.name == f"api.routes.{nome}":
            log.warning("rotas '%s' ainda não existem — pulando", nome)
        else:
            raise

app.include_router(cache_http.router)
# cache compartilhado entre alunos (L2) nas funções de serviço de dado público
sigaa_cache.instalar()

STATUS = {
    E.CredenciaisInvalidas: 401,
    E.SessaoExpirada: 401,
    E.AcessoNegado: 403,
    E.NaoEncontrado: 404,
    E.NavegacaoInvalida: 502,
    E.SistemaIndisponivel: 503,
    E.SigaaError: 502,
}


@app.exception_handler(E.SigaaError)
async def erro_sigaa(_: Request, exc: E.SigaaError):
    status = next((s for cls, s in STATUS.items() if isinstance(exc, cls)), 502)
    headers = {"Retry-After": "5"} if isinstance(exc, E.SigaaOcupado) else None
    return JSONResponse(status_code=status, content={"erro": {"codigo": exc.codigo, "mensagem": str(exc)}}, headers=headers)


@app.exception_handler(ValueError)
async def erro_valor(_: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"erro": {"codigo": "requisicao_invalida", "mensagem": str(exc)}})


@app.exception_handler(Exception)
async def erro_geral(_: Request, exc: Exception):
    log.exception("erro não tratado")
    return JSONResponse(status_code=500, content={"erro": {"codigo": "erro_interno", "mensagem": "Erro interno da API."}})


from fastapi import HTTPException  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(HTTPException)
async def erro_http(_: Request, exc: HTTPException):
    det = exc.detail if isinstance(exc.detail, dict) else {"codigo": "erro", "mensagem": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"erro": det}, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def erro_validacao(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"erro": {"codigo": "requisicao_invalida", "mensagem": "Parâmetros inválidos.", "detalhes": exc.errors()}})


async def _sondar_sigaa() -> tuple[bool, int | None]:
    """Um GET no SIGAA pra ver se ele responde. Isolado pra poder ser cacheado/testado."""
    try:
        async with httpx.AsyncClient(timeout=10, verify=_ssl_ctx()) as h:
            r = await h.get(config.SIGAA_URL + "/sigaa/verTelaLogin.do")
            return r.status_code == 200, int(r.elapsed.total_seconds() * 1000)
    except httpx.HTTPError:
        return False, None


class _StatusSigaa:
    """Cacheia a sondagem do SIGAA por ``STATUS_CACHE_S`` s. /v1/status é PÚBLICO e sondava o SIGAA
    a cada chamada: um atacante repetindo /v1/status transformava a API num martelo contra a UFBA.
    O cache (com singleflight por trava) garante no máximo uma sondagem por janela, por mais
    chamadas simultâneas que cheguem."""

    def __init__(self) -> None:
        self._ts = 0.0
        self._val: tuple[bool, int | None] = (False, None)
        self._lock = asyncio.Lock()

    async def ler(self) -> tuple[bool, int | None]:
        import time as _t

        if config.STATUS_CACHE_S > 0 and _t.monotonic() - self._ts < config.STATUS_CACHE_S:
            return self._val
        async with self._lock:
            if config.STATUS_CACHE_S > 0 and _t.monotonic() - self._ts < config.STATUS_CACHE_S:
                return self._val
            self._val = await _sondar_sigaa()
            self._ts = _t.monotonic()
            return self._val


_status_sigaa = _StatusSigaa()


@app.get("/v1/status", tags=["Sistema"], summary="A API e o SIGAA estão no ar?")
async def status():
    sigaa_ok, ms = await _status_sigaa.ler()
    return {"api": "ok", "versao": __version__, "sigaa": {"url": config.SIGAA_URL, "no_ar": sigaa_ok, "latencia_ms": ms}, "sessoes_ativas": gerenciador.total,
            "servidor": {"processos_de_parse": cpu.ativo(), "conexoes_sigaa_em_uso": _em_voo(), "conexoes_sigaa_max": config.MAX_CONCORRENCIA_SIGAA}}


def _em_voo() -> int:
    lim = getattr(gerenciador, "_limite", None)  # o Carga (teto global) nasce com a 1ª sessão
    return lim.em_voo if lim is not None else 0


@app.get("/", include_in_schema=False)
async def raiz():
    return {"nome": "SIGAA UFBA API", "docs": "/docs", "status": "/v1/status"}
