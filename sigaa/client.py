"""Cliente assíncrono do SIGAA (testado no SIGAA da UFBA, v4.13).

O SIGAA é um sistema JSF/Struts *stateful*: cada tela guarda estado no servidor
(o ``javax.faces.ViewState``) e a navegação só é aceita a partir de links que o
próprio sistema gerou. Por isso este cliente:

* serializa a navegação de uma sessão (``asyncio.Lock``) — duas telas abertas ao
  mesmo tempo na mesma sessão quebram o ViewState uma da outra. Pra paralelizar, use
  VÁRIAS sessões do mesmo aluno (``sigaa.pool.PoolSigaa``) e ``await c.paralelo([...])``;
* sabe "clicar" nos ``h:commandLink`` (função JS ``jsfcljs``) e nos itens do
  menu JSCook do portal sem precisar de navegador;
* trata a tela de avisos pós-login e a escolha de vínculo;
* detecta sessão expirada, erro do sistema e navegação recusada, e consegue
  relogar sozinho se as credenciais forem mantidas em memória.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Sequence, TypeVar
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from .pool import PoolSigaa

from .errors import (
    AcessoNegado,
    CredenciaisInvalidas,
    NavegacaoInvalida,
    SessaoExpirada,
    SigaaError,
    SigaaOcupado,
    SistemaIndisponivel,
)

log = logging.getLogger("sigaa.client")

#: SIGAA alvo. Respeita SIGAA_URL em TODO SigaaClient criado sem base_url (inclusive as sessões
#: anônimas das rotas públicas) — senão um teste contra o SIGAA simulado vazaria pro SIGAA real.
BASE_URL = os.getenv("SIGAA_URL", "https://sigaa.ufba.br").rstrip("/")
URL_PORTAL = "/sigaa/verPortalDiscente.do"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 sigaa-api"
)

_RE_VIEWSTATE = re.compile(
    r'name="javax\.faces\.ViewState"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*name="javax\.faces\.ViewState"'
)
_RE_JSFCLJS = re.compile(r"getElementById\('([^']+)'\),\s*\{(.*?)\},\s*'([^']*)'\)", re.S)
_RE_PARAMS = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")
_RE_MENU = re.compile(r"\[(?:null|'[^']*'),\s*'([^']+)',\s*'(menu_form_menu_[^']+)',\s*'([^']+)'")


@dataclass
class Page:
    """Uma resposta do SIGAA já decodificada."""

    url: str
    status: int
    content: bytes
    content_type: str
    encoding: str = "iso-8859-1"
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    _html: str | None = field(default=None, repr=False)
    _soup: BeautifulSoup | None = field(default=None, repr=False)
    _lx: Any = field(default=None, repr=False)

    @property
    def html(self) -> str:
        if self._html is None:
            self._html = self.content.decode(self.encoding, errors="replace")
        return self._html

    @property
    def soup(self) -> BeautifulSoup:
        if self._soup is None:
            self._soup = BeautifulSoup(self.html, "lxml")
        return self._soup

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type or not self.content_type

    @property
    def is_pdf(self) -> bool:
        return "pdf" in self.content_type or self.content[:4] == b"%PDF"

    @property
    def viewstate(self) -> str | None:
        m = _RE_VIEWSTATE.search(self.html)
        return (m.group(1) or m.group(2)) if m else None

    def text(self) -> str:
        return re.sub(r"\n\s*\n+", "\n", self.soup.get_text("\n"))

    def form(self, form_id: str):
        f = self.soup.find("form", id=form_id) or self.soup.find("form", attrs={"name": form_id})
        if f is not None and not f.find("input", attrs={"name": "javax.faces.ViewState"}) and "javax.faces.ViewState" in self.html:
            # formulário ANINHADO (o SIGAA tem): o lxml fecha o externo cedo e perde campos/ViewState.
            # O html.parser respeita o aninhamento.
            alt = BeautifulSoup(self.html, "html.parser")
            f2 = alt.find("form", id=form_id) or alt.find("form", attrs={"name": form_id})
            if f2 is not None:
                return f2
        return f

    @property
    def nome_arquivo(self) -> str | None:
        """Nome do arquivo do Content-Disposition (downloads)."""
        cd = self.headers.get("content-disposition", "")
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.I)
        return m.group(1) if m else None

    def arvore_lxml(self) -> Any:
        """A árvore do lxml (o MESMO parser libxml2 que o BeautifulSoup usa por baixo, sem a camada
        Python dele: ~9x mais rápido). Só pra navegação (links e formulários); ``None`` se não der."""
        if self._lx is None:
            try:
                import lxml.html

                self._lx = lxml.html.fromstring(self.html)
            except Exception:  # noqa: BLE001 - documento estranho: quem chamou usa a soup
                self._lx = False
        return None if self._lx is False else self._lx

    def links_jsf(self) -> list["JsfLink"]:
        """Todos os h:commandLink (jsfcljs) da página."""
        rapido = self._links_jsf_lxml()
        if rapido is not None:
            return rapido
        out = []
        for el in self.soup.find_all(onclick=re.compile("jsfcljs")):
            m = _RE_JSFCLJS.search(el["onclick"])
            if not m:
                continue
            out.append(
                JsfLink(
                    texto=el.get_text(" ", strip=True) or el.get("title") or "",
                    form_id=m.group(1),
                    params=dict(_RE_PARAMS.findall(m.group(2))),
                    onclick=el["onclick"],
                    element=el,
                )
            )
        return out

    def _links_jsf_lxml(self) -> list["JsfLink"] | None:
        doc = self.arvore_lxml()
        if doc is None:
            return None
        out = []
        for el in doc.iter():
            oc = el.get("onclick") if isinstance(el.tag, str) else None
            if not oc or "jsfcljs" not in oc:
                continue
            m = _RE_JSFCLJS.search(oc)
            if not m:
                continue
            out.append(
                JsfLink(
                    texto=_texto_lxml(el) or el.get("title") or "",
                    form_id=m.group(1),
                    params=dict(_RE_PARAMS.findall(m.group(2))),
                    onclick=oc,
                    element=el,
                )
            )
        return out

    def menu_items(self) -> list["MenuItem"]:
        """Itens do menu JSCook (o menu de cima do portal)."""
        import html as _html

        return [
            MenuItem(rotulo=_html.unescape(lbl), acao=acao, form_id=form)
            for lbl, acao, form in _RE_MENU.findall(self.html)
        ]


@dataclass
class JsfLink:
    texto: str
    form_id: str
    params: dict[str, str]
    onclick: str
    element: Any = None


@dataclass
class MenuItem:
    rotulo: str
    acao: str
    form_id: str


def _sem_usuario(texto: str, usuario: str) -> str:
    """Pro log: o texto do SIGAA sem o login do aluno e curto."""
    return (texto.replace(usuario, "<usuario>") if usuario else texto)[:200]


def _sai_do_portal(url: str) -> bool:
    """URL da turma virtual (``/ava/``) ou do módulo mobile: contexto JSF diferente do portal."""
    return "/sigaa/ava/" in url or "/sigaa/mobile/" in url


def eh_portal(page: "Page") -> bool:
    """A resposta é a página inicial do Portal do Discente? (é o que o SIGAA devolve quando o
    clique veio de uma view que ele já descartou)."""
    h = page.html if page.is_html else ""
    return 'id="turmas-portal"' in h or ("menu_form_menu_discente" in h and 'id="portal-docente"' in h)


def form_fields(form) -> dict[str, str]:
    """Campos que um navegador enviaria ao submeter ``form`` (sem os botões)."""
    data: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name:
            continue
        tipo = (el.get("type") or "").lower()
        if tipo in ("submit", "button", "image", "reset", "file"):
            continue
        if tipo in ("checkbox", "radio") and not el.has_attr("checked"):
            continue
        if el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            data[name] = opt.get("value", opt.get_text(strip=True)) if opt else ""
        elif el.name == "textarea":
            data[name] = el.get_text()
        else:
            data[name] = el.get("value", "")
    return data


def _texto_lxml(el) -> str:
    """O ``get_text(" ", strip=True)`` do BeautifulSoup, num elemento do lxml (texto em ordem de
    documento, sem comentários nem o conteúdo de script/style)."""
    partes: list[str] = []

    def andar(no) -> None:
        if no.text and no.text.strip():
            partes.append(no.text.strip())
        for filho in no:
            if isinstance(filho.tag, str) and filho.tag not in _SEM_TEXTO:
                andar(filho)
            if filho.tail and filho.tail.strip():
                partes.append(filho.tail.strip())

    if isinstance(el.tag, str):
        andar(el)
    return " ".join(partes)


_SEM_TEXTO = frozenset(("script", "style", "template"))


def _campos_lxml(page: "Page", form_id: str) -> tuple[str, dict[str, str]] | None:
    """(action, campos) do formulário pelo lxml — o mesmo que ``form_fields(page.form(...))``.
    ``None`` = deixa pro caminho do BeautifulSoup (form não achado, ou form ANINHADO, que só o
    html.parser lê direito)."""
    doc = page.arvore_lxml()
    if doc is None:
        return None
    form = next((f for f in doc.iter("form") if f.get("id") == form_id), None)
    if form is None:
        form = next((f for f in doc.iter("form") if f.get("name") == form_id), None)
    if form is None:
        return None
    campos = list(form.iter("input", "select", "textarea"))
    if "javax.faces.ViewState" in page.html and not any(c.tag == "input" and c.get("name") == "javax.faces.ViewState" for c in campos):
        return None
    data: dict[str, str] = {}
    for el in campos:
        name = el.get("name")
        if not name:
            continue
        tipo = (el.get("type") or "").lower()
        if tipo in ("submit", "button", "image", "reset", "file"):
            continue
        if tipo in ("checkbox", "radio") and el.get("checked") is None:
            continue
        if el.tag == "select":
            opcoes = list(el.iter("option"))
            opt = next((o for o in opcoes if o.get("selected") is not None), None)
            if opt is None and opcoes:  # (elemento do lxml sem filhos é "falso": nada de `or` aqui)
                opt = opcoes[0]
            data[name] = (opt.get("value") if opt.get("value") is not None else _texto_lxml(opt).strip()) if opt is not None else ""
        elif el.tag == "textarea":
            data[name] = el.text_content()
        else:
            data[name] = el.get("value", "")
    return form.get("action") or "", data


FORM_LATIN1 = "application/x-www-form-urlencoded; charset=ISO-8859-1"


def corpo_form(data: dict[str, Any]) -> bytes:
    """Corpo x-www-form-urlencoded em ISO-8859-1 (o que o SIGAA espera)."""
    itens = [(k, x) for k, v in data.items() for x in (v if isinstance(v, (list, tuple)) else [v])]
    return urlencode(itens, encoding="iso-8859-1", errors="xmlcharrefreplace").encode("ascii")


LoginCallback = Callable[[], Awaitable[tuple[str, str]]]
T = TypeVar("T")
Fluxo = Callable[["SigaaClient"], Awaitable[T]]


class _Transporte(httpx.AsyncBaseTransport):
    """Embrulha um transporte httpx de OUTRO dono (``SigaaClient(transport=...)``): fechar o cliente
    não fecha o transporte."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:  # o dono (quem criou o transporte) fecha
        pass


