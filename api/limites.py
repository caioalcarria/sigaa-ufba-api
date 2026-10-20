"""Limites de concorrência da API (defesa contra DoS por abuso de um token ou de um IP).

O teto global de requisições ao SIGAA (``sigaa.client.Carga`` / ``MAX_CONCORRENCIA_SIGAA``) protege o
SIGAA, mas NÃO impede que:

* um único token (aluno) dispare dezenas de requisições em paralelo e consuma sozinho todo o budget
  global, deixando os demais alunos na fila (starvation);
* um IP anônimo martele as rotas públicas ``/v1/publico/*`` (sem login) em paralelo;
* o próprio processo da API fique sem fôlego (event loop, memória) com requisições demais em voo.

Este middleware ASGI aplica, ANTES de a requisição tocar o SIGAA:

* **por token** (ou por IP nas rotas sem login): no máximo ``POR_TOKEN`` requisições em voo ao mesmo
  tempo; excedeu → **429 ``muitas_tentativas``** na hora (sem enfileirar — falha rápido e barato);
* **por IP nas rotas públicas**: no máximo ``POR_IP`` em voo;
* **global**: no máximo ``GLOBAL`` requisições em voo na API; a mais espera uma vaga por ``ESPERA_S``
  e, se não vier, **503 ``sigaa_ocupado``** com ``Retry-After`` (mesma semântica do teto do SIGAA).

Os contadores por chave são removidos quando zeram, então o dicionário não cresce sem limite.
Tudo configurável por ``api.config`` (variáveis ``SIGAA_API_CONC_*``); ``0`` desliga cada teto.
"""

from __future__ import annotations

import asyncio
import hashlib

from starlette.responses import JSONResponse

from .config import config

#: caminhos que não passam pelos tetos (saúde/infra; são baratos e não tocam o SIGAA logado)
ISENTOS = ("/", "/v1/status", "/docs", "/redoc", "/openapi.json")


def _resposta(status: int, codigo: str, msg: str, retry: int | None = None):
    headers = {"Retry-After": str(retry)} if retry is not None else None
    return JSONResponse(status_code=status, content={"erro": {"codigo": codigo, "mensagem": msg}}, headers=headers)


class _Contador:
    """Requisições em voo de uma chave. Sem lock: em asyncio de 1 thread, checar-e-incrementar
    sem ``await`` no meio é atômico."""

    __slots__ = ("n",)

    def __init__(self) -> None:
        self.n = 0


class Limites:
    def __init__(self, app, *, por_token: int, por_ip: int, global_: int, espera_s: float) -> None:
        self.app = app
        self.por_token = por_token
        self.por_ip = por_ip
        self.espera_s = espera_s
        self._contadores: dict[str, _Contador] = {}
        self._global = asyncio.Semaphore(global_) if global_ > 0 else None

    # ---- chave e teto da requisição --------------------------------------
    def _chave_e_teto(self, scope) -> tuple[str | None, int]:
        caminho = scope.get("path", "")
        token = None
        for nome, valor in scope.get("headers", []):
            if nome == b"authorization" and valor[:7].lower() == b"bearer ":
                token = valor[7:].strip()
                break
        if token:
            return "tok:" + hashlib.sha256(token).hexdigest()[:16], self.por_token
        ip = (scope.get("client") or ("desconhecido", 0))[0]
        if caminho.startswith("/v1/publico"):
            return "ip:" + ip, self.por_ip
        # rotas logadas sem Bearer (ex.: Basic, login): limita por IP com o teto de token
        return "ip:" + ip, self.por_token

    def _tentar_entrar(self, chave: str, teto: int) -> bool:
        if teto <= 0:
            return True
        c = self._contadores.get(chave)
        if c is None:
            c = self._contadores[chave] = _Contador()
        if c.n >= teto:
            return False
        c.n += 1
        return True

    def _sair(self, chave: str, teto: int) -> None:
        if teto <= 0:
            return
        c = self._contadores.get(chave)
        if c is None:
            return
        c.n -= 1
        if c.n <= 0:
            self._contadores.pop(chave, None)

    # ---- ASGI ------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") in ISENTOS:
            return await self.app(scope, receive, send)

        chave, teto = self._chave_e_teto(scope)
        if not self._tentar_entrar(chave, teto):
            return await _resposta(
                429, "muitas_tentativas",
                "Você tem requisições demais em andamento ao mesmo tempo; aguarde uma terminar.",
            )(scope, receive, send)
        try:
            if self._global is None:
                return await self.app(scope, receive, send)
            try:
                await asyncio.wait_for(self._global.acquire(), self.espera_s)
            except (TimeoutError, asyncio.TimeoutError):
                return await _resposta(
                    503, "sigaa_ocupado",
                    "A API está no limite de requisições simultâneas; tente de novo em instantes.",
                    retry=5,
                )(scope, receive, send)
            try:
                return await self.app(scope, receive, send)
            finally:
                self._global.release()
        finally:
            self._sair(chave, teto)


def instalar(app) -> None:
    """Registra o middleware se algum teto estiver ligado. Chamado por ``api.main``."""
    if config.CONC_POR_TOKEN <= 0 and config.CONC_POR_IP <= 0 and config.CONC_GLOBAL <= 0:
        return
    app.add_middleware(
        Limites,
        por_token=config.CONC_POR_TOKEN,
        por_ip=config.CONC_POR_IP,
        global_=config.CONC_GLOBAL,
        espera_s=config.CONC_ESPERA_S,
    )
