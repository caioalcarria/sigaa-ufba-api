"""``?fresco=true`` em laço furava o cache e martelava o SIGAA (o teto por token só limita o paralelo).
Agora cada aluno (ou IP, nas rotas públicas) tem ``SIGAA_API_MAX_FRESCO_POR_MIN`` bypasses por minuto;
passou, o pedido é servido do cache como um pedido normal — o contrato não muda."""

from __future__ import annotations

import pytest

from tests.seguranca.test_isolamento_cache import A, B, _app, _cli, _middleware, limpo  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_fresco_em_laco_nao_martela_o_sigaa():
    ch: dict[str, int] = {}
    app = _app(ch)
    async with _cli(app) as c:
        await c.get("/v1/eco", headers=A)  # MISS: grava
        _middleware(app).max_fresco = 3
        estados = [(await c.get("/v1/eco?fresco=true", headers=A)).headers["x-cache"] for _ in range(10)]
    assert estados[:3] == ["BYPASS"] * 3
    assert set(estados[3:]) == {"HIT"}, estados
    assert ch["eco"] == 1 + 3, "passou do teto e ainda foi ao SIGAA"


async def test_teto_de_fresco_e_por_aluno():
    ch: dict[str, int] = {}
    app = _app(ch)
    async with _cli(app) as c:
        await c.get("/v1/eco", headers=A)
        await c.get("/v1/eco", headers=B)
        _middleware(app).max_fresco = 1
        assert (await c.get("/v1/eco?fresco=true", headers=A)).headers["x-cache"] == "BYPASS"
        assert (await c.get("/v1/eco?fresco=true", headers=A)).headers["x-cache"] == "HIT"
        assert (await c.get("/v1/eco?fresco=true", headers=B)).headers["x-cache"] == "BYPASS"


async def test_teto_de_fresco_no_publico_por_ip_e_desligavel():
    ch: dict[str, int] = {}
    app = _app(ch)
    async with _cli(app) as c:
        await c.get("/v1/publico/eco")
        m = _middleware(app)
        m.max_fresco = 2
        estados = [(await c.get("/v1/publico/eco?fresco=1")).headers["x-cache"] for _ in range(4)]
        assert estados == ["BYPASS", "BYPASS", "HIT", "HIT"]
        m.max_fresco = 0
        assert (await c.get("/v1/publico/eco?fresco=1")).headers["x-cache"] == "BYPASS"
