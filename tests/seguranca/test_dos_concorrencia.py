"""DoS — limites de concorrência da API (api/limites.py).

Prova que um token (ou IP) não consegue manter requisições demais em voo ao mesmo tempo (429) e que
o teto global protege a API inteira (503), sem o dicionário de contadores crescer sem limite.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from api.limites import Limites


def _app_lento(segundos: float):
    """App ASGI mínimo: dorme e responde 200 (simula uma rota que está trabalhando)."""

    async def app(scope, receive, send):
        await asyncio.sleep(segundos)
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


async def _rajada(mw: Limites, n: int, *, headers=None, path="/v1/historico") -> list[int]:
    transporte = httpx.ASGITransport(app=mw)
    async with httpx.AsyncClient(transport=transporte, base_url="http://t") as c:
        reqs = [c.get(path, headers=headers or {}) for _ in range(n)]
        respostas = await asyncio.gather(*reqs)
    return sorted(r.status_code for r in respostas)


@pytest.mark.asyncio
async def test_teto_por_token_rejeita_excesso():
    mw = Limites(_app_lento(0.15), por_token=2, por_ip=8, global_=0, espera_s=1)
    codigos = await _rajada(mw, 5, headers={"Authorization": "Bearer AAA"})
    assert codigos.count(200) == 2
    assert codigos.count(429) == 3


@pytest.mark.asyncio
async def test_tokens_diferentes_nao_se_atrapalham():
    mw = Limites(_app_lento(0.15), por_token=1, por_ip=8, global_=0, espera_s=1)
    transporte = httpx.ASGITransport(app=mw)
    async with httpx.AsyncClient(transport=transporte, base_url="http://t") as c:
        r = await asyncio.gather(
            c.get("/v1/historico", headers={"Authorization": "Bearer AAA"}),
            c.get("/v1/historico", headers={"Authorization": "Bearer BBB"}),
        )
    assert [x.status_code for x in r] == [200, 200]


@pytest.mark.asyncio
async def test_teto_global_devolve_503_com_retry_after():
    mw = Limites(_app_lento(0.2), por_token=0, por_ip=0, global_=2, espera_s=0.05)
    transporte = httpx.ASGITransport(app=mw)
    async with httpx.AsyncClient(transport=transporte, base_url="http://t") as c:
        respostas = await asyncio.gather(*[c.get("/v1/historico") for _ in range(4)])
    codigos = sorted(r.status_code for r in respostas)
    assert codigos.count(200) == 2
    assert codigos.count(503) == 2
    ocupado = next(r for r in respostas if r.status_code == 503)
    assert ocupado.headers.get("Retry-After") == "5"
    assert ocupado.json()["erro"]["codigo"] == "sigaa_ocupado"


@pytest.mark.asyncio
async def test_status_e_isento():
    mw = Limites(_app_lento(0.15), por_token=1, por_ip=1, global_=0, espera_s=1)
    codigos = await _rajada(mw, 4, path="/v1/status")
    assert codigos == [200, 200, 200, 200]


@pytest.mark.asyncio
async def test_contadores_nao_vazam():
    mw = Limites(_app_lento(0.0), por_token=4, por_ip=4, global_=0, espera_s=1)
    await _rajada(mw, 6, headers={"Authorization": "Bearer AAA"})
    assert mw._contadores == {}, "contador deveria ser removido ao zerar (sem crescimento de memória)"
