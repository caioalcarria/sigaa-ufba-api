"""Proxy autenticado das fotos do SIGAA (elas só abrem com a sessão do aluno)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from ..config import config
from ..deps import Cliente
from ..seguranca_http import foto_canonica, tipo_imagem

router = APIRouter(prefix="/v1", tags=["portal"])


@router.get(
    "/fotos",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
    summary="Abrir uma foto do SIGAA (perfil, participantes)",
    description="Recebe o `foto_url` que outras rotas devolvem (`/shared/verFoto?idFoto=..&key=..`, relativo ou no próprio SIGAA) "
    "e baixa a imagem com a sessão do aluno. Qualquer outro endereço é recusado com 422.",
)
async def foto(cli: Cliente, url: Annotated[str, Query(max_length=512)]):
    # nada do que veio é repassado cru: o caminho é remontado (só /shared/verFoto com idFoto e key validados),
    # senão o proxy viraria um GET com a sessão do aluno em QUALQUER tela do SIGAA (logoff, ações JSF por GET...)
    caminho = foto_canonica(url, cli.base_url)
    if caminho is None:
        raise HTTPException(422, detail={"codigo": "requisicao_invalida", "mensagem": "Isto não é um endereço de foto do SIGAA (/shared/verFoto?idFoto=..&key=..)."})
    page = await cli.executar(lambda c: c.get(caminho))
    tipo = tipo_imagem(page.content_type)
    if tipo is None:  # SVG/HTML no domínio da API = script; só imagem raster passa
        raise HTTPException(404, detail={"codigo": "nao_encontrado", "mensagem": "O SIGAA não devolveu uma imagem."})
    if config.FOTO_MAX_BYTES > 0 and len(page.content) > config.FOTO_MAX_BYTES:
        raise HTTPException(502, detail={"codigo": "sigaa_erro", "mensagem": "A foto do SIGAA passa do tamanho máximo."})
    return Response(page.content, media_type=tipo, headers={"Cache-Control": "private, max-age=3600"})
