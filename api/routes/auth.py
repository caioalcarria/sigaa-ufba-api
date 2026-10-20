"""Login, sessão e logout."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, model_validator

from ..config import config
from ..deps import MSG_MUITAS, SessaoAtual
from ..login_seguro import CifradoInvalido, chaveiro, https_ok
from ..sessions import MuitasTentativas, gerenciador

router = APIRouter(prefix="/v1/auth", tags=["Autenticação"])

MSG_HTTPS = "A senha só pode ser enviada por HTTPS (fora do próprio servidor). Use https:// — ver docs/seguranca/README.md."


class LoginRequest(BaseModel):
    usuario: str = Field(description="Login do SIGAA (o mesmo da tela de login). Dispensado com `cifrado`.", examples=["fulano.tal"])
    senha: SecretStr = Field(description="Senha do SIGAA. Nunca é gravada; com `lembrar` fica cifrada só na memória do servidor. Dispensada com `cifrado`.")
    cifrado: SecretStr | None = Field(
        None,
        description="Alternativa a `usuario`+`senha`: base64 de RSA-OAEP-SHA256 do JSON `{\"usuario\",\"senha\",\"ts\"}` "
        "com a chave de `GET /v1/auth/chave` (`ts` = segundos desde 1970; vale 5 min e uma vez só).",
    )
    lembrar: bool = Field(
        False,
        description="Se true, a API reloga sozinha quando o SIGAA derrubar a sessão por inatividade (~30 min). "
        "Sem isso, a resposta vira 401 `sessao_expirada` e o cliente precisa logar de novo.",
    )

    @model_validator(mode="before")
    @classmethod
    def _cifrado_dispensa(cls, v):
        # com `cifrado`, usuario/senha vêm de dentro do envelope (o erro de campo faltando continua igual sem ele)
        if isinstance(v, dict) and v.get("cifrado") is not None:
            v = {**v, "usuario": v.get("usuario") or "-", "senha": v.get("senha") or "-"}
        return v


class SessaoInfo(BaseModel):
    token: str | None = Field(None, description="Use em `Authorization: Bearer <token>`. Só aparece na resposta do login.")
    tipo: str = "Bearer"
    criada_em: datetime
    expira_em: datetime = Field(description="Validade máxima do token.")
    ocioso_expira_em_min: float = Field(description="O token morre se ficar esse tempo sem uso.")
    lembrar: bool
    sigaa_logado: bool = Field(description="Se a sessão no SIGAA está ativa neste momento.")


def _info(sess, token: str | None = None) -> SessaoInfo:
    return SessaoInfo(
        token=token,
        criada_em=datetime.fromtimestamp(sess.criada_em, timezone.utc),
        expira_em=datetime.fromtimestamp(sess.expira_em, timezone.utc),
        ocioso_expira_em_min=config.TOKEN_OCIOSO_MIN,
        lembrar=sess.lembrar,
        sigaa_logado=sess.cliente.logado,
    )


@router.post(
    "/login",
    response_model=SessaoInfo,
    summary="Entrar com usuário e senha do SIGAA",
    description="Faz login no SIGAA (atravessa a tela de avisos e a escolha de vínculo) e devolve um token opaco. "
    "Erros: 401 `credenciais_invalidas`, 429 `muitas_tentativas`, 503 `sigaa_indisponivel`.",
    responses={401: {"description": "Usuário e/ou senha inválidos"}, 429: {"description": "Muitas tentativas"}},
)
async def login(corpo: LoginRequest, request: Request):
    ip = request.client.host if request.client else "?"
    if not https_ok(request.url.scheme, ip):
        raise HTTPException(403, detail={"codigo": "https_obrigatorio", "mensagem": MSG_HTTPS})
    if corpo.cifrado is not None:
        if not config.LOGIN_CIFRADO:
            raise HTTPException(422, detail={"codigo": "requisicao_invalida", "mensagem": "Login cifrado desligado neste servidor."})
        try:
            usuario, senha = chaveiro.abrir(corpo.cifrado.get_secret_value())
        except CifradoInvalido as e:
            raise HTTPException(422, detail={"codigo": "cifrado_invalido", "mensagem": str(e)}) from None
    else:
        usuario, senha = corpo.usuario, corpo.senha.get_secret_value()
    try:
        token, sess = await gerenciador.autenticar(usuario, senha, ip=ip, lembrar=corpo.lembrar)
    except MuitasTentativas:  # por IP ou por usuário: a mesma resposta (não revela qual)
        raise HTTPException(429, detail={"codigo": "muitas_tentativas", "mensagem": MSG_MUITAS}) from None
    return _info(sess, token)


@router.get(
    "/chave",
    summary="Chave pública pra cifrar o corpo do login (opcional)",
    description="RSA 2048 gerada no boot (muda a cada reinício). Cifre `{\"usuario\",\"senha\",\"ts\"}` com RSA-OAEP-SHA256 e "
    "mande `{\"cifrado\": base64}` em POST /v1/auth/login. Protege a senha de quem vê o corpo depois do TLS; não do dono do servidor.",
)
async def chave():
    if not config.LOGIN_CIFRADO:
        raise HTTPException(404, detail={"codigo": "nao_encontrado", "mensagem": "Login cifrado desligado neste servidor."})
    return chaveiro.publica()


@router.get("/sessao", response_model=SessaoInfo, summary="Ver a sessão atual (validade, se o SIGAA ainda está logado)")
async def ver_sessao(sess: SessaoAtual):
    return _info(sess)


@router.post("/renovar", response_model=SessaoInfo, summary="Tocar o SIGAA pra sessão não expirar")
async def renovar(sess: SessaoAtual):
    async with sess.cliente.lock:
        await sess.cliente.manter_viva()
    return _info(sess)


@router.delete("/sessao", status_code=204, summary="Sair (logout no SIGAA e invalida o token)")
async def logout(sess: SessaoAtual):
    # pela própria sessão: vale pro token e pro Basic (antes, no Basic, só deslogava do SIGAA e a sessão
    # — com a senha cifrada — continuava viva). Esquece a credencial e fecha o pool inteiro.
    await gerenciador.encerrar_sessao(sess)
