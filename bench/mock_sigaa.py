"""SIGAA SIMULADO — um SIGAA UFBA de mentira, local, pra medir a sigaa-api sob carga sem tocar na UFBA.

    .venv/bin/python bench/mock_sigaa.py --porta 8111                 # latência padrão (calibrada)
    .venv/bin/python bench/mock_sigaa.py --porta 8111 --fator 0       # sem latência (só CPU da API)
    SIGAA_URL=http://127.0.0.1:8111  → a API/SigaaClient falam com ele como se fosse o real

O QUE ELE REPRODUZ
* As TELAS: serve as fixtures ANONIMIZADAS de ``tests/fixtures/**`` (HTML real do SIGAA, com dados
  trocados por fictícios) + PDFs SINTÉTICOS (``bench/sintetico.py``: histórico e declaração).
* O PROTOCOLO: login (``verTelaLogin.do`` → ``logar.do`` → tela de avisos → portal), cookie
  ``JSESSIONID`` por sessão, ``javax.faces.ViewState`` PRÓPRIO por sessão (cada tela servida ganha um
  ``j_idN`` novo; POST com ViewState que a sessão não emitiu — ou que já saiu da janela de
  ``--views`` telas — recebe "O endereço digitado não é válido"), menu JSCook (``jscook_action``),
  cliques ``jsfcljs`` (o mock descobre QUAL link da tela de origem foi clicado), estado de turma
  virtual por sessão, sessão expirada (``expirada.jsp``) por ociosidade, logout.
* A LATÊNCIA: por classe de resposta (padrão ≈ 450 ms, PDF ≈ 3,5 s, POST do login ≈ 0,7 s →
  login completo ≈ 3 s, redirect ≈ 80 ms) × ``--fator``, com ``--jitter`` (±fração, uniforme).
  ``--max-concorrencia N`` limita quantas respostas o "servidor" processa ao mesmo tempo (as outras
  esperam na fila) — pra simular um SIGAA saturado.
* Qualquer usuário entra; senha ``errada`` é recusada ("Usuário e/ou senha inválidos").

CONTROLE (JSON): ``GET /__mock/config`` · ``POST /__mock/config`` {fator, jitter, latencias:{classe:s},
max_concorrencia, ttl_sessao, views} · ``GET /__mock/stats`` (requisições por regra, misses, sessões,
pico de concorrência) · ``POST /__mock/reset`` (zera stats) · ``POST /__mock/expirar`` (derruba todas as
sessões — testa o relogin da API).

Tudo que o mock NÃO sabe responder vira um MISS (listado em /__mock/stats) e devolve a tela de
"Comportamento Inesperado" — o SigaaClient transforma isso em erro 502, então rota não coberta aparece.
"""

from __future__ import annotations

import argparse
import asyncio
import html as H
import random
import re
import secrets
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl

from bs4 import BeautifulSoup
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

AQUI = Path(__file__).resolve().parent
FIX = AQUI.parent / "tests" / "fixtures"
CT_HTML = "text/html;charset=ISO-8859-1"

# ------------------------------------------------------------------ configuração
LATENCIAS_PADRAO = {
    "padrao": 0.45,  # 1 ida/volta com tela (medido: GET portal ≈ 450 ms)
    "pdf": 3.5,  # o SIGAA gerando o PDF do histórico/declaração
    "login": 0.7,  # POST logar.do; + 4 telas "padrao" + 2×0,25 s do min_interval do cliente ≈ 3 s no total
    "redirect": 0.08,  # 302 sem trabalho no servidor
    "publico": 0.45,  # telas públicas (sem login)
    "ajax": 0.25,  # respostas a4j (parciais)
}


@dataclass
class Config:
    fator: float = 1.0
    jitter: float = 0.10
    latencias: dict = field(default_factory=lambda: dict(LATENCIAS_PADRAO))
    max_concorrencia: int = 0  # 0 = sem limite
    ttl_sessao: float = 1800.0  # ociosidade até a sessão expirar (s)
    views: int = 20  # telas (ViewStates) lembradas por sessão
    seed: int | None = None


