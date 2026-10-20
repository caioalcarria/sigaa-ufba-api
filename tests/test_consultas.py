"""Testes dos parsers da área 'consultas' (logada) com fixtures anonimizadas."""

from datetime import date
from pathlib import Path

import pytest

from sigaa.parsers import consultas as P

FIX = Path(__file__).parent / "fixtures" / "consultas"


def fx(nome: str) -> bytes:
    return (FIX / nome).read_bytes()


# ------------------------------------------------------------------ calendário


def test_lista_calendarios():
    cals = P.parse_lista_calendarios(fx("calendario_lista.html"))
    assert len(cals) > 100
    primeiro = cals[0]
    assert (primeiro.ano, primeiro.periodo, primeiro.ead) == (2027, 1, False)
    ead = [c for c in cals if c.ead]
    assert ead and all("DIST" in c.tipo for c in ead)
    assert {(c.ano, c.periodo) for c in cals} >= {(2026, 2), (1969, 1)}


def test_calendario_detalhe():
    cal = P.parse_calendario(fx("calendario.html"))
    assert (cal.ano, cal.periodo) == (2026, 2)
    assert cal.vigente is True
    assert cal.nivel == "GRADUAÇÃO"
    assert cal.periodo_letivo.inicio == date(2026, 8, 19) and cal.periodo_letivo.fim == date(2026, 12, 19)
    assert cal.periodo_ferias.fim == date(2027, 2, 28)
    ev = {e.rotulo: e for e in cal.eventos}
    assert ev["Matrícula OnLine"].inicio == date(2026, 8, 3)
    assert ev["Matrícula OnLine"].grupo.startswith("Datas para Períodos de Matrículas")
    assert ev["Trancamento de Turmas"].fim == date(2026, 10, 17)
    nd = ev["Matrícula de Aluno Especial"]
    assert nd.definido is False and nd.inicio is None and nd.texto == "Não Definido"
    assert len(cal.eventos) > 25


def test_calendario_vazio_nao_quebra():
    cal = P.parse_calendario("<html><body><p>Nada</p></body></html>")
    assert cal.eventos == [] and cal.periodo_letivo is None


# ---------------------------------------------------------------------- cursos


def test_busca_cursos():
    cursos = P.parse_busca_cursos(fx("cursos_busca.html"))
    assert len(cursos) > 100
    si = next(c for c in cursos if c.nome == "SISTEMAS DE INFORMAÇÃO")
    assert si.unidade_sigla == "IC/UFBA" and si.nivel == "GRADUAÇÃO"
    assert si.coordenadores and "DE TAL" in si.coordenadores[0]


def test_opcoes_cursos_com_id():
    cursos = P.parse_opcoes_cursos(fx("estrutura_form.html"), "busca:curso")
    si = next(c for c in cursos if c.nome.startswith("SISTEMAS DE INFORMA"))
    assert si.id == 1876885 and si.municipio == "SALVADOR" and si.grau == "BACHARELADO"
    assert any((c.grau or "").endswith("EAD") for c in cursos)


# ----------------------------------------------------------------- componentes


def test_busca_componentes():
    comps = P.parse_busca_componentes(fx("componentes_busca.html"))
    assert len(comps) == 25
    es1 = next(c for c in comps if c.codigo == "MATA62")
    assert es1.id and es1.carga_horaria == 60 and es1.tipo == "DISCIPLINA" and es1.nivel == "GRADUAÇÃO"
    assert any("/" in c.codigo for c in comps)  # códigos de pós (PGCOMP/IC0050)


def test_componente_painel_com_prerequisito():
    c = P.parse_componente(fx("componente_painel.html"), 44744)
    assert (c.codigo, c.nome) == ("MATA62", "ENGENHARIA DE SOFTWARE I")
    assert c.pre_requisitos.expressao == "(MATA55)"
    assert c.pre_requisitos.componentes[0].nome == "PROGRAMAÇÃO ORIENTADA A OBJETOS"
    assert c.co_requisitos.expressao is None and c.co_requisitos.componentes == []
    assert [x.codigo for x in c.equivalencias.componentes] == ["MAT161A", "MAT161B", "MAT161", "MATA62A"]
    assert " OU " in c.equivalencias.expressao
    assert c.ementa is None  # "Não definido" no SIGAA
    assert c.carga_horaria_total == 60
    assert c.outras_informacoes["Quantidade de Avaliações"] == "1"


