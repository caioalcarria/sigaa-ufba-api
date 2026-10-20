"""Configuração comum dos testes."""

import pytest


@pytest.fixture(autouse=True)
def _http_puro_nos_testes(monkeypatch):
    """O TestClient fala HTTP de um cliente "testclient" (não é loopback): sem isto, a regra de HTTPS
    obrigatório fora do localhost (SIGAA_API_EXIGIR_HTTPS=auto) recusaria todo login dos testes antigos.
    Os testes dessa regra (tests/seguranca/test_auth_transporte.py) voltam pro "auto"."""
    from api.config import config

    monkeypatch.setattr(config, "EXIGIR_HTTPS", "false")
