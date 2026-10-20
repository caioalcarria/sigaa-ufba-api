"""SEG·HTTP — CORS fechado por padrão, Host opcional, docs opcionais, CSRF impossível (sem cookie).

Antes: ``SIGAA_API_CORS`` padrão ``*`` com ``allow_headers=*`` — qualquer site podia usar a API pelo navegador
da vítima (com um token roubado ou Basic). Agora o padrão é NENHUMA origem; a variável libera.
As variantes com variável de ambiente rodam num processo à parte (a config é lida no import).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from api.config import config
from api.main import app

RAIZ = Path(__file__).resolve().parents[2]
cliente = TestClient(app)


def test_cors_padrao_nenhuma_origem():
    assert config.CORS == []
    r = cliente.get("/", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def _rodar(env: dict[str, str], codigo: str) -> dict:
    e = {**os.environ, **env, "SIGAA_PARSE_PROCESSOS": "0", "PYTHONPATH": str(RAIZ)}
    out = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=e, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


_SONDA = """
import json
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app)
pre = c.options("/v1/historico", headers={"Origin": "https://front.example", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
ruim = c.options("/v1/historico", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
simples = c.get("/", headers={"Origin": "https://front.example"})
host_ruim = c.get("/", headers={"Host": "evil.example"})
host_bom = c.get("/", headers={"Host": "api.exemplo.br"})
print(json.dumps({
  "pre": dict(pre.headers), "ruim": dict(ruim.headers), "simples": dict(simples.headers),
  "host_ruim": host_ruim.status_code, "host_ruim_h": dict(host_ruim.headers), "host_bom": host_bom.status_code,
  "docs": c.get("/docs").status_code, "openapi": c.get("/openapi.json").status_code,
}))
"""


def test_cors_liberado_por_variavel_sem_credenciais_e_host_e_docs():
    d = _rodar({"SIGAA_API_CORS": "https://front.example", "SIGAA_API_HOSTS": "api.exemplo.br,testserver", "SIGAA_API_DOCS": "false"}, _SONDA)
    assert d["pre"]["access-control-allow-origin"] == "https://front.example"
    assert "access-control-allow-credentials" not in d["pre"]
    assert "authorization" in d["pre"]["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in d["ruim"]
    assert d["simples"]["access-control-allow-origin"] == "https://front.example"
    assert d["host_ruim"] == 400 and d["host_ruim_h"]["x-content-type-options"] == "nosniff"
    assert d["host_bom"] == 200
    assert d["docs"] == 404 and d["openapi"] == 404


def test_cors_estrela_nunca_com_credenciais():
    d = _rodar({"SIGAA_API_CORS": "*"}, _SONDA)
    assert d["pre"]["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in d["pre"]
    assert d["host_ruim"] == 200 and d["docs"] == 200  # padrões: qualquer Host, docs no ar


def test_nenhuma_rota_autentica_por_cookie():
    """CSRF: a autenticação só lê ``Authorization`` (Bearer/Basic). Um cookie com o token não autentica."""
    r = cliente.get("/v1/historico", headers={"Cookie": "token=qualquer; Authorization=Bearer x"})
    assert r.status_code == 401 and r.json()["erro"]["codigo"] == "nao_autenticado"
    fonte = "".join(p.read_text(encoding="utf-8") for p in (RAIZ / "api").rglob("*.py"))
    assert "request.cookies" not in fonte and "Cookie(" not in fonte and "set_cookie" not in fonte