CFG = Config()
_rng = random.Random()
_sem: asyncio.Semaphore | None = None


def latencia(classe: str) -> float:
    base = CFG.latencias.get(classe, CFG.latencias["padrao"]) * CFG.fator
    if base <= 0:
        return 0.0
    j = CFG.jitter
    return max(0.0, base * (1 + _rng.uniform(-j, j))) if j else base


# ------------------------------------------------------------------ fixtures
_cache: dict[str, bytes] = {}
_links_cache: dict[str, list[dict]] = {}


def fixture(nome: str) -> bytes:
    if nome not in _cache:
        if nome.startswith("@"):
            from sintetico import declaracao_pdf, historico_pdf  # noqa: PLC0415

            _cache[nome] = {"@historico.pdf": historico_pdf, "@declaracao.pdf": declaracao_pdf}[nome]()
        else:
            b = (FIX / nome).read_bytes()
            if any(x > 127 for x in b):
                try:  # algumas fixtures foram salvas em UTF-8; o SIGAA real serve ISO-8859-1
                    b = b.decode("utf-8").encode("iso-8859-1", "xmlcharrefreplace")
                except UnicodeDecodeError:
                    pass
            _cache[nome] = b
    return _cache[nome]


_RE_JSFCLJS = re.compile(r"getElementById\('([^']+)'\),\s*\{(.*?)\},\s*'([^']*)'\)", re.S)
_RE_PARAMS = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")


def links(nome: str) -> list[dict]:
    """Os h:commandLink (jsfcljs) da fixture — pra descobrir qual foi clicado."""
    if nome not in _links_cache:
        out = []
        if not nome.startswith("@"):
            soup = BeautifulSoup(fixture(nome).decode("iso-8859-1", "replace"), "lxml")
            for el in soup.find_all(onclick=re.compile("jsfcljs")):
                m = _RE_JSFCLJS.search(el["onclick"])
                if m:
                    out.append({
                        "texto": el.get_text(" ", strip=True) or el.get("title") or "",
                        "form": m.group(1),
                        "params": dict(_RE_PARAMS.findall(m.group(2))),
                        "onclick": el["onclick"],
                    })
        _links_cache[nome] = out
    return _links_cache[nome]


# ------------------------------------------------------------------ sessões
@dataclass
class Sessao:
    id: str
    logado: bool = False
    usuario: str = ""
    criada: float = field(default_factory=time.time)
    ultimo: float = field(default_factory=time.time)
    views: OrderedDict = field(default_factory=OrderedDict)  # token → fixture que o emitiu
    cont: int = 1
    turma: str | None = None  # frontEndIdTurma aberto na turma virtual
    em_voo: int = 0


SESSOES: dict[str, Sessao] = {}
STATS = {"req": Counter(), "regra": Counter(), "misses": [], "status": Counter(), "pico": 0, "em_voo": 0,
         "logins": 0, "expiradas": 0, "vs_invalido": 0, "inicio": time.time()}


def nova_sessao() -> Sessao:
    sid = secrets.token_hex(16).upper() + ".mock"
    s = Sessao(sid)
    SESSOES[sid] = s
    return s


# ------------------------------------------------------------------ resposta
@dataclass
class Resp:
    corpo: bytes = b""
    status: int = 200
    ctype: str = CT_HTML
    classe: str = "padrao"
    headers: dict = field(default_factory=dict)
    regra: str = ""
    origem_nome: str | None = None  # fixture servida (vira "origem" dos ViewStates dela)


_RE_VS_TAG = re.compile(rb'<input[^>]*javax\.faces\.ViewState[^>]*>', re.I)
_RE_VALUE = re.compile(rb'value="[^"]*"')


