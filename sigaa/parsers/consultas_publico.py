"""Parsers do SIGAA PÚBLICO (sem login). Funções PURAS: recebem o HTML (str ou bytes) e devolvem modelos.

Tolerância: procuram por RÓTULO (texto do th/dt/label), nunca por posição; campo que some vira
``None``; tabela vazia ou "Nenhum conteúdo..." vira ``[]``. Algumas páginas públicas vêm em UTF-8
(portais de centro/departamento) e outras em ISO-8859-1 — ``bytes`` são decodificados sozinhos.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
import warnings
from datetime import date, datetime

from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

from sigaa.models.consultas_publico import (
    AcaoExtensao,
    AcaoExtensaoResumo,
    AcervoArtigo,
    AcervoExemplar,
    AcervoTitulo,
    AcervoTituloDetalhe,
    AcordoMobilidade,
    ApresentacaoProgramaPos,
    AquisicaoBiblioteca,
    AreaConcentracaoPos,
    BasePesquisa,
    BolsistaPesquisa,
    CargaHorariaItem,
    Centro,
    CentroCursoAberto,
    CentroResumo,
    ComponenteCurricular,
    ComponenteEstrutura,
    ComponenteRef,
    ComponenteResumo,
    CoordenadorProgramaPos,
    CurriculoDoComponente,
    Curso,
    CursoAberto,
    CursoAbertoTurma,
    CursoDoCentro,
    CursoProgramaPos,
    CursoResumo,
    Departamento,
    DepartamentoCursoAberto,
    DepartamentoResumo,
    DisciplinaMinistrada,
    Docente,
    DocenteCursoAberto,
    DocenteProgramaPos,
    DocenteResumo,
    DocenteTurma,
    DocenteTurmaCurso,
    DocumentoProcessoSeletivo,
    EquivalenciaHistorico,
    EstruturaCurricular,
    EstruturaResumo,
    EtapaProcessoSeletivo,
    EventoCalendarioCurso,
    FormacaoAcademica,
    InscricaoExtensaoAberta,
    LaboratorioPesquisa,
    LaboratorioPesquisaResumo,
    LinhaPesquisaPos,
    MaterialCursoAberto,
    MembroComissaoProcessoSeletivo,
    MembroEquipePublica,
    MiniAtividadeExtensao,
    NivelEstrutura,
    NoticiaCurso,
    NoticiaProcessoSeletivo,
    NoticiaProgramaPos,
    NoticiaProgramaPosDetalhe,
    NovaAquisicaoBiblioteca,
    NovasAquisicoesBiblioteca,
    OpcaoSelect,
    Pessoa,
    ProcessoSeletivo,
    ProcessoSeletivoProgramaPos,
    ProcessoSeletivoResumo,
    ProducaoCategoria,
    ProducaoItem,
    ProgramaComponente,
    ProgramaPos,
    ProgramaPosResumo,
    ProjetoPedagogico,
    ProjetoPesquisa,
    ProjetoPesquisaResumo,
    Responsavel,
    TopicoCursoAberto,
    TurmaCurso,
    TurmaPublica,
    UnidadeAcademica,
    UnidadeRef,
)
from sigaa.util.horario import decodificar, separar_locais

# ------------------------------------------------------------------------- utilidades
_VAZIOS = {
    "",
    "-",
    "--",
    "nenhum conteudo disponivel ate o momento",
    "nao informado",
    "nao informada",
    "nao cadastrado",
    "nao cadastrada",
}
_RE_CODIGO = re.compile(r"\b([A-Z]{2,}[A-Z0-9/]*\d+[A-Z]?)\b")
_RE_DATA = re.compile(r"(\d{2}/\d{2}/\d{4})")
_RE_JSF = re.compile(r"jsfcljs\(document\.getElementById\('([^']+)'\),\s*\{(.*?)\}", re.S)
_RE_PARAM = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")


def _decode(html: str | bytes) -> str:
    if isinstance(html, str):
        return html
    try:
        return html.decode("utf-8")
    except UnicodeDecodeError:
        return html.decode("iso-8859-1", errors="replace")


def _soup(html: str | bytes | BeautifulSoup) -> BeautifulSoup:
    if isinstance(html, BeautifulSoup):
        return html
    return BeautifulSoup(_decode(html), "lxml")


def _limpa(s: str | None) -> str:
    if s is None:
        return ""
    s = _html.unescape(s).replace("\xa0", " ").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def _txt(el: Tag | None, sep: str = " ") -> str:
    if el is None:
        return ""
    return _limpa(el.get_text(sep))


def _linhas(el: Tag | None) -> list[str]:
    """Texto do elemento quebrado nas <br>/blocos, sem linhas vazias."""
    if el is None:
        return []
    bruto = el.get_text("\n")
    return [x for x in (_limpa(p) for p in bruto.split("\n")) if x]


def _norm(s: str | None) -> str:
    s = _limpa(s).lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.strip(" :.").strip()


def _valor(s: str | None) -> str | None:
    s = _limpa(s)
    return None if _norm(s) in _VAZIOS else s


def _multilinha(el: Tag | None) -> str | None:
    """Texto preservando as quebras de linha (<br>) — None se vazio/'não informado'."""
    linhas = [x for x in _linhas(el) if _valor(x)]
    return "\n".join(linhas) or None


def _int(s: str | None) -> int | None:
    m = re.search(r"-?\d+", _limpa(s))
    return int(m.group()) if m else None


def _ch(s: str | None) -> int | None:
    """'60h', '60 h.', '3101h' → 60/3101."""
    m = re.search(r"(\d+)\s*h", _limpa(s), re.I)
    return int(m.group(1)) if m else _int(s)


def _data(s: str | None) -> date | None:
    m = _RE_DATA.search(_limpa(s))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y").date()
    except ValueError:
        return None


def _bool(s: str | None) -> bool | None:
    n = _norm(s)
    if n in ("sim", "s", "ativa", "ativo", "true"):
        return True
    if n in ("nao", "n", "inativa", "inativo", "false"):
        return False
    return None


def _jsf(el: Tag | None) -> dict[str, str]:
    """Parâmetros do jsfcljs de um link (``{'id': '123', ...}``)."""
    if el is None:
        return {}
    m = _RE_JSF.search(el.get("onclick") or "")
    return dict(_RE_PARAM.findall(m.group(2))) if m else {}


def _qs_int(href: str | None, nome: str) -> int | None:
    if not href:
        return None
    m = re.search(rf"[?&]\s*{nome}=\s*(\d+)", href.replace("\n", "").replace("\t", ""))
    return int(m.group(1)) if m else None


def _codigo_nome(s: str) -> tuple[str, str, int | None]:
    """'MATA37 - INTRODUÇÃO À LÓGICA DE PROGRAMAÇÃO - 60h' → (código, nome, 60)."""
    s = _limpa(s)
    ch = None
    m = re.search(r"\s*-\s*(\d+)\s*h\.?\s*$", s)
    if m:
        ch = int(m.group(1))
        s = s[: m.start()]
    cod, _, nome = s.partition(" - ")
    return cod.strip(), nome.strip(), ch


def _codigos(expr: str | None) -> list[str]:
    if not expr:
        return []
    out: list[str] = []
    for c in _RE_CODIGO.findall(expr):
        if c not in ("OU", "E") and c not in out:
            out.append(c)
    return out


def _pares(container: Tag | None) -> dict[str, Tag]:
    """{rótulo normalizado: td} para as linhas <tr><th>Rótulo</th><td>valor</td></tr> (só o 1º nível de cada tr)."""
    out: dict[str, Tag] = {}
    if container is None:
        return out
    for tr in container.find_all("tr"):
        for th in tr.find_all("th", recursive=False):
            td = th.find_next_sibling(["td", "th"])
            if td is not None and td.name == "td":
                out.setdefault(_norm(th.get_text(" ")), td)
    return out


def _pega(pares: dict[str, Tag], *rotulos: str) -> Tag | None:
    """Primeiro valor cujo rótulo normalizado começa com (ou é igual a) algum dos rótulos dados."""
    alvos = [_norm(r) for r in rotulos]
    for a in alvos:
        if a in pares:
            return pares[a]
    for a in alvos:
        for k, v in pares.items():
            if k.startswith(a):
                return v
    return None


def _dl(container: Tag | None) -> dict[str, Tag]:
    """{rótulo normalizado do <dt>: <dd> (o primeiro)} — e os <dd> extras ficam em ``_dl_todos``."""
    out: dict[str, Tag] = {}
    if container is None:
        return out
    for dt in container.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            out.setdefault(_norm(dt.get_text(" ")), dd)
    return out


def _dl_todos(container: Tag | None, rotulo: str) -> list[Tag]:
    """Todos os <dd> que seguem o <dt> do rótulo até o próximo <dt>."""
    if container is None:
        return []
    alvo = _norm(rotulo)
    for dt in container.find_all("dt"):
        if _norm(dt.get_text(" ")).startswith(alvo):
            out = []
            for sib in dt.find_next_siblings():
                if sib.name == "dt":
                    break
                if sib.name == "dd":
                    out.append(sib)
            return out
    return []


def _pessoas_links(els: list[Tag]) -> list[Pessoa]:
    out: list[Pessoa] = []
    for el in els:
        links = el.find_all("a", href=re.compile("siape"))
        if links:
            for a in links:
                nome = _txt(a)
                if nome:
                    out.append(Pessoa(nome=nome, siape=_qs_int(a.get("href"), "siape")))
        else:
            nome = _valor(_txt(el))
            if nome:
                out.append(Pessoa(nome=nome))
    return out


def _mensagens(soup: BeautifulSoup) -> str:
    """Texto das caixas de mensagem do SIGAA (erros/avisos)."""
    caixas = soup.select("#painel-erros, .erros, ul.erros, .warning, .info, .alert")
    return " ".join(_txt(c) for c in caixas)


def sem_resultados(html: str | bytes) -> bool:
    """True quando a página diz que a busca não achou nada."""
    t = _norm(_soup(html).get_text(" "))
    return any(
        k in t
        for k in (
            "nenhum registro encontrado",
            "nenhum resultado encontrado",
            "nenhuma turma encontrada",
            "nenhum componente",
            "nenhum docente",
            "nao foram encontrados",
            "nao foi encontrado",
        )
    )


def parse_opcoes(html: str | bytes, select_id: str) -> list[OpcaoSelect]:
    """Opções de um <select> (por id ou name), sem a opção 'SELECIONE/TODOS' de valor vazio/0."""
    sp = _soup(html)
    sel = sp.find("select", id=select_id) or sp.find("select", attrs={"name": select_id})
    if sel is None:
        return []
    out = []
    for o in sel.find_all("option"):
        v = (o.get("value") or "").strip()
        r = _txt(o)
        if v in ("", "0") or "selecione" in _norm(r) or _norm(r) in ("todos", "-- todos --"):
            continue
        out.append(OpcaoSelect(valor=v, rotulo=r))
    return out


# ------------------------------------------------------------------------------ cursos
def parse_lista_cursos(html: str | bytes, nivel: str = "G") -> list[CursoResumo]:
    """public/curso/lista.jsf?nivel=X — linhas agrupadas por unidade (td.subFormulario)."""
    sp = _soup(html)
    tabela = None
    for t in sp.find_all("table", class_="listagem"):
        cap = t.find("caption")
        if cap and "curso" in _norm(cap.get_text()):
            tabela = t
            break
    if tabela is None:
        return []
    cab = [_norm(th.get_text()) for th in tabela.select("thead th")]
    out: list[CursoResumo] = []
    unidade = None
    programa_id = None
    for tr in tabela.select("tbody tr"):
        sub = tr.find("td", class_="subFormulario")
        if sub is not None:
            unidade = _txt(sub) or None
            a = sub.find("a", href=True)
            programa_id = _qs_int(a["href"], "id") if a else None
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        celulas = {cab[i] if i < len(cab) else str(i): tds[i] for i in range(len(tds))}
        a_get = tr.find("a", href=re.compile(r"portal\.jsf\?id="))
        a_jsf = next((a for a in tr.find_all("a", onclick=True) if "id" in _jsf(a)), None)
        cid = _qs_int(a_get["href"], "id") if a_get else None
        if cid is None and a_jsf is not None:
            cid = _int(_jsf(a_jsf).get("id"))
        if cid is None:
            continue
        out.append(
            CursoResumo(
                id=cid,
                nome=_txt(celulas.get("nome", tds[0])),
                nivel=nivel,
                nivel_texto=_valor(_txt(celulas.get("nivel"))),
                unidade=unidade,
                programa_id=programa_id,
                sede=_valor(_txt(celulas.get("sede"))),
                modalidade=_valor(_txt(celulas.get("modalidade"))),
                coordenador=_valor(_txt(celulas.get("coordenador"))),
                url_portal=f"/sigaa/public/curso/portal.jsf?id={cid}&lc=pt_BR" if a_get else None,
            )
        )
    return out


def _topicos(container: Tag) -> dict[str, str | None]:
    """<span class="topico">Rótulo: <strong>valor</strong></span> → {rótulo: valor}."""
    out: dict[str, str | None] = {}
    for sp_ in container.find_all("span", class_=re.compile("topico")):
        forte = sp_.find(["strong", "label"])
        if sp_.find("label") is not None and sp_.find("strong") is None:
            # ppp.jsf: <span class="topico2"><label>Rótulo:</label> valor</span>
            lab = sp_.find("label")
            rot = _norm(lab.get_text())
            lab_txt = _txt(lab)
            valor = _limpa(_txt(sp_)[len(lab_txt):])
            a = sp_.find("a", href=True)
            out[rot] = _valor(valor) or (a["href"] if a else None)
            continue
        if forte is None:
            continue
        valor = _txt(forte)
        rot = _norm(_txt(sp_).replace(valor, "", 1))
        out[rot] = _valor(valor)
    return out


def parse_curso_portal(html: str | bytes, curso_id: int | None = None, nivel: str = "G") -> Curso:
    """public/curso/portal.jsf?id=N (graduação): apresentação, coordenação, títulos, calendário resumido."""
    sp = _soup(html)
    nome_el = sp.select_one("#nomes .nome_curso") or sp.select_one(".nome_curso")
    centro_el = sp.select_one("#nomes .nome_centro") or sp.select_one(".nome_centro")
    nome = _txt(nome_el) or None
    if nome:
        nome = re.sub(r"^CURSO DE\s+", "", nome, flags=re.I).strip(" /-")
    if not nome or not re.search(r"[A-Za-zÀ-ÿ]{2,}", nome):
        nome = None  # id inexistente: o SIGAA renderiza o template vazio (' / ')
    if curso_id is None:
        a = sp.find("a", href=re.compile(r"curso/portal\.jsf\?[^\"]*id="))
        curso_id = _qs_int(a["href"], "id") if a else None
    esq = sp.find(id="esquerda") or sp.find(id="conteudo") or sp
    top = _topicos(esq)
    coord = []
    for k, v in top.items():
        if k.startswith("coordenacao") and v:
            coord.append(Pessoa(nome=v, cargo="Coordenação"))
    info = esq.find(class_="informacoes")
    tel = email = None
    if info:
        for p in info.find_all("p"):
            rot = _norm(p.get_text(" ").split(":")[0])
            val = _valor(_txt(p.find(class_="cor")))
            if rot.startswith("telefone"):
                tel = val
            elif rot.startswith("e-mail") or rot.startswith("email"):
                email = val
    apres = _valor(_txt(esq.find("div", class_="texto")))
    calendario = []
    lista = sp.select_one("#listagem3")
    if lista:
        for li in lista.find_all("li"):
            ev = li.find(class_="evento")
            desc = _limpa(_txt(ev).lstrip("·").strip()) if ev else ""
            datas = _RE_DATA.findall(_txt(li).replace(_txt(ev), "") if ev else _txt(li))
            if not desc:
                continue
            calendario.append(
                EventoCalendarioCurso(
                    periodo=(re.search(r"\d{4}\.\d", desc) or [None])[0],
                    descricao=desc,
                    data_inicio=_data(datas[0]) if datas else None,
                    data_fim=_data(datas[1]) if len(datas) > 1 else None,
                )
            )
    return Curso(
        id=curso_id or 0,
        nivel=nivel,
        nome=nome,
        unidade=_txt(centro_el) or None,
        modalidade=top.get("modalidade de curso") or top.get("modalidade"),
        coordenacao=coord,
        telefones=[tel] if tel else [],
        emails=[email] if email else [],
        titulo_profissional=top.get("titulo do profissional"),
        area_conhecimento=top.get("area de conhecimento cnpq"),
        convenio_academico=top.get("convenio academico"),
        endereco_alternativo=top.get("endereco alternativo"),
        apresentacao=apres,
        calendario=calendario,
    )


def parse_curso_detalhe_pos(html: str | bytes, curso_id: int | None = None, nivel: str = "S") -> Curso:
    """'Consulta de Cursos > Detalhes do Curso' (pós: aberta pelo link jsfcljs da lista)."""
    sp = _soup(html)
    tabela = None
    for t in sp.find_all("table"):
        cap = t.find("caption", recursive=False)
        if cap and "detalhes do curso" in _norm(cap.get_text()):
            tabela = t
            break
    tabela = tabela or sp
    pares = _pares(tabela)
    coord = []
    for linha in _linhas(_pega(pares, "Coordenação do Curso", "Coordenação")):
        m = re.match(r"(.+?)\s*\((.+)\)\s*$", linha)
        coord.append(Pessoa(nome=m.group(1).strip(), cargo=m.group(2).strip()) if m else Pessoa(nome=linha))
    pagina = _pega(pares, "Página Oficial")
    a = pagina.find("a", href=True) if pagina else None
    return Curso(
        id=curso_id or 0,
        nivel=nivel,
        nome=_valor(_txt(_pega(pares, "Candidato ao curso de", "Curso"))),
        nivel_texto=_valor(_txt(_pega(pares, "Nível"))),
        unidade=_valor(_txt(_pega(pares, "Unidade"))),
        municipio=_valor(_txt(_pega(pares, "Município"))),
        modalidade=_valor(_txt(_pega(pares, "Modalidade de Ensino", "Modalidade"))),
        coordenacao=coord,
        telefones=[x for x in _linhas(_pega(pares, "Telefone")) if _valor(x)],
        emails=[x for x in _linhas(_pega(pares, "E-mail")) if _valor(x)],
        pagina_oficial=(a["href"] if a else _valor(_txt(pagina))),
        conceito=_valor(_txt(_pega(pares, "Conceito"))),
        portaria=_valor(_txt(_pega(pares, "Portaria"))),
        estruturas=parse_estruturas_curso(sp),
    )


def parse_estruturas_curso(html: str | bytes | BeautifulSoup) -> list[EstruturaResumo]:
    """Estruturas listadas em public/curso/curriculo.jsf (graduação) ou no 'Detalhes do Curso' (pós)."""
    sp = _soup(html)
    out: list[EstruturaResumo] = []
    vistos: set[int] = set()
    turno = None
    for tr in sp.find_all("tr"):
        if "campos" in (tr.get("class") or []) and not tr.find("a"):
            turno = _txt(tr) or None
            continue
        links = [a for a in tr.find_all("a", onclick=True, recursive=True) if "id" in _jsf(a)]
        if not links or tr.find("tr") is not None:
            continue
        texto = _txt(tr.find("td"))
        m = re.search(r"Estrutura Curricular\s+([^,\s]+)\s*,?\s*Criado em\s*([\d.]+)?", texto, re.I)
        if not m:
            continue
        eid = _int(_jsf(links[0]).get("id"))
        if eid is None or eid in vistos:
            continue
        vistos.add(eid)
        tds = tr.find_all("td", recursive=False)
        status = _valor(_txt(tds[1])) if len(tds) >= 3 else None
        out.append(
            EstruturaResumo(
                id=eid,
                codigo=m.group(1),
                ano_criacao=m.group(2),
                status=status,
                ativa=_bool(status) if status else None,
                turno=turno,
            )
        )
    return out


def parse_calendario_curso(html: str | bytes) -> list[EventoCalendarioCurso]:
    """public/curso/calendario.jsf?id=N — blocos por período (div#group_lt) com <b>datas</b> → evento."""
    sp = _soup(html)
    out: list[EventoCalendarioCurso] = []
    for bloco in sp.find_all("div", id="listagem_tabela"):
        grupo = bloco.find(id="group_lt")
        periodo = _txt(grupo) or None
        for td in bloco.find_all("td"):
            b = td.find("b")
            datas = _RE_DATA.findall(_txt(b)) if b else []
            desc = _txt(td)
            if b:
                desc = desc.replace(_txt(b), "", 1)
            desc = _limpa(desc).lstrip("→ ").strip()
            if not desc:
                continue
            out.append(
                EventoCalendarioCurso(
                    periodo=periodo,
                    descricao=desc,
                    data_inicio=_data(datas[0]) if datas else None,
                    data_fim=_data(datas[1]) if len(datas) > 1 else None,
                )
            )
    return out


def parse_ppp(html: str | bytes, curso_id: int) -> ProjetoPedagogico:
    sp = _soup(html)
    cont = sp.find(id="conteudo") or sp
    top = _topicos(cont)

    def g(*k: str) -> str | None:
        for kk in k:
            for rot, v in top.items():
                if rot.startswith(_norm(kk)):
                    return v
        return None

    return ProjetoPedagogico(
        curso_id=curso_id,
        perfil_profissional=g("Perfil Profissional"),
        competencias_habilidades=g("Competências e Habilidades"),
        metodologia=g("Metodologia"),
        avaliacao=g("Avaliação do Curso"),
        projeto_pedagogico=g("Projeto Pedagógico"),
    )


def parse_noticias_curso(html: str | bytes) -> list[NoticiaCurso]:
    sp = _soup(html)
    out: list[NoticiaCurso] = []
    tabela = sp.find(id="table_lt") or sp.find("table", class_="listagem")
    if tabela is None:
        return out
    for tr in tabela.find_all("tr"):
        if "campos" in (tr.get("class") or []):
            continue
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        titulo = _txt(tds[1])
        if not titulo:
            continue
        out.append(NoticiaCurso(data=_data(_txt(tds[0])), titulo=titulo, texto=_valor(_txt(tds[2])) if len(tds) > 2 else None))
    return out


def parse_turmas_curso(html: str | bytes) -> list[TurmaCurso]:
    """public/curso/turmas.jsf (resultado da busca Ano.Período/Código) — um bloco por componente."""
    sp = _soup(html)
    out: list[TurmaCurso] = []
    for bloco in sp.find_all("div", id="listagem_tabela"):
        g = bloco.find(id="group_lt")
        if g is None:
            continue
        a = g.find("a")
        cod, nome, _ = _codigo_nome(_txt(g))
        cid = _int(_jsf(a).get("id")) if a else None
        tabela = bloco.find("table")
        if tabela is None:
            continue
        cab = []
        for tr in tabela.find_all("tr"):
            if "campos" in (tr.get("class") or []):
                cab = [_norm(td.get_text(" ")) for td in tr.find_all("td")]
                continue
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue
            col = {}
            for i, td in enumerate(tds):
                k = cab[i] if i < len(cab) else str(i)
                col[k] = td

            def c(prefixo: str) -> Tag | None:
                return next((v for k, v in col.items() if k.startswith(prefixo)), None)

            doc_td = c("docente")
            docentes = [
                DocenteTurmaCurso(nome=_txt(x), siape=_qs_int(x.get("href"), "siape"))
                for x in (doc_td.find_all("a") if doc_td else [])
                if _txt(x)
            ]
            if doc_td is not None and not docentes:
                docentes = [DocenteTurmaCurso(nome=n.strip()) for n in _txt(doc_td).split(",") if n.strip()]
            hor = c("horario")
            out.append(
                TurmaCurso(
                    componente_id=cid,
                    codigo_componente=cod,
                    nome_componente=nome,
                    periodo=_valor(_txt(c("periodo"))),
                    turma=_valor(_txt(c("turma"))),
                    docentes=docentes,
                    vagas_reservadas=_int(_txt(c("vgs") or c("vagas"))),
                    horario=decodificar(_txt(hor)) if hor is not None and _txt(hor) else None,
                )
            )
    return out


# ------------------------------------------------------------------ estrutura curricular
def _componente_da_linha(tr: Tag) -> ComponenteEstrutura | None:
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 2:
        return None
    txt0 = _txt(tds[0])
    if not re.match(r"^\S+\s+-\s+.+", txt0):
        return None
    cod, nome, ch = _codigo_nome(txt0)
    natureza = _valor(_txt(tds[1]))
    link = next((a for a in tr.find_all("a", onclick=True) if "id" in _jsf(a)), None)
    cid = _int(_jsf(link).get("id")) if link else None
    if cid is None:
        prog = next((a for a in tr.find_all("a", onclick=True) if "idComponente" in _jsf(a)), None)
        cid = _int(_jsf(prog).get("idComponente")) if prog else None
    return ComponenteEstrutura(
        id=cid,
        codigo=cod,
        nome=nome,
        carga_horaria=ch,
        natureza=natureza,
        obrigatoria=(_norm(natureza) == "obrigatoria") if natureza else None,
    )


def _total_da_linha(tr: Tag) -> int | None:
    tds = tr.find_all("td", recursive=False)
    if not tds:
        return None
    t = _txt(tds[0])
    if re.search(r"(Carga Hor[aá]ria Total|CH Total)\s*:", t, re.I):
        return _ch(t.split(":", 1)[1])
    return None


def parse_estrutura_curricular(html: str | bytes, estrutura_id: int | None = None, curso_id: int | None = None) -> EstruturaCurricular:
    """Detalhes (abas por nível) ou Relatório da Estrutura Curricular — os dois formatos."""
    sp = _soup(html)
    pares = _pares(sp)

    def ch(*r: str) -> int | None:
        return _ch(_txt(_pega(pares, *r)))

    niveis: list[NivelEstrutura] = []
    optativas: list[ComponenteEstrutura] = []
    complementares: list[ComponenteEstrutura] = []
    ch_opt_listadas = None

    def bloco(rotulo: str) -> NivelEstrutura:
        n = _norm(rotulo)
        if n.startswith("optativa"):
            tipo, num = "optativas", None
        elif n.startswith("complementar"):
            tipo, num = "complementares", None
        else:
            tipo, num = "nivel", _int(rotulo)
        nv = NivelEstrutura(nivel=num, rotulo=_limpa(rotulo), tipo=tipo)
        niveis.append(nv)
        return nv

    atual: NivelEstrutura | None = None
    abas = sp.find(id="tabs-semestres")
    if abas is not None:
        # formato 1: abas — div#optativas / #complementares / #semestreN, cada uma com table>caption
        for t in abas.find_all("table", class_="subFormulario"):
            cap = t.find("caption")
            if cap is None:
                continue
            atual = bloco(_txt(cap))
            for tr in t.find_all("tr"):
                if tr.find_parent("table") is not t:
                    continue
                tot = _total_da_linha(tr)
                if tot is not None:
                    atual.carga_horaria_total = tot
                    continue
                c = _componente_da_linha(tr)
                if c is not None:
                    atual.componentes.append(c)
    else:
        # formato 2: relatório — linhas em sequência: tr.tituloRelatorio abre o bloco, tr.componentes, 'CH Total:'
        for tr in sp.find_all("tr"):
            if "tituloRelatorio" in (tr.get("class") or []):
                atual = bloco(_txt(tr))
                continue
            if atual is None:
                continue
            tot = _total_da_linha(tr)
            if tot is not None:
                atual.carga_horaria_total = tot
                continue
            if "componentes" in (tr.get("class") or []) or tr.find("a", onclick=True):
                c = _componente_da_linha(tr)
                if c is not None:
                    atual.componentes.append(c)
    for nv in niveis:
        if nv.tipo == "optativas":
            optativas, ch_opt_listadas = nv.componentes, nv.carga_horaria_total
        elif nv.tipo == "complementares":
            complementares = nv.componentes
    so_niveis = [n for n in niveis if n.tipo == "nivel"]
    return EstruturaCurricular(
        id=estrutura_id,
        curso_id=curso_id,
        codigo=_valor(_txt(_pega(pares, "Código"))),
        matriz_curricular=_valor(_txt(_pega(pares, "Matriz Curricular"))),
        periodo_vigor=_valor(_txt(_pega(pares, "Período Letivo de Entrada em Vigor"))),
        ch_total_minima=ch("Total Mínima"),
        ch_obrigatoria_aula=ch("Subtotal de CH de Aula"),
        ch_obrigatoria_orientacao=ch("Subtotal de CH de Orientação"),
        ch_obrigatoria_total=ch("Total"),
        ch_optativa_minima=ch("Carga Horária Optativa Mínima"),
        ch_complementar_minima=ch("Carga Horária Complementar Mínima"),
        ch_atividade_academica_especifica=ch("Carga Horária Obrigatória Atividade Acadêmica Específica"),
        ch_maxima_eletivos=ch("Carga Horária Máxima de Componentes Eletivos"),
        ch_maxima_periodo=ch("Carga Horária Máxima por Período Letivo"),
        prazo_minimo=_int(_txt(_pega(pares, "Mínimo"))),
        prazo_medio=_int(_txt(_pega(pares, "Médio"))),
        prazo_maximo=_int(_txt(_pega(pares, "Máximo"))),
        niveis=sorted(so_niveis, key=lambda n: n.nivel or 0),
        optativas=optativas,
        complementares=complementares,
        ch_total_optativas_listadas=ch_opt_listadas,
    )


# --------------------------------------------------------------------------- componentes
def parse_busca_componentes(html: str | bytes) -> list[ComponenteResumo]:
    """Resultado de public/componentes/busca_componentes.jsf (form formListagemComponentes)."""
    sp = _soup(html)
    form = sp.find("form", id="formListagemComponentes")
    tabela = form.find("table") if form else None
    if tabela is None:
        return []
    cab = [_norm(th.get_text()) for th in tabela.select("thead th")]
    out: list[ComponenteResumo] = []
    for tr in tabela.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        col = {cab[i] if i < len(cab) else str(i): tds[i] for i in range(len(tds))}
        det = next((a for a in tr.find_all("a", onclick=True) if "id" in _jsf(a)), None)
        prog = next((a for a in tr.find_all("a", onclick=True) if "idComponente" in _jsf(a)), None)
        cod = _txt(col.get("codigo", tds[0]))
        if not cod:
            continue
        out.append(
            ComponenteResumo(
                id=_int(_jsf(det).get("id")) if det else (_int(_jsf(prog).get("idComponente")) if prog else None),
                codigo=cod,
                nome=_txt(col.get("nome", tds[1])),
                tipo=_valor(_txt(col.get("tipo"))),
                carga_horaria=_ch(_txt(col.get("ch total"))),
                tem_programa=prog is not None,
            )
        )
    return out


def parse_componentes_departamento(html: str | bytes) -> list[ComponenteResumo]:
    """public/departamento/componentes.jsf?id=N — tabelas por tipo (h2 DISCIPLINA/ATIVIDADE...)."""
    sp = _soup(html)
    raiz = sp.find(id="disciplinas-docente") or sp.find(id="colDirCorpo") or sp
    out: list[ComponenteResumo] = []
    for tabela in raiz.find_all("table", class_="listagem"):
        h2 = tabela.find_previous("h2")
        tipo = _txt(h2) if h2 else None
        for tr in tabela.find_all("tr"):
            cod_td = tr.find("td", class_="cod") or tr.find("td", class_="codigo")
            if cod_td is None:
                continue
            nome_td = tr.find("td", class_="nome")
            ch_td = tr.find("td", class_="ch")
            a = next((x for x in tr.find_all("a", onclick=True) if "id" in _jsf(x)), None)
            out.append(
                ComponenteResumo(
                    id=_int(_jsf(a).get("id")) if a else None,
                    codigo=_txt(cod_td),
                    nome=_txt(nome_td),
                    tipo=tipo,
                    carga_horaria=_ch(_txt(ch_td)),
                )
            )
    return out


def _refs(tabela: Tag | None) -> list[ComponenteRef]:
    out = []
    if tabela is None:
        return out
    for td in tabela.find_all("td"):
        cod, nome, _ = _codigo_nome(_txt(td))
        if cod:
            out.append(ComponenteRef(codigo=cod, nome=nome or None))
    return out


def _tabela_por_caption(sp: Tag, *trechos: str) -> Tag | None:
    for t in sp.find_all("table"):
        cap = t.find("caption", recursive=False)
        if cap is not None and any(_norm(x) in _norm(cap.get_text()) for x in trechos):
            return t
    return None


def parse_componente(html: str | bytes, componente_id: int | None = None) -> ComponenteCurricular:
    """'Resumo do Componente Curricular' — nos dois formatos que o SIGAA público usa:
    (1) busca_componentes/estrutura/turmas/departamento (com a tabela 'Cargas Horárias');
    (2) /sigaa/link/public/ensino/visualizarComponente/{id} → componentes/resumo.jsf (CH em linhas simples)."""
    sp = _soup(html)
    geral = _tabela_por_caption(sp, "Dados Gerais") or sp
    pares = _pares(geral)
    atributos = {}
    for tr in geral.find_all("tr"):
        th = tr.find("th", recursive=False)
        td = tr.find("td", recursive=False)
        if th is not None and td is not None:
            atributos.setdefault(_limpa(th.get_text(" ")).rstrip(": ").strip(), _txt(td))

    def v(*r: str) -> str | None:
        return _valor(_txt(_pega(pares, *r)))

    pre, co, eq = v("Pré-Requisitos"), v("Co-Requisitos"), v("Equivalências")

    # tabela de cargas horárias (formato 1)
    cargas: list[CargaHorariaItem] = []
    tch = _tabela_por_caption(sp, "Cargas Horárias")
    if tch is not None:
        grupo = None
        for tr in tch.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) == 1:
                grupo = _txt(tds[0]) or grupo
                continue
            if len(tds) >= 2:
                cel = tds[0]
                pop = cel.find(class_="popUp")
                if pop is not None:
                    pop.extract()
                rot = _txt(cel)
                horas = _ch(_txt(tds[-1]))
                if rot:
                    cargas.append(CargaHorariaItem(rotulo=rot, horas=horas, grupo=grupo))

    def soma(*trechos: str) -> int | None:
        achou = [c.horas or 0 for c in cargas if all(_norm(t) in _norm(c.rotulo) for t in trechos) and not _norm(c.rotulo).startswith("subtotal")]
        return sum(achou) if achou else None

    def ch_item(*trechos: str) -> int | None:
        for c in cargas:
            if all(_norm(t) in _norm(c.rotulo) for t in trechos):
                return c.horas
        return None

    teorica = soma("aula teorica") if cargas else _ch(v("Carga Horária Teórica"))
    pratica = soma("aula pratica") if cargas else _ch(v("Carga Horária Prática"))
    total = ch_item("total de carga horaria do componente") if cargas else _ch(v("Carga Horária Total"))
    total_aula = ch_item("total de carga horaria de aula") if cargas else None
    ead = ch_item("subtotal", "a distancia") if cargas else _ch(v("Carga Horária de Ead"))
    if not cargas:
        for rot in ("Carga Horária Teórica", "Carga Horária Prática", "Carga Horária de Ead", "Carga Horária Total"):
            h = _ch(v(rot))
            if h is not None:
                cargas.append(CargaHorariaItem(rotulo=rot, horas=h))

    hist = []
    th_ = _tabela_por_caption(sp, "Histórico de Equivalências")
    if th_ is not None:
        for tr in th_.select("tbody tr") or th_.find_all("tr")[1:]:
            tds = tr.find_all("td", recursive=False)
            if len(tds) >= 2:
                hist.append(
                    EquivalenciaHistorico(
                        expressao=_txt(tds[0]),
                        ativa=_bool(_txt(tds[1])),
                        inicio_vigencia=_data(_txt(tds[2])) if len(tds) > 2 else None,
                        fim_vigencia=_data(_txt(tds[3])) if len(tds) > 3 else None,
                    )
                )

    curriculos = []
    tc = sp.find("table", id=re.compile("listaCurriculosComponente")) or _tabela_por_caption(sp, "Currículos")
    if tc is not None:
        cab = [_norm(th.get_text()) for th in tc.select("thead th")]
        for tr in tc.select("tbody tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2:
                continue
            col = {cab[i] if i < len(cab) else str(i): _txt(tds[i]) for i in range(len(tds))}

            def cc(p: str) -> str | None:
                return next((x for k, x in col.items() if k.startswith(p)), None)

            curriculos.append(
                CurriculoDoComponente(
                    codigo=cc("codigo") or _txt(tds[0]),
                    periodo_implementacao=_valor(cc("ano.periodo")),
                    matriz_curricular=_valor(cc("matriz")),
                    obrigatoria=_bool(cc("obrigatoria")),
                    semestre=_int(cc("periodo")),
                    ativo=_bool(cc("ativo")),
                )
            )

    return ComponenteCurricular(
        id=componente_id,
        codigo=v("Código"),
        nome=v("Nome"),
        tipo=v("Tipo do Componente"),
        modalidade=v("Modalidade de Educação", "Modalidade"),
        unidade_responsavel=v("Unidade Responsável"),
        pre_requisitos=pre,
        co_requisitos=co,
        equivalencias=eq,
        pre_requisitos_codigos=_codigos(pre),
        co_requisitos_codigos=_codigos(co),
        equivalencias_codigos=_codigos(eq),
        ementa=v("Ementa/Descrição", "Ementa"),
        carga_horaria_total=total,
        carga_horaria_aula=total_aula,
        carga_horaria_teorica=teorica,
        carga_horaria_pratica=pratica,
        carga_horaria_extensionista=soma("aula extensionista") if cargas else None,
        carga_horaria_ead=ead,
        cargas_horarias=cargas,
        quantidade_avaliacoes=_int(v("Quantidade de Avaliações")),
        matriculavel_online=_bool(v("Matriculável On-Line")),
        necessita_orientador=_bool(v("Necessita de Orientador")),
        possui_subturmas=_bool(v("Possui Subturmas")),
        exige_horario=_bool(v("Exige Horário")),
        permite_multiplas_aprovacoes=_bool(v("Permite Múltiplas Aprovações")),
        atributos=atributos,
        equivalente_de=_refs(_tabela_por_caption(sp, "como equivalente")),
        requisito_de=_refs(_tabela_por_caption(sp, "como pré-requisito", "como pre-requisito")),
        historico_equivalencias=hist,
        curriculos=curriculos,
    )


def sem_programa(html: str | bytes) -> bool:
    return "nao possui um programa cadastrado" in _norm(_soup(html).get_text(" "))


_SECOES_PROGRAMA = {
    "ementa": "ementa",
    "objetivos": "objetivos",
    "conteudo": "conteudo",
    "metodologia": "metodologia",
    "procedimentos de avaliacao": "avaliacao",
    "avaliacao": "avaliacao",
    "competencias": "competencias_habilidades",
    "referencias": "referencias",
    "bibliografia": "referencias",
}


def parse_programa_componente(html: str | bytes, componente_id: int | None = None) -> ProgramaComponente | None:
    """Programa atual do componente. ``None`` quando o SIGAA diz que não há programa cadastrado.
    Lê pares rótulo→texto (th/td, dt/dd ou caption de tabela) e mapeia as seções conhecidas."""
    sp = _soup(html)
    if sem_programa(sp):
        return None
    secoes: dict[str, str] = {}
    for rot, td in _pares(sp).items():
        val = _limpa(td.get_text("\n"))
        if val:
            secoes.setdefault(rot, val)
    for rot, dd in _dl(sp).items():
        secoes.setdefault(rot, _limpa(dd.get_text("\n")))
    for t in sp.find_all("table"):
        cap = t.find("caption", recursive=False)
        if cap is not None:
            corpo = _limpa(t.get_text("\n").replace(cap.get_text(), "", 1))
            if corpo:
                secoes.setdefault(_norm(cap.get_text()), corpo)
    campos: dict[str, str | None] = {}
    for rot, val in secoes.items():
        for chave, campo in _SECOES_PROGRAMA.items():
            if rot.startswith(chave) and campo not in campos:
                campos[campo] = _valor(val)
    if not any(campos.values()):
        return None
    cod = _valor(secoes.get("codigo"))
    nome = _valor(secoes.get("nome"))
    comp = secoes.get("componente curricular")
    if comp and not cod:
        cod, nome, _ = _codigo_nome(comp)
    periodo = secoes.get("ano-periodo") or secoes.get("ano/periodo") or secoes.get("periodo")
    return ProgramaComponente(
        id_componente=componente_id,
        codigo=cod,
        nome=nome,
        periodo=_valor(periodo),
        secoes={k: v for k, v in secoes.items() if v},
        **campos,
    )


# ------------------------------------------------------------------------------ turmas
_RE_DOC_CH = re.compile(r"\s*([^,(]+?)\s*\((\d+)\s*h\)")


def parse_turmas_publicas(html: str | bytes) -> list[TurmaPublica]:
    """public/turmas/listar.jsf — linhas 'agrupador' (componente) seguidas das turmas."""
    sp = _soup(html)
    raiz = sp.find(id="turmasAbertas") or sp
    out: list[TurmaPublica] = []
    for tabela in raiz.find_all("table", class_="listagem"):
        cab = [_norm(th.get_text()) for th in tabela.select("thead th")]
        cod = nome = None
        cid = None
        for tr in tabela.select("tbody tr") or tabela.find_all("tr"):
            if "agrupador" in (tr.get("class") or []):
                titulo = tr.find(class_="tituloDisciplina") or tr
                cod, nome, _ = _codigo_nome(_txt(titulo))
                a = next((x for x in tr.find_all("a", onclick=True) if "id" in _jsf(x)), None)
                cid = _int(_jsf(a).get("id")) if a else None
                continue
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2 or cod is None:
                continue
            col = {}
            for i, td in enumerate(tds):
                col[cab[i] if i < len(cab) else str(i)] = td
            turma_td = tr.find("td", class_="turma") or col.get("codigo")
            per_td = tr.find("td", class_="anoPeriodo") or col.get("ano-periodo")
            doc_td = tr.find("td", class_="nome") or col.get("docente")
            loc_td = col.get("local") or (tds[-1] if len(tds) >= 4 else None)
            doc_txt = _txt(doc_td)
            docentes = [DocenteTurma(nome=m.group(1).strip(), carga_horaria=int(m.group(2))) for m in _RE_DOC_CH.finditer(doc_txt)]
            if not docentes and _valor(doc_txt):
                docentes = [DocenteTurma(nome=n.strip()) for n in doc_txt.split(",") if n.strip()]
            loc_txt = _txt(loc_td)
            local, locais = separar_locais(loc_txt)
            ant = out[-1] if out else None
            if (
                ant is not None
                and ant.codigo_componente == cod
                and ant.turma == _valor(_txt(turma_td))
                and ant.periodo == _valor(_txt(per_td))
                and ant.local_texto == _valor(loc_txt)
            ):
                # o SIGAA repete a linha da turma para cada docente: junta numa só
                ant.docentes.extend(d for d in docentes if d not in ant.docentes)
                ant.docentes_texto = ", ".join(x for x in (ant.docentes_texto, _valor(doc_txt)) if x) or None
                continue
            out.append(
                TurmaPublica(
                    componente_id=cid,
                    codigo_componente=cod,
                    nome_componente=nome,
                    turma=_valor(_txt(turma_td)),
                    periodo=_valor(_txt(per_td)),
                    docentes=docentes,
                    docentes_texto=_valor(doc_txt),
                    local=local,
                    locais=locais,
                    local_texto=_valor(loc_txt),
                )
            )
    return out


def parse_unidades_turmas(html: str | bytes) -> list[UnidadeAcademica]:
    """Opções do select 'Unidade' (formTurma:inputDepto) da consulta pública de turmas."""
    return [UnidadeAcademica(id=int(o.valor), nome=o.rotulo) for o in parse_opcoes(html, "formTurma:inputDepto") if o.valor.isdigit()]


# ----------------------------------------------------------------------------- docentes
def parse_busca_docentes(html: str | bytes) -> list[DocenteResumo]:
    """public/docente/busca_docentes.jsf (resultado): span.nome, span.departamento, link siape."""
    sp = _soup(html)
    out: list[DocenteResumo] = []
    for t in sp.find_all("table", class_="listagem"):
        cap = t.find("caption")
        if cap is None or "docente" not in _norm(cap.get_text()):
            continue
        for tr in t.find_all("tr"):
            nome_el = tr.find(class_="nome")
            if nome_el is None:
                continue
            a = tr.find("a", href=re.compile("siape"))
            img = tr.find("img")
            out.append(
                DocenteResumo(
                    siape=_qs_int(a.get("href"), "siape") if a else None,
                    nome=_txt(nome_el),
                    unidade=_valor(_txt(tr.find(class_="departamento"))),
                    foto_url=img.get("src") if img else None,
                )
            )
    return out


def parse_docentes_departamento(html: str | bytes) -> list[DocenteResumo]:
    """public/departamento/professores.jsf?id=N — grupos (h2: 'Ativo Permanente'...) com tabelas por docente."""
    sp = _soup(html)
    raiz = sp.find(id="professores") or sp.find(id="colDirCorpo") or sp
    out: list[DocenteResumo] = []
    categoria = None
    for el in raiz.find_all(["h2", "table"]):
        if el.name == "h2":
            categoria = _txt(el) or categoria
            continue
        nome_el = el.find(class_="nome")
        if nome_el is None:
            continue
        bruto = _txt(nome_el)
        m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", bruto)
        nome, tit = (m.group(1).strip(), m.group(2).strip()) if m else (bruto, None)
        pag = el.find("a", href=re.compile("siape"))
        lat = el.find("a", href=re.compile("lattes"))
        img = el.find("img")
        out.append(
            DocenteResumo(
                siape=_qs_int(pag.get("href"), "siape") if pag else None,
                nome=nome,
                titulacao=tit,
                categoria=categoria,
                formacao_resumo=_valor(_txt(el.find(class_="departamento"))),
                lattes=lat.get("href") if lat else None,
                foto_url=img.get("src") if img else None,
            )
        )
    return out


def parse_docente(html: str | bytes, siape: int) -> Docente:
    """public/docente/portal.jsf?siape=N — perfil pessoal + contatos."""
    sp = _soup(html)
    esq = sp.find(id="left") or sp
    h3s = [h for h in esq.find_all("h3") if not h.get("class")]
    nome = _txt(h3s[0]) if h3s else None
    unidade = _valor(_txt(esq.find("h3", class_="departamento")))
    perfil = sp.find(id="perfil-docente") or sp
    d = _dl(perfil)

    def dd(*r: str) -> Tag | None:
        return _pega(d, *r)

    lat = dd("Currículo Lattes")
    lat_a = lat.find("a", href=True) if lat else None
    form = sp.find(id="formacao-academica")
    formacoes = []
    if form is not None and not form.find(class_="vazio"):
        linhas = form.find_all("tr") or form.find_all("li")
        for ln in linhas:
            tds = ln.find_all("td")
            if tds:
                vals = [_txt(t) for t in tds if _txt(t)]
                if vals:
                    formacoes.append(FormacaoAcademica(titulo=vals[0], instituicao=vals[1] if len(vals) > 1 else None, periodo=vals[2] if len(vals) > 2 else None))
            elif _txt(ln):
                formacoes.append(FormacaoAcademica(titulo=_txt(ln)))
        if not formacoes:
            for rot, val in _dl(form).items():
                formacoes.append(FormacaoAcademica(titulo=_limpa(val.get_text(" ")), periodo=rot or None))
    contato = _dl(sp.find(id="contato"))
    end = _pega(contato, "Endereço profissional")
    foto = esq.select_one(".foto_professor img")
    return Docente(
        siape=siape,
        nome=nome,
        unidade=unidade,
        descricao_pessoal=_valor(_txt(dd("Descrição pessoal"))),
        formacao=_multilinha(dd("Formação acadêmica/profissional", "Formação")),
        areas_interesse=[x for x in _linhas(dd("Áreas de Interesse")) if _valor(x)],
        lattes=(lat_a["href"].strip() if lat_a else _valor(_txt(lat))),
        formacao_academica=formacoes,
        endereco_profissional=_multilinha(end),
        sala=_valor(_txt(_pega(contato, "Sala"))),
        telefone=_valor(_txt(_pega(contato, "Telefone"))),
        email=_valor(_txt(_pega(contato, "Endereço eletrônico", "E-mail"))),
        foto_url=foto.get("src") if foto else None,
    )


def docente_existe(html: str | bytes) -> bool:
    sp = _soup(html)
    return sp.find(id="perfil-docente") is not None or sp.find(id="id-docente") is not None


def parse_producao_docente(html: str | bytes) -> list[ProducaoCategoria]:
    """public/docente/producao.jsf?siape=N — <h2>Categoria (n)</h2><ul><li>...</li></ul>."""
    sp = _soup(html)
    raiz = sp.find(id="producao-docente") or sp.find(id="center") or sp
    out: list[ProducaoCategoria] = []
    for h2 in raiz.find_all("h2"):
        cat = _txt(h2)
        m = re.match(r"(.+?)\s*\((\d+)\)\s*$", cat)
        nome, qtd = (m.group(1).strip(), int(m.group(2))) if m else (cat, None)
        ul = h2.find_next_sibling(["ul", "ol", "table"])
        itens = []
        if ul is not None:
            for li in ul.find_all(["li", "tr"]):
                t = _txt(li)
                if not t:
                    continue
                datas = re.findall(r"\b(\d{2}/\d{4})\b", t)
                sit = re.search(r"(Orienta[cç][aã]o em Andamento|Conclu[ií]da em\s*(\d{2}/\d{4})?)", t, re.I)
                titulo = t.split(",")[0].strip() or None
                itens.append(
                    ProducaoItem(
                        texto=t,
                        titulo=titulo,
                        data=datas[-1] if datas else None,
                        situacao=_limpa(sit.group(1)) if sit else None,
                    )
                )
        out.append(ProducaoCategoria(categoria=nome, quantidade=qtd, itens=itens))
    return out


def parse_disciplinas_docente(html: str | bytes) -> list[DisciplinaMinistrada]:
    """public/docente/disciplinas.jsf?siape=N — abas por nível; linhas td.anoPeriodo separam os períodos."""
    sp = _soup(html)
    raiz = sp.find(id="disciplinas-docente") or sp
    out: list[DisciplinaMinistrada] = []
    for tabela in raiz.find_all("table"):
        periodo = None
        for tr in tabela.find_all("tr"):
            ap = tr.find("td", class_="anoPeriodo")
            if ap is not None:
                periodo = _txt(ap) or periodo
                continue
            cod = tr.find("td", class_="codigo")
            if cod is None or periodo is None:
                continue
            tds = tr.find_all("td", recursive=False)
            nome_td = cod.find_next_sibling("td")
            hor = tr.find("td", class_="horario")
            out.append(
                DisciplinaMinistrada(
                    periodo=periodo,
                    codigo=_txt(cod),
                    nome=_txt(nome_td),
                    carga_horaria=_ch(_txt(tr.find("td", class_="ch"))) if tr.find("td", class_="ch") else (_ch(_txt(tds[2])) if len(tds) > 2 else None),
                    horario=decodificar(_txt(hor)) if hor is not None and _txt(hor) else None,
                )
            )
    return out


# ---------------------------------------------------------------- centros e departamentos
def parse_lista_centros(html: str | bytes) -> list[CentroResumo]:
    """public/centro/lista.jsf — uma tabela por centro: caption (nome - SIGLA + link portal) + departamentos."""
    sp = _soup(html)
    out: list[CentroResumo] = []
    for t in sp.find_all("table", class_="listagem"):
        cap = t.find("caption")
        if cap is None:
            continue
        a_portal = cap.find("a", href=re.compile(r"portal\.jsf\?.*id="))
        a_nome = cap.find("a", class_="nomeCentro") or cap
        if a_portal is None:
            continue
        bruto = _txt(a_nome)
        nome, _, sigla = bruto.rpartition(" - ")
        if not nome:
            nome, sigla = bruto, ""
        mun = None
        sub = t.find("td", class_="subListagem")
        if sub is not None:
            m = re.search(r"MUNIC[IÍ]PIO DE\s+(.+?),", _txt(sub), re.I)
            mun = m.group(1).strip() if m else None
        deps = []
        for a in t.select("tbody a.nomeDepartamento"):
            did = _qs_int(a.get("href"), "id")
            nm = _txt(a)
            if did and nm and all(d.id != did for d in deps):
                deps.append(UnidadeRef(id=did, nome=nm))
        out.append(CentroResumo(id=_qs_int(a_portal["href"], "id") or 0, nome=nome.strip(), sigla=sigla.strip() or None, municipio=mun, departamentos=deps))
    return out


def _cabeca_unidade(sp: BeautifulSoup) -> tuple[str | None, str | None, int | None]:
    top = sp.find(id="colDirTop")
    if top is None:
        return None, None, None
    h1, h2 = top.find("h1"), top.find("h2")
    a = top.find("a", href=re.compile(r"centro/portal\.jsf"))
    return (_txt(h1) or None), (_txt(h2) or None), (_qs_int(a["href"], "id") if a else None)


def parse_centro(html: str | bytes, centro_id: int) -> Centro:
    """public/centro/portal.jsf?id=N (apresentação + diretoria + telefones)."""
    sp = _soup(html)
    sigla, nome, _ = _cabeca_unidade(sp)
    corpo = sp.find(id="colDirCorpo") or sp
    vazio = corpo.find("p", class_="vazio")
    apres = None
    tit = corpo.find(id="titulo")
    if tit is not None and vazio is None:
        prox = tit.find_next_sibling(["p", "div"])
        apres = _valor(_txt(prox)) if prox is not None and prox.name != "dl" else None
    return Centro(
        id=centro_id,
        nome=nome,
        sigla=sigla,
        apresentacao=apres,
        diretoria=_pessoas_links(_dl_todos(corpo, "Diretoria")),
        telefones=[x for x in _linhas(_pega(_dl(corpo), "Telefone")) if _valor(x)],
        endereco_alternativo=_valor(_txt(_pega(_dl(corpo), "Endereço Alternativo"))),
    )


def parse_centro_departamentos(html: str | bytes) -> list[UnidadeRef]:
    sp = _soup(html)
    corpo = sp.find(id="colDirCorpo") or sp
    out: list[UnidadeRef] = []
    for a in corpo.find_all("a", href=re.compile(r"departamento/portal\.jsf")):
        did, nm = _qs_int(a["href"], "id"), _txt(a)
        if did and nm and all(x.id != did for x in out):
            out.append(UnidadeRef(id=did, nome=nm))
    if not out:
        # alguns layouts trazem o nome numa célula e o link só no ícone
        for tr in corpo.find_all("tr"):
            a = tr.find("a", href=re.compile(r"departamento/portal\.jsf"))
            td = tr.find("td")
            if a and td and _txt(td):
                out.append(UnidadeRef(id=_qs_int(a["href"], "id") or 0, nome=_txt(td)))
    return out


def parse_centro_cursos(html: str | bytes) -> list[CursoDoCentro]:
    sp = _soup(html)
    corpo = sp.find(id="colDirCorpo") or sp
    t = corpo.find("table", class_="listagem")
    if t is None:
        return []
    cab = [_norm(th.get_text()) for th in t.select("thead th")]
    out = []
    for tr in t.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        col = {cab[i] if i < len(cab) else str(i): tds[i] for i in range(len(tds))}
        a = tr.find("a", href=re.compile(r"curso/portal\.jsf"))
        out.append(
            CursoDoCentro(
                id=_qs_int(a["href"], "id") if a else None,
                nome=_txt(col.get("nome do curso", tds[0])),
                municipio=_valor(_txt(col.get("municipio"))),
                modalidade=_valor(_txt(col.get("modalidade"))),
                coordenador=_valor(_txt(col.get("coordenador"))),
            )
        )
    return out


def parse_centro_programas(html: str | bytes) -> list[UnidadeRef]:
    sp = _soup(html)
    corpo = sp.find(id="colDirCorpo") or sp
    out: list[UnidadeRef] = []
    for a in corpo.find_all("a", href=re.compile(r"programa/portal\.jsf")):
        pid, nm = _qs_int(a["href"], "id"), _txt(a)
        if pid and nm and all(x.id != pid for x in out):
            out.append(UnidadeRef(id=pid, nome=nm))
    return out


def parse_lista_departamentos(html: str | bytes) -> list[DepartamentoResumo]:
    """Resultado de public/departamento/lista.jsf (Buscar) — sub-cabeçalho = centro."""
    sp = _soup(html)
    out: list[DepartamentoResumo] = []
    for t in sp.find_all("table", class_="listagem"):
        centro = None
        for tr in t.find_all("tr"):
            sub = tr.find("td", class_="subListagem")
            if sub is not None:
                centro = _txt(sub) or None
                continue
            a = tr.find("a", href=re.compile(r"portal\.jsf\?.*id="))
            if a is None:
                continue
            did = _qs_int(a["href"], "id")
            nm = _txt(a) or _txt(tr.find("td"))
            if did and nm and all(x.id != did for x in out):
                out.append(DepartamentoResumo(id=did, nome=nm, centro=centro))
    return out


def parse_departamento(html: str | bytes, departamento_id: int) -> Departamento:
    """public/departamento/portal.jsf?id=N."""
    sp = _soup(html)
    sigla, nome, centro_id = _cabeca_unidade(sp)
    corpo = sp.find(id="colDirCorpo") or sp
    noticias = []
    tn = corpo.find(id="noticiasDestaque")
    if tn is not None:
        for td in tn.find_all("td"):
            if "vazio" in (td.get("class") or []):
                continue
            t = _txt(td)
            if t:
                noticias.append(t)
    apres = None
    tit = corpo.find(id="titulo")
    if tit is not None:
        prox = tit.find_next_sibling(["p", "div"])
        if prox is not None and "vazio" not in (prox.get("class") or []):
            apres = _valor(_txt(prox))
    d = _dl(corpo)
    return Departamento(
        id=departamento_id,
        sigla=sigla,
        nome=nome,
        centro_id=centro_id,
        apresentacao=apres,
        chefia=_pessoas_links(_dl_todos(corpo, "Chefia")),
        telefones=[x for x in _linhas(_pega(d, "Telefone")) if _valor(x)],
        endereco_alternativo=_valor(_txt(_pega(d, "Endereço Alternativo"))),
        noticias=noticias,
    )


def unidade_existe(html: str | bytes) -> bool:
    """Portal de centro/departamento válido tem o cabeçalho #colDirTop com nome. Id inexistente: o centro vem com o
    template vazio (h1 '()', h2 vazio) e o departamento pode cair na home pública."""
    sp = _soup(html)
    top = sp.find(id="colDirTop")
    if top is None:
        return False
    return any(re.search(r"[A-Za-zÀ-ÿ]{2,}", _txt(h)) for h in top.find_all(["h1", "h2"]))


# ------------------------------------------------------------------------- responsáveis
TIPOS_RESPONSAVEL = {
    "chefes": "1",
    "coordenadores_graduacao": "2",
    "coordenadores_pos": "3",
    "diretores": "4",
}


def parse_responsaveis(html: str | bytes, tipo: str) -> list[Responsavel]:
    """public/academico/busca_responsavel.jsf (resultado)."""
    sp = _soup(html)
    t = None
    for tab in sp.find_all("table", class_="listagem"):
        cap = tab.find("caption")
        if cap is not None and "resultado" in _norm(cap.get_text()):
            t = tab
            break
    if t is None:
        return []
    cab = [_norm(th.get_text()) for th in t.find_all("th")]
    out: list[Responsavel] = []
    centro = None
    for tr in t.find_all("tr"):
        sub = tr.find("td", class_="subListagem")
        if sub is not None:
            centro = _txt(sub) or None
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        col = {cab[i] if i < len(cab) else str(i): _txt(tds[i]) for i in range(len(tds))}
        unidade = _txt(tds[0])
        out.append(
            Responsavel(
                tipo=tipo,
                centro=centro,
                unidade=unidade,
                nome=col.get("nome") or _txt(tds[1]),
                cargo=_valor(col.get("cargo")),
                telefone=_valor(col.get("telefone")),
                email=_valor(col.get("e-mail")),
            )
        )
    return out


# ====================================================================================================
# BIBLIOTECA, PROCESSOS SELETIVOS, DIPLOMAS, MOBILIDADE E PROGRAMAS DE PÓS  (frente 'extras1')
# ====================================================================================================
# ------------------------------------------------------------------ helpers
def _ex1_soup(html) -> BeautifulSoup:
    if isinstance(html, bytes):
        try:
            html = html.decode("utf-8")
        except UnicodeDecodeError:
            html = html.decode("iso-8859-1")
    return BeautifulSoup(html, "lxml")


def _ex1_txt(el) -> str | None:
    if el is None:
        return None
    t = re.sub(r"\s+", " ", el.get_text(" ", strip=True) if hasattr(el, "get_text") else str(el)).strip()
    return t or None


def _ex1_clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _ex1_mojibake(s: str | None) -> str | None:
    """Conserta texto UTF-8 lido como latin-1 ('ApresentaÃ§Ã£o' -> 'Apresentação')."""
    if s and re.search(r"Ã.|Â.", s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def _ex1_bloco_texto(el) -> str | None:
    """Texto de um bloco HTML rico: quebra linha só em <br> e em elementos de bloco."""
    if el is None:
        return None
    for br in el.find_all("br"):
        br.replace_with("\n")
    for b in el.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]):
        b.append("\n")
    linhas = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in el.get_text("").split("\n")]
    return "\n".join(ln for ln in linhas if ln) or None


