"""Camada HTTP da API: cabeçalhos de segurança, limites de requisição e saída segura de arquivos.

* :class:`SegurancaHTTP` — middleware ASGI puro (sem ``BaseHTTPMiddleware``: não cria task nem stream,
  o HIT do cache continua barato). Fica POR FORA de tudo (inclusive do tratador de 500), então vale pra
  HIT, 304, erros, 504 do prazo e preflight do CORS. Ele só ADICIONA o que falta: ``Cache-Control`` e
  ``Content-Security-Policy`` que a rota/o cache já puseram não são tocados.
* :func:`foto_canonica` — a única forma de URL de foto que o proxy ``/v1/fotos`` aceita.
* :func:`resposta_arquivo` / :func:`content_disposition` — downloads repassados do SIGAA com nome saneado
  (RFC 6266/5987) e sem servir tipo "ativo" (HTML/SVG/XML/JS) no domínio da API.
* :func:`mensagem_publica` — o que de um ``ValueError`` pode ir pro cliente.
"""

from __future__ import annotations

import hashlib
import base64
import html
import re
import unicodedata
from urllib.parse import parse_qsl, quote, urlsplit

from fastapi import Response

from .config import config

# ---------------------------------------------------------------- fotos (proxy /v1/fotos)
#: único caminho de foto do SIGAA (perfil, participantes, docentes): /shared/verFoto?idFoto=<n>&key=<hex>
CAMINHO_FOTO = "/shared/verFoto"
_ID_FOTO = re.compile(r"\d{1,12}")
_CHAVE_FOTO = re.compile(r"[0-9A-Za-z]{1,64}")
#: imagens raster que o navegador nunca executa (SVG fica de fora: é documento com script)
TIPOS_IMAGEM = frozenset({"image/jpeg", "image/pjpeg", "image/png", "image/gif", "image/webp", "image/bmp"})