_SSL: Any = None


def ssl_compartilhado() -> Any:
    """Apelido de :func:`_ssl_ctx` (um contexto SSL por processo)."""
    return _ssl_ctx()


def transporte(*, http2: bool = False, max_conexoes: int = 4, keepalive: int | None = None, keepalive_s: float = 4.5) -> httpx.AsyncHTTPTransport:
    """Transporte httpx de UMA sessão (é o padrão de cada ``SigaaClient``).

    Um transporte por sessão, e não um compartilhado entre todas: a piscina de conexões do httpcore
    degrada com muita requisição simultânea (medido, servidor de 150 ms: C=64 → 356 req/s nos dois
    desenhos; C=200 → compartilhado 76 req/s × um por sessão 793 req/s). O contexto SSL é que é
    compartilhado. O SIGAA UFBA fala só HTTP/1.1 (ALPN recusa h2) e fecha conexão ociosa em 5 s
    (``Keep-Alive: timeout=5``), daí ``keepalive_s`` = 4,5; conexão nova custa ~0,1 s de TCP+TLS."""
    return httpx.AsyncHTTPTransport(
        http2=http2,
        verify=_ssl_ctx(),
        limits=httpx.Limits(max_connections=max_conexoes, max_keepalive_connections=keepalive or max_conexoes, keepalive_expiry=keepalive_s),
        retries=1,
    )


