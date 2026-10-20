"""Testes dos parsers acadêmicos (fixtures anonimizadas + histórico sintético com variações)."""

from datetime import date
from pathlib import Path

import pytest

from sigaa.parsers.academico import (
    parse_atividades_autonomas,
    parse_comprovante_inscricao,
    parse_comprovante_solicitacao,
    parse_declaracao_vinculo_texto,
    parse_horarios_local,
    parse_listagem,
    parse_resultado_processamento,
    parse_suspensoes,
    parse_trancamentos,
)
from sigaa.parsers.historico_pdf import calcular_cr, calcular_iap, parse_historico_texto

FIX = Path(__file__).parent / "fixtures" / "academico"


def fx(nome: str) -> bytes:
    return (FIX / nome).read_bytes()


CAB = """UFBA - Universidade Federal da Bahia
Rua Augusto Viana, s/n - Canela - Salvador/BA - CEP 40110-909
Documento Oficial
Histórico Escolar - Emitido em: 05/03/2026 às 10:15"""
ROD = """Para verificar sua autenticidade entre em https://sigaa.ufba.br/sigaa/documentos informando a matrícula, data de emissão e o código de
Página {n} de 2
verificação: abc123def0"""

PAG1 = f"""{CAB}
Dados Pessoais
Nome: FULANA DE TAL Matrícula: 200000002
Data de Nascimento: 01/01/2000 Local de Nascimento: SALVADOR/BA
Nacionalidade: BRASILEIRA
Nº do documento com órgão expedidor: 0000000, (SSP/BA)
Nº do CPF: 000.000.000-00
Dados do Vínculo do Discente
Curso: CIÊNCIA DA COMPUTAÇÃO/IC/UFBA - SALVADOR - BACHARELADO - PRESENCIAL - MT
Status: FORMANDO Índices Acadêmicos
Ênfase: SISTEMAS DISTRIBUÍDOS IAP: 0.8000 CR: 7.5000 MC: 7.9000
Currículo: 2019.1 - 2019.1
Reconhecimento do Curso: 1, 01/01/2010. D.O.U.: 02/01/2010
Ingresso: 2019.2 - 01/08/2019 Perfil Inicial:2
Forma de Ingresso: Transferência Externa
Período Letivo Atual: 12 Prazo para Conclusão (Padrão / Máximo):2024.1 / 2026.2
Suspensões: -
Prorrogações: -
Conclusão: -
Tipo Saída: -
Data da Conclusão: - Data da Colação de Grau:-
Trabalho de Conclusão de
UM ESTUDO SOBRE ALGO
Curso:
Data da Expedição do Diploma: -
Componentes Curriculares Cursados/Cursando
Semestre Componente Curricular CH Nota Situação
CÁLCULO A
2019.2 OB MATA02 90 7.0 APR
Dr. DOCENTE UM (45h), Dra. DOCENTE DOIS
(45h)
DISCIPLINA APROVEITADA DE OUTRA IES
2019.2 OP XYZ123 60 -- DISP
ESTRUTURAS DE DADOS
2020.1 OB MATD04 60 3.0 REP
MSc. DOCENTE TRES (60h)
PROGRAMAÇÃO COMPETITIVA
2020.1 OB MATF34 60 0.0 REPF
Esp. DOCENTE QUATRO (60h)
{ROD.format(n=1)}"""

PAG2 = f"""{CAB}
Nome: FULANA DE TAL Matrícula: 200000002
Componentes Curriculares Cursados/Cursando
Semestre Componente Curricular CH Nota Situação
ESTRUTURAS DE DADOS
2020.2 OB MATD04 60 9.0 APR *
DOCENTE TRES (60h)
SISTEMAS OPERACIONAIS
2021.1 OB MATA58 60 -- TRANC
DOCENTE CINCO (60h)
TCC
2021.2 OB GICC0003 45 -- MATR
Legenda
OP Optativo OB Obrigatório
SIGLA SIGNIFICADO
APR Aprovado
DISP Dispensado
Carga Horária e Créditos Integralizados/Pendentes
Obrigatórias Optativos Complementares Total
Exigido 300 h 60 h 0 h 360 h
Integralizado 150 h 60 h 0 h 210 h
Pendente 150 h 0 h 0 h 150 h
Componentes Curriculares Obrigatórios Pendentes:2
Código Componente Curricular CH
MATA58 SISTEMAS OPERACIONAIS 60 h
GICC0003 TCC Matriculado 45 h
Equivalências:
Cumpriu MATA37 - INTRODUÇÃO À LÓGICA (60h) através de XYZ123 - DISCIPLINA APROVEITADA DE
OUTRA IES (60h)
Observações:
- Uma observação que quebra
em duas linhas
{ROD.format(n=2)}"""