def com_viewstate(sess: Sessao, corpo: bytes, nome: str) -> bytes:
    """Troca o ViewState da fixture por um token NOVO desta sessão (como o JSF faz a cada tela)."""
    token = f"j_id{sess.cont}"
    sess.cont += 1
    sess.views[token] = nome
    while len(sess.views) > max(1, CFG.views):
        sess.views.popitem(last=False)
    novo = b'value="' + token.encode() + b'"'
    return _RE_VS_TAG.sub(lambda m: _RE_VALUE.sub(novo, m.group(0), count=1), corpo)


def tela(nome: str, regra: str, classe: str = "padrao", status: int = 200) -> Resp:
    ct = "application/pdf" if nome.endswith(".pdf") else ("text/xml;charset=ISO-8859-1" if nome.endswith(".xml") else CT_HTML)
    hd = {"Content-Disposition": f'attachment; filename="{nome.lstrip("@")}"'} if nome.endswith(".pdf") else {}
    return Resp(fixture(nome), status, ct, classe, hd, regra, nome)


def redirect(local: str, regra: str, classe: str = "redirect") -> Resp:
    return Resp(b"", 302, CT_HTML, classe, {"Location": local}, regra)


def _pagina_simples(titulo: str, msg: str, form: str = "") -> bytes:
    return (
        f"<html><head><title>{titulo}</title></head><body><div id='painel-erros'><ul class='erros'><li>{msg}</li></ul></div>"
        f"{form}</body></html>"
    ).encode("iso-8859-1", "xmlcharrefreplace")


PAG_LOGIN = (
    "<html><head><title>SIGAA - Sistema Integrado de Gestão de Atividades Acadêmicas</title></head><body>"
    "<form name='loginForm' method='post' action='/sigaa/logar.do?dispatch=logOn'>"
    "<input type='hidden' name='width' value=''/><input type='hidden' name='height' value=''/>"
    "<input type='hidden' name='urlRedirect' value=''/><input type='hidden' name='subsistemaRedirect' value=''/>"
    "<input type='hidden' name='acao' value=''/><input type='hidden' name='acessibilidade' value=''/>"
    "<input type='text' name='user.login'/><input type='password' name='user.senha'/>"
    "<input type='submit' value='Entrar'/></form></body></html>"
)
PAG_AVISO = (
    "<html><head><title>SIGAA - Avisos</title></head><body><h2>Avisos</h2><p>Aviso de teste do SIGAA simulado.</p>"
    "<form id='j_id_jsp_1_1' name='j_id_jsp_1_1' method='post' action='/sigaa/telaAvisoLogon.jsf'>"
    "<input type='hidden' name='j_id_jsp_1_1' value='j_id_jsp_1_1'/>"
    "<input type='submit' name='j_id_jsp_1_1:j_id_jsp_1_2' value='Continuar &gt;&gt;'/>"
    "<input type='hidden' name='javax.faces.ViewState' id='javax.faces.ViewState' value='j_id1'/></form></body></html>"
)
PAG_EXPIRADA = _pagina_simples("SIGAA - Sessão Expirada", "Sua sessão expirou. Faça o login novamente.")
PAG_INVALIDA = _pagina_simples("SIGAA", "O endereço digitado não é válido.")
PAG_INESPERADO = _pagina_simples("SIGAA - Erro", "Comportamento Inesperado! (SIGAA simulado: tela não mapeada)")


# ------------------------------------------------------------------ roteamento
@dataclass
class Ctx:
    req: Request
    metodo: str
    caminho: str
    query: dict
    form: dict
    sess: Sessao
    origem: str | None  # fixture que emitiu o ViewState enviado
    link: dict | None  # link jsfcljs clicado (quando dá pra saber)

    def acao(self) -> str:
        return self.form.get("jscook_action", "")


