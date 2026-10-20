"""SEG·HTTP — limites da requisição e métodos: corpo (413), URL (414), cabeçalhos (431), TRACE/TRACK (405).

Antes: login aceitava corpo de qualquer tamanho (o pydantic lia tudo pra memória), URL e cabeçalhos só tinham
o teto do servidor HTTP, e TRACE/TRACK caíam no roteador.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.config import config
from api.main import app

cliente = TestClient(app, raise_server_exceptions=False)


def test_corpo_grande_413_com_content_length():
    r = cliente.post("/v1/auth/login", content=b'{"usuario":"a","senha":"' + b"x" * (config.MAX_CORPO_BYTES + 10) + b'"}', headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["erro"]["codigo"] == "corpo_grande"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_corpo_grande_413_chunked():
    def pedacos():
        yield b'{"usuario":"a","senha":"'
        for _ in range(config.MAX_CORPO_BYTES // 1024 + 2):
            yield b"x" * 1024
        yield b'"}'

    r = cliente.post("/v1/auth/login", content=pedacos(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_corpo_pequeno_chunked_chega_inteiro():
    """O corpo lido pra contar é reapresentado à app: a validação vê o JSON completo."""

    def pedacos():
        yield b'{"usuario":'
        yield b'"a"}'

    r = cliente.post("/v1/auth/login", content=pedacos(), headers={"content-type": "application/json"})
    assert r.status_code == 422  # falta a senha: o JSON chegou e foi validado
    assert [d["loc"] for d in r.json()["erro"]["detalhes"]] == [["body", "senha"]]


def test_url_grande_414():
    r = cliente.get("/v1/publico/cursos", params={"nome": "a" * (config.MAX_URL_BYTES + 1)})
    assert r.status_code == 414 and r.json()["erro"]["codigo"] == "url_grande"


def test_cabecalhos_grandes_431():
    r = cliente.get("/", headers={"x-lixo": "a" * (config.MAX_CABECALHOS_BYTES + 1)})
    assert r.status_code == 431
    r = cliente.get("/", headers={f"x-h{i}": "1" for i in range(config.MAX_CABECALHOS + 1)})
    assert r.status_code == 431


@pytest.mark.parametrize("metodo", ["TRACE", "TRACK", "CONNECT"])
def test_trace_track_405(metodo):
    r = cliente.request(metodo, "/v1/status")
    assert r.status_code == 405 and "allow" in r.headers
    assert "x-content-type-options" in r.headers


def test_options_sem_cors_nao_vaza():
    r = cliente.options("/v1/historico", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-headers" not in r.headers
    assert r.status_code in (400, 405)


def test_requisicao_normal_continua():
    assert cliente.get("/").status_code == 200
