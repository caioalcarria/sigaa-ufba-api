"""SEG·HTTP — cabeçalhos de segurança em TODAS as respostas (rota, HIT do cache, 304, erros, 404, 500, docs).

Antes não havia nenhum: sem ``nosniff``, sem ``frame-ancestors``/``X-Frame-Options``, sem CSP, sem
``Referrer-Policy``, e ``/v1/auth/sessao``/401/``/v1/me`` sem ``Cache-Control`` (proxy/navegador podia guardar).
"""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from api.main import app

cliente = TestClient(app, raise_server_exceptions=False)

ESPERADOS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-resource-policy": "same-origin",
}


def _tem_cabecalhos(r) -> None:
    for k, v in ESPERADOS.items():
        assert r.headers.get(k) == v, (k, r.headers.get(k), r.request.url)
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "permissions-policy" in r.headers


@pytest.mark.parametrize("caminho", ["/", "/v1/historico", "/v1/auth/sessao", "/nao-existe", "/v1/turmas/abc!/notas", "/openapi.json"])
def test_cabecalhos_em_rotas_e_erros(caminho):
    r = cliente.get(caminho)
    _tem_cabecalhos(r)


def test_json_tem_csp_que_nao_carrega_nada():
    r = cliente.get("/")
    assert r.headers["content-security-policy"].startswith("default-src 'none'")


@pytest.mark.parametrize("caminho", ["/v1/historico", "/v1/auth/sessao", "/v1/me"])
def test_dado_pessoal_sem_cache_vem_no_store(caminho):
    r = cliente.get(caminho)  # 401: nem o erro pode ficar em cache intermediário
    assert r.status_code == 401 and r.headers["cache-control"] == "no-store"


def test_sem_hsts_em_http_e_com_hsts_em_https():
    assert "strict-transport-security" not in cliente.get("/").headers
    r = TestClient(app, base_url="https://testserver").get("/")
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_hit_e_304_do_cache_tambem_tem_cabecalhos(monkeypatch):
    from api.routes import consultas as R

    chamadas = []

    async def publico(fluxo):  # noqa: ARG001
        chamadas.append(1)
        return []

    monkeypatch.setattr(R, "_publico", publico)
    url = "/v1/publico/unidades?_t=cabecalhos"
    r1 = cliente.get(url)
    r2 = cliente.get(url)
    assert r1.status_code == 200 and r2.status_code == 200
    if r2.headers.get("x-cache") != "HIT":
        pytest.skip("cache L1 desligado neste ambiente")
    _tem_cabecalhos(r2)
    assert r2.headers["cache-control"].startswith("public, max-age=")  # o do cache NÃO é sobrescrito
    r3 = cliente.get(url, headers={"If-None-Match": r2.headers["etag"]})
    assert r3.status_code == 304
    _tem_cabecalhos(r3)


def test_docs_csp_com_hash_do_script_inline():
    r = cliente.get("/docs")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in csp and "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    for s in re.findall(rb"<script>(.*?)</script>", r.content, re.S):
        h = base64.b64encode(hashlib.sha256(s).digest()).decode()
        assert f"'sha256-{h}'" in csp
    assert cliente.get("/redoc").headers["content-security-policy"].startswith("default-src 'none'; script-src 'self' https://cdn.jsdelivr.net")


def test_500_tambem_tem_cabecalhos():
    from ._falso_http import AUTH, ClienteFalso, com_cliente

    with com_cliente(ClienteFalso(erro=RuntimeError("x"))) as cli:
        r = cli.get("/v1/historico", headers=AUTH)
    assert r.status_code == 500
    _tem_cabecalhos(r)
    assert r.headers["cache-control"] == "no-store"
