"""Parsers da área "consultas" (logada): Calendário Acadêmico e Consultas Gerais (curso,
componente, estrutura curricular, turma, unidade).

Funções PURAS (HTML → modelo), sem rede. Tolerantes: procuram por RÓTULO (sem acento,
sem caixa, sem ':'), nunca por posição fixa; campo ausente vira ``None``/``[]``.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from sigaa.models.consultas import (
    AlocacaoSala,
    Calendario,
    CalendarioResumo,
    CargaHorariaItem,
    ComponenteDaEstrutura,
    ComponenteDetalhe,
    ComponenteRef,
    ComponenteResumo,
    ContagemSituacao,
    CurriculoDoComponente,
    CursoConsulta,
    CursoOpcao,
    DeclaracaoPrazoMaximo,
    DocenteTurma,
    EquivalenciaHistorico,
    EstruturaDetalhe,
    EstruturaResumo,
    EventoCalendario,
    ExpressaoRequisito,
    HorarioAula,
    Intervalo,
    NivelEstrutura,
    Opcao,
    PrazosConclusao,
    ProcessamentoTurma,
    TurmaDetalhe,
    TurmaOferta,
    UnidadeConsulta,
    VagaReservada,
)

Html = str | bytes

# ================================================================ utilidades


def _soup(html: Html) -> BeautifulSoup:
    if isinstance(html, bytes):
        html = html.decode("iso-8859-1", errors="replace")
    return BeautifulSoup(html, "lxml")


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _txt(el: Tag | None) -> str:
    return _clean(el.get_text(" ")) if el is not None else ""


def _norm(s: str | None) -> str:
    """Chave de comparação: sem acento, minúsculo, sem pontuação final."""
    s = unicodedata.normalize("NFKD", _clean(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[\"'“”]", "", s.lower())
    return s.strip(" :.-")


def _ou_none(s: str | None) -> str | None:
    s = _clean(s)
    return s if s and s not in ("-", "--") and _norm(s) not in ("nao definido", "nao informado") else None


def _int(s: str | None) -> int | None:
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else None


def _data(s: str | None) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _intervalo(s: str | None) -> Intervalo:
    texto = _clean(s) or None
    datas = re.findall(r"\d{2}/\d{2}/\d{4}", texto or "")
    if not datas:
        return Intervalo(texto=texto, definido=False)
    return Intervalo(inicio=_data(datas[0]), fim=_data(datas[-1]) if len(datas) > 1 else None, definido=True, texto=texto)


def _sim_nao(s: str | None) -> bool | None:
    n = _norm(s)
    if n in ("sim", "s", "ativo", "ativa", "true"):
        return True
    if n in ("nao", "n", "inativo", "inativa", "false"):
        return False
    return None


def _id_onclick(onclick: str | None, chave: str = "id") -> int | None:
    m = re.search(rf"'{chave}'\s*:\s*'(\d+)'", onclick or "")
    return int(m.group(1)) if m else None


def _pares(raiz: Tag) -> list[tuple[str, Tag]]:
    """Pares (rótulo, célula) de linhas ``<tr><th>Rótulo</th><td>valor</td>`` (também th td th td...)."""
    out: list[tuple[str, Tag]] = []
    for tr in raiz.find_all("tr"):
        cels = tr.find_all(["th", "td"], recursive=False)
        for i, c in enumerate(cels[:-1]):
            if c.name == "th" and cels[i + 1].name == "td":
                out.append((_txt(c), cels[i + 1]))
    return out


def _mensagens(soup: BeautifulSoup) -> list[str]:
    return [_txt(e) for e in soup.select("ul.erros li, ul.info li, ul.warning li")] or [
        _txt(e) for e in soup.select(".erros, .info") if _txt(e)
    ]


def mensagens_sigaa(html: Html) -> list[str]:
    """Mensagens de erro/aviso que o SIGAA mostra no topo da tela (ex.: 'não possui um programa cadastrado')."""
    return [re.sub(r"\s*\(x\) fechar mensagens\s*", "", m) for m in _mensagens(_soup(html))]


def _cap(tabela: Tag | None) -> str:
    """Legenda PRÓPRIA da tabela (``tabela.caption`` acharia a de uma tabela aninhada)."""
    c = tabela.find("caption", recursive=False) if tabela is not None else None
    if c is None and tabela is not None:
        for filho in tabela.find_all(["thead", "tbody"], recursive=False):
            c = c or filho.find("caption", recursive=False)
    return _norm(c.get_text()) if c is not None else ""


def _tabela_por_caption(soup: BeautifulSoup, trecho: str) -> Tag | None:
    alvo = _norm(trecho)
    for cap in soup.find_all("caption"):
        if alvo in _norm(cap.get_text()):
            return cap.find_parent("table")
    return None


def opcoes_select(html: Html, nome: str) -> list[Opcao]:
    """Opções de um ``<select name=...>`` (sem a opção '-- SELECIONE --')."""
    sel = _soup(html).find("select", attrs={"name": nome})
    if sel is None:
        return []
    out = []
    for o in sel.find_all("option"):
        v = o.get("value", "")
        t = _clean(o.get_text())
        if v in ("", "0") and "SELECIONE" in t.upper():
            continue
        out.append(Opcao(id=v, nome=t))
    return out


# ================================================================ calendário


def parse_lista_calendarios(html: Html) -> list[CalendarioResumo]:
    soup = _soup(html)
    tabela = _tabela_por_caption(soup, "Lista de Calendários") or soup
    out: list[CalendarioResumo] = []
    ano = periodo = None
    for tr in tabela.find_all("tr"):
        if "secao" in (tr.get("class") or []):
            m = re.search(r"(\d{4})\s*[./-]\s*(\d+)", _txt(tr))
            ano, periodo = (int(m.group(1)), int(m.group(2))) if m else (None, None)
            continue
        link = tr.find("a", onclick=re.compile("jsfcljs"))
        cid = _id_onclick(link.get("onclick")) if link else None
        if cid is None or ano is None:
            continue
        tds = tr.find_all("td")
        tipo = _txt(tds[0]) if tds else ""
        out.append(CalendarioResumo(id=cid, ano=ano, periodo=periodo, tipo=tipo, ead="DISTANCIA" in _norm(tipo).upper()))
    return out


_CAL_CAMPOS = {
    "unidade responsavel": "unidade_responsavel",
    "nivel de ensino": "nivel",
    "vigente": "vigente",
    "ano - periodo de ferias vigente": "periodo_ferias_vigente",
    "ano - periodo das turmas na solicitacao": "periodo_turmas_solicitacao",
    "periodo letivo": "periodo_letivo",
    "periodo de ferias": "periodo_ferias",
    "ano/semestre": "ano_semestre",
}


def parse_calendario(html: Html, resumo: CalendarioResumo | None = None) -> Calendario:
    soup = _soup(html)
    tabela = _tabela_por_caption(soup, "Dados do Calendário") or soup.find("table", class_="visualizacao") or soup
    cal = Calendario()
    if resumo:
        cal.id, cal.ano, cal.periodo, cal.tipo = resumo.id, resumo.ano, resumo.periodo, resumo.tipo
    grupo = None
    for tr in tabela.find_all("tr"):
        sub = tr.find("td", class_="subFormulario")
        if sub is not None:
            grupo = _txt(sub) or None
            continue
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None:
            continue
        rotulo, valor = _txt(th).rstrip(":").strip(), _txt(td)
        campo = _CAL_CAMPOS.get(_norm(rotulo)) if grupo is None else None
        if campo == "ano_semestre":
            m = re.search(r"(\d{4})\s*[/.-]\s*(\d+)", valor)
            if m:
                cal.ano, cal.periodo = int(m.group(1)), int(m.group(2))
        elif campo == "vigente":
            cal.vigente = _sim_nao(valor)
        elif campo in ("periodo_letivo", "periodo_ferias"):
            setattr(cal, campo, _intervalo(valor))
        elif campo:
            setattr(cal, campo, valor or None)
        else:
            iv = _intervalo(valor)
            cal.eventos.append(
                EventoCalendario(rotulo=rotulo, grupo=grupo, inicio=iv.inicio, fim=iv.fim, definido=iv.definido, texto=iv.texto)
            )
    return cal


# ==================================================================== cursos


def _separa_unidade(nome: str) -> tuple[str, str | None]:
    if "/" in nome:
        a, b = nome.split("/", 1)
        return _clean(a), _clean(b) or None
    return nome, None


def parse_busca_cursos(html: Html) -> list[CursoConsulta]:
    soup = _soup(html)
    tabela = _tabela_por_caption(soup, "cursos encontrados")
    if tabela is None:
        return []
    out = []
    for tr in tabela.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        completo = _txt(tds[0])
        if not completo:
            continue
        nome, sigla = _separa_unidade(completo)
        coords: list[str] = []
        if len(tds) > 2:
            coords = [_clean(x) for x in tds[2].get_text("\n").split("\n") if _clean(x)]
        out.append(CursoConsulta(nome=nome, nome_completo=completo, unidade_sigla=sigla, nivel=_txt(tds[1]) or None, coordenadores=coords))
    return out


def parse_opcoes_cursos(html: Html, nome_select: str) -> list[CursoOpcao]:
    """Cursos do combo (``busca:curso`` em Estrutura, ``form:selectCurso`` em Turma)."""
    out = []
    for o in opcoes_select(html, nome_select):
        if not o.id.isdigit():
            continue
        partes = [p.strip() for p in o.nome.split(" - ")]
        nome, sigla = _separa_unidade(partes[0])
        out.append(
            CursoOpcao(
                id=int(o.id),
                nome=nome,
                unidade_sigla=sigla,
                municipio=partes[1] if len(partes) > 1 else None,
                grau=" - ".join(partes[2:]) or None if len(partes) > 2 else None,
                texto=o.nome,
            )
        )
    return out


# =============================================================== componentes


def parse_busca_componentes(html: Html) -> list[ComponenteResumo]:
    soup = _soup(html)
    out: list[ComponenteResumo] = []
    vistos: set[tuple] = set()
    # as linhas ficam dentro de um <form> no meio do <tbody>; o lxml às vezes as tira da tabela,
    # então procuramos qualquer linha com o link de ação do componente.
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
        link = tr.find("a", onclick=re.compile(r"'id(Componente)?'\s*:"))
        if link is None:
            continue
        cid = _id_onclick(link.get("onclick")) or _id_onclick(link.get("onclick"), "idComponente")
        codigo, nome = _txt(tds[0]), _txt(tds[1])
        chave = (cid, codigo)
        if not codigo or chave in vistos:
            continue
        vistos.add(chave)
        out.append(
            ComponenteResumo(
                id=cid, codigo=codigo, nome=nome, nivel=_txt(tds[2]) or None, carga_horaria=_int(_txt(tds[3])), tipo=_txt(tds[4]) or None
            )
        )
    return out


def _expressao(td: Tag | None) -> ExpressaoRequisito:
    if td is None:
        return ExpressaoRequisito()
    refs: list[ComponenteRef] = []
    for ac in td.find_all(["acronym", "abbr"]):
        cod = _txt(ac)
        nome = None
        t = ac.get("title") or ""
        if " - " in t:
            nome = _clean(t.split(" - ", 1)[1]) or None
        if cod and all(r.codigo != cod for r in refs):
            refs.append(ComponenteRef(codigo=cod, nome=nome))
    expr = _txt(td)
    expr = re.sub(r"\(\s+", "(", expr)
    expr = re.sub(r"\s+\)", ")", expr)
    if not refs:
        # expressão sem <acronym> (outras telas): extrai códigos no formato do SIGAA
        for cod in re.findall(r"\b[A-Z]{2,}[A-Z0-9/]*\d+[A-Z0-9]*\b", expr):
            if all(r.codigo != cod for r in refs):
                refs.append(ComponenteRef(codigo=cod))
    return ExpressaoRequisito(expressao=_ou_none(expr), componentes=refs)


def _ref_texto(s: str) -> ComponenteRef | None:
    s = _clean(s)
    if not s:
        return None
    if " - " in s:
        a, b = s.split(" - ", 1)
        return ComponenteRef(codigo=a.strip(), nome=b.strip() or None)
    return ComponenteRef(codigo=s)


def _cargas_horarias(soup: BeautifulSoup) -> tuple[list[CargaHorariaItem], int | None, int | None]:
    tabela = None
    for cap in soup.find_all("caption"):
        if _norm(cap.get_text()).startswith("cargas horarias"):
            tabela = cap.find_parent("table")
            break
    if tabela is None:
        return [], None, None
    itens: list[CargaHorariaItem] = []
    total = aula = None
    grupo = None
    for tr in tabela.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) == 1 and tds[0].get("colspan"):
            grupo = _txt(tds[0]) or None
            continue
        if len(tds) < 2:
            continue
        rot = tds[0]
        for pop in rot.select("div.popUp, span"):
            pop.decompose()
        rotulo = _txt(rot)
        horas = _int(_txt(tds[-1]))
        if not rotulo:
            continue
        n = _norm(rotulo)
        if n.startswith("total de carga horaria do componente"):
            total = horas
        elif n.startswith("total de carga horaria de aula"):
            aula = horas
        itens.append(CargaHorariaItem(rotulo=rotulo, horas=horas, grupo=grupo))
    return itens, total, aula


_COMP_CAMPOS = {
    "codigo": "codigo",
    "nome": "nome",
    "unidade responsavel": "unidade_responsavel",
    "tipo do componente curricular": "tipo",
    "tipo do componente": "tipo",
    "modalidade de educacao": "modalidade",
    "modalidade": "modalidade",
}


def parse_componente(html: Html, id_componente: int | None = None) -> ComponenteDetalhe:
    """Painel do componente (``/sigaa/graduacao/componente/view_painel.jsf?id=``) OU o
    'Relatório para impressão' da busca — os dois usam os mesmos rótulos. As seções exclusivas
    do relatório (equivalente de, pré-requisito de, histórico, currículos) também são lidas."""
    soup = _soup(html)
    comp = ComponenteDetalhe(id=id_componente)
    cargas, total, aula = _cargas_horarias(soup)
    comp.cargas_horarias, comp.carga_horaria_total, comp.carga_horaria_aula = cargas, total, aula

    # linhas de tabelas que NÃO são de pares rótulo→valor do componente
    especiais = ("cargas horarias", "outros componentes", "historico de equival", "curriculos")
    for tr in soup.find_all("tr"):
        tab = tr.find_parent("table")
        if tab is not None and (_cap(tab).startswith(especiais) or tab.get("id") == "listaCurriculosComponente"):
            continue
        cels = tr.find_all(["th", "td"], recursive=False)
        if len(cels) < 2 or cels[0].name != "th":
            continue
        rotulo, td = _txt(cels[0]).rstrip(":").strip(), cels[1]
        n = _norm(rotulo)
        if n in _COMP_CAMPOS:
            setattr(comp, _COMP_CAMPOS[n], _ou_none(_txt(td)))
        elif n.startswith("pre-requisito"):
            comp.pre_requisitos = _expressao(td)
        elif n.startswith("co-requisito"):
            comp.co_requisitos = _expressao(td)
        elif n.startswith("equivalencia"):
            comp.equivalencias = _expressao(td)
        elif n.startswith("ementa"):
            comp.ementa = _ou_none(_txt(td))
        elif rotulo:
            comp.outras_informacoes[rotulo] = _txt(td)

    # ementa no painel: <tr class="secao">Ementa/Descrição</tr><tr><td><p>...</p></td></tr>
    if comp.ementa is None:
        for tr in soup.find_all("tr", class_="secao"):
            if _norm(tr.get_text()).startswith("ementa"):
                nxt = tr.find_next_sibling("tr")
                if nxt is not None:
                    comp.ementa = _ou_none(_txt(nxt))
                break

    for t in soup.find_all("table"):
        cap = _cap(t)
        alvo = None
        if cap.startswith("outros componentes") and "equivalente" in cap:
            alvo = comp.equivalente_de
        elif cap.startswith("outros componentes") and "pre-requisito" in cap:
            alvo = comp.pre_requisito_de
        elif cap.startswith("outros componentes") and "co-requisito" in cap:
            alvo = comp.co_requisito_de
        if alvo is not None:
            for td in t.find_all("td"):
                r = _ref_texto(_txt(td))
                if r:
                    alvo.append(r)
        elif cap.startswith("historico de equival"):
            for tr in t.find_all("tr"):
                tds = tr.find_all("td", recursive=False)
                if len(tds) >= 2:
                    comp.historico_equivalencias.append(
                        EquivalenciaHistorico(
                            expressao=_expressao(tds[0]),
                            ativa=_sim_nao(_txt(tds[1])),
                            inicio_vigencia=_data(_txt(tds[2])) if len(tds) > 2 else None,
                            fim_vigencia=_data(_txt(tds[3])) if len(tds) > 3 else None,
                        )
                    )
        elif t.get("id") == "listaCurriculosComponente" or cap == "curriculos":
            for tr in t.find_all("tr"):
                tds = tr.find_all("td", recursive=False)
                if len(tds) < 3:
                    continue
                por_classe = {c: td for td in tds for c in (td.get("class") or [])}
                cod_cels = [td for td in tds if "colCodigo" in (td.get("class") or [])]
                comp.curriculos.append(
                    CurriculoDoComponente(
                        codigo=_txt(cod_cels[0] if cod_cels else tds[0]),
                        ano_periodo=_ou_none(_txt(cod_cels[1])) if len(cod_cels) > 1 else _ou_none(_txt(tds[1])),
                        matriz=_ou_none(_txt(por_classe.get("colMatriz", tds[2]))),
                        obrigatoria=_sim_nao(_txt(por_classe.get("colObg"))) if "colObg" in por_classe else None,
                        semestre=(_int(_txt(por_classe.get("colPeriodo"))) or None) if "colPeriodo" in por_classe else None,
                        ativo=_sim_nao(_txt(por_classe.get("colAtivo"))) if "colAtivo" in por_classe else None,
                    )
                )
    return comp


def mesclar_componente(base: ComponenteDetalhe, extra: ComponenteDetalhe) -> ComponenteDetalhe:
    """Completa o painel com o que só o relatório tem."""
    dados = base.model_dump()
    for k, v in extra.model_dump().items():
        if k == "outras_informacoes":
            ja = {_norm(x) for x in dados[k]}
            dados[k] = {**dados[k], **{x: y for x, y in v.items() if _norm(x) not in ja}}
        elif dados.get(k) in (None, [], {}) or (isinstance(dados.get(k), dict) and dados[k].get("expressao") is None and "componentes" in dados[k] and not dados[k]["componentes"]):
            dados[k] = v
    return ComponenteDetalhe.model_validate(dados)


# ================================================================ estruturas


def parse_busca_estruturas(html: Html) -> list[EstruturaResumo]:
    soup = _soup(html)
    tabela = _tabela_por_caption(soup, "Estruturas Curriculares Encontradas") or soup
    out: list[EstruturaResumo] = []
    for tr in tabela.find_all("tr"):
        link = tr.find("a", onclick=re.compile(r"detalhar"))
        if link is None:
            continue
        eid = _id_onclick(link.get("onclick"))
        tds = tr.find_all("td", recursive=False)
        if eid is None or len(tds) < 4:
            continue
        matriz = _txt(tds[2])
        inativa = bool(re.search(r"\(\s*inativa\s*\)", matriz, re.I))
        matriz = _clean(re.sub(r"\(\s*inativa\s*\)", "", matriz, flags=re.I))
        out.append(
            EstruturaResumo(
                id=eid, codigo=_txt(tds[0]), ano_periodo=_ou_none(_txt(tds[1])), matriz=matriz or None, ativa=not inativa, situacao=_ou_none(_txt(tds[3]))
            )
        )
    return out


def _horas(s: str | None) -> int | None:
    return _int(s)


def _semestre(nome: str) -> int | None:
    m = re.match(r"\s*(\d+)\s*[ºo°]", nome)
    return int(m.group(1)) if m else None


def _nome_ch(s: str) -> tuple[str, int | None]:
    m = re.match(r"(.*?)\s*-\s*(\d+)\s*h\s*$", _clean(s))
    return (m.group(1).strip(), int(m.group(2))) if m else (_clean(s), None)


def parse_estrutura_relatorio(html: Html, id_estrutura: int | None = None) -> EstruturaDetalhe:
    """'Relatório da Estrutura Curricular': cabeçalho + componentes por semestre (tipo/natureza)."""
    soup = _soup(html)
    est = EstruturaDetalhe(id=id_estrutura)
    for rotulo, td in _pares(soup):
        n, v = _norm(rotulo), _txt(td)
        if n == "codigo" and est.codigo is None:
            est.codigo = v or None
        elif n == "matriz curricular":
            est.matriz = v or None
        elif n == "unidade de vinculacao":
            est.unidade_vinculacao = v or None
        elif n == "municipio de funcionamento":
            est.municipio = v or None
        elif n.startswith("periodo letivo de entrada"):
            est.periodo_entrada_vigor = re.sub(r"\s*\.\s*", ".", v) or None
        elif n == "minimo":
            est.prazos.minimo = _int(v)
        elif n == "medio":
            est.prazos.medio = _int(v)
        elif n == "maximo":
            est.prazos.maximo = _int(v)
        elif n == "obrigatoria":
            est.ch_obrigatoria = _horas(v)
        elif n == "optativa":
            est.ch_optativa = _horas(v)
            m = re.search(r"Optativa Livre:\s*(\d+)", v, re.I)
            est.ch_optativa_livre = int(m.group(1)) if m else None
        elif n == "complementar":
            est.ch_complementar = _horas(v)
        elif n == "total" and est.ch_total is None:
            est.ch_total = _horas(v)

    nivel: NivelEstrutura | None = None
    for tr in soup.find_all("tr"):
        classes = tr.get("class") or []
        if "tituloRelatorio" in classes:
            nome = _txt(tr)
            nivel = NivelEstrutura(nome=nome, semestre=_semestre(nome))
            est.niveis.append(nivel)
            continue
        if nivel is None:
            continue
        tds = tr.find_all("td", recursive=False)
        if "componentes" in classes and len(tds) >= 2:
            nome, ch = _nome_ch(_txt(tds[1]))
            est_comp = ComponenteDaEstrutura(
                codigo=_txt(tds[0]),
                nome=nome,
                carga_horaria=ch,
                ch_detalhada=_ou_none(_txt(tds[2])) if len(tds) > 2 else None,
                tipo=_ou_none(_txt(tds[3])) if len(tds) > 3 else None,
                natureza=_ou_none(_txt(tds[4])) if len(tds) > 4 else None,
            )
            nivel.componentes.append(est_comp)
        elif "ch total" in _norm(tr.get_text()):
            nivel.carga_horaria_total = _int(tr.get_text().split(":", 1)[-1])
    return est


_ESTR_DET = {
    "carga horaria minima": "ch_total",
    "carga horaria optativa minima": "ch_optativa",
    "carga horaria complementar minima": "ch_complementar",
    "carga horaria maxima por periodo letivo": "ch_maxima_periodo",
    "carga horaria maxima de componentes eletivos": "ch_maxima_eletivos",
}


def parse_estrutura_detalhar(html: Html, id_estrutura: int | None = None) -> EstruturaDetalhe:
    """Tela 'Detalhar' da estrutura: cargas horárias extras e o id/modalidade de cada componente
    (``PainelComponente.show(<id>, ...)``). Os níveis vêm das abas ('1º Nível', 'Optativos'...)."""
    soup = _soup(html)
    est = EstruturaDetalhe(id=id_estrutura)
    for rotulo, td in _pares(soup):
        n, v = _norm(rotulo), _txt(td)
        if n == "codigo" and est.codigo is None:
            est.codigo = v or None
        elif n == "matriz curricular":
            est.matriz = v or None
        elif n.startswith("periodo letivo de entrada"):
            est.periodo_entrada_vigor = re.sub(r"\s*\.\s*", ".", v) or None
        elif n in _ESTR_DET:
            setattr(est, _ESTR_DET[n], _horas(v))
        elif n == "total" and est.ch_obrigatoria is None:
            est.ch_obrigatoria = _horas(v)
        elif n == "minimo":
            est.prazos.minimo = _int(v)
        elif n == "medio":
            est.prazos.medio = _int(v)
        elif n == "maximo":
            est.prazos.maximo = _int(v)
        elif re.search(r"\d+\s*h", v) and ("carga horaria" in n or n.startswith("subtotal")):
            est.outras_cargas[_clean(rotulo).rstrip(":")] = _horas(v)

    for tabela in soup.find_all("table", class_="rich-table"):
        titulo = tabela.find_previous("span", style=re.compile("bold"))
        nome = _txt(titulo) if titulo else ""
        nivel = NivelEstrutura(nome=nome, semestre=_semestre(nome))
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            lab = tr.find("label", onclick=re.compile(r"PainelComponente\.show"))
            if lab is None or len(tds) < 2:
                continue
            m = re.search(r"show\((\d+)", lab["onclick"])
            nome_c, ch = _nome_ch(_txt(tds[1]))
            nivel.componentes.append(
                ComponenteDaEstrutura(
                    id=int(m.group(1)) if m else None,
                    codigo=_txt(lab),
                    nome=nome_c,
                    carga_horaria=ch,
                    modalidade=_ou_none(_txt(tds[2])) if len(tds) > 2 else None,
                )
            )
        if nivel.componentes:
            est.niveis.append(nivel)
    return est


def mesclar_estrutura(relatorio: EstruturaDetalhe, detalhar: EstruturaDetalhe | None) -> EstruturaDetalhe:
    """Relatório (semestres/natureza) + Detalhar (ids, modalidade, CH extras)."""
    if detalhar is None:
        return relatorio
    if not relatorio.niveis:
        relatorio.niveis = detalhar.niveis
    ids = {c.codigo: c for n in detalhar.niveis for c in n.componentes}
    for n in relatorio.niveis:
        for c in n.componentes:
            d = ids.get(c.codigo)
            if d:
                c.id = c.id or d.id
                c.modalidade = c.modalidade or d.modalidade
    for campo in ("codigo", "matriz", "periodo_entrada_vigor", "ch_total", "ch_obrigatoria", "ch_optativa", "ch_complementar", "ch_maxima_periodo", "ch_maxima_eletivos"):
        if getattr(relatorio, campo) is None:
            setattr(relatorio, campo, getattr(detalhar, campo))
    for campo in ("minimo", "medio", "maximo"):
        if getattr(relatorio.prazos, campo) is None:
            setattr(relatorio.prazos, campo, getattr(detalhar.prazos, campo))
    relatorio.outras_cargas = {**detalhar.outras_cargas, **relatorio.outras_cargas}
    return relatorio


def parse_declaracao_prazo(html: Html) -> DeclaracaoPrazoMaximo:
    soup = _soup(html)
    texto = _txt(soup.body or soup)
    dec = DeclaracaoPrazoMaximo()
    m = re.search(r"Declaramos.*?per[ií]odos letivos regulares\s*\.?", texto, re.S)
    dec.texto = _clean(m.group(0)) if m else None
    corpo = dec.texto or texto
    if m := re.search(r"Curso de\s+(.*?)\s+-\s+Turno\s+(.*?)\s+-\s+Modalidade\s+(.*?)\s+é de", corpo):
        dec.curso, dec.turno, dec.modalidade = m.group(1), m.group(2), m.group(3)
    if m := re.search(r"é de\s+(\d+)", corpo):
        dec.prazo_maximo = int(m.group(1))
    if m := re.search(r"identificador\s+(\w+)", texto):
        dec.identificador = m.group(1)
    if m := re.search(r"c[óo]digo de verifica[çc][ãa]o\s+(\w+)", texto, re.I):
        dec.codigo_verificacao = m.group(1)
    return dec


# ==================================================================== turmas

_DIAS = {1: "Domingo", 2: "Segunda", 3: "Terça", 4: "Quarta", 5: "Quinta", 6: "Sexta", 7: "Sábado"}
# grade horária da UFBA (aulas de 55 min)
_GRADE = {
    "M": ["07:00", "07:55", "08:50", "09:45", "10:40", "11:35", "12:30"],
    "T": ["13:00", "13:55", "14:50", "15:45", "16:40", "17:35", "18:30"],
    "N": ["18:30", "19:25", "20:20", "21:15", "22:10"],
}


def decodificar_horario(codigo: str | None) -> list[HorarioAula]:
    """'35T12' → (3=terça, 5=quinta) × (T1 13:00, T2 13:55); aceita vários blocos ('3N34 6N3')."""
    out: list[HorarioAula] = []
    for dias, turno, aulas in re.findall(r"\b([1-7]+)([MTN])(\d+)\b", codigo or ""):
        for d in dias:
            for a in aulas:
                grade = _GRADE[turno]
                i = int(a) - 1
                ini = grade[i] if 0 <= i < len(grade) else None
                fim = grade[i + 1] if 0 <= i + 1 < len(grade) else None
                out.append(HorarioAula(dia=_DIAS[int(d)], dia_numero=int(d), turno=turno, aula=int(a), inicio=ini, fim=fim))
    return out


_RE_ALOC = re.compile(
    r"(?P<local>.+?)\s+-\s+(?P<dia>Segunda|Terça|Terca|Quarta|Quinta|Sexta|Sábado|Sabado|Domingo)\s+Hor[áa]rios?\s+(?P<ini>\d{1,2}:\d{2})\s+[àa]s\s+(?P<fim>\d{1,2}:\d{2})",
    re.I,
)


def _alocacoes(texto: str) -> list[AlocacaoSala]:
    out = []
    for m in _RE_ALOC.finditer(_clean(texto)):
        out.append(AlocacaoSala(local=_clean(m.group("local")).strip(" -"), dia=m.group("dia"), inicio=m.group("ini"), fim=m.group("fim")))
    return out


def _docentes(texto: str) -> list[DocenteTurma]:
    out = []
    for m in re.finditer(r"([^,()]+?)\s*\((\d+)\s*h\)", texto):
        nome = re.sub(r"^(?:e|E)\s+", "", _clean(m.group(1)))
        out.append(DocenteTurma(nome=nome, carga_horaria=int(m.group(2))))
    if not out:
        for nome in re.split(r",|\n", texto):
            if _clean(nome) and "definir" not in nome.lower():
                out.append(DocenteTurma(nome=_clean(nome)))
    return out


def _horario_e_periodo(texto: str) -> tuple[str | None, Intervalo | None]:
    texto = _clean(texto)
    if not texto:
        return None, None
    m = re.match(r"(.*?)\s*\((\d{2}/\d{2}/\d{4}.*?)\)\s*$", texto)
    if m:
        return (_ou_none(m.group(1)), _intervalo(m.group(2)))
    return texto, None


def parse_busca_turmas(html: Html) -> list[TurmaOferta]:
    soup = _soup(html)
    tabela = soup.find("table", id="lista-turmas") or _tabela_por_caption(soup, "Turmas Encontradas")
    if tabela is None:
        return []
    # mapeia colunas pelo cabeçalho (algumas telas escondem Docente/Horário)
    cab = [_norm(th.get_text()) for th in tabela.select("thead th")]

    def col(*nomes: str) -> int | None:
        for i, c in enumerate(cab):
            if any(c.startswith(n) for n in nomes):
                return i
        return None

    c_doc, c_tipo, c_mod, c_sit = col("docente"), col("tipo"), col("modalidade"), col("situacao")
    c_hor, c_loc, c_mat = col("horario"), col("local"), col("mat")
    out: list[TurmaOferta] = []
    comp_cod = comp_nome = nivel = None
    for tr in tabela.find_all("tr"):
        classes = tr.get("class") or []
        if "destaque" in classes:
            t = _txt(tr)
            m = re.match(r"(.*?)\s+-\s+(.*?)(?:\s*\(([^)]*)\))?\s*$", t)
            if m:
                comp_cod, comp_nome, nivel = m.group(1), _clean(m.group(2)), m.group(3)
            else:
                comp_cod, comp_nome, nivel = None, t, None
            continue
        if "no-hover" in classes:
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
        a = tr.find("a", onclick=re.compile(r"PainelTurma\.show"))
        tid = int(re.search(r"show\((\d+)", a["onclick"]).group(1)) if a else None
        ano = periodo = None
        if m := re.search(r"(\d{4})\.(\d+)", _txt(tds[0])):
            ano, periodo = int(m.group(1)), int(m.group(2))
        cod_turma = re.sub(r"(?i)^turma\s*", "", _txt(tds[1])) or None

        def cel(i: int | None) -> str:
            return _txt(tds[i]) if i is not None and i < len(tds) else ""

        horario, per = _horario_e_periodo(cel(c_hor))
        local = cel(c_loc)
        mat = re.search(r"(\d+)\s*/\s*(\d+)", cel(c_mat))
        out.append(
            TurmaOferta(
                id=tid,
                componente_codigo=comp_cod,
                componente_nome=comp_nome,
                nivel=nivel,
                ano=ano,
                periodo=periodo,
                codigo_turma=cod_turma,
                docentes=_docentes(cel(c_doc)),
                tipo=_ou_none(cel(c_tipo)),
                modalidade=_ou_none(cel(c_mod)),
                situacao=_ou_none(cel(c_sit)),
                horario_codigo=horario,
                horarios=decodificar_horario(horario),
                periodo_aulas=per,
                local=_ou_none(local),
                alocacoes=_alocacoes(local),
                matriculados=int(mat.group(1)) if mat else None,
                capacidade=int(mat.group(2)) if mat else None,
            )
        )
    return out


def parse_turma_painel(html: Html, id_turma: int | None = None) -> TurmaDetalhe:
    """Painel 'Informações da Turma' (``/sigaa/graduacao/turma/view_painel.jsf?id=``)."""
    soup = _soup(html)
    t = TurmaDetalhe(id=id_turma)
    for rotulo, td in _pares(soup):
        n, v = _norm(rotulo), _txt(td)
        if n.startswith("ano") and "periodo" in n:
            if m := re.search(r"(\d{4})\.(\d+)", v):
                t.ano, t.periodo = int(m.group(1)), int(m.group(2))
        elif n == "periodo letivo":
            t.periodo_letivo = _intervalo(v)
        elif n.startswith("componente e turma"):
            m = re.match(r"(.*?)\s+-\s+(.*)\s+-\s+Turma\s+(\S+)", v)
            if m:
                t.componente_codigo, t.componente_nome, t.codigo_turma = m.group(1), m.group(2), m.group(3)
            else:
                t.componente_nome = v or None
        elif n == "tipo do componente":
            t.tipo_componente = _ou_none(v)
        elif n == "carga horaria":
            t.carga_horaria = _int(v)
        elif n == "tipo da turma":
            t.tipo_turma = _ou_none(v)
        elif n.startswith("local e horario"):
            t.local_horario = _ou_none(v)
            cod = re.search(r"\b[1-7]+[MTN]\d+(?:\s+[1-7]+[MTN]\d+)*", v)
            t.horario_codigo = cod.group(0) if cod else None
            t.horarios = decodificar_horario(t.horario_codigo)
            t.alocacoes = _alocacoes(v)
        elif n == "capacidade":
            t.capacidade = _int(v)
        elif n == "totais":
            if m := re.search(r"(\d+)\s+solicita[çc][õo]es realizadas na matr[íi]cula", v, re.I):
                t.solicitacoes_matricula = int(m.group(1))
            if m := re.search(r"(\d+)\s+solicita[çc][õo]es realizadas na rematr[íi]cula", v, re.I):
                t.solicitacoes_rematricula = int(m.group(1))
            if m := re.search(r"(\d+)\s+alunos? matriculados?", v, re.I):
                t.matriculados = int(m.group(1))
    # Professores (n) e Vagas Reservadas: sub-tabelas com <tr class="secao"> de cabeçalho
    for sec in soup.find_all("tr", class_="secao"):
        n = _norm(sec.get_text())
        linhas = sec.find_next_siblings("tr")
        if n.startswith("professores"):
            for tr in linhas:
                t.docentes.extend(_docentes(_txt(tr)))
        elif n.startswith("vagas reservadas"):
            for tr in linhas:
                tds = tr.find_all("td", recursive=False)
                txt = _txt(tr)
                m = re.search(r"\((\d+)\s*/\s*(\d+)\)", txt)
                if m:
                    curso = _txt(tds[0]) if len(tds) > 1 else _clean(txt[: m.start()])
                    t.vagas_reservadas.append(VagaReservada(curso=curso, ingressantes=int(m.group(1)), demais=int(m.group(2)), texto=txt))
    return t


def parse_processamento(html: Html, id_turma: int | None = None, rematricula: bool = False) -> ProcessamentoTurma:
    """Resultado do processamento — só AGREGADOS (nenhum nome/matrícula de aluno sai daqui)."""
    soup = _soup(html)
    p = ProcessamentoTurma(id_turma=id_turma, rematricula=rematricula)
    info = None
    for h2 in soup.find_all(["h2", "h3"]):
        if "turma" in _norm(h2.get_text()):
            info = h2.find_next("table")
            break
    for tr in (info.find_all("tr") if info else []):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 2:
            continue
        n, v = _norm(tds[0].get_text()), _txt(tds[1])
        if n.startswith("componente"):
            p.componente = v or None
        elif n == "turma":
            p.codigo_turma = v or None
        elif n == "horario":
            p.horario = v or None
        elif n == "capacidade":
            p.capacidade = _int(v)
    reservas = soup.find("table", class_="reservas")
    for tr in (reservas.find_all("tr") if reservas else []):
        tds = tr.find_all("td", recursive=False)
        if len(tds) >= 3 and "total" not in (tr.get("class") or []):
            p.vagas_reservadas.append(VagaReservada(curso=_txt(tds[0]), ingressantes=_int(_txt(tds[1])), demais=_int(_txt(tds[2])), texto=_txt(tr)))
    contagem: dict[tuple[str, str], int] = {}
    for tabela in soup.find_all("table"):
        cabs = [_norm(th.get_text()) for th in tabela.find_all("th")]
        if "situacao" not in cabs:
            continue
        i_sit = cabs.index("situacao")
        cap_el = tabela.find("caption", recursive=False)
        grupo = _txt(cap_el) if cap_el is not None else ""
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) > i_sit:
                sit = _txt(tds[i_sit])
                if sit:
                    contagem[(grupo, sit)] = contagem.get((grupo, sit), 0) + 1
    p.por_situacao = [ContagemSituacao(grupo=g, situacao=s, quantidade=q) for (g, s), q in contagem.items()]
    p.total_solicitacoes = sum(contagem.values())
    return p


# ================================================================== unidades


def parse_busca_unidades(html: Html) -> list[UnidadeConsulta]:
    soup = _soup(html)
    tabela = _tabela_por_caption(soup, "Lista de Unidades")
    if tabela is None:
        return []
    cab = [_norm(td.get_text()) for td in (tabela.find("thead") or tabela).find("tr").find_all(["td", "th"])]

    def col(nome: str, padrao: int) -> int:
        return next((i for i, c in enumerate(cab) if c.startswith(nome)), padrao)

    i_cod, i_nome, i_sigla, i_tipo, i_ativa = col("codigo", 0), col("unidade", 1), col("sigla", 2), col("tipo", 3), col("ativa", 4)
    out = []
    for tr in tabela.find_all("tr"):
        if tr.find_parent("thead"):
            continue
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        link = tr.find("a", onclick=re.compile("jsfcljs"))

        def cel(i: int) -> str:
            return _txt(tds[i]) if i < len(tds) else ""

        if not cel(i_nome):
            continue
        out.append(
            UnidadeConsulta(
                id=_id_onclick(link.get("onclick")) if link else None,
                codigo=_ou_none(cel(i_cod)),
                nome=cel(i_nome),
                sigla=_ou_none(cel(i_sigla)),
                tipo=_ou_none(cel(i_tipo)),
                ativa=_sim_nao(cel(i_ativa)) if "ativa" in cab else None,
            )
        )
    return out


def emitido_em(html: Html) -> datetime | None:
    """'Emitido em 19/10/2026 19:51' dos relatórios."""
    m = re.search(r"Emitido em\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", _txt(_soup(html)))
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d/%m/%Y %H:%M") if m else None
