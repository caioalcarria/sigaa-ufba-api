"""SEG·HTTP — arquivos repassados do SIGAA: nome e tipo vêm de fora, não podem virar cabeçalho nem script.

Antes:
* ``/v1/atividades-autonomas/{id}/comprovante`` montava ``filename="{nome}"`` cru (academico.py:292): aspas e
  ``;`` do nome do SIGAA reescreviam o cabeçalho, e nome com acento/travessão (fora do latin-1) dava 500;
* arquivos/anexos da turma virtual, o gráfico de estatísticas e ``/v1/me/foto`` repassavam o content-type do
  SIGAA: ``text/html``/``image/svg+xml`` era servido no domínio da API (XSS se alguém abrir o link);
* ``/v1/documentos/comprovante-inscricao/html`` serve HTML do SIGAA na origem da API sem CSP/sandbox.
"""

from __future__ import annotations

import pytest

from ._falso_http import AUTH, ClienteFalso, com_cliente

NOMES_RUINS = [
    'a".pdf; filename=evil.html',
    "rel\r\nSet-Cookie: x=1.pdf",
    "relatório – versão final.pdf",
    "../../etc/passwd",
    "\x00\x07nome.pdf",
    "😀" * 300,
]


def _cd_seguro(cd: str) -> None:
    assert "\r" not in cd and "\n" not in cd and "\x00" not in cd
    assert cd.count('"') == 2, cd  # só as aspas do filename=
    assert "filename*=UTF-8''" in cd
    assert "/" not in cd.split("filename=", 1)[1].split(";", 1)[0]
    cd.encode("latin-1")


@pytest.mark.parametrize("nome", NOMES_RUINS)
def test_comprovante_atividade_nome_saneado(nome):
    with com_cliente(ClienteFalso(resposta=(b"%PDF-1.4", "application/pdf", nome))) as cli:
        r = cli.get("/v1/atividades-autonomas/1/comprovante", headers=AUTH)
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    _cd_seguro(cd)
    assert cd.startswith("inline;")  # PDF continua abrindo no navegador (contrato)
    assert cd.count("filename=") == 1


@pytest.mark.parametrize("nome", NOMES_RUINS)
def test_arquivo_turma_nome_saneado(nome):
    with com_cliente(ClienteFalso(resposta=(b"dados", "application/pdf", nome))) as cli:
        r = cli.get("/v1/turmas/123/arquivos/456", headers=AUTH)
    assert r.status_code == 200
    _cd_seguro(r.headers["content-disposition"])
    assert r.headers["content-disposition"].startswith("attachment;")


@pytest.mark.parametrize("tipo", ["text/html", "text/html; charset=utf-8", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/javascript", ""])
@pytest.mark.parametrize("rota", ["/v1/turmas/123/arquivos/456", "/v1/turmas/123/forum/1/topicos/2/anexos/3", "/v1/atividades-autonomas/1/comprovante"])
def test_download_de_tipo_ativo_vira_octet_stream(rota, tipo):
    with com_cliente(ClienteFalso(resposta=(b"<script>alert(1)</script>", tipo, "x.html"))) as cli:
        r = cli.get(rota, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream", r.headers["content-type"]
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]


def test_download_pdf_sem_sandbox():
    """PDF não leva ``sandbox`` (o leitor de PDF do navegador não abre documento em sandbox)."""
    with com_cliente(ClienteFalso(resposta=(b"%PDF-1.4", "application/pdf", "a.pdf"))) as cli:
        r = cli.get("/v1/turmas/123/arquivos/456", headers=AUTH)
    assert r.headers["content-type"] == "application/pdf" and "sandbox" not in r.headers["content-security-policy"]


@pytest.mark.parametrize("tipo", ["text/html", "image/svg+xml"])
def test_grafico_nao_serve_html(tipo):
    with com_cliente(ClienteFalso(resposta=(b"<svg onload=alert(1)>", tipo))) as cli:
        r = cli.get("/v1/turmas/123/estatisticas/grafico", headers=AUTH)
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_grafico_png_continua():
    with com_cliente(ClienteFalso(resposta=(b"\x89PNG\r\n", "image/png"))) as cli:
        r = cli.get("/v1/turmas/123/estatisticas/grafico", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


@pytest.mark.parametrize("tipo", ["image/svg+xml", "text/html"])
def test_me_foto_nao_serve_svg(tipo):
    with com_cliente(ClienteFalso(resposta=(b"<svg onload=alert(1)>", tipo))) as cli:
        r = cli.get("/v1/me/foto", headers=AUTH)
    assert r.status_code == 404 and "svg" not in r.headers["content-type"]


def test_me_foto_jpeg_continua():
    with com_cliente(ClienteFalso(resposta=(b"\xff\xd8\xff", "image/jpeg"))) as cli:
        r = cli.get("/v1/me/foto", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, max-age=3600"


def test_comprovante_html_em_sandbox():
    html = "<html><body><h1>Comprovante</h1><script>fetch('/v1/me')</script><img src=x onerror=alert(1)></body></html>"
    with com_cliente(ClienteFalso(resposta=html)) as cli:
        r = cli.get("/v1/documentos/comprovante-inscricao/html", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/html; charset=utf-8"  # contrato: continua HTML pra imprimir
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "default-src 'none'" in csp and "script-src" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("inline;")
    assert r.headers["cache-control"] == "no-store"
