"""SEG·SEGREDOS — ``/v1/status`` (sem login): não vira amplificador de requisição ao SIGAA e não expõe
os contadores internos (sessões ativas, conexões em uso, processos) a qualquer um por padrão.

Sem rede: a sonda do SIGAA é trocada por uma falsa."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as m
from api.config import config

CAMPOS = {"api", "versao", "sigaa", "sessoes_ativas", "servidor"}


@pytest.fixture
def sonda(monkeypatch):
    chamadas = []

    async def falsa():
        chamadas.append(1)
        return True, 42

    monkeypatch.setattr(config, "SIGAA_URL", "http://127.0.0.1:9")  # nunca o SIGAA real
    monkeypatch.setattr(m, "_sondar_sigaa", falsa)
    monkeypatch.setattr(m, "_SONDA", {"quando": float("-inf"), "valor": (False, None), "tarefa": None})
    return chamadas


def test_rajada_no_status_nao_vira_rajada_no_sigaa(sonda, monkeypatch):
    monkeypatch.setattr(config, "STATUS_CACHE_S", 30.0)
    c = TestClient(m.app)
    for _ in range(20):
        r = c.get("/v1/status")
        assert r.status_code == 200 and r.json()["sigaa"]["no_ar"] is True
    assert len(sonda) == 1


def test_contadores_internos_escondidos_por_padrao(sonda, monkeypatch):
    monkeypatch.setattr(config, "STATUS_DETALHADO", False)
    j = TestClient(m.app).get("/v1/status").json()
    assert set(j) == CAMPOS  # o contrato (os campos) não muda
    assert j["sessoes_ativas"] is None
    assert set(j["servidor"]) == {"processos_de_parse", "conexoes_sigaa_em_uso", "conexoes_sigaa_max"}
    assert all(v is None for v in j["servidor"].values())


def test_detalhado_liga_os_contadores(sonda, monkeypatch):
    monkeypatch.setattr(config, "STATUS_DETALHADO", True)
    j = TestClient(m.app).get("/v1/status").json()
    assert isinstance(j["sessoes_ativas"], int) and isinstance(j["servidor"]["conexoes_sigaa_max"], int)


def test_padroes_da_config():
    from api.config import Config

    assert Config.STATUS_DETALHADO is False and Config.STATUS_CACHE_S > 0
