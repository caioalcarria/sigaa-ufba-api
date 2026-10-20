"""SEG·SEGREDOS — nenhum log do processo carrega senha, token, cookie de sessão ou dado pessoal óbvio.

Os valores abaixo são FICTÍCIOS (gerados pro teste)."""

from __future__ import annotations

import io
import logging

import httpx
import pytest

import api.main  # noqa: F401 - subir o app liga a máscara de log

TOKEN = "tok3n-FICTICIO-abcdef0123456789"
SENHA = "SenhaFicticia#2026"
JSESSION = "A1B2C3D4E5F6FICTICIO0000"
FERNET = "gAAAAABmFICTICIOfakeFernetTokenFakeFakeFake0123456789abcdef=="
SEGREDOS = [TOKEN, SENHA, JSESSION, FERNET, "000.111.222-33", "aluno.ficticio@exemplo.com", "dXN1YXJpbzpzZW5oYQ"]


@pytest.fixture
def saida():
    """Um handler simples no logger RAIZ (como o lastResort / um dictConfig qualquer)."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    raiz = logging.getLogger()
    nivel = raiz.level
    raiz.addHandler(h)
    raiz.setLevel(logging.DEBUG)
    try:
        yield buf
    finally:
        raiz.removeHandler(h)
        raiz.setLevel(nivel)


def _sem_segredo(texto: str) -> None:
    for s in SEGREDOS:
        assert s not in texto, f"vazou no log: {texto!r}"


def test_mensagem_e_args_de_logger_filho_sao_mascarados(saida):
    log = logging.getLogger("sigaa.pool")  # logger filho: filtro no raiz não pegaria
    log.warning("keep-alive falhou: %s", f"GET https://sigaa.exemplo/sigaa/portal.jsf;jsessionid={JSESSION}?x=1")
    log.info("Authorization: Bearer %s", TOKEN)
    log.info("cabeçalhos %r", {"authorization": f"Basic dXN1YXJpbzpzZW5oYQ==", "cookie": f"JSESSIONID={JSESSION}"})
    log.info("form user.login=fulano&user.senha=%s&x=1", SENHA)
    log.info('corpo {"usuario": "fulano", "senha": "%s"}', SENHA)
    log.info("cred %r", FERNET.encode())
    log.info("aluno %s cpf %s", "aluno.ficticio@exemplo.com", "000.111.222-33")
    texto = saida.getvalue()
    _sem_segredo(texto)
    assert "***" in texto and "keep-alive falhou" in texto  # a linha continua lá, útil


def test_traceback_do_log_exception_e_mascarado(saida):
    try:
        raise RuntimeError(f"Link 'x' não encontrado na página https://h/sigaa/a.jsf;jsessionid={JSESSION} senha={SENHA}")
    except RuntimeError:
        logging.getLogger("sigaa_api").exception("erro não tratado")
    texto = saida.getvalue()
    _sem_segredo(texto)
    assert "Traceback" in texto and "RuntimeError" in texto


def test_url_com_usuario_e_senha_mascarada(saida):
    logging.getLogger("sigaa_api.cache").warning("SIGAA_API_CACHE_URL ignorado (%s)", f"redis://default:{SENHA}@10.0.0.5:6379/0")
    texto = saida.getvalue()
    assert SENHA not in texto and "redis://***@10.0.0.5" in texto


def test_log_do_httpx_e_do_access_log_do_uvicorn(saida):
    logging.getLogger("httpx").info('HTTP Request: %s %s "%s %d %s"', "GET", httpx.URL(f"https://h/sigaa/p.jsf;jsessionid={JSESSION}"), "HTTP/1.1", 200, "OK")
    # o access log do uvicorn desempacota record.args (5 itens) — a máscara não pode quebrar isso
    from uvicorn.logging import AccessFormatter

    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    acc = logging.getLogger("uvicorn.access")
    acc.addHandler(h)
    try:
        acc.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", f"/v1/x?token={TOKEN}", "1.1", 200)
    finally:
        acc.removeHandler(h)
    _sem_segredo(saida.getvalue() + buf.getvalue())
    assert '"GET /v1/x?token=*** HTTP/1.1" 200' in buf.getvalue()


def test_mascarar_nao_estraga_mensagem_comum():
    from api.log_seguro import mascarar

    for ok in ["pool de parse: 3 processo(s)", "TokenInvalido: token expirado", "Usuário e/ou senha inválidos.",
               "revalidação de /v1/publico/cursos falhou: timeout", "sessão SIGAA caiu"]:
        assert mascarar(ok) == ok
