"""Log sem segredo: mascara token, senha, cookie de sessão e dado pessoal óbvio ANTES de qualquer
handler formatar a linha.

Por que na fábrica de registros (``logging.setLogRecordFactory``) e não num filtro de logger: filtro
de logger só vale pro registro emitido NAQUELE logger (o de ``sigaa.pool`` não passa pelo do raiz), e
filtro de handler depende de quem configurou os handlers (o uvicorn faz o dele no boot, o ``lastResort``
do Python não tem filtro nenhum). A fábrica vale pra todo logger do processo — inclusive ``httpx``
(que loga a URL de cada requisição em INFO) e o access log do uvicorn.

O que é mascarado (ver ``PADROES``): ``Authorization``/``Bearer``/``Basic``, ``Cookie``/``Set-Cookie``,
``JSESSIONID`` (cookie e ``;jsessionid=`` na URL), ``senha``/``password``/``token``/``segredo`` como
``chave=valor`` ou JSON, usuário:senha em URL (``redis://u:s@host``), token Fernet (``gAAAA...``),
CPF e e-mail. Vale pra mensagem, argumentos, traceback (``exc_info``) e ``stack_info``.

Não substitui o cuidado de não logar dado: é a rede de proteção.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Any

MASCARA = "***"
#: nomes de campo cujo VALOR nunca vai pro log
_SENSIVEL = r"(?:senha|password|passwd|pwd|secret|segredo|token|api[_-]?key)"

#: (regex, substituição) — aplicados em ordem
PADROES: list[tuple[re.Pattern[str], str]] = [
    # cabeçalhos inteiros (até o fim da linha / da aspa)
    (re.compile(r"(?i)\b((?:proxy-)?authorization|cookie|set-cookie)(['\"]?\s*[:=]\s*['\"]?)[^\r\n'\"]+"), r"\1\2" + MASCARA),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{4,}"), r"\1 " + MASCARA),
    # cookie de sessão do SIGAA (Java): JSESSIONID=..., ;jsessionid=... na URL
    (re.compile(r"(?i)\b(jsessionid)(['\"]?\s*[=:]\s*['\"]?)[^;&\s'\",)\]}]+"), r"\1\2" + MASCARA),
    # chave=valor (query, formulário) e "chave": "valor" (JSON, repr de dict) com nome sensível:
    # user.senha=..., password=..., {"senha": "..."}, {'token': '...'}. "Chave: texto" solto em prosa
    # (ex.: "TokenInvalido: mensagem") NÃO casa — só "=" ou chave entre aspas.
    (re.compile(r"(?i)([\w.\-]*" + _SENSIVEL + r"[\w.\-]*)(\s*=\s*)(b?['\"])?[^\s&'\",;)\]}]+"),
     lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}{MASCARA}"),
    (re.compile(r"(?i)(['\"][\w.\-]*" + _SENSIVEL + r"[\w.\-]*['\"]\s*:\s*)(b?['\"])?[^'\",)\]}]+"),
     lambda m: f"{m.group(1)}{m.group(2) or ''}{MASCARA}"),
    # usuário:senha embutidos em URL (redis://user:senha@host, https://u:s@h)
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@'\"]*:[^/\s@'\"]*@"), r"\1" + MASCARA + "@"),
    # token Fernet (senha "lembrar" cifrada, cache L2 cifrado)
    (re.compile(r"gAAAAA[A-Za-z0-9_\-]{20,}={0,2}"), MASCARA),
    # dado pessoal óbvio
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "<cpf>"),
    (re.compile(r"\b[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+\b"), "<email>"),
]

_PRIMITIVOS = (int, float, bool, type(None))


def mascarar(texto: str) -> str:
    """Devolve ``texto`` com os segredos trocados por ``***`` (CPF/e-mail por ``<cpf>``/``<email>``)."""
    for rx, sub in PADROES:
        texto = rx.sub(sub, texto)
    return texto


def _arg(a: Any) -> Any:
    if isinstance(a, str):
        return mascarar(a)
    if isinstance(a, _PRIMITIVOS):
        return a
    if isinstance(a, (bytes, bytearray)):
        a = repr(a)
        return mascarar(a)
    try:
        s = str(a)
    except Exception:  # noqa: BLE001 - __str__ quebrado não pode derrubar o log
        return "<sem repr>"
    m = mascarar(s)
    return a if m == s else m  # sem nada sensível: mantém o objeto (o %r/%d continua igual)


def limpar(rec: logging.LogRecord) -> logging.LogRecord:
    """Mascara um registro no lugar (mensagem, args, traceback, stack).

    A mensagem é julgada JÁ FORMATADA (o segredo pode estar metade no modelo, metade no argumento:
    ``"Bearer %s", token``). Se mascarar só os argumentos resolve, o registro mantém ``msg``/``args``
    separados (o access log do uvicorn desempacota ``args``); senão vira a mensagem pronta, mascarada."""
    try:
        cheia = rec.getMessage()
    except Exception:  # noqa: BLE001 - registro mal formado: o logging reporta do jeito dele
        cheia = None
    if cheia is not None:
        limpa = mascarar(cheia)
        if limpa != cheia:
            ok = False
            if rec.args:
                args = {k: _arg(v) for k, v in rec.args.items()} if isinstance(rec.args, dict) else tuple(_arg(a) for a in rec.args)
                try:
                    so_args = str(rec.msg) % args
                    ok = mascarar(so_args) == so_args
                except Exception:  # noqa: BLE001
                    ok = False
                if ok:
                    rec.args = args
            if not ok:
                rec.msg, rec.args = limpa, ()
    if rec.exc_info and rec.exc_info[0] is not None and not rec.exc_text:
        # o Formatter só formata o traceback se exc_text estiver vazio: entregamos ele já limpo
        rec.exc_text = mascarar("".join(traceback.format_exception(*rec.exc_info)).rstrip("\n"))
    elif rec.exc_text:
        rec.exc_text = mascarar(rec.exc_text)
    if rec.stack_info:
        rec.stack_info = mascarar(rec.stack_info)
    return rec


class FiltroSegredos(logging.Filter):
    """O mesmo como ``logging.Filter`` (pra usar num ``dictConfig``/handler próprio)."""

    def filter(self, record: logging.LogRecord) -> bool:
        limpar(record)
        return True


_instalado = False


def instalar() -> None:
    """Liga a máscara pra TODO logger do processo (idempotente)."""
    global _instalado
    if _instalado:
        return
    anterior = logging.getLogRecordFactory()

    def fabrica(*args: Any, **kwargs: Any) -> logging.LogRecord:
        rec = anterior(*args, **kwargs)
        try:
            return limpar(rec)
        except Exception:  # noqa: BLE001 - nunca perder a linha de log por causa da máscara
            return rec

    logging.setLogRecordFactory(fabrica)
    _instalado = True