def _ex1_int(s) -> int | None:
    if s is None:
        return None
    m = re.search(r"\d+", str(s).replace(".", ""))
    return int(m.group()) if m else None


def _ex1_date(s) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _ex1_dates(s) -> list[date]:
    out = []
    for d, mth, y in re.findall(r"(\d{2})/(\d{2})/(\d{4})", s or ""):
        try:
            out.append(date(int(y), int(mth), int(d)))
        except ValueError:
            pass
    return out


def _ex1_datetimes(s) -> list[datetime]:
    """Todas as datas (com hora opcional, 'dd/mm/aaaa às HH:MM' ou 'dd/mm/aaaa HH:MM')."""
    out = []
    for d, mth, y, hh, mm in re.findall(r"(\d{2})/(\d{2})/(\d{4})(?:\s*(?:às|as|-)?\s*(\d{1,2}):(\d{2}))?", s or ""):
        try:
            out.append(datetime(int(y), int(mth), int(d), int(hh or 0), int(mm or 0)))
        except ValueError:
            pass
    return out


def _ex1_jsf_param(onclick: str | None, nome: str) -> str | None:
    m = re.search(r"'" + re.escape(nome) + r"'\s*:\s*'?([^',}]*)'?", onclick or "")
    return m.group(1) if m else None


