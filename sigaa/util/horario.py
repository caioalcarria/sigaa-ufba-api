"""Decodificador do código de horário do SIGAA e montagem da grade semanal / iCalendar.

O SIGAA escreve o horário de uma turma como ``<dias><turno><slots>``, separados por espaço:

* ``46N12``      → quarta e sexta, noite, horários 1 e 2 (18:30–20:20)
* ``2N1234 4N4`` → segunda N1..N4 (18:30–22:10) e quarta N4 (21:15–22:10)
* ``7T2  7T3``   → sábado T2 e T3 (o SIGAA às vezes repete o dia em blocos separados)

Dias: 1=domingo, 2=segunda ... 7=sábado. Turnos: M (manhã), T (tarde), N (noite).
O texto pode vir com o período das aulas: ``46N12 (19/08/2026 - 19/12/2026)``.

A tabela de horas é a da UFBA, conferida no "Comprovante de Matrícula" do SIGAA (grade
Seg..Sáb × 07:00..22:10) e nos locais detalhados ("Terça Horários 18:30 às 19:25").
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from sigaa.models.portal import (
    AulaGrade,
    AulaSemanal,
    DiaGrade,
    GradeHoraria,
    Horario,
    LocalAula,
    SlotHorario,
    SlotTabela,
    TabelaHorarios,
    Turma,
    Turno,
)

# Tabela real da UFBA (slots de 55 min).
TABELA_UFBA: dict[str, list[tuple[str, str]]] = {
    "M": [("07:00", "07:55"), ("07:55", "08:50"), ("08:50", "09:45"), ("09:45", "10:40"), ("10:40", "11:35"), ("11:35", "12:30")],
    "T": [("13:00", "13:55"), ("13:55", "14:50"), ("14:50", "15:45"), ("15:45", "16:40"), ("16:40", "17:35"), ("17:35", "18:30")],
    "N": [("18:30", "19:25"), ("19:25", "20:20"), ("20:20", "21:15"), ("21:15", "22:10")],
}

DIAS = {1: "Domingo", 2: "Segunda", 3: "Terça", 4: "Quarta", 5: "Quinta", 6: "Sexta", 7: "Sábado"}
_DIA_ISO = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 1: 7}
_ICS_DIA = {1: "SU", 2: "MO", 3: "TU", 4: "WE", 5: "TH", 6: "FR", 7: "SA"}
_ORDEM_TURNO = {"M": 0, "T": 1, "N": 2}

_RE_TOKEN = re.compile(r"^([1-7]+)([MTN])([1-9]+)$", re.I)
_RE_PERIODO = re.compile(r"\(\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\s*\)")
_RE_LOCAL = re.compile(
    r"(?P<local>.+?)\s*-\s*(?P<dia>Segunda|Ter[cç]a|Quarta|Quinta|Sexta|S[aá]bado|Domingo)(?:-feira)?\s+Hor[aá]rios?\s+"
    r"(?P<ini>\d{1,2}:\d{2})\s*(?:às|as|a|-)\s*(?P<fim>\d{1,2}:\d{2})",
    re.I,
)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


_DIA_POR_NOME = {_sem_acento(v): k for k, v in DIAS.items()}


def dia_por_nome(nome: str) -> int | None:
    """'Terça', 'terca', 'Terça-feira', 'Sabado' → número SIGAA (3, 7...)."""
    n = _sem_acento(nome).replace("-feira", "").strip()
    return _DIA_POR_NOME.get(n)


def _data(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def _min(h: str) -> int:
    hh, mm = h.split(":")
    return int(hh) * 60 + int(mm)


def slot(turno: str, numero: int, tabela: dict[str, list[tuple[str, str]]] = TABELA_UFBA) -> SlotHorario:
    t = turno.upper()
    faixa = tabela.get(t, [])
    ini, fim = faixa[numero - 1] if 0 < numero <= len(faixa) else (None, None)
    return SlotHorario(turno=Turno(t), slot=numero, codigo=f"{t}{numero}", inicio=ini, fim=fim)


def tabela_horarios(tabela: dict[str, list[tuple[str, str]]] = TABELA_UFBA) -> TabelaHorarios:
    slots = [
        SlotTabela(codigo=f"{t}{i}", turno=Turno(t), slot=i, inicio=a, fim=b)
        for t in ("M", "T", "N")
        for i, (a, b) in enumerate(tabela.get(t, []), start=1)
    ]
    return TabelaHorarios(
        instituicao="UFBA",
        fonte="Grade do Comprovante de Matrícula do SIGAA UFBA (Seg..Sáb × 07:00..22:10) e locais detalhados das turmas.",
        slots=slots,
        dias=DIAS,
    )


def decodificar(texto: str | None, tabela: dict[str, list[tuple[str, str]]] = TABELA_UFBA) -> Horario | None:
    """Decodifica o horário do SIGAA. Nunca levanta exceção: o que não entender vai em ``nao_reconhecido``."""
    if texto is None:
        return None
    cru = re.sub(r"\s+", " ", texto).strip()
    if not cru:
        return None
    data_ini = data_fim = None
    m = _RE_PERIODO.search(cru)
    if m:
        data_ini, data_fim = _data(m.group(1)), _data(m.group(2))
    codigo = _RE_PERIODO.sub(" ", cru)
    codigo = re.sub(r"\s+", " ", codigo).strip()

    # (dia, turno) -> set(slots)
    mapa: dict[tuple[int, str], set[int]] = {}
    ruins: list[str] = []
    for tok in codigo.replace(",", " ").replace(";", " ").split():
        mt = _RE_TOKEN.match(tok)
        if not mt:
            ruins.append(tok)
            continue
        dias, turno, slots = mt.group(1), mt.group(2).upper(), mt.group(3)
        for d in dias:
            mapa.setdefault((int(d), turno), set()).update(int(s) for s in slots)

    aulas: list[AulaSemanal] = []
    total_slots = 0
    total_min = 0
    min_ok = True
    for (dia, turno), nums in mapa.items():
        ordenados = sorted(nums)
        total_slots += len(ordenados)
        # quebra em blocos contínuos (N1 N2 | N4)
        blocos: list[list[int]] = []
        for n in ordenados:
            if blocos and n == blocos[-1][-1] + 1:
                blocos[-1].append(n)
            else:
                blocos.append([n])
        for b in blocos:
            s_ini, s_fim = slot(turno, b[0], tabela), slot(turno, b[-1], tabela)
            minutos = None
            if s_ini.inicio and s_fim.fim:
                minutos = _min(s_fim.fim) - _min(s_ini.inicio)
            for n in b:
                sl = slot(turno, n, tabela)
                if sl.inicio and sl.fim:
                    total_min += _min(sl.fim) - _min(sl.inicio)
                else:
                    min_ok = False
            aulas.append(
                AulaSemanal(
                    dia=dia,
                    dia_nome=DIAS[dia],
                    dia_iso=_DIA_ISO[dia],
                    turno=Turno(turno),
                    slots=b,
                    codigos=[f"{turno}{n}" for n in b],
                    inicio=s_ini.inicio,
                    fim=s_fim.fim,
                    minutos=minutos,
                )
            )
    aulas.sort(key=lambda a: (a.dia_iso, _ORDEM_TURNO[a.turno.value], a.slots[0]))
    return Horario(
        texto=texto.strip(),
        codigo=codigo,
        data_inicio=data_ini,
        data_fim=data_fim,
        aulas=aulas,
        aulas_por_semana=total_slots,
        minutos_por_semana=total_min if (min_ok and total_slots) else None,
        reconhecido=not ruins and bool(aulas),
        nao_reconhecido=ruins,
    )


def separar_locais(texto: str | None) -> tuple[str | None, list[LocalAula]]:
    """'PAF 1 - 006 -  Terça Horários  18:30 às 19:25PAF 1 - 006 -  Terça Horários  19:25 às 20:20'
    → ('PAF 1 - 006', [LocalAula(...), LocalAula(...)]).  Texto sem detalhamento volta como está."""
    if not texto:
        return None, []
    t = re.sub(r"\s+", " ", texto).strip()
    if not t:
        return None, []
    locais: list[LocalAula] = []
    pos = 0
    for m in _RE_LOCAL.finditer(t):
        local = m.group("local").strip(" -")
        locais.append(
            LocalAula(
                local=local,
                dia_nome=m.group("dia").capitalize(),
                dia=dia_por_nome(m.group("dia")),
                inicio=m.group("ini").zfill(5),
                fim=m.group("fim").zfill(5),
            )
        )
        pos = m.end()
    if not locais:
        return t, []
    resto = t[pos:].strip(" -")
    nomes: list[str] = []
    for lc in locais:
        if lc.local not in nomes:
            nomes.append(lc.local)
    if resto:
        nomes.append(resto)
    return ", ".join(nomes), locais


# ------------------------------------------------------------------ grade
def _local_do_bloco(turma: Turma, aula: AulaSemanal) -> str | None:
    salas = [
        lc.local
        for lc in turma.locais
        if lc.dia == aula.dia and lc.inicio and aula.inicio and aula.fim and aula.inicio <= lc.inicio < aula.fim
    ]
    unicos = list(dict.fromkeys(salas))
    return ", ".join(unicos) if unicos else turma.local


def montar_grade(turmas: list[Turma], periodo: str | None = None) -> GradeHoraria:
    aulas: list[AulaGrade] = []
    sem: list[str] = []
    inicios, fins = [], []
    ocupado: dict[tuple[int, str], str] = {}
    conflitos: list[str] = []
    for t in turmas:
        h = t.horario
        if not h or not h.aulas:
            sem.append(f"{t.codigo or ''} {t.nome}".strip())
            continue
        if h.data_inicio:
            inicios.append(h.data_inicio)
        if h.data_fim:
            fins.append(h.data_fim)
        for a in h.aulas:
            for cod in a.codigos:
                chave = (a.dia, cod)
                nome = t.codigo or t.nome
                if chave in ocupado and ocupado[chave] != nome:
                    conflitos.append(f"{DIAS[a.dia]} {cod}: {ocupado[chave]} × {nome}")
                ocupado.setdefault(chave, nome)
            aulas.append(
                AulaGrade(
                    dia=a.dia,
                    dia_nome=a.dia_nome,
                    inicio=a.inicio,
                    fim=a.fim,
                    turno=a.turno,
                    codigos=a.codigos,
                    turma_id=t.turma_id,
                    codigo=t.codigo,
                    nome=t.nome,
                    turma=t.turma,
                    local=_local_do_bloco(t, a),
                )
            )
    aulas.sort(key=lambda a: (_DIA_ISO[a.dia], a.inicio or "99:99"))
    dias_usados = sorted({a.dia for a in aulas} | {2, 3, 4, 5, 6}, key=lambda d: _DIA_ISO[d])
    dias = [DiaGrade(dia=d, dia_nome=DIAS[d], aulas=[a for a in aulas if a.dia == d]) for d in dias_usados]
    return GradeHoraria(
        periodo=periodo,
        data_inicio=min(inicios) if inicios else None,
        data_fim=max(fins) if fins else None,
        dias=dias,
        aulas=aulas,
        conflitos=conflitos,
        sem_horario=sem,
    )


# ----------------------------------------------------------------- iCalendar
def _ics_esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _dobrar(linha: str) -> str:
    # RFC 5545: linhas de no máx. 75 octetos, continuação com um espaço
    b = linha.encode("utf-8")
    if len(b) <= 75:
        return linha
    partes, atual = [], b""
    for ch in linha:
        cb = ch.encode("utf-8")
        if len(atual) + len(cb) > (75 if not partes else 74):
            partes.append(atual.decode("utf-8"))
            atual = b""
        atual += cb
    partes.append(atual.decode("utf-8"))
    return "\r\n ".join(partes)


def gerar_ics(turmas: list[Turma], nome_calendario: str = "Aulas SIGAA", agora: datetime | None = None) -> str:
    """Um VEVENT semanal (RRULE) por bloco de aula de cada turma, entre data_inicio e data_fim
    do horário. Fuso America/Bahia (UTC-3, sem horário de verão)."""
    agora = agora or datetime.now(timezone.utc).replace(tzinfo=None)
    stamp = agora.strftime("%Y%m%dT%H%M%SZ")
    L = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sigaa-api//grade-horaria//PT-BR",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_ics_esc(nome_calendario)}",
        "X-WR-TIMEZONE:America/Bahia",
        "BEGIN:VTIMEZONE",
        "TZID:America/Bahia",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:-0300",
        "TZOFFSETTO:-0300",
        "TZNAME:-03",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    for t in turmas:
        h = t.horario
        if not h or not h.aulas:
            continue
        for a in h.aulas:
            if not a.inicio or not a.fim:
                continue
            ini_periodo = h.data_inicio or agora.date()
            # primeira ocorrência do dia da semana a partir do início do período
            delta = (a.dia_iso - ini_periodo.isoweekday()) % 7
            primeiro = ini_periodo + timedelta(days=delta)
            hi, mi = a.inicio.split(":")
            hf, mf = a.fim.split(":")
            dtini = datetime(primeiro.year, primeiro.month, primeiro.day, int(hi), int(mi))
            dtfim = datetime(primeiro.year, primeiro.month, primeiro.day, int(hf), int(mf))
            rrule = f"RRULE:FREQ=WEEKLY;BYDAY={_ICS_DIA[a.dia]}"
            if h.data_fim:
                rrule += f";UNTIL={h.data_fim.strftime('%Y%m%d')}T235959Z"
            titulo = f"{t.codigo} - {t.nome}" if t.codigo else t.nome
            local = _local_do_bloco(t, a)
            uid = f"{t.turma_id or t.front_end_id or _sem_acento(titulo).replace(' ', '')}-{a.dia}{''.join(a.codigos)}@sigaa-api"
            desc = f"Turma {t.turma or '?'} · {h.codigo} · {', '.join(a.codigos)}"
            L += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp}",
                f"DTSTART;TZID=America/Bahia:{dtini.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=America/Bahia:{dtfim.strftime('%Y%m%dT%H%M%S')}",
                rrule,
                f"SUMMARY:{_ics_esc(titulo)}",
                f"DESCRIPTION:{_ics_esc(desc)}",
            ]
            if local:
                L.append(f"LOCATION:{_ics_esc(local)}")
            L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "\r\n".join(_dobrar(x) for x in L) + "\r\n"