class Carga:
    """Teto GLOBAL de requisições simultâneas ao SIGAA (todas as sessões de todos os alunos) e a
    medida de pressão: o pool só abre sessão nova (um login = ~4 viagens) se o SIGAA está folgado."""

    def __init__(self, teto: int) -> None:
        self.teto = max(1, teto)
        self.em_voo = 0
        self._sem = asyncio.Semaphore(self.teto)

    @property
    def pressao(self) -> float:
        """0 = ocioso · 1 = no teto (ou com fila esperando vaga)."""
        return self.em_voo / self.teto

    async def __aenter__(self) -> None:
        self.em_voo += 1  # conta também quem está na fila esperando vaga
        try:
            await asyncio.wait_for(self._sem.acquire(), ESPERA_MAX_S)
        except TimeoutError:
            self.em_voo -= 1
            raise SigaaOcupado("A API está no limite de requisições simultâneas ao SIGAA; tente de novo em instantes.") from None
        except BaseException:
            self.em_voo -= 1
            raise

    async def __aexit__(self, *exc) -> None:
        self._sem.release()
        self.em_voo -= 1


@dataclass
class Compartilhado:
    """Estado do ALUNO (não da tela) dividido entre as sessões dele: cache curto (``memo``), as
    buscas em andamento (singleflight) e dados estáveis (ex.: mapa idTurma↔frontEndIdTurma)."""

    memo: dict[str, tuple[float, Any]] = field(default_factory=dict)
    em_voo: dict[str, asyncio.Future] = field(default_factory=dict)
    dados: dict[str, Any] = field(default_factory=dict)

