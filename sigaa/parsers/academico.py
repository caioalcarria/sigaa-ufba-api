"""Parsers das telas acadêmicas em HTML (comprovantes de matrícula, trancamentos,
atividades autônomas, suspensões/movimentações, listagens simples) e da declaração
de vínculo (PDF). Funções puras: recebem o HTML/PDF e devolvem modelos."""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from ..models.academico import (
    AtividadeAutonoma,
    AtividadeAutonomaDetalhe,
    AtividadesAutonomas,
    ComprovanteMatricula,
    DeclaracaoVinculo,
    FiltrosAvaliacao,
    LinhaAvaliacao,
    OpcaoSelect,
    ResultadoAvaliacao,
    GradeCelula,
    GrupoAtividadesAutonomas,
    GrupoProcessamento,
    HorarioSlot,
    ItemLista,
    ListaGenerica,
    MinhaPosicao,
    Movimentacao,
    ResultadoProcessamento,
    Suspensoes,
    Trancamento,
    TurmaMatricula,
    VagasCurso,
)

DIAS = "Segunda|Terça|Terca|Quarta|Quinta|Sexta|Sábado|Sabado|Domingo"
_RE_SLOT = re.compile(rf"(?P<local>.*?)\s*-\s*(?P<dia>{DIAS})\s+Hor[áa]rios?\s+(?P<ini>\d{{2}}:\d{{2}})\s*(?:às|as|a|-)\s*(?P<fim>\d{{2}}:\d{{2}})")
_RE_HORARIO = re.compile(r"^(?P<cod>[\dMTN ]+?)\s*\((?P<per>[^)]*)\)\s*$")


def _soup(html: str | bytes) -> BeautifulSoup:
    if isinstance(html, bytes):
        html = html.decode("iso-8859-1", errors="replace")
    return BeautifulSoup(html, "lxml")


def _t(el: Tag | None) -> str | None:
    if el is None:
        return None
    s = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
    return s or None


def _limpo(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip(" :")
    return s or None


def _data(s: str | None) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _datahora(s: str | None) -> datetime | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2}))?", s or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4) or 0), int(m.group(5) or 0))
    except ValueError:
        return None


def _int(s: str | None) -> int | None:
    m = re.search(r"-?\d+", s or "")
    return int(m.group(0)) if m else None


def mensagens_sigaa(html: str | bytes) -> list[str]:
    """Mensagens do painel de erros/avisos do SIGAA (ex.: 'Nenhuma solicitação...')."""
    sp = _soup(html)
    return [_t(li) for li in sp.select("#painel-erros li, ul.erros li, ul.info li, ul.warning li") if _t(li)]


def rotulo_valor(container: Tag | BeautifulSoup) -> dict[str, str]:
    """Pares 'Rótulo:' → valor de tabelas de visualização (th/td ou td/td)."""
    out: dict[str, str] = {}
    for tr in container.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        for i, c in enumerate(cells[:-1]):
            k = _t(c)
            if k and k.endswith(":"):
                v = _t(cells[i + 1])
                if v is not None and not (v.endswith(":") and len(v) < 40):
                    out.setdefault(k.rstrip(":").strip(), v)
    return out


def parse_horarios_local(texto: str | None) -> tuple[str | None, list[HorarioSlot]]:
    """'PAF 1 - 006 - Terça Horários 18:30 às 19:25PAF 1 - 006 - Terça Horários 19:25 às 20:20'
    → (local, [slots]). Quando não há horário detalhado, devolve (texto, [])."""
    if not texto:
        return None, []
    slots = [
        HorarioSlot(dia=m.group("dia").replace("Terca", "Terça").replace("Sabado", "Sábado"), inicio=m.group("ini"), fim=m.group("fim"), local=_limpo(m.group("local")))
        for m in _RE_SLOT.finditer(texto)
    ]
    if not slots:
        return _limpo(texto), []
    locais = sorted({s.local for s in slots if s.local})
    return (", ".join(locais) if locais else None), slots


