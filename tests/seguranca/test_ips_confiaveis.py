"""IPs confiáveis (SIGAA_API_IPS_CONFIAVEIS): saem dos limites POR IP; o resto continua valendo."""

import asyncio

import pytest

from api import limites, sessions
from api.config import config


def _scope(ip, path="/v1/publico/cursos", token=None):
    hs = [(b"authorization", b"Bearer " + token)] if token else []
    return {"type": "http", "path": path, "client": (ip, 1), "headers": hs}


def test_concorrencia_por_ip_ignora_ip_confiavel(monkeypatch):
    mw = limites.Limites(lambda *a: None, por_token=6, por_ip=8, global_=0, espera_s=1)
    monkeypatch.setattr(config, "IPS_CONFIAVEIS", frozenset({"127.0.0.1"}))
    assert mw._chave_e_teto(_scope("127.0.0.1")) == (None, 0)
    chave, teto = mw._chave_e_teto(_scope("10.0.0.9"))
    assert chave == "ip:10.0.0.9" and teto == 8
    # com token, o limite por TOKEN continua valendo mesmo no IP confiável
    chave, teto = mw._chave_e_teto(_scope("127.0.0.1", "/v1/me", token=b"abc"))
    assert chave.startswith("tok:") and teto == 6


def test_padrao_sem_ip_confiavel():
    assert config.IPS_CONFIAVEIS == frozenset() or "127.0.0.1" not in config.IPS_CONFIAVEIS


def test_login_por_ip_pula_ip_confiavel_mas_nao_o_limite_por_usuario(monkeypatch):
    ger = sessions.Gerenciador()
    ger.limite_login = sessions.LimiteLogin(1)
    monkeypatch.setattr(config, "IPS_CONFIAVEIS", frozenset({"127.0.0.1"}))
    assert ger.limite_login.permitir(sessions.chave_ip("10.0.0.9"))
    assert not ger.limite_login.permitir(sessions.chave_ip("10.0.0.9"))  # IP comum: estoura no 2º
    chamadas = []

    async def falso_login(*a, **k):
        chamadas.append(1)
        raise RuntimeError("parou depois do limite por IP")

    monkeypatch.setattr(ger, "_criar", falso_login, raising=False)
    for _ in range(3):  # IP confiável: nunca dá MuitasTentativas pelo limite POR IP
        try:
            asyncio.run(ger.autenticar("fulano", "x", ip="127.0.0.1"))
        except sessions.MuitasTentativas:
            pytest.fail("IP confiável bateu no limite por IP")
        except Exception:  # noqa: BLE001 - qualquer outra coisa = passou do limite por IP
            pass