def _ex1_qs(href: str | None, nome: str) -> str | None:
    if not href:
        return None
    v = parse_qs(urlparse(href).query).get(nome)
    return v[0] if v else None


def _ex1_header_map(ths) -> dict[str, int]:
    """Mapa 'rótulo normalizado' -> índice da coluna."""
    out = {}
    for i, th in enumerate(ths):
        k = (_ex1_txt(th) or "").lower()
        if k:
            out[k] = i
    return out


def _ex1_col(cols: dict[str, int], *chaves: str) -> int | None:
    for ch in chaves:
        for k, i in cols.items():
            if ch in k:
                return i
    return None


def _ex1_visualizacao(table) -> dict[str, object]:
    """th 'Rótulo:' -> td (tabela class=visualizacao)."""
    out = {}
    for tr in table.find_all("tr"):
        th = tr.find("th", recursive=False)
        td = tr.find("td", recursive=False)
        if th is not None and td is not None:
            k = (_ex1_txt(th) or "").rstrip(":").strip().lower()
            if k and k not in out:
                out[k] = td
    return out


def mensagem_erro_publico(html) -> str | None:
    """Texto do #painel-erros (validação do formulário), se houver."""
    painel = _ex1_soup(html).select_one("#painel-erros")
    if painel is None:
        return None
    t = _ex1_txt(painel) or ""
    return _ex1_clean(t.replace("(x) fechar mensagens", "")) or None


