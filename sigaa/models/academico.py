"""Modelos da vida acadêmica do aluno: histórico, índices, integralização, matrícula, documentos."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- histórico
class Docente(BaseModel):
    nome: str = Field(description="Nome do docente como aparece no documento (sem o título).")
    titulo: str | None = Field(None, description="Titulação abreviada: Dr., Dra., MSc., Esp. ...")
    carga_horaria: int | None = Field(None, description="Horas que o docente ministrou na turma.")


class ComponenteCursado(BaseModel):
    periodo: str = Field(description="Ano.período letivo, ex.: 2024.2")
    codigo: str = Field(description="Código do componente, ex.: MATA37")
    nome: str = Field(description="Nome do componente (o PDF do SIGAA corta nomes muito longos).")
    natureza: str | None = Field(None, description="Sigla da natureza: OB, OP, EB, EP, LV, EC... (vazio quando o SIGAA não informa)")
    natureza_descricao: str | None = Field(None, description="Natureza por extenso, conforme a legenda do histórico.")
    carga_horaria: int | None = Field(None, description="Carga horária em horas.")
    nota: float | None = Field(None, description="Nota final (None quando '--').")
    frequencia: float | None = Field(None, description="Frequência em % quando o histórico traz a coluna.")
    situacao: str = Field(description="Sigla da situação: APR, REP, REPF, REPMF, TRANC, MATR, DISP, CANC, TRANS, INCORP, CUMP...")
    situacao_descricao: str | None = Field(None, description="Situação por extenso, conforme a legenda.")
    aprovado: bool = Field(description="True para APR, DISP, INCORP, CUMP, TRANS (componente integralizado).")
    cursando: bool = Field(description="True quando a situação é MATR (matriculado no período atual).")
    docentes: list[Docente] = Field(default_factory=list)
    marcadores: list[str] = Field(default_factory=list, description="Símbolos extras ao lado da linha (*, @, &...), quando houver.")


class Indices(BaseModel):
    cr: float | None = Field(None, description="Coeficiente de Rendimento.")
    iap: float | None = Field(None, description="Índice de Aproveitamento (IAP) — como o SIGAA da UFBA chama.")
    outros: dict[str, float] = Field(default_factory=dict, description="Qualquer outro índice que o histórico trouxer (MC, IRA, IECH...).")


class DadosPessoaisHistorico(BaseModel):
    nome: str | None = None
    matricula: str | None = None
    data_nascimento: date | None = None
    local_nascimento: str | None = None
    nacionalidade: str | None = None
    documento_identidade: str | None = Field(None, description="Número do RG como no documento.")
    orgao_expedidor: str | None = None
    cpf: str | None = None


class VinculoHistorico(BaseModel):
    curso: str | None = None
    status: str | None = None
    enfase: str | None = None
    curriculo: str | None = Field(None, description="Código da estrutura curricular, ex.: T20252 - 2025.2")
    reconhecimento_curso: str | None = None
    ingresso_periodo: str | None = Field(None, description="Período de ingresso, ex.: 2022.1")
    ingresso_data: date | None = None
    perfil_inicial: int | None = None
    forma_ingresso: str | None = Field(None, description="Sisu, Transferência, Portador de diploma...")
    periodo_letivo_atual: int | None = Field(None, description="Quantos períodos letivos o aluno já cursou (semestre corrente).")
    prazo_conclusao_padrao: str | None = None
    prazo_conclusao_maximo: str | None = None
    suspensoes: list[str] = Field(default_factory=list, description="Períodos de suspensão de programa.")
    prorrogacoes: str | None = None
    conclusao: str | None = None
    tipo_saida: str | None = None
    data_conclusao: str | None = None
    data_colacao_grau: str | None = None
    trabalho_conclusao_curso: str | None = None
    data_expedicao_diploma: str | None = None
    campos_extras: dict[str, str] = Field(default_factory=dict, description="Rótulos do bloco de vínculo que a API ainda não conhece.")


class CargaHorariaCategoria(BaseModel):
    categoria: str = Field(description="Obrigatórias, Optativos, Complementares, Total...")
    exigido: int | None = None
    integralizado: int | None = None
    pendente: int | None = None


class AtividadeAutonomaResumo(BaseModel):
    categoria: str
    carga_horaria: float


class CargaExtensionista(BaseModel):
    descricao: str
    periodo: str | None = Field(None, description="Data ou período como impresso.")
    carga_horaria: int | None = None


class ComponentePendente(BaseModel):
    codigo: str
    nome: str
    carga_horaria: int | None = None
    matriculado: bool = Field(False, description="True quando o aluno já está matriculado nele no período atual.")


class ComponenteRef(BaseModel):
    codigo: str
    nome: str | None = None
    carga_horaria: int | None = None


class Equivalencia(BaseModel):
    tipo: str = Field(description="Como o SIGAA descreve: 'Cumpriu'...")
    componente: ComponenteRef = Field(description="Componente do currículo que foi cumprido.")
    atraves_de: list[ComponenteRef] = Field(description="Componente(s) cursado(s) que valeram por ele.")
    texto: str = Field(description="Linha original do histórico.")


class EstatisticaPeriodo(BaseModel):
    periodo: str
    componentes: int
    carga_horaria: int
    carga_horaria_aprovada: int
    aprovados: int
    reprovados: int
    trancados: int
    cursando: int
    cr_periodo: float | None = Field(None, description="CR só deste período (mesma regra do CR oficial).")
    cr_acumulado: float | None = Field(None, description="CR acumulado até o fim deste período — a evolução do CR.")
    iap_acumulado: float | None = Field(None, description="IAP acumulado até o fim deste período.")


class EstatisticasHistorico(BaseModel):
    por_periodo: list[EstatisticaPeriodo]
    total_componentes: int
    total_aprovados: int
    total_reprovados: int
    total_trancados: int
    total_cursando: int
    carga_horaria_aprovada: int
    cr_calculado: float | None = Field(
        None, description="CR recalculado pela API: Σ(nota×CH)/Σ(CH) dos componentes com nota, sem reprovação por falta."
    )
    iap_calculado: float | None = Field(
        None, description="IAP recalculado: CH aprovada / CH de todos os componentes encerrados (trancados contam)."
    )
    calculo_confere_com_oficial: bool | None = Field(
        None, description="True se o CR/IAP recalculados batem com os do histórico — garante que a evolução por período é confiável."
    )
    taxa_aprovacao: float | None = Field(None, description="Aprovados / (aprovados + reprovados), de 0 a 1.")


class Legenda(BaseModel):
    naturezas: dict[str, str] = Field(default_factory=dict)
    situacoes: dict[str, str] = Field(default_factory=dict)


class Historico(BaseModel):
    instituicao: str | None = None
    emitido_em: datetime | None = None
    codigo_verificacao: str | None = Field(None, description="Código pra validar o documento em /sigaa/documentos.")
    url_verificacao: str | None = None
    dados_pessoais: DadosPessoaisHistorico
    vinculo: VinculoHistorico
    indices: Indices
    componentes: list[ComponenteCursado]
    atividades_autonomas: list[AtividadeAutonomaResumo] = Field(default_factory=list)
    carga_horaria: list[CargaHorariaCategoria] = Field(default_factory=list, description="Exigido × integralizado × pendente por categoria.")
    carga_horaria_extensionista: list[CargaExtensionista] = Field(default_factory=list)
    obrigatorios_pendentes: list[ComponentePendente] = Field(default_factory=list)
    total_obrigatorios_pendentes: int | None = Field(None, description="Total que o próprio SIGAA declara no título da seção.")
    equivalencias: list[Equivalencia] = Field(default_factory=list)
    observacoes: list[str] = Field(default_factory=list)
    legenda: Legenda = Field(default_factory=Legenda)
    estatisticas: EstatisticasHistorico | None = None
    linhas_nao_reconhecidas: list[str] = Field(default_factory=list, description="Linhas que o parser não soube classificar (ajuda a reportar variações).")


# --------------------------------------------------------------- matrícula atual
class HorarioSlot(BaseModel):
    dia: str = Field(description="Dia da semana por extenso, ex.: Terça")
    inicio: str = Field(description="HH:MM")
    fim: str = Field(description="HH:MM")
    local: str | None = None


class TurmaMatricula(BaseModel):
    turma_id: int | None = Field(None, description="idTurma do SIGAA (o mesmo de /v1/turmas/{turma_id}), quando a tela expõe.")
    codigo: str
    componente: str
    carga_horaria: int | None = None
    turma: str | None = Field(None, description="Código da turma, ex.: 01")
    docentes: list[str] = Field(default_factory=list)
    tipo: str | None = Field(None, description="DISCIPLINA, ATIVIDADE...")
    local: str | None = None
    horario_codigo: str | None = Field(None, description="Código SIGAA do horário, ex.: 35N12")
    horario_periodo: str | None = Field(None, description="Vigência impressa ao lado do horário.")
    horarios: list[HorarioSlot] = Field(default_factory=list, description="Horários detalhados quando a tela traz (dia, início, fim, sala).")
    situacao: str = Field(description="MATRICULADO, INDEFERIDO, DEFERIDA, TRANCADO, ...")
    rematricula: bool = False


class GradeCelula(BaseModel):
    horario: str = Field(description="Faixa, ex.: 18:30 - 19:25")
    dia: str
    slot: int | None = Field(None, description="Número do horário no SIGAA (1-6 manhã, 7-12 tarde, 13-16 noite na UFBA).")
    conteudo: str | None = Field(None, description="Código(s) das turmas naquele horário.")


class ComprovanteMatricula(BaseModel):
    titulo: str = Field(description="Título do documento como o SIGAA imprime.")
    numero: str | None = Field(None, description="Número do comprovante de solicitação, quando houver.")
    emitido_em: datetime | None = None
    periodo: str | None = None
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    matricula: str | None = None
    nome: str | None = None
    curso: str | None = None
    nivel: str | None = None
    status: str | None = None
    vinculo: str | None = Field(None, description="REGULAR, ESPECIAL...")
    turmas: list[TurmaMatricula]
    total_matriculadas: int | None = None
    grade: list[GradeCelula] = Field(default_factory=list, description="Grade semanal impressa no comprovante (só as células ocupadas).")


# ------------------------------------------------------------- outras consultas
class Trancamento(BaseModel):
    periodo: str
    componente_codigo: str | None = None
    componente_nome: str | None = None
    turma: str | None = None
    status: str
    data_solicitacao: date | None = None
    data_visto_coordenador: date | None = None
    motivo: str | None = None


class AtividadeAutonoma(BaseModel):
    id: int | None = Field(None, description="Id do registro (use em /v1/atividades-autonomas/{id}).")
    categoria: str = Field(description="Grupo: ATIVIDADES DE ENSINO, EXTENSÃO CURRICULAR...")
    data: date | None = None
    tipo: str | None = None
    descricao: str | None = None
    carga_horaria: float | None = None
    status: str | None = Field(None, description="ACEITO, REJEITADO, PENDENTE...")


class GrupoAtividadesAutonomas(BaseModel):
    categoria: str
    registros: list[AtividadeAutonoma]
    carga_horaria_aprovada: float | None = None


class AtividadesAutonomas(BaseModel):
    total_registros: int | None = None
    grupos: list[GrupoAtividadesAutonomas]


class ItemLista(BaseModel):
    """Linha genérica de uma listagem do SIGAA (quando a tela é simples)."""

    campos: dict[str, str | None]


class ListaGenerica(BaseModel):
    titulo: str | None = None
    vazio: bool = Field(description="True quando o SIGAA disse que não há registros.")
    mensagem: str | None = Field(None, description="Mensagem do SIGAA (ex.: 'Nenhum diploma digital encontrado.').")
    itens: list[ItemLista] = Field(default_factory=list)


class Integralizacao(BaseModel):
    curriculo: str | None = None
    percentual: float | None = Field(None, description="% integralizado (CH integralizada / CH exigida total).")
    carga_horaria: list[CargaHorariaCategoria]
    obrigatorios_pendentes: list[ComponentePendente]
    atividades_autonomas: list[AtividadeAutonomaResumo]
    carga_horaria_extensionista: list[CargaExtensionista]
    periodo_letivo_atual: int | None = None
    prazo_conclusao_padrao: str | None = None
    prazo_conclusao_maximo: str | None = None


class VagasCurso(BaseModel):
    curso: str
    reservadas_ingressantes: int | None = None
    demais_alunos: int | None = Field(None, description="Vagas restantes pra demais alunos (o SIGAA mostra negativo quando estourou).")


class GrupoProcessamento(BaseModel):
    grupo: str = Field(description="Curso/grupo de prioridade em que os solicitantes foram ranqueados.")
    solicitantes: int
    matriculados: int
    indeferidos: int


class MinhaPosicao(BaseModel):
    grupo: str
    posicao: int = Field(description="Posição do aluno no ranking do grupo.")
    total_no_grupo: int
    situacao: str
    prioridade: str | None = Field(None, description="Faixa de prioridade (I, II, III...).")


class ResultadoProcessamento(BaseModel):
    """Resultado do processamento de (re)matrícula de UMA turma.

    Por privacidade a API NÃO devolve nome nem matrícula dos outros alunos: só contagens e a posição do próprio aluno."""

    turma_id: int
    rematricula: bool = False
    componente_codigo: str | None = None
    componente_nome: str | None = None
    turma: str | None = None
    horario_codigo: str | None = None
    capacidade: int | None = None
    vagas: list[VagasCurso] = Field(default_factory=list)
    vagas_total_reservadas: int | None = None
    vagas_total_demais: int | None = None
    grupos: list[GrupoProcessamento] = Field(default_factory=list)
    minha_posicao: MinhaPosicao | None = None


class Movimentacao(BaseModel):
    tipo: str = Field(description="PRORROGAÇÃO ADMINISTRATIVA, TRANCAMENTO DE PROGRAMA, ...")
    periodo: str | None = None
    data: datetime | None = None
    observacao: str | None = None


class Suspensoes(BaseModel):
    solicitacoes: ListaGenerica
    movimentacoes: list[Movimentacao] = Field(default_factory=list, description="Histórico de movimentações do discente.")


class DeclaracaoVinculo(BaseModel):
    nome: str | None = None
    matricula: str | None = None
    curso: str | None = None
    local_data: str | None = Field(None, description="Linha 'Cidade, dd de Mês de aaaa.'")
    emitido_em: date | None = None
    codigo_verificacao: str | None = None
    url_verificacao: str | None = None
    orgao_emissor: str | None = None
    texto: str = Field(description="Texto integral da declaração.")


class OpcaoSelect(BaseModel):
    id: str = Field(description="Valor interno do SIGAA (use nos filtros).")
    nome: str


class FiltrosAvaliacao(BaseModel):
    departamentos: list[OpcaoSelect]
    periodos: list[OpcaoSelect] = Field(description="Ano-períodos com relatório disponível (o id NÃO é o ano-período; use o `nome` ou o `id`).")


class LinhaAvaliacao(BaseModel):
    docente: str
    componente_codigo: str | None = None
    componente_nome: str | None = None
    turma: str | None = None
    horario_codigo: str | None = None
    horario_periodo: str | None = None
    discentes: int | None = Field(None, description="Quantidade de discentes da turma.")
    atuacao_docente_media: float | None = Field(None, description="Média da atuação do docente (quando a instituição publica).")
    atuacao_docente_dp: float | None = None
    autoavaliacao_media: float | None = None
    autoavaliacao_dp: float | None = None


class ResultadoAvaliacao(BaseModel):
    departamento: str | None = None
    periodo: str | None = None
    linhas: list[LinhaAvaliacao]
    medias_publicadas: bool = Field(description="False quando o SIGAA só lista as turmas, sem as notas da avaliação (caso da UFBA hoje).")


class AtividadeAutonomaDetalhe(BaseModel):
    id: int
    tipo: str | None = Field(None, description="Categoria/tipo como o SIGAA mostra.")
    ch_maxima_tipo: float | None = Field(None, description="Teto de horas que esse tipo de atividade aceita (o número entre parênteses no tipo).")
    comprovante: str | None = Field(None, description="Nome do arquivo de comprovante enviado.")
    carga_horaria: float | None = None
    observacoes: str | None = None
    status: str | None = None
    parecer_coordenador: str | None = Field(None, description="Justificativa do coordenador (motivo da rejeição, quando houver).")
    campos_extras: dict[str, str] = Field(default_factory=dict)