@pytest.fixture(scope="module")
def hist():
    return parse_historico_texto([PAG1, PAG2])


def test_historico_cabecalho(hist):
    assert hist.emitido_em.isoformat() == "2026-03-05T10:15:00"
    assert hist.codigo_verificacao == "abc123def0"
    assert hist.dados_pessoais.nome == "FULANA DE TAL"
    assert hist.dados_pessoais.matricula == "200000002"
    assert hist.dados_pessoais.data_nascimento == date(2000, 1, 1)
    assert hist.dados_pessoais.orgao_expedidor == "SSP/BA"


def test_historico_vinculo_variacoes(hist):
    v = hist.vinculo
    assert v.status == "FORMANDO"
    assert v.enfase == "SISTEMAS DISTRIBUÍDOS"
    assert v.forma_ingresso == "Transferência Externa"
    assert v.ingresso_periodo == "2019.2" and v.ingresso_data == date(2019, 8, 1)
    assert v.perfil_inicial == 2
    assert v.prazo_conclusao_padrao == "2024.1" and v.prazo_conclusao_maximo == "2026.2"
    assert v.suspensoes == []
    assert v.trabalho_conclusao_curso == "UM ESTUDO SOBRE ALGO"
    assert hist.indices.cr == 7.5 and hist.indices.iap == 0.8
    assert hist.indices.outros == {"MC": 7.9}


def test_historico_componentes(hist):
    cs = hist.componentes
    assert [c.codigo for c in cs] == ["MATA02", "XYZ123", "MATD04", "MATF34", "MATD04", "MATA58", "GICC0003"]
    calc = cs[0]
    assert calc.nome == "CÁLCULO A" and calc.nota == 7.0 and calc.aprovado
    # docentes quebrados em duas linhas e com títulos variados
    assert [(d.titulo, d.nome, d.carga_horaria) for d in calc.docentes] == [("Dr.", "DOCENTE UM", 45), ("Dra.", "DOCENTE DOIS", 45)]
    disp = cs[1]
    assert disp.situacao == "DISP" and disp.nota is None and disp.aprovado and disp.docentes == []
    assert cs[4].marcadores == ["*"]
    assert cs[5].situacao == "TRANC" and cs[5].nota is None
    assert cs[6].cursando and cs[6].docentes == []
    assert hist.linhas_nao_reconhecidas == []


def test_historico_secoes(hist):
    tot = next(c for c in hist.carga_horaria if c.categoria == "Total")
    assert (tot.exigido, tot.integralizado, tot.pendente) == (360, 210, 150)
    assert hist.total_obrigatorios_pendentes == 2
    assert hist.obrigatorios_pendentes[1].matriculado is True
    eq = hist.equivalencias[0]
    assert eq.componente.codigo == "MATA37" and eq.atraves_de[0].codigo == "XYZ123"
    assert hist.observacoes == ["Uma observação que quebra em duas linhas"]
    assert hist.legenda.situacoes["DISP"] == "Dispensado"


def test_regra_cr_iap(hist):
    # CR: (7*90 + 3*60 + 9*60) / 210 = 6.4286 — REPF fica fora, DISP/TRANC/MATR não têm nota
    assert calcular_cr(hist.componentes) == pytest.approx(6.4286, abs=1e-4)
    # IAP: aprovadas APR (90+60) / encerradas (90+60+60+60+60+60) = 150/390
    assert calcular_iap(hist.componentes) == pytest.approx(150 / 390, abs=1e-4)
    por = {p.periodo: p for p in hist.estatisticas.por_periodo}
    assert por["2020.1"].reprovados == 2
    assert por["2019.2"].cr_periodo == 7.0


def test_historico_tolerante_a_secoes_ausentes():
    h = parse_historico_texto([f"{CAB}\nDados Pessoais\nNome: X Matrícula: 1\n{ROD.format(n=1)}"])
    assert h.componentes == [] and h.carga_horaria == [] and h.estatisticas.cr_calculado is None


