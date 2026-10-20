"""Oferta HISTÓRICA de turmas por componente (pra prever a oferta por paridade) e a previsão
aplicada aos pendentes do aluno."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from .consultas import TurmaOferta


class Paridade(str, Enum):
    impar = "impar"
    par = "par"
    ambos = "ambos"
    sem_oferta = "sem_oferta"


class Confianca(str, Enum):
    alta = "alta"
    media = "media"
    baixa = "baixa"
    sem_dados = "sem_dados"


class OrigemRequisito(str, Enum):
    sigaa = "sigaa"
    inferido = "inferido"


class TurmasDoComponente(BaseModel):
    """O que a busca de turmas do SIGAA devolve pra UM componente sem filtro de ano/período (todos os
    períodos que o SIGAA guarda). É o valor do cache compartilhado (L2)."""

    componente: str = Field(description="Código pesquisado.")
    periodo_atual: str | None = Field(None, description="Período que o SIGAA pré-preenche na consulta (o período corrente), ex.: '2026.2'.")
    turmas: list[TurmaOferta] = Field(default_factory=list, description="Todas as turmas encontradas, de todos os períodos.")


class OfertaPeriodo(BaseModel):
    periodo: str = Field(description="Ano.período, ex.: '2025.1'.")
    ano: int
    numero: int = Field(description="Número do período (1, 2; 3/4 = períodos especiais).")
    total_turmas: int
    total_vagas: int | None = Field(None, description="Soma das capacidades (None se o SIGAA não informou).")
    total_matriculados: int | None = None
    docentes: list[str] = Field(default_factory=list, description="Docentes distintos do período.")
    reserva_para_o_curso: bool | None = Field(
        None,
        description="Só com `curso`: alguma turma do período tinha vaga reservada pro curso. None = o SIGAA não tem "
        "dado de reserva desse período (antes de 2025.2) ou `curso` não foi informado.",
    )
    turmas: list[TurmaOferta] = Field(default_factory=list, description="As turmas (turma, docentes, horário, local, vagas). Vazio com `incluir_turmas=false`.")


class ResumoOferta(BaseModel):
    periodos_analisados: list[str] = Field(description="Períodos regulares (x.1/x.2) da janela analisada, do mais antigo ao mais novo.")
    periodos_com_oferta: list[str] = Field(description="Períodos regulares em que houve ao menos uma turma.")
    periodos_sem_oferta: list[str] = Field(description="Períodos regulares da janela sem nenhuma turma.")
    periodos_especiais: list[str] = Field(default_factory=list, description="Períodos 3/4 (férias/especiais) com turma — fora da paridade.")
    paridade: Paridade = Field(description="impar = só abriu em x.1; par = só em x.2; ambos; sem_oferta.")
    ofertas_impar: int = Field(description="Quantos semestres ímpares da janela tiveram turma.")
    ofertas_par: int
    impares_analisados: int
    pares_analisados: int
    frequencia: float | None = Field(None, description="Fração dos períodos regulares analisados com oferta (0–1).")
    frequencia_impar: float | None = None
    frequencia_par: float | None = None
    chance_impar: float | None = Field(
        None, description="Frequência PONDERADA nos semestres ímpares: os 2 mais recentes valem o dobro (o padrão muda com o currículo)."
    )
    chance_par: float | None = None
    tendencia: Literal["impar", "par", "ambos", "irregular", "sem_oferta"] = Field(
        "sem_oferta",
        description="Pela chance ponderada (≥ 0,5 = tende a abrir): impar, par, ambos; irregular = abriu, mas abaixo de 0,5 nos dois lados.",
    )
    ultima_oferta: str | None = Field(None, description="Último período com turma.")
    primeira_oferta: str | None = None
    media_turmas_por_oferta: float | None = None
    media_vagas_por_oferta: float | None = None


class PrevisaoPeriodo(BaseModel):
    periodo: str = Field(description="Período previsto, ex.: '2027.1'.")
    provavel: bool | None = Field(None, description="Tende a abrir? None = sem histórico pra dizer.")
    probabilidade: float | None = Field(
        None, description="Frequência nos semestres da MESMA paridade, com peso 2 pros 2 mais recentes (0–1). `provavel` = ≥ 0,5."
    )
    confianca: Confianca = Field(description="alta: ≥3 semestres da mesma paridade observados; media: 2; baixa: 1; sem_dados: 0.")
    ja_publicada: bool = Field(False, description="O SIGAA já mostra turma desse período (então não é previsão: é oferta).")
    motivo: str = Field(description="Explicação em português.")


class HistoricoOferta(BaseModel):
    componente: str = Field(description="Código do componente.")
    nome: str | None = None
    desde: str = Field(description="Início da janela analisada (o SIGAA da UFBA só guarda turmas a partir de 2023.1).")
    ate: str | None = Field(None, description="Fim da janela (período atual do SIGAA, ou o último período publicado se for depois).")
    curso: int | None = Field(None, description="Id do curso (de /v1/consultas/cursos/ids) usado pra marcar a reserva de vagas.")
    periodos: list[OfertaPeriodo] = Field(description="Só os períodos com turma, do mais antigo ao mais novo.")
    resumo: ResumoOferta
    previsao: PrevisaoPeriodo | None = Field(None, description="Previsão pro `alvo` (padrão: o período seguinte ao atual).")
    avisos: list[str] = Field(default_factory=list)


class RequisitoComponente(BaseModel):
    """Pré/co-requisitos de um componente pendente — inclusive os que não têm turma no período
    (TCC, estágio e outras ATIVIDADES não aparecem na oferta de turmas)."""

    codigo: str
    nome: str | None = None
    tipo: str | None = Field(None, description="DISCIPLINA, ATIVIDADE... (ATIVIDADE não tem turma: a matrícula é feita pelo colegiado/orientador).")
    natureza: str | None = Field(None, description="OBRIGATORIO / OPTATIVO.")
    semestre_ideal: int | None = None
    pre_requisitos: str | None = Field(None, description="Expressão do SIGAA, ex.: '( GICC0003 )'.")
    co_requisitos: str | None = None
    sequencia_apos: list[str] = Field(
        default_factory=list,
        description="Componentes que precisam vir ANTES por SEQUÊNCIA (I → II → III do mesmo prefixo e natureza) "
        "e que o SIGAA não lista no pré-requisito. Só aparece quando `origem_sequencia='inferido'`.",
    )
    origem_pre_requisitos: OrigemRequisito | None = Field(None, description="'sigaa' = veio do componente no SIGAA; None = não foi possível ler.")
    origem_sequencia: OrigemRequisito | None = Field(None, description="'inferido' quando `sequencia_apos` foi deduzido pelo nome/código.")
    apto: bool | None = Field(None, description="Pré-requisitos (e sequência inferida) cumpridos? None = não deu pra verificar.")
    faltando: list[str] = Field(default_factory=list, description="Códigos que faltam (pré-requisito e/ou sequência).")


class PrevisaoComponente(BaseModel):
    codigo: str
    nome: str | None = None
    natureza: str | None = None
    semestre_ideal: int | None = None
    tipo: str | None = None
    sem_turma: bool = Field(False, description="ATIVIDADE (TCC, estágio...): não tem turma na consulta; a paridade não se aplica.")
    requisito: RequisitoComponente
    resumo: ResumoOferta | None = None
    previsao: PrevisaoPeriodo | None = None
    erro: str | None = Field(None, description="Se não foi possível ler o histórico deste componente.")


class PrevisaoOfertaAluno(BaseModel):
    alvo: str = Field(description="Período previsto.")
    desde: str
    periodo_atual: str | None = None
    componentes: list[PrevisaoComponente]
    provaveis: list[str] = Field(default_factory=list, description="Pendentes que tendem a abrir no alvo.")
    improvaveis: list[str] = Field(default_factory=list, description="Pendentes que historicamente NÃO abrem na paridade do alvo.")
    sem_historico: list[str] = Field(default_factory=list, description="Pendentes sem turma nenhuma desde `desde` (inclui ATIVIDADES).")
    avisos: list[str] = Field(default_factory=list)
