"""Oferta histórica por componente (paridade/previsão), regra de sequência I → II e os requisitos
dos pendentes sem turma (TCC). Fixtures anonimizadas em ``tests/fixtures/oferta/`` e dados sintéticos."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from sigaa.client import Page
from sigaa.models.academico import Historico
from sigaa.models.consultas import DocenteTurma, TurmaOferta
from sigaa.models.oferta import Confianca, OrigemRequisito, Paridade, TurmasDoComponente
from sigaa.models.planejamento import ComponenteGrade, GradeCurricular, SemestreGrade, StatusComponente
from sigaa.parsers import consultas as P
from sigaa.services import oferta as O
from sigaa.services import planejamento as PL

FIX = Path(__file__).parent / "fixtures" / "oferta"


def fx(nome: str) -> bytes:
    return (FIX / nome).read_bytes()


def _page(nome: str, url: str = "https://sigaa.ufba.br/sigaa/ensino/turma/busca_turma.jsf") -> Page:
    return Page(url=url, status=200, content=fx(nome), content_type="text/html")


class FakeBusca:
    """Cliente falso: o menu abre a busca de turmas e o POST devolve a fixture; guarda os corpos enviados."""

    _sem_cache_compartilhado = True

    def __init__(self, resposta: str):
        self.resposta, self.posts = resposta, []

    async def menu(self, bean):
        assert bean == "buscaTurmaBean.popularBuscaGeral"
        return _page("turmas_componente_todos.html")

    async def post(self, url, data, content=None, headers=None):
        self.posts.append(parse_qs(content.decode("ascii"), keep_blank_values=True))
        return _page(self.resposta)

    async def paralelo(self, fluxos):
        return [await f(self) for f in fluxos]


def _t(ano, per, cod="ZZZA01", turma="01", cap=40, mat=30, tid=None, doc="DOCENTE FICTICIO A"):
    return TurmaOferta(
        id=tid or ano * 100 + per * 10 + int(turma), componente_codigo=cod, componente_nome="COMPONENTE FICTICIO", ano=ano, periodo=per,
        codigo_turma=turma, capacidade=cap, matriculados=mat, docentes=[DocenteTurma(nome=doc)], situacao="CONSOLIDADA",
    )


# ------------------------------------------------------------------ SIGAA (parser + navegação)
def test_parser_busca_todos_os_periodos():
    ts = P.parse_busca_turmas(fx("turmas_componente_todos.html"))
    assert len(ts) == 16
    assert {(t.ano, t.periodo) for t in ts} == {(a, p) for a in (2023, 2024, 2025, 2026) for p in (1, 2)}
    assert all(t.componente_codigo == "MATA37" and t.id and t.capacidade for t in ts)
    assert all(d.nome.startswith("DOCENTE FICTICIO") for t in ts for d in t.docentes)


def test_turmas_do_componente_tira_o_filtro_de_periodo():
    c = FakeBusca("turmas_componente_todos.html")
    r = asyncio.run(O.turmas_do_componente(c, " mata37 "))
    assert r.componente == "MATA37" and r.periodo_atual == "2026.2" and len(r.turmas) == 16
    corpo = c.posts[0]
    # o checkbox "Ano-Período" vem marcado na tela: se fosse enviado, o SIGAA buscaria só o período atual
    assert "form:checkAnoPeriodo" not in corpo
    assert corpo["form:checkCodigo"] == ["on"] and corpo["form:inputCodDisciplina"] == ["MATA37"]
    assert corpo["form:buttonBuscar"] == ["Buscar"]


def test_turmas_do_componente_sem_resultado_e_codigo_invalido():
    r = asyncio.run(O.turmas_do_componente(FakeBusca("turmas_busca_vazia.html"), "GICC0003"))
    assert r.turmas == [] and r.periodo_atual == "2026.2"
    with pytest.raises(ValueError):
        asyncio.run(O.turmas_do_componente(FakeBusca("turmas_busca_vazia.html"), "MATA37'; DROP"))


def test_historico_com_curso_faz_as_duas_buscas():
    c = FakeBusca("turmas_componente_todos.html")
    h = asyncio.run(O.historico(c, "MATA37", curso=1000001, incluir_turmas=False))
    assert len(c.posts) == 2 and "form:checkCurso" not in c.posts[0] and c.posts[1]["form:selectCurso"] == ["1000001"]
    por = {p.periodo: p.reserva_para_o_curso for p in h.periodos}
    assert por["2025.1"] is None and por["2025.2"] is True and por["2026.2"] is True


def test_turmas_reservadas_manda_curso_sem_periodo():
    c = FakeBusca("turmas_componente_todos.html")
    ids = asyncio.run(O.turmas_reservadas(c, "MATA37", 1000001))
    assert len(ids) == 16 and ids == sorted(ids)
    assert c.posts[0]["form:checkCurso"] == ["on"] and c.posts[0]["form:selectCurso"] == ["1000001"]
    assert "form:checkAnoPeriodo" not in c.posts[0]


# ------------------------------------------------------------------ períodos
def test_periodos():
    assert O.ler_periodo("2025.1") == (2025, 1) and O.ler_periodo(None) is None and O.ler_periodo(" ") is None
    with pytest.raises(ValueError):
        O.ler_periodo("2025-1")
    assert O.proximo((2026, 2)) == (2027, 1) and O.proximo((2026, 1)) == (2026, 2) and O.proximo((2026, 3)) == (2027, 1)
    assert O.regulares((2025, 2), (2027, 1)) == [(2025, 2), (2026, 1), (2026, 2), (2027, 1)]
    assert O.regulares((2025, 3), (2026, 2)) == [(2026, 1), (2026, 2)]


# ------------------------------------------------------------------ resumo e previsão
def _bruto_fixture() -> TurmasDoComponente:
    return TurmasDoComponente(componente="MATA37", periodo_atual="2026.2", turmas=P.parse_busca_turmas(fx("turmas_componente_todos.html")))


def test_historico_todo_semestre():
    h = O.montar_historico(_bruto_fixture())
    assert h.desde == "2023.1" and h.ate == "2026.2" and len(h.periodos) == 8
    r = h.resumo
    assert r.paridade == Paridade.ambos and r.frequencia == 1.0 and r.ofertas_impar == 4 and r.ofertas_par == 4
    assert r.ultima_oferta == "2026.2" and r.primeira_oferta == "2023.1" and r.periodos_sem_oferta == []
    assert r.media_turmas_por_oferta == 2.0
    p = h.periodos[-1]
    assert p.periodo == "2026.2" and p.total_turmas == 2 and p.total_vagas == sum(t.capacidade for t in p.turmas)
    assert h.previsao.periodo == "2027.1" and h.previsao.provavel and h.previsao.confianca == Confianca.alta
    assert h.previsao.probabilidade == 1.0 and not h.previsao.ja_publicada


def test_historico_so_par_preve_que_nao_abre_no_impar():
    turmas = [_t(a, 2) for a in (2023, 2024, 2025)] + [_t(2026, 2, turma="01"), _t(2026, 2, turma="02")]
    h = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=turmas))
    r = h.resumo
    assert r.paridade == Paridade.par and r.ofertas_par == 4 and r.ofertas_impar == 0
    assert r.frequencia == 0.5 and r.frequencia_par == 1.0 and r.frequencia_impar == 0.0
    assert r.periodos_sem_oferta == ["2023.1", "2024.1", "2025.1", "2026.1"]
    assert h.previsao.provavel is False and h.previsao.probabilidade == 0.0 and h.previsao.confianca == Confianca.alta
    prox_par = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=turmas), alvo=(2027, 2))
    assert prox_par.previsao.provavel is True and prox_par.previsao.probabilidade == 1.0


def test_historico_peso_dos_semestres_recentes():
    # padrão real do MATC73: abriu no ímpar em 2023.1 e 2024.1, e desde então só no par
    turmas = [_t(2023, 1), _t(2024, 1)] + [_t(a, 2) for a in (2023, 2024, 2025, 2026)]
    h = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=turmas))
    r = h.resumo
    assert r.paridade == Paridade.ambos and r.frequencia_impar == 0.5  # a frequência simples diria 50%
    assert r.chance_impar == round(2 / 6, 3) and r.chance_par == 1.0 and r.tendencia == "par"
    assert h.previsao.periodo == "2027.1" and h.previsao.provavel is False and h.previsao.probabilidade == round(2 / 6, 3)
    assert "mais recentes (2025.1, 2026.1): 0" in h.previsao.motivo
    # voltou a abrir no ímpar recentemente: a chance sobe
    volta = [_t(2023, 1), _t(2025, 1), _t(2026, 1)] + [_t(a, 2) for a in (2023, 2024)]
    v = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=volta))
    assert v.resumo.chance_impar == round(5 / 6, 3) and v.resumo.chance_par == round(2 / 6, 3) and v.resumo.tendencia == "impar"
    irregular = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=[_t(2023, 1), _t(2023, 2)]))
    assert irregular.resumo.tendencia == "irregular"


def test_historico_desde_alvo_publicado_e_periodo_especial():
    turmas = [_t(2025, 1), _t(2026, 1), _t(2026, 3), _t(2027, 1, turma="05")]
    h = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=turmas), desde=(2025, 1))
    # a oferta de 2027.1 já publicada estica a janela e a previsão vira fato
    assert h.ate == "2027.1" and h.resumo.periodos_analisados == ["2025.1", "2025.2", "2026.1", "2026.2", "2027.1"]
    assert h.resumo.periodos_especiais == ["2026.3"] and h.resumo.paridade == Paridade.impar
    # alvo padrão = o seguinte ao período atual (2027.1), que já tem turma publicada
    assert h.previsao.periodo == "2027.1" and h.previsao.ja_publicada and h.previsao.provavel
    par = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=turmas), desde=(2025, 1), alvo=(2027, 2))
    assert par.previsao.provavel is False and par.previsao.probabilidade == 0.0  # 0 de 2 pares
    assert par.previsao.confianca == Confianca.media
    passado = O.montar_historico(TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.2", turmas=turmas), alvo=(2025, 2))
    assert passado.previsao.provavel is False and "não teve turma" in passado.previsao.motivo


def test_historico_desde_antes_de_2023_avisa():
    h = O.montar_historico(_bruto_fixture(), desde=(2019, 1))
    assert h.desde == "2023.1" and any("2023.1" in a for a in h.avisos)


def test_historico_sem_turma():
    h = O.montar_historico(TurmasDoComponente(componente="GICC0003", periodo_atual="2026.2", turmas=[]))
    assert h.periodos == [] and h.resumo.paridade == Paridade.sem_oferta and h.resumo.ultima_oferta is None
    assert any("ATIVIDADES" in a for a in h.avisos)


def test_historico_reserva_por_curso_so_a_partir_de_2025_2():
    turmas = [_t(2025, 1, tid=1), _t(2025, 2, tid=2), _t(2026, 1, tid=3)]
    h = O.montar_historico(
        TurmasDoComponente(componente="ZZZA01", periodo_atual="2026.1", turmas=turmas), curso=1000001, reservadas={2}, incluir_turmas=False
    )
    por = {p.periodo: p for p in h.periodos}
    assert por["2025.1"].reserva_para_o_curso is None  # o SIGAA não tem reserva antes de 2025.2
    assert por["2025.2"].reserva_para_o_curso is True and por["2026.1"].reserva_para_o_curso is False
    assert all(p.turmas == [] for p in h.periodos) and por["2025.2"].total_turmas == 1
    assert any("2025.2" in a for a in h.avisos)


def test_historico_tolerante_no_lote():
    class Quebra:
        _sem_cache_compartilhado = True

        async def menu(self, bean):
            raise RuntimeError("SIGAA fora")

    h = asyncio.run(O.historico_tolerante(Quebra(), "MATA37"))
    assert h.periodos == [] and "SIGAA fora" in h.avisos[0]


# ------------------------------------------------------------------ sequência I → II (inferida)
def _g(cod, nome, natureza="OBRIGATORIO", sem=7, status=StatusComponente.pendente, cid=None):
    return ComponenteGrade(id=cid, codigo=cod, nome=nome, natureza=natureza, semestre_ideal=sem, status=status, carga_horaria=60)


def test_inferir_sequencias():
    comps = [
        _g("GICC0003", "TCC BACHARELADO SISTEMAS DE INFORMAÇÃO I"),
        _g("GICC0004", "TCC BACHARELADO SISTEMAS DE INFORMAÇÃO II", sem=8),
        _g("ZZZA10", "LABORATÓRIO FICTÍCIO I"),
        _g("ZZZA11", "LABORATÓRIO FICTICIO II"),  # sem acento: mesmo nome-base
        _g("ZZZA12", "LABORATÓRIO FICTÍCIO III"),
        _g("ZZZA20", "TÓPICOS FICTÍCIOS I", natureza="OPTATIVO"),
        _g("ZZZA21", "TÓPICOS FICTÍCIOS II"),  # natureza diferente: não é sequência
        _g("ZZZA30", "CÁLCULO FICTÍCIO A"),
        _g("ZZZA31", "CÁLCULO FICTÍCIO B"),  # letra não é sufixo de sequência
        _g("YYYB01", "ESTÁGIO FICTÍCIO I"),
        _g("XXXB02", "ESTÁGIO FICTÍCIO II"),  # prefixo de código diferente
        _g("ZZZA40", "PROJETO FICTÍCIO 1"),
        _g("ZZZA41", "PROJETO FICTÍCIO 2"),
    ]
    seq = PL.inferir_sequencias(comps)
    assert seq == {"GICC0004": "GICC0003", "ZZZA11": "ZZZA10", "ZZZA12": "ZZZA11", "ZZZA41": "ZZZA40"}


def test_montar_requisito_sigaa_e_inferido():
    tcc2 = _g("GICC0004", "TCC BACHARELADO SISTEMAS DE INFORMAÇÃO II")
    # o SIGAA já cita o antecessor: nada de inferido
    r = PL.montar_requisito(tcc2, "( GICC0003 )", None, "ATIVIDADE", True, "GICC0003", set())
    assert r.sequencia_apos == [] and r.origem_sequencia is None and r.origem_pre_requisitos == OrigemRequisito.sigaa
    assert r.apto is False and r.faltando == ["GICC0003"]
    # o SIGAA não traz pré-requisito: a sequência é inferida e bloqueia
    r = PL.montar_requisito(tcc2, None, None, "ATIVIDADE", True, "GICC0003", set())
    assert r.sequencia_apos == ["GICC0003"] and r.origem_sequencia == OrigemRequisito.inferido
    assert r.apto is False and r.faltando == ["GICC0003"]
    r = PL.montar_requisito(tcc2, None, None, "ATIVIDADE", True, "GICC0003", {"GICC0003"})
    assert r.apto is True and r.faltando == []
    # alternativas vêm só da expressão; a sequência inferida entra no mínimo que falta
    r = PL.montar_requisito(tcc2, "( ZZZA00 ) OU ( ZZZA01 E ZZZA02 )", None, "ATIVIDADE", True, "GICC0003", {"ZZZA01"})
    assert r.alternativas == [["ZZZA00"], ["ZZZA01", "ZZZA02"]] and r.sequencia_apos == ["GICC0003"]
    assert r.faltando == ["ZZZA00", "ZZZA02", "GICC0003"] and r.faltando_minimo == ["ZZZA00", "GICC0003"]
    # não deu pra ler o SIGAA: apto desconhecido, a não ser que a sequência já bloqueie
    r = PL.montar_requisito(tcc2, None, None, None, False, None, set())
    assert r.apto is None and r.origem_pre_requisitos is None


# ------------------------------------------------------------------ integração com o planejador
def _hist():
    return Historico.model_construct(
        vinculo=SimpleNamespace(curso="CURSO FICTICIO", periodo_letivo_atual=7, curriculo="X"),
        componentes=[], equivalencias=[], obrigatorios_pendentes=[], carga_horaria=[],
    )


def _grade():
    s7 = [
        _g("GICC0003", "TCC BACHARELADO SISTEMAS DE INFORMAÇÃO I", cid=1),
        _g("ZZZA10", "LABORATÓRIO FICTÍCIO I", cid=3),
        _g("ZZZA01", "DISCIPLINA FICTÍCIA", cid=5),
        _g("ZZZA00", "BASE FICTÍCIA", status=StatusComponente.aprovado, sem=1, cid=6),
    ]
    s8 = [_g("GICC0004", "TCC BACHARELADO SISTEMAS DE INFORMAÇÃO II", sem=8, cid=2), _g("ZZZA11", "LABORATÓRIO FICTÍCIO II", sem=8, cid=4)]
    return GradeCurricular(
        semestres=[SemestreGrade(nome="7", semestre=7, carga_horaria=0, carga_horaria_cumprida=0, componentes=s7),
                   SemestreGrade(nome="8", semestre=8, carga_horaria=0, carga_horaria_cumprida=0, componentes=s8)],
        optativas=[], obrigatorias_pendentes=5, obrigatorias_cumpridas=1, optativas_cursadas_ch=0,
    )


REQS = {
    1: ("( LETA09 )", None, "ATIVIDADE"),
    2: ("( GICC0003 )", None, "ATIVIDADE"),
    3: (None, None, "DISCIPLINA"),
    4: (None, None, "DISCIPLINA"),  # o SIGAA não traz: a sequência é inferida
    5: ("( ZZZA00 )", None, "DISCIPLINA"),
}


class FakePlanejador:
    _sem_cache_compartilhado = True

    async def paralelo(self, fluxos):
        return [await f(self) for f in fluxos]

    async def memo(self, chave, ttl, fn):
        return await fn()


@pytest.fixture
def planejador(monkeypatch):
    async def historico(c):
        return _hist()

    async def grade(c):
        return _grade()

    async def oferta_curso(c, ano=None, periodo=None):
        def com_horario(t, cod):
            return t.model_copy(update={"horario_codigo": cod, "horarios": P.decodificar_horario(cod)})

        return [
            com_horario(_t(2026, 2, cod="ZZZA11", turma="01"), "24N12"),  # o Lab II tem turma, mas o Lab I não foi feito
            com_horario(_t(2026, 2, cod="ZZZA10", turma="01"), "35N12"),
            com_horario(_t(2026, 2, cod="ZZZA01", turma="01"), "35N34"),
        ]

    async def requisitos(c, cid):
        return REQS[cid]

    async def turmas_comp(c, codigo):
        hist = {
            "ZZZA01": [_t(a, 2, cod="ZZZA01") for a in (2023, 2024, 2025, 2026)],
            "ZZZA10": [_t(a, p, cod="ZZZA10") for a in (2023, 2024, 2025, 2026) for p in (1, 2)],
            "ZZZA11": [_t(a, 1, cod="ZZZA11") for a in (2024, 2025, 2026)],
        }
        return TurmasDoComponente(componente=codigo, periodo_atual="2026.2", turmas=hist.get(codigo, []))

    monkeypatch.setattr(PL.academico, "historico", historico)
    monkeypatch.setattr(PL, "grade_curricular", grade)
    monkeypatch.setattr(PL, "oferta_do_curso", oferta_curso)
    monkeypatch.setattr(PL, "_requisitos", requisitos)
    monkeypatch.setattr(O, "turmas_do_componente", turmas_comp)
    return FakePlanejador()


def test_planejamento_traz_requisitos_dos_sem_turma_e_sequencia(planejador):
    plano = asyncio.run(PL.planejamento(planejador))
    req = {r.codigo: r for r in plano.requisitos}
    # TCC I e II não têm turma (não viram candidatos), mas o pré-requisito vem em `requisitos`
    assert {"GICC0003", "GICC0004"} <= set(req) and "GICC0004" not in {x.codigo for x in plano.candidatos}
    assert req["GICC0004"].pre_requisitos == "( GICC0003 )" and req["GICC0004"].apto is False
    assert req["GICC0004"].origem_pre_requisitos == OrigemRequisito.sigaa and req["GICC0004"].origem_sequencia is None
    assert req["ZZZA11"].sequencia_apos == ["ZZZA10"] and req["ZZZA11"].origem_sequencia == OrigemRequisito.inferido
    cand = {x.codigo: x for x in plano.candidatos}
    assert cand["ZZZA11"].apto is False and cand["ZZZA11"].faltando == ["ZZZA10"] and cand["ZZZA11"].origem_sequencia == OrigemRequisito.inferido
    assert cand["ZZZA11"].alternativas == [] and cand["ZZZA11"].faltando_minimo == ["ZZZA10"]
    assert cand["ZZZA01"].alternativas == [["ZZZA00"]] and cand["ZZZA01"].faltando_minimo == []
    assert cand["ZZZA10"].apto is True and cand["ZZZA10"].desbloqueia == ["ZZZA11"]
    assert cand["ZZZA01"].apto is True
    assert any("Atividades obrigatórias" in a and "GICC0003" in a for a in plano.avisos)
    assert not any("SEM turma" in a and "GICC" in a for a in plano.avisos)
    # a sugestão não põe Lab I e Lab II no mesmo semestre
    s = PL.sugerir(plano, _grade())
    assert [i.codigo for i in s.itens] == ["ZZZA10", "ZZZA01"]


def test_planejamento_periodo_sem_reserva_avisa(planejador):
    plano = asyncio.run(PL.planejamento(planejador, 2025, 1))
    assert any("2025.2" in a and "reserva" in a for a in plano.avisos)


def test_previsao_oferta(planejador):
    prev = asyncio.run(PL.previsao_oferta(planejador))
    assert prev.alvo == "2027.1" and prev.periodo_atual == "2026.2" and prev.desde == "2023.1"
    por = {x.codigo: x for x in prev.componentes}
    assert set(por) == {"GICC0003", "GICC0004", "ZZZA10", "ZZZA11", "ZZZA01"}  # aprovado fica fora
    assert por["ZZZA01"].resumo.paridade == Paridade.par and por["ZZZA01"].previsao.provavel is False
    assert por["ZZZA10"].previsao.provavel is True and por["ZZZA11"].resumo.paridade == Paridade.impar
    tcc = por["GICC0004"]
    assert tcc.sem_turma and tcc.previsao.provavel is None and tcc.requisito.pre_requisitos == "( GICC0003 )"
    # ATIVIDADE sem turma: a paridade não se aplica (null) — 0.0 é só pra "analisou e nunca abriu"
    assert tcc.resumo.chance_impar is None and tcc.resumo.chance_par is None and tcc.resumo.frequencia is None
    assert tcc.previsao.probabilidade is None and tcc.resumo.periodos_analisados  # a janela continua informada
    assert tcc.requisito.alternativas == [["GICC0003"]] and tcc.requisito.faltando_minimo == ["GICC0003"]
    assert por["ZZZA01"].resumo.chance_impar == 0.0 and por["ZZZA01"].resumo.chance_par == 1.0  # disciplina: 0.0 de verdade
    assert por["ZZZA11"].requisito.sequencia_apos == ["ZZZA10"]
    assert set(prev.provaveis) == {"ZZZA10", "ZZZA11"} and "ZZZA01" in prev.improvaveis
    assert {"GICC0003", "GICC0004"} <= set(prev.sem_historico)
    alvo_par = asyncio.run(PL.previsao_oferta(planejador, alvo="2027.2"))
    assert "ZZZA01" in alvo_par.provaveis and "ZZZA11" in alvo_par.improvaveis


# ------------------------------------------------------------------ rotas e cache
class _CliFake:
    _sem_cache_compartilhado = True

    async def executar(self, fluxo):
        return await fluxo(self)

    async def paralelo(self, fluxos):
        return [await f(self) for f in fluxos]


@pytest.fixture
def api_fake(monkeypatch):
    from fastapi.testclient import TestClient

    from api import deps
    from api.main import app
    from sigaa.cache import cache

    async def turmas(c, codigo):
        if codigo == "QUEBRA1":
            raise RuntimeError("SIGAA fora")
        return _bruto_fixture() if codigo == "MATA37" else TurmasDoComponente(componente=codigo, periodo_atual="2026.2", turmas=[])

    monkeypatch.setattr(O, "turmas_do_componente", turmas)
    monkeypatch.setattr(cache, "ligado", False)  # o middleware passa direto (sem sessão real pra identificar)
    app.dependency_overrides[deps._cliente] = lambda: _CliFake()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(deps._cliente, None)


def test_rota_historico_nao_cai_no_turma_id(api_fake):
    r = api_fake.get("/v1/consultas/turmas/historico", params={"componente": "mata37", "alvo": "2027.1"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["componente"] == "MATA37" and j["resumo"]["paridade"] == "ambos" and len(j["periodos"]) == 8
    assert j["previsao"]["periodo"] == "2027.1" and j["periodos"][0]["turmas"]
    r = api_fake.get("/v1/consultas/turmas/historico/lote", params={"componentes": "MATA37,GICC0004,QUEBRA1"})
    assert r.status_code == 200, r.text
    lote = {x["componente"]: x for x in r.json()}
    assert lote["MATA37"]["periodos"][0]["turmas"] == []  # lote: incluir_turmas=false por padrão
    assert lote["GICC0004"]["resumo"]["paridade"] == "sem_oferta"
    assert "SIGAA fora" in lote["QUEBRA1"]["avisos"][0]  # um componente quebrado não derruba o lote
    assert api_fake.get("/v1/consultas/turmas/historico", params={"componente": "MATA37", "desde": "2025-1"}).status_code == 422
    assert api_fake.get("/v1/consultas/turmas/historico", params={"componente": "MA'37"}).status_code == 422
    assert api_fake.get("/v1/consultas/turmas/historico/lote", params={"componentes": ",".join(f"ZZZA{i:02d}" for i in range(41))}).status_code == 422


def test_politicas_de_cache_das_rotas_novas():
    from api import cache as C

    h = C.politica("/v1/consultas/turmas/historico", {"componente": "MATC73"})
    assert h.escopo == C.COMPARTILHADO and h.ttl == 6 * 3600 and h.swr == 7 * 86400
    assert C.politica("/v1/consultas/turmas/historico/lote", {}).escopo == C.COMPARTILHADO
    assert C.politica("/v1/consultas/turmas/123", {}).ttl == 5 * 60  # vagas: continua curto
    assert C.politica("/v1/consultas/turmas", {}).ttl == 10 * 60
    assert C.politica("/v1/planejamento/previsao-oferta", {}).escopo == C.ALUNO  # usa a grade DO aluno


def test_rotas_novas_no_openapi_e_exigem_login():
    from fastapi.testclient import TestClient

    from api.main import app

    assert TestClient(app).get("/v1/consultas/turmas/historico", params={"componente": "MATC73"}).status_code == 401
    caminhos = app.openapi()["paths"]
    assert {"/v1/consultas/turmas/historico", "/v1/consultas/turmas/historico/lote", "/v1/planejamento/previsao-oferta"} <= set(caminhos)