def foto_canonica(url: str, base_url: str) -> str | None:
    """``/shared/verFoto?idFoto=N&key=K`` reconstruído a partir do ``foto_url`` (relativo ou absoluto no
    próprio SIGAA), ou ``None`` se não for EXATAMENTE isso. Nada do que o cliente mandou é repassado cru:
    caminho fixo, só os dois parâmetros, validados — traversal, ``;``, ``%2e``, ``\\``, credenciais,
    porta/esquema/host diferentes e parâmetro extra caem fora."""
    if not url or len(url) > 512 or any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url) or "\\" in url:
        return None
    url = html.unescape(url)  # o src do HTML às vezes chega com &amp;
    try:
        alvo, base = urlsplit(url), urlsplit(base_url)
    except ValueError:
        return None
    if alvo.fragment or "#" in url:
        return None
    if alvo.scheme or alvo.netloc:
        if (alvo.scheme.lower(), alvo.netloc.lower()) != (base.scheme.lower(), base.netloc.lower()):
            return None
    if alvo.path != CAMINHO_FOTO:
        return None
    try:
        pares = parse_qsl(alvo.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    except ValueError:
        return None
    q = dict(pares)
    if len(pares) != 2 or set(q) != {"idFoto", "key"}:
        return None
    if not _ID_FOTO.fullmatch(q["idFoto"]) or not _CHAVE_FOTO.fullmatch(q["key"]):
        return None
    return f"{CAMINHO_FOTO}?idFoto={q['idFoto']}&key={q['key']}"


#: parâmetro de texto livre que vira id/opção do SIGAA: curto e sem caractere de controle (CR/LF, NUL...)
TEXTO_ID = r"^[^\x00-\x1f\x7f]{1,64}$"


def tipo_base(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def tipo_imagem(content_type: str | None) -> str | None:
    """O tipo (sem parâmetros) se for imagem raster segura; senão ``None``."""
    t = tipo_base(content_type)
    return t if t in TIPOS_IMAGEM else None


# ---------------------------------------------------------------- downloads
#: tipos que o navegador renderiza/executa: nunca servir como estão no domínio da API (XSS)
_ATIVO = re.compile(r"(html|svg|xml|xsl|javascript|ecmascript|jscript|x-shockwave|text/css|multipart/|text/vtt|cache-manifest)", re.I)
#: o que pode abrir "inline" (o resto vai como attachment)
_INLINE_OK = re.compile(r"^(application/pdf|image/(jpeg|pjpeg|png|gif|webp|bmp)|text/plain|text/calendar)$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def tipo_ativo(content_type: str | None) -> bool:
    return bool(_ATIVO.search(tipo_base(content_type))) or not tipo_base(content_type)


def _nome_ascii(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    limpo = re.sub(r'[^A-Za-z0-9._ ()+-]', "_", sem_acento).strip(" .")
    return limpo[:150] or "arquivo"


def nome_seguro(nome: str | None, padrao: str = "arquivo") -> str:
    """Nome de arquivo vindo do SIGAA sem controle (CR/LF), sem separador de caminho e com tamanho limitado."""
    n = _CTRL.sub("", nome or "").replace("/", "_").replace("\\", "_")
    n = unicodedata.normalize("NFC", n).strip(" .")
    return n[:200] or padrao


def content_disposition(nome: str | None, *, inline: bool = False, padrao: str = "arquivo") -> str:
    """``attachment; filename="ascii"; filename*=UTF-8''pct`` (RFC 6266 + 5987): nada do nome original
    entra cru no cabeçalho (aspas, ``;``, CR/LF, unicode)."""
    n = nome_seguro(nome, padrao)
    return f"{'inline' if inline else 'attachment'}; filename=\"{_nome_ascii(n)}\"; filename*=UTF-8''{quote(n, safe='')}"


def resposta_arquivo(conteudo: bytes, tipo: str | None, nome: str | None, *, inline: bool = False, padrao: str = "arquivo") -> Response:
    """Download repassado do SIGAA. Tipo ativo (HTML/SVG/XML/JS…) ou vazio vira
    ``application/octet-stream`` + ``attachment``; ``inline`` só pra PDF/imagem/texto puro."""
    t = (tipo or "").strip()
    if tipo_ativo(t) or _CTRL.search(t):
        t, inline = "application/octet-stream", False
    elif inline and not _INLINE_OK.match(tipo_base(t)):
        inline = False
    return Response(
        conteudo,
        media_type=t,
        headers={
            "Content-Disposition": content_disposition(nome, inline=inline, padrao=padrao),
            "Content-Security-Policy": CSP_PDF if tipo_base(t) == "application/pdf" else CSP_ARQUIVO,
        },
    )


# ---------------------------------------------------------------- erros
#: mensagens de ValueError do próprio Python (int("..."), json, datas, unpack...) — dizem como o código
#: quebrou e às vezes ecoam pedaço do HTML do SIGAA. As de propósito (serviços) são frases em português.
_VALUEERROR_INTERNO = re.compile(
    r"invalid literal|could not convert|not enough values|too many values|is not in list|substring not found|"
    r"math domain|time data|unconverted data|out of range|must be in|invalid isoformat|isoformat string|"
    r"empty separator|arg is an empty|codec can't|expecting value|unterminated|extra data|validation error|"
    r"invalid \w+ literal|base \d+|could not|cannot|can't|unexpected|object|attribute|NoneType|Traceback|File \"",
    re.I,
)
MAX_MENSAGEM = 300


def mensagem_publica(exc: BaseException, padrao: str = "Parâmetros inválidos.") -> str:
    """O texto de um ``ValueError`` só vai pro cliente se for um ``ValueError`` "puro" com mensagem de
    serviço (não de subclasses como JSONDecodeError/UnicodeDecodeError/ValidationError do pydantic, nem
    mensagens do próprio Python). Limitado e sem caracteres de controle."""
    if type(exc) is not ValueError:
        return padrao
    msg = str(exc)
    if not msg or _VALUEERROR_INTERNO.search(msg):
        return padrao
    return limitar(msg)


def limitar(msg: str, n: int = MAX_MENSAGEM) -> str:
    msg = _CTRL.sub(" ", msg).strip()
    return msg if len(msg) <= n else msg[: n - 1] + "…"


# ---------------------------------------------------------------- cabeçalhos
#: JSON e erros: nada carrega, nada embute (se alguém abrir a resposta como documento, é inerte)
CSP_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
#: arquivos repassados: idem + sandbox (sem script, origem opaca), menos pra PDF (o leitor do navegador quebra)
CSP_ARQUIVO = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; sandbox"
CSP_PDF = "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
#: HTML vindo do SIGAA (comprovante pra imprimir): sem script nenhum, origem opaca (sandbox), só estilo inline
CSP_HTML_SIGAA = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; sandbox"
#: Swagger/ReDoc carregam do jsDelivr; o script inline do Swagger entra por hash (calculado na hora)
_CSP_DOCS = (
    "default-src 'none'; script-src 'self' https://cdn.jsdelivr.net{hashes}; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com data:; img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_SCRIPT_INLINE = re.compile(rb"<script>(.*?)</script>", re.S)

FIXOS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"),
]
_HSTS = (b"strict-transport-security", b"max-age=31536000")
_NO_STORE = (b"cache-control", b"no-store")
METODOS_BLOQUEADOS = frozenset({"TRACE", "TRACK", "CONNECT"})


def _json(status: int, codigo: str, mensagem: str, extra: list[tuple[bytes, bytes]] | None = None):
    corpo = ('{"erro":{"codigo":"%s","mensagem":"%s"}}' % (codigo, mensagem)).encode()
    hs = [(b"content-type", b"application/json"), (b"content-length", str(len(corpo)).encode()), (b"connection", b"close")]
    return status, hs + (extra or []), corpo


#: (método, caminho) que recebem arquivo no corpo: limite SIGAA_API_MAX_CORPO_UPLOAD_BYTES
UPLOADS = {("PUT", "/v1/me/foto")}


class SegurancaHTTP:
    """Middleware ASGI puro, o mais externo da pilha: limites (405/413/414/431) e cabeçalhos de segurança."""

    def __init__(
        self,
        app,
        *,
        max_corpo: int | None = None,
        max_url: int | None = None,
        max_cabecalhos_bytes: int | None = None,
        max_cabecalhos: int | None = None,
        hsts: str | None = None,
        docs: tuple[str, ...] = ("/docs", "/redoc"),
    ) -> None:
        self.app = app
        self.max_corpo = config.MAX_CORPO_BYTES if max_corpo is None else max_corpo
        self.max_upload = max(self.max_corpo, config.MAX_CORPO_UPLOAD_BYTES) if self.max_corpo > 0 else 0
        self.max_url = config.MAX_URL_BYTES if max_url is None else max_url
        self.max_cab_bytes = config.MAX_CABECALHOS_BYTES if max_cabecalhos_bytes is None else max_cabecalhos_bytes
        self.max_cab = config.MAX_CABECALHOS if max_cabecalhos is None else max_cabecalhos
        self.hsts = (config.HSTS if hsts is None else hsts).strip().lower()
        self.docs = tuple(d for d in docs if d)

    # ------------------------------------------------------------ entrada
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        hsts = self.hsts in ("1", "true", "sim", "yes", "on") or (self.hsts == "auto" and scope.get("scheme") == "https")
        docs = bool(self.docs) and path.startswith(self.docs)
        publico = path.startswith("/v1/publico/")

        async def enviar(msg):
            if msg["type"] == "http.response.start":
                msg = dict(msg)
                msg["headers"] = self._cabecalhos(list(msg.get("headers") or []), hsts, publico, None)
            await send(msg)

        recusa = self._recusar(scope)
        if recusa is not None:
            return await self._enviar_pronto(enviar, *recusa)

        max_corpo = self.max_upload if (scope.get("method"), path) in UPLOADS else self.max_corpo
        if max_corpo > 0:
            hs = scope["headers"]
            cl = next((v for k, v in hs if k == b"content-length"), None)
            if cl is not None:
                if cl.strip().isdigit() and int(cl) > max_corpo:
                    return await self._enviar_pronto(enviar, *_json(413, "corpo_grande", f"Corpo da requisição passa de {max_corpo} bytes."))
            elif any(k == b"transfer-encoding" for k, _ in hs):
                # sem Content-Length (chunked): lê até o limite antes de deixar a app ver qualquer byte
                partes, total = [], 0
                while True:
                    m = await receive()
                    if m["type"] != "http.request":
                        return
                    corpo = m.get("body", b"")
                    total += len(corpo)
                    if total > max_corpo:
                        return await self._enviar_pronto(enviar, *_json(413, "corpo_grande", f"Corpo da requisição passa de {max_corpo} bytes."))
                    partes.append(corpo)
                    if not m.get("more_body"):
                        break
                receive = _reapresentar(b"".join(partes), receive)

        if docs:
            return await self._docs(scope, receive, send, hsts)
        return await self.app(scope, receive, enviar)

    def _recusar(self, scope):
        if scope.get("method", "GET").upper() in METODOS_BLOQUEADOS:
            return _json(405, "metodo_nao_permitido", "Método não permitido.", [(b"allow", b"GET, POST, PUT, PATCH, DELETE, OPTIONS")])
        if self.max_url > 0 and len(scope.get("raw_path") or scope.get("path", "").encode()) + len(scope.get("query_string") or b"") > self.max_url:
            return _json(414, "url_grande", f"Endereço passa de {self.max_url} bytes.")
        hs = scope.get("headers") or []
        if (self.max_cab > 0 and len(hs) > self.max_cab) or (self.max_cab_bytes > 0 and sum(len(k) + len(v) for k, v in hs) > self.max_cab_bytes):
            return _json(431, "cabecalhos_grandes", "Cabeçalhos da requisição grandes demais.")
        return None

    @staticmethod
    async def _enviar_pronto(enviar, status, hs, corpo):
        await enviar({"type": "http.response.start", "status": status, "headers": hs})
        await enviar({"type": "http.response.body", "body": corpo})

    # ------------------------------------------------------------ saída
    @staticmethod
    def _cabecalhos(hs: list, hsts: bool, publico: bool, csp: bytes | None) -> list:
        tem = {k.lower() for k, _ in hs}
        for par in FIXOS:
            if par[0] not in tem:
                hs.append(par)
        if b"content-security-policy" not in tem:
            if csp is None:
                tipo = next((v for k, v in hs if k.lower() == b"content-type"), b"").lower()
                csp = (CSP_PDF if tipo.startswith(b"application/pdf") else CSP_API).encode()
            hs.append((b"content-security-policy", csp))
        if b"cache-control" not in tem and not publico:
            hs.append(_NO_STORE)  # dado pessoal que não passou pelo cache (login, sessão, 401, /me...)
        if hsts and b"strict-transport-security" not in tem:
            hs.append(_HSTS)
        return hs

    async def _docs(self, scope, receive, send, hsts: bool):
        """/docs e /redoc: segura a página (pequena) pra pôr o hash do script inline na CSP."""
        inicio: dict = {}
        partes: list[bytes] = []

        async def capturar(msg):
            if msg["type"] == "http.response.start":
                inicio.update(msg)
            elif msg["type"] == "http.response.body":
                partes.append(msg.get("body", b""))
                if not msg.get("more_body"):
                    corpo = b"".join(partes)
                    hashes = "".join(
                        " 'sha256-%s'" % base64.b64encode(hashlib.sha256(s).digest()).decode() for s in _SCRIPT_INLINE.findall(corpo)
                    )
                    csp = _CSP_DOCS.format(hashes=hashes).encode()
                    hs = self._cabecalhos(list(inicio.get("headers") or []), hsts, False, csp)
                    await send({**inicio, "headers": hs})
                    await send({"type": "http.response.body", "body": corpo})

        await self.app(scope, receive, capturar)


def _reapresentar(corpo: bytes, receive):
    entregue = False

    async def rx():
        nonlocal entregue
        if not entregue:
            entregue = True
            return {"type": "http.request", "body": corpo, "more_body": False}
        return await receive()

    return rx
