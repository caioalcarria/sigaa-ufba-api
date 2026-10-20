"""Dependências do FastAPI: resolve a autenticação na sessão SIGAA do aluno.

Aceita dois jeitos:
* ``Authorization: Bearer <token>`` — o token de ``POST /v1/auth/login`` (recomendado);
* ``Authorization: Basic base64(usuario:senha)`` — atalho pra scripts (``curl -u``): a API
  cria/reaproveita uma sessão pra essa credencial. DESLIGADO por padrão (a senha vai em toda
  requisição); religue com SIGAA_API_PERMITIR_BASIC=true.
"""

from __future__ import annotations

import base64
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBearer

from sigaa.client import SigaaClient

from .config import config
from .sessions import MuitasTentativas, Sessao, gerenciador

bearer = HTTPBearer(auto_error=False, description="Token devolvido por POST /v1/auth/login")
basic = HTTPBasic(auto_error=False, description="Usuário e senha do SIGAA (atalho pra scripts)")


MSG_MUITAS = "Muitas tentativas de login. Espere alguns minutos."


def _erro(status: int, codigo: str, mensagem: str) -> HTTPException:
    return HTTPException(status, detail={"codigo": codigo, "mensagem": mensagem})


async def _sessao(
    request: Request,
    _b: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> Sessao:
    auth = request.headers.get("authorization") or ""
    esquema, _, valor = auth.partition(" ")
    esquema = esquema.lower()
    if esquema == "bearer" and valor:
        sess = await gerenciador.obter(valor.strip())
        if sess is None:
            raise _erro(401, "token_invalido", "Token inválido ou expirado. Faça login de novo em POST /v1/auth/login.")
        return sess
    if esquema == "basic" and valor and config.PERMITIR_BASIC:
        from .login_seguro import https_ok

        if not https_ok(request.url.scheme, request.client.host if request.client else None):
            raise _erro(403, "https_obrigatorio", "A senha só pode ser enviada por HTTPS (fora do próprio servidor).")
        try:
            usuario, sep, senha = base64.b64decode(valor.strip(), validate=True).decode("utf-8").partition(":")
        except Exception:  # noqa: BLE001 - sem encadear: o traceback teria a credencial
            raise _erro(401, "basic_invalido", "Authorization Basic malformado.") from None
        if not sep or not usuario:
            raise _erro(401, "basic_invalido", "Authorization Basic malformado.")
        ip = request.client.host if request.client else "?"
        try:
            return await gerenciador.obter_basic(usuario, senha, ip=ip)
        except MuitasTentativas:
            raise _erro(429, "muitas_tentativas", MSG_MUITAS) from None
    raise _erro(401, "nao_autenticado", "Envie Authorization: Bearer <token> (de POST /v1/auth/login).")


async def _cliente(sess: Annotated[Sessao, Depends(_sessao)]) -> SigaaClient:
    return sess.cliente


SessaoAtual = Annotated[Sessao, Depends(_sessao)]
Cliente = Annotated[SigaaClient, Depends(_cliente)]
