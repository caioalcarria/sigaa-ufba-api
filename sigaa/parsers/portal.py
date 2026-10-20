"""Parsers (puros, sem rede) das telas do Portal do Discente.

Tolerância: cada aluno vê uma variação destas telas (bolsista, formando, pós, aluno sem
turma, sem foto, fórum vazio...). Tudo é procurado por RÓTULO/ID e o que faltar vira None.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from sigaa.models.portal import (
    Atividade,
    Atualizacao,
    CaixaPostal,
    Contato,
    Curso,
    DadosInstitucionais,
    DadosPessoais,
    Documentos,
    Endereco,
    FiltrosSalasLivres,
    ForumCurso,
    Integralizacao,
    Mensagem,
    MensagemForum,
    MensagemResumo,
    Modulo,
    Modulos,
    NoticiaPortal,
    OpcaoFiltro,
    Perfil,
    PortalDiscente,
    RelatorioSalasLivres,
    SalaLivre,
    TopicoForum,
    TopicoForumDetalhe,
    Turma,
)
from sigaa.util.horario import decodificar, separar_locais

_RE_JSF_PARAMS = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")
_RE_PERIODO = re.compile(r"\b(\d{4})\.(\d)\b")
_RE_DATA = re.compile(r"(\d{2}/\d{2}/\d{4})")
_RE_DATA_HORA = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\s*(?:às|as|-)?\s*(\d{1,2}:\d{2}))?")
_RE_COD_NOME = re.compile(r"^\s*([A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*)\s+-\s+(.+?)\s*$")


# ----------------------------------------------------------------- helpers
def _soup(html: str | bytes) -> BeautifulSoup:
    if isinstance(html, bytes):
        html = html.decode("iso-8859-1", errors="replace")
    return BeautifulSoup(html, "lxml")


def _limpa(s: str | None) -> str | None:
    if s is None:
        return None
    s = _html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _txt(el: Tag | None, sep: str = " ") -> str | None:
    return _limpa(el.get_text(sep)) if el is not None else None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _int(s: str | None) -> int | None:
    if s is None:
        return None
    m = re.search(r"-?\d+", s.replace(".", ""))
    return int(m.group()) if m else None


def _float_br(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip().replace("R$", "").replace(" ", "")
    if not re.search(r"\d", s):
        return None
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return float(s)
    except ValueError:
        return None


def _data(s: str | None) -> date | None:
    if not s:
        return None
    m = _RE_DATA.search(s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y").date()
    except ValueError:
        return None


def _data_hora(s: str | None) -> datetime | None:
    if not s:
        return None
    m = _RE_DATA_HORA.search(s)
    if not m:
        return None
    try:
        d = datetime.strptime(m.group(1), "%d/%m/%Y")
    except ValueError:
        return None
    if m.group(2):
        hh, mm = m.group(2).split(":")
        d = d.replace(hour=int(hh), minute=int(mm))
    return d


def _params(onclick: str | None) -> dict[str, str]:
    if not onclick or "jsfcljs" not in onclick:
        return {}
    m = re.search(r"jsfcljs\([^,]+,\s*\{(.*?)\}", onclick, re.S)
    return dict(_RE_JSF_PARAMS.findall(m.group(1))) if m else {}


def _cod_nome(s: str) -> tuple[str | None, str]:
    s = _limpa(s) or ""
    m = _RE_COD_NOME.match(s)
    return (m.group(1), m.group(2).strip()) if m else (None, s)


def _periodo(s: str | None) -> tuple[str | None, int | None, int | None]:
    if not s:
        return None, None, None
    m = _RE_PERIODO.search(s)
    if not m:
        return None, None, None
    return f"{m.group(1)}.{m.group(2)}", int(m.group(1)), int(m.group(2))


def _conteudo(sp: BeautifulSoup) -> Tag:
    return sp.find(id="conteudo") or sp.body or sp


def semestre_atual(html: str | bytes | BeautifulSoup) -> str | None:
    sp = html if isinstance(html, BeautifulSoup) else _soup(html)
    p = sp.select_one("p.periodo-atual")
    per, _, _ = _periodo(_txt(p))
    return per


def _turma(
    nome_txt: str,
    *,
    turma_id: int | None = None,
    front_end_id: str | None = None,
    periodo: str | None = None,
    turma: str | None = None,
    ch: int | None = None,
    horario_txt: str | None = None,
    local_txt: str | None = None,
    nivel: str | None = None,
    atual_periodo: str | None = None,
) -> Turma:
    codigo, nome = _cod_nome(nome_txt)
    per, ano, sem = _periodo(periodo)
    local, locais = separar_locais(local_txt)
    return Turma(
        turma_id=turma_id,
        front_end_id=front_end_id,
        periodo=per,
        ano=ano,
        semestre=sem,
        codigo=codigo,
        nome=nome,
        turma=turma,
        carga_horaria=ch,
        nivel=nivel,
        local=local,
        locais=locais,
        horario=decodificar(horario_txt) if horario_txt else None,
        atual=bool(per and atual_periodo and per == atual_periodo),
    )


# ---------------------------------------------------------- portal: dados
def _dados_institucionais(sp: BeautifulSoup) -> DadosInstitucionais:
    dados: dict[str, str] = {}
    integ: dict[str, str] = {}
    # A caixa "Dados Institucionais" é um div#agenda-docente com <h4>; há outro #agenda-docente (botões)
    caixa = None
    for div in sp.find_all(id="agenda-docente"):
        h4 = div.find("h4")
        if h4 and "institucion" in _norm(h4.get_text()):
            caixa = div
            break
    if caixa is None:
        caixa = sp.find(id="perfil-docente")
    if caixa is not None:
        for tr in caixa.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) != 2:
                continue
            k, v = _txt(tds[0]), _txt(tds[1])
            if not k or tds[1].find("table"):
                continue
            k = k.rstrip(":").strip()
            if _norm(k).startswith("ch "):
                integ[k] = v or ""
            else:
                dados[k] = v or ""

    def pega(*rotulos: str) -> str | None:
        for r in rotulos:
            for k, v in dados.items():
                if _norm(k) == _norm(r):
                    return v or None
        return None

    conhecidos = {"matricula", "curso", "nivel", "status", "e mail", "email", "entrada"}
    extras = {k: v for k, v in dados.items() if _norm(k) not in conhecidos}

    curso_txt = pega("Curso")
    curso = _curso(curso_txt) if curso_txt else None

    email = pega("E-Mail", "Email", "E-mail")
    truncado = bool(email and email.endswith("..."))

    integralizacao = None
    if integ or (caixa is not None and "Integraliz" in caixa.get_text()):
        integralizacao = _integralizacao(caixa, integ)

    nome = _txt(sp.select_one("p.info-docente span.nome")) or None
    abrev = None
    usu = sp.select_one("#info-usuario p.usuario span")
    if usu is not None:
        abrev = _limpa(usu.get("title")) or _txt(usu)
    unidade_txt = _txt(sp.select_one("#info-usuario p.unidade"))
    unidade, unidade_cod = None, None
    if unidade_txt:
        m = re.match(r"(.*?)\s*\(([\d.]+)\)\s*$", unidade_txt)
        unidade, unidade_cod = (m.group(1).strip(), m.group(2)) if m else (unidade_txt, None)

    foto = sp.select_one("#perfil-docente .foto img") or sp.find("img", src=re.compile(r"verFoto"))
    foto_url = foto.get("src") if foto is not None and "verFoto" in (foto.get("src") or "") else None

    id_disc = None
    menu = sp.find("form", id="menu:form_menu_discente")
    if menu is not None:
        inp = menu.find("input", attrs={"name": "id"})
        id_disc = _int(inp.get("value")) if inp is not None else None

    return DadosInstitucionais(
        nome=nome,
        nome_abreviado=abrev,
        matricula=pega("Matrícula", "Matricula"),
        id_discente=id_disc,
        curso=curso,
        nivel=pega("Nível", "Nivel"),
        status=pega("Status"),
        email=email,
        email_truncado=truncado,
        entrada=pega("Entrada"),
        unidade=unidade,
        unidade_codigo=unidade_cod,
        semestre_atual=semestre_atual(sp),
        foto_url=foto_url,
        campos_extras=extras,
        integralizacao=integralizacao,
    )


def _curso(texto: str) -> Curso:
    t = _limpa(texto) or texto
    partes = [p.strip() for p in re.split(r"\s+-\s+|\s+-$", t) if p.strip()]
    nome = unidade = inst = municipio = grau = turno = None
    if partes:
        cab = partes[0].split("/")
        nome = cab[0].strip() or None
        if len(cab) > 1:
            unidade = cab[1].strip() or None
        if len(cab) > 2:
            inst = cab[2].strip() or None
    resto = partes[1:]
    if resto and re.fullmatch(r"[MTNDIV]{1,3}", resto[-1]):
        turno = resto.pop()
    if resto:
        municipio = resto[0]
    if len(resto) > 1:
        grau = resto[1]
    return Curso(texto=t, nome=nome, unidade_sigla=unidade, instituicao=inst, municipio=municipio, grau=grau, turno=turno)


def _integralizacao(caixa: Tag | None, linhas: dict[str, str]) -> Integralizacao:
    campos = {
        "ch obrigatoria pendente": "ch_obrigatoria_pendente",
        "ch optativa pendente": "ch_optativa_pendente",
        "ch complementar pendente": "ch_complementar_pendente",
        "ch total curriculo": "ch_total_curriculo",
    }
    out: dict = {}
    outros: dict[str, int] = {}
    for k, v in linhas.items():
        n = _norm(k)
        if n in campos:
            out[campos[n]] = _int(v)
        elif _int(v) is not None:
            outros[k] = _int(v)  # type: ignore[assignment]
    pct = pct_arred = None
    if caixa is not None:
        barra = caixa.find("div", style=re.compile(r"width:\s*[\d.]+%"))
        if barra is not None:
            m = re.search(r"width:\s*([\d.]+)%", barra["style"])
            if m:
                pct = round(float(m.group(1)), 2)
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*Integralizad", caixa.get_text(" "))
        if m:
            pct_arred = round(float(m.group(1).replace(",", ".")))
    return Integralizacao(**out, percentual=pct, percentual_arredondado=pct_arred, outros=outros)


# --------------------------------------------------- portal: turmas/atualizações
def _turmas_portal(sp: BeautifulSoup, atual: str | None) -> list[Turma]:
    caixa = sp.find(id="turmas-portal")
    if caixa is None:
        return []
    out: list[Turma] = []
    periodo_corrente = atual
    for tabela in caixa.find_all("table"):
        ths = [_norm(th.get_text()) for th in tabela.find_all("th")]
        if not any("componente" in h for h in ths):
            continue
        cols = {h: i for i, h in enumerate(ths)}
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) == 1:
                per, _, _ = _periodo(_txt(tds[0]))
                if per:
                    periodo_corrente = per
                continue
            desc = tr.find("td", class_="descricao")
            if desc is None:
                continue
            a = desc.find("a")
            nome = _txt(a) or _txt(desc) or ""
            p = _params(a.get("onclick") if a else None)
            front = p.get("frontEndIdTurma")
            infos = tr.find_all("td", class_="info")
            local_txt = _txt(infos[0]) if len(infos) > 0 else None
            hor_txt = _txt(infos[1]) if len(infos) > 1 else None
            # a linha seguinte (oculta) traz o idTurma: <td id="linha_393420">
            tid = None
            prox = tr.find_next_sibling("tr")
            if prox is not None:
                cel = prox.find("td", id=re.compile(r"^linha_\d+$"))
                if cel is not None:
                    tid = _int(cel["id"].split("_", 1)[1])
            out.append(
                _turma(
                    nome,
                    turma_id=tid,
                    front_end_id=front,
                    periodo=periodo_corrente,
                    horario_txt=hor_txt,
                    local_txt=local_txt,
                    atual_periodo=atual or periodo_corrente,
                )
            )
        break
    return out


def _atualizacoes(sp: BeautifulSoup) -> list[Atualizacao]:
    form = sp.find("form", id="formAtualizacoesTurmas") or sp.find(id="atualizacoes-turma")
    if form is None:
        return []
    out: list[Atualizacao] = []
    for tab in form.find_all("table"):
        trs = tab.find_all("tr")
        if not trs:
            continue
        a = tab.find("a")
        if a is None:
            continue
        cab = _txt(trs[0]) or ""
        link_txt = _txt(a) or ""
        p = _params(a.get("onclick"))
        texto = _txt(trs[1]) if len(trs) > 1 else None
        texto = texto or ""
        turma_nome, periodo = link_txt, None
        m = re.match(r"(.*)\((\d{4}\.\d)\)\s*$", link_txt)
        if m:
            turma_nome, periodo = m.group(1).strip(), m.group(2)
        tipo = titulo = None
        if ":" in texto:
            tipo, titulo = (x.strip() for x in texto.split(":", 1))
        out.append(
            Atualizacao(
                data=_data(cab),
                turma_id=_int(p.get("idTurma")),
                turma=turma_nome,
                periodo=periodo,
                tipo=tipo or None,
                titulo=titulo or None,
                texto=texto,
            )
        )
    return out


def _tipo_atividade(texto: str, icone: str | None) -> str | None:
    base = _norm(f"{texto} {icone or ''}")
    for chave, rot in (
        ("questionario", "Questionário"),
        ("tarefa", "Tarefa"),
        ("avalia", "Avaliação"),
        ("prova", "Avaliação"),
        ("enquete", "Enquete"),
        ("forum", "Fórum"),
        ("aula", "Aula"),
    ):
        if chave in base:
            return rot
    return None


def _atividades(sp: BeautifulSoup) -> list[Atividade]:
    caixa = sp.find(id="avaliacao-portal") or sp.find("form", id="formAtividades")
    if caixa is None:
        return []
    out: list[Atividade] = []
    for tr in caixa.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        linha = _txt(tr) or ""
        dt = _data_hora(linha)
        if dt is None:
            continue
        img = tr.find("img")
        icone = (img.get("title") or img.get("alt") or img.get("src")) if img else None
        a = tr.find("a")
        p = _params(a.get("onclick")) if a is not None else {}
        # célula de descrição = a mais longa que não é só a data
        cand = [c for c in tds if (_txt(c) or "") and not re.fullmatch(r"[\d/:\s]+", _txt(c) or "")]
        desc_td = max(cand, key=lambda c: len(_txt(c) or ""), default=None)
        turma = None
        descricao = _txt(desc_td) or linha
        if desc_td is not None:
            partes = [x for x in (_limpa(s) for s in desc_td.stripped_strings) if x]
            if len(partes) >= 2:
                turma, descricao = partes[0], " ".join(partes[1:])
        hora = None
        m = re.search(r"\b(\d{1,2}:\d{2})\b", linha)
        if m:
            hora = m.group(1).zfill(5)
        concl = None
        if img is not None and re.search(r"concluid|entregue|check|ok", (img.get("src") or "") + (img.get("title") or ""), re.I):
            concl = True
        out.append(
            Atividade(
                data=dt.date(),
                hora=hora,
                tipo=_tipo_atividade(descricao, icone),
                descricao=descricao,
                turma=turma,
                turma_id=_int(p.get("idTurma") or p.get("id")) if p else None,
                concluida=concl,
                texto=linha,
            )
        )
    return out


def _noticias(sp: BeautifulSoup) -> list[NoticiaPortal]:
    caixa = sp.find(id="noticias-portal")
    if caixa is None:
        return []
    out = []
    for el in caixa.find_all(["a", "p", "li"]):
        t = _txt(el)
        if not t or "não há notícias" in t.lower() or "nao ha noticias" in _norm(t):
            continue
        if el.name != "a" and el.find("a"):
            continue
        id_ = None
        m = re.search(r"id(?:Noticia)?=(\d+)|\((\d+)\)", (el.get("href") or "") + (el.get("onclick") or ""))
        if m:
            id_ = int(m.group(1) or m.group(2))
        out.append(NoticiaPortal(titulo=t, data=_data(t), id=id_))
    return out


def _comunidades(sp: BeautifulSoup) -> list[str]:
    caixa = sp.find(id="participantes")
    if caixa is None or caixa.find("p", class_="vazio"):
        return []
    return [t for t in (_txt(a) for a in caixa.find_all("a")) if t]


def _forum_previa(sp: BeautifulSoup) -> list[TopicoForum]:
    caixa = sp.find(id="forum-portal")
    if caixa is None:
        return []
    return _topicos_tabela(caixa)


def parse_portal(html: str | bytes) -> PortalDiscente:
    """Página inicial do Portal do Discente (/sigaa/verPortalDiscente.do)."""
    sp = _soup(html)
    dados = _dados_institucionais(sp)
    versao = None
    rod = sp.find(id="rodape")
    if rod is not None:
        m = re.search(r"v\d+\.\d+[\w.\-]*", rod.get_text(" "))
        versao = m.group() if m else None
    return PortalDiscente(
        dados=dados,
        turmas_semestre=_turmas_portal(sp, dados.semestre_atual),
        atualizacoes=_atualizacoes(sp),
        atividades=_atividades(sp),
        noticias=_noticias(sp),
        comunidades_virtuais=_comunidades(sp),
        forum_curso=_forum_previa(sp),
        versao_sigaa=versao,
    )


def parse_dados_institucionais(html: str | bytes) -> DadosInstitucionais:
    return _dados_institucionais(_soup(html))


# --------------------------------------------------------- turmas anteriores
def parse_turmas_classico(html: str | bytes) -> list[Turma]:
    """/sigaa/portais/discente/turmas.jsf — 'Todas as Turmas Virtuais' (código, turma, CH,
    horário, frontEndIdTurma). Não traz o idTurma numérico nem o local."""
    sp = _soup(html)
    atual = semestre_atual(sp)
    tabela = None
    for t in _conteudo(sp).find_all("table"):
        cab = _norm(" ".join(th.get_text() for th in t.find_all("th")))
        if "disciplina" in cab or "componente" in cab:
            tabela = t
            break
    if tabela is None:
        return []
    heads = [_norm(th.get_text()) for th in tabela.find_all("th")]

    def idx(*nomes: str) -> int | None:
        for i, h in enumerate(heads):
            if any(n in h for n in nomes):
                return i
        return None

    i_nome, i_turma, i_ch, i_hor = idx("disciplina", "componente"), idx("turma"), idx("ch", "carga"), idx("horario")
    out: list[Turma] = []
    periodo = None
    for tr in tabela.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        if len(tds) == 1 or "periodo" in (tds[0].get("class") or []):
            per, _, _ = _periodo(_txt(tds[0]))
            if per:
                periodo = per
            continue

        def cel(i: int | None) -> str | None:
            return _txt(tds[i]) if i is not None and i < len(tds) else None

        nome = cel(i_nome if i_nome is not None else 0)
        if not nome:
            continue
        front = None
        for a in tr.find_all("a"):
            p = _params(a.get("onclick"))
            if p.get("frontEndIdTurma"):
                front = p["frontEndIdTurma"]
                break
        ch_txt = cel(i_ch)
        out.append(
            _turma(
                nome,
                front_end_id=front,
                periodo=periodo,
                turma=cel(i_turma),
                ch=_int(ch_txt) if ch_txt else None,
                horario_txt=cel(i_hor),
                atual_periodo=atual,
            )
        )
    return out


def parse_turmas_mobile(html: str | bytes, semestre_atual_: str | None = None) -> list[Turma]:
    """/sigaa/mobile/touch/ava/turmas_discente.jsf — 'Turmas do Discente' da interface mobile:
    traz o idTurma NUMÉRICO, local e horário de todas as turmas."""
    sp = _soup(html)
    out: list[Turma] = []
    periodo = nivel = None
    for li in sp.find_all("li"):
        if li.get("data-role") == "list-divider":
            t = _txt(li) or ""
            periodo, _, _ = _periodo(t)
            m = re.search(r"\d{4}\.\d\s*-\s*(.+)$", t)
            nivel = m.group(1).strip() if m else None
            continue
        a = li.find("a")
        if a is None:
            continue
        p = _params(a.get("onclick"))
        if "idTurma" not in p:
            continue
        smalls = [_txt(s) or "" for s in a.find_all("small")]
        local_txt = hor_txt = None
        for s in smalls:
            n = _norm(s)
            if n.startswith("local"):
                local_txt = s.split(":", 1)[1].strip() if ":" in s else None
            elif n.startswith("horario"):
                hor_txt = s.split(":", 1)[1].strip() if ":" in s else None
        for s in a.find_all("small"):
            s.extract()
        nome = _txt(a) or ""
        out.append(
            _turma(
                nome,
                turma_id=_int(p.get("idTurma")),
                periodo=periodo,
                horario_txt=hor_txt,
                local_txt=local_txt,
                nivel=nivel,
                atual_periodo=semestre_atual_,
            )
        )
    if semestre_atual_ is None and out:
        # sem o semestre atual explícito, considera atual o período mais recente
        maior = max((t.periodo for t in out if t.periodo), default=None)
        for t in out:
            t.atual = t.periodo == maior
    return out


def _casa(a: Turma, b: Turma) -> bool:
    if a.turma_id and b.turma_id:
        return a.turma_id == b.turma_id
    if a.front_end_id and b.front_end_id:
        return a.front_end_id == b.front_end_id
    if a.periodo != b.periodo:
        return False
    if a.codigo and b.codigo:
        return a.codigo == b.codigo and (not a.turma or not b.turma or a.turma == b.turma)
    return _norm(a.nome) == _norm(b.nome)


def _completar(base: Turma, t: Turma) -> None:
    for campo in ("turma_id", "front_end_id", "codigo", "turma", "carga_horaria", "nivel", "local", "periodo", "ano", "semestre"):
        if getattr(base, campo) in (None, "") and getattr(t, campo) not in (None, ""):
            setattr(base, campo, getattr(t, campo))
    if not base.locais and t.locais:
        base.locais = t.locais
        base.local = t.local or base.local
    if (base.horario is None or not base.horario.aulas) and t.horario is not None:
        base.horario = t.horario
    base.atual = base.atual or t.atual


def mesclar_turmas(*fontes: list[Turma]) -> list[Turma]:
    """Junta as listas de turmas das várias telas (turmas.jsf, mobile, portal), casando por
    idTurma → frontEndIdTurma → (período, código, turma) → (período, nome), e completa
    campo a campo. Ordena do período mais recente pro mais antigo (estável dentro do período)."""
    res: list[Turma] = []
    for fonte in fontes:
        livres = list(range(len(res)))  # cada item de res casa com no máx. 1 item desta fonte
        for t in fonte:
            alvo = next((i for i in livres if _casa(res[i], t)), None)
            if alvo is None:
                res.append(t.model_copy(deep=True))
                continue
            livres.remove(alvo)
            _completar(res[alvo], t)
    res.sort(key=lambda t: (t.ano or 0, t.semestre or 0), reverse=True)
    return res


# ------------------------------------------------------------ dados pessoais
def _valor_celula(td: Tag) -> str | None:
    """Valor de uma célula de formulário: input (value), select (opção selecionada),
    textarea, radio marcado, ou o texto."""
    partes: list[str] = []
    radios = td.find_all("input", attrs={"type": "radio"})
    if radios:
        for r in radios:
            if r.has_attr("checked"):
                lab = td.find("label", attrs={"for": r.get("id")})
                partes.append(_txt(lab) or r.get("value", ""))
        return " ".join(partes) or None
    controles = td.find_all(["input", "select", "textarea"])
    vis = [c for c in controles if not (c.name == "input" and (c.get("type") or "text").lower() in ("hidden", "submit", "button", "image"))]
    if vis:
        for c in vis:
            if c.name == "select":
                o = c.find("option", selected=True)
                if o is not None and o.get("value") not in ("", "0", "-1", None):
                    partes.append(_txt(o) or "")
            elif c.name == "textarea":
                v = _limpa(c.get_text())
                if v:
                    partes.append(v)
            else:
                v = _limpa(c.get("value"))
                if v:
                    partes.append(v)
        return " ".join(p for p in partes if p) or None
    return _txt(td)


def _pares_formulario(tabela: Tag) -> list[tuple[str, str, str | None]]:
    """[(seção, rótulo, valor)] — trata 'th: td' e rótulos embutidos com <b>Zona:</b> dentro do td."""
    out: list[tuple[str, str, str | None]] = []
    secao = ""
    for tr in tabela.find_all("tr"):
        if tr.find_parent("table") is not tabela:
            continue
        sub = tr.find("td", class_="subFormulario")
        if sub is not None and len(tr.find_all(["td", "th"], recursive=False)) == 1:
            secao = _txt(sub) or secao
            continue
        cels = tr.find_all(["th", "td"], recursive=False)
        i = 0
        while i < len(cels):
            c = cels[i]
            if c.name == "th":
                rot = (_txt(c) or "").rstrip(":").strip()
                td = cels[i + 1] if i + 1 < len(cels) and cels[i + 1].name == "td" else None
                if td is None:
                    out.append((secao, rot, None))
                    i += 1
                    continue
                embutidos = td.find_all("b", recursive=False)
                if embutidos and not td.find(["input", "select", "textarea"]):
                    # "170531590574 <b>Zona:</b> 123" → rótulo do th = texto antes; cada <b> = rótulo do texto depois
                    antes: list[str] = []
                    for no in td.children:
                        if isinstance(no, Tag) and no.name == "b":
                            break
                        antes.append(no.get_text() if isinstance(no, Tag) else str(no))
                    out.append((secao, rot, _limpa("".join(antes))))
                    for b in embutidos:
                        depois: list[str] = []
                        for no in b.next_siblings:
                            if isinstance(no, Tag) and no.name == "b":
                                break
                            depois.append(no.get_text() if isinstance(no, Tag) else str(no))
                        out.append((secao, (_txt(b) or "").rstrip(":").strip(), _limpa("".join(depois))))
                else:
                    out.append((secao, rot, _valor_celula(td)))
                i += 2
            else:
                i += 1
    return out


def parse_dados_pessoais(html: str | bytes) -> DadosPessoais:
    """'Meus Dados Pessoais' (/sigaa/graduacao/discente/dados_discente.jsf)."""
    sp = _soup(html)
    tabela = None
    for t in _conteudo(sp).find_all("table", class_="formulario"):
        tabela = t
        break
    if tabela is None:
        return DadosPessoais()
    pares = _pares_formulario(tabela)
    conhecidos: dict[str, str] = {}
    usados: set[int] = set()

    def pega(*rotulos: str, secao: str | None = None) -> str | None:
        for r in rotulos:
            for i, (sec, k, v) in enumerate(pares):
                if _norm(k) == _norm(r) and (secao is None or _norm(secao) in _norm(sec)):
                    usados.add(i)
                    return v
        return None

    d = DadosPessoais(
        matricula=pega("Matrícula"),
        nome=pega("Nome"),
        curso=pega("Curso"),
        sexo=pega("Sexo"),
        estado_civil=pega("Estado civil"),
        data_nascimento=_data(pega("Data de nascimento", secao="discente") or pega("Data de nascimento")),
        naturalidade=pega("Naturalidade"),
        raca=pega("Raça", "Cor/Raça", "Raca"),
        tipo_sanguineo=pega("Tipo Sanguíneo"),
        nacionalidade=pega("Nacionalidade"),
        pais=pega("País"),
        escola_ensino_medio=pega("Escola de conclusão do Ensino Médio"),
        tipo_escola_ensino_medio=pega("Tipo da Escola de Ensino Médio"),
        ano_conclusao_ensino_medio=_int(pega("Ano de Conclusão")),
        nome_pai=pega("Nome do pai"),
        nome_mae=pega("Nome da mãe"),
    )
    nee = pega("Tipos de NEE", "Necessidades Especiais")
    d.necessidades_especiais = [x.strip() for x in re.split(r"[,;]", nee) if x.strip()] if nee else []

    rg = pega("RG", "Identidade")
    rg_num, rg_org = rg, None
    if rg and " - " in rg:
        rg_num, rg_org = (x.strip() or None for x in rg.split(" - ", 1))
    elif rg and rg.endswith("-"):
        rg_num = rg.rstrip("- ").strip()
    d.documentos = Documentos(
        cpf=pega("CPF"),
        rg=rg_num,
        rg_orgao=rg_org,
        rg_expedicao=_data(pega("Data de Expedição")),
        titulo_eleitor=pega("Título de Eleitor"),
        titulo_zona=pega("Zona"),
        titulo_secao=pega("Seção"),
        titulo_uf=pega("UF", secao="documentos"),
        certificado_militar=pega("Certificado Militar"),
        certificado_militar_expedicao=_data(pega("Data de Expedição do Certificado Militar")),
        certificado_militar_serie=pega("Série"),
        certificado_militar_categoria=pega("Categoria"),
        certificado_militar_orgao=pega("Órgão"),
    )

    # Endereço/contato são campos de formulário — lidos pelos ids (estáveis no SIGAA)
    def campo(*ids: str) -> str | None:
        for i in ids:
            el = sp.find(id=i) or sp.find(attrs={"name": i})
            if el is None:
                continue
            if el.name == "select":
                o = el.find("option", selected=True)
                v = _txt(o) if o is not None and o.get("value") not in ("", "0", "-1", None) else None
            elif el.name == "textarea":
                v = _limpa(el.get_text())
            else:
                v = _limpa(el.get("value"))
            if v:
                return v
        return None

    d.endereco = Endereco(
        cep=campo("formDiscente:endCEP"),
        tipo_logradouro=campo("formDiscente:selectTipoLogradouro"),
        logradouro=campo("formDiscente:txtLogradouro"),
        numero=campo("formDiscente:txtNumero"),
        complemento=campo("formDiscente:txtComplemento"),
        bairro=campo("formDiscente:txtBairro"),
        uf=campo("formDiscente:selectUF"),
        municipio=campo("formDiscente:selectMunicipio"),
    )
    if not any(d.endereco.model_dump().values()):
        d.endereco = Endereco(
            cep=pega("CEP"), logradouro=pega("Logradouro"), numero=pega("Número"), complemento=pega("Complemento"),
            bairro=pega("Bairro"), uf=pega("UF", secao="endere"), municipio=pega("Município"),
        )

    def fone(ddd: str, num: str) -> str | None:
        a, b = campo(ddd), campo(num)
        if not b:
            return None
        return f"({a}) {b}" if a else b

    d.contato = Contato(
        telefone=fone("formDiscente:telFixoDDD", "formDiscente:txtTelefone"),
        celular=fone("formDiscente:telCelDDD", "formDiscente:txtCelular"),
        email=campo("formDiscente:txtEmail") or pega("E-Mail", "Email"),
    )
    d.banco = campo("formDiscente:banco") or pega("Banco")
    d.agencia = campo("formDiscente:agencia", "formDiscente:txtAgencia") or pega("Agência")
    d.conta = campo("formDiscente:conta", "formDiscente:txtConta") or pega("Conta")
    d.renda_familiar = _float_br(campo("formDiscente:txtRendaFamiliar"))
    d.membros_familia = _int(campo("formDiscente:txtQuantidadeMembros"))
    d.zona_residencia = pega("Zona de Residência")
    d.transporte_escolar_publico = pega("Transporte Escolar Público")
    d.tipo_transporte = campo("formDiscente:tipoTransporte") or pega("Tipo de Transporte")

    # o que sobrou e tem valor vira campos_extras (exceto a confirmação de senha)
    ignorar = {"senha", "data de nascimento", "telefone", "e mail", "cep", "logradouro", "numero", "bairro", "uf",
               "banco", "renda familiar bruta mensal", "quantidade de membros do grupo familiar", "tipo de transporte"}
    for i, (sec, k, v) in enumerate(pares):
        if i in usados or not v or _norm(k) in ignorar or "confirm" in _norm(sec) or "senha" in _norm(sec):
            continue
        conhecidos.setdefault(k, v)
    d.campos_extras = conhecidos
    return d


def parse_perfil(html: str | bytes) -> Perfil:
    """perfil.jsf ('Atualizar Foto e Perfil')."""
    sp = _soup(html)
    c = _conteudo(sp)

    def area(*ids: str, titulo: str | None = None) -> str | None:
        for i in ids:
            el = c.find(id=i) or c.find(attrs={"name": i})
            if el is not None:
                return _limpa(el.get_text()) if el.name == "textarea" else _limpa(el.get("value"))
        if titulo:
            for el in c.find_all(["textarea", "input"]):
                if titulo in _norm(el.get("title") or ""):
                    return _limpa(el.get_text()) if el.name == "textarea" else _limpa(el.get("value"))
        return None

    foto = c.find("img", id="fotoPerfil") or c.find("img", src=re.compile("verFoto"))
    foto_url = foto.get("src") if foto is not None and "verFoto" in (foto.get("src") or "") else None
    return Perfil(
        descricao_pessoal=area("descricaoPessoal", titulo="descricao pessoal"),
        areas_interesse=area("areasInteresse", titulo="areas de interesse"),
        curriculo_lattes=area("curriculoLattes", titulo="curriculo lattes"),
        assinatura=area(titulo="assinatura"),
        foto_url=_html.unescape(foto_url) if foto_url else None,
        tem_foto=foto_url is not None and "idFoto=" in foto_url and not re.search(r"idFoto=(&|$|0\b)", foto_url),
    )


# --------------------------------------------------------------------- fórum
def _topicos_tabela(raiz: Tag) -> list[TopicoForum]:
    out: list[TopicoForum] = []
    for tabela in raiz.find_all("table"):
        heads = [_txt(th) or "" for th in tabela.find_all("th")]
        if not heads:
            continue
        hn = [_norm(h) for h in heads]
        if not any(k in " ".join(hn) for k in ("titulo", "topico", "assunto")):
            continue
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2:
                continue
            cols = {heads[i] or f"col{i}": (_txt(td) or "") for i, td in enumerate(tds) if i < len(heads)}

            def col(*nomes: str) -> str | None:
                for i, h in enumerate(hn):
                    if any(n in h for n in nomes) and i < len(tds):
                        return _txt(tds[i])
                return None

            titulo = col("titulo", "topico", "assunto")
            if not titulo:
                continue
            id_ = None
            for a in tr.find_all("a"):
                p = _params(a.get("onclick"))
                for k in ("idTopico", "idForumMensagem", "id", "idMensagem"):
                    if p.get(k, "").isdigit():
                        id_ = int(p[k])
                        break
                if id_ is None:
                    m = re.search(r"id=(\d+)", a.get("href") or "")
                    id_ = int(m.group(1)) if m else None
                if id_:
                    break
            ult = col("ultima", "ultimo")
            out.append(
                TopicoForum(
                    id=id_,
                    titulo=titulo,
                    autor=col("autor", "criado por", "usuario"),
                    respostas=_int(col("resposta", "mensagens")),
                    criado_em=_data_hora(col("criado", "data", "cadastr")),
                    ultima_postagem=_data_hora(ult),
                    ultima_postagem_texto=ult,
                    colunas=cols,
                )
            )
    return out


def parse_forum_curso(html: str | bytes) -> ForumCurso:
    """/sigaa/graduacao/ForumCurso/listar.jsf — listagem dos tópicos do fórum do curso."""
    sp = _soup(html)
    c = _conteudo(sp)
    h2 = c.find("h2")
    titulo = None
    if h2 is not None:
        partes = [p.strip() for p in (_txt(h2) or "").split(">")]
        titulo = partes[-1] if partes else None
    desc = _txt(c.find("div", class_="descricaoOperacao"))
    if desc:
        desc = re.sub(r"^Caro Usu[aá]rio,?\s*", "", desc)
    return ForumCurso(titulo=titulo, descricao=desc, topicos=_topicos_tabela(c))


def parse_topico_forum(html: str | bytes) -> TopicoForumDetalhe:
    """Tela de um tópico do fórum (best-effort: o fórum do curso do autor estava vazio).
    Procura blocos de mensagem por classes comuns do SIGAA e cai pra tabelas com autor/data."""
    sp = _soup(html)
    c = _conteudo(sp)
    titulo = None
    for el in c.find_all(["h3", "h4", "caption", "legend"]):
        t = _txt(el)
        if t:
            titulo = t
            break
    msgs: list[MensagemForum] = []
    blocos = c.select(".mensagem, .forum-mensagem, div.post, table.mensagem, table.listagem tr")
    for b in blocos:
        t = _txt(b, "\n") or ""
        if len(t) < 2:
            continue
        dt = _data_hora(t)
        autor = None
        bold = b.find(["b", "strong"])
        if bold is not None:
            autor = _txt(bold)
        msgs.append(MensagemForum(autor=autor, data=dt, texto=t))
    return TopicoForumDetalhe(titulo=titulo, mensagens=msgs)


# ------------------------------------------------------------------- módulos
def parse_modulos(html: str | bytes) -> Modulos:
    """/sigaa/verMenuPrincipal.do?dialog=true — painel 'Módulos' (cada li tem classe '<chave> on|off')."""
    sp = _soup(html)
    mods: list[Modulo] = []
    grupo = "Módulos"
    for el in sp.find_all(["h3", "h4", "li"]):
        if el.name in ("h3", "h4"):
            grupo = _txt(el) or grupo
            continue
        classes = el.get("class") or []
        if not classes:
            continue
        a = el.find("a")
        nome = _txt(el)
        if not nome:
            continue
        estado = [x for x in classes if x.lower() in ("on", "off", "true", "false")]
        chave = next((x for x in classes if x.lower() not in ("on", "off", "true", "false")), classes[0])
        href = a.get("href") if a is not None else None
        hab = bool(estado and estado[0].lower() in ("on", "true")) or bool(href and href not in ("#", ""))
        mods.append(Modulo(chave=chave, nome=nome, grupo=grupo, habilitado=hab, url=href if hab and href and href != "#" else None))
    # sem cabeçalhos no HTML: o SIGAA ordena Módulos, Outros Sistemas (sipac/sigrh/sigadmin), Portais
    outros = {"sipac", "sigrh", "sigadmin"}
    vistos_portal = False
    for m in mods:
        if m.grupo != "Módulos":
            continue
        if m.chave in outros:
            m.grupo = "Outros Sistemas"
        elif m.chave in ("docente", "discente") or m.chave.startswith("portal_") or m.chave == "tutor" or vistos_portal:
            if m.chave not in ("portal_avaliacao",):
                m.grupo = "Portais"
                vistos_portal = True
    return Modulos(modulos=mods, habilitados=[m.nome for m in mods if m.habilitado])


# -------------------------------------------------------------- caixa postal
def parse_caixa_postal(html: str | bytes) -> CaixaPostal:
    """Caixa de entrada (caixapostal.ufba.br/cxpostal/verCaixadeEntrada.jsf). Best-effort:
    o host só resolve dentro da rede da UFBA; a estrutura não pôde ser validada de fora."""
    sp = _soup(html)
    out: list[MensagemResumo] = []
    for tabela in sp.find_all("table"):
        heads = [_norm(th.get_text()) for th in tabela.find_all("th")]
        if not any("assunto" in h for h in heads):
            continue
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2:
                continue

            def col(n: str) -> str | None:
                for i, h in enumerate(heads):
                    if n in h and i < len(tds):
                        return _txt(tds[i])
                return None

            assunto = col("assunto")
            if not assunto:
                continue
            id_ = None
            for a in tr.find_all("a"):
                m = re.search(r"id(?:Mensagem)?['=:]+\s*'?(\d+)", (a.get("href") or "") + (a.get("onclick") or ""))
                if m:
                    id_ = m.group(1)
                    break
            lida = None
            if tr.get("class"):
                cl = " ".join(tr["class"]).lower()
                lida = False if ("naolida" in cl or "nao-lida" in cl or "unread" in cl) else None
            out.append(MensagemResumo(id=id_, remetente=col("remetente") or col("de"), assunto=assunto, data=_data_hora(col("data")), lida=lida))
    return CaixaPostal(mensagens=out)


def parse_mensagem(html: str | bytes) -> Mensagem:
    sp = _soup(html)
    c = _conteudo(sp)
    pares: dict[str, str] = {}
    for tr in c.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is not None and td is not None:
            pares[_norm(_txt(th) or "")] = _txt(td) or ""
    corpo = c.find(class_=re.compile("corpo|mensagem|texto", re.I))
    return Mensagem(
        remetente=pares.get("remetente") or pares.get("de"),
        assunto=pares.get("assunto"),
        data=_data_hora(pares.get("data") or pares.get("enviada em")),
        texto=_txt(corpo, "\n") or _txt(c, "\n") or "",
    )


# -------------------------------------------------------------- salas livres
def parse_filtros_salas_livres(html: str | bytes) -> FiltrosSalasLivres:
    """Formulário 'Relatório de Salas Livres' (formRelatSalaLivre.jsf)."""
    sp = _soup(html)

    def opcoes(sufixo: str) -> list[OpcaoFiltro]:
        sel = sp.find("select", attrs={"name": re.compile(re.escape(sufixo) + "$")})
        if sel is None:
            return []
        return [
            OpcaoFiltro(valor=o.get("value", ""), rotulo=_txt(o) or "")
            for o in sel.find_all("option")
            if o.get("value") not in (None, "", "0")
        ]

    def valor(sufixo: str) -> int | None:
        el = sp.find("input", attrs={"name": re.compile(re.escape(sufixo) + "$")})
        return _int(el.get("value")) if el is not None else None

    return FiltrosSalasLivres(
        ano=valor(":inputAno"),
        periodo=valor(":inputPeriodo"),
        niveis=opcoes(":selectNivelTurma"),
        dias=opcoes(":selectDiaSemana"),
        turnos=opcoes(":selectTurno"),
        predios=opcoes(":selectPredio"),
    )


def parse_salas_livres(html: str | bytes) -> RelatorioSalasLivres:
    """Resultado do relatório (tabela predio | nome do predio | sala | capacidade | dia | inicio | fim | turno)."""
    sp = _soup(html)
    emitido = None
    m = re.search(r"Emitido em\s*(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2})", sp.get_text(" "))
    if m:
        emitido = _data_hora(m.group(1))
    salas: list[SalaLivre] = []
    for tabela in sp.find_all("table"):
        heads = [_norm(_txt(th) or "") for th in tabela.find_all(["th"])]
        if not heads:
            primeira = tabela.find("tr")
            heads = [_norm(_txt(td) or "") for td in primeira.find_all("td")] if primeira else []
        if "sala" not in heads:
            continue

        def i(*n: str) -> int | None:
            for k, h in enumerate(heads):
                if h in n:
                    return k
            return None

        ip, inome, isala, icap, idia, iini, ifim, itur = (
            i("predio"), i("nome do predio"), i("sala"), i("capacidade"), i("dia da semana", "dia"), i("inicio"), i("fim"), i("turno"),
        )
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue

            def c(k: int | None) -> str | None:
                return _txt(tds[k]) if k is not None and k < len(tds) else None

            sala = c(isala)
            if not sala or _norm(sala) == "sala":
                continue
            ini, fim = c(iini), c(ifim)
            salas.append(
                SalaLivre(
                    predio=c(ip),
                    predio_nome=c(inome),
                    sala=sala,
                    capacidade=_int(c(icap)),
                    dia_nome=c(idia),
                    inicio=ini[:5].zfill(5) if ini and re.match(r"\d", ini) else ini,
                    fim=fim[:5].zfill(5) if fim and re.match(r"\d", fim) else fim,
                    turno=c(itur),
                )
            )
        break
    return RelatorioSalasLivres(emitido_em=emitido, total=len(salas), salas=salas)


def resultado_salas_vazio(html: str | bytes) -> bool:
    return "Nenhuma turma foi encontrada" in (html.decode("iso-8859-1", "replace") if isinstance(html, bytes) else html)
