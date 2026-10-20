"""Proxy autenticado das fotos do SIGAA (elas só abrem com a sessão do aluno)."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Response

from ..deps import Cliente

router = APIRouter(prefix="/v1", tags=["portal"])


@router.get(
    "/fotos",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
    summary="Abrir uma foto do SIGAA (perfil, participantes)",
    description="Recebe o `foto_url` que outras rotas devolvem e baixa a imagem com a sessão do aluno. Só aceita caminhos de foto do próprio SIGAA.",
)
async def foto(cli: Cliente, url: str):
    alvo = urlparse(url)
    if alvo.netloc and alvo.netloc != urlparse(cli.base_url).netloc:
        raise HTTPException(422, detail={"codigo": "requisicao_invalida", "mensagem": "Só fotos do próprio SIGAA."})
    caminho = alvo.path + (f"?{alvo.query}" if alvo.query else "")
    if not (alvo.path.startswith("/shared/verFoto") or alvo.path.startswith("/sigaa/") and "foto" in alvo.path.lower()):
        raise HTTPException(422, detail={"codigo": "requisicao_invalida", "mensagem": "Isto não é um endereço de foto do SIGAA."})
    page = await cli.executar(lambda c: c.get(caminho))
    if not page.content_type.startswith("image/"):
        raise HTTPException(404, detail={"codigo": "nao_encontrado", "mensagem": "O SIGAA não devolveu uma imagem."})
    return Response(page.content, media_type=page.content_type, headers={"Cache-Control": "private, max-age=3600"})