_SSL: Any = None

#: quanto uma requisição espera por vaga no teto global (``Carga``) antes de desistir com
#: ``SigaaOcupado`` (503 + Retry-After) — falha em vez de empilhar quando o SIGAA está lento
ESPERA_MAX_S = float(os.getenv("SIGAA_ESPERA_MAX_S", "20"))

#: teto de bytes de UMA resposta do SIGAA, já DESCOMPRIMIDA, lido em streaming. Sem isso o httpx
#: carrega o corpo inteiro na memória e descomprime gzip/deflate/brotli SEM limite: um upstream
#: comprometido/mal-intencionado (ou um MITM) devolveria um corpo gigante ou uma "bomba" de
#: compressão (poucos KB → vários GB) e derrubaria o processo da API por falta de memória. O teto é
#: por tipo (HTML × PDF) e a leitura aborta assim que passa, sem materializar o resto.
MAX_RESP_HTML = int(float(os.getenv("SIGAA_MAX_RESP_HTML_MB", "20")) * 1024 * 1024)
MAX_RESP_PDF = int(float(os.getenv("SIGAA_MAX_RESP_PDF_MB", "50")) * 1024 * 1024)


class RespostaGrandeDemais(SigaaError):
    """O SIGAA devolveu uma resposta acima do teto (``SIGAA_MAX_RESP_*_MB``): recusada sem carregar
    o restante na memória (defesa contra resposta gigante / bomba de descompressão do upstream)."""

    codigo = "sigaa_resposta_grande"


async def _ler_com_teto(r: httpx.Response) -> bytes:
    """Lê o corpo de ``r`` em pedaços (já descomprimido pelo httpx) até o teto do tipo; passou do
    teto → aborta com ``RespostaGrandeDemais`` sem acumular o resto."""
    teto = MAX_RESP_PDF if "pdf" in r.headers.get("content-type", "").lower() else MAX_RESP_HTML
    tam = 0
    pedacos: list[bytes] = []
    async for ch in r.aiter_bytes():
        tam += len(ch)
        if tam > teto:
            raise RespostaGrandeDemais(
                f"O SIGAA devolveu mais de {teto // (1024 * 1024)} MB; resposta recusada."
            )
        pedacos.append(ch)
    return b"".join(pedacos)


def _ssl_ctx() -> Any:
    """UM contexto SSL pro processo inteiro. Criar um por ``httpx.AsyncClient`` (o padrão)
    carrega o bundle de CAs de novo a cada cliente: ~11 ms de CPU no event loop por login e
    por requisição pública. O contexto é imutável depois de pronto, então dá pra dividir."""
    global _SSL
    if _SSL is None:
        _SSL = httpx.create_ssl_context()  # o mesmo que o httpx faria (certifi / SSL_CERT_FILE)
    return _SSL


def _plano_submit(html: str, url: str, form_id: str, extra: dict | None, botao) -> tuple[str, dict]:
    """(url do action, campos) de um submit — puro, roda no pool de CPU (``sigaa.cpu``)."""
    page = Page(url=url, status=200, content=b"", content_type="text/html", _html=html)
    rapido = _campos_lxml(page, form_id)
    if rapido is not None:
        action, data = rapido
    else:
        form = page.form(form_id)
        if form is None:
            raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página.")
        action, data = form.get("action") or "", form_fields(form)
    if botao:
        nome, valor = (botao, botao) if isinstance(botao, str) else botao
        data[nome] = valor
    if extra:
        data.update(extra)
    return urljoin(page.url, action or page.url), data


def _plano_clique(html: str, url: str, alvo: str, extra: dict | None) -> tuple[str, dict]:
    """(url do action, campos) do clique num h:commandLink — puro, roda no pool de CPU."""
    page = Page(url=url, status=200, content=b"", content_type="text/html", _html=html)
    return _plano_link(page, SigaaClient._achar_link(page, alvo), extra)


def _plano_link(page: "Page", link: "JsfLink", extra: dict | None) -> tuple[str, dict]:
    rapido = _campos_lxml(page, link.form_id)
    if rapido is not None:
        action, data = rapido
    else:
        form = page.form(link.form_id)
        if form is None:
            raise NavegacaoInvalida(f"Formulário '{link.form_id}' do link não está na página.")
        action, data = form.get("action") or "", form_fields(form)
    data.update(link.params)
    if extra:
        data.update(extra)
    return urljoin(page.url, action or page.url), data