# ------------------------------------------------------------------ biblioteca
def parse_acervo_resultado(html) -> list[AcervoTitulo]:
    """Resultado da busca pública do acervo (buscaPublicaAcervo.jsf, tabela #listagem)."""
    soup = _ex1_soup(html)
    table = soup.find("table", id="listagem") or next(
        (t for t in soup.select("table.listagem") if "Títulos Encontrados" in (_ex1_txt(t.caption) or "")), None
    )
    if table is None:
        return []
    thead = table.find("thead")
    cols = _ex1_header_map(thead.find_all("th")) if thead else {}
    i_aut, i_tit = _ex1_col(cols, "autor"), _ex1_col(cols, "título", "titulo")
    i_ed, i_ano, i_qtd = _ex1_col(cols, "edição", "edicao"), _ex1_col(cols, "ano"), _ex1_col(cols, "qtd", "quant")
    out = []
    for tr in table.find_all("tr", recursive=False) + (table.tbody.find_all("tr", recursive=False) if table.tbody else []):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        link = tr.find("a", onclick=re.compile("idTitulo"))
        cell = lambda i: _ex1_txt(tds[i]) if i is not None and i < len(tds) else None  # noqa: E731
        titulo = cell(i_tit)
        if not titulo:
            continue
        out.append(
            AcervoTitulo(
                id=_ex1_int(_ex1_jsf_param(link["onclick"], "idTitulo")) if link else None,
                autor=cell(i_aut),
                titulo=titulo.rstrip(" /").strip(),
                edicao=(cell(i_ed) or "").rstrip(" -").strip() or None,
                ano=(cell(i_ano) or "").rstrip(".").strip() or None,
                quantidade=_ex1_int(cell(i_qtd)),
            )
        )
    return out


