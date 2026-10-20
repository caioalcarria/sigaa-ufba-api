"""Planejamento acadêmico: grade curricular do aluno, oferta filtrada, simulação/sugestão de matrícula, horas."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from sigaa.models.oferta import PrevisaoOfertaAluno
from sigaa.models.planejamento import CargaHorariaGestao, GradeCurricular, PlanejamentoMatricula, SimulacaoMatricula
from sigaa.services import planejamento as svc

from ..deps import Cliente

router = APIRouter(prefix="/v1", tags=["Planejamento"])

DIAS = {"seg": 2, "ter": 3, "qua": 4, "qui": 5, "sex": 6, "sab": 7, "dom": 1}


def _lista(v: str | None) -> list[str]:
    return [x.strip().lower() for x in (v or "").split(",") if x.strip()]


@router.get(
    "/grade-curricular",
    response_model=GradeCurricular,
    summary="A grade curricular do aluno, marcada com o que já fez",
    description="Estrutura curricular do curso do aluno (semestre a semestre + optativas) cruzada com o histórico: "
    "cada componente vem APROVADO / CURSANDO / PENDENTE, com por qual código foi cumprido (equivalências), nota, "
    "tentativas, reprovações e trancamentos. Traz também a CH máxima por período e o semestre mais atrasado.",
)
async def get_grade_curricular(cli: Cliente):
    return await cli.executar(svc.grade_curricular)


@router.get(
    "/planejamento/matricula",
    response_model=PlanejamentoMatricula,
    summary="O que dá pra pegar no semestre (oferta × grade × histórico)",
    description="Turmas ofertadas com reserva pro curso do aluno, filtradas pelo que ele AINDA precisa cursar. Pra cada "
    "componente: natureza, semestre ideal, se está atrasado, pré/co-requisitos, se está APTO (e o que falta), quantos "
    "pendentes ele destrava, reprovações anteriores e as turmas (horário decodificado, local, docentes, vagas livres).\n\n"
    "Filtros: `natureza` (obrigatorio|optativo), `so_aptos`, `turnos` (M,T,N — só turmas inteiramente nesses turnos), "
    "`sem_dias` (seg,sab... — tira turmas com aula nesses dias), `com_vagas`. `considerar_cursando_como_aprovado` (padrão true) "
    "serve pra planejar o PRÓXIMO semestre assumindo aprovação no atual.",
)
async def get_planejamento(
    cli: Cliente,
    ano: int | None = None,
    periodo: int | None = None,
    natureza: Literal["obrigatorio", "optativo"] | None = None,
    so_aptos: bool = False,
    turnos: str | None = Query(None, description="Ex.: N ou T,N"),
    sem_dias: str | None = Query(None, description="Ex.: sab ou seg,sex"),
    com_vagas: bool = False,
    considerar_cursando_como_aprovado: bool = True,
):
    plano = await cli.executar(lambda c: svc.planejamento(c, ano, periodo, considerar_cursando_como_aprovado))
    tset = {t.upper() for t in _lista(turnos)}
    dset = {DIAS[d[:3]] for d in _lista(sem_dias) if d[:3] in DIAS}
    out = []
    for comp in plano.candidatos:
        if natureza and comp.natureza != natureza.upper():
            continue
        if so_aptos and comp.apto is not True:
            continue
        turmas = [
            t
            for t in comp.turmas
            if (not tset or all(h.turno in tset for h in t.horarios))
            and (not dset or not any(h.dia_numero in dset for h in t.horarios))
            and (not com_vagas or t.vagas_livres is None or t.vagas_livres > 0)
        ]
        if turmas:
            out.append(comp.model_copy(update={"turmas": turmas}))
    return plano.model_copy(update={"candidatos": out})


@router.get(
    "/planejamento/previsao-oferta",
    response_model=PrevisaoOfertaAluno,
    summary="Previsão de oferta dos pendentes do aluno (por paridade, com o histórico do SIGAA)",
    description="Pra cada componente PENDENTE da grade do aluno (obrigatórios; `incluir_optativas=true` traz as optativas): "
    "o padrão histórico de oferta desde `desde` (paridade, frequência, última oferta), a previsão pro `alvo` (padrão: o "
    "período seguinte ao atual) e os pré/co-requisitos — do SIGAA e, quando o SIGAA não cita, a SEQUÊNCIA I → II "
    "inferida pelo nome/código (`origem_sequencia='inferido'`). ATIVIDADES sem turma (TCC, estágio) vêm com "
    "`sem_turma=true`: a matrícula delas é pelo colegiado. O histórico de cada componente vem do cache compartilhado.",
)
async def get_previsao_oferta(
    cli: Cliente,
    alvo: str | None = Query(None, pattern=r"^\d{4}\.[1-4]$", description="Período a prever, ex.: 2027.1"),
    desde: str | None = Query(None, pattern=r"^\d{4}\.[1-4]$", description="Início da janela (mínimo 2023.1)"),
    incluir_optativas: bool = False,
    considerar_cursando_como_aprovado: bool = True,
):
    return await cli.executar(lambda c: svc.previsao_oferta(c, alvo, desde, incluir_optativas, considerar_cursando_como_aprovado))


class EscolhaTurma(BaseModel):
    codigo: str | None = Field(None, description="Código do componente (ex.: MATA63).")
    turma: str | None = Field(None, description="Código da turma (ex.: 01). Omitido = a primeira ofertada.")
    turma_id: int | None = Field(None, description="Ou o id da turma no SIGAA.")


class SimulacaoRequest(BaseModel):
    turmas: list[EscolhaTurma]
    ano: int | None = None
    periodo: int | None = None
    considerar_cursando_como_aprovado: bool = True


@router.post(
    "/planejamento/simular",
    response_model=SimulacaoMatricula,
    summary="Simular uma matrícula (choques, CH máxima, pré-requisitos, integralização)",
    description="Recebe as turmas que o aluno pensa em pegar e devolve: choques de horário, se passa da CH máxima do período, "
    "pré-requisitos faltando, turmas lotadas, a grade semanal resultante e como fica a integralização. Nada é enviado ao SIGAA.",
)
async def post_simular(cli: Cliente, corpo: SimulacaoRequest):
    async def fluxo(c):
        plano = await svc.planejamento(c, corpo.ano, corpo.periodo, corpo.considerar_cursando_como_aprovado)
        grade = await svc.grade_curricular(c)
        escolhas = [(str(e.turma_id), None) if e.turma_id else ((e.codigo or "").upper(), e.turma) for e in corpo.turmas]
        return svc.simular(plano, escolhas, grade)

    return await cli.executar(fluxo)


@router.get(
    "/planejamento/sugestao",
    response_model=SimulacaoMatricula,
    summary="Sugestão automática de matrícula sem choque",
    description="Monta uma combinação gulosa: obrigatórias aptas primeiro (as mais atrasadas e as que destravam mais pendentes), "
    "depois optativas aptas, sem choque de horário, até a CH máxima. É um ponto de partida — a decisão é do aluno.",
)
async def get_sugestao(
    cli: Cliente,
    ch_maxima: int | None = None,
    turnos: str | None = Query(None, description="Ex.: N — só turmas no noturno"),
    incluir_optativas: bool = True,
    evitar_lotadas: bool = True,
    ano: int | None = None,
    periodo: int | None = None,
):
    async def fluxo(c):
        plano = await svc.planejamento(c, ano, periodo)
        grade = await svc.grade_curricular(c)
        tset = {t.upper() for t in _lista(turnos)} or None
        return svc.sugerir(plano, grade, ch_maxima, tset, incluir_optativas, evitar_lotadas)

    return await cli.executar(fluxo)


@router.get(
    "/carga-horaria",
    response_model=CargaHorariaGestao,
    summary="Gerenciamento de horas (obrigatória, optativa, complementar, extensão)",
    description="CH exigida × integralizada × pendente por categoria, as atividades autônomas registradas (aceitas, rejeitadas, "
    "em análise), a CH extensionista e dicas do que falta.",
)
async def get_carga_horaria(cli: Cliente):
    return await cli.executar(svc.gestao_horas)
