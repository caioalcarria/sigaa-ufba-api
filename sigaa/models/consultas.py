"""Modelos da área "consultas" (logada): Consultas Gerais do Portal do Discente, Calendário
Acadêmico (salas livres ficam na frente "portal").

Os modelos do SIGAA *público* (sem login) ficam em ``sigaa/models/consultas_publico.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# ---------------------------------------------------------------- comuns


class Intervalo(BaseModel):
    """Um intervalo de datas do SIGAA ("De 19/08/2026 até 19/12/2026" / "Não Definido")."""

    inicio: date | None = Field(None, description="Primeiro dia (ISO 8601). `null` se não definido.")
    fim: date | None = Field(None, description="Último dia (ISO 8601). `null` se não definido.")
    definido: bool = Field(False, description="`false` quando o SIGAA mostra 'Não Definido'.")
    texto: str | None = Field(None, description="Texto cru exibido pelo SIGAA.")


class Pagina(BaseModel, Generic[T]):
    """Envelope de paginação das listas (``?pagina=&por_pagina=``)."""

    itens: list[T] = Field(default_factory=list, description="Itens desta página.")
    total: int = Field(0, description="Total de itens (todas as páginas).")
    pagina: int = Field(1, description="Página atual (começa em 1).")
    por_pagina: int = Field(50, description="Itens por página.")
    paginas: int = Field(0, description="Total de páginas.")

    @classmethod
    def de(cls, itens: list, pagina: int, por_pagina: int) -> "Pagina":
        total = len(itens)
        ini = (pagina - 1) * por_pagina
        return cls(itens=itens[ini : ini + por_pagina], total=total, pagina=pagina, por_pagina=por_pagina, paginas=-(-total // por_pagina))


class Opcao(BaseModel):
    """Uma opção de um combo de filtro do SIGAA (unidade, curso, prédio, tipo...)."""

    id: str = Field(description="Valor enviado ao SIGAA (geralmente o id numérico, às vezes uma letra).")
    nome: str = Field(description="Texto exibido.")


# ------------------------------------------------------------- calendário


class CalendarioResumo(BaseModel):
    id: int = Field(description="Id do calendário no SIGAA (estável).")
    ano: int = Field(description="Ano letivo.")
    periodo: int = Field(description="Período letivo (1, 2...).")
    tipo: str = Field(description="Tipo do calendário como o SIGAA mostra: 'CALENDÁRIO GERAL', 'ENSINO A DISTÂNCIA'...")
    ead: bool = Field(description="`true` se for o calendário de Ensino a Distância.")


class EventoCalendario(BaseModel):
    rotulo: str = Field(description="Nome do evento como no SIGAA (ex.: 'Matrícula OnLine', 'Trancamento de Turmas').")
    grupo: str | None = Field(None, description="Seção onde o evento aparece (ex.: 'Datas para Turmas Regulares').")
    inicio: date | None = Field(None, description="Início (ISO 8601) ou `null` se não definido.")
    fim: date | None = Field(None, description="Fim (ISO 8601) ou `null` se não definido.")
    definido: bool = Field(False, description="`false` quando o SIGAA mostra 'Não Definido'.")
    texto: str | None = Field(None, description="Texto cru da célula.")


class Calendario(BaseModel):
    id: int | None = Field(None, description="Id do calendário no SIGAA.")
    ano: int | None = Field(None, description="Ano letivo.")
    periodo: int | None = Field(None, description="Período letivo.")
    tipo: str | None = Field(None, description="'CALENDÁRIO GERAL', 'ENSINO A DISTÂNCIA'...")
    unidade_responsavel: str | None = Field(None, description="Unidade responsável pelo calendário.")
    nivel: str | None = Field(None, description="Nível de ensino (ex.: 'GRADUAÇÃO').")
    vigente: bool | None = Field(None, description="Se é o calendário vigente.")
    periodo_ferias_vigente: str | None = Field(None, description="Ano-período de férias vigente (ex.: '2026-4').")
    periodo_turmas_solicitacao: str | None = Field(None, description="Ano-período das turmas na solicitação (ex.: '2027-1').")
    periodo_letivo: Intervalo | None = Field(None, description="Período letivo (início e fim das aulas).")
    periodo_ferias: Intervalo | None = Field(None, description="Período de férias.")
    eventos: list[EventoCalendario] = Field(default_factory=list, description="Todos os prazos do calendário, na ordem da tela.")


# ------------------------------------------------------------------ cursos


class CursoConsulta(BaseModel):
    """Linha da 'Consulta geral de cursos' (a tela logada não expõe id nem detalhe)."""

    nome: str = Field(description="Nome do curso sem a sigla da unidade (ex.: 'SISTEMAS DE INFORMAÇÃO').")
    nome_completo: str = Field(description="Texto cru (ex.: 'SISTEMAS DE INFORMAÇÃO/IC/UFBA').")
    unidade_sigla: str | None = Field(None, description="Sigla da unidade depois da 1ª barra (ex.: 'IC/UFBA').")
    nivel: str | None = Field(None, description="Nível (ex.: 'GRADUAÇÃO').")
    coordenadores: list[str] = Field(default_factory=list, description="Coordenador(es) atuais.")


class CursoOpcao(BaseModel):
    """Curso como aparece nos combos de Estrutura Curricular / Turma (com id)."""

    id: int = Field(description="Id do curso no SIGAA.")
    nome: str = Field(description="Nome (ex.: 'SISTEMAS DE INFORMAÇÃO').")
    unidade_sigla: str | None = Field(None, description="Sigla da unidade (ex.: 'IC/UFBA').")
    municipio: str | None = Field(None, description="Município (ex.: 'SALVADOR').")
    grau: str | None = Field(None, description="Grau/modalidade (ex.: 'BACHARELADO', 'LICENCIATURA - EAD').")
    texto: str = Field(description="Texto cru da opção.")


# ------------------------------------------------------------- componentes


class ComponenteRef(BaseModel):
    codigo: str = Field(description="Código do componente (ex.: 'MATA37').")
    nome: str | None = Field(None, description="Nome do componente, quando o SIGAA mostra.")


class ExpressaoRequisito(BaseModel):
    """Uma expressão de pré/co-requisito ou equivalência, ex.: '( MATA55 ) E ( MATA40 OU MATA57 )'."""

    expressao: str | None = Field(None, description="Expressão normalizada com E / OU / parênteses. `null` se não houver.")
    componentes: list[ComponenteRef] = Field(default_factory=list, description="Componentes citados na expressão.")


class CargaHorariaItem(BaseModel):
    rotulo: str = Field(description="Ex.: 'Carga Horária de Aula Teórica - Presencial'.")
    horas: int | None = Field(None, description="Horas.")
    grupo: str | None = Field(None, description="Bloco da tabela (ex.: 'Aula', 'Orientação Acadêmica').")


class ComponenteResumo(BaseModel):
    id: int | None = Field(None, description="Id do componente no SIGAA (use em /componentes/{id}).")
    codigo: str = Field(description="Código (ex.: 'MATA37').")
    nome: str = Field(description="Nome.")
    nivel: str | None = Field(None, description="Nível de ensino.")
    carga_horaria: int | None = Field(None, description="Carga horária total em horas.")
    tipo: str | None = Field(None, description="DISCIPLINA, ATIVIDADE, MÓDULO, BLOCO...")


class EquivalenciaHistorico(BaseModel):
    expressao: ExpressaoRequisito = Field(description="Expressão de equivalência.")
    ativa: bool | None = Field(None, description="Se está ativa.")
    inicio_vigencia: date | None = Field(None, description="Início da vigência.")
    fim_vigencia: date | None = Field(None, description="Fim da vigência.")


class CurriculoDoComponente(BaseModel):
    """Estrutura curricular que inclui o componente (tabela 'Currículos' do relatório)."""

    codigo: str = Field(description="Código da estrutura (ex.: 'G20251X').")
    ano_periodo: str | None = Field(None, description="Ano.período de implementação (ex.: '2025.2').")
    matriz: str | None = Field(None, description="Matriz curricular.")
    obrigatoria: bool | None = Field(None, description="Se o componente é obrigatório nessa estrutura.")
    semestre: int | None = Field(None, description="Semestre/nível em que aparece (`null` para optativas).")
    ativo: bool | None = Field(None, description="Se a estrutura está ativa.")


class ComponenteDetalhe(BaseModel):
    id: int | None = Field(None, description="Id do componente no SIGAA.")
    codigo: str | None = Field(None, description="Código.")
    nome: str | None = Field(None, description="Nome.")
    tipo: str | None = Field(None, description="Tipo do componente (DISCIPLINA, ATIVIDADE...).")
    modalidade: str | None = Field(None, description="Modalidade de educação (Presencial, A Distância...).")
    unidade_responsavel: str | None = Field(None, description="Unidade responsável (texto cru, com município e código).")
    pre_requisitos: ExpressaoRequisito = Field(default_factory=ExpressaoRequisito, description="Pré-requisitos.")
    co_requisitos: ExpressaoRequisito = Field(default_factory=ExpressaoRequisito, description="Co-requisitos.")
    equivalencias: ExpressaoRequisito = Field(default_factory=ExpressaoRequisito, description="Equivalências vigentes.")
    ementa: str | None = Field(None, description="Ementa/descrição.")
    carga_horaria_total: int | None = Field(None, description="Total de carga horária do componente (h).")
    carga_horaria_aula: int | None = Field(None, description="Total de carga horária de aula (h).")
    cargas_horarias: list[CargaHorariaItem] = Field(default_factory=list, description="Detalhamento da CH (teórica, prática, extensionista, EAD...).")
    outras_informacoes: dict[str, str] = Field(default_factory=dict, description="Demais pares rótulo→valor (Matriculável On-Line, Quantidade de Avaliações, Possui subturmas...).")
    equivalente_de: list[ComponenteRef] = Field(default_factory=list, description="Outros componentes que têm este como equivalente (só com `completo=true`).")
    pre_requisito_de: list[ComponenteRef] = Field(default_factory=list, description="Outros componentes que têm este como pré-requisito (só com `completo=true`).")
    co_requisito_de: list[ComponenteRef] = Field(default_factory=list, description="Outros componentes que têm este como co-requisito (só com `completo=true`).")
    historico_equivalencias: list[EquivalenciaHistorico] = Field(default_factory=list, description="Histórico de expressões de equivalência (só com `completo=true`).")
    curriculos: list[CurriculoDoComponente] = Field(default_factory=list, description="Estruturas curriculares que incluem o componente (só com `completo=true`).")


# -------------------------------------------------------------- estruturas


class EstruturaResumo(BaseModel):
    id: int = Field(description="Id da estrutura curricular no SIGAA.")
    codigo: str = Field(description="Código (ex.: 'G20251X').")
    ano_periodo: str | None = Field(None, description="Ano-período de entrada em vigor (ex.: '2025.2').")
    matriz: str | None = Field(None, description="Matriz curricular.")
    ativa: bool = Field(description="`false` quando o SIGAA marca '(Inativa)'.")
    situacao: str | None = Field(None, description="Situação (CADASTRADA, CONSOLIDADA...).")


class ComponenteDaEstrutura(BaseModel):
    id: int | None = Field(None, description="Id do componente (use em /componentes/{id}).")
    codigo: str = Field(description="Código.")
    nome: str = Field(description="Nome.")
    carga_horaria: int | None = Field(None, description="CH total em horas.")
    ch_detalhada: str | None = Field(None, description="CH detalhada como no SIGAA (ex.: '60h Aula', '1h Orientação Acadêmica/Profissional').")
    tipo: str | None = Field(None, description="DISCIPLINA, ATIVIDADE...")
    natureza: str | None = Field(None, description="OBRIGATORIO, OPTATIVO, COMPLEMENTAR...")
    modalidade: str | None = Field(None, description="Presencial, A Distância...")


class NivelEstrutura(BaseModel):
    nome: str = Field(description="Ex.: '1º Semestre', 'Componentes Optativos'.")
    semestre: int | None = Field(None, description="Número do semestre; `null` para optativos/complementares.")
    carga_horaria_total: int | None = Field(None, description="CH total do bloco (h).")
    componentes: list[ComponenteDaEstrutura] = Field(default_factory=list, description="Componentes do bloco.")


class PrazosConclusao(BaseModel):
    minimo: int | None = Field(None, description="Prazo mínimo em semestres.")
    medio: int | None = Field(None, description="Prazo médio em semestres.")
    maximo: int | None = Field(None, description="Prazo máximo em semestres.")


class EstruturaDetalhe(BaseModel):
    id: int | None = Field(None, description="Id da estrutura.")
    codigo: str | None = Field(None, description="Código.")
    matriz: str | None = Field(None, description="Matriz curricular.")
    unidade_vinculacao: str | None = Field(None, description="Unidade de vinculação.")
    municipio: str | None = Field(None, description="Município de funcionamento.")
    periodo_entrada_vigor: str | None = Field(None, description="Período letivo de entrada em vigor (ex.: '2025.2').")
    prazos: PrazosConclusao = Field(default_factory=PrazosConclusao, description="Prazos para conclusão (semestres).")
    ch_total: int | None = Field(None, description="Carga horária total/mínima (h).")
    ch_obrigatoria: int | None = Field(None, description="CH obrigatória (h).")
    ch_optativa: int | None = Field(None, description="CH optativa mínima (h).")
    ch_optativa_livre: int | None = Field(None, description="CH optativa livre (h).")
    ch_complementar: int | None = Field(None, description="CH complementar mínima (h).")
    ch_maxima_periodo: int | None = Field(None, description="CH máxima por período letivo (h).")
    ch_maxima_eletivos: int | None = Field(None, description="CH máxima de componentes eletivos (h).")
    outras_cargas: dict[str, int] = Field(default_factory=dict, description="Demais cargas horárias da tela 'Detalhar' (rótulo → horas).")
    niveis: list[NivelEstrutura] = Field(default_factory=list, description="Componentes por semestre + optativos.")


class DeclaracaoPrazoMaximo(BaseModel):
    curso: str | None = Field(None, description="Curso.")
    turno: str | None = Field(None, description="Turno.")
    modalidade: str | None = Field(None, description="Modalidade/grau.")
    prazo_maximo: int | None = Field(None, description="Prazo máximo em períodos letivos regulares.")
    identificador: str | None = Field(None, description="Identificador do documento (autenticação em /sigaa/documentos/).")
    codigo_verificacao: str | None = Field(None, description="Código de verificação do documento.")
    texto: str | None = Field(None, description="Texto da declaração.")


# ------------------------------------------------------------------ turmas


class DocenteTurma(BaseModel):
    nome: str = Field(description="Nome do docente.")
    carga_horaria: int | None = Field(None, description="CH do docente na turma (h).")


class HorarioAula(BaseModel):
    dia: str = Field(description="Dia da semana ('Segunda'...'Sábado').")
    dia_numero: int = Field(description="Dia no código SIGAA (2=segunda ... 7=sábado).")
    turno: str = Field(description="M, T ou N.")
    aula: int = Field(description="Número do horário no turno (1..6).")
    inicio: str | None = Field(None, description="Hora de início ('13:00').")
    fim: str | None = Field(None, description="Hora de fim ('13:55').")


class AlocacaoSala(BaseModel):
    local: str = Field(description="Sala/espaço (ex.: 'PAF 1 - 106').")
    dia: str | None = Field(None, description="Dia da semana.")
    inicio: str | None = Field(None, description="Início ('13:00').")
    fim: str | None = Field(None, description="Fim ('13:55').")


class TurmaOferta(BaseModel):
    id: int | None = Field(None, description="Id da turma no SIGAA (use em /turmas/{id}).")
    componente_codigo: str | None = Field(None, description="Código do componente.")
    componente_nome: str | None = Field(None, description="Nome do componente.")
    nivel: str | None = Field(None, description="Nível (GRADUAÇÃO...).")
    ano: int | None = Field(None, description="Ano.")
    periodo: int | None = Field(None, description="Período.")
    codigo_turma: str | None = Field(None, description="Código da turma (ex.: '01').")
    docentes: list[DocenteTurma] = Field(default_factory=list, description="Docentes e CH de cada um.")
    tipo: str | None = Field(None, description="REGULAR, FÉRIAS, ENSINO INDIVIDUAL.")
    modalidade: str | None = Field(None, description="Presencial, A Distância, Remoto...")
    situacao: str | None = Field(None, description="ABERTA, A DEFINIR DOCENTE, CONSOLIDADA...")
    horario_codigo: str | None = Field(None, description="Código de horário SIGAA (ex.: '35T12').")
    horarios: list[HorarioAula] = Field(default_factory=list, description="Horário decodificado do código.")
    periodo_aulas: Intervalo | None = Field(None, description="Início e fim das aulas.")
    local: str | None = Field(None, description="Local como o SIGAA mostra ('A definir', 'Smart Class I'...).")
    alocacoes: list[AlocacaoSala] = Field(default_factory=list, description="Sala por dia/horário, quando o SIGAA detalha.")
    matriculados: int | None = Field(None, description="Nº de matrículas.")
    capacidade: int | None = Field(None, description="Capacidade (vagas).")


class VagaReservada(BaseModel):
    curso: str = Field(description="Curso/matriz com reserva.")
    ingressantes: int | None = Field(None, description="Vagas para ingressantes.")
    demais: int | None = Field(None, description="Vagas para os demais alunos.")
    texto: str | None = Field(None, description="Texto cru.")


class TurmaDetalhe(BaseModel):
    id: int | None = Field(None, description="Id da turma.")
    ano: int | None = Field(None, description="Ano.")
    periodo: int | None = Field(None, description="Período.")
    periodo_letivo: Intervalo | None = Field(None, description="Período letivo da turma.")
    componente_codigo: str | None = Field(None, description="Código do componente.")
    componente_nome: str | None = Field(None, description="Nome do componente.")
    codigo_turma: str | None = Field(None, description="Código da turma.")
    tipo_componente: str | None = Field(None, description="Tipo do componente.")
    carga_horaria: int | None = Field(None, description="CH (h).")
    tipo_turma: str | None = Field(None, description="REGULAR, FÉRIAS...")
    local_horario: str | None = Field(None, description="Local e horário (texto cru).")
    horario_codigo: str | None = Field(None, description="Código de horário (ex.: '35T12').")
    horarios: list[HorarioAula] = Field(default_factory=list, description="Horário decodificado.")
    alocacoes: list[AlocacaoSala] = Field(default_factory=list, description="Sala por dia/horário.")
    capacidade: int | None = Field(None, description="Capacidade.")
    solicitacoes_matricula: int | None = Field(None, description="Solicitações realizadas na matrícula.")
    solicitacoes_rematricula: int | None = Field(None, description="Solicitações realizadas na rematrícula.")
    matriculados: int | None = Field(None, description="Alunos matriculados.")
    docentes: list[DocenteTurma] = Field(default_factory=list, description="Professores.")
    vagas_reservadas: list[VagaReservada] = Field(default_factory=list, description="Reservas de vagas por curso.")


class ContagemSituacao(BaseModel):
    grupo: str = Field(description="Grupo/curso da lista do processamento.")
    situacao: str = Field(description="Situação (MATRICULADO, INDEFERIDO, EXCLUÍDA...).")
    quantidade: int = Field(description="Quantidade de solicitações nessa situação.")


class ProcessamentoTurma(BaseModel):
    """Resultado do processamento de (re)matrícula **agregado**: a tela original lista nome e
    matrícula de outros alunos, que esta API não expõe."""

    id_turma: int | None = Field(None, description="Id da turma.")
    rematricula: bool = Field(False, description="`true` = processamento da rematrícula.")
    componente: str | None = Field(None, description="Componente (código - nome).")
    codigo_turma: str | None = Field(None, description="Código da turma.")
    horario: str | None = Field(None, description="Horário (texto cru).")
    capacidade: int | None = Field(None, description="Capacidade.")
    vagas_reservadas: list[VagaReservada] = Field(default_factory=list, description="Reserva de vagas (ingressantes / demais).")
    total_solicitacoes: int = Field(0, description="Total de solicitações listadas.")
    por_situacao: list[ContagemSituacao] = Field(default_factory=list, description="Contagem por grupo e situação.")


# ---------------------------------------------------------------- unidades


class UnidadeConsulta(BaseModel):
    id: int | None = Field(None, description="Id da unidade no SIGAA (o mesmo usado nos filtros de turma/componente).")
    codigo: str | None = Field(None, description="Código hierárquico (ex.: '122801').")
    nome: str = Field(description="Nome.")
    sigla: str | None = Field(None, description="Sigla.")
    tipo: str | None = Field(None, description="Departamento, Centro Acadêmico, Coordenação de Curso...")
    ativa: bool | None = Field(None, description="Se está ativa.")