def _parse_horario_cod(s: str | None) -> tuple[str | None, str | None]:
    s = _limpo(s)
    if not s:
        return None, None
    m = _RE_HORARIO.match(s)
    return (m.group("cod").strip(), m.group("per").strip()) if m else (s, None)


DIA_POR_DIGITO = {"1": "Domingo", "2": "Segunda", "3": "Terça", "4": "Quarta", "5": "Quinta", "6": "Sexta", "7": "Sábado"}
_RE_GRADE_JS = re.compile(r"getElementById\('(\d)_(\d+)'\);\s*if\s*\(elem\)\s*\{?\s*elem\.innerHTML\s*=\s*'([^']*)'")


def _parse_grade(tabela: Tag | None, html: str | None = None) -> list[GradeCelula]:
    """Grade semanal. O SIGAA desenha a tabela com '---' em spans id='<dia>_<slot>' e preenche
    via JavaScript (elem.innerHTML = 'MATC72'); lemos o script. <dia> segue o código de horário
    do SIGAA (2=segunda ... 7=sábado, 1=domingo)."""
    if tabela is None:
        return []
    faixa_por_span: dict[str, str] = {}
    for tr in tabela.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        faixa = _t(cells[0]) or ""
        for sp in tr.find_all("span", id=re.compile(r"^\d_\d+$")):
            faixa_por_span[sp["id"]] = faixa
    preenchido: dict[str, list[str]] = {}
    fonte = html if html is not None else str(tabela.find_parent() or tabela)
    for dia, slot, conteudo in _RE_GRADE_JS.findall(fonte):
        if conteudo.strip("- "):
            preenchido.setdefault(f"{dia}_{slot}", []).append(conteudo.strip())
    for sp in tabela.find_all("span", id=re.compile(r"^\d_\d+$")):
        v = _t(sp)
        if v and v.strip("- ") and sp["id"] not in preenchido:
            preenchido[sp["id"]] = [v]
    out = []
    for sid, conts in sorted(preenchido.items(), key=lambda kv: (int(kv[0].split("_")[1]), kv[0])):
        dia, slot = sid.split("_")
        out.append(GradeCelula(horario=faixa_por_span.get(sid, ""), dia=DIA_POR_DIGITO.get(dia, dia), slot=int(slot), conteudo=", ".join(dict.fromkeys(conts))))
    return out


# ------------------------------------------------- comprovante de inscrição
def parse_comprovante_inscricao(html: str | bytes) -> ComprovanteMatricula:
    """'Emitir Atestado de Matrícula' → COMPROVANTE DE INSCRIÇÃO SEMESTRAL EM COMPONENTES CURRICULARES."""
    sp = _soup(html)
    rel = sp.find(id="relatorio") or sp
    titulo = _t(rel.find("h3")) or "Comprovante de inscrição"
    ident = rel.find(id="identificacao") or rel
    kv = rotulo_valor(ident)
    per_txt = kv.get("Período Letivo") or ""
    m_per = re.search(r"(\d{4}\.\d)", per_txt)
    datas = re.findall(r"\d{2}/\d{2}/\d{4}", per_txt)
    emit = None
    m_emit = re.search(r"Emitido em\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", sp.get_text(" "))
    if m_emit:
        emit = _datahora(m_emit.group(1))
    turmas = []
    tab = rel.find(id="matriculas")
    if tab:
        for tr in tab.select("tbody tr"):
            cod = _t(tr.find(class_="codigo"))
            if not cod:
                continue
            local_txt = _t(tr.find(class_="local"))
            local_txt = re.sub(r"^Local:\s*", "", local_txt or "") or None
            local, slots = parse_horarios_local(local_txt)
            tipo = _t(tr.find(class_="tipoComponente"))
            hcod, hper = _parse_horario_cod(_t(tr.find(class_="horario")))
            turmas.append(
                TurmaMatricula(
                    codigo=cod,
                    componente=_t(tr.find(class_="componente")) or cod,
                    docentes=[d for d in (_t(x) for x in tr.find_all(class_="docente")) if d],
                    tipo=re.sub(r"^Tipo:\s*", "", tipo) if tipo else None,
                    local=local,
                    horarios=slots,
                    turma=_t(tr.find(class_="turma")),
                    situacao=_t(tr.find(class_="status")) or "",
                    horario_codigo=hcod,
                    horario_periodo=hper,
                )
            )
    total = None
    for h4 in rel.find_all("h4"):
        m = re.search(r"Turmas Matriculadas:\s*(\d+)", _t(h4) or "")
        if m:
            total = int(m.group(1))
    return ComprovanteMatricula(
        titulo=titulo,
        emitido_em=emit,
        periodo=m_per.group(1) if m_per else None,
        periodo_inicio=_data(datas[0]) if datas else None,
        periodo_fim=_data(datas[1]) if len(datas) > 1 else None,
        matricula=kv.get("Matrícula"),
        nome=kv.get("Nome"),
        curso=kv.get("Curso"),
        nivel=kv.get("Nível"),
        vinculo=kv.get("Vínculo"),
        turmas=turmas,
        total_matriculadas=total,
        grade=_parse_grade(rel.find(id="horario"), sp.decode() if hasattr(sp, "decode") else None),
    )


