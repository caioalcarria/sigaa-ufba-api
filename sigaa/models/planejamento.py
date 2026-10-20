"""Planejamento acadêmico: grade curricular do aluno, oferta filtrada, simulação e sugestão de matrícula, horas."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .academico import AtividadeAutonoma, CargaExtensionista, CargaHorariaCategoria
from .consultas import HorarioAula
from .oferta import OrigemRequisito, RequisitoComponente


class StatusComponente(str, Enum):
    aprovado = "APROVADO"
    cursando = "CURSANDO"
    pendente = "PENDENTE"


class Tentativa(BaseModel):
    periodo: str
    codigo_cursado: str = Field(description="Código que o aluno cursou (pode ser um equivalente).")
    situacao: str
    nota: float | None = None


class ComponenteGrade(BaseModel):
    id: int | None = Field(None, description="Id do componente no SIGAA (/v1/publico/componentes/{id}).")
    codigo: str
    nome: str
    carga_horaria: int | None = None
    natureza: str = Field(description="OBRIGATORIO ou OPTATIVO (como a estrutura define).")
    semestre_ideal: int | None = Field(None, description="Semestre da estrutura; None para optativas.")
    status: StatusComponente
    cumprido_por: str | None = Field(None, description="Código pelo qual foi integralizado, quando foi por equivalência.")
    periodo_conclusao: str | None = None
    nota: float | None = None
    tentativas: list[Tentativa] = Field(default_factory=list, description="Todas as vezes que o aluno cursou/trancou este componente (ou equivalente).")
    reprovacoes: int = 0
    trancamentos: int = 0


class SemestreGrade(BaseModel):
    nome: str
    semestre: int | None
    carga_horaria: int
    carga_horaria_cumprida: int
    componentes: list[ComponenteGrade]


class GradeCurricular(BaseModel):
    estrutura_id: int | None = None
    estrutura_codigo: str | None = None
    matriz: str | None = None
    ch_total: int | None = None
    ch_obrigatoria: int | None = None
    ch_optativa: int | None = None
    ch_complementar: int | None = None
    ch_maxima_periodo: int | None = Field(None, description="Máximo de CH por período letivo (limite de matrícula).")
    prazos_semestres: dict[str, int | None] = Field(default_factory=dict)
    semestres: list[SemestreGrade] = Field(description="Componentes obrigatórios por semestre ideal.")
    optativas: list[ComponenteGrade] = Field(description="Componentes optativos da estrutura.")
    obrigatorias_pendentes: int
    obrigatorias_cumpridas: int
    optativas_cursadas_ch: int = Field(description="CH optativa já aprovada (pela estrutura).")
    semestre_mais_atrasado: int | None = Field(None, description="Menor semestre ideal com obrigatória pendente.")


class TurmaCandidata(BaseModel):
    turma_id: int | None
    codigo_turma: str | None
    docentes: list[str] = Field(default_factory=list)
    horario_codigo: str | None = None
    horarios: list[HorarioAula] = Field(default_factory=list)
    local: str | None = None
    capacidade: int | None = None
    matriculados: int | None = None
    vagas_livres: int | None = Field(None, description="capacidade − matriculados (pode ser ≤ 0: turma lotada).")
    situacao: str | None = None


class ComponenteCandidato(BaseModel):
    codigo: str
    nome: str
    componente_id: int | None = None
    carga_horaria: int | None = None
    natureza: str = Field(description="OBRIGATORIO, OPTATIVO ou FORA_DA_ESTRUTURA.")
    semestre_ideal: int | None = None
    atrasado: bool = Field(description="True se o semestre ideal já passou (semestre ideal < período letivo atual do aluno).")
    pre_requisitos: str | None = Field(None, description="Expressão do SIGAA, ex.: '(MATA55) E (MATA40 OU MATA57)'.")
    co_requisitos: str | None = None
    sequencia_apos: list[str] = Field(
        default_factory=list,
        description="Antecessor(es) por SEQUÊNCIA (I → II), regra inferida pelo nome/código. Só aparece quando o SIGAA NÃO "
        "cita o antecessor no pré-requisito (se cita, já está em `alternativas`).",
    )
    origem_sequencia: OrigemRequisito | None = Field(None, description="'inferido' quando `sequencia_apos` não veio do SIGAA.")
    apto: bool | None = Field(None, description="VEREDITO: pré-requisitos (e sequência inferida) cumpridos? Considera as equivalências do histórico (ex.: LETA09 cumprido por equivalência conta como cumprido) — leia isto, não a expressão em texto, que cita os códigos originais. None = não foi possível verificar.")
    faltando: list[str] = Field(
        default_factory=list,
        description="UNIÃO dos códigos ausentes de TODAS as alternativas da expressão (OU) — não é a lista do que falta "
        "cursar: com '(A) OU (B E C)' e nada cumprido vem [A, B, C], mas basta A. Pra isso use `faltando_minimo`/`alternativas`.",
    )
    alternativas: list[list[str]] = Field(
        default_factory=list,
        description="A expressão de pré-requisito já parseada em caminhos: cada item é uma alternativa E (cumprir todos os "
        "códigos dela basta). Ex.: '(MATC73) OU (MATA47 E MATA53 E MATE12)' → [[MATC73], [MATA47, MATA53, MATE12]]. "
        "Não inclui `sequencia_apos`. Vazio = sem pré-requisito (ou não lido).",
    )
    faltando_minimo: list[str] = Field(
        default_factory=list,
        description="O MENOR conjunto de códigos que ainda falta pra cumprir alguma alternativa, dado o que o aluno já tem "
        "(mais o antecessor de `sequencia_apos`, se faltar). Vazio quando `apto`.",
    )
    desbloqueia: list[str] = Field(default_factory=list, description="Componentes pendentes que têm este como pré-requisito.")
    reprovacoes_anteriores: int = 0
    turmas: list[TurmaCandidata]


class PlanejamentoMatricula(BaseModel):
    ano: int | None = None
    periodo: int | None = None
    curso: str | None = None
    considerou_cursando_como_aprovado: bool
    ch_maxima_periodo: int | None = None
    ch_pendente: list[CargaHorariaCategoria] = Field(default_factory=list)
    candidatos: list[ComponenteCandidato]
    total_ofertados_para_o_curso: int = Field(description="Componentes distintos com turma reservada pro curso no período.")
    requisitos: list[RequisitoComponente] = Field(
        default_factory=list,
        description="Pré/co-requisitos de TODOS os pendentes lidos — inclusive os sem turma no período (TCC, estágio e outras "
        "ATIVIDADES nunca aparecem em `candidatos`). Use isto pra montar o grafo de pré-requisitos.",
    )
    avisos: list[str] = Field(default_factory=list)


class Choque(BaseModel):
    turmas: list[str] = Field(description="Componentes/turmas em conflito.")
    dia: str
    horario: str = Field(description="Slot em conflito, ex.: N1 18:30-19:25")


class ItemSimulado(BaseModel):
    codigo: str
    turma: str | None = None
    turma_id: int | None = None
    carga_horaria: int | None = None
    apto: bool | None = None
    faltando: list[str] = Field(default_factory=list)
    ja_aprovado: bool = False
    natureza: str | None = None


class SimulacaoMatricula(BaseModel):
    itens: list[ItemSimulado]
    ch_total: int
    ch_maxima_periodo: int | None = None
    excede_ch_maxima: bool
    choques: list[Choque]
    problemas: list[str] = Field(description="Tudo que impediria/atrapalharia a matrícula, em português.")
    valida: bool = Field(description="True se não há choque, nem excesso de CH, nem pré-requisito faltando.")
    ch_obrigatoria_pendente_depois: int | None = None
    ch_optativa_pendente_depois: int | None = None
    percentual_integralizado_depois: float | None = None
    grade: dict[str, list[str]] = Field(default_factory=dict, description="Dia → lista 'HH:MM-HH:MM CODIGO'.")


class CargaHorariaGestao(BaseModel):
    """Gerenciamento de horas: o que o curso exige × o que já foi cumprido, por tipo de carga."""

    categorias: list[CargaHorariaCategoria]
    percentual_integralizado: float | None = None
    complementar_exigida: int | None = None
    complementar_integralizada: int | None = None
    complementar_pendente: int | None = None
    atividades_aceitas_ch: float = 0
    atividades_rejeitadas_ch: float = 0
    atividades_em_analise_ch: float = 0
    atividades: list[AtividadeAutonoma] = Field(default_factory=list)
    extensao: list[CargaExtensionista] = Field(default_factory=list)
    extensao_total_ch: int = 0
    dicas: list[str] = Field(default_factory=list)

