"""Transporte da senha no login: HTTPS obrigatório fora do localhost, corpo cifrado opcional
(GET /v1/auth/chave) e o corpo do login nunca no log."""

from __future__ import annotations

import base64
import json
import logging
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from api import login_seguro as L
from api.config import config
from api.main import app
from api.sessions import gerenciador
from sigaa.errors import CredenciaisInvalidas

SENHA = "Senha-Secreta-9137"


@pytest.fixture
def capturado(monkeypatch):
    """Login sem SIGAA: autenticar só registra o que recebeu (ou recusa a senha 'errada')."""
    visto: list = []

    async def autenticar(usuario, senha, *, ip="?", lembrar=False, origem="token"):
        visto.append((usuario, senha))
        if senha == "errada":
            raise CredenciaisInvalidas("Usuário e/ou senha inválidos.")
        raise RuntimeError("parou aqui (teste)")  # vira 500 genérico — e passa pelo log.exception

    monkeypatch.setattr(gerenciador, "autenticar", autenticar)
    return visto


def _cli(base="http://testserver", ip="203.0.113.9"):
    return TestClient(app, base_url=base, client=(ip, 50000), raise_server_exceptions=False)


def _cifrar(dados: dict, pem: str | None = None) -> str:
    pem = pem or _cli().get("/v1/auth/chave").json()["chave_publica_pem"]
    pub = serialization.load_pem_public_key(pem.encode())
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    return base64.b64encode(pub.encrypt(json.dumps(dados).encode(), oaep)).decode()


# ------------------------------------------------------------------ HTTPS
def test_login_por_http_de_fora_do_localhost_e_recusado_sem_ler_a_senha(monkeypatch, capturado):
    monkeypatch.setattr(config, "EXIGIR_HTTPS", "auto")
    r = _cli().post("/v1/auth/login", json={"usuario": "a", "senha": SENHA})
    assert r.status_code == 403 and r.json()["erro"]["codigo"] == "https_obrigatorio"
    assert capturado == [], "a senha não pode nem chegar ao SIGAA"


@pytest.mark.parametrize("ip", ["127.0.0.1", "::1"])
def test_login_por_http_do_localhost_passa(monkeypatch, capturado, ip):
    monkeypatch.setattr(config, "EXIGIR_HTTPS", "auto")
    _cli(ip=ip).post("/v1/auth/login", json={"usuario": "a", "senha": SENHA})
    assert capturado == [("a", SENHA)]


def test_login_por_https_passa_e_modo_true_recusa_ate_localhost(monkeypatch, capturado):
    monkeypatch.setattr(config, "EXIGIR_HTTPS", "auto")
    _cli(base="https://testserver").post("/v1/auth/login", json={"usuario": "a", "senha": SENHA})
    assert capturado == [("a", SENHA)]
    monkeypatch.setattr(config, "EXIGIR_HTTPS", "true")
    assert _cli(ip="127.0.0.1").post("/v1/auth/login", json={"usuario": "a", "senha": SENHA}).status_code == 403


def test_basic_por_http_de_fora_e_recusado(monkeypatch):
    monkeypatch.setattr(config, "EXIGIR_HTTPS", "auto")
    monkeypatch.setattr(config, "PERMITIR_BASIC", True)
    b = base64.b64encode(f"a:{SENHA}".encode()).decode()
    r = _cli().get("/v1/me", headers={"Authorization": f"Basic {b}"})
    assert r.status_code == 403 and r.json()["erro"]["codigo"] == "https_obrigatorio"


# ------------------------------------------------------------------ corpo cifrado
def test_chave_publica_e_login_cifrado(capturado):
    k = _cli().get("/v1/auth/chave").json()
    assert k["alg"] == "RSA-OAEP-256" and "PRIVATE" not in k["chave_publica_pem"]
    _cli().post("/v1/auth/login", json={"cifrado": _cifrar({"usuario": "fulano", "senha": SENHA, "ts": time.time()}, k["chave_publica_pem"])})
    assert capturado == [("fulano", SENHA)]


def test_login_cifrado_vencido_repetido_ou_lixo_e_recusado_com_mensagem_unica(capturado):
    velho = _cifrar({"usuario": "a", "senha": SENHA, "ts": time.time() - 3600})
    bom = _cifrar({"usuario": "a", "senha": SENHA, "ts": time.time()})
    c = _cli()
    respostas = [
        c.post("/v1/auth/login", json={"cifrado": velho}),
        c.post("/v1/auth/login", json={"cifrado": "AAAA"}),
        c.post("/v1/auth/login", json={"cifrado": base64.b64encode(b"x" * 256).decode()}),
    ]
    c.post("/v1/auth/login", json={"cifrado": bom})  # 1ª vez: aceito
    respostas.append(c.post("/v1/auth/login", json={"cifrado": bom}))  # replay
    assert {r.status_code for r in respostas} == {422}
    assert len({r.json()["erro"]["mensagem"] for r in respostas}) == 1
    assert capturado == [("a", SENHA)], "só o envelope bom, uma vez"


def test_login_cifrado_desligavel(monkeypatch, capturado):
    monkeypatch.setattr(config, "LOGIN_CIFRADO", False)
    assert _cli().get("/v1/auth/chave").status_code == 404
    assert _cli().post("/v1/auth/login", json={"cifrado": "AAAA"}).status_code == 422


# ------------------------------------------------------------------ log
def test_corpo_do_login_nunca_vai_pro_log(caplog, capturado):
    caplog.set_level(logging.DEBUG)
    c = _cli()
    c.post("/v1/auth/login", json={"usuario": "a", "senha": SENHA})  # 500 genérico (log.exception)
    c.post("/v1/auth/login", json={"usuario": "a", "senha": "errada"})  # recusado
    c.post("/v1/auth/login", json={"senha": SENHA})  # 422
    c.post("/v1/auth/login", content=b'{"usuario": "a", "senha": "' + SENHA.encode() + b'"', headers={"content-type": "application/json"})  # JSON quebrado
    env = _cifrar({"usuario": "a", "senha": SENHA, "ts": time.time()})
    c.post("/v1/auth/login", json={"cifrado": env})
    texto = "\n".join(caplog.text.splitlines() + [r.getMessage() for r in caplog.records])
    assert any(r.levelno >= logging.ERROR for r in caplog.records), "o caminho do log.exception foi exercitado"
    assert SENHA not in texto and env not in texto and env[:40] not in texto
