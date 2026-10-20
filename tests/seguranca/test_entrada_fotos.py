"""SEG·HTTP — GET /v1/fotos?url= não pode virar proxy pra qualquer tela do SIGAA (nem pra fora dele).

Antes: aceitava qualquer ``/sigaa/...`` com "foto" no caminho (substring!), ``..``, ``;foto``, query livre e
qualquer coisa começando com ``/shared/verFoto`` — a API fazia GET com a SESSÃO DO ALUNO em telas arbitrárias
(ex.: logoff, ações JSF por GET). E repassava qualquer ``image/*`` (inclusive SVG = script no domínio da API).
"""

from __future__ import annotations

import pytest

from api.config import config

from ._falso_http import AUTH, ClienteFalso, com_cliente

RUINS = [
    "/sigaa/foto/../logar.do?dispatch=logOff",  # traversal
    "/sigaa/logar.do;foto?dispatch=logOff",  # "foto" só como parâmetro de matriz
    "/sigaa/portais/discente/discente.jsf;jsessionid=x?foto=1",
    "/sigaa/%2e%2e/admin/foto",
    "/sigaa/fotos/../../shared/verFoto?idFoto=1&key=0",
    "/shared/verFoto/../../sigaa/portais/discente/discente.jsf",
    "/shared/verFotoXYZ?idFoto=1&key=0",
    "/shared/verFoto?idFoto=1&key=0&dispatch=logOff",  # parâmetro extra
    "/shared/verFoto?idFoto=1&idFoto=2&key=0",
    "/shared/verFoto?idFoto=abc&key=0",
    "/shared/verFoto?idFoto=1&key=0%0d%0aX-Injetado:%201",
    "/shared/verFoto?idFoto=1&key=../../x",
    "/shared/verFoto?idFoto=1&key=0#frag",
    "/shared//verFoto?idFoto=1&key=0",
    "/shared/%76erFoto?idFoto=1&key=0",
    "//evil.example/shared/verFoto?idFoto=1&key=0",
    "https://evil.example/shared/verFoto?idFoto=1&key=0",
    "http://sigaa.ufba.br/shared/verFoto?idFoto=1&key=0",  # esquema diferente do SIGAA configurado
    "https://usuario:senha@sigaa.ufba.br/shared/verFoto?idFoto=1&key=0",
    "https://sigaa.ufba.br:8443/shared/verFoto?idFoto=1&key=0",
    "https://sigaa.ufba.br@evil.example/shared/verFoto?idFoto=1&key=0",
    "javascript:alert(1)//shared/verFoto?idFoto=1&key=0",
    "file:///shared/verFoto?idFoto=1&key=0",
    "\\\\evil.example\\shared\\verFoto?idFoto=1&key=0",
    "/\\evil.example/shared/verFoto?idFoto=1&key=0",
    "shared/verFoto?idFoto=1&key=0",
    "",
]


@pytest.mark.parametrize("url", RUINS)
def test_foto_recusa_caminho_fora_da_lista(url):
    falso = ClienteFalso()
    with com_cliente(falso) as cli:
        r = cli.get("/v1/fotos", params={"url": url}, headers=AUTH)
    assert r.status_code == 422, (url, r.status_code, r.text)
    assert falso.pedidos == [], f"a API pediu {falso.pedidos} ao SIGAA para {url!r}"
    assert r.json()["erro"]["codigo"] == "requisicao_invalida"


@pytest.mark.parametrize(
    "url",
    [
        "/shared/verFoto?idFoto=2887171&key=d50aef4522b1b7c62991777aeb764244",
        "https://sigaa.ufba.br/shared/verFoto?idFoto=2887171&key=d50aef4522b1b7c62991777aeb764244",
        "/shared/verFoto?key=d50aef4522b1b7c62991777aeb764244&idFoto=2887171",
        "/shared/verFoto?idFoto=2887171&amp;key=d50aef4522b1b7c62991777aeb764244",  # src ainda com &amp;
    ],
)
def test_foto_valida_vai_canonica(url):
    falso = ClienteFalso()
    with com_cliente(falso) as cli:
        r = cli.get("/v1/fotos", params={"url": url}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert falso.pedidos == ["/shared/verFoto?idFoto=2887171&key=d50aef4522b1b7c62991777aeb764244"]
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_foto_que_o_proprio_parser_devolve_continua_abrindo():
    """Os foto_url das fixtures (perfil, participantes, docentes) passam."""
    falso = ClienteFalso()
    with com_cliente(falso) as cli:
        r = cli.get("/v1/fotos", params={"url": "/shared/verFoto?idFoto=1&key=0"}, headers=AUTH)
    assert r.status_code == 200 and falso.pedidos == ["/shared/verFoto?idFoto=1&key=0"]


@pytest.mark.parametrize("tipo", ["image/svg+xml", "image/svg+xml; charset=utf-8", "text/html", "image/x-icon; foo", "application/octet-stream", ""])
def test_foto_nao_repassa_tipo_ativo(tipo):
    falso = ClienteFalso(conteudo=b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>", tipo=tipo)
    with com_cliente(falso) as cli:
        r = cli.get("/v1/fotos", params={"url": "/shared/verFoto?idFoto=1&key=0"}, headers=AUTH)
    assert r.status_code == 404, (tipo, r.status_code, r.headers.get("content-type"))
    assert "svg" not in r.headers.get("content-type", "")


def test_foto_grande_demais_e_recusada(monkeypatch):
    monkeypatch.setattr(config, "FOTO_MAX_BYTES", 1024, raising=False)
    falso = ClienteFalso(conteudo=b"\xff\xd8\xff" + b"0" * 4096)
    with com_cliente(falso) as cli:
        r = cli.get("/v1/fotos", params={"url": "/shared/verFoto?idFoto=1&key=0"}, headers=AUTH)
    assert r.status_code == 502 and r.json()["erro"]["codigo"] == "sigaa_erro"


def test_foto_url_gigante_e_recusada():
    falso = ClienteFalso()
    with com_cliente(falso) as cli:
        r = cli.get("/v1/fotos", params={"url": "/shared/verFoto?idFoto=1&key=" + "a" * 3000}, headers=AUTH)
    assert r.status_code == 422 and falso.pedidos == []


# ---------------------------------------------------------------- ids de texto repassados ao SIGAA
@pytest.mark.parametrize(
    "rota,params",
    [
        ("/v1/mensagens/" + "1" * 65, None),
        ("/v1/mensagens/1%0d%0aX-Injetado:%201", None),
        ("/v1/avaliacao-institucional/resultado", {"departamento_id": "1\r\nX: y", "periodo": "2025.2"}),
        ("/v1/avaliacao-institucional/resultado", {"departamento_id": "1", "periodo": "2025.2" * 20}),
        ("/v1/avaliacao-institucional/observacoes", {"periodo": "\x00"}),
        ("/v1/historico/componentes", {"situacao": "APR\nREP"}),
    ],
)
def test_ids_de_texto_validados(rota, params):
    falso = ClienteFalso(resposta=[])
    with com_cliente(falso) as cli:
        r = cli.get(rota, params=params, headers=AUTH)
    assert r.status_code == 422, (rota, r.status_code)
    assert falso.pedidos == []