def parse_acervo_total(html) -> int:
    """Total de títulos da busca ('Títulos Encontrados ( 1 a 25 de 47 )'); 0 se nada."""
    soup = _ex1_soup(html)
    cap = soup.find("caption", string=re.compile("Títulos Encontrados"))
    if cap is None:
        return 0
    nums = re.findall(r"\d+", cap.get_text())
    return int(nums[-1]) if nums else 0


def parse_acervo_detalhe(html) -> AcervoTituloDetalhe:
    """Tela 'Materiais de um Título' (paginaDetalhesMateriaisPublica.jsf)."""
    soup = _ex1_soup(html)
    dados = next((t for t in soup.select("table.visualizacao") if "Dados do Título" in (_ex1_txt(t.caption) or "")), None)
    campos = _ex1_visualizacao(dados) if dados is not None else {}

    def val(*ks):
        for k in ks:
            if k in campos:
                return _ex1_txt(campos[k])
        return None

    def lista(*ks):
        for k in ks:
            if k in campos:
                tds = campos[k].find_all("td")
                vals = [_ex1_txt(td) for td in tds] if tds else [_ex1_txt(campos[k])]
                return [v.rstrip(".").strip() for v in vals if v]
        return []

    id_input = soup.find("input", id=re.compile("idTituloVisaulizandoMateriais|idTitulo"))
    exemplares: list[AcervoExemplar] = []
    total = None
    sub = next((t for t in soup.select("table.subFormulario") if "Exemplar" in (_ex1_txt(t.caption) or "")), None)
    if sub is not None:
        nums = re.findall(r"\d+", _ex1_txt(sub.caption) or "")
        total = int(nums[-1]) if nums else None
        thead = sub.find("thead")
        cols = _ex1_header_map(thead.find_all("th")) if thead else {}
        i_loc, i_tipo = _ex1_col(cols, "localiza"), _ex1_col(cols, "tipo")
        i_col, i_st, i_sit = _ex1_col(cols, "coleç", "colec"), _ex1_col(cols, "status"), _ex1_col(cols, "situa")
        biblioteca = None
        ultimo: AcervoExemplar | None = None
        for tr in (sub.tbody or sub).find_all("tr", recursive=False):
            if "biblioteca" in (tr.get("class") or []):
                biblioteca = _ex1_txt(tr)
                continue
            det = tr.find("a", onclick=re.compile("idMaterialMostrarDetalhes"))
            if det is not None:
                if ultimo is not None:
                    m = re.search(r"idMaterialMostrarDetalhes'?\s*:\s*'?(\d+)", det["onclick"])
                    ultimo.id_material = int(m.group(1)) if m else None
                continue
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue
            cell = lambda i: _ex1_txt(tds[i]) if i is not None and i < len(tds) else None  # noqa: E731
            ultimo = AcervoExemplar(
                biblioteca=biblioteca,
                localizacao=cell(i_loc),
                tipo_material=cell(i_tipo),
                colecao=cell(i_col),
                status=cell(i_st),
                situacao=cell(i_sit),
            )
            exemplares.append(ultimo)
    titulo = val("título", "titulo")
    return AcervoTituloDetalhe(
        id=_ex1_int(id_input.get("value")) if id_input else None,
        registro_sistema=_ex1_int(val("registro no sistema")),
        numero_chamada=val("número de chamada", "numero de chamada"),
        autor=val("autor"),
        titulo=titulo.rstrip(" /").strip() if titulo else None,
        local_publicacao=(val("local da publicação") or "").rstrip(" :").strip() or None,
        editora=(val("editora") or "").rstrip(" ,").strip() or None,
        ano_publicacao=(val("ano publicação", "ano de publicação") or "").rstrip(".").strip() or None,
        edicao=(val("edição", "edicao") or "").rstrip(" -").strip() or None,
        assuntos=lista("assunto"),
        notas=lista("notas gerais", "notas"),
        total_exemplares=total if total is not None else (len(exemplares) if sub is not None else None),
        exemplares=exemplares,
    )


def parse_artigos_resultado(html) -> list[AcervoArtigo]:
    """Resultado da busca de artigos (buscaPublicaAcervoArtigos.jsf). Tolerante: lê pelos rótulos do thead."""
    soup = _ex1_soup(html)
    table = next((t for t in soup.select("table.listagem") if t.find("thead")), None)
    if table is None:
        return []
    cols = _ex1_header_map(table.find("thead").find_all("th"))
    i_tit, i_aut = _ex1_col(cols, "título", "titulo"), _ex1_col(cols, "autor")
    i_pub, i_ano = _ex1_col(cols, "periódico", "periodico", "publica", "fonte"), _ex1_col(cols, "ano")
    out = []
    for tr in (table.tbody or table).find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        cell = lambda i: _ex1_txt(tds[i]) if i is not None and i < len(tds) else None  # noqa: E731
        titulo = cell(i_tit)
        if not titulo:
            continue
        link = tr.find("a", onclick=re.compile(r"'id\w*'\s*:"))
        ident = None
        if link is not None:
            m = re.search(r"'id(?:Artigo|Titulo)?'\s*:\s*'(\d+)'", link["onclick"])
            ident = int(m.group(1)) if m else None
        out.append(AcervoArtigo(id=ident, titulo=titulo, autor=cell(i_aut), publicacao=cell(i_pub), ano=cell(i_ano)))
    return out


def parse_aquisicoes(html) -> list[AquisicaoBiblioteca]:
    """Resultado de buscaPublicaAquisicoes.jsf (agrupado por ano > centro > departamento)."""
    soup = _ex1_soup(html)
    table = next((t for t in soup.select("table.listagem") if "Títulos Encontrados" in (_ex1_txt(t.caption) or "")), None)
    if table is None:
        return []
    ano = centro = depto = None
    out = []
    for tr in (table.tbody or table).find_all("tr", recursive=False):
        th = tr.find("th", recursive=False)
        if th is not None and not tr.find("td", recursive=False):
            cls = th.get("class") or []
            t = _ex1_txt(th) or ""
            if "ano" in cls:
                ano = _ex1_int(t)
                centro = depto = None
            elif "centro" in cls:
                centro, depto = t, None
            elif "depto" in cls:
                depto = t
            continue
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        bruto = _ex1_txt(tds[0]) or ""
        m = re.match(r"(.*?)\s*(?:-\s*Vol\.\s*([\w.]+))?\s*(?:,\s*(\d{4}))?\s*$", bruto)
        titulo, vol, anop = (m.group(1), m.group(2), m.group(3)) if m else (bruto, None, None)
        out.append(
            AquisicaoBiblioteca(
                ano_aquisicao=ano,
                centro=centro,
                departamento=depto,
                titulo=titulo.strip(" ,-") or bruto,
                volume=vol if vol not in (None, "0") else None,
                ano_publicacao=int(anop) if anop else None,
                autor=_ex1_txt(tds[1]) if len(tds) > 1 else None,
                quantidade=_ex1_int(_ex1_txt(tds[2])) if len(tds) > 2 else None,
            )
        )
    return out


def parse_novas_aquisicoes(html) -> NovasAquisicoesBiblioteca:
    """Informativo de novas aquisições (resultadoBuscaPublicaNovasAquisicoes.jsf)."""
    soup = _ex1_soup(html)
    filtros = soup.find("table", id="tabelaFiltros")
    campos = {}
    if filtros is not None:
        for tr in filtros.find_all("tr", recursive=False) + (filtros.tbody.find_all("tr", recursive=False) if filtros.tbody else []):
            th, td = tr.find("th", recursive=False), tr.find("td", recursive=False)
            if th is not None and td is not None:
                campos[(_ex1_txt(th) or "").rstrip(":").lower()] = td
    periodo = _ex1_dates(_ex1_txt(campos.get("período")) or "")
    res = soup.find("table", id="tabelaResultado")
    total, itens = 0, []
    if res is not None:
        m = re.search(r"\((\d+)\)", _ex1_txt(res.caption) or "")
        total = int(m.group(1)) if m else 0
        area = None
        for tr in (res.tbody or res).find_all("tr", recursive=False):
            if "infoaltrem" in [c.lower() for c in (tr.get("class") or [])]:
                area = _ex1_txt(tr)
                continue
            t = _ex1_txt(tr)
            if t:
                itens.append(NovaAquisicaoBiblioteca(area=area, descricao=t))
    return NovasAquisicoesBiblioteca(
        bibliotecas=_ex1_txt(campos.get("biblioteca(s)")),
        area=_ex1_txt(campos.get("área de conhecimento")),
        data_inicio=periodo[0] if periodo else None,
        data_fim=periodo[1] if len(periodo) > 1 else None,
        total=total,
        itens=itens,
    )


# ---------------------------------------------------------- processos seletivos
def parse_processos_seletivos(html) -> list[ProcessoSeletivoResumo]:
    """Lista pública processo_seletivo/lista.jsf?nivel=S|L|T|I|F (uma linha por curso)."""
    soup = _ex1_soup(html)
    table = next((t for t in soup.select("table.listagem") if "Processos Seletivos" in (_ex1_txt(t.caption) or "")), None)
    if table is None:
        return []
    edital = id_prog = None
    out = []
    for tr in (table.tbody or table).find_all("tr", recursive=False):
        agrup = tr.find("td", class_="agrupador")
        if agrup is not None:
            edital = _ex1_txt(agrup.find("a")) or _ex1_txt(agrup)
            prog = tr.find("a", href=re.compile(r"programa/portal\.jsf"))
            id_prog = _ex1_int(_ex1_qs(prog["href"], "id")) if prog else None
            continue
        ver = tr.find("a", onclick=re.compile(r"'id'\s*:"))
        tds = tr.find_all("td", recursive=False)
        if ver is None or len(tds) < 3:
            continue
        per = tr.find("td", class_="colData") or tds[2]
        datas = _ex1_dates(_ex1_txt(per))
        out.append(
            ProcessoSeletivoResumo(
                id=int(_ex1_jsf_param(ver["onclick"], "id")),
                edital=edital,
                curso=_ex1_txt(tds[0]),
                vagas=_ex1_int(_ex1_txt(tr.find("td", class_="colVagas") or tds[1])),
                inscricao_inicio=datas[0] if datas else None,
                inscricao_fim=datas[1] if len(datas) > 1 else None,
                aberto="fechado" not in (per.get("class") or []),
                id_programa=id_prog,
            )
        )
    return out


