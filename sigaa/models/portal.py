"""Modelos do Portal do Discente: dados institucionais, integralização, turmas (atuais e
anteriores), horários/grade semanal, atividades, atualizações das turmas, fórum do curso,
dados pessoais, perfil, módulos, caixa postal e o relatório de salas livres."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


# ------------------------------------------------------------------- horários
class Turno(str, Enum):
    M = "M"
    T = "T"
    N = "N"


class SlotHorario(BaseModel):
    turno: Turno = Field(description="Turno do slot: M (manhã), T (tarde), N (noite).")
    slot: int = Field(description="Número do horário dentro do turno (M1..M6, T1..T6, N1..N4 na UFBA).")
    codigo: str = Field(description="Turno + número, ex.: 'N1'.")
    inicio: str | None = Field(None, description="Hora de início 'HH:MM' (None se o slot não existe na tabela da instituição).")
    fim: str | None = Field(None, description="Hora de fim 'HH:MM'.")


class AulaSemanal(BaseModel):
    """Um bloco contínuo de aula num dia da semana (ex.: terça, N1+N2 = 18:30–20:20)."""

    dia: int = Field(description="Dia da semana no padrão SIGAA: 1=domingo, 2=segunda ... 7=sábado.")
    dia_nome: str = Field(description="Nome do dia: Segunda, Terça...")
    dia_iso: int = Field(description="Dia ISO 8601: 1=segunda ... 7=domingo (útil pra calendários).")
    turno: Turno = Field(description="Turno do bloco.")
    slots: list[int] = Field(description="Números dos horários do bloco, ex.: [1, 2].")
    codigos: list[str] = Field(description="Códigos dos horários, ex.: ['N1', 'N2'].")
    inicio: str | None = Field(None, description="Início do bloco 'HH:MM' (início do primeiro slot).")
    fim: str | None = Field(None, description="Fim do bloco 'HH:MM' (fim do último slot).")
    minutos: int | None = Field(None, description="Duração do bloco em minutos.")


class Horario(BaseModel):
    """Código de horário do SIGAA decodificado (ex.: '46N12 (19/08/2026 - 19/12/2026)')."""

    texto: str = Field(description="Texto cru como o SIGAA mostra.")
    codigo: str = Field(description="Só o código, sem o período: '46N12', '2N1234 4N4'.")
    data_inicio: date | None = Field(None, description="Início do período de aulas (quando o texto traz).")
    data_fim: date | None = Field(None, description="Fim do período de aulas.")
    aulas: list[AulaSemanal] = Field(default_factory=list, description="Blocos semanais, ordenados por dia e hora.")
    aulas_por_semana: int = Field(0, description="Quantidade de slots (horas-aula) por semana.")
    minutos_por_semana: int | None = Field(None, description="Soma da duração dos slots na semana, em minutos.")
    reconhecido: bool = Field(description="False quando algum pedaço do código não pôde ser interpretado.")
    nao_reconhecido: list[str] = Field(default_factory=list, description="Pedaços do código que não foram entendidos.")


class LocalAula(BaseModel):
    """Um item do 'Local' detalhado ('PAF 1 - 006 - Terça Horários 18:30 às 19:25')."""

    local: str = Field(description="Prédio/sala, ex.: 'PAF 1 - 006'.")
    dia_nome: str | None = Field(None, description="Dia da semana, ex.: 'Terça'.")
    dia: int | None = Field(None, description="Dia no padrão SIGAA (2=segunda ... 7=sábado).")
    inicio: str | None = Field(None, description="'HH:MM'.")
    fim: str | None = Field(None, description="'HH:MM'.")


class SlotTabela(BaseModel):
    codigo: str = Field(description="'M1', 'T3', 'N4'...")
    turno: Turno
    slot: int
    inicio: str
    fim: str


class TabelaHorarios(BaseModel):
    instituicao: str = Field(description="Instituição a que a tabela se refere.")
    fonte: str = Field(description="De onde a tabela foi tirada.")
    slots: list[SlotTabela]
    dias: dict[int, str] = Field(description="Dias da semana no padrão SIGAA (1=domingo ... 7=sábado).")


# --------------------------------------------------------------------- turmas
class Turma(BaseModel):
    turma_id: int | None = Field(
        None,
        description="idTurma NUMÉRICO do SIGAA (estável; é o id usado em /v1/turmas/{turma_id}/...). "
        "None só se nenhuma tela trouxe o id dessa turma.",
    )
    front_end_id: str | None = Field(None, description="frontEndIdTurma (hash hexadecimal que o portal clássico usa nos links).")
    periodo: str | None = Field(None, description="Ano.período letivo, ex.: 2026.2")
    ano: int | None = Field(None, description="Ano letivo.")
    semestre: int | None = Field(None, description="Período dentro do ano (1, 2, 3/4 para cursos de verão...).")
    codigo: str | None = Field(None, description="Código do componente, ex.: MATC89.")
    nome: str = Field(description="Nome do componente curricular.")
    turma: str | None = Field(None, description="Número/código da turma, ex.: '01'.")
    carga_horaria: int | None = Field(None, description="Carga horária total em horas.")
    nivel: str | None = Field(None, description="Nível de ensino da turma (GRADUAÇÃO...), quando a tela informa.")
    local: str | None = Field(None, description="Local como o SIGAA mostra (sala/prédio), sem o detalhamento de horário repetido.")
    locais: list[LocalAula] = Field(default_factory=list, description="Local detalhado por dia/horário, quando o SIGAA informa.")
    horario: Horario | None = Field(None, description="Código de horário decodificado.")
    atual: bool = Field(False, description="True se a turma é do semestre atual.")


class ListaTurmas(BaseModel):
    semestre_atual: str | None = Field(None, description="Semestre atual segundo o portal.")
    total: int = Field(description="Quantidade de turmas devolvidas.")
    periodos: list[str] = Field(default_factory=list, description="Períodos presentes, do mais recente pro mais antigo.")
    turmas: list[Turma] = Field(default_factory=list)


# ------------------------------------------------------------- grade semanal
class AulaGrade(BaseModel):
    dia: int = Field(description="1=domingo ... 7=sábado (padrão SIGAA).")
    dia_nome: str
    inicio: str | None = Field(None, description="'HH:MM'.")
    fim: str | None = Field(None, description="'HH:MM'.")
    turno: Turno
    codigos: list[str] = Field(description="Slots do bloco, ex.: ['N1','N2'].")
    turma_id: int | None = None
    codigo: str | None = Field(None, description="Código do componente.")
    nome: str
    turma: str | None = None
    local: str | None = Field(None, description="Sala desse dia/horário (quando o SIGAA detalha) ou o local geral da turma.")


class DiaGrade(BaseModel):
    dia: int
    dia_nome: str
    aulas: list[AulaGrade] = Field(default_factory=list)


class GradeHoraria(BaseModel):
    periodo: str | None = Field(None, description="Período da grade.")
    data_inicio: date | None = Field(None, description="Primeiro dia de aula entre as turmas.")
    data_fim: date | None = Field(None, description="Último dia de aula entre as turmas.")
    dias: list[DiaGrade] = Field(default_factory=list, description="Segunda a sábado (e domingo se houver aula).")
    aulas: list[AulaGrade] = Field(default_factory=list, description="Todos os blocos, em ordem de dia e hora.")
    conflitos: list[str] = Field(default_factory=list, description="Choques de horário detectados (mesmo dia e slot em duas turmas).")
    sem_horario: list[str] = Field(default_factory=list, description="Turmas cujo horário não pôde ser decodificado.")


# ------------------------------------------------------- portal (página inicial)
class Curso(BaseModel):
    texto: str = Field(description="Texto cru: 'SISTEMAS DE INFORMAÇÃO/IC/UFBA - SALVADOR - BACHARELADO - N'.")
    nome: str | None = Field(None, description="Nome do curso.")
    unidade_sigla: str | None = Field(None, description="Sigla da unidade (IC).")
    instituicao: str | None = Field(None, description="Sigla da instituição (UFBA).")
    municipio: str | None = Field(None, description="Município/campus.")
    grau: str | None = Field(None, description="BACHARELADO, LICENCIATURA...")
    turno: str | None = Field(None, description="Turno do curso (letra): M, T, N, MT, D...")


class Integralizacao(BaseModel):
    ch_obrigatoria_pendente: int | None = Field(None, description="CH obrigatória pendente (horas).")
    ch_optativa_pendente: int | None = Field(None, description="CH optativa pendente (horas).")
    ch_complementar_pendente: int | None = Field(None, description="CH complementar pendente (horas).")
    ch_total_curriculo: int | None = Field(None, description="CH total do currículo (horas).")
    percentual: float | None = Field(None, description="Percentual integralizado com casas decimais (da barra de progresso).")
    percentual_arredondado: int | None = Field(None, description="Percentual como o SIGAA escreve ('56% Integralizado').")
    outros: dict[str, int] = Field(default_factory=dict, description="Outras linhas 'CH ...' que o SIGAA mostrar.")


class DadosInstitucionais(BaseModel):
    nome: str | None = Field(None, description="Nome completo.")
    nome_abreviado: str | None = Field(None, description="Nome abreviado do cabeçalho.")
    matricula: str | None = Field(None, description="Matrícula (string: é identificador, não quantidade).")
    id_discente: int | None = Field(None, description="Id interno do discente no SIGAA.")
    curso: Curso | None = None
    nivel: str | None = Field(None, description="GRADUAÇÃO, MESTRADO...")
    status: str | None = Field(None, description="ATIVO, FORMANDO, TRANCADO...")
    email: str | None = Field(None, description="E-mail como o portal mostra (o SIGAA corta e-mails longos com '...').")
    email_truncado: bool = Field(False, description="True quando o portal cortou o e-mail.")
    entrada: str | None = Field(None, description="Período de entrada, ex.: 2022.1")
    unidade: str | None = Field(None, description="Unidade do vínculo (cabeçalho).")
    unidade_codigo: str | None = Field(None, description="Código da unidade, ex.: 12.28")
    semestre_atual: str | None = Field(None, description="Semestre atual do sistema, ex.: 2026.2")
    foto_url: str | None = Field(None, description="URL da foto no SIGAA (precisa da sessão; use /v1/me/foto).")
    foto_api: str | None = Field(None, description="Rota desta API que devolve a foto (`/v1/me/foto`), quando o aluno tem foto.")
    foto_base64: str | None = Field(None, description="A foto em data URI (`data:image/jpeg;base64,...`) — só com `?incluir_foto=true`.")
    campos_extras: dict[str, str] = Field(default_factory=dict, description="Rótulos de Dados Institucionais que a API não conhece.")
    integralizacao: Integralizacao | None = None


class Atualizacao(BaseModel):
    """Item de 'Últimas Atualizações' das turmas (o letreiro rotativo do portal)."""

    data: date | None = None
    turma_id: int | None = Field(None, description="idTurma numérico.")
    turma: str = Field(description="Nome da turma como aparece ('APLICAÇÕES PARA DISPOSITIVOS MÓVEIS').")
    periodo: str | None = Field(None, description="Período entre parênteses no link, ex.: 2026.2")
    tipo: str | None = Field(None, description="Tipo da atualização: 'Nova Notícia', 'Nova Tarefa', 'Novo Arquivo'...")
    titulo: str | None = Field(None, description="Texto depois do tipo.")
    texto: str = Field(description="Descrição completa como o SIGAA mostra.")


class Atividade(BaseModel):
    """Item de 'Minhas atividades' (próximos 15 dias / últimos 7 dias)."""

    data: date | None = None
    hora: str | None = Field(None, description="'HH:MM' quando informado.")
    tipo: str | None = Field(None, description="Avaliação, Tarefa, Questionário... (deduzido do texto/ícone).")
    descricao: str = Field(description="Descrição da atividade.")
    turma: str | None = Field(None, description="Nome da turma.")
    turma_id: int | None = None
    concluida: bool | None = Field(None, description="Quando o SIGAA indica (ícone/texto de entregue).")
    texto: str = Field(description="Linha inteira crua.")


class NoticiaPortal(BaseModel):
    titulo: str
    data: date | None = None
    id: int | None = Field(None, description="Id da notícia quando o link traz.")


class TopicoForum(BaseModel):
    id: int | None = Field(None, description="Id do tópico quando o link traz.")
    titulo: str
    autor: str | None = None
    respostas: int | None = None
    criado_em: datetime | None = None
    ultima_postagem: datetime | None = None
    ultima_postagem_texto: str | None = Field(None, description="Coluna de última postagem crua.")
    colunas: dict[str, str] = Field(default_factory=dict, description="Todas as colunas da linha, por rótulo do cabeçalho.")


class ForumCurso(BaseModel):
    titulo: str | None = Field(None, description="'FÓRUM DO CURSO DE SISTEMAS DE INFORMAÇÃO'.")
    descricao: str | None = None
    topicos: list[TopicoForum] = Field(default_factory=list)


class MensagemForum(BaseModel):
    autor: str | None = None
    data: datetime | None = None
    texto: str


class TopicoForumDetalhe(BaseModel):
    id: int | None = None
    titulo: str | None = None
    mensagens: list[MensagemForum] = Field(default_factory=list)


class PortalDiscente(BaseModel):
    """Tudo da página inicial do Portal do Discente numa chamada."""

    dados: DadosInstitucionais
    turmas_semestre: list[Turma] = Field(default_factory=list, description="Turmas do semestre (com turma_id e local).")
    atualizacoes: list[Atualizacao] = Field(default_factory=list)
    atividades: list[Atividade] = Field(default_factory=list)
    noticias: list[NoticiaPortal] = Field(default_factory=list, description="Notícias do portal (o quadro do topo).")
    comunidades_virtuais: list[str] = Field(default_factory=list, description="Comunidades virtuais de que participa.")
    forum_curso: list[TopicoForum] = Field(default_factory=list, description="Prévia dos tópicos do fórum do curso.")
    versao_sigaa: str | None = Field(None, description="Versão do SIGAA no rodapé.")


# --------------------------------------------------------- dados pessoais/perfil
class Endereco(BaseModel):
    cep: str | None = None
    tipo_logradouro: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    uf: str | None = None
    municipio: str | None = None


class Contato(BaseModel):
    telefone: str | None = Field(None, description="Telefone fixo com DDD: '(71) 30000000'.")
    celular: str | None = Field(None, description="Celular com DDD.")
    email: str | None = Field(None, description="E-mail pessoal cadastrado.")


class Documentos(BaseModel):
    cpf: str | None = None
    rg: str | None = None
    rg_orgao: str | None = Field(None, description="Órgão expedidor/UF do RG, ex.: SSP/BA.")
    rg_expedicao: date | None = None
    titulo_eleitor: str | None = None
    titulo_zona: str | None = None
    titulo_secao: str | None = None
    titulo_uf: str | None = None
    certificado_militar: str | None = None
    certificado_militar_expedicao: date | None = None
    certificado_militar_serie: str | None = None
    certificado_militar_categoria: str | None = None
    certificado_militar_orgao: str | None = None


class DadosPessoais(BaseModel):
    """'Meus Dados Pessoais' (tela de atualização — a API só LÊ, nunca grava)."""

    matricula: str | None = None
    nome: str | None = None
    curso: str | None = None
    sexo: str | None = None
    estado_civil: str | None = None
    data_nascimento: date | None = None
    naturalidade: str | None = None
    raca: str | None = None
    tipo_sanguineo: str | None = None
    nacionalidade: str | None = None
    pais: str | None = None
    escola_ensino_medio: str | None = None
    tipo_escola_ensino_medio: str | None = None
    ano_conclusao_ensino_medio: int | None = None
    necessidades_especiais: list[str] = Field(default_factory=list, description="Tipos de NEE.")
    nome_pai: str | None = None
    nome_mae: str | None = None
    documentos: Documentos = Field(default_factory=Documentos)
    endereco: Endereco = Field(default_factory=Endereco)
    contato: Contato = Field(default_factory=Contato)
    banco: str | None = None
    agencia: str | None = None
    conta: str | None = None
    renda_familiar: float | None = Field(None, description="Renda familiar bruta mensal (R$).")
    membros_familia: int | None = None
    zona_residencia: str | None = None
    transporte_escolar_publico: str | None = None
    tipo_transporte: str | None = None
    campos_extras: dict[str, str] = Field(default_factory=dict, description="Rótulos que a API ainda não conhece (valor cru).")


class Perfil(BaseModel):
    """perfil.jsf (tela de edição — só leitura)."""

    descricao_pessoal: str | None = None
    areas_interesse: str | None = None
    curriculo_lattes: str | None = None
    assinatura: str | None = Field(None, description="Assinatura usada na caixa postal.")
    foto_url: str | None = None
    tem_foto: bool = False


# ---------------------------------------------------------------- módulos
class Modulo(BaseModel):
    chave: str = Field(description="Classe CSS do item (graduacao, biblioteca, discente...).")
    nome: str
    grupo: str | None = Field(None, description="Seção do painel: Módulos, Outros Sistemas, Portais.")
    habilitado: bool = Field(description="True quando o usuário tem acesso (item 'on').")
    url: str | None = Field(None, description="Link quando habilitado.")


class Modulos(BaseModel):
    modulos: list[Modulo] = Field(default_factory=list)
    habilitados: list[str] = Field(default_factory=list, description="Nomes dos módulos acessíveis.")


# ------------------------------------------------------------ caixa postal
class MensagemResumo(BaseModel):
    id: str | None = None
    remetente: str | None = None
    assunto: str
    data: datetime | None = None
    lida: bool | None = None


class CaixaPostal(BaseModel):
    mensagens: list[MensagemResumo] = Field(default_factory=list)


class Mensagem(BaseModel):
    id: str | None = None
    remetente: str | None = None
    assunto: str | None = None
    data: datetime | None = None
    texto: str


# ----------------------------------------------------------- salas livres
class OpcaoFiltro(BaseModel):
    valor: str
    rotulo: str


class FiltrosSalasLivres(BaseModel):
    ano: int | None = None
    periodo: int | None = None
    niveis: list[OpcaoFiltro] = Field(default_factory=list)
    dias: list[OpcaoFiltro] = Field(default_factory=list)
    turnos: list[OpcaoFiltro] = Field(default_factory=list)
    predios: list[OpcaoFiltro] = Field(default_factory=list)


class SalaLivre(BaseModel):
    predio: str | None = Field(None, description="Sigla/nome do prédio (coluna 'predio').")
    predio_nome: str | None = Field(None, description="Coluna 'nome do predio'.")
    sala: str
    capacidade: int | None = None
    dia_nome: str | None = None
    inicio: str | None = Field(None, description="'HH:MM'.")
    fim: str | None = Field(None, description="'HH:MM'.")
    turno: str | None = None


class RelatorioSalasLivres(BaseModel):
    emitido_em: datetime | None = None
    filtros: dict[str, str] = Field(default_factory=dict, description="Filtros usados.")
    total: int
    salas: list[SalaLivre] = Field(default_factory=list)
