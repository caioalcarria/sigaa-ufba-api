"""Testes do planejador (pré-requisitos, simulação, sugestão) com dados sintéticos."""

from sigaa.models.academico import CargaHorariaCategoria
from sigaa.models.consultas import HorarioAula
from sigaa.models.planejamento import ComponenteCandidato, GradeCurricular, PlanejamentoMatricula, TurmaCandidata
from sigaa.services.planejamento import avaliar_requisito, simular, sugerir


def test_requisito_simples_e_composto():
    assert avaliar_requisito(None, set()) == (True, [])
    assert avaliar_requisito("(MATA62)", {"MATA62"}) == (True, [])
    assert avaliar_requisito("(MATA62)", set()) == (False, ["MATA62"])
    expr = "(MATC73) OU (MATA47 E MATA53 E MATE12) OU ((MATC73) E (MATD04))"
    assert avaliar_requisito(expr, {"MATC73"})[0] is True
    assert avaliar_requisito(expr, {"MATA47", "MATA53", "MATE12"})[0] is True
    ok, falt = avaliar_requisito(expr, {"MATA47"})
    assert ok is False and "MATC73" in falt
    assert avaliar_requisito("(MATA55) E (MATA40 OU MATA57)", {"MATA55", "MATA57"})[0] is True
    assert avaliar_requisito("(MATA55) E (MATA40 OU MATA57)", {"MATA40"}) == (False, ["MATA55"])


def _h(dia, turno, aula, ini, fim):
    return HorarioAula(dia={2: "Segunda", 3: "Terça", 4: "Quarta", 5: "Quinta"}[dia], dia_numero=dia, turno=turno, aula=aula, inicio=ini, fim=fim)


def _cand(cod, ch, horarios, natureza="OBRIGATORIO", apto=True, sem=2, vagas=10, turma="01"):
    return ComponenteCandidato(
        codigo=cod, nome=cod, carga_horaria=ch, natureza=natureza, semestre_ideal=sem, atrasado=False, apto=apto,
        turmas=[TurmaCandidata(turma_id=hash(cod) % 10**6, codigo_turma=turma, horarios=horarios, vagas_livres=vagas)],
    )


N12_35 = [_h(3, "N", 1, "18:30", "19:25"), _h(3, "N", 2, "19:25", "20:20"), _h(5, "N", 1, "18:30", "19:25"), _h(5, "N", 2, "19:25", "20:20")]
N34_35 = [_h(3, "N", 3, "20:20", "21:15"), _h(3, "N", 4, "21:15", "22:10"), _h(5, "N", 3, "20:20", "21:15"), _h(5, "N", 4, "21:15", "22:10")]
N12_24 = [_h(2, "N", 1, "18:30", "19:25"), _h(2, "N", 2, "19:25", "20:20"), _h(4, "N", 1, "18:30", "19:25"), _h(4, "N", 2, "19:25", "20:20")]
T12_24 = [_h(2, "T", 1, "13:00", "13:55"), _h(4, "T", 1, "13:00", "13:55")]


def _plano(cands, chmax=180):
    return PlanejamentoMatricula(
        considerou_cursando_como_aprovado=True, ch_maxima_periodo=chmax, candidatos=cands, total_ofertados_para_o_curso=len(cands),
        ch_pendente=[
            CargaHorariaCategoria(categoria="Obrigatórias", exigido=300, integralizado=120, pendente=180),
            CargaHorariaCategoria(categoria="Optativos", exigido=60, integralizado=0, pendente=60),
            CargaHorariaCategoria(categoria="Total", exigido=360, integralizado=120, pendente=240),
        ],
    )


GRADE = GradeCurricular(semestres=[], optativas=[], obrigatorias_pendentes=3, obrigatorias_cumpridas=2, optativas_cursadas_ch=0)


def test_simular_detecta_choque_ch_e_requisito():
    plano = _plano([_cand("AAA01", 60, N12_35), _cand("BBB02", 60, N12_35), _cand("CCC03", 60, N34_35, apto=False), _cand("DDD04", 60, N12_24)], chmax=150)
    s = simular(plano, [("AAA01", None), ("BBB02", None), ("CCC03", None)], GRADE)
    assert not s.valida
    assert len(s.choques) == 4 and s.choques[0].dia == "Terça"
    assert s.excede_ch_maxima and s.ch_total == 180
    assert any("pré-requisito" in p for p in s.problemas)


def test_simular_valido_e_integralizacao():
    plano = _plano([_cand("AAA01", 60, N12_35), _cand("DDD04", 60, N12_24), _cand("OPT01", 60, N34_35, natureza="OPTATIVO", sem=None)])
    s = simular(plano, [("AAA01", None), ("DDD04", "01"), ("OPT01", None)], GRADE)
    assert s.valida and s.choques == [] and s.ch_total == 180
    assert s.ch_obrigatoria_pendente_depois == 60 and s.ch_optativa_pendente_depois == 0
    assert s.percentual_integralizado_depois == round(100 * (360 - 60) / 360, 2)
    assert list(s.grade) == ["Segunda", "Terça", "Quarta", "Quinta"]


def test_simular_componente_inexistente_e_lotada():
    plano = _plano([_cand("AAA01", 60, N12_35, vagas=0)])
    s = simular(plano, [("AAA01", None), ("ZZZ99", None)], GRADE)
    assert not s.valida
    assert any("lotada" in p for p in s.problemas) and any("ZZZ99" in p for p in s.problemas)


def test_sugerir_sem_choque_respeitando_turno_e_ch():
    plano = _plano(
        [_cand("AAA01", 60, N12_35), _cand("BBB02", 60, N12_35), _cand("CCC03", 60, T12_24), _cand("DDD04", 60, N12_24), _cand("EEE05", 60, N34_35, apto=False)],
        chmax=120,
    )
    s = sugerir(plano, GRADE, turnos={"N"})
    assert [i.codigo for i in s.itens] == ["AAA01", "DDD04"]
    assert s.valida and s.ch_total == 120