def parse_processo_seletivo(html) -> ProcessoSeletivo:
    """Detalhe 'Dados do Processo Seletivo' (processo_seletivo/view.jsf, aberto por POST)."""
    soup = _ex1_soup(html)
    vis = next((t for t in soup.select("table.visualizacao") if "Processo Seletivo" in (_ex1_txt(t.caption) or "")), None)
    if vis is None:
        vis = soup.select_one("table.visualizacao")
    campos: dict[str, object] = {}
    if vis is not None:
        for th in vis.find_all("th"):
            k = (_ex1_txt(th) or "").rstrip(":").strip().lower()
            td = th.find_next_sibling("td")
            if k and td is not None and k not in campos:
                campos[k] = td

    curso_td = campos.get("curso")
    curso = programa = None
    if curso_td is not None:
        un = curso_td.find(class_="unidade")
        programa = _ex1_txt(un)
        if un is not None:
            un.extract()
        curso = _ex1_txt(curso_td)
        if un is not None:
            curso_td.append(un)
    periodo = _ex1_datetimes(_ex1_txt(campos.get("período de inscrições")) or "")
    insc = soup.find("a", title=re.compile("Inscrever-se", re.I)) or soup.find("a", string=re.compile("inscrever-se", re.I))
    ident = _ex1_int(_ex1_jsf_param(insc["onclick"], "id")) if insc is not None and insc.get("onclick") else None

    def sub(nome):
        return next((t for t in soup.select("table.subFormulario") if nome in (_ex1_txt(t.caption) or "")), None)

    etapas = []
    t = sub("Etapas")
    if t is not None:
        for tr in t.find_all("tr", class_=re.compile("linha")):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            span = tds[0].find("span")
            dts = [(_ex1_datetimes(_ex1_txt(td) or "") or [None])[0] for td in tds[1:4]]
            dts += [None] * (3 - len(dts))
            etapas.append(
                EtapaProcessoSeletivo(
                    nome=_ex1_txt(tds[0]) or "",
                    descricao=_ex1_clean(span.get("title")) if span is not None else None,
                    divulgacao_resultado=dts[0],
                    interposicao_recurso=dts[1],
                    analise_recurso=dts[2],
                )
            )
    comissao = []
    t = sub("Comissão")
    if t is not None:
        for tr in t.find_all("tr", class_=re.compile("linha")):
            tds = tr.find_all("td", recursive=False)
            if tds and _ex1_txt(tds[0]):
                comissao.append(MembroComissaoProcessoSeletivo(nome=_ex1_txt(tds[0]), funcao=_ex1_txt(tds[1]) if len(tds) > 1 else None))
    documentos = []
    t = sub("Documentos")
    if t is not None:
        for tr in t.find_all("tr", class_=re.compile("linha")):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            a = tds[0].find("a", href=True)
            documentos.append(
                DocumentoProcessoSeletivo(
                    descricao=_ex1_txt(tds[0]) or "",
                    tipo=_ex1_txt(tds[1]) if len(tds) > 1 else None,
                    disponibilizado_em=(_ex1_datetimes(_ex1_txt(tds[2]) or "") or [None])[0] if len(tds) > 2 else None,
                    url=a["href"] if a is not None else None,
                )
            )

    def texto_apos(rotulo):
        if vis is None:
            return None
        cab = next((td for td in vis.find_all("td", class_="subFormulario") if rotulo in (_ex1_txt(td) or "")), None)
        if cab is None:
            return None
        nxt = cab.find_parent("tr").find_next_sibling("tr")
        td = nxt.find("td", class_="texto") if nxt is not None else None
        return _ex1_bloco_texto(td)

    noticias = []
    box = soup.find(id="noticias")
    if box is not None and not re.search(r"Não há notícias", box.get_text()):
        for li in box.find_all(["li", "tr"]):
            t_ = _ex1_txt(li)
            if t_:
                d = _ex1_date(t_)
                noticias.append(NoticiaProcessoSeletivo(titulo=t_, data=d.strftime("%d/%m/%Y") if d else None))
    return ProcessoSeletivo(
        id=ident,
        curso=curso,
        programa=programa,
        edital=_ex1_txt(campos.get("edital")),
        nivel=_ex1_txt(campos.get("nível")),
        inscricao_inicio=periodo[0] if periodo else None,
        inscricao_fim=periodo[1] if len(periodo) > 1 else None,
        vagas=_ex1_int(_ex1_txt(campos.get("número de vagas"))),
        questionario=_ex1_txt(campos.get("questionário específico")),
        inscricoes_abertas=insc is not None,
        etapas=etapas,
        comissao=comissao,
        documentos=documentos,
        descricao=texto_apos("Descrição e Orientações"),
        orientacoes_inscritos=texto_apos("Orientações aos Inscritos"),
        noticias=noticias,
    )


# ------------------------------------------------------- acordos de mobilidade
def parse_acordos_mobilidade(html) -> list[AcordoMobilidade]:
    """Lista de acordos de cooperação (acordos_mobilidade.jsf após 'Buscar')."""
    soup = _ex1_soup(html)
    table = next((t for t in soup.select("table.listagem") if "Acordos" in (_ex1_txt(t.caption) or "")), None)
    if table is None:
        return []
    inner = table.find("table") or table
    thead = inner.find("thead")
    cols = _ex1_header_map(thead.find_all("th")) if thead else {}
    i_pais, i_inst, i_sig = _ex1_col(cols, "país", "pais"), _ex1_col(cols, "instituição", "instituicao"), _ex1_col(cols, "sigla")
    i_st, i_fim = _ex1_col(cols, "status"), _ex1_col(cols, "vigência", "vigencia")
    corpo = inner.find("tbody") or inner
    out = []
    for tr in corpo.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        cell = lambda i: _ex1_txt(tds[i]) if i is not None and i < len(tds) else None  # noqa: E731
        link = tr.find("a", onclick=re.compile(r"'id\w*'\s*:"))
        ident = None
        if link is not None:
            m = re.search(r"'id\w*'\s*:\s*'(\d+)'", link["onclick"])
            ident = int(m.group(1)) if m else None
        out.append(
            AcordoMobilidade(
                id=ident,
                pais=cell(i_pais),
                instituicao=cell(i_inst),
                sigla=cell(i_sig),
                status=cell(i_st),
                fim_vigencia=_ex1_date(cell(i_fim)),
            )
        )
    return out


# --------------------------------------------------------- programas de pós
def _ex1_sigla(nome: str) -> str | None:
    m = re.search(r"\(([^()]+)\)\s*$", nome)
    if m:
        return m.group(1).strip()
    m = re.search(r"/\s*([A-Z0-9-]+)\s*$", nome)
    return m.group(1) if m else None


def parse_programas_pos(html) -> list[ProgramaPosResumo]:
    """Resultado de programa/lista.jsf (agrupado por centro)."""
    soup = _ex1_soup(html)
    table = next((t for t in soup.select("table.listagem") if "Programas" in (_ex1_txt(t.caption) or "")), None)
    if table is None:
        return []
    centro = None
    out, vistos = [], set()
    for tr in (table.tbody or table).find_all("tr", recursive=False):
        sub = tr.find("td", class_="subListagem")
        if sub is not None:
            centro = _ex1_txt(sub)
            continue
        a = tr.find("a", href=re.compile(r"portal\.jsf"))
        if a is None:
            continue
        ident = _ex1_int(_ex1_qs(a["href"], "id"))
        nome = _ex1_txt(a)
        if ident is None or not nome or ident in vistos:
            continue
        vistos.add(ident)
        out.append(ProgramaPosResumo(id=ident, nome=nome, sigla=_ex1_sigla(nome), centro=centro))
    return out


def parse_programa_portal(html) -> ProgramaPos:
    """Página inicial pública do programa (programa/portal.jsf?id=)."""
    soup = _ex1_soup(html)
    nomes = soup.find(id="nomes")

    def span(cls, tirar=None):
        el = nomes.find(class_=cls) if nomes is not None else None
        if el is None:
            return None
        t = _ex1_txt(el) or ""
        if tirar:
            t = re.sub(tirar, "", t, flags=re.I).strip()
        return t or None

    centro_a = nomes.find("a", href=re.compile(r"centro/portal\.jsf")) if nomes is not None else None
    nome_a = nomes.find(class_="nome_programa") if nomes is not None else None
    site_a = nomes.select_one(".url_programa a") if nomes is not None else None
    link_home = soup.find("a", href=re.compile(r"portal\.jsf\?.*id=\d+"))
    ident = _ex1_int(_ex1_qs(link_home["href"], "id")) if link_home else None

    extras: dict[str, int] = {}
    for a in soup.find_all("a", href=re.compile(r"secao_extra\.jsf")):
        k = _ex1_mojibake(_ex1_txt(a) or "").lstrip("·• ").strip()
        v = _ex1_int(_ex1_qs(a["href"], "extra"))
        if k and v is not None:
            extras.setdefault(k, v)
    noticias = []
    lst = soup.select_one("#esquerda #listagem")
    if lst is not None:
        noticias = _ex1_noticias_links(lst)
    processos = []
    form = soup.find("form", id="formProcessos")
    if form is not None:
        for a in form.find_all("a", onclick=re.compile(r"'id'\s*:")):
            datas = _ex1_dates(_ex1_txt(a))
            nivel = _ex1_txt(a.find("span", class_=lambda c: c and "data" not in c)) if a.find("span") else None
            processos.append(
                ProcessoSeletivoProgramaPos(
                    id=int(_ex1_jsf_param(a["onclick"], "id")),
                    nivel=nivel,
                    edital=None,
                    inscricao_inicio=datas[0] if datas else None,
                    inscricao_fim=datas[1] if len(datas) > 1 else None,
                )
            )
    return ProgramaPos(
        id=ident,
        nome=_ex1_txt(nome_a),
        sigla=span("sigla"),
        centro=_ex1_txt(centro_a),
        id_centro=_ex1_int(_ex1_qs(centro_a["href"], "id")) if centro_a else None,
        telefone=span("telefone_programa", r"^Telefone/Ramal:"),
        email=span("email_programa", r"^E-mail:"),
        site=site_a.get("href") if site_a is not None else None,
        secoes_extras=extras,
        noticias=noticias,
        processos_seletivos=processos,
    )


def _ex1_noticias_links(container) -> list[NoticiaProgramaPos]:
    out = []
    for a in container.find_all("a", href=re.compile(r"noticias_desc\.jsf")):
        ident = _ex1_int(_ex1_qs(a["href"], "noticia"))
        if ident is None:
            continue
        li = a.find_parent("li") or a
        dspan = li.find("span", class_="data")
        titulo = _ex1_txt(a) or ""
        if dspan is not None and dspan in a.descendants:
            titulo = titulo.replace(_ex1_txt(dspan) or "", "", 1)
        dts = _ex1_datetimes(_ex1_txt(dspan) or "")
        out.append(NoticiaProgramaPos(id=ident, titulo=titulo.strip().lstrip("- ").strip(), data=dts[0] if dts else None))
    return out


def parse_programa_apresentacao(html) -> ApresentacaoProgramaPos:
    """Página programa/apresentacao.jsf: texto, endereço alternativo e quadro de coordenação."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo")
    if c is None:
        return ApresentacaoProgramaPos()
    secoes: dict[str, object] = {}
    titulo = None
    for el in c.find_all("div", recursive=False):
        cls = el.get("class") or []
        if "titulo" in cls:
            titulo = (_ex1_txt(el) or "").lower()
        elif titulo and titulo not in secoes and ("texto" in cls or "texto_afastado" in cls):
            secoes[titulo] = el
    alt = secoes.get("endereço alternativo")
    coord = []
    box = secoes.get("coordenação do programa")
    if box is not None:
        for li in box.find_all("li"):
            a = li.find("a")
            if a is None or not _ex1_txt(a):
                continue
            tels, email = [], None
            for p_ in li.select(".dados p"):
                rot = (p_.get_text(" ", strip=True) or "").lower()
                v = _ex1_txt(p_.find(class_="cor"))
                if not v:
                    continue
                if "mail" in rot:
                    email = v
                elif "telefone" in rot:
                    tels.append(v)
            coord.append(
                CoordenadorProgramaPos(
                    nome=_ex1_txt(a), siape=_ex1_int(_ex1_qs(a.get("href"), "siape")), telefones=tels, email=email
                )
            )
    alt_a = alt.find("a", href=True) if alt is not None else None
    return ApresentacaoProgramaPos(
        texto=_ex1_bloco_texto(secoes.get("apresentação")),
        endereco_alternativo=(alt_a["href"] if alt_a else (_ex1_txt(alt) or "").lstrip("- ").strip() or None),
        coordenacao=coord,
    )


def parse_programa_areas(html) -> list[AreaConcentracaoPos]:
    """Áreas de concentração e linhas de pesquisa (programa/areas.jsf)."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo") or soup
    out: list[AreaConcentracaoPos] = []
    for bloco in c.find_all("div", id="listagem_tabela"):
        g = bloco.find(id="group_lt")
        nivel = _ex1_txt(g)
        atual: AreaConcentracaoPos | None = None
        for table in bloco.find_all("table"):
            campos = table.find("tr", class_="campos")
            if campos is not None:
                atual = AreaConcentracaoPos(nivel=nivel, nome=_ex1_txt(campos) or "")
                out.append(atual)
                continue
            for td in table.find_all("td", class_="denominacao"):
                tr = td.find_parent("tr")
                img = tr.find("img", onclick=True)
                ident = None
                desc = None
                if img is not None:
                    m = re.search(r"#trOpcoes(\d+)", img["onclick"])
                    if m:
                        ident = int(m.group(1))
                        d = table.find(id=f"trOpcoes{ident}")
                        desc = _ex1_txt(d)
                linha = LinhaPesquisaPos(id=ident, nome=(_ex1_txt(td) or "").lstrip("› ").strip(), descricao=desc)
                if atual is None:
                    atual = AreaConcentracaoPos(nivel=nivel, nome="")
                    out.append(atual)
                atual.linhas_pesquisa.append(linha)
    return out


def parse_programa_cursos(html) -> list[CursoProgramaPos]:
    """Cursos do programa (programa/cursos.jsf)."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo") or soup
    out = []
    for bloco in c.find_all("div", id="listagem_tabela"):
        g = _ex1_txt(bloco.find(id="group_lt")) or ""
        nome, _, nivel = g.rpartition(" - ")
        if not nome:
            nome, nivel = g, None
        capes = bloco.find("a", href=re.compile("capes", re.I))
        det = bloco.find("a", onclick=re.compile(r"'id'\s*:"))
        out.append(
            CursoProgramaPos(
                id=_ex1_int(_ex1_jsf_param(det["onclick"], "id")) if det else None,
                nome=nome.strip(),
                nivel=(nivel or "").strip() or None,
                nivel_codigo=_ex1_jsf_param(det["onclick"], "nivel") if det else None,
                url_capes=capes["href"] if capes else None,
            )
        )
    return out


def parse_programa_docentes(html) -> list[DocenteProgramaPos]:
    """Corpo docente (programa/equipe.jsf): um bloco por grupo (área / Pós-Doutorandos...)."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo") or soup
    out = []
    grupo = None
    for el in c.find_all(["div", "table"]):
        if el.name == "div" and el.get("id") == "listagem_tabela":
            grupo = _ex1_txt(el.find(id="group_lt"))
            continue
        if el.name != "table" or el.get("id") != "table_lt":
            continue
        head = el.find("tr", class_="campos")
        cols = _ex1_header_map(head.find_all("td")) if head else {}
        i_nome = _ex1_col(cols, "nome") or 0
        i_vin, i_niv = _ex1_col(cols, "vínculo", "vinculo"), _ex1_col(cols, "nível", "nivel")
        i_tel = _ex1_col(cols, "telefone", "ramal")
        for tr in el.find_all("tr"):
            if tr is head:
                continue
            tds = tr.find_all("td", recursive=False)
            if len(tds) <= i_nome:
                continue
            nome = _ex1_txt(tds[i_nome])
            if not nome:
                continue
            cell = lambda i: _ex1_txt(tds[i]) if i is not None and i < len(tds) else None  # noqa: E731
            portal = tr.find("a", href=re.compile(r"siape="))
            lattes = tr.find("a", href=re.compile(r"lattes", re.I))
            mail = tr.find("a", href=re.compile(r"^mailto:", re.I))
            out.append(
                DocenteProgramaPos(
                    nome=nome,
                    grupo=grupo,
                    vinculo=cell(i_vin),
                    nivel=cell(i_niv),
                    ramal=cell(i_tel),
                    siape=_ex1_int(_ex1_qs(portal["href"], "siape")) if portal else None,
                    lattes=lattes["href"] if lattes else None,
                    email=mail["href"][7:].strip() if mail else None,
                )
            )
    return out