# ----------------------------------------- comprovante de solicitação de matrícula
_RE_COMP = re.compile(r"^(?P<cod>\S+)\s*-\s*(?P<nome>.*?)\s*-\s*(?P<ch>\d+)\s*h\b\s*(?P<rem>\(REMATR[ÍI]CULA\))?", re.I)


def parse_comprovante_solicitacao(html: str | bytes) -> ComprovanteMatricula:
    """'Ver Comprovante de Matrícula' / 'Ver Resultado do Processamento' (comprovante_solicitacoes.jsf)."""
    sp = _soup(html)
    rel = sp.find(id="relatorio") or sp
    h3 = _t(rel.find("h3")) or "Comprovante de Solicitação de Matrícula"
    m_num = re.search(r"N[°ºo]\s*(\d+)", h3)
    titulo = re.sub(r"\s*N[°ºo]\s*\d+", "", h3).strip()
    m_per = re.search(r"(\d{4}\.\d)", _t(rel.find("h4")) or "")
    vis = rel.find("table", class_="visualizacao")
    kv = rotulo_valor(vis) if vis else {}
    emit = None
    m_emit = re.search(r"Emitido em\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", sp.get_text(" "))
    if m_emit:
        emit = _datahora(m_emit.group(1))
    turmas = []
    tab = rel.find("table", class_="listagem")
    if tab:
        for tr in tab.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            comp_txt = _t(tds[0]) or ""
            m = _RE_COMP.match(comp_txt)
            local, slots = parse_horarios_local(_t(tds[2]))
            situ_el = tds[3]
            tid = None
            a = situ_el.find("a", onclick=True)
            if a:
                mt = re.search(r"idTurma=(\d+)", a["onclick"])
                tid = int(mt.group(1)) if mt else None
            turmas.append(
                TurmaMatricula(
                    turma_id=tid,
                    codigo=m.group("cod") if m else comp_txt.split(" ")[0],
                    componente=m.group("nome") if m else comp_txt,
                    carga_horaria=int(m.group("ch")) if m else None,
                    rematricula=bool(m and m.group("rem")) or "rematricula=true" in str(situ_el),
                    turma=re.sub(r"^Turma\s*", "", _t(tds[1]) or "") or None,
                    local=local,
                    horarios=slots,
                    situacao=_t(situ_el) or "",
                )
            )
    grade_tab = None
    for t in rel.find_all("table"):
        primeira = t.find("tr")
        if primeira and (_t(primeira) or "").startswith("Horários") and t.find("span", id=re.compile(r"^\d_\d+$")):
            grade_tab = t
    return ComprovanteMatricula(
        titulo=titulo,
        numero=m_num.group(1) if m_num else None,
        emitido_em=emit,
        periodo=m_per.group(1) if m_per else None,
        matricula=kv.get("Matrícula"),
        nome=kv.get("Discente"),
        curso=kv.get("Curso"),
        status=kv.get("Status"),
        vinculo=kv.get("Tipo"),
        turmas=turmas,
        total_matriculadas=sum(1 for t in turmas if t.situacao.upper().startswith(("DEFERID", "MATRICULAD"))),
        grade=_parse_grade(grade_tab, str(sp)),
    )


