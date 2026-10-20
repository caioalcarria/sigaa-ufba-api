"""SEG·HTTP — respostas de erro não ecoam segredo nem detalhe interno.

Antes: o 422 de validação devolvia ``exc.errors()`` inteiro, com ``input`` (o pydantic põe ali o valor
recebido — num login malformado, a SENHA); o tratador de ``ValueError`` devolvia ``str(exc)`` (mensagens do
Python como ``invalid literal for int() with base 10: '<pedaço do HTML do SIGAA>'``); e a mensagem de
``SigaaError`` (às vezes tirada do HTML do SIGAA) saía sem limite.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.main import app
from sigaa import errors as E

from ._falso_http import AUTH, ClienteFalso, com_cliente

SENHA = "S3nh4-Sup3r-S3cr3t4"
cliente = TestClient(app)


@pytest.mark.parametrize(
    "corpo",
    [
        {"senha": SENHA},  # falta usuario: o pydantic ecoa o objeto inteiro em "input"
        {"usuario": 1, "senha": SENHA},
        {"usuario": "fulano", "senha": SENHA, "lembrar": "talvez"},
        {"usuario": ["fulano"], "senha": SENHA},
        {"usuario": "fulano", "senha": {"v": SENHA}},
        [SENHA],
    ],
)
def test_422_do_login_nao_ecoa_senha(corpo):
    r = cliente.post("/v1/auth/login", json=corpo)
    assert r.status_code == 422
    assert SENHA not in r.text, r.text
    erro = r.json()["erro"]
    assert erro["codigo"] == "requisicao_invalida" and isinstance(erro["detalhes"], list) and erro["detalhes"]
    for d in erro["detalhes"]:
        assert set(d) <= {"type", "loc", "msg"}


def test_422_de_json_quebrado_nao_ecoa_corpo():
    r = cliente.post("/v1/auth/login", content='{"usuario": "fulano", "senha": "' + SENHA, headers={"content-type": "application/json"})
    assert r.status_code == 422 and SENHA not in r.text


def test_422_de_query_nao_ecoa_valor():
    r = cliente.get("/v1/fotos", params={"url": "x" * 600 + SENHA}, headers=AUTH)
    assert r.status_code in (401, 422) and SENHA not in r.text


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("invalid literal for int() with base 10: '<td>SEGREDO-DO-HTML</td>'"),
        json.JSONDecodeError("Expecting value", "SEGREDO-DO-HTML", 0),
        UnicodeDecodeError("utf-8", b"SEGREDO-DO-HTML", 0, 1, "invalid start byte"),
        ValueError("time data 'SEGREDO-DO-HTML' does not match format '%d/%m/%Y'"),
        ValueError("not enough values to unpack (expected 2, got 1) SEGREDO-DO-HTML"),
    ],
)
def test_valueerror_interno_nao_vaza(exc):
    with com_cliente(ClienteFalso(erro=exc)) as cli:
        r = cli.get("/v1/historico", headers=AUTH)
    assert r.status_code == 422
    assert "SEGREDO-DO-HTML" not in r.text and "invalid literal" not in r.text
    assert r.json()["erro"] == {"codigo": "requisicao_invalida", "mensagem": "Parâmetros inválidos."}


def test_validationerror_do_pydantic_nao_vaza():
    class M(BaseModel):
        n: int

    try:
        M(n="SEGREDO-DO-HTML")
    except ValueError as e:  # pydantic_core.ValidationError é subclasse de ValueError
        exc = e
    with com_cliente(ClienteFalso(erro=exc)) as cli:
        r = cli.get("/v1/historico", headers=AUTH)
    assert r.status_code == 422 and "SEGREDO-DO-HTML" not in r.text


def test_valueerror_de_servico_continua_explicando():
    """Contrato: as mensagens de propósito ("Informe nome ou tipo.") continuam indo pro cliente."""
    with com_cliente(ClienteFalso(erro=ValueError("Informe nome ou tipo."))) as cli:
        r = cli.get("/v1/historico", headers=AUTH)
    assert r.status_code == 422 and r.json()["erro"]["mensagem"] == "Informe nome ou tipo."


def test_filtro_invalido_das_consultas_nao_vaza(monkeypatch):
    from api.routes import consultas as R

    async def quebra(cli, fluxo):  # noqa: ARG001
        raise R._422(ValueError("invalid literal for int() with base 10: 'SEGREDO-DO-HTML'"))

    monkeypatch.setattr(R, "_logado", quebra)
    with com_cliente(ClienteFalso()) as cli:
        r = cli.get("/v1/consultas/unidades", params={"nome": "abc"}, headers=AUTH)
    assert r.status_code == 422 and "SEGREDO-DO-HTML" not in r.text
    assert R._422(ValueError("Informe nome ou tipo.")).detail["mensagem"] == "Informe nome ou tipo."


def test_mensagem_do_sigaa_limitada_e_sem_controle():
    msg = "<script>alert(1)</script>\r\nX-Injetado: 1\x00" + "A" * 5000
    with com_cliente(ClienteFalso(erro=E.NaoEncontrado(msg))) as cli:
        r = cli.get("/v1/historico", headers=AUTH)
    assert r.status_code == 404
    m = r.json()["erro"]["mensagem"]
    assert len(m) <= 300 and "\r" not in m and "\n" not in m and "\x00" not in m
    assert r.headers["content-type"].startswith("application/json")


def test_500_generico():
    with com_cliente(ClienteFalso(erro=RuntimeError("/home/usuario/segredo.py linha 42"))) as cli:
        r = cli.get("/v1/historico", headers=AUTH)
    assert r.status_code == 500 and "segredo" not in r.text and "Traceback" not in r.text
    assert r.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.parametrize(
    "msg",
    [
        "O SIGAA da UFBA quebra ('Comportamento Inesperado') ao abrir calendários de Ensino a Distância; consulta bloqueada.",
        "Informe pelo menos um filtro (codigo, nome, nivel, unidade, tipo ou modalidade).",
        "Informe curso_id ou codigo.",
        "Informe pelo menos um filtro além de ano/período (codigo, nome, unidade, docente, curso...).",
        "Nível inválido: 'X'. Use um de ['G', 'S'].",
        "tipo inválido: 'x'. Use um de ['chefes'].",
        "departamento_id exige centro_id (o select de departamento depende do centro).",
    ],
)
def test_mensagens_dos_servicos_passam_pelo_filtro(msg):
    """Contrato: as mensagens de ``raise ValueError`` dos serviços (sigaa/services) continuam visíveis."""
    from api.seguranca_http import mensagem_publica

    assert mensagem_publica(ValueError(msg)) == msg
