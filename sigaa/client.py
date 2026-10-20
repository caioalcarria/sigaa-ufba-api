"""Cliente assíncrono do SIGAA (testado no SIGAA da UFBA, v4.13).

O SIGAA é um sistema JSF/Struts *stateful*: cada tela guarda estado no servidor
(o ``javax.faces.ViewState``) e a navegação só é aceita a partir de links que o
próprio sistema gerou. Por isso este cliente:

* serializa a navegação de uma sessão (``asyncio.Lock``) — duas telas abertas ao
  mesmo tempo na mesma sessão quebram o ViewState uma da outra;
* sabe "clicar" nos ``h:commandLink`` (função JS ``jsfcljs``) e nos itens do
  menu JSCook do portal sem precisar de navegador;
* trata a tela de avisos pós-login e a escolha de vínculo;
* detecta sessão expirada, erro do sistema e navegação recusada, e consegue
  relogar sozinho se as credenciais forem mantidas em memória.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from .errors import (
    AcessoNegado,
    CredenciaisInvalidas,
    NavegacaoInvalida,
    SessaoExpirada,
    SigaaError,
    SigaaOcupado,
    SistemaIndisponivel,
)

#: SIGAA alvo. Respeita SIGAA_URL em TODO SigaaClient criado sem base_url (inclusive as sessões
#: anônimas das rotas públicas) — senão um teste contra o SIGAA simulado vazaria pro SIGAA real.
BASE_URL = os.getenv("SIGAA_URL", "https://sigaa.ufba.br").rstrip("/")
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

_SSL: Any = None

#: teto GLOBAL de requisições simultâneas ao SIGAA (somando todas as sessões do processo):
#: protege o SIGAA de rajada e vira backpressure — quem passa do teto espera na fila
MAX_CONEXOES = int(os.getenv("SIGAA_MAX_CONEXOES", "50"))
#: quanto uma requisição espera por vaga antes de desistir com ``SigaaOcupado`` (503)
ESPERA_MAX_S = float(os.getenv("SIGAA_ESPERA_MAX_S", "20"))
_vagas: dict[int, tuple[Any, asyncio.Semaphore]] = {}


def _semaforo() -> asyncio.Semaphore | None:
    """Um semáforo por event loop (asyncio.Semaphore se prende ao loop do 1º uso)."""
    if MAX_CONEXOES <= 0:
        return None
    loop = asyncio.get_running_loop()
    par = _vagas.get(id(loop))
    if par is None or par[0] is not loop:
        par = (loop, asyncio.Semaphore(MAX_CONEXOES))
        _vagas.clear()  # um loop vivo por processo; descarta o de testes antigos
        _vagas[id(loop)] = par
    return par[1]


def em_uso() -> int:
    """Requisições ao SIGAA em andamento agora (pro /v1/status)."""
    sem = _vagas and next(iter(_vagas.values()))[1]
    return (MAX_CONEXOES - sem._value) if sem else 0


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
        min_interval: float = 0.25,
        credenciais: LoginCallback | None = None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("SIGAA_URL") or BASE_URL).rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
            cookies=cookies,
            verify=_ssl_ctx(),
        )
        self.lock = asyncio.Lock()
        self._credenciais = credenciais
        self._min_interval = min_interval
        self._ultimo = 0.0
        self.logado = bool(cookies)
        self.ultimo_uso = time.time()
        self.portal_cache: Page | None = None
        self._memo: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------ cache
    async def memo(self, chave: str, ttl: float, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Cache curto por sessão: evita reemitir o mesmo documento/tela em rotas que
        dependem dele (ex.: histórico → índices, integralização, pendências)."""
        agora = time.monotonic()
        hit = self._memo.get(chave)
        if hit and agora - hit[0] < ttl:
            return hit[1]
        valor = await fn()
        self._memo[chave] = (agora, valor)
        return valor

    def limpar_cache(self) -> None:
        self._memo.clear()

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
        espera = self._min_interval - (time.monotonic() - self._ultimo)
        if espera > 0:
            await asyncio.sleep(espera)
        sem = _semaforo()
        if sem is not None:
            try:
                await asyncio.wait_for(sem.acquire(), ESPERA_MAX_S)
            except TimeoutError:
                raise SigaaOcupado("A API está no limite de requisições simultâneas ao SIGAA; tente de novo em instantes.") from None
        try:
            r = await self._http.request(method, self._url(path), **kw)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise SistemaIndisponivel(f"SIGAA não respondeu: {e}") from e
        finally:
            if sem is not None:
                sem.release()
            self._ultimo = time.monotonic()
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

    async def executar(self, fluxo: Callable[["SigaaClient"], Awaitable[Any]]) -> Any:
        """Roda um fluxo de navegação com a sessão travada; se a sessão do SIGAA tiver caído
        e houver credenciais guardadas, reloga e refaz o fluxo UMA vez (as telas antigas morrem
        junto com a sessão, então o fluxo inteiro precisa recomeçar)."""
        async with self.lock:
            try:
                return await fluxo(self)
            except SessaoExpirada:
                if not self._credenciais:
                    raise
                usuario, senha = await self._credenciais()
                await self.login(usuario, senha)
                return await fluxo(self)
            finally:
                # a árvore do BeautifulSoup do portal guardado é grande e cheia de ciclos: retida
                # em centenas de sessões, cada varredura completa do GC parava o processo por
                # ~300 ms. O HTML fica (ViewState/menu saem dele); a soup é refeita se precisar.
                if self.portal_cache is not None:
                    self.portal_cache._soup = None

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
            msg = page.soup.select_one(".erros, #painel-erros, .info")
            raise CredenciaisInvalidas(msg.get_text(" ", strip=True) if msg else "Login recusado pelo SIGAA.")
        page = await self._pos_login(page)
        self.logado = True
        self.portal_cache = page if "/portais/discente/" in page.url else None
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
        """Página inicial do Portal do Discente (ponto de partida de quase tudo)."""
        page = await self.get("/sigaa/verPortalDiscente.do")
        self.portal_cache = page
        return page

    async def menu(self, acao: str, portal: Page | None = None) -> Page:
        """Dispara um item do menu do portal. ``acao`` = trecho do bean (``portalDiscente.historico``) ou rótulo."""
        portal = portal or await self.portal()
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
            await self._req("GET", "/sigaa/verPortalDiscente.do")
            return True
        except SessaoExpirada:
            return False