# ----------------------------------------------- resultado do processamento
def parse_resultado_processamento(html: str | bytes, turma_id: int, matricula: str | None, rematricula: bool = False) -> ResultadoProcessamento:
    sp = _soup(html)
    res = ResultadoProcessamento(turma_id=turma_id, rematricula=rematricula)
    kv = rotulo_valor(sp)
    h2 = next((h for h in sp.find_all("h2") if "Informa" in (_t(h) or "")), None)
    info = h2.find_next("table") if h2 else None
    if info:
        for tr in info.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) == 2 and _t(tds[0]):
                kv.setdefault(_t(tds[0]).rstrip(":"), _t(tds[1]) or "")
    comp = kv.get("Componente Curricular")
    if comp:
        m = re.match(r"(\S+)\s*-\s*(.*)", comp)
        res.componente_codigo, res.componente_nome = (m.group(1), m.group(2)) if m else (None, comp)
    res.turma = kv.get("Turma")
    res.horario_codigo = _parse_horario_cod(kv.get("Horário"))[0]
    res.capacidade = _int(kv.get("Capacidade"))
    for tab in sp.find_all("table"):
        texto = _t(tab) or ""
        cab = [(_t(c) or "") for c in (tab.find("tr").find_all(["th", "td"]) if tab.find("tr") else [])]
        if "Ingressantes" in texto and "Demais" in texto and not res.vagas:
            for tr in tab.find_all("tr"):
                tds = [(_t(c) or "") for c in tr.find_all(["td", "th"])]
                if len(tds) >= 3 and re.match(r"^-?\d+$", tds[-1]) and re.match(r"^-?\d+$", tds[-2]):
                    if tds[0].lower().startswith("total"):
                        res.vagas_total_reservadas, res.vagas_total_demais = int(tds[-2]), int(tds[-1])
                    else:
                        res.vagas.append(VagasCurso(curso=tds[0], reservadas_ingressantes=int(tds[-2]), demais_alunos=int(tds[-1])))
        elif any(c.startswith("Matr") for c in cab) and any("Situa" in c for c in cab):
            grupo = _t(tab.find("caption")) or _grupo_anterior(tab) or "?"
            linhas = []
            for tr in tab.find_all("tr")[1:]:
                tds = [(_t(c) or "") for c in tr.find_all("td")]
                if len(tds) >= 5 and re.match(r"^\d+$", tds[0]):
                    linhas.append(tds)
            mat = sum(1 for l in linhas if l[4].upper().startswith(("MATRICULAD", "DEFERID")))
            res.grupos.append(GrupoProcessamento(grupo=grupo, solicitantes=len(linhas), matriculados=mat, indeferidos=len(linhas) - mat))
            if matricula:
                for l in linhas:
                    if l[1] == matricula:
                        res.minha_posicao = MinhaPosicao(
                            grupo=grupo, posicao=int(l[0]), total_no_grupo=len(linhas), situacao=l[4], prioridade=l[5] if len(l) > 5 else None
                        )
    return res


def _grupo_anterior(tab: Tag) -> str | None:
    prev = tab.find_previous(["h3", "h4", "caption", "b", "strong", "td"])
    return _t(prev)