class SigaaClient:
    """Uma sessão de um aluno no SIGAA.

    Exemplo::

        async with SigaaClient() as sigaa:
            await sigaa.login("usuario", "senha")
            portal = await sigaa.portal()
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 40.0,
        min_interval: float = 0.3,
        folga: float = 0.15,
        credenciais: LoginCallback | None = None,
        cookies: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        http2: bool = False,
        conexoes: int = 4,
        compartilhado: Compartilhado | None = None,
        limite: Carga | asyncio.Semaphore | None = None,
        reusar_views: int = 0,
    ) -> None:
        """``min_interval``: intervalo mínimo entre o INÍCIO de duas requisições desta sessão (≤ 1/min_interval
        req/s). ``folga``: pausa mínima entre o FIM de uma requisição e o início da próxima. Com o SIGAA
        respondendo em ~0,45 s, quem manda é a folga — a espera por viagem cai de 0,25 s (o antigo
        min_interval contado do fim) pra 0,15 s, sem nunca disparar colado na resposta anterior.
        ``transport``: transporte httpx de outro dono (testes); sem ele cada sessão cria o seu (``transporte()``,
        ``conexoes`` conexões keep-alive, contexto SSL compartilhado).
        ``compartilhado``: memo/dados do aluno divididos entre as sessões do pool.
        ``limite``: teto GLOBAL de requisições simultâneas ao SIGAA (``Carga``; protege o SIGAA).
        ``reusar_views``: quantas navegações uma página GET (portal, turmas.jsf) pode ser reaproveitada
        (o ViewState dela continua válido no servidor) antes de ser baixada de novo; 0 = nunca reaproveita."""
        self.base_url = (base_url or os.getenv("SIGAA_URL") or BASE_URL).rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
            cookies=cookies,
            transport=_Transporte(transport) if transport is not None else transporte(http2=http2, max_conexoes=conexoes),
        )
        self.lock = asyncio.Lock()
        self._credenciais = credenciais
        self._min_interval = min_interval
        self._folga = folga
        self._ultimo_inicio = 0.0
        self._ultimo = 0.0  # fim da última requisição
        self._ritmo = asyncio.Lock()
        self._limite = limite
        self.logado = bool(cookies)
        self.ultimo_uso = time.time()
        self.portal_cache: Page | None = None
        self.compartilhado = compartilhado or Compartilhado()
        self.pool: PoolSigaa | None = None
        self.reusar_views = reusar_views
        self.navegacoes = 0  # requisições feitas nesta sessão (cada uma pode criar uma view no servidor)
        self.requisicoes = 0
        self._paginas: dict[str, tuple[int, float, Page]] = {}

    @property
    def _memo(self) -> dict[str, tuple[float, Any]]:
        return self.compartilhado.memo

    @property
    def dados(self) -> dict[str, Any]:
        """Dados estáveis do aluno (compartilhados entre as sessões do pool)."""
        return self.compartilhado.dados

    # ------------------------------------------------------------------ cache
    async def memo(self, chave: str, ttl: float, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Cache curto do aluno (dividido entre as sessões do pool): evita reemitir o mesmo
        documento/tela em rotas que dependem dele (ex.: histórico → índices, integralização).

        SINGLEFLIGHT: se outra sessão/rota já está buscando a mesma ``chave``, espera o resultado
        dela em vez de buscar de novo (duas rotas que precisam do histórico = 1 emissão)."""
        comp = self.compartilhado
        hit = comp.memo.get(chave)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        voo = comp.em_voo.get(chave)
        if voo is not None:
            return await asyncio.shield(voo)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        comp.em_voo[chave] = fut
        try:
            valor = await fn()
        except BaseException as e:
            if not fut.done():
                fut.set_exception(e) if isinstance(e, Exception) else fut.cancel()
            fut.exception() if not fut.cancelled() else None  # evita "exception never retrieved"
            raise
        else:
            comp.memo[chave] = (time.monotonic(), valor)
            fut.set_result(valor)
            return valor
        finally:
            if comp.em_voo.get(chave) is fut:
                del comp.em_voo[chave]

    def limpar_cache(self) -> None:
        self._memo.clear()
        self.dados.clear()

    # ------------------------------------------------------------------ infra
    async def __aenter__(self) -> "SigaaClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    def cookies(self) -> dict[str, str]:
        return {c.name: c.value for c in self._http.cookies.jar}

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))

    async def _req(self, method: str, path: str, *, verificar: bool = True, **kw) -> Page:
        # ritmo por sessão: ``min_interval`` entre os INÍCIOS e ``folga`` depois do FIM da anterior
        async with self._ritmo:
            espera = max(self._ultimo_inicio + self._min_interval, self._ultimo + self._folga) - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
            self._ultimo_inicio = time.monotonic()
        self.navegacoes += 1
        self.requisicoes += 1
        # streaming + teto de bytes: o corpo é lido em pedaços e abortado se passar do limite, em vez
        # de o httpx carregar/descomprimir a resposta inteira na memória (ver MAX_RESP_* / _ler_com_teto)
        req = self._http.build_request(method, self._url(path), **kw)
        limite_cm = self._limite if self._limite is not None else contextlib.nullcontext()
        try:
            async with limite_cm:
                r = await self._http.send(req, stream=True, follow_redirects=True)
                try:
                    conteudo = await _ler_com_teto(r)
                finally:
                    await r.aclose()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise SistemaIndisponivel(f"SIGAA não respondeu: {e}") from e
        finally:
            self._ultimo = time.monotonic()
        r._content = conteudo  # replica o que .content guardaria, pra r.encoding decidir igual
        self.navegacoes += len(r.history)  # cada redirect seguido também pode virar uma view
        if _sai_do_portal(path) or _sai_do_portal(str(r.url)):
            # entrar na turma virtual / no módulo mobile muda o contexto JSF da sessão: o portal guardado
            # passa a disparar o menu pra tela atual (medido: o menu voltou /ava/index.jsf com 7 navegações)
            self._paginas.pop(URL_PORTAL, None)
        self.ultimo_uso = time.time()
        if r.status_code >= 500:
            raise SistemaIndisponivel(f"SIGAA respondeu HTTP {r.status_code}")
        page = Page(
            url=str(r.url),
            status=r.status_code,
            content=r.content,
            content_type=r.headers.get("content-type", ""),
            encoding=r.encoding or "iso-8859-1",
            headers={k.lower(): v for k, v in r.headers.items()},
        )
        if verificar:
            self._verificar(page)
        return page

    def _verificar(self, page: Page) -> None:
        if "/expirada.jsp" in page.url or "verTelaLogin.do" in page.url:
            self.logado = False
            raise SessaoExpirada("A sessão do SIGAA expirou.")
        if not page.is_html:
            return
        h = page.html
        if "Comportamento Inesperado" in h:
            raise SigaaError("O SIGAA retornou 'Comportamento Inesperado'.")
        if "O endereço digitado não é válido" in h or "O endere&ccedil;o digitado n&atilde;o &eacute; v&aacute;lido" in h:
            raise NavegacaoInvalida("O SIGAA recusou a navegação (estado da tela inválido).")
        if "Usuário Não Autorizado" in h or "Usu&aacute;rio N&atilde;o Autorizado" in h:
            raise AcessoNegado("O SIGAA negou acesso a esta funcionalidade.")

    # ------------------------------------------------------------ primitivas
    async def get(self, path: str, **kw) -> Page:
        return await self._com_relogin(lambda: self._req("GET", path, **kw))

    async def post(self, path: str, data: dict[str, Any], **kw) -> Page:
        # O SIGAA decodifica o corpo do POST como ISO-8859-1; o httpx mandaria UTF-8 e
        # qualquer busca com acento ("JOSÉ", "computação") voltaria vazia.
        corpo = kw.pop("content", None) or corpo_form(data)  # aceita corpo já pronto (compatibilidade)
        headers = {"Content-Type": FORM_LATIN1, **kw.pop("headers", {})}
        return await self._com_relogin(lambda: self._req("POST", path, content=corpo, headers=headers, **kw))

    async def _com_relogin(self, fn: Callable[[], Awaitable[Page]]) -> Page:
        return await fn()

    async def executar(self, fluxo: Fluxo[T]) -> T:
        """Roda um fluxo de navegação com a sessão travada; se a sessão do SIGAA tiver caído
        e houver credenciais guardadas, reloga e refaz o fluxo UMA vez (as telas antigas morrem
        junto com a sessão, então o fluxo inteiro precisa recomeçar).

        Com pool (``c.pool``), o fluxo vai pra QUALQUER sessão livre do aluno — duas rotas do
        mesmo aluno rodam ao mesmo tempo."""
        if self.pool is not None:
            return await self.pool.executar(fluxo)
        async with self.lock:
            return await self._rodar(fluxo)

    async def _rodar(self, fluxo: Fluxo[T]) -> T:
        """O fluxo nesta sessão (já travada por quem chama), com o relogin automático."""
        try:
            return await fluxo(self)
        except SessaoExpirada:
            if not self._credenciais:
                raise
            await self.relogar()
            return await fluxo(self)
        finally:
            # a árvore do BeautifulSoup do portal guardado é grande e cheia de ciclos: retida
            # em centenas de sessões, cada varredura completa do GC parava o processo por
            # ~300 ms. O HTML fica (ViewState/menu saem dele); a soup é refeita se precisar.
            if self.portal_cache is not None:
                self.portal_cache._soup = None

    async def relogar(self) -> Page:
        if not self._credenciais:
            raise SessaoExpirada("Sessão expirada e sem credenciais guardadas.")
        usuario, senha = await self._credenciais()
        return await self.login(usuario, senha)

    async def paralelo(self, fluxos: Sequence[Fluxo[T]], *, max_sessoes: int | None = None) -> list[T]:
        """Roda vários fluxos INDEPENDENTES e devolve os resultados na mesma ordem.

        Cada fluxo recebe uma sessão só dele enquanto roda (pode navegar à vontade: abrir turma,
        clicar no menu...). Sem pool, roda um depois do outro nesta sessão (mesmo resultado, só mais
        lento). Com pool, esta sessão (que quem chama já está segurando) trabalha junto com as outras
        sessões livres do aluno, e o pool abre sessões novas se a fila compensar. Se algum fluxo
        falhar, os que ainda não começaram são cancelados e o erro do primeiro (pela ordem) sobe.

        Exemplo::

            notas = await c.paralelo([lambda s, t=t: notas_turma(s, t) for t in turmas])
        """
        fluxos = list(fluxos)
        if self.pool is not None and len(fluxos) > 1:
            return await self.pool.paralelo(fluxos, atual=self, max_sessoes=max_sessoes)
        return [await self._rodar(f) for f in fluxos]

    async def pagina(self, path: str, *, reusar: bool = True) -> Page:
        """GET de uma tela de PARTIDA (portal, turmas.jsf) que pode ser reaproveitada enquanto o
        ViewState dela continua guardado no servidor. O MyFaces do SIGAA (estado no servidor) guarda
        as 10 últimas views da sessão; uma view que saiu da janela NÃO dá erro: o SIGAA ignora o
        clique e devolve o portal. Por isso a conta é conservadora: só reaproveita se houve menos de
        ``reusar_views`` requisições nesta sessão desde o último uso da página (toda requisição conta
        como view, até as que não são JSF, e cada redirect conta mais uma)."""
        hit = self._paginas.get(path) if reusar and self.reusar_views > 0 else None
        if hit and self.navegacoes - hit[0] < self.reusar_views and time.monotonic() - hit[1] < 600:
            # quem pede a página vai usá-la já (clique): usar uma view a torna a MAIS RECENTE do
            # servidor de novo (medido: 25 reusos seguidos da mesma view funcionam), então a contagem
            # recomeça a partir desse clique.
            self._paginas[path] = (self.navegacoes + 1, hit[1], hit[2])
            return hit[2]
        page = await self.get(path)
        self._paginas[path] = (self.navegacoes, time.monotonic(), page)
        return page

    def esquecer_paginas(self) -> None:
        self._paginas.clear()

    async def submit(
        self,
        page: Page,
        form_id: str,
        extra: dict[str, str] | None = None,
        botao: str | tuple[str, str] | None = None,
    ) -> Page:
        """Submete um formulário da página (com o ViewState dela)."""
        from .cpu import rodar

        url, data = await rodar(_plano_submit, page.html, page.url, form_id, extra, botao)
        return await self.post(url, data)

    async def clicar(self, page: Page, alvo: str | JsfLink, extra: dict[str, str] | None = None) -> Page:
        """Emula o clique num h:commandLink. ``alvo`` = trecho do onclick, texto do link, ou o JsfLink."""
        from .cpu import rodar

        if isinstance(alvo, JsfLink):  # o link já veio da soup daqui: monta aqui mesmo
            url, data = _plano_link(page, alvo, extra)
        else:  # parse da página + achar o link + campos do form: no pool de CPU
            url, data = await rodar(_plano_clique, page.html, page.url, alvo, extra)
        return await self.post(url, data)

    @staticmethod
    def _achar_link(page: Page, alvo: str) -> JsfLink:
        links = page.links_jsf()
        for ln in links:
            if ln.texto == alvo:
                return ln
        for ln in links:
            if alvo in ln.onclick:
                return ln
        for ln in links:
            if alvo.lower() in ln.texto.lower():
                return ln
        raise NavegacaoInvalida(f"Link '{alvo}' não encontrado na página {page.url}.")

    # ------------------------------------------------------------------ login
    async def login(self, usuario: str, senha: str) -> Page:
        self._http.cookies.clear()
        self._paginas.clear()
        await self._req("GET", "/sigaa/verTelaLogin.do", verificar=False)
        page = await self._req(
            "POST",
            "/sigaa/logar.do?dispatch=logOn",
            content=corpo_form({
                "width": "1920",
                "height": "1080",
                "urlRedirect": "",
                "subsistemaRedirect": "",
                "acao": "",
                "acessibilidade": "",
                "user.login": usuario,
                "user.senha": senha,
            }),
            headers={"Content-Type": FORM_LATIN1},
            verificar=False,
        )
        if "Usuário e/ou senha inválidos" in page.html:
            raise CredenciaisInvalidas("Usuário e/ou senha inválidos.")
        if "logar.do" in page.url and 'name="user.senha"' in page.html:
            # qualquer recusa vira a MESMA mensagem (o texto do SIGAA — "usuário não encontrado",
            # "bloqueado"... — diria se a conta existe e pode trazer o login); o motivo vai só pro log
            msg = page.soup.select_one(".erros, #painel-erros, .info")
            log.info("login recusado pelo SIGAA: %s", _sem_usuario(msg.get_text(" ", strip=True) if msg else "sem mensagem", usuario))
            raise CredenciaisInvalidas("Usuário e/ou senha inválidos.")
        page = await self._pos_login(page)
        self.logado = True
        self.portal_cache = page if "/portais/discente/" in page.url else None
        if self.portal_cache is not None:  # a tela de chegada É o portal: serve de partida pro menu
            self._paginas[URL_PORTAL] = (self.navegacoes, time.monotonic(), page)
        return page

    async def _pos_login(self, page: Page) -> Page:
        """Atravessa as telas intermediárias (avisos, escolha de vínculo) até um portal."""
        for _ in range(4):
            if "telaAvisoLogon" in page.url:
                form = page.soup.find("form")
                botao = form.find("input", {"type": "submit"}) if form else None
                if not botao:
                    break
                page = await self.submit(page, form.get("id"), botao=(botao["name"], botao["value"]))
                continue
            if "vinculos.jsf" in page.url or "Selecione o vínculo" in page.html:
                page = await self._escolher_vinculo(page)
                continue
            break
        return page

    async def _escolher_vinculo(self, page: Page) -> Page:
        """Aluno com mais de um vínculo: entra no primeiro vínculo de discente ATIVO."""
        links = [ln for ln in page.links_jsf() if "vinculo" in ln.onclick.lower()]
        if not links:
            raise SigaaError("Tela de escolha de vínculo sem opções reconhecíveis.")
        return await self.clicar(page, links[0])

    async def logout(self) -> None:
        try:
            await self._req("GET", "/sigaa/logar.do?dispatch=logOff", verificar=False)
        finally:
            self.logado = False

    # ---------------------------------------------------------------- portal
    async def portal(self) -> Page:
        """Página inicial do Portal do Discente (ponto de partida de quase tudo). Sempre baixa de novo."""
        page = await self.get(URL_PORTAL)
        self.portal_cache = page
        self._paginas[URL_PORTAL] = (self.navegacoes, time.monotonic(), page)
        return page

    async def menu(self, acao: str, portal: Page | None = None) -> Page:
        """Dispara um item do menu do portal. ``acao`` = trecho do bean (``portalDiscente.historico``) ou rótulo.

        Sem ``portal``, reaproveita a última página do portal desta sessão enquanto o ViewState dela
        ainda vale (``reusar_views``) — economiza 1 viagem por item de menu. Se o SIGAA recusar o
        ViewState reaproveitado, baixa o portal de novo e repete UMA vez."""
        reusado = portal is None and self.reusar_views > 0 and URL_PORTAL in self._paginas
        portal = portal or await self.pagina(URL_PORTAL)
        try:
            page = await self._disparar_menu(portal, acao)
        except NavegacaoInvalida:
            if not reusado:
                raise
            page = None
        if reusado and (page is None or eh_portal(page) or _sai_do_portal(page.url)):
            # a view reaproveitada já não valia (o SIGAA devolve o portal, ou a tela em que a sessão está): baixa e repete
            self._paginas.pop(URL_PORTAL, None)
            page = await self._disparar_menu(await self.portal(), acao)
        return page

    async def _disparar_menu(self, portal: Page, acao: str) -> Page:
        itens = portal.menu_items()
        item = next((i for i in itens if acao in i.acao), None) or next(
            (i for i in itens if acao.lower() == i.rotulo.lower()), None
        )
        if item is None:
            raise NavegacaoInvalida(f"Item de menu '{acao}' não existe para este usuário.")
        return await self.post(
            "/sigaa/portais/discente/discente.jsf",
            {item.form_id: item.form_id, "jscook_action": item.acao, "javax.faces.ViewState": portal.viewstate or ""},
        )

    async def manter_viva(self) -> bool:
        """Toca o SIGAA pra sessão não expirar. Devolve False se ela já tinha caído."""
        try:
            page = await self._req("GET", URL_PORTAL)
            self._paginas[URL_PORTAL] = (self.navegacoes, time.monotonic(), page)
            return True
        except SessaoExpirada:
            return False
