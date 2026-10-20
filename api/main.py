"""SIGAA UFBA API — servidor FastAPI.

Rodar:  uvicorn api.main:app --reload
Docs:   http://localhost:8000/docs  (Swagger)  ·  /redoc
"""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sigaa import errors as E
from sigaa import __version__

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
`muitas_tentativas` (429), `sigaa_erro` / `navegacao_invalida` (502), `sigaa_indisponivel` (503).
"""

#: módulos de rota (cada frente do projeto tem o seu); ausentes são ignorados com aviso
ROTAS = ["auth", "portal", "midia", "turma_virtual", "academico", "planejamento", "consultas"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    gerenciador.iniciar()
    yield
    await gerenciador.parar()


app = FastAPI(
    title="SIGAA UFBA API (não oficial)",
    version=__version__,
    description=DESCRICAO,
    lifespan=lifespan,
    contact={"name": "sigaa-api", "url": "https://github.com/"},
    license_info={"name": "MIT"},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for nome in ROTAS:
    try:
        mod = importlib.import_module(f"api.routes.{nome}")
        app.include_router(mod.router)
    except ModuleNotFoundError as e:
        if e.name == f"api.routes.{nome}":
            log.warning("rotas '%s' ainda não existem — pulando", nome)
        else:
            raise

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
    return JSONResponse(status_code=status, content={"erro": {"codigo": exc.codigo, "mensagem": str(exc)}})


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


@app.get("/v1/status", tags=["Sistema"], summary="A API e o SIGAA estão no ar?")
async def status():
    sigaa_ok, ms = False, None
    try:
        async with httpx.AsyncClient(timeout=10) as h:
            r = await h.get(config.SIGAA_URL + "/sigaa/verTelaLogin.do")
            sigaa_ok, ms = r.status_code == 200, int(r.elapsed.total_seconds() * 1000)
    except httpx.HTTPError:
        pass
    return {"api": "ok", "versao": __version__, "sigaa": {"url": config.SIGAA_URL, "no_ar": sigaa_ok, "latencia_ms": ms}, "sessoes_ativas": gerenciador.total}


@app.get("/", include_in_schema=False)
async def raiz():
    return {"nome": "SIGAA UFBA API", "docs": "/docs", "status": "/v1/status"}