# ---------------------------------------------------------------- trancamentos
def parse_trancamentos(html: str | bytes) -> list[Trancamento]:
    sp = _soup(html)
    out: list[Trancamento] = []
    for tab in sp.find_all("table", class_="listagem"):
        for tr in tab.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) == 1 and out:
                txt = _t(tds[0]) or ""
                m = re.match(r"Motivo do Trancamento:\s*(.*)", txt)
                if m:
                    out[-1].motivo = m.group(1).strip() or None
                continue
            if len(tds) >= 5 and re.match(r"^\d{4}\.\d$", _t(tds[0]) or ""):
                comp = _t(tds[1]) or ""
                m = re.match(r"(\S+)\s*-\s*(.*)", comp)
                out.append(
                    Trancamento(
                        periodo=_t(tds[0]),
                        componente_codigo=m.group(1) if m else None,
                        componente_nome=m.group(2) if m else comp or None,
                        turma=_t(tds[2]),
                        status=_t(tds[3]) or "",
                        data_solicitacao=_data(_t(tds[4])),
                        data_visto_coordenador=_data(_t(tds[5])) if len(tds) > 5 else None,
                    )
                )
    return out


# ------------------------------------------------------ atividades autônomas
def parse_atividades_autonomas(html: str | bytes) -> AtividadesAutonomas:
    sp = _soup(html)
    tab = next((t for t in sp.find_all("table", class_="listagem") if "Atividades Aut" in (_t(t.find("caption")) or "")), None)
    if tab is None:
        return AtividadesAutonomas(total_registros=0, grupos=[])
    m_tot = re.search(r"\((\d+)\)", _t(tab.find("caption")) or "")
    grupos: list[GrupoAtividadesAutonomas] = []
    for tr in tab.select("tbody tr"):
        sub = tr.find("td", class_="subFormulario")
        if sub:
            grupos.append(GrupoAtividadesAutonomas(categoria=_t(sub) or "", registros=[]))
            continue
        cells = tr.find_all(["th", "td"])
        txt = _t(tr) or ""
        if "Carga Horária Total Aprovada" in txt:
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*h", txt)
            if grupos and m:
                grupos[-1].carga_horaria_aprovada = float(m.group(1).replace(",", "."))
            continue
        if len(cells) >= 5 and _data(_t(cells[0])):
            if not grupos:
                grupos.append(GrupoAtividadesAutonomas(categoria="", registros=[]))
            ch = re.search(r"(\d+(?:[.,]\d+)?)", _t(cells[3]) or "")
            a = tr.find("a", onclick=re.compile(r"'id'\s*:\s*'\d+'"))
            mid = re.search(r"'id'\s*:\s*'(\d+)'", a["onclick"]) if a else None
            reg = AtividadeAutonoma(
                id=int(mid.group(1)) if mid else None,
                categoria=grupos[-1].categoria,
                data=_data(_t(cells[0])),
                tipo=_t(cells[1]),
                descricao=_t(cells[2]),
                carga_horaria=float(ch.group(1).replace(",", ".")) if ch else None,
                status=_t(cells[4]),
            )
            grupos[-1].registros.append(reg)
    return AtividadesAutonomas(total_registros=int(m_tot.group(1)) if m_tot else None, grupos=grupos)


