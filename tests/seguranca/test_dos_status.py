"""DoS — /v1/status não pode virar um martelo contra o SIGAA real.

/v1/status é PÚBLICO (sem login) e faz um GET no SIGAA. Antes da correção cada chamada sondava o
SIGAA; um atacante repetindo /v1/status usava a API pra martelar a UFBA. Agora a sondagem fica em
cache por ``STATUS_CACHE_S`` s: N chamadas (mesmo simultâneas) = no máximo 1 sondagem por janela.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api.main import app


def test_status_cacheia_a_sondagem(monkeypatch):
    chamadas = {"n": 0}

    async def sondagem_fake():
        chamadas["n"] += 1
        return True, 42

    monkeypatch.setattr(main, "_sondar_sigaa", sondagem_fake)
    monkeypatch.setattr(main, "_status_sigaa", main._StatusSigaa())
    monkeypatch.setattr(main.config, "STATUS_CACHE_S", 60)

    cliente = TestClient(app)
    for _ in range(25):
        r = cliente.get("/v1/status")
        assert r.status_code == 200 and r.json()["sigaa"]["no_ar"] is True

    assert chamadas["n"] == 1, f"sondou o SIGAA {chamadas['n']}x (deveria sondar 1x e cachear)"


@pytest.mark.asyncio
async def test_status_singleflight_sob_concorrencia(monkeypatch):
    chamadas = {"n": 0}

    async def sondagem_lenta():
        chamadas["n"] += 1
        await asyncio.sleep(0.05)
        return True, 10

    monkeypatch.setattr(main, "_sondar_sigaa", sondagem_lenta)
    monkeypatch.setattr(main.config, "STATUS_CACHE_S", 60)
    st = main._StatusSigaa()

    resultados = await asyncio.gather(*[st.ler() for _ in range(20)])
    assert all(r == (True, 10) for r in resultados)
    assert chamadas["n"] == 1, f"{chamadas['n']} sondagens simultâneas (singleflight deveria deixar 1)"