def test_componente_painel_ementa_e_cargas():
    c = P.parse_componente(fx("componente_painel_sem_requisito.html"), 44697)
    assert c.codigo == "MATA37" and c.ementa.startswith("Desenvolvimento de algoritmos")
    assert c.pre_requisitos.componentes == []
    teorica = next(x for x in c.cargas_horarias if "Teórica - Presencial" in x.rotulo)
    assert teorica.horas == 30 and teorica.grupo == "Aula"
    assert all("Tempo estimado" not in x.rotulo for x in c.cargas_horarias)  # tooltip removido
    assert c.carga_horaria_aula == 60


def test_componente_relatorio_e_mescla():
    rel = P.parse_componente(fx("componente_relatorio.html"), 44697)
    assert rel.codigo == "MATA37" and rel.unidade_responsavel.startswith("DEPARTAMENTO DE CIÊNCIA DA COMPUTAÇÃO")
    assert {x.codigo for x in rel.pre_requisito_de} >= {"MATA40", "MATA55"}
    assert any(x.codigo == "MAT146" for x in rel.equivalente_de)
    h = rel.historico_equivalencias[0]
    assert h.ativa is True and h.inicio_vigencia == date(2023, 1, 1) and h.fim_vigencia is None
    assert len(rel.curriculos) > 10
    cur = rel.curriculos[0]
    assert cur.codigo and cur.matriz and cur.obrigatoria in (True, False)
    assert all(c.semestre is None or c.semestre > 0 for c in rel.curriculos)
    painel = P.parse_componente(fx("componente_painel_sem_requisito.html"), 44697)
    m = P.mesclar_componente(painel, rel)
    assert m.ementa == painel.ementa and m.curriculos and m.pre_requisito_de
    chaves = [P._norm(k) for k in m.outras_informacoes]
    assert len(chaves) == len(set(chaves))


def test_componente_sem_programa_mensagem():
    msgs = P.mensagens_sigaa(fx("componente_sem_programa.html"))
    assert any("não possui um programa cadastrado" in m for m in msgs)


# ------------------------------------------------------------------ estruturas


def test_busca_estruturas():
    ests = P.parse_busca_estruturas(fx("estruturas_busca.html"))
    assert len(ests) == 6
    ativa = [e for e in ests if e.ativa]
    assert [e.codigo for e in ativa] == ["G20251X"]
    assert ativa[0].id == 2421505 and ativa[0].situacao == "CONSOLIDADA"
    assert "(Inativa)" not in ests[0].matriz


def test_estrutura_relatorio_detalhar_mescla():
    rel = P.parse_estrutura_relatorio(fx("estrutura_relatorio.html"), 2421505)
    assert rel.codigo == "G20251X" and rel.periodo_entrada_vigor == "2025.2"
    assert (rel.prazos.minimo, rel.prazos.medio, rel.prazos.maximo) == (10, 10, 15)
    assert (rel.ch_obrigatoria, rel.ch_optativa, rel.ch_complementar, rel.ch_total) == (2206, 480, 415, 3101)
    assert rel.ch_optativa_livre == 0
    sem1 = rel.niveis[0]
    assert sem1.semestre == 1 and sem1.carga_horaria_total == 300
    mata37 = next(c for c in sem1.componentes if c.codigo == "MATA37")
    assert mata37.natureza == "OBRIGATORIO" and mata37.carga_horaria == 60 and mata37.ch_detalhada == "60h Aula"
    opt = rel.niveis[-1]
    assert opt.semestre is None and len(opt.componentes) > 100 and opt.componentes[0].natureza == "OPTATIVO"

    det = P.parse_estrutura_detalhar(fx("estrutura_detalhar.html"), 2421505)
    assert det.ch_maxima_periodo == 540 and det.ch_maxima_eletivos == 0
    assert det.outras_cargas["Subtotal de CH de Aula"] == 2040

    m = P.mesclar_estrutura(rel, det)
    assert all(c.id for n in m.niveis for c in n.componentes)
    assert next(c for c in m.niveis[0].componentes if c.codigo == "MATA37").id == 44697
    assert m.ch_maxima_periodo == 540 and m.unidade_vinculacao.startswith("INSTITUTO DE COMPUTAÇÃO")


def test_declaracao_prazo():
    d = P.parse_declaracao_prazo(fx("estrutura_declaracao.html"))
    assert d.curso == "SISTEMAS DE INFORMAÇÃO" and d.turno == "Noturno" and d.prazo_maximo == 15
    assert d.codigo_verificacao == "0000000000"


# ---------------------------------------------------------------------- turmas