# --------------------------------------------------------- listagem genérica
def parse_listagem(html: str | bytes) -> ListaGenerica:
    """Qualquer tela 'table.listagem' simples (diploma digital, aproveitamentos, avaliações...)."""
    sp = _soup(html)
    msgs = mensagens_sigaa(html)
    tab = sp.find("table", class_="listagem") or next(
        (t for t in sp.find_all("table") if t.find("caption") and t.find("thead") and "Movimenta" not in (_t(t.find("caption")) or "")), None
    )
    titulo = _t(tab.find("caption")) if tab else None
    h2 = sp.find("h2")
    if not titulo and h2:
        titulo = re.sub(r"^Portal do Discente\s*>\s*", "", _t(h2) or "")
    itens: list[ItemLista] = []
    vazio_msg = None
    if tab:
        cab_tr = tab.find("thead").find("tr") if tab.find("thead") else tab.find("tr")
        cab = [(_t(c) or f"col{i}") for i, c in enumerate(cab_tr.find_all(["th", "td"]))] if cab_tr else []
        corpo = tab.find("tbody") or tab
        for tr in corpo.find_all("tr", recursive=False):
            cells = tr.find_all(["td", "th"], recursive=False)
            if tr is cab_tr or not cells:
                continue
            if len(cells) == 1:
                vazio_msg = vazio_msg or _t(cells[0])
                continue
            campos = {cab[i] if i < len(cab) else f"col{i}": _t(c) for i, c in enumerate(cells)}
            campos = {k: v for k, v in campos.items() if not k.startswith("col") or v}
            if any(campos.values()):
                itens.append(ItemLista(campos=campos))
    texto = sp.get_text(" ")
    m = re.search(r"(Nenhum[a]?\s[^.<\n]{3,120}\.?)", texto)
    mensagem = (msgs[0] if msgs else None) or vazio_msg or (m.group(1).strip() if m else None)
    return ListaGenerica(titulo=titulo, vazio=not itens, mensagem=mensagem if not itens else None, itens=itens)


def parse_suspensoes(html: str | bytes) -> Suspensoes:
    sp = _soup(html)
    movs: list[Movimentacao] = []
    for tab in sp.find_all("table"):
        if "Movimenta" not in (_t(tab.find("caption")) or ""):
            continue
        for tr in tab.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) == 1 and movs:
                movs[-1].observacao = _t(tds[0])
            elif len(tds) >= 3:
                movs.append(Movimentacao(tipo=_t(tds[0]) or "", periodo=_t(tds[1]), data=_datahora(_t(tds[2]))))
    lista = parse_listagem(html)
    if lista.vazio and not lista.mensagem:
        m = re.search(r"(Nenhuma Solicita[çc][ãa]o[^.]*\.)", sp.get_text(" "))
        lista.mensagem = m.group(1) if m else None
    return Suspensoes(solicitacoes=lista, movimentacoes=movs)


# ------------------------------------------------------- declaração de vínculo
_MESES = {m: i for i, m in enumerate(["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"], 1)}


def parse_declaracao_vinculo_texto(texto: str) -> DeclaracaoVinculo:
    corrido = re.sub(r"\s+", " ", texto)
    d = DeclaracaoVinculo(texto=texto.strip())
    m = re.search(r"que\s+([A-ZÀ-Ý][A-ZÀ-Ý'\s]+?)\s+é\s+alun[oa]", corrido)
    d.nome = m.group(1).strip() if m else None
    m = re.search(r"sob o n[úu]mero\s+(\d+)", corrido)
    d.matricula = m.group(1) if m else None
    m = re.search(r"no curso de\s+(.*?)\.\s", corrido)
    d.curso = m.group(1).strip() if m else None
    m = re.search(r"([A-ZÀ-Ý][\wÀ-ÿ ]+),\s*(\d{1,2}) de (\w+) de (\d{4})\.?", corrido)
    if m:
        d.local_data = m.group(0).strip()
        mes = _MESES.get(m.group(3).lower())
        if mes:
            d.emitido_em = date(int(m.group(4)), mes, int(m.group(2)))
    m = re.search(r"C[óo]digo de verifica[çc][ãa]o:\s*([0-9a-fA-F]{6,})", corrido)
    d.codigo_verificacao = m.group(1) if m else None
    m = re.search(r"(https?://\S+/documentos)", corrido)
    d.url_verificacao = m.group(1) if m else None
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]
    cab = []
    for l in linhas:
        if l.startswith("CNPJ") or re.match(r"^D\s?E\s?C\s?L", l):
            break
        cab.append(l)
    orgaos = [l for l in cab if l.isupper() and "UNIVERSIDADE" not in l and not re.match(r"^\d+$", l)]
    d.orgao_emissor = orgaos[-1] if orgaos else None
    return d