def link_clicado(origem: str | None, form: dict) -> dict | None:
    """Qual link da tela de origem foi clicado: todas as CHAVES dos params dele vieram no POST
    (o valor pode ter sido trocado — ex.: o serviço muda o ``id`` da estrutura); desempata por valores iguais."""
    if not origem:
        return None
    melhor, pontos = None, (-1, -1)
    for ln in links(origem):
        ps = ln["params"]
        if ln["form"] not in form or not all(k in form for k in ps):
            continue
        p = (len(ps), sum(form.get(k) == v for k, v in ps.items()))
        if p > pontos:
            melhor, pontos = ln, p
    return melhor


# menu JSCook do portal (jscook_action contém a chave) → tela
MENU = [
    ("portalDiscente.historico", "@historico.pdf", "pdf"),
    ("declaracaoVinculo.emitirDeclaracao", "@declaracao.pdf", "pdf"),
    ("portalDiscente.atestadoMatricula", "academico/comprovante_inscricao.html", "padrao"),
    ("matriculaGraduacao.verComprovanteSolicitacoes", "academico/comprovante_solicitacao.html", "padrao"),
    ("trancamentoMatricula.iniciarMeusTrancamentos", "academico/trancamentos.html", "padrao"),
    ("trancamentoPrograma.exibirMinhasSolicitacoes", "academico/suspensoes.html", "padrao"),
    ("solicitacaoRegistroAtividadeAutonomaMBean.listar", "academico/atividades_autonomas.html", "padrao"),
    ("solicitacaoAproveitamentoEstudosMBean.listar", "academico/aproveitamentos.html", "padrao"),
    ("buscaDiplomaDigitalMBean.iniciarBuscaDiscente", "academico/diploma.html", "padrao"),
    ("avaliacaoInstitucionalAnterior.listaAnterior", "academico/avaliacoes_anteriores.html", "padrao"),
    ("curriculo.popularBuscaGeral", "consultas/estrutura_form.html", "padrao"),
    ("buscaTurmaBean.popularBuscaGeral", "consultas/turmas_busca.html", "padrao"),
    ("componenteCurricular.popularBuscaDiscente", "consultas/componentes_busca.html", "padrao"),
    ("curso.popularBuscaGeral", "consultas/cursos_busca.html", "padrao"),
    ("unidade.popularBuscaGeral", "consultas/unidades_busca.html", "padrao"),
    ("calendario.iniciarBusca", "consultas/calendario_lista.html", "padrao"),
]

# submits de formulário (POST sem link clicado): (origem (prefixo), campo que tem que vir, destino)
SUBMITS: list[tuple[str, str, str]] = [
    ("consultas/estrutura", "busca:j_id", "consultas/estruturas_busca.html"),  # botão Buscar (nome gerado)
    ("consultas/estrutura", "busca:curso", "consultas/estrutura_form.html"),  # troca do combo de curso
    ("consultas/turmas_busca", "form:buttonBuscar", "consultas/turmas_busca.html"),
    ("consultas/componente", "formBusca", "consultas/componentes_busca.html"),
    ("consultas/cursos_busca", "busca", "consultas/cursos_busca.html"),
    ("consultas/unidades_busca", "formBuscaUnidade", "consultas/unidades_busca.html"),
    ("consultas/publico/componentes_busca", "form", "consultas/publico/componentes_busca_codigo.html"),
    ("consultas/publico/turmas_form", "formTurma", "consultas/publico/turmas_resultado.html"),
]

# cliques: (fixture de origem (prefixo), trecho do onclick OU texto exato do link, destino)
TV = "turma_virtual/"
TV_MENU = {  # rótulo do menu lateral da turma virtual → tela
    "notícias": "noticias.html", "ver notas": "notas_subavaliacoes.html", "notas": "notas_subavaliacoes.html",
    "frequência": "frequencia.html", "participantes": "participantes.html", "plano de curso": "plano_curso.html",
    "conteúdo": "conteudos.html", "conteúdos": "conteudos.html", "conteúdo/página web": "conteudos.html", "referências": "referencias.html",
    "vídeos": "videos_vazio.html", "arquivos": "arquivos.html", "tarefas": "tarefas_vazio.html",
    "questionários": "questionarios_vazio.html", "enquetes": "enquetes_vazio.html", "avaliações": "avaliacoes.html",
    "fóruns": "foruns.html", "fórum": "foruns.html", "linha do tempo": "linha_tempo.html", "grupos": "grupo_vazio.html",
    "meu grupo": "grupo_vazio.html", "estatísticas": "estatisticas.html", "situação dos discentes": "estatisticas.html",
    "principal": "principal_matc89.html", "programa": "programa_indisponivel.html",
}
TV_PRINCIPAIS = ["principal_matc89.html", "principal_mata07.html", "principal_matb19.html", "principal_ementa.html"]