def parse_programa_processos_seletivos(html) -> list[ProcessoSeletivoProgramaPos]:
    """Processos seletivos do programa (programa/processo_seletivo.jsf)."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo") or soup
    out = []
    nivel = None
    for el in c.find_all(["div", "table"]):
        if el.get("id") == "group_lt":
            nivel = _ex1_txt(el)
            continue
        if el.name != "table":
            continue
        for tr in el.find_all("tr"):
            a = tr.find("a", onclick=re.compile(r"'id'\s*:"))
            if a is None:
                continue
            datas = _ex1_dates(_ex1_txt(tr.find("td")))
            edital = _ex1_txt(a.find("span", class_=lambda cl: cl and "data" not in cl.split()))
            out.append(
                ProcessoSeletivoProgramaPos(
                    id=int(_ex1_jsf_param(a["onclick"], "id")),
                    nivel=nivel,
                    edital=edital,
                    inscricao_inicio=datas[0] if datas else None,
                    inscricao_fim=datas[1] if len(datas) > 1 else None,
                )
            )
    return out


def parse_programa_noticias(html) -> list[NoticiaProgramaPos]:
    """Lista completa de notícias (programa/noticias.jsf)."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo") or soup
    return _ex1_noticias_links(c)


def parse_programa_noticia(html) -> NoticiaProgramaPosDetalhe:
    """Uma notícia (programa/noticias_desc.jsf?id=&noticia=)."""
    soup = _ex1_soup(html)
    c = soup.find(id="conteudo") or soup
    t = c.find(class_="texto") or c
    h2 = t.find("h2")
    titulo = _ex1_txt(h2)
    if h2 is not None:
        h2.extract()
    texto = _ex1_bloco_texto(t) or ""
    link = soup.find("a", href=re.compile(r"noticia=\d+"))
    ident = idp = None
    if link is not None:
        ident = _ex1_int(_ex1_qs(link["href"], "noticia"))
        idp = _ex1_int(_ex1_qs(link["href"], "id"))
    return NoticiaProgramaPosDetalhe(id=ident, id_programa=idp, titulo=titulo, texto=texto)


# ====================================================================================================
# PESQUISA, EXTENSÃO E CURSOS ABERTOS  (frente 'extras2')
# ====================================================================================================
_EX2_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_EX2_PARAMS = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")


# ------------------------------------------------------------------ helpers
def _ex2_soup(html: str | bytes) -> BeautifulSoup:
    if isinstance(html, bytes):  # telas JSF vêm em ISO-8859-1; respostas a4j (XML) em UTF-8
        try:
            html = html.decode("utf-8") if html.lstrip()[:5] == b"<?xml" else html.decode("iso-8859-1")
        except UnicodeDecodeError:
            html = html.decode("iso-8859-1", errors="replace")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(html, "lxml")


def _ex2_txt(el) -> str:
    if el is None:
        return ""
    s = el if isinstance(el, str) else el.get_text(" ")
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _ex2_norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip(" :?").lower()


def _ex2_none(s: str | None) -> str | None:
    s = _ex2_txt(s) if s is not None else ""
    return s or None


def _ex2_int(s) -> int | None:
    m = re.search(r"-?\d+", (s or "").replace(".", ""))
    return int(m.group()) if m else None


def _ex2_float(s) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return float(m.group().replace(",", ".")) if m else None


def _ex2_data(s) -> date | None:
    m = _EX2_DATA.search(s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _ex2_datas(s) -> tuple[date | None, date | None]:
    ds = [d for d in (_ex2_data(x.group()) for x in _EX2_DATA.finditer(s or "")) if d]
    return (ds[0] if ds else None, ds[1] if len(ds) > 1 else None)


def _ex2_bool(s) -> bool | None:
    n = _ex2_norm(s or "")
    if n.startswith("sim"):
        return True
    if n.startswith("nao"):
        return False
    return None


def _ex2_params(el) -> dict[str, str]:
    return dict(_EX2_PARAMS.findall((el.get("onclick") or "") if el is not None else ""))


def _ex2_tabela(soup: BeautifulSoup, *caption_trechos: str):
    """A primeira <table> cujo caption contenha um dos trechos (comparação sem acento)."""
    alvos = [_ex2_norm(t) for t in caption_trechos]
    for cap in soup.find_all("caption"):
        c = _ex2_norm(_ex2_txt(cap))
        if any(a in c for a in alvos):
            return cap.find_parent("table")
    return None


def _ex2_cabecalho(tabela) -> dict[str, int]:
    """Mapa rótulo-normalizado → índice da coluna, lido do thead (primeira linha)."""
    head = tabela.find("thead")
    tr = head.find("tr") if head else None
    if tr is None:
        return {}
    return {_ex2_norm(_ex2_txt(th)): i for i, th in enumerate(tr.find_all(["th", "td"]))}


def _ex2_col(cab: dict[str, int], *rotulos: str) -> int | None:
    for r in rotulos:
        r = _ex2_norm(r)
        for k, i in cab.items():
            if k == r or k.startswith(r):
                return i
    return None


def _ex2_linhas(tabela) -> list:
    corpo = tabela.find("tbody") or tabela
    return [tr for tr in corpo.find_all("tr", recursive=False)] or [
        tr for tr in tabela.find_all("tr") if tr.find_parent("thead") is None and tr.find_parent("tfoot") is None
    ]


def _ex2_rotulos(tabela) -> list[tuple[str, list[str]]]:
    """Pares (rótulo, [valores]) de uma tabela th→td. Linha sem th (td vazio + td valor) continua o rótulo anterior."""
    out: list[tuple[str, list[str]]] = []
    if tabela is None:
        return out
    for tr in tabela.find_all("tr"):
        cels = tr.find_all(["th", "td"], recursive=False)
        if not cels:
            continue
        if any(c.name == "th" for c in cels):
            i = 0
            while i < len(cels):
                c = cels[i]
                if c.name == "th":
                    rot = _ex2_txt(c)
                    val = cels[i + 1] if i + 1 < len(cels) and cels[i + 1].name == "td" else None
                    if rot:
                        out.append((rot, [_ex2_txt(val)] if val is not None else []))
                    i += 2
                else:
                    i += 1
        elif len(cels) == 2 and not _ex2_txt(cels[0]) and out and "subFormulario" not in (cels[1].get("class") or []):
            v = _ex2_txt(cels[1])
            if v:
                out[-1][1].append(v)
    return out


def _ex2_get(pares: list[tuple[str, list[str]]], *rotulos: str, todos: bool = False):
    alvos = [_ex2_norm(r) for r in rotulos]
    achados = [vals for rot, vals in pares if _ex2_norm(rot) in alvos]
    if todos:
        return achados
    if not achados or not achados[0]:
        return None
    return achados[0][0] or None


def _ex2_secoes(soup: BeautifulSoup) -> dict[str, str]:
    """Seções 'h4 + p' (Descrição, Resumo, Público Alvo...)."""
    out: dict[str, str] = {}
    for h in soup.find_all("h4"):
        titulo = _ex2_txt(h)
        if not titulo or _ex2_norm(titulo).startswith("membros"):
            continue
        partes = []
        for sib in h.find_next_siblings():
            if sib.name in ("h4", "h2", "h3", "table"):
                break
            if sib.name in ("p", "div", "ul"):
                partes.append(_ex2_txt(sib))
        texto = " ".join(p for p in partes if p)
        if texto:
            out[titulo] = texto
    return out


def _ex2_membros(soup: BeautifulSoup) -> list[MembroEquipePublica]:
    out = []
    for tab in soup.select("table.equipeProjeto"):
        desc = tab.find("td", class_="descricao") or tab
        nome_el = desc.find("span", class_="nome")
        link = nome_el.find("a", href=re.compile(r"siape|portal")) if nome_el else None
        nome = _ex2_txt(link) if link else ""
        if not nome and nome_el is not None:
            primeiro = next((s for s in nome_el.find_all(string=True, recursive=False) if s.strip()), "")
            nome = _ex2_txt(primeiro) or _ex2_txt(nome_el).split(" Categoria")[0]
        texto = _ex2_txt(desc)
        cat = re.search(r"Categoria\s*:\s*(.+?)(?=\s+(?:Fun\S*o|Tipo)\s*:|\s+Entre em contato|\s+\S+@\S+|$)", texto)
        fun = re.search(r"(?:Fun\S*o|Tipo)\s*:\s*(.+?)(?=\s+Entre em contato|\s+\S+@\S+|$)", texto)
        funcao = _ex2_txt(fun.group(1)) if fun else None
        if funcao:  # "COORDENADOR(A) COORDENADOR(A)" → uma vez só
            m = re.fullmatch(r"(.+?)\s+\1", funcao)
            funcao = m.group(1) if m else funcao
        siape = None
        if link is not None:
            m = re.search(r"siape=\s*(\d+)", link.get("href") or "")
            siape = int(m.group(1)) if m else None
        if not nome:
            continue
        out.append(
            MembroEquipePublica(
                nome=nome,
                categoria=_ex2_none(cat.group(1)) if cat else None,
                funcao=funcao,
                coordenador="COORDENADOR" in (funcao or "").upper() and "VICE" not in (funcao or "").upper(),
                siape=siape,
            )
        )
    return out


def mensagens_publico(html: str | bytes) -> list[str]:
    """Mensagens do painel de erros/avisos do SIGAA (ex.: 'Não foram encontrados resultados...')."""
    soup = _ex2_soup(html)
    return [_ex2_txt(li) for li in soup.select("#painel-erros li, ul.erros li, ul.warning li, ul.info li")]


# ------------------------------------------------------------------ pesquisa
def parse_projetos_pesquisa(html: str | bytes) -> list[ProjetoPesquisaResumo]:
    """Lista de projetos da consulta 'Quem pesquisa o que' (agrupada por centro e ano)."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Projetos de Pesquisa Encontrados", "Projetos encontrados")
    if tab is None:
        return []
    out: list[ProjetoPesquisaResumo] = []
    centro = ano = None
    atual: dict | None = None
    for tr in _ex2_linhas(tab):
        classes = tr.get("class") or []
        tds = tr.find_all("td", recursive=False)
        if "centro" in classes:
            centro = _ex2_none(_ex2_txt(tr))
            continue
        if "ano" in classes:
            ano = _ex2_int(_ex2_txt(tr))
            continue
        if not tds:
            continue
        if tds[0].get("rowspan"):  # 1ª linha do registro: código | título
            atual = {
                "codigo": _ex2_none(_ex2_txt(tds[0])),
                "titulo": _ex2_txt(tds[1]) if len(tds) > 1 else "",
                "centro": centro,
                "ano": ano,
            }
            out.append(ProjetoPesquisaResumo(**atual))
            continue
        link = tr.find("a", onclick=re.compile(r"'id'\s*:"))
        if atual is not None and (link is not None or len(tds) >= 3):  # 2ª linha: coordenador | tipo | situação | ver
            vals = [_ex2_txt(td) for td in tds]
            pid = _ex2_int(_ex2_params(link).get("id")) if link is not None else None
            out[-1] = out[-1].model_copy(
                update={
                    "coordenador": _ex2_none(vals[0]) if vals else None,
                    "tipo": _ex2_none(vals[1]) if len(vals) > 1 else None,
                    "situacao": _ex2_none(vals[2]) if len(vals) > 2 else None,
                    "id": pid,
                }
            )
            atual = None
    return [p for p in out if p.titulo]


def parse_projeto_pesquisa(html: str | bytes) -> ProjetoPesquisa:
    """Visualização de um projeto de pesquisa."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Projeto de Pesquisa") or soup.find("table", class_="visualizacao")
    pares = _ex2_rotulos(tab)
    g = lambda *r: _ex2_get(pares, *r)  # noqa: E731
    codigo = g("Código")
    cota = g("Cota")
    ini, fim = _ex2_datas(cota)
    secoes = _ex2_secoes(soup)
    resumo = next((v for k, v in secoes.items() if _ex2_norm(k) in ("descricao", "resumo")), None)
    pal = g("Palavra-Chave", "Palavras-Chave", "Palavras Chave")
    m_ano = re.search(r"-(\d{4})\b", codigo or "")
    return ProjetoPesquisa(
        codigo=codigo,
        titulo=g("Título"),
        ano=int(m_ano.group(1)) if m_ano else None,
        tipo=g("Tipo do Projeto", "Tipo"),
        situacao=g("Situação"),
        centro=g("Centro", "Unidade"),
        coordenador=g("Coordenador", "Coordenador(a)"),
        edital=g("Edital"),
        cota=cota,
        data_inicio=ini,
        data_fim=fim,
        palavras_chave=[p.strip() for p in re.split(r"[.;,]\s*", pal or "") if p.strip()],
        area_conhecimento=g("Área de Conhecimento"),
        grupo_pesquisa=g("Grupo de Pesquisa"),
        linha_pesquisa=g("Linha de Pesquisa"),
        resumo=resumo,
        secoes=secoes,
        membros=_ex2_membros(soup),
    )


def parse_bases_pesquisa(html: str | bytes) -> list[BasePesquisa]:
    """Lista de bases (grupos) de pesquisa."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Bases de Pesquisa", "Grupos de Pesquisa")
    if tab is None:
        return []
    cab = _ex2_cabecalho(tab)
    i_cod, i_nome, i_coord = _ex2_col(cab, "Código"), _ex2_col(cab, "Nome"), _ex2_col(cab, "Coordenador")
    out = []
    for tr in _ex2_linhas(tab):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        cel = lambda i: _ex2_txt(tds[i]) if i is not None and i < len(tds) else ""  # noqa: E731
        nome = cel(i_nome if i_nome is not None else 1)
        if not nome:
            continue
        link = tr.find("a", onclick=re.compile(r"'id\w*'\s*:"))
        p = _ex2_params(link)
        bid = next((_ex2_int(v) for k, v in p.items() if k.lower().startswith("id")), None)
        out.append(
            BasePesquisa(
                id=bid,
                codigo=_ex2_none(cel(i_cod)),
                nome=nome,
                coordenador=_ex2_none(cel(i_coord if i_coord is not None else 2)),
            )
        )
    return out


def parse_bolsistas_pesquisa(html: str | bytes) -> list[BolsistaPesquisa]:
    """Lista de bolsistas de iniciação científica (agrupada por cota)."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Alunos encontrados", "Bolsistas encontrados")
    if tab is None:
        return []
    out: list[dict] = []
    cota = None
    for tr in _ex2_linhas(tab):
        classes = tr.get("class") or []
        tds = tr.find_all("td", recursive=False)
        if "cota" in classes:
            cota = _ex2_none(_ex2_txt(tr))
            continue
        rot = tr.find("i")
        if rot is not None and out:
            r = _ex2_norm(_ex2_txt(rot))
            valor = _ex2_txt(tr).split(":", 1)[-1].strip() if ":" in _ex2_txt(tr) else _ex2_txt(tr)
            b = out[-1]
            if r.startswith("projeto"):
                m = re.match(r"(\S+-\d{4})\s*-\s*(.+)", valor)
                b["projeto_codigo"], b["projeto_titulo"] = (m.group(1), m.group(2)) if m else (None, valor or None)
            elif r.startswith("titulo"):
                b["plano_titulo"] = valor or None
            elif r.startswith("orientador"):
                b["orientador"] = valor or None
            elif r.startswith("periodo"):
                b["data_inicio"], b["data_fim"] = _ex2_datas(valor)
            continue
        if len(tds) >= 2 and not tds[0].get("colspan"):
            nome = _ex2_txt(tds[0])
            if nome:
                out.append({"discente": nome, "tipo_bolsa": _ex2_none(_ex2_txt(tds[1])), "cota": cota})
    return [BolsistaPesquisa(**b) for b in out]


