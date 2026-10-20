"""Parsers da TURMA VIRTUAL (AVA). Funções puras: HTML → modelo, zero rede.

Tolerância: cada professor usa a turma virtual de um jeito, então toda tela pode vir vazia
("Nenhum item foi encontrado"), com colunas a mais/a menos ou em outra ordem. As tabelas são lidas
pelo TEXTO do cabeçalho (sem acento, minúsculo), nunca pela posição.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from datetime import date, datetime

from bs4 import BeautifulSoup, Comment, Tag

from sigaa.models.turma_virtual import (
    Andamento,
    Arquivo,
    AulaCronograma,
    Avaliacao,
    AvaliacaoNota,
    AvaliacaoPlano,
    AvaliacaoResumo,
    ConteudoTurma,
    Enquete,
    EstatisticasTurma,
    EventoLinhaTempo,
    EventoRecente,
    ForumDetalhe,
    ForumTurma,
    Frequencia,
    GrupoTurma,
    ItemMenuTurma,
    MaterialTopico,
    MensagemForum,
    NotasTurma,
    NotaUnidade,
    Noticia,
    Participante,
    Participantes,
    PlanoCurso,
    ProgramaComponente,
    Questionario,
    ReferenciaPlano,
    ReferenciaTurma,
    RegistroFrequencia,
    Tarefa,
    TopicoAula,
    TopicoForum,
    TopicoForumDetalhe,
    TurmaVirtual,
    TurmaVirtualResumo,
    Video,
)

# ===================================================================== utilidades
_RE_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4}|\d{2})(?:\D{1,4}(\d{1,2})[:h](\d{2}))?")
_RE_ID = re.compile(r"'id'\s*:\s*'(\d+)'")
_RE_FE = re.compile(r"'frontEndIdTurma'\s*:\s*'(\w+)'")
_VAZIO = ("nenhum item foi encontrado", "nenhum forum foi encontrado", "nao ha ", "nenhum registro", "nenhuma ", "nenhum ")


def _soup(html: str | bytes) -> BeautifulSoup:
    if isinstance(html, bytes):
        html = html.decode("iso-8859-1", errors="replace")
    return BeautifulSoup(html, "lxml")


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower().rstrip(":").strip()


def _t(el) -> str:
    if el is None:
        return ""
    if isinstance(el, str):
        return re.sub(r"\s+", " ", el).strip()
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


_BLOCOS = ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre")


def _texto_bloco(el) -> str | None:
    """Texto multi-linha: blocos (p, div, li, br...) viram quebra de linha; inline (a, span, b) fica na linha."""
    if el is None:
        return None
    el = BeautifulSoup(str(el), "lxml")
    for x in el.find_all(["script", "style"]):
        x.decompose()
    for br in el.find_all("br"):
        br.replace_with("\n")
    for b in el.find_all(_BLOCOS):
        b.insert_after("\n")
        if b.name == "li":
            b.insert(0, "• ")
    txt = el.get_text("")
    txt = re.sub(r"[ \t\xa0\r\f\v]+", " ", txt)
    txt = re.sub(r" *\n *", "\n", txt)
    txt = re.sub(r"\n{2,}", "\n", txt).strip()
    return txt or None


def _inner_html(el) -> str | None:
    if el is None:
        return None
    s = "".join(str(c) for c in el.contents).strip()
    return s or None


def _ano(a: str) -> int:
    n = int(a)
    return n + 2000 if n < 100 else n


def _data(s: str | None) -> date | None:
    m = _RE_DATA.search(s or "")
    if not m:
        return None
    try:
        return date(_ano(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _datahora(s: str | None) -> datetime | None:
    m = _RE_DATA.search(s or "")
    if not m:
        return None
    try:
        h, mi = (int(m.group(4)), int(m.group(5))) if m.group(4) else (0, 0)
        return datetime(_ano(m.group(3)), int(m.group(2)), int(m.group(1)), h, mi)
    except ValueError:
        return None


def _data_ou_datahora(s: str | None) -> datetime | date | None:
    m = _RE_DATA.search(s or "")
    if not m:
        return None
    return _datahora(s) if m.group(4) else _data(s)


def _todas_datas(s: str) -> list[datetime]:
    out = []
    for m in _RE_DATA.finditer(s or ""):
        d = _datahora(m.group(0))
        if d:
            out.append(d)
    return out


def _float(s: str | None) -> float | None:
    s = (s or "").strip().replace("%", "").strip()
    if not s or s in ("-", "--", "---"):
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", s)
    return float(m.group(0).replace(",", ".")) if m else None


def _int(s: str | None) -> int | None:
    m = re.search(r"-?\d+", s or "")
    return int(m.group(0)) if m else None


def _id_de(el) -> int | None:
    """Id do registro no onclick (jsfcljs 'id':'123') ou num input hidden name=id do form."""
    if el is None:
        return None
    alvos = [el] + (el.find_all(onclick=True) if isinstance(el, Tag) else [])
    for a in alvos:
        m = _RE_ID.search(a.get("onclick", "") or "")
        if m:
            return int(m.group(1))
    for a in el.find_all("a", href=True) if isinstance(el, Tag) else []:
        m = re.search(r"[?&](?:id|idArquivo|idProducao)=(\d+)", a["href"])
        if m:
            return int(m.group(1))
    return None


def _conteudo(sp: BeautifulSoup) -> Tag:
    return sp.find(id="conteudo") or sp.find(id="relatorio") or sp.body or sp


def mensagens(html: str | bytes) -> list[str]:
    """Mensagens de erro/aviso/info do SIGAA (painel-erros: ul.erros, ul.warning, ul.info)."""
    sp = _soup(html)
    out = []
    for ul in sp.select("#painel-erros ul, ul.erros, ul.warning, ul.info"):
        for li in ul.find_all("li"):
            t = _t(li)
            if t and t not in out:
                out.append(t)
    return out


def esta_vazio(el) -> bool:
    if el is None:
        return True
    vazio = el.find(class_="empty-listing")
    if vazio is not None:
        return True
    t = _norm(_t(el))
    return any(v in t for v in _VAZIO[:2])


def _linhas(table: Tag) -> list[tuple[dict[str, str], dict[str, Tag], Tag]]:
    """Linhas de uma tabela de listagem: (cabeçalho_normalizado → texto, cabeçalho → td, tr)."""
    heads: list[str] = []
    thead = table.find("thead")
    tr_head = thead.find("tr") if thead else None
    if tr_head is None:
        primeira = table.find("tr")
        if primeira is not None and primeira.find("th") and not primeira.find("td"):
            tr_head = primeira
    if tr_head is not None:
        for th in tr_head.find_all(["th", "td"]):
            span = int(th.get("colspan", 1) or 1)
            nome = _norm(_t(th))
            heads.extend([nome] + [f"{nome}_{i}" for i in range(1, span)])
    out = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr", recursive=False) or body.find_all("tr"):
        if tr is tr_head or tr.find_parent("thead"):
            continue
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        txt: dict[str, str] = {}
        cel: dict[str, Tag] = {}
        for i, td in enumerate(tds):
            h = heads[i] if i < len(heads) else f"col{i}"
            if not h:
                h = f"col{i}"
            txt[h] = _t(td)
            cel[h] = td
        out.append((txt, cel, tr))
    return out


def _pega(d: dict[str, str], *chaves: str) -> str | None:
    """Valor do primeiro cabeçalho que CONTÉM alguma das chaves (normalizadas)."""
    for ch in chaves:
        for k, v in d.items():
            if ch in k:
                return v if v != "" else None
    return None


def _celula(c: dict[str, Tag], *chaves: str) -> Tag | None:
    for ch in chaves:
        for k, v in c.items():
            if ch in k:
                return v
    return None


def _tabela_listagem(sp, *, legenda: str | None = None) -> Tag | None:
    cont = _conteudo(sp)
    tabelas = cont.find_all("table", class_=re.compile(r"listing|listagem|tabelaRelatorio"))
    if legenda:
        for t in tabelas:
            cap = t.find("caption")
            leg = t.find_previous("legend")
            if (cap and legenda in _norm(_t(cap))) or (leg and legenda in _norm(_t(leg))):
                return t
    return tabelas[0] if tabelas else None


# ===================================================================== listas de turmas
def _horario_chave(s: str | None) -> str:
    return re.sub(r"\s+", "", s or "").upper()


def parse_turmas_anteriores(html: str | bytes) -> list[TurmaVirtualResumo]:
    """/sigaa/portais/discente/turmas.jsf — 'Todas as Turmas Virtuais' (agrupadas por período)."""
    sp = _soup(html)
    out: list[TurmaVirtualResumo] = []
    periodo = None
    for tr in _conteudo(sp).find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        t0 = _t(tds[0])
        if len(tds) == 1 or (re.fullmatch(r"\d{4}\.\d", t0) and not tr.find(onclick=_RE_FE)):
            if re.fullmatch(r"\d{4}\.\d", t0):
                periodo = t0
            continue
        a = tr.find(onclick=_RE_FE)
        if a is None:
            continue
        fe = _RE_FE.search(a["onclick"]).group(1)
        textos = [_t(td) for td in tds]
        disc = next((x for x in textos if re.match(r"[A-Z]{2,}\w*\d+\s*-", x)), textos[0])
        m = re.match(r"(\S+)\s*-\s*(.+)", disc)
        ch = next((x for x in textos if re.fullmatch(r"\d+\s*h", x)), None)
        hor = next((x for x in textos if re.search(r"\(\d{2}/\d{2}/\d{4}", x)), None)
        turma = next((x for x in textos if re.fullmatch(r"[0-9A-Z]{1,4}", x) and x != disc), None)
        out.append(
            TurmaVirtualResumo(
                front_end_id=fe,
                codigo=m.group(1) if m else None,
                nome=(m.group(2) if m else disc).strip() or None,
                turma=turma,
                periodo=periodo,
                carga_horaria=_int(ch),
                horario=hor,
            )
        )
    return out


def parse_turmas_portal(html: str | bytes) -> list[TurmaVirtualResumo]:
    """Quadro 'Turmas do Semestre' do portal do discente (form_acessarTurmaVirtual*)."""
    sp = _soup(html)
    out = []
    for form in sp.find_all("form", id=re.compile(r"^form_acessarTurmaVirtual")):
        a = form.find(onclick=_RE_FE)
        if a is None:
            continue
        tr = form.find_parent("tr")
        tds = tr.find_all("td", recursive=False) if tr else []
        local = _t(tds[1]) if len(tds) > 1 else None
        hor = _t(tds[2]) if len(tds) > 2 else None
        out.append(
            TurmaVirtualResumo(
                front_end_id=_RE_FE.search(a["onclick"]).group(1),
                nome=_t(a) or None,
                local=local or None,
                horario=hor or None,
                atual=True,
            )
        )
    # idTurma das atualizações (só aparece pra turma com novidade): casa pelo nome
    ids = {}
    for a in sp.find_all(onclick=re.compile(r"'idTurma'")):
        m = re.search(r"'idTurma'\s*:\s*'(\d+)'", a["onclick"])
        nome = re.sub(r"\s*\(\d{4}\.\d\)\s*$", "", _t(a))
        if m and nome:
            ids.setdefault(_norm(nome), int(m.group(1)))
    for t in out:
        t.turma_id = ids.get(_norm(t.nome))
    return out


def parse_turmas_mobile(html: str | bytes) -> list[TurmaVirtualResumo]:
    """/sigaa/mobile/touch/ava/turmas_discente.jsf (versão mobile): é a ÚNICA lista que traz o idTurma
    numérico de TODAS as turmas (cmdEntrarTurma com 'idTurma'). front_end_id fica vazio."""
    sp = _soup(html)
    out = []
    periodo = None
    for li in sp.find_all("li"):
        if li.get("data-role") == "list-divider":
            m = re.search(r"\d{4}\.\d", _t(li))
            periodo = m.group(0) if m else periodo
            continue
        a = li.find("a", onclick=re.compile(r"'idTurma'"))
        if a is None:
            continue
        idt = int(re.search(r"'idTurma'\s*:\s*'(\d+)'", a["onclick"]).group(1))
        smalls = [_t(s) for s in a.find_all("small")]
        for s in a.find_all("small"):
            s.extract()
        titulo = _t(a)
        m = re.match(r"(\S+)\s*-\s*(.+)", titulo)
        local = next((s.split(":", 1)[1].strip() for s in smalls if _norm(s).startswith("local")), None)
        hor = next((s.split(":", 1)[1].strip() for s in smalls if _norm(s).startswith("horario")), None)
        out.append(
            TurmaVirtualResumo(
                turma_id=idt,
                front_end_id="",
                codigo=m.group(1) if m else None,
                nome=(m.group(2) if m else titulo).strip(),
                periodo=periodo,
                horario=hor,
                local=local,
            )
        )
    return out


def casar_turmas(desktop: list[TurmaVirtualResumo], mobile: list[TurmaVirtualResumo]) -> list[TurmaVirtualResumo]:
    """Preenche turma_id das turmas do desktop (que só têm frontEndIdTurma) casando com a lista mobile
    por (período, código, horário com datas). Se o horário não bater, cai pra (período, código) único."""
    por_chave = {(t.periodo, t.codigo, _horario_chave(t.horario)): t for t in mobile}
    por_cod: dict[tuple, list[TurmaVirtualResumo]] = {}
    for t in mobile:
        por_cod.setdefault((t.periodo, t.codigo), []).append(t)
    for d in desktop:
        if d.turma_id:
            continue
        m = por_chave.get((d.periodo, d.codigo, _horario_chave(d.horario)))
        if m is None and len(por_cod.get((d.periodo, d.codigo), [])) == 1:
            m = por_cod[(d.periodo, d.codigo)][0]
        if m is not None:
            d.turma_id = m.turma_id
            d.local = d.local or m.local
    return desktop


# ===================================================================== página principal
_GRUPOS_MENU = {"turma", "alunos", "materiais", "atividades", "estatistica", "ajuda"}


def parse_menu(html: str | bytes) -> list[ItemMenuTurma]:
    """Menu lateral (rich:panelBar): cada grupo é um .rich-panelbar-interior com o cabeçalho e os itemMenu."""
    sp = _soup(html)
    form = sp.find("form", id="formMenu")
    if form is None:
        return []
    out = []
    grupos = form.select(".rich-panelbar-interior")
    if not grupos:
        return [ItemMenuTurma(rotulo=_t(a)) for a in form.find_all("a", onclick=re.compile("jsfcljs")) if _t(a)]
    for g in grupos:
        cab = g.find(class_="rich-panelbar-header")
        nome = _t(cab) or None
        for a in g.find_all("a", onclick=re.compile("jsfcljs")):
            if _t(a):
                out.append(ItemMenuTurma(rotulo=_t(a), grupo=nome))
    return out


def _tipo_material(icone: str, a: Tag | None) -> str:
    i = (icone or "").lower()
    oc = (a.get("onclick", "") if a else "") + (a.get("href", "") if a else "")
    oc = oc.lower()
    for chave, tipo in (
        ("tarefa", "tarefa"),
        ("questionario", "questionario"),
        ("enquete", "enquete"),
        ("forum", "forum"),
        ("chat", "chat"),
        ("video", "video"),
        ("youtube", "video"),
        ("conteudo", "conteudo"),
        ("site", "referencia"),
        ("referencia", "referencia"),
        ("link", "referencia"),
    ):
        if chave in i or chave in oc:
            return tipo
    if "porta_arquivos/icones" in i or "arquivo" in oc or "verproducao" in oc:
        return "arquivo"
    return "outro"


def _parse_topicos(cont: Tag) -> list[TopicoAula]:
    out = []
    for top in cont.select("div.topico-aula"):
        tit_el = top.find("div", class_="titulo")
        tit = _t(tit_el)
        m = re.search(r"\((\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\)", tit)
        ini = fim = None
        if m:
            ini, fim = _data(m.group(1)), _data(m.group(2))
            tit = (tit[: m.start()] + tit[m.end():]).strip()
        corpo = top.find("div", class_="conteudotopico")
        materiais = []
        desc_partes = []
        if corpo is not None:
            for item in corpo.find_all("div", class_="item"):
                img = next((i for i in item.find_all("img") if "indicator" not in i.get("src", "")), None)
                icone = img.get("src", "") if img else ""
                a = item.find("a", onclick=True) or item.find("a", href=True)
                titulo = _t(a) if a else _t(item)
                d = item.find(class_="descricao-item")
                href = a.get("href") if a is not None else None
                hid = re.search(r"'id'\s*:\s*'([0-9A-F]{20,})'", a.get("onclick", "") if a is not None else "")
                materiais.append(
                    MaterialTopico(
                        id=_id_de(item),
                        id_hash=hid.group(1) if hid else None,
                        tipo=_tipo_material(icone, a),
                        titulo=titulo,
                        descricao=_t(d) or None,
                        url=href if href and href not in ("#",) and not href.startswith("javascript") else None,
                        icone=icone.rsplit("/", 1)[-1] or None,
                    )
                )
            # texto do tópico = o que sobra fora dos itens
            copia = BeautifulSoup(str(corpo), "lxml")
            for x in copia.select("div.item, script, div.drag_indicator, span[id$=':status']"):
                x.decompose()
            txt = _texto_bloco(copia.body or copia)
            if txt:
                desc_partes.append(txt)
            links = [a["href"] for a in copia.find_all("a", href=re.compile(r"^https?://"))]
        else:
            links = []
        desc_html = None
        if corpo is not None:
            desc_el = corpo.find(class_=re.compile("descricao-?topico|conteudoTopico", re.I))
            desc_html = _inner_html(desc_el) if desc_el else None
        out.append(
            TopicoAula(
                titulo=tit,
                data_inicio=ini,
                data_fim=fim,
                descricao="\n".join(desc_partes) or None,
                descricao_html=desc_html,
                materiais=materiais,
                links=list(dict.fromkeys(links)),
            )
        )
    return out


def _painel_lateral(sp: BeautifulSoup, titulo: str) -> Tag | None:
    for h in sp.select("#barraDireita .headerBloco, #barraDireita .rich-stglpanel-header"):
        if titulo in _norm(_t(h)):
            painel = h.find_parent(class_="rich-stglpanel")
            if painel is not None:
                return painel.find(class_="rich-stglpanel-body")
    return None


def parse_cabecalho_turma(html: str | bytes) -> dict:
    sp = _soup(html)
    out: dict = {}
    cod = sp.find(id="linkCodigoTurma")
    nome = sp.find(id="linkNomeTurma")
    per = sp.find(id="linkPeriodoTurma")
    if cod:
        out["codigo"] = _t(cod).rstrip("-").strip() or None
    if nome:
        out["nome"] = _t(nome) or None
    if per:
        t = _t(per)
        m = re.search(r"T\s*(\w+)", t)
        out["turma"] = m.group(1) if m else None
        m = re.search(r"\d{4}\.\d", t)
        out["periodo"] = m.group(0) if m else None
    return out


def parse_principal(html: str | bytes, front_end_id: str | None = None) -> TurmaVirtual:
    sp = _soup(html)
    cont = _conteudo(sp)
    cab = parse_cabecalho_turma(html)

    # outras turmas (Trocar de Turma) + CH da turma atual
    outras = []
    ch = None
    form_t = sp.find("form", id="formTurma")
    if form_t is not None:
        for a in form_t.find_all("a", onclick=_RE_FE):
            t = _t(a)
            fe = _RE_FE.search(a["onclick"]).group(1)
            m = re.match(r"(\S+)\s*-\s*(.+?)\s*(?:\((\d+)h\))?\s*(?:\((\d{4}\.\d)\))?$", t)
            r = TurmaVirtualResumo(
                front_end_id=fe,
                codigo=m.group(1) if m else None,
                nome=m.group(2) if m else t,
                carga_horaria=int(m.group(3)) if m and m.group(3) else None,
                periodo=m.group(4) if m else None,
            )
            outras.append(r)
            if fe == front_end_id or (r.codigo and r.codigo == cab.get("codigo") and r.periodo == cab.get("periodo")):
                ch = r.carga_horaria

    # última notícia
    ult = None
    un = cont.find(id="ultimaNoticia")
    if un is not None:
        h4 = un.find("h4")
        linha = _t(h4).replace("Última Notícia", "").strip() if h4 else ""
        m = re.match(r"(.*?)\s*-\s*(\d{2}/\d{2}/\d{4}(?:\s+\d{1,2}:\d{2})?)\s*$", linha)
        corpo = un.find(class_="conteudoNoticia")
        autor = un.find("i")
        ult = Noticia(
            titulo=(m.group(1) if m else linha) or "(sem título)",
            data=_data_ou_datahora(m.group(2)) if m else None,
            conteudo=_texto_bloco(BeautifulSoup(str(corpo), "lxml")) if corpo else None,
            conteudo_html=_inner_html(corpo),
            autor=_t(autor) or None,
        )

    # ementa (turmas sem tópicos mostram 'Ementa: ...' ou um texto solto)
    ementa = None
    tem_topicos = bool(cont.select("div.topico-aula"))
    sem_topicos = "nao criou nenhum topico de aula" in _norm(_t(cont))
    if not tem_topicos and not sem_topicos:
        bruto = _texto_bloco(BeautifulSoup(str(cont.find("form", id="formAva") or cont), "lxml"))
        if bruto:
            bruto = re.sub(r"^Ementa:\s*", "", bruto.strip())
            ementa = bruto or None

    # andamento
    andamento = None
    pa = _painel_lateral(sp, "andamento")
    if pa is not None:
        t = _t(pa)
        m = re.search(r"(\d+)\s*/\s*(\d+)", t)
        p = re.search(r"(\d+(?:[.,]\d+)?)\s*%", t)
        andamento = Andamento(
            aulas_ministradas=int(m.group(1)) if m else None,
            aulas_total=int(m.group(2)) if m else None,
            percentual_ch_ministrada=_float(p.group(1)) if p else None,
        )

    # notícias recentes
    recentes = []
    pn = _painel_lateral(sp, "noticias")
    if pn is not None:
        for form in pn.find_all("form"):
            idf = form.find("input", attrs={"name": "id"})
            ital = form.find_previous_sibling("i")
            txt_antes = ""
            node = ital.previous_sibling if ital else None
            while node is not None and not (isinstance(node, Tag) and node.name in ("form", "i")):
                txt_antes = (node if isinstance(node, str) else _t(node)) + " " + txt_antes
                node = node.previous_sibling
            recentes.append(
                Noticia(
                    id=int(idf["value"]) if idf and idf.get("value", "").isdigit() else None,
                    titulo=_t(ital) or "(sem título)",
                    data=_data_ou_datahora(txt_antes),
                )
            )

    atividades = []
    pat = _painel_lateral(sp, "atividades")
    if pat is not None:
        txt = pat.get_text("\n")
        linhas = [x.strip() for x in txt.split("\n") if x.strip()]
        i = 0
        while i < len(linhas):
            if re.fullmatch(r"\d{2}/\d{2}", linhas[i]) and i + 1 < len(linhas):
                atividades.append(EventoRecente(data=linhas[i], descricao=linhas[i + 1]))
                i += 2
            else:
                if not esta_vazio(BeautifulSoup(linhas[i], "lxml")) and "nenhum" not in _norm(linhas[i]):
                    atividades.append(EventoRecente(descricao=linhas[i]))
                i += 1

    avals = []
    pav = _painel_lateral(sp, "avaliacoes")
    if pav is not None:
        linhas = [x.strip() for x in pav.get_text("\n").split("\n") if x.strip()]
        i = 0
        while i < len(linhas):
            if re.fullmatch(r"\d{2}/\d{2}(?:\s+\d{2}:\d{2})?", linhas[i]) and i + 1 < len(linhas):
                avals.append(AvaliacaoResumo(data=linhas[i], descricao=linhas[i + 1]))
                i += 2
            else:
                i += 1

    enquete = None
    pe = _painel_lateral(sp, "enquete")
    if pe is not None:
        t = _t(pe)
        if t and "nenhuma" not in _norm(t):
            enquete = t

    return TurmaVirtual(
        front_end_id=front_end_id,
        codigo=cab.get("codigo"),
        nome=cab.get("nome"),
        turma=cab.get("turma"),
        periodo=cab.get("periodo"),
        carga_horaria=ch,
        ementa=ementa,
        sem_topicos=sem_topicos,
        andamento=andamento,
        ultima_noticia=ult,
        topicos=_parse_topicos(cont),
        noticias_recentes=recentes,
        atividades_recentes=atividades,
        avaliacoes_proximas=avals,
        enquete_aberta=enquete,
        menu=parse_menu(html),
        outras_turmas=outras,
    )


# ===================================================================== notícias
def parse_noticias(html: str | bytes) -> list[Noticia]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        titulo = _pega(txt, "titulo") or next(iter(txt.values()), "")
        if not titulo:
            continue
        out.append(Noticia(id=_id_de(tr), titulo=titulo, data=_data_ou_datahora(_pega(txt, "data"))))
    return out


def parse_noticia(html: str | bytes) -> Noticia:
    """Detalhe de uma notícia (Visualizar). Lê por rótulo; cai no bloco de conteúdo se não houver tabela."""
    sp = _soup(html)
    cont = _conteudo(sp)
    campos: dict[str, Tag] = {}
    for th in cont.find_all(["th", "label", "dt", "b", "strong"]):
        rot = _norm(_t(th))
        if rot in ("titulo", "data", "data de cadastro", "cadastrado em", "autor", "cadastrado por", "texto", "noticia", "conteudo", "descricao"):
            alvo = th.find_next_sibling(["td", "dd", "span", "div"]) or th.find_next(["td", "dd"])
            if alvo is not None:
                campos.setdefault(rot, alvo)
    titulo = _t(campos.get("titulo")) if "titulo" in campos else None
    corpo = campos.get("texto") or campos.get("noticia") or campos.get("conteudo") or campos.get("descricao")
    if corpo is None:
        corpo = cont.find(class_=re.compile("conteudoNoticia|noticia", re.I))
    data_el = campos.get("data") or campos.get("data de cadastro") or campos.get("cadastrado em")
    autor_el = campos.get("autor") or campos.get("cadastrado por")
    if not titulo:
        leg = cont.find(["legend", "h3", "h4", "caption"])
        titulo = _t(leg) if leg else None
    data = _data_ou_datahora(_t(data_el)) if data_el else _data_ou_datahora(_t(cont))
    idf = cont.find("input", attrs={"name": "id"})
    return Noticia(
        id=int(idf["value"]) if idf is not None and idf.get("value", "").isdigit() else None,
        titulo=titulo or "(sem título)",
        data=data,
        conteudo=_texto_bloco(BeautifulSoup(str(corpo), "lxml")) if corpo is not None else None,
        conteudo_html=_inner_html(corpo),
        autor=_t(autor_el) or None if autor_el else None,
    )


# ===================================================================== participantes
_ROTULOS_PART = {
    "departamento": "departamento",
    "formacao": "formacao",
    "e-mail": "email",
    "email": "email",
    "curso": "curso",
    "matricula": "matricula",
    "usuario": "usuario",
    "login": "usuario",
}


def _participante(td_info: Tag, td_foto: Tag | None, papel: str) -> Participante | None:
    strong = td_info.find("strong")
    if strong is None:
        return None
    nome = _t(strong)
    if not nome:
        return None
    dados: dict[str, str] = {}
    extras: dict[str, str] = {}
    # pares "Rótulo: <em>valor</em>"
    for em in td_info.find_all("em"):
        rot_txt = ""
        node = em.previous_sibling
        while node is not None and not (isinstance(node, Tag) and node.name in ("em", "br", "strong")):
            if not isinstance(node, Comment):
                rot_txt = (node if isinstance(node, str) else _t(node)) + rot_txt
            node = node.previous_sibling
        rot_txt = re.sub(r"\s+", " ", rot_txt).strip()
        rot = _norm(rot_txt)
        val = _t(em)
        chave = _ROTULOS_PART.get(rot)
        if chave:
            dados[chave] = val
        elif rot:
            extras[rot_txt.strip().rstrip(":").strip()] = val
    a_pub = strong.find("a", href=re.compile("RedirectDocente|public"))
    img = td_foto.find("img") if td_foto is not None else None
    foto = img.get("src") if img is not None and "no_picture" not in img.get("src", "") else None
    status = td_info.find("img", src=re.compile("online|offline"))
    return Participante(
        nome=nome,
        papel=papel,
        email=dados.get("email") or None,
        departamento=dados.get("departamento"),
        formacao=dados.get("formacao"),
        curso=dados.get("curso"),
        matricula=dados.get("matricula"),
        usuario=dados.get("usuario"),
        foto_url=foto,
        pagina_publica=a_pub["href"] if a_pub is not None else None,
        online=("online" in status["src"] and "offline" not in status["src"]) if status is not None else None,
        campos_extras=extras,
    )


def parse_participantes(html: str | bytes) -> Participantes:
    sp = _soup(html)
    cont = _conteudo(sp)
    res = Participantes()
    for leg in cont.find_all("legend"):
        rot = _norm(_t(leg))
        papel = "docente" if rot.startswith("docente") else "discente" if rot.startswith("discente") else None
        if papel is None:
            continue
        total = _int(rot)
        tab = leg.find_next("table", class_="participantes")
        lista = []
        if tab is not None:
            for tr in tab.find_all("tr"):
                tds = tr.find_all("td", recursive=False)
                for i, td in enumerate(tds):
                    if td.find("strong"):
                        foto = tds[i - 1] if i > 0 else None
                        p = _participante(td, foto, papel)
                        if p:
                            lista.append(p)
        if papel == "docente":
            res.docentes, res.total_docentes = lista, total
        else:
            res.discentes, res.total_discentes = lista, total
    return res


# ===================================================================== plano de curso / programa
def _refs(tab: Tag | None) -> list[ReferenciaPlano]:
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        desc = _pega(txt, "descricao", "referencia")
        if not desc:
            continue
        out.append(
            ReferenciaPlano(
                tipo=_pega(txt, "tipo"),
                descricao=desc,
                na_biblioteca=bool(tr.find("img", src=re.compile("destaque"))),
            )
        )
    return out


def parse_plano_curso(html: str | bytes) -> PlanoCurso:
    sp = _soup(html)
    cont = _conteudo(sp)
    plano = PlanoCurso()
    for tab in cont.find_all("table"):
        for tr in tab.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th is None or td is None or tr.find_parent("thead"):
                continue
            rot = _norm(_t(th))
            val = _texto_bloco(BeautifulSoup(str(td), "lxml"))
            if rot.startswith("metodologia"):
                plano.metodologia = val
            elif "procedimentos de avaliacao" in rot or rot == "avaliacao":
                plano.procedimentos_avaliacao = val
            elif "horario de atendimento" in rot:
                plano.horario_atendimento = val
            elif rot.startswith("objetivo"):
                plano.objetivos = val
            elif "programa atual" in rot:
                m = re.search(r"'idComponente'\s*:\s*'(\d+)'", str(td))
                plano.id_componente = int(m.group(1)) if m else None
            elif rot and val and tab.get("id") not in ("listaTopicosAula", "listaAvaliacoes"):
                plano.campos_extras[_t(th).rstrip(":")] = val
    crono = cont.find("table", id="listaTopicosAula") or _tabela_listagem(sp, legenda="cronograma")
    if crono is not None:
        for txt, cel, tr in _linhas(crono):
            d = _pega(txt, "descricao")
            if not d:
                continue
            plano.cronograma.append(AulaCronograma(inicio=_data(_pega(txt, "inicio")), fim=_data(_pega(txt, "fim")), descricao=d))
    av = cont.find("table", id="listaAvaliacoes") or _tabela_listagem(sp, legenda="avaliacoes")
    if av is not None:
        for txt, cel, tr in _linhas(av):
            d = _pega(txt, "descricao")
            if d:
                plano.avaliacoes.append(AvaliacaoPlano(data=_data(_pega(txt, "data")), descricao=d))
    for tab in cont.find_all("table"):
        cap = _norm(_t(tab.find("caption")))
        if "referencias basicas" in cap:
            plano.referencias_basicas = _refs(tab)
        elif "referencias complementares" in cap:
            plano.referencias_complementares = _refs(tab)
    return plano


_CAMPOS_PROGRAMA = {
    "ementa": "ementa",
    "objetivos": "objetivos",
    "objetivo": "objetivos",
    "conteudo": "conteudo",
    "conteudo programatico": "conteudo",
    "competencias e habilidades": "competencias",
    "competencias": "competencias",
    "metodologia": "metodologia",
    "procedimentos de avaliacao": "avaliacao",
    "avaliacao": "avaliacao",
    "referencias": "referencias",
    "bibliografia": "referencias",
    "referencias bibliograficas": "referencias",
}


def parse_programa(html: str | bytes) -> ProgramaComponente:
    """Programa do componente (Visualizar Programa / 'Programa atual do componente')."""
    sp = _soup(html)
    msgs = mensagens(html)
    sem = next((m for m in msgs if "nao possui" in _norm(m) and "programa" in _norm(m)), None)
    prog = ProgramaComponente(disponivel=sem is None, mensagem=sem or (msgs[0] if msgs else None))
    if sem:
        m = re.search(r"curricular\s+(\S+)\s*-\s*(.+?)\s+n[ãa]o possui", sem)
        if m:
            prog.codigo, prog.nome = m.group(1), m.group(2)
        return prog
    cont = _conteudo(sp)
    for tr in cont.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None:
            continue
        rot_txt = _t(th).rstrip(":").strip()
        val = _texto_bloco(BeautifulSoup(str(td), "lxml"))
        if not rot_txt or not val:
            continue
        prog.campos[rot_txt] = val
        chave = _CAMPOS_PROGRAMA.get(_norm(rot_txt))
        if chave and getattr(prog, chave) is None:
            setattr(prog, chave, val)
        if _norm(rot_txt) in ("componente curricular", "componente", "disciplina"):
            m = re.match(r"(\S+)\s*-\s*(.+)", val)
            if m:
                prog.codigo, prog.nome = m.group(1), m.group(2)
        if _norm(rot_txt) == "codigo":
            prog.codigo = val
        if _norm(rot_txt) == "nome":
            prog.nome = val
    if not prog.campos:
        prog.disponivel = False
    return prog


# ===================================================================== materiais
def parse_conteudos(html: str | bytes) -> list[ConteudoTurma]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        t = _pega(txt, "titulo") or next(iter(txt.values()), "")
        if t:
            out.append(ConteudoTurma(id=_id_de(tr), titulo=t, criado_em=_data(_pega(txt, "criado", "data"))))
    return out


def parse_conteudo(html: str | bytes, id: int | None = None) -> ConteudoTurma:
    sp = _soup(html)
    cont = _conteudo(sp)
    titulo = None
    corpo = None
    for th in cont.find_all(["th", "label", "b", "strong"]):
        rot = _norm(_t(th))
        if rot == "titulo":
            alvo = th.find_next_sibling(["td", "span", "div"]) or th.find_next("td")
            titulo = _t(alvo) or titulo
        elif rot in ("conteudo", "texto", "descricao"):
            corpo = th.find_next_sibling(["td", "div"]) or th.find_next("td")
    if corpo is None:
        corpo = cont.find(class_=re.compile(r"conteudo(Pagina|Texto|Turma)?$|texto", re.I)) or cont.find("form") or cont
    if not titulo:
        leg = cont.find(["legend", "h2", "h3", "h4", "caption"])
        titulo = _t(leg) if leg else "(sem título)"
    copia = BeautifulSoup(str(corpo), "lxml")
    for x in copia.select("script, style, legend, input, .infoAltRem, .botoes, .voltar"):
        x.decompose()
    return ConteudoTurma(
        id=id,
        titulo=titulo,
        criado_em=None,
        conteudo=_texto_bloco(copia.body or copia),
        conteudo_html=_inner_html(corpo),
    )


def parse_referencias(html: str | bytes) -> list[ReferenciaTurma]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        nome = _pega(txt, "nome", "titulo", "descricao")
        if not nome:
            continue
        a = (_celula(cel, "url", "link") or tr).find("a", href=re.compile(r"^(https?:|www\.)"))
        url = a["href"] if a is not None else _pega(txt, "url", "link")
        out.append(
            ReferenciaTurma(
                id=_id_de(tr),
                nome=nome,
                tipo=_pega(txt, "tipo"),
                url=url if url and url.rstrip("/") not in ("http:", "https:", "http:/", "https:/") else None,
                topico=_pega(txt, "topico"),
            )
        )
    return out


def parse_videos(html: str | bytes) -> list[Video]:
    sp = _soup(html)
    cont = _conteudo(sp)
    out = []
    tab = _tabela_listagem(sp)
    if tab is not None:
        for txt, cel, tr in _linhas(tab):
            t = _pega(txt, "titulo", "nome")
            if not t:
                continue
            a = tr.find("a", href=re.compile(r"^https?:"))
            out.append(
                Video(
                    id=_id_de(tr),
                    titulo=t,
                    descricao=_pega(txt, "descricao"),
                    url=a["href"] if a is not None else _pega(txt, "link", "url"),
                    topico=_pega(txt, "topico"),
                    data=_data(_pega(txt, "data", "cadastrado")),
                )
            )
        return out
    # layout alternativo: blocos com iframe/vídeo embutido
    for bloco in cont.find_all(["iframe", "video"]):
        src = bloco.get("src") or (bloco.find("source") or {}).get("src")
        h = bloco.find_previous(["h3", "h4", "strong", "legend"])
        out.append(Video(titulo=_t(h) or "(vídeo)", url=src))
    return out


def parse_arquivos(html: str | bytes) -> list[Arquivo]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        nome = _pega(txt, "nome", "arquivo", "titulo")
        if not nome:
            continue
        a = tr.find("a", href=re.compile(r"verProducao|download|Arquivo|idArquivo", re.I))
        out.append(
            Arquivo(
                id=_id_de(tr),
                nome=nome,
                descricao=_pega(txt, "descricao"),
                topico=_pega(txt, "topico", "aula"),
                data=_data(_pega(txt, "data", "cadastr", "enviado")),
                tamanho=_pega(txt, "tamanho"),
                url=a["href"] if a is not None else None,
            )
        )
    return out


# ===================================================================== atividades
def _periodo(txt: dict[str, str], linha: str) -> tuple[datetime | None, datetime | None]:
    ini = _datahora(_pega(txt, "inicio", "abertura", "de "))
    fim = _datahora(_pega(txt, "fim", "prazo", "termino", "encerramento", "ate"))
    if ini is None or fim is None:
        ds = _todas_datas(_pega(txt, "periodo", "data", "entrega") or linha)
        if ds:
            ini = ini or (ds[0] if len(ds) > 1 else None)
            fim = fim or ds[-1]
    return ini, fim


def _sim(s: str | None) -> bool | None:
    n = _norm(s)
    if not n:
        return None
    if n in ("sim", "s", "enviada", "enviado", "respondido", "respondida", "votou", "votado"):
        return True
    if n in ("nao", "n", "nao enviada", "nao enviado", "pendente", "nao respondido", "nao respondida"):
        return False
    return None


def parse_tarefas(html: str | bytes, agora: datetime | None = None) -> list[Tarefa]:
    """Lista de tarefas (/ava/TarefaTurma/listar.jsf). O SIGAA põe às vezes uma 2ª linha com a descrição."""
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    agora = agora or datetime.now()
    out: list[Tarefa] = []
    for txt, cel, tr in _linhas(tab):
        linha = _t(tr)
        titulo = _pega(txt, "titulo", "tarefa", "nome")
        if not titulo:
            # linha de descrição pendurada na tarefa anterior
            if out and len([v for v in txt.values() if v]) == 1:
                out[-1].descricao = (out[-1].descricao + "\n" if out[-1].descricao else "") + linha
            continue
        ini, fim = _periodo(txt, linha)
        status = _pega(txt, "envi", "situacao", "status")
        enviada = _sim(status)
        if enviada is None and tr.find("img", src=re.compile(r"(check|enviad|ok)", re.I)):
            enviada = True
        nota = _float(_pega(txt, "nota"))
        conhecidos = ("titulo", "tarefa", "nome", "inicio", "fim", "periodo", "data", "envi", "situacao", "status", "nota", "entrega")
        out.append(
            Tarefa(
                id=_id_de(tr),
                titulo=titulo,
                descricao=_pega(txt, "descricao"),
                inicio=ini,
                fim=fim,
                enviada=enviada,
                nota=nota,
                status=status,
                em_grupo=True if "grupo" in _norm(linha) else None,
                aberta=(ini is None or ini <= agora) and fim >= agora if fim else None,
                topico=_pega(txt, "topico"),
                campos_extras={k: v for k, v in txt.items() if v and not any(c in k for c in conhecidos) and not k.startswith("col")},
            )
        )
    return out


def parse_questionarios(html: str | bytes) -> list[Questionario]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        titulo = _pega(txt, "titulo", "questionario", "nome")
        if not titulo:
            continue
        linha = _t(tr)
        ini, fim = _periodo(txt, linha)
        status = _pega(txt, "situacao", "status", "respond", "envi")
        out.append(
            Questionario(
                id=_id_de(tr),
                titulo=titulo,
                inicio=ini,
                fim=fim,
                respondido=_sim(status),
                nota=_float(_pega(txt, "nota")),
                status=status,
                campos_extras={k: v for k, v in txt.items() if v and not k.startswith("col") and not any(c in k for c in ("titulo", "questionario", "nome", "inicio", "fim", "situacao", "status", "respond", "nota"))},
            )
        )
    return out


def parse_enquetes(html: str | bytes) -> list[Enquete]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        perg = _pega(txt, "pergunta", "titulo", "enquete", "descricao")
        if not perg:
            continue
        status = _pega(txt, "situacao", "status", "vot")
        out.append(
            Enquete(
                id=_id_de(tr),
                pergunta=perg,
                prazo=_data_ou_datahora(_pega(txt, "prazo", "data", "fim", "ate")),
                status=status,
                votou=_sim(status),
                campos_extras={k: v for k, v in txt.items() if v and not k.startswith("col") and not any(c in k for c in ("pergunta", "titulo", "enquete", "prazo", "data", "situacao", "status", "vot"))},
            )
        )
    return out


def parse_avaliacoes(html: str | bytes) -> list[Avaliacao]:
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        d = _pega(txt, "descricao", "avaliacao")
        if not d:
            continue
        hora = _pega(txt, "hora")
        out.append(Avaliacao(id=_id_de(tr), data=_data(_pega(txt, "data")), hora=hora if hora and re.match(r"\d{1,2}:\d{2}", hora) else None, descricao=d))
    return out


# ===================================================================== fórum
def _pares_th_td(cont: Tag) -> dict[str, Tag]:
    """Tabelas de detalhe 'th Rótulo: | td valor' e listas 'label Rótulo: | span valor' → {rótulo_normalizado: el}."""
    out: dict[str, Tag] = {}
    for tr in cont.find_all("tr"):
        th, td = tr.find("th", recursive=False), tr.find("td", recursive=False)
        if th is not None and td is not None:
            out.setdefault(_norm(_t(th)), td)
    for lab in cont.find_all("label"):
        alvo = lab.find_next_sibling(["span", "div", "td"])
        if alvo is not None:
            out.setdefault(_norm(_t(lab)), alvo)
    return out


def _sim_nao(s: str | None) -> bool | None:
    n = _norm(s)
    return True if n == "sim" else False if n in ("nao", "não") else None


def parse_foruns(html: str | bytes) -> list[ForumTurma]:
    """/ava/ForumTurma/lista.jsf. Os links não trazem id: o fórum é identificado pela POSIÇÃO (1..n)."""
    sp = _soup(html)
    tab = _tabela_listagem(sp)
    if tab is None:
        return []
    out = []
    for txt, cel, tr in _linhas(tab):
        c_tit = _celula(cel, "titulo", "forum", "nome")
        if c_tit is None:
            continue
        a = c_tit.find("a")
        titulo = _t(a) if a is not None else _t(c_tit)
        if not titulo:
            continue
        # resto da célula: "<br/> [<b>Aula: </b><i>X</i><br/>] descrição"
        aula = None
        b = c_tit.find("b", string=re.compile("Aula", re.I))
        if b is not None:
            i_el = b.find_next_sibling("i")
            aula = _t(i_el) or None
        copia = BeautifulSoup(str(c_tit), "lxml")
        for x in copia.find_all(["a", "b", "i"]):
            x.decompose()
        desc = _t(copia) or None
        out.append(
            ForumTurma(
                id=len(out) + 1,
                titulo=titulo,
                descricao=desc,
                aula=aula,
                tipo=_pega(txt, "tipo"),
                autor=_pega(txt, "autor"),
                topicos=_int(_pega(txt, "topicos")),
                criado_em=_data_ou_datahora(_pega(txt, "criado")),
                inicio=_data(_pega(txt, "inicio")),
                fim=_data(_pega(txt, "fim")),
                campos_extras={k: v for k, v in txt.items() if v and not k.startswith("col") and not any(c in k for c in ("titulo", "tipo", "topicos", "autor", "criado", "inicio", "fim"))},
            )
        )
    return out


def parse_forum(html: str | bytes, forum_id: int = 1) -> ForumDetalhe:
    """/ava/Foruns/view.jsf: dados do fórum (th/td) + tabela de tópicos (Mensagem, Autor, Respostas, Última Mensagem)."""
    sp = _soup(html)
    cont = _conteudo(sp)
    campos = _pares_th_td(cont)
    def v(*ch):
        for c in ch:
            if c in campos:
                return _texto_bloco(campos[c])
        return None
    forum = ForumTurma(
        id=forum_id,
        titulo=v("titulo") or "(fórum)",
        descricao=v("descricao"),
        aula=v("topico de aula"),
        tipo=v("tipo"),
        autor=v("autor(a)", "autor"),
        criado_em=_data_ou_datahora(v("criado em")),
        inicio=_data(v("inicio")),
        fim=_data(v("fim")),
        monitorar_leitura=_sim_nao(v("monitorar leitura")),
        ordenacao=v("ordenacao padrao"),
    )
    topicos = []
    tab = _tabela_listagem(sp)
    if tab is not None:
        for txt, cel, tr in _linhas(tab):
            t = _pega(txt, "mensagem", "titulo", "topico", "assunto")
            if not t:
                continue
            ult = _celula(cel, "ultima")
            ult_txt = _texto_bloco(ult) if ult is not None else None
            autor_ult = ult_txt.split("\n")[0].strip() if ult_txt and not _RE_DATA.match(ult_txt) else None
            topicos.append(
                TopicoForum(
                    id=len(topicos) + 1,
                    titulo=t,
                    autor=_pega(txt, "autor"),
                    respostas=_int(_pega(txt, "respostas")),
                    ultima_mensagem_autor=autor_ult or None,
                    ultima_mensagem_em=_datahora(ult_txt),
                )
            )
    forum.topicos = len(topicos) if topicos or forum.topicos is None else forum.topicos
    return ForumDetalhe(forum=forum, topicos=topicos)


def _anexo(el: Tag | None) -> int | None:
    if el is None:
        return None
    a = el.find(onclick=re.compile(r"'idArquivo'"))
    m = re.search(r"'idArquivo'\s*:\s*'(\d+)'", a["onclick"]) if a is not None else None
    return int(m.group(1)) if m else None


def _sem_anexo(el: Tag | None) -> Tag | None:
    if el is None:
        return None
    copia = BeautifulSoup(str(el), "lxml")
    for a in copia.find_all(onclick=re.compile(r"idArquivo")):
        a.decompose()
    return copia.body or copia


def parse_topico_forum(html: str | bytes, forum_id: int = 1, topico_id: int = 1) -> TopicoForumDetalhe:
    """/ava/Foruns/Mensagem/view.jsf: cabeçalho do tópico (Assunto, Mensagem, Autor, Criado em) + respostas
    (cada uma num span id='form:comConteudo...' com título em <b>, 'por' AUTOR, data em <i>, texto em td.conteudoMensagemForum)."""
    sp = _soup(html)
    cont = _conteudo(sp)
    tab = cont.find("table", class_="formAva")
    campos = _pares_th_td(tab) if tab is not None else {}
    def v(c):
        return _texto_bloco(campos[c]) if c in campos else None
    corpo = campos.get("mensagem")
    principal = MensagemForum(
        titulo=v("assunto"),
        autor=v("autor(a)") or v("autor"),
        data=_datahora(v("criado em")),
        texto=_texto_bloco(_sem_anexo(corpo)) or "",
        texto_html=_inner_html(corpo),
        anexo_id=_anexo(campos.get("arquivo")) or _anexo(corpo),
    )
    respostas = []
    for span in cont.find_all("span", id=re.compile(r"comConteudo")):
        b = span.find("b")
        titulo = _t(b) or None
        td_info = b.find_parent("td") if b is not None else None
        autor = None
        if td_info is not None:
            m = re.search(r"\bpor\s+(.+)$", _t(td_info).replace(titulo or "", "", 1).strip())
            autor = m.group(1).strip() if m else None
        data = None
        for i_el in span.find_all("i"):
            d = _datahora(_t(i_el))
            if d:
                data = d
                break
        corpo_r = span.find("td", class_="conteudoMensagemForum")
        respostas.append(
            MensagemForum(
                titulo=titulo,
                autor=autor,
                data=data,
                texto=_texto_bloco(_sem_anexo(corpo_r)) or "",
                texto_html=_inner_html(corpo_r),
                anexo_id=_anexo(corpo_r),
            )
        )
    topico = TopicoForum(id=topico_id, titulo=principal.titulo or "(tópico)", autor=principal.autor, respostas=len(respostas))
    return TopicoForumDetalhe(forum_id=forum_id, topico=topico, mensagem=principal, respostas=respostas)


def parse_referencia(html: str | bytes, id: int | None = None) -> ReferenciaTurma:
    """/ava/IndicacaoReferencia/mostrar.jsf (Descrição, Tipo, Autor, Ano, URL, Detalhes)."""
    cont = _conteudo(_soup(html))
    campos = _pares_th_td(cont)
    def v(c):
        return _texto_bloco(campos[c]) if c in campos else None
    url_el = campos.get("url")
    a = url_el.find("a", href=True) if url_el is not None else None
    url = a["href"] if a is not None and a["href"] not in ("http://", "https://", "#") else None
    return ReferenciaTurma(
        id=id,
        nome=v("descricao") or v("titulo") or "(referência)",
        tipo=v("tipo"),
        url=url,
        topico=v("topico de aula"),
        autor=v("autor"),
        ano=_int(v("ano")),
        detalhes=v("detalhes"),
    )


def parse_avaliacao(html: str | bytes, id: int | None = None) -> Avaliacao:
    """/ava/DataAvaliacao/mostrar.jsf (Descrição, Data da Avaliação, Hora da Avaliação)."""
    campos = _pares_th_td(_conteudo(_soup(html)))
    def v(c):
        return _t(campos[c]) if c in campos else None
    hora = v("hora da avaliacao") or v("hora")
    return Avaliacao(id=id, descricao=v("descricao") or "(avaliação)", data=_data(v("data da avaliacao") or v("data")), hora=hora if hora and re.match(r"\d{1,2}:\d{2}", hora) else None)


# ===================================================================== notas
def parse_notas(html: str | bytes) -> NotasTurma:
    """'Ver Notas': relatório com cabeçalho de 2 linhas (Unid. N com colspan + as avaliações da unidade,
    cujos nome/peso vêm em inputs hidden denAval_*/pesoAval_*). Quando não há notas o SIGAA fica na
    tela anterior com a mensagem 'Ainda não foram lançadas notas.'"""
    sp = _soup(html)
    msgs = mensagens(html)
    res = NotasTurma()
    h3 = sp.find("h3")
    if h3 is not None:
        m = re.match(r"(\S+)\s*-\s*(.+?)(?:\s*\(\d+h\))?\s*-\s*Turma.*?\((\d{4}\.\d)\)", _t(h3))
        if m:
            res.codigo, res.nome, res.periodo = m.group(1), m.group(2), m.group(3)
    tab = sp.find("table", class_="tabelaRelatorio")
    if tab is None:
        tab = next((t for t in sp.find_all("table") if "unid" in _norm(_t(t.find("tr")))), None)
    if tab is None:
        res.lancadas = False
        res.mensagem = next((m for m in msgs if "nota" in _norm(m)), msgs[0] if msgs else None)
        return res
    thead = tab.find("thead") or tab
    trs = thead.find_all("tr")
    # linha 1: grupos; linha 2: avaliações (opcional)
    grupos: list[tuple[str, int]] = [(_t(th), int(th.get("colspan", 1) or 1)) for th in trs[0].find_all("th")]
    sub: list[Tag | None] = []
    if len(trs) > 1:
        sub = trs[1].find_all("th")
    colunas: list[tuple[str, str | None, Tag | None]] = []  # (grupo, sub-rótulo, th)
    si = 0
    for nome, span in grupos:
        if span > 1:
            for _ in range(span):
                th = sub[si] if si < len(sub) else None
                colunas.append((nome, _t(th) if th is not None else None, th))
                si += 1
        else:
            colunas.append((nome, None, None))
            if sub and si < len(sub) and not _t(sub[si]):
                si += 1
    corpo = tab.find("tbody") or tab
    tr_aluno = next((tr for tr in corpo.find_all("tr") if tr.find("td") and not tr.find_parent("thead")), None)
    if tr_aluno is None:
        res.lancadas = False
        res.mensagem = msgs[0] if msgs else "Nenhuma linha de notas."
        return res
    tds = tr_aluno.find_all("td", recursive=False)
    unidades: dict[str, NotaUnidade] = {}
    for (grupo, subrot, th), td in zip(colunas, tds):
        val = _t(td)
        g = _norm(grupo)
        chave = f"{grupo} / {subrot}" if subrot else grupo
        res.colunas[chave] = val
        if g.startswith("unid") or re.match(r"(n|u|p)\d", g) or (g.startswith("nota") and g != "nota final"):
            u = unidades.setdefault(grupo, NotaUnidade(rotulo=grupo))
            if subrot is None or _norm(subrot) in ("nota", "media", ""):
                u.nota = _float(val)
            else:
                aid = (th.get("id") or "").replace("aval_", "") if th is not None else ""
                den = sp.find("input", id=f"denAval_{aid}") if aid else None
                peso = sp.find("input", id=f"pesoAval_{aid}") if aid else None
                u.avaliacoes.append(
                    AvaliacaoNota(
                        id=int(aid) if aid.isdigit() else None,
                        abreviacao=subrot,
                        denominacao=den.get("value") if den is not None else None,
                        peso=_float(peso.get("value")) if peso is not None else None,
                        nota=_float(val),
                    )
                )
        elif "reposicao" in g or "recuperacao" in g or "prova final" in g:
            res.reposicao = _float(val)
        elif "resultado" in g or "media" in g or g == "nota final":
            res.resultado = _float(val)
        elif "falta" in g:
            res.faltas = _int(val)
        elif g.startswith("sit"):
            res.situacao = val or None
    res.unidades = list(unidades.values())
    return res


# ===================================================================== frequência
def parse_frequencia(html: str | bytes) -> Frequencia:
    sp = _soup(html)
    cont = _conteudo(sp)
    freq = Frequencia()
    tab = _tabela_listagem(sp)
    if tab is not None:
        for txt, cel, tr in _linhas(tab):
            d = _data(_pega(txt, "data") or next(iter(txt.values()), ""))
            sit = _pega(txt, "situacao", "frequencia", "presenca") or ""
            if d is None:
                continue
            n = _norm(sit)
            if "nao registrad" in n or not n:
                faltas, reg = None, False
            elif "presente" in n:
                faltas, reg = 0, True
            else:
                faltas, reg = _int(sit), True
            freq.registros.append(RegistroFrequencia(data=d, situacao=sit, faltas=faltas, registrada=reg))
    freq.total_faltas = sum(r.faltas or 0 for r in freq.registros)
    txt = _t(cont)
    if "frequencia ainda nao foi lancada" in _norm(txt):
        # o SIGAA imprime totais de lixo nesse caso (sempre 59/59/100%): não confie neles
        freq.lancada = False
        m = re.search(r"([\d.,]+)\s*%\s*da carga hor", txt)
        freq.minimo_percentual = _float(m.group(1)) if m else None
        m = re.search(r"aula dura\s*(\d+)\s*minutos", txt)
        freq.duracao_aula_min = int(m.group(1)) if m else None
        return freq
    def num(rot: str) -> str | None:
        m = re.search(re.escape(rot) + r"[^:]*:\s*([\d.,]+)", txt, re.I)
        return m.group(1) if m else None
    freq.presencas_registradas = _int(num("Presenças Registradas"))
    freq.aulas_com_registro = _int(num("Número de Aulas com Registro de Frequência"))
    freq.percentual_registradas = _float(num("Porcentagem de Frequência em relação as Aulas com Registro"))
    freq.aulas_ch = _int(num("Número de Aulas definidas pela CH"))
    freq.percentual_ch = _float(num("Porcentagem de Frequência em relação a CH"))
    m = re.search(r"([\d.,]+)\s*%\s*da carga hor", txt)
    freq.minimo_percentual = _float(m.group(1)) if m else None
    m = re.search(r"aula dura\s*(\d+)\s*minutos", txt)
    freq.duracao_aula_min = int(m.group(1)) if m else None
    if freq.aulas_ch and freq.minimo_percentual:
        freq.max_faltas = int(freq.aulas_ch * (1 - freq.minimo_percentual / 100))
        freq.faltas_restantes = freq.max_faltas - freq.total_faltas
    return freq


# ===================================================================== outros
def parse_linha_tempo(html: str | bytes) -> list[EventoLinhaTempo]:
    sp = _soup(html)
    out = []
    for box in _conteudo(sp).select(".box-conversation"):
        autor = box.find("strong")
        span = box.select_one(".description-student span")
        tipo = _t(span).rstrip(":").strip() if span else ""
        titulo = None
        if span is not None and span.parent is not None:
            titulo = _t(span.parent).replace(_t(span), "", 1).strip() or None
        data_el = box.find(class_=re.compile(r"data(Esq|Dir)?"))
        corpo = box.find(class_="content")
        out.append(
            EventoLinhaTempo(
                autor=_t(autor) or None,
                tipo=tipo or "(evento)",
                titulo=titulo,
                data=_datahora(_t(data_el)) if data_el else None,
                texto=_texto_bloco(BeautifulSoup(str(corpo), "lxml")) if corpo else None,
            )
        )
    return out


def parse_grupo(html: str | bytes) -> GrupoTurma:
    sp = _soup(html)
    cont = _conteudo(sp)
    vazio = cont.find(class_="empty-listing")
    if vazio is not None and "nenhum grupo" in _norm(_t(vazio)):
        return GrupoTurma(cadastrado=False)
    nome = None
    for el in cont.find_all(["th", "label", "b", "strong"]):
        if _norm(_t(el)) in ("nome", "grupo", "nome do grupo"):
            alvo = el.find_next_sibling(["td", "span"]) or el.find_next("td")
            if alvo is not None and alvo.name != "input":
                nome = _t(alvo) or nome
    membros = []
    tab = _tabela_listagem(sp)
    if tab is not None:
        for txt, cel, tr in _linhas(tab):
            n = _pega(txt, "nome", "discente", "aluno") or next((v for v in txt.values() if v), None)
            if n:
                membros.append(n)
    leg = cont.find("legend")
    if nome is None and leg is not None and "grupo" in _norm(_t(leg)):
        nome = _t(leg)
    return GrupoTurma(cadastrado=True, nome=nome, membros=membros)


def parse_estatisticas(html: str | bytes) -> EstatisticasTurma:
    sp = _soup(html)
    cont = _conteudo(sp)
    leg = cont.find("legend")
    valores = {}
    for tr in cont.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is not None and td is not None:
            valores[_t(th).rstrip(":")] = _t(td)
    img = cont.find("img", src=re.compile("cewolf"))
    if img is not None:
        valores["grafico_url"] = _html.unescape(img["src"])
    return EstatisticasTurma(titulo=_t(leg) or None, vazio=not valores, valores=valores)


def url_grafico_estatisticas(html: str | bytes) -> str | None:
    img = _soup(html).find("img", src=re.compile("cewolf"))
    return _html.unescape(img["src"]) if img is not None else None