def _principal_da_turma(fe: str | None) -> str:
    return TV + TV_PRINCIPAIS[sum(map(ord, fe or "")) % len(TV_PRINCIPAIS)]


def _norm(s: str) -> str:
    import unicodedata

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip().lower()


CLIQUES: list[tuple[str, str, str]] = [
    ("portal/portal.html", "meusDadosPessoais", "portal/dados_pessoais.html"),
    ("portal/mobile_home.html", "lnkMinhasTurmas", "turma_virtual/turmas_mobile.html"),
    ("turma_virtual/turmas_mobile.html", "lnkVerTodas", "portal/mobile_turmas_todas.html"),
    ("portal/forum_lista.html", "", "turma_virtual/forum_topico.html"),
    ("consultas/estruturas_busca.html", "resultado:relatorio", "consultas/estrutura_relatorio.html"),
    ("consultas/estruturas_busca.html", "resultado:detalhar", "consultas/estrutura_detalhar.html"),
    ("consultas/estruturas_busca.html", "resultado:declaracaoPrazoMaximo", "consultas/estrutura_declaracao.html"),
    ("consultas/calendario_lista.html", "'id'", "consultas/calendario.html"),
    ("consultas/componentes_busca.html", "", "consultas/componente_relatorio.html"),
    ("consultas/publico/curso_curriculos.html", "Relat", "consultas/publico/estrutura_relatorio.html"),
    ("consultas/publico/curso_curriculos.html", "", "consultas/publico/estrutura_detalhes.html"),
    ("consultas/publico/componentes_busca", "", "consultas/publico/componente_detalhe_busca.html"),
]

GETS: dict[str, tuple[str, str]] = {  # caminho → (tela, classe)
    "/sigaa/portais/discente/turmas.jsf": ("turma_virtual/turmas_todas.html", "padrao"),
    "/sigaa/mobile/touch/menu.jsf": ("portal/mobile_home.html", "padrao"),
    "/sigaa/portais/discente/perfil.jsf": ("portal/perfil.html", "padrao"),
    "/sigaa/verMenuPrincipal.do": ("portal/modulos.html", "padrao"),
    "/sigaa/graduacao/componente/view_painel.jsf": ("consultas/componente_painel.html", "ajax"),
    "/sigaa/graduacao/turma/view_painel.jsf": ("consultas/turma_painel.html", "ajax"),
    # públicas (sem login)
    "/sigaa/public/curso/lista.jsf": ("consultas/publico/curso_lista_G.html", "publico"),
    "/sigaa/public/curso/portal.jsf": ("consultas/publico/curso_portal.html", "publico"),
    "/sigaa/public/curso/curriculo.jsf": ("consultas/publico/curso_curriculos.html", "publico"),
    "/sigaa/public/curso/calendario.jsf": ("consultas/publico/curso_calendario.html", "publico"),
    "/sigaa/public/curso/noticias.jsf": ("consultas/publico/curso_noticias.html", "publico"),
    "/sigaa/public/curso/ppp.jsf": ("consultas/publico/curso_ppp.html", "publico"),
    "/sigaa/public/componentes/busca_componentes.jsf": ("consultas/publico/componentes_busca_codigo.html", "publico"),
    "/sigaa/link/public/ensino/visualizarComponente/": ("consultas/publico/componente_resumo_link.html", "publico"),
    "/sigaa/public/turmas/listar.jsf": ("consultas/publico/turmas_form.html", "publico"),
    "/sigaa/public/departamento/portal.jsf": ("consultas/publico/departamento_portal.html", "publico"),
    "/sigaa/public/departamento/professores.jsf": ("consultas/publico/departamento_professores.html", "publico"),
    "/sigaa/public/departamento/componentes.jsf": ("consultas/publico/departamento_componentes.html", "publico"),
    "/sigaa/public/docente/portal.jsf": ("consultas/publico/docente_portal.html", "publico"),
    "/sigaa/public/centro/lista.jsf": ("consultas/publico/centros_lista.html", "publico"),
}


