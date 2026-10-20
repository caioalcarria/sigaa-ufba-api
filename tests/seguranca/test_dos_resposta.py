"""DoS — teto de bytes por resposta do SIGAA (resposta gigante / bomba de descompressão do upstream).

Antes da correção o ``SigaaClient`` lia ``r.content`` inteiro: um upstream comprometido/MITM podia
devolver um corpo enorme ou um gzip "bomba" (poucos KB → vários GB) e estourar a memória da API.
Agora o corpo é lido em streaming e abortado assim que passa do teto (``SIGAA_MAX_RESP_*_MB``).
"""

from __future__ import annotations

import gzip

import httpx
import pytest

from sigaa.client import MAX_RESP_HTML, RespostaGrandeDemais, SigaaClient


def _transporte(corpo: bytes, headers: dict[str, str] | None = None) -> httpx.MockTransport:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=corpo, headers=headers or {"content-type": "text/html"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_resposta_normal_passa():
    corpo = b"<html><body>ok</body></html>"
    c = SigaaClient("http://sigaa.test", transport=_transporte(corpo), min_interval=0, folga=0)
    try:
        page = await c.get("/qualquer", verificar=False)
        assert page.content == corpo
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_resposta_gigante_e_recusada():
    # 2 MB acima do teto de HTML, servido sem compressão: a leitura aborta sem materializar o resto
    corpo = b"A" * (MAX_RESP_HTML + 2 * 1024 * 1024)
    c = SigaaClient("http://sigaa.test", transport=_transporte(corpo), min_interval=0, folga=0)
    try:
        with pytest.raises(RespostaGrandeDemais):
            await c.get("/historico.pdf", verificar=False)
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_bomba_de_descompressao_e_recusada():
    # ~400 KB comprimidos que viram ~400 MB descomprimidos: o cap conta os bytes DESCOMPRIMIDOS
    bruto = b"\0" * (400 * 1024 * 1024)
    bomba = gzip.compress(bruto)
    assert len(bomba) < 1 * 1024 * 1024  # a "bomba" em si é pequena
    headers = {"content-type": "text/html", "content-encoding": "gzip"}
    c = SigaaClient("http://sigaa.test", transport=_transporte(bomba, headers), min_interval=0, folga=0)
    try:
        with pytest.raises(RespostaGrandeDemais):
            await c.get("/portal", verificar=False)
    finally:
        await c.close()