def test_comprovante_inscricao():
    c = parse_comprovante_inscricao(fx("comprovante_inscricao.html"))
    assert c.periodo == "2026.2" and c.periodo_inicio == date(2026, 8, 19)
    assert c.nome == "FULANO DE TAL DA SILVA" and c.matricula == "200000001"
    assert c.total_matriculadas == 3 and len(c.turmas) == 6
    sit = {t.codigo: t.situacao for t in c.turmas}
    assert sit["MATC72"] == "MATRICULADO" and sit["MATA63"] == "INDEFERIDO"
    ihc = next(t for t in c.turmas if t.codigo == "MATC72")
    assert ihc.horario_codigo == "35N12" and ihc.horarios[0].dia == "Terça" and ihc.horarios[0].inicio == "18:30"
    assert any(g.dia == "Segunda" and g.conteudo == "ADMF01" and g.slot == 13 for g in c.grade)


def test_comprovante_solicitacao():
    c = parse_comprovante_solicitacao(fx("comprovante_solicitacao.html"))
    assert c.numero == "100001" and c.periodo == "2026.2"
    ids = {t.codigo: t.turma_id for t in c.turmas}
    assert ids["MATC72"] == 386385
    mat236 = next(t for t in c.turmas if t.codigo == "MAT236")
    assert mat236.rematricula and mat236.situacao == "TRANCADO" and mat236.carga_horaria == 60
    assert len(c.grade) > 0


def test_resultado_processamento_nao_vaza_terceiros():
    r = parse_resultado_processamento(fx("processamento_393408.html"), 393408, "200000001")
    assert r.componente_codigo == "MATA63" and r.capacidade == 45
    assert r.vagas_total_demais == 45 and len(r.vagas) == 3
    assert r.minha_posicao and r.minha_posicao.situacao == "INDEFERIDO"
    dump = r.model_dump_json()
    assert "FICTICIO" not in dump and "200000002" not in dump


def test_trancamentos():
    t = parse_trancamentos(fx("trancamentos.html"))
    assert len(t) == 1 and t[0].componente_codigo == "MAT236" and t[0].motivo
    assert t[0].data_solicitacao == date(2026, 9, 21)


def test_atividades_autonomas():
    a = parse_atividades_autonomas(fx("atividades_autonomas.html"))
    assert a.total_registros == 6
    assert [g.carga_horaria_aprovada for g in a.grupos] == [60.0, 140.0]
    assert {r.status for g in a.grupos for r in g.registros} == {"ACEITO", "REJEITADO"}


def test_suspensoes_e_movimentacoes():
    s = parse_suspensoes(fx("suspensoes.html"))
    assert s.solicitacoes.vazio and s.solicitacoes.mensagem
    assert len(s.movimentacoes) == 5 and s.movimentacoes[0].tipo == "PRORROGAÇÃO ADMINISTRATIVA"


@pytest.mark.parametrize(
    "arquivo,vazio",
    [("aproveitamentos.html", True), ("diploma.html", True), ("avaliacoes_anteriores.html", False)],
)
def test_listagens(arquivo, vazio):
    lista = parse_listagem(fx(arquivo))
    assert lista.vazio is vazio
    if vazio:
        assert lista.mensagem
    else:
        assert lista.itens[0].campos["Ano-Período"] == "2025.2"


def test_horarios_local():
    local, slots = parse_horarios_local("PAF 1 - 006 - Terça Horários 18:30 às 19:25PAF 1 - 006 - Terça Horários 19:25 às 20:20")
    assert local == "PAF 1 - 006" and [s.fim for s in slots] == ["19:25", "20:20"]
    assert parse_horarios_local("Smart Class III") == ("Smart Class III", [])


def test_declaracao():
    d = parse_declaracao_vinculo_texto(
        "UNIVERSIDADE FEDERAL DA BAHIA\nNÚCLEO DE REGISTROS\nCNPJ: 0\nD E C L A R A Ç Ã O\n"
        "Declaramos, para os fins a que se fizerem necessários, que FULANA DE TAL é aluno(a) vinculado(a) a este(a) Universidade, sob o\n"
        "número 200000002, no curso de COMPUTAÇÃO - SALVADOR. \nSalvador, 5 de Março de 2026.\nCódigo de verificação:\nabcdef1234"
    )
    assert d.nome == "FULANA DE TAL" and d.matricula == "200000002" and d.emitido_em == date(2026, 3, 5)
    assert d.codigo_verificacao == "abcdef1234" and d.orgao_emissor == "NÚCLEO DE REGISTROS"