def rotear(c: Ctx) -> Resp | None:
    p, m = c.caminho, c.metodo
    # ---------------------------------------------------------------- login / sessão
    if p == "/sigaa/verTelaLogin.do":
        return Resp(PAG_LOGIN.encode("iso-8859-1"), regra="login:tela")
    if p == "/sigaa/logar.do":
        disp = c.query.get("dispatch")
        if disp == "logOff":
            c.sess.logado = False
            SESSOES.pop(c.sess.id, None)
            return redirect("/sigaa/verTelaLogin.do", "logout")
        if disp == "logOn" and m == "POST":
            if c.form.get("user.senha") == "errada" or not c.form.get("user.login"):
                return Resp(_pagina_simples("SIGAA", "Usuário e/ou senha inválidos", PAG_LOGIN), regra="login:recusado", classe="login")
            c.sess.logado, c.sess.usuario = True, c.form["user.login"]
            STATS["logins"] += 1
            return redirect("/sigaa/telaAvisoLogon.jsf", "login:ok", classe="login")
    if p == "/sigaa/telaAvisoLogon.jsf":
        if m == "GET":
            return Resp(com_viewstate(c.sess, PAG_AVISO.encode("iso-8859-1"), "@aviso"), regra="login:aviso")
        return redirect("/sigaa/portais/discente/discente.jsf", "login:aviso_ok", classe="padrao")
    if p == "/sigaa/expirada.jsp":
        return Resp(PAG_EXPIRADA, regra="expirada")

    # ---------------------------------------------------------------- portal + menu
    if p in ("/sigaa/verPortalDiscente.do", "/sigaa/portais/discente/discente.jsf") and m == "GET":
        return tela("portal/portal.html", "portal")
    if p == "/sigaa/portais/discente/discente.jsf" and m == "POST" and c.acao():
        for chave, destino, classe in MENU:
            if chave in c.acao():
                return tela(destino, f"menu:{chave}", classe)
        return None
    if m == "GET":
        alvo = GETS.get(p) or next((v for k, v in GETS.items() if k.endswith("/") and p.startswith(k)), None)
        if alvo:
            nome = alvo[0]
            if p == "/sigaa/public/curso/lista.jsf" and c.query.get("nivel", "G") != "G":
                nome = "consultas/publico/curso_lista_S.html"
            return tela(nome, f"get:{p if p in GETS else p.rsplit('/', 1)[0] + '/'}", alvo[1])
    if p == "/sigaa/relatorioProcessamento":
        return tela("academico/processamento_389847.html", "processamento")

    # ---------------------------------------------------------------- cliques jsfcljs
    if m == "POST" and c.link is not None:
        ln, org = c.link, c.origem or ""
        if "frontEndIdTurma" in ln["params"]:  # entrar na turma virtual
            c.sess.turma = ln["params"]["frontEndIdTurma"]
            return tela(_principal_da_turma(c.sess.turma), "tv:abrir")
        if org.startswith(TV) and ln["form"] == "formMenu":
            dest = TV_MENU.get(_norm(ln["texto"]))
            if dest:
                return tela(TV + dest, f"tv:{_norm(ln['texto'])}")
        for o, trecho, dest in CLIQUES:
            if org.startswith(o) and (trecho in ln["onclick"] or trecho == ln["texto"]):
                return tela(dest, f"clique:{o}:{trecho}")
    if m == "POST" and c.origem:
        for o, campo, dest in SUBMITS:
            if c.origem.startswith(o) and any(k.startswith(campo) for k in c.form):
                return tela(dest, f"submit:{o}:{campo}")
    return None


