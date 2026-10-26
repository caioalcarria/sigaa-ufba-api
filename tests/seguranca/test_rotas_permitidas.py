"""SEG·HTTP — lista de rotas permitidas (``SIGAA_API_ROTAS_PERMITIDAS``).

Padrão: vazio = todas as rotas (nada muda pra quem já usa). Com a lista, o que está fora dá 404
``nao_encontrado`` — inclusive o preflight do CORS — e travessia (``..``, ``//``) não fura o prefixo.
As variantes com variável de ambiente rodam num processo à parte (a config é lida no import).
"""

from __future__ import annotations

import pytest

from api.config import config
from api.rotas_permitidas import ler_padroes, permitido

from .test_http_cors_hosts import _rodar

LISTA = "/v1/status,/v1/auth/*,/v1/historico,/v1/indices*,/v1/publico/componentes/*"


def test_padrao_vazio_libera_tudo():
    assert config.ROTAS_PERMITIDAS == ""


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        ("/", True),
        ("/v1/status", True),
        ("/v1/status/", True),
        ("/v1/auth/login", True),
        ("/v1/indices", True),
        ("/v1/indices/simular", True),
        ("/v1/historico", True),
        ("/v1/historico/pdf", False),  # exato não vira prefixo
        ("/v1/publico/componentes/codigo/MATA37", True),
        ("/v1/me/dados-pessoais", False),
        ("/v1/turmas/1/participantes", False),
        ("/docs", False),
        ("/v1/publico/componentes/../../me/dados-pessoais", False),
        ("/v1/auth/./../me", False),
        ("//v1/me", False),
    ],
)
def test_casamento(caminho, esperado):
    prefixos, exatos = ler_padroes(LISTA)
    assert permitido(caminho, prefixos, exatos) is esperado


def test_item_sem_barra_e_recusado():
    with pytest.raises(ValueError):
        ler_padroes("v1/status")


_SONDA = """
import json
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app)
fora = c.get("/v1/me/dados-pessoais", headers={"Authorization": "Bearer x"})
pre_fora = c.options("/v1/me", headers={"Origin": "https://front.example", "Access-Control-Request-Method": "GET"})
pre_dentro = c.options("/v1/historico", headers={"Origin": "https://front.example", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
print(json.dumps({
  "raiz": c.get("/").status_code,
  "historico_sem_token": c.get("/v1/historico").status_code,
  "fora": fora.status_code, "fora_json": fora.json(), "fora_h": dict(fora.headers),
  "pre_fora": pre_fora.status_code,
  "pre_dentro": pre_dentro.status_code, "pre_dentro_h": dict(pre_dentro.headers),
}))
"""


def test_lista_por_variavel():
    d = _rodar({"SIGAA_API_ROTAS_PERMITIDAS": LISTA, "SIGAA_API_CORS": "https://front.example"}, _SONDA)
    assert d["raiz"] == 200
    assert d["historico_sem_token"] == 401  # liberada: chega na rota (e pede login)
    assert d["fora"] == 404 and d["fora_json"]["erro"]["codigo"] == "nao_encontrado"
    assert d["fora_h"]["x-content-type-options"] == "nosniff"  # cabeçalhos de segurança continuam
    assert d["pre_fora"] == 404
    assert d["pre_dentro"] == 200 and d["pre_dentro_h"]["access-control-allow-origin"] == "https://front.example"