def parse_laboratorios(html: str | bytes) -> list[LaboratorioPesquisaResumo]:
    """Lista de laboratórios de pesquisa."""
    soup = _ex2_soup(html)
    tab = soup.find("table", id="tableLaboratoriosEncontrados") or _ex2_tabela(soup, "Laboratórios Encontrados")
    if tab is None:
        return []
    cab = _ex2_cabecalho(tab)
    i_cod, i_nome = _ex2_col(cab, "Código"), _ex2_col(cab, "Nome")
    i_uni, i_coord = _ex2_col(cab, "Unidade"), _ex2_col(cab, "Coordenador")
    out = []
    for tr in tab.find_all("tr"):
        if tr.find_parent("thead") is not None:
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        cel = lambda i: _ex2_txt(tds[i]) if i is not None and i < len(tds) else ""  # noqa: E731
        nome = cel(i_nome if i_nome is not None else 1)
        if not nome:
            continue
        link = tr.find("a", onclick=re.compile(r"'id'\s*:"))
        out.append(
            LaboratorioPesquisaResumo(
                id=_ex2_int(_ex2_params(link).get("id")) if link is not None else None,
                codigo=_ex2_none(cel(i_cod if i_cod is not None else 0)),
                nome=nome,
                unidade=_ex2_none(cel(i_uni)),
                coordenador=_ex2_none(cel(i_coord)),
            )
        )
    return out


def parse_laboratorio(html: str | bytes) -> LaboratorioPesquisa:
    """Visualização de um laboratório de pesquisa."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Dados do Laboratório") or soup.find("table", class_="formulario")
    pares = _ex2_rotulos(tab)
    g = lambda *r: _ex2_get(pares, *r)  # noqa: E731
    lista = lambda *r: (_ex2_get(pares, *r, todos=True) or [[]])[0]  # noqa: E731
    pal = g("Palavras Chave", "Palavras-Chave")
    presta = pretende = None
    serv_atuais: list[str] = []
    serv_futuros: list[str] = []
    alvo = serv_atuais  # os blocos "Serviços:" vêm logo depois da pergunta a que se referem
    for rot, vals in pares:
        n = _ex2_norm(rot)
        if n.startswith("existe prestacao"):
            presta, alvo = _ex2_bool(vals[0] if vals else ""), serv_atuais
        elif n.startswith("existe intencao"):
            pretende, alvo = _ex2_bool(vals[0] if vals else ""), serv_futuros
        elif n == "servicos":
            alvo.extend(v for v in vals if v not in alvo)
    return LaboratorioPesquisa(
        codigo=g("Código"),
        tipo=g("Tipo de Laboratório"),
        nome=g("Nome"),
        sigla=g("Sigla"),
        descricao=g("Descrição"),
        inicio_atividades=_ex2_data(g("Início das Atividades")),
        em_atividade=_ex2_bool(g("Laboratório em Atividade")),
        area_m2=_ex2_float(g("Área")),
        unidade=g("Unidade"),
        subunidade=g("Subunidade"),
        localizacao=g("Localização Física", "Localização"),
        grupos_pesquisa=lista("Grupos de Pesquisa"),
        programas_pos=lista("Programas de Pós"),
        producoes=lista("Produções Científicas"),
        palavras_chave=[p.strip() for p in (pal or "").split(",") if p.strip()],
        presta_servicos=presta,
        servicos=serv_atuais,
        pretende_prestar_servicos=pretende,
        servicos_futuros=serv_futuros,
        coordenador=g("Coordenador"),
        inicio_coordenacao=_ex2_data(g("Início da Coordenação")),
        vice_coordenador=g("Vice-Coordenador"),
    )


# ------------------------------------------------------------------ extensão
def parse_acoes_extensao(html: str | bytes) -> list[AcaoExtensaoResumo]:
    """Lista de ações de extensão (consulta_extensao.jsf)."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Ações de extensão localizadas", "Ações localizadas")
    if tab is None:
        return []
    cab = _ex2_cabecalho(tab)
    i_tit, i_tipo, i_uni = _ex2_col(cab, "Ano/Título", "Título"), _ex2_col(cab, "Tipo"), _ex2_col(cab, "Departamento", "Unidade")
    out = []
    for tr in _ex2_linhas(tab):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        cel = lambda i: _ex2_txt(tds[i]) if i is not None and i < len(tds) else ""  # noqa: E731
        bruto = cel(i_tit if i_tit is not None else 0)
        if not bruto:
            continue
        m = re.match(r"(\d{4})\s*-\s*(.+)", bruto)
        link = tr.find("a", onclick=re.compile("idAtividadeExtensaoSelecionada"))
        p = _ex2_params(link)
        out.append(
            AcaoExtensaoResumo(
                id=_ex2_int(p.get("idAtividadeExtensaoSelecionada")),
                ano=int(m.group(1)) if m else None,
                titulo=m.group(2).strip() if m else bruto,
                tipo=_ex2_none(cel(i_tipo if i_tipo is not None else 1)),
                tipo_id=_ex2_int(p.get("acao")),
                unidade=_ex2_none(cel(i_uni if i_uni is not None else 2)),
            )
        )
    return out


def parse_acao_extensao(html: str | bytes) -> AcaoExtensao:
    """Visualização de uma ação de extensão (programa, projeto, curso, evento, produto)."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Ação de Extensão") or soup.find("table", class_="visualizacao")
    pares = _ex2_rotulos(tab)
    g = lambda *r: _ex2_get(pares, *r)  # noqa: E731
    unidades: list[str] = []
    if tab is not None:
        lab = next((s for s in tab.find_all("span", class_="label") if "envolvidas" in _ex2_norm(_ex2_txt(s))), None)
        if lab is not None:
            td = lab.find_parent("td")
            unidades = [t.strip() for t in td.get_text("\n").split("\n") if t.strip() and "envolvidas" not in _ex2_norm(t)]

    def _quebrado(*rotulos):
        if tab is None:
            return []
        alvos = [_ex2_norm(r) for r in rotulos]
        for th in tab.find_all("th"):
            if _ex2_norm(_ex2_txt(th)) in alvos:
                td = th.find_next_sibling("td")
                return [t.strip() for t in td.get_text("\n").split("\n") if t.strip()] if td else []
        return []

    membros = _ex2_membros(soup)
    secoes = _ex2_secoes(soup)
    sec = lambda *ks: next((v for k, v in secoes.items() if _ex2_norm(k) in [_ex2_norm(x) for x in ks]), None)  # noqa: E731
    coord = next((m.nome for m in membros if m.coordenador), None) or g("Coordenador", "Coordenação")
    url = g("Url da Acão", "Url da Ação", "URL da Ação")
    m_id = re.search(r"visualizacaoAcaoExtensao/(\d+)", url or "")
    return AcaoExtensao(
        id=int(m_id.group(1)) if m_id else None,
        titulo=g("Título"),
        ano=_ex2_int(g("Ano")),
        tipo=g("Tipo"),
        bolsas_concedidas=_ex2_int(g("Nº Bolsas Concedidas", "No Bolsas Concedidas")),
        discentes_envolvidos=_ex2_int(g("Nº Discentes Envolvidos", "No Discentes Envolvidos")),
        publico_estimado=_ex2_int(g("Público Estimado")),
        area_principal=g("Área Principal"),
        area_cnpq=g("Área do CNPq"),
        unidade_proponente=g("Unidade Proponente"),
        unidades_envolvidas=unidades,
        municipios=_quebrado("Municípios de Realização"),
        espacos=_quebrado("Espaços de Realização"),
        fonte_financiamento=g("Fonte de Financiamento"),
        url=url,
        coordenador=coord,
        resumo=sec("Resumo"),
        publico_alvo=sec("Público Alvo", "Público-Alvo"),
        campos={rot.rstrip(": ").strip(): vals[0] for rot, vals in pares if vals and vals[0]},
        secoes=secoes,
        membros=membros,
    )


def parse_inscricoes_extensao(html: str | bytes) -> list[InscricaoExtensaoAberta]:
    """Cursos/eventos de extensão com período de inscrição aberto (só a listagem)."""
    soup = _ex2_soup(html)
    tab = _ex2_tabela(soup, "Inscrições Abertas")
    if tab is None:
        return []
    out: list[InscricaoExtensaoAberta] = []
    corpo = tab.find("tbody") or tab
    for tr in corpo.find_all("tr", recursive=False):
        sub = tr.find("table", class_="listagemSub")
        if sub is not None:  # linha escondida com as mini atividades do registro anterior
            if out:
                minis = []
                for st in (sub.find("tbody") or sub).find_all("tr"):
                    c = [_ex2_txt(td) for td in st.find_all("td")]
                    if c and c[0]:
                        minis.append(MiniAtividadeExtensao(
                            titulo=c[0],
                            data=_ex2_none(c[1]) if len(c) > 1 else None,
                            hora=_ex2_none(c[2]) if len(c) > 2 else None,
                            local=_ex2_none(c[3]) if len(c) > 3 else None,
                        ))
                out[-1] = out[-1].model_copy(update={"mini_atividades": minis})
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7:
            continue
        titulo_el = tds[0].find("span")
        titulo = _ex2_txt(titulo_el) if titulo_el else _ex2_txt(tds[0])
        coord = re.search(r"Coordena\S*o\s*:\s*(.+)", _ex2_txt(tds[0]))
        link = tr.find("a", onclick=re.compile("idAtividadeExtensaoSelecionada"))
        out.append(
            InscricaoExtensaoAberta(
                id=_ex2_int(_ex2_params(link).get("idAtividadeExtensaoSelecionada")),
                titulo=titulo,
                tipo=_ex2_none(_ex2_txt(tds[1])),
                coordenador=_ex2_none(coord.group(1)) if coord else None,
                inscricoes_ate=_ex2_data(_ex2_txt(tds[2])),
                vagas_total=_ex2_int(_ex2_txt(tds[3])),
                vagas_aprovadas=_ex2_int(_ex2_txt(tds[4])),
                vagas_pendentes=_ex2_int(_ex2_txt(tds[5])),
                vagas_restantes=_ex2_int(_ex2_txt(tds[6])),
            )
        )
    return out


# ------------------------------------------------------------ cursos abertos
def parse_centros_cursos_abertos(html: str | bytes) -> list[CentroCursoAberto]:
    """Centros do filtro (select idCentro) com os departamentos do menu lateral (dd id=<id do centro>)."""
    soup = _ex2_soup(html)
    sel = soup.find("select", id="formPrincipal:idCentro")
    out = []
    for op in sel.find_all("option") if sel else []:
        cid = _ex2_int(op.get("value"))
        if not cid:
            continue
        dd = soup.find("dd", id=str(cid))
        deps = [DepartamentoCursoAberto(nome=_ex2_txt(a)) for a in (dd.find_all("a", class_="departamento") if dd else []) if _ex2_txt(a)]
        out.append(CentroCursoAberto(id=cid, nome=_ex2_txt(op), departamentos=deps))
    return out


def parse_departamentos_cursos_abertos(html: str | bytes) -> list[DepartamentoCursoAberto]:
    """Opções do select idDepartamento (página ou resposta AJAX a4j depois de escolher o centro)."""
    soup = _ex2_soup(html)
    sel = soup.find("select", id="formPrincipal:idDepartamento")
    return [
        DepartamentoCursoAberto(id=_ex2_int(op.get("value")), nome=_ex2_txt(op))
        for op in (sel.find_all("option") if sel else [])
        if _ex2_int(op.get("value"))
    ]


def parse_cursos_abertos(html: str | bytes) -> list[CursoAbertoTurma]:
    """Turmas abertas listadas (últimas publicadas ou resultado da busca)."""
    soup = _ex2_soup(html)
    caixa = soup.find(id="turmasAbertas") or soup
    out = []
    for a in caixa.find_all("a", onclick=re.compile(r"'tid'\s*:")):
        tid = _ex2_int(_ex2_params(a).get("tid"))
        if not tid:
            continue
        td = a.find_parent("td")
        codigo = None
        if td is not None:
            antes = "".join(s for s in td.find_all(string=True, recursive=False))
            codigo = _ex2_none(antes)
        out.append(CursoAbertoTurma(id=tid, codigo=codigo, nome=_ex2_txt(a)))
    return out


def parse_curso_aberto(html: str | bytes) -> CursoAberto:
    """Página pública de uma turma aberta (informações gerais, docentes e material)."""
    soup = _ex2_soup(html)
    form = soup.find("form", id="formResumoCursoAberto") or soup
    h4 = _ex2_txt(form.find("h4"))
    m = re.match(r"(.+?)\s*\(([^()]+)\)\s*$", h4)
    nome, codigo = (m.group(1), m.group(2)) if m else (h4 or None, None)
    tab = _ex2_tabela(soup, "Informações Gerais") or form.find("table", class_="visualizacao")
    pares = _ex2_rotulos(tab)
    docentes = []
    for bloco in (tab.select("div.bloco") if tab else []):
        n = _ex2_txt(bloco.find("span", class_="nome"))
        if not n:
            continue
        perfil = bloco.find("a", href=re.compile("siape="))
        ms = re.search(r"siape=(\d+)", perfil["href"]) if perfil else None
        docentes.append(DocenteCursoAberto(nome=n, siape=int(ms.group(1)) if ms else None))
    topicos = []
    for div in form.select("div.topico-aula"):
        h3 = _ex2_txt(div.find("h3"))
        mt = re.match(r"(.*?)\s*\(([^()]*)\)\s*$", h3)
        titulo = mt.group(1) if mt else h3
        ini, fim = _ex2_datas(mt.group(2) if mt else "")
        ul = div.find("ul")
        conteudo = _ex2_none(_ex2_txt(ul)) if ul else None
        mats = []
        for a in div.find_all("a", href=re.compile("verProducao")):
            mid = re.search(r"idProducao=(\d+)", a["href"])
            mats.append(MaterialCursoAberto(
                titulo=_ex2_txt(a),
                descricao=_ex2_none(a.get("title")),
                id_producao=int(mid.group(1)) if mid else None,
                url=a["href"],
            ))
        topicos.append(TopicoCursoAberto(titulo=titulo, data_inicio=ini, data_fim=fim, conteudo=conteudo, materiais=mats))
    return CursoAberto(
        codigo=codigo,
        nome=nome,
        periodo=_ex2_get(pares, "Data da Oferta", "Período"),
        ementa=_ex2_get(pares, "Ementa"),
        docentes=docentes,
        topicos=topicos,
    )