PROTEGIDO = re.compile(r"^/sigaa/(portais|ava|mobile|graduacao|verPortalDiscente|relatorioProcessamento|telaAvisoLogon|geral|diplomas|portal)")


# ------------------------------------------------------------------ handler
async def tratar(req: Request) -> Response:
    corpo = await req.body()
    caminho = req.url.path
    query = dict(parse_qsl(req.url.query, keep_blank_values=True))
    form = dict(parse_qsl(corpo.decode("iso-8859-1"), keep_blank_values=True)) if corpo and req.method == "POST" else {}
    STATS["req"][f"{req.method} {caminho}"] += 1

    agora = time.time()
    sid = req.cookies.get("JSESSIONID")
    sess = SESSOES.get(sid) if sid else None
    if sess and agora - sess.ultimo > CFG.ttl_sessao:
        SESSOES.pop(sess.id, None)
        sess = None
        STATS["expiradas"] += 1
    set_cookie = None
    resp: Resp | None = None
    if sess is None:
        if PROTEGIDO.match(caminho) and caminho != "/sigaa/telaAvisoLogon.jsf":
            resp = redirect("/sigaa/expirada.jsp", "sem_sessao")
        sess = nova_sessao()
        set_cookie = sess.id
    sess.ultimo = agora

    if resp is None and PROTEGIDO.match(caminho) and not sess.logado and not caminho.startswith("/sigaa/telaAvisoLogon"):
        resp = redirect("/sigaa/expirada.jsp", "nao_logado")

    origem = None
    if resp is None and req.method == "POST" and "javax.faces.ViewState" in form:
        vs = form["javax.faces.ViewState"]
        origem = sess.views.get(vs)
        if origem is None:
            STATS["vs_invalido"] += 1
            resp = Resp(PAG_INVALIDA, regra="viewstate_invalido")
        else:
            sess.views.move_to_end(vs)

    if resp is None:
        ctx = Ctx(req, req.method, caminho, query, form, sess, origem, link_clicado(origem, form))
        resp = rotear(ctx)
        if resp is None:
            STATS["misses"].append({
                "metodo": req.method, "caminho": caminho, "query": query,
                "form": {k: v for k, v in form.items() if k not in ("user.senha",)},
                "origem": origem, "link": ctx.link and {k: ctx.link[k] for k in ("texto", "form", "params")},
            })
            del STATS["misses"][:-200]
            resp = Resp(PAG_INESPERADO, regra="MISS")

    # tempo de "servidor" (com fila se --max-concorrencia)
    STATS["em_voo"] += 1
    STATS["pico"] = max(STATS["pico"], STATS["em_voo"])
    try:
        dt = latencia(resp.classe if not caminho.startswith("/sigaa/public") or resp.classe != "padrao" else "publico")
        if _sem is not None:
            async with _sem:
                if dt:
                    await asyncio.sleep(dt)
        elif dt:
            await asyncio.sleep(dt)
    finally:
        STATS["em_voo"] -= 1

    corpo_out = resp.corpo
    if resp.origem_nome and resp.ctype.startswith("text/html") and b"javax.faces.ViewState" in corpo_out:
        corpo_out = com_viewstate(sess, corpo_out, resp.origem_nome)
    STATS["regra"][resp.regra] += 1
    STATS["status"][resp.status] += 1
    out = Response(corpo_out, status_code=resp.status, media_type=resp.ctype, headers=resp.headers)
    if set_cookie:
        out.set_cookie("JSESSIONID", set_cookie, path="/sigaa", httponly=True)
    return out