@pytest.mark.parametrize(
    "codigo,esperado",
    [
        ("35T12", [("Terça", "13:00", "13:55"), ("Terça", "13:55", "14:50"), ("Quinta", "13:00", "13:55"), ("Quinta", "13:55", "14:50")]),
        ("6N4", [("Sexta", "21:15", "22:10")]),
        ("2M1", [("Segunda", "07:00", "07:55")]),
    ],
)
def test_decodificar_horario(codigo, esperado):
    assert [(h.dia, h.inicio, h.fim) for h in P.decodificar_horario(codigo)] == esperado


def test_decodificar_varios_blocos():
    hs = P.decodificar_horario("3N34 6N3")
    assert [(h.dia_numero, h.aula) for h in hs] == [(3, 3), (3, 4), (6, 3)]
    assert P.decodificar_horario(None) == [] and P.decodificar_horario("A definir") == []


def test_busca_turmas_componente():
    ts = P.parse_busca_turmas(fx("turmas_busca.html"))
    assert len(ts) == 7
    t = ts[0]
    assert t.id == 393429 and t.componente_codigo == "MATA37" and t.nivel == "GRADUAÇÃO"
    assert (t.ano, t.periodo, t.codigo_turma) == (2026, 2, "01")
    assert t.docentes[0].carga_horaria == 60 and "DE TAL" in t.docentes[0].nome
    assert (t.matriculados, t.capacidade) == (38, 45)
    assert t.horario_codigo == "35T12" and len(t.horarios) == 4
    assert t.periodo_aulas.inicio == date(2026, 8, 19)
    assert t.alocacoes[0].local == "PAF 1 - 106" and t.alocacoes[0].dia == "Quinta" and t.alocacoes[0].inicio == "13:00"
    assert t.situacao == "ABERTA" and t.tipo == "REGULAR" and t.modalidade == "Presencial"


def test_busca_turmas_variacoes():
    ts = P.parse_busca_turmas(fx("turmas_busca_unidade.html"))
    assert len(ts) == 57 and len({t.componente_codigo for t in ts}) > 30
    multi = next(t for t in ts if len(t.docentes) > 1)
    assert all(not d.nome.startswith("e ") for d in multi.docentes)
    a_definir = next(t for t in ts if t.local == "A definir")
    assert a_definir.alocacoes == []
    dois_blocos = next(t for t in ts if t.horario_codigo and " " in t.horario_codigo)
    assert len({h.dia for h in dois_blocos.horarios}) == 2


def test_turma_painel():
    t = P.parse_turma_painel(fx("turma_painel.html"), 393429)
    assert (t.ano, t.periodo, t.componente_codigo, t.codigo_turma) == (2026, 2, "MATA37", "01")
    assert (t.solicitacoes_matricula, t.solicitacoes_rematricula, t.matriculados, t.capacidade) == (68, 26, 38, 45)
    assert len(t.docentes) == 1 and t.carga_horaria == 60
    assert t.vagas_reservadas[0].demais == 45 and t.vagas_reservadas[0].curso.startswith("CIÊNCIA DA COMPUTAÇÃO")
    assert t.horario_codigo == "35T12"


def test_processamento_so_agregados():
    p = P.parse_processamento(fx("turma_processamento.html"), 393429)
    assert p.capacidade == 45 and p.codigo_turma == "01"
    assert p.vagas_reservadas[0].ingressantes == 43 and p.vagas_reservadas[0].demais == 2
    assert p.total_solicitacoes == sum(x.quantidade for x in p.por_situacao) > 0
    assert any(x.situacao == "MATRICULADO" for x in p.por_situacao)
    assert "ALUNO" not in p.model_dump_json()  # nenhum nome sai daqui


# -------------------------------------------------------------------- unidades


def test_busca_unidades():
    us = P.parse_busca_unidades(fx("unidades_busca.html"))
    assert len(us) == 13
    dcc = next(u for u in us if u.codigo == "122801")
    assert dcc.id == 1114 and dcc.sigla == "DCC/IC/UFBA" and dcc.tipo == "Departamento" and dcc.ativa is True
    assert any(u.ativa is False for u in us)


def test_tolerancia_html_vazio():
    vazio = "<html><body></body></html>"
    assert P.parse_busca_cursos(vazio) == []
    assert P.parse_busca_componentes(vazio) == []
    assert P.parse_busca_estruturas(vazio) == []
    assert P.parse_busca_turmas(vazio) == []
    assert P.parse_busca_unidades(vazio) == []
    assert P.parse_componente(vazio).codigo is None
    assert P.parse_turma_painel(vazio).docentes == []