def parse_declaracao_vinculo_pdf(pdf: bytes) -> DeclaracaoVinculo:
    from .historico_pdf import extrair_texto

    return parse_declaracao_vinculo_texto("\n".join(extrair_texto(pdf)))


# ------------------------------------------------- avaliação institucional
def _opcoes(sel: Tag | None) -> list[OpcaoSelect]:
    if sel is None:
        return []
    return [
        OpcaoSelect(id=o.get("value", ""), nome=_t(o) or "")
        for o in sel.find_all("option")
        if o.get("value") not in (None, "", "0", "-1") and not (_t(o) or "").startswith("--")
    ]


def parse_filtros_avaliacao(html: str | bytes) -> FiltrosAvaliacao:
    sp = _soup(html)
    return FiltrosAvaliacao(
        departamentos=_opcoes(sp.find("select", attrs={"name": "form:escolha_relatorio"})),
        periodos=_opcoes(sp.find("select", attrs={"name": "form:anoPeriodo"})),
    )


def _f(s: str | None) -> float | None:
    try:
        return float((s or "").replace(",", "."))
    except ValueError:
        return None


def parse_resultado_avaliacao(html: str | bytes) -> ResultadoAvaliacao:
    sp = _soup(html)
    kv = rotulo_valor(sp)
    tab = next((t for t in sp.find_all("table") if t.find("th", string=re.compile("Docente"))), None)
    linhas: list[LinhaAvaliacao] = []
    publicadas = False
    if tab:
        for tr in tab.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            v = [_t(td) for td in tds]
            m = re.match(r"(\S+)\s*-\s*(.*)", v[1] or "")
            hcod, hper = _parse_horario_cod(v[3])
            notas = [_f(x) for x in v[5:9]] + [None] * 4
            publicadas = publicadas or any(n is not None for n in notas[:4])
            linhas.append(
                LinhaAvaliacao(
                    docente=v[0] or "",
                    componente_codigo=m.group(1) if m else None,
                    componente_nome=m.group(2) if m else v[1],
                    turma=v[2],
                    horario_codigo=hcod,
                    horario_periodo=hper,
                    discentes=_int(v[4]),
                    atuacao_docente_media=notas[0],
                    atuacao_docente_dp=notas[1],
                    autoavaliacao_media=notas[2],
                    autoavaliacao_dp=notas[3],
                )
            )
    return ResultadoAvaliacao(
        departamento=kv.get("Departamento"), periodo=kv.get("Ano-Período"), linhas=linhas, medias_publicadas=publicadas
    )


def parse_atividade_autonoma_detalhe(html: str | bytes, registro_id: int) -> AtividadeAutonomaDetalhe:
    sp = _soup(html)
    tab = sp.find("table", class_="visualizacao") or sp
    kv = rotulo_valor(tab)
    tipo = kv.pop("Tipo da Atividade Autônoma", None)
    m = re.search(r"\((\d+(?:[.,]\d+)?)\s*h\)\s*$", tipo or "")
    ch = re.search(r"(\d+(?:[.,]\d+)?)", kv.pop("Carga Horária Desenvolvida", "") or "")
    for k in ("Matrícula", "Nome"):
        kv.pop(k, None)
    return AtividadeAutonomaDetalhe(
        id=registro_id,
        tipo=re.sub(r"\s*\(\d+(?:[.,]\d+)?\s*h\)\s*$", "", tipo) if tipo else None,
        ch_maxima_tipo=float(m.group(1).replace(",", ".")) if m else None,
        comprovante=kv.pop("Comprovante da Atividade", None),
        carga_horaria=float(ch.group(1).replace(",", ".")) if ch else None,
        observacoes=kv.pop("Observações", None),
        status=kv.pop("Status", None),
        parecer_coordenador=kv.pop("Parecer do Coordenador", None),
        campos_extras=kv,
    )