# ------------------------------------------------------------------ controle
def _cfg_json() -> dict:
    return {"mock": "sigaa-simulado", "fator": CFG.fator, "jitter": CFG.jitter, "latencias_s": CFG.latencias,
            "max_concorrencia": CFG.max_concorrencia, "ttl_sessao_s": CFG.ttl_sessao, "views_por_sessao": CFG.views}


async def ctl_config(req: Request) -> Response:
    global _sem
    if req.method == "POST":
        d = await req.json()
        for k in ("fator", "jitter", "ttl_sessao"):
            if k in d:
                setattr(CFG, k, float(d[k]))
        if "views" in d:
            CFG.views = int(d["views"])
        if "latencias" in d:
            CFG.latencias.update({k: float(v) for k, v in d["latencias"].items()})
        if "max_concorrencia" in d:
            CFG.max_concorrencia = int(d["max_concorrencia"])
            _sem = asyncio.Semaphore(CFG.max_concorrencia) if CFG.max_concorrencia > 0 else None
    return JSONResponse(_cfg_json())


async def ctl_stats(_: Request) -> Response:
    return JSONResponse({
        "uptime_s": round(time.time() - STATS["inicio"], 1), "sessoes": len(SESSOES), "logins": STATS["logins"],
        "em_voo": STATS["em_voo"], "pico_concorrencia": STATS["pico"], "expiradas": STATS["expiradas"],
        "viewstate_invalido": STATS["vs_invalido"], "status": dict(STATS["status"]), "por_regra": dict(STATS["regra"].most_common()),
        "por_caminho": dict(STATS["req"].most_common(40)), "misses": STATS["misses"][-50:], "total_misses": STATS["regra"]["MISS"],
    })


async def ctl_reset(_: Request) -> Response:
    for k in ("req", "regra", "status"):
        STATS[k] = Counter()
    STATS.update(misses=[], pico=0, expiradas=0, vs_invalido=0, logins=0, inicio=time.time())
    return JSONResponse({"ok": True})


async def ctl_expirar(_: Request) -> Response:
    n = len(SESSOES)
    SESSOES.clear()
    return JSONResponse({"derrubadas": n})


app = Starlette(routes=[
    Route("/__mock/config", ctl_config, methods=["GET", "POST"]),
    Route("/__mock/stats", ctl_stats),
    Route("/__mock/reset", ctl_reset, methods=["POST"]),
    Route("/__mock/expirar", ctl_expirar, methods=["POST"]),
    Route("/{caminho:path}", tratar, methods=["GET", "POST", "HEAD"]),
])


def main() -> None:
    global _sem
    import sys

    sys.path.insert(0, str(AQUI))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8111)
    ap.add_argument("--fator", type=float, default=1.0, help="multiplica todas as latências (0 = sem latência)")
    ap.add_argument("--jitter", type=float, default=0.10)
    ap.add_argument("--lat", action="append", default=[], metavar="CLASSE=SEG", help="ex.: --lat pdf=3.5 --lat padrao=0.45")
    ap.add_argument("--max-concorrencia", type=int, default=0)
    ap.add_argument("--ttl-sessao", type=float, default=1800)
    ap.add_argument("--views", type=int, default=20)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    if a.porta == 8000:
        raise SystemExit("8000 é a produção")
    CFG.fator, CFG.jitter, CFG.max_concorrencia, CFG.ttl_sessao, CFG.views = a.fator, a.jitter, a.max_concorrencia, a.ttl_sessao, a.views
    for kv in a.lat:
        k, v = kv.split("=", 1)
        CFG.latencias[k] = float(v)
    if a.seed is not None:
        _rng.seed(a.seed)
    if CFG.max_concorrencia > 0:
        _sem = asyncio.Semaphore(CFG.max_concorrencia)
    fixture("@historico.pdf")  # gera os PDFs no boot (não na 1ª requisição)
    fixture("@declaracao.pdf")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=a.porta, log_level="warning", access_log=False,
                backlog=4096, limit_concurrency=None, timeout_keep_alive=30)


if __name__ == "__main__":
    main()
