"""Modelos da TURMA VIRTUAL (AVA) do SIGAA: página principal, tópicos de aula, notícias, participantes,
plano de curso, materiais, atividades (tarefas, questionários, enquetes), avaliações, fóruns, notas e frequência.

Cada professor usa a turma virtual de um jeito — quase tudo aqui pode vir vazio (`[]`/`None`)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ identificação
class TurmaVirtualResumo(BaseModel):
    """Uma turma que o aluno pode abrir na turma virtual (do semestre ou anterior)."""

    turma_id: int | None = Field(None, description="idTurma NUMÉRICO do SIGAA (estável). None quando não deu pra descobrir.")
    front_end_id: str = Field(description="frontEndIdTurma: hash que o SIGAA usa pra abrir a turma virtual (estável entre logins).")
    codigo: str | None = Field(None, description="Código do componente, ex.: MATC89.")
    nome: str | None = Field(None, description="Nome do componente.")
    turma: str | None = Field(None, description="Número/código da turma, ex.: 01.")
    periodo: str | None = Field(None, description="Ano.período letivo, ex.: 2026.2.")
    carga_horaria: int | None = Field(None, description="Carga horária total em horas.")
    horario: str | None = Field(None, description="Horário codificado como o SIGAA mostra, ex.: '46N12 (19/08/2026 - 19/12/2026)'.")
    local: str | None = Field(None, description="Local da aula (só nas turmas do semestre, vindo do portal).")
    atual: bool = Field(False, description="True quando a turma é do semestre corrente (aparece no portal).")


class ItemMenuTurma(BaseModel):
    rotulo: str = Field(description="Texto do item no menu lateral da turma virtual (ex.: 'Tarefas').")
    grupo: str | None = Field(None, description="Seção do menu: Turma, Alunos, Materiais, Atividades, Estatística, Ajuda.")


# ------------------------------------------------------------------ página principal
class MaterialTopico(BaseModel):
    """Um item pendurado num tópico de aula (arquivo, conteúdo, link, vídeo, tarefa, questionário...)."""

    id: int | None = Field(None, description="Id numérico do material no SIGAA, quando o link traz um.")
    id_hash: str | None = Field(None, description="Alguns links (arquivos nos tópicos) trazem um hash em vez do id numérico.")
    tipo: str = Field(description="arquivo, conteudo, referencia, video, tarefa, questionario, forum, enquete, chat, outro.")
    titulo: str = Field(description="Texto do link.")
    descricao: str | None = Field(None, description="Descrição que o docente escreveu embaixo do item.")
    url: str | None = Field(None, description="URL direta (links externos, vídeos, download de arquivo).")
    icone: str | None = Field(None, description="Nome do ícone que o SIGAA usa (ajuda a identificar tipos novos).")


class TopicoAula(BaseModel):
    titulo: str = Field(description="Título do tópico de aula.")
    data_inicio: date | None = Field(None, description="Início do tópico (o SIGAA mostra '(dd/mm/aaaa - dd/mm/aaaa)').")
    data_fim: date | None = Field(None, description="Fim do tópico.")
    descricao: str | None = Field(None, description="Texto do conteúdo do tópico (sem HTML).")
    descricao_html: str | None = Field(None, description="HTML do conteúdo do tópico, como o docente escreveu.")
    materiais: list[MaterialTopico] = Field(default_factory=list, description="Arquivos, links e atividades do tópico.")
    links: list[str] = Field(default_factory=list, description="URLs externas citadas no texto do tópico (formulários, sites...).")


class Andamento(BaseModel):
    aulas_ministradas: int | None = Field(None, description="Aulas já ministradas.")
    aulas_total: int | None = Field(None, description="Aulas previstas.")
    percentual_ch_ministrada: float | None = Field(None, description="% da carga horária já ministrada.")


class EventoRecente(BaseModel):
    data: str | None = Field(None, description="Data como aparece no quadro (dd/mm, sem ano).")
    descricao: str = Field(description="Ex.: 'Nova Notícia: Sem aula hoje'.")


class AvaliacaoResumo(BaseModel):
    data: str | None = Field(None, description="'dd/mm HH:MM' como aparece no quadro lateral.")
    descricao: str


class Noticia(BaseModel):
    id: int | None = Field(None, description="Id da notícia no SIGAA.")
    titulo: str = Field(description="Título da notícia.")
    data: datetime | date | None = Field(None, description="Data (e hora, quando o SIGAA mostra) da publicação.")
    conteudo: str | None = Field(None, description="Texto da notícia (sem HTML). None na listagem.")
    conteudo_html: str | None = Field(None, description="HTML da notícia.")
    autor: str | None = Field(None, description="Quem cadastrou.")


class TurmaVirtual(BaseModel):
    """Página principal da turma virtual."""

    turma_id: int | None = Field(None, description="idTurma numérico do SIGAA.")
    front_end_id: str | None = Field(None, description="frontEndIdTurma da turma aberta.")
    codigo: str | None = Field(None, description="Código do componente.")
    nome: str | None = Field(None, description="Nome do componente.")
    turma: str | None = Field(None, description="Turma, ex.: 01 (o SIGAA mostra 'T01').")
    periodo: str | None = Field(None, description="Ano.período.")
    carga_horaria: int | None = Field(None, description="Carga horária em horas, quando aparece.")
    ementa: str | None = Field(None, description="Ementa mostrada na página principal (algumas turmas mostram em vez dos tópicos).")
    andamento: Andamento | None = Field(None, description="Quadro 'Andamento das Aulas'.")
    ultima_noticia: Noticia | None = Field(None, description="Destaque 'Última Notícia' do topo.")
    topicos: list[TopicoAula] = Field(default_factory=list, description="Tópicos de aula (conteúdo programado) com os materiais.")
    noticias_recentes: list[Noticia] = Field(default_factory=list, description="Quadro lateral 'Notícias' (as 5 últimas).")
    atividades_recentes: list[EventoRecente] = Field(default_factory=list, description="Quadro lateral 'Atividades'.")
    avaliacoes_proximas: list[AvaliacaoResumo] = Field(default_factory=list, description="Quadro lateral 'Avaliações'.")
    sem_topicos: bool = Field(False, description="True quando o SIGAA mostra 'seu professor não criou nenhum tópico de aula'.")
    enquete_aberta: str | None = Field(None, description="Pergunta da enquete em destaque, se houver.")
    menu: list[ItemMenuTurma] = Field(default_factory=list, description="Itens do menu lateral disponíveis pra esta turma.")
    outras_turmas: list[TurmaVirtualResumo] = Field(default_factory=list, description="Turmas do 'Trocar de Turma'.")


# ------------------------------------------------------------------ participantes
class Participante(BaseModel):
    nome: str = Field(description="Nome completo.")
    papel: str = Field(description="'docente' ou 'discente'.")
    email: str | None = Field(None, description="E-mail (quando o SIGAA mostra).")
    departamento: str | None = Field(None, description="Departamento/unidade (docentes).")
    formacao: str | None = Field(None, description="Titulação (docentes), ex.: DOUTORADO.")
    curso: str | None = Field(None, description="Curso (discentes).")
    matricula: str | None = Field(None, description="Matrícula (discentes).")
    usuario: str | None = Field(None, description="Login no SIGAA, quando o SIGAA mostra.")
    foto_url: str | None = Field(None, description="URL da foto no SIGAA (precisa da sessão pra abrir).")
    foto_api: str | None = Field(None, description="Rota desta API que devolve a foto (`/v1/fotos?url=...`).")
    pagina_publica: str | None = Field(None, description="Link pra página pública do docente.")
    online: bool | None = Field(None, description="True quando o SIGAA marca o usuário como on-line agora.")
    campos_extras: dict[str, str] = Field(default_factory=dict, description="Rótulos que a API ainda não conhece.")


class Participantes(BaseModel):
    total_docentes: int | None = Field(None, description="Contagem que o SIGAA mostra no título 'Docentes (n)'.")
    total_discentes: int | None = Field(None, description="Contagem de 'Discentes (n)'.")
    docentes: list[Participante] = Field(default_factory=list)
    discentes: list[Participante] = Field(default_factory=list)


# ------------------------------------------------------------------ plano de curso
class AulaCronograma(BaseModel):
    inicio: date | None = Field(None, description="Data de início do tópico.")
    fim: date | None = Field(None, description="Data de fim do tópico.")
    descricao: str = Field(description="Descrição do tópico/aula.")


class AvaliacaoPlano(BaseModel):
    data: date | None = Field(None, description="Data prevista.")
    descricao: str = Field(description="Descrição da avaliação.")


class ReferenciaPlano(BaseModel):
    tipo: str | None = Field(None, description="Tipo de material: Livro, Artigo, Site...")
    descricao: str = Field(description="Referência como o docente cadastrou.")
    na_biblioteca: bool = Field(False, description="True quando o SIGAA marca que a referência consta na biblioteca.")


class PlanoCurso(BaseModel):
    metodologia: str | None = Field(None, description="Metodologia de ensino.")
    procedimentos_avaliacao: str | None = Field(None, description="Procedimentos de avaliação da aprendizagem.")
    horario_atendimento: str | None = Field(None, description="Horário de atendimento do docente.")
    objetivos: str | None = Field(None, description="Objetivos, quando o plano traz.")
    id_componente: int | None = Field(None, description="Id do componente (link 'Programa atual do componente').")
    cronograma: list[AulaCronograma] = Field(default_factory=list, description="Cronograma de aulas.")
    avaliacoes: list[AvaliacaoPlano] = Field(default_factory=list, description="Avaliações previstas no plano.")
    referencias_basicas: list[ReferenciaPlano] = Field(default_factory=list)
    referencias_complementares: list[ReferenciaPlano] = Field(default_factory=list)
    campos_extras: dict[str, str] = Field(default_factory=dict, description="Outros rótulos do plano (th: td).")


class ProgramaComponente(BaseModel):
    """Programa do componente curricular (ementa, objetivos, conteúdo, bibliografia)."""

    codigo: str | None = None
    nome: str | None = None
    disponivel: bool = Field(True, description="False quando o SIGAA diz que o componente não possui programa cadastrado.")
    mensagem: str | None = Field(None, description="Mensagem do SIGAA (ex.: 'não possui um programa cadastrado').")
    ementa: str | None = None
    objetivos: str | None = None
    conteudo: str | None = None
    competencias: str | None = Field(None, description="Competências e habilidades.")
    metodologia: str | None = None
    avaliacao: str | None = None
    referencias: str | None = Field(None, description="Bibliografia como texto.")
    campos: dict[str, str] = Field(default_factory=dict, description="Todos os rótulos → valores da tela.")


# ------------------------------------------------------------------ materiais
class ConteudoTurma(BaseModel):
    """Conteúdo/Página web criada pelo docente."""

    id: int | None = Field(None, description="Id do conteúdo.")
    titulo: str = Field(description="Título.")
    criado_em: date | None = Field(None, description="Data de criação.")
    conteudo: str | None = Field(None, description="Texto da página (só no detalhe).")
    conteudo_html: str | None = Field(None, description="HTML da página (só no detalhe).")


class ReferenciaTurma(BaseModel):
    """Indicação de referência (site, livro, artigo...) do menu 'Referências'."""

    id: int | None = Field(None, description="Id da referência.")
    nome: str = Field(description="Título/nome.")
    tipo: str | None = Field(None, description="Site, Livro, Artigo, Revista...")
    url: str | None = Field(None, description="Link, quando houver.")
    topico: str | None = Field(None, description="Tópico de aula ao qual está vinculada.")
    autor: str | None = Field(None, description="Autor (só no detalhe).")
    ano: int | None = Field(None, description="Ano (só no detalhe).")
    detalhes: str | None = Field(None, description="Campo 'Detalhes' (só no detalhe).")


class Video(BaseModel):
    id: int | None = Field(None, description="Id do vídeo.")
    titulo: str
    descricao: str | None = None
    url: str | None = Field(None, description="Link do vídeo (YouTube etc.) ou do arquivo.")
    topico: str | None = None
    data: date | None = None


class Arquivo(BaseModel):
    id: int | None = Field(None, description="Id do arquivo — use em /arquivos/{arquivo_id} pra baixar.")
    nome: str = Field(description="Nome do arquivo como o docente publicou.")
    descricao: str | None = None
    topico: str | None = Field(None, description="Tópico de aula onde o arquivo está.")
    data: date | None = Field(None, description="Data de publicação.")
    tamanho: str | None = Field(None, description="Tamanho como o SIGAA mostra.")
    url: str | None = Field(None, description="URL de download direto do SIGAA (/sigaa/verProducao?idProducao=...&key=...), precisa da sessão.")


# ------------------------------------------------------------------ atividades
class Tarefa(BaseModel):
    id: int | None = Field(None, description="Id da tarefa.")
    titulo: str
    descricao: str | None = Field(None, description="Enunciado (no detalhe).")
    inicio: datetime | None = Field(None, description="Início do período de envio.")
    fim: datetime | None = Field(None, description="Prazo final de envio.")
    enviada: bool | None = Field(None, description="True quando o aluno já enviou.")
    nota: float | None = Field(None, description="Nota atribuída, quando houver.")
    status: str | None = Field(None, description="Texto cru da situação/coluna de envio.")
    em_grupo: bool | None = Field(None, description="True quando é tarefa em grupo.")
    aberta: bool | None = Field(None, description="Calculado: agora está dentro do período de envio.")
    topico: str | None = None
    campos_extras: dict[str, str] = Field(default_factory=dict)


class TarefaPendente(Tarefa):
    turma_id: int | None = Field(None, description="idTurma da turma da tarefa.")
    turma_codigo: str | None = None
    turma_nome: str | None = None


class Questionario(BaseModel):
    id: int | None = None
    titulo: str
    inicio: datetime | None = None
    fim: datetime | None = None
    respondido: bool | None = Field(None, description="True quando o aluno já respondeu/enviou.")
    nota: float | None = None
    status: str | None = Field(None, description="Texto cru da situação.")
    campos_extras: dict[str, str] = Field(default_factory=dict)


class Enquete(BaseModel):
    id: int | None = None
    pergunta: str
    prazo: datetime | date | None = Field(None, description="Data limite / data da enquete.")
    status: str | None = Field(None, description="Texto cru (ex.: 'Aberta', 'Votado').")
    votou: bool | None = None
    resultados: dict[str, float] = Field(default_factory=dict, description="Opção → votos/% (quando o SIGAA mostra o resultado).")
    campos_extras: dict[str, str] = Field(default_factory=dict)


class Avaliacao(BaseModel):
    id: int | None = Field(None, description="Id da data de avaliação.")
    data: date | None = None
    hora: str | None = Field(None, description="HH:MM.")
    descricao: str


class AvaliacaoAgendada(Avaliacao):
    turma_id: int | None = None
    turma_codigo: str | None = None
    turma_nome: str | None = None


# ------------------------------------------------------------------ fórum
class ForumTurma(BaseModel):
    id: int = Field(description="Posição do fórum na lista da turma (1, 2...). O SIGAA não expõe id numérico pro aluno; a ordem é estável.")
    titulo: str
    descricao: str | None = None
    aula: str | None = Field(None, description="Tópico de aula ao qual o fórum está vinculado.")
    tipo: str | None = Field(None, description="Fórum geral, Uma única discussão simples, Perguntas e respostas...")
    autor: str | None = None
    topicos: int | None = Field(None, description="Quantidade de tópicos.")
    criado_em: datetime | date | None = None
    inicio: date | None = Field(None, description="Início do período do fórum.")
    fim: date | None = Field(None, description="Fim do período do fórum.")
    monitorar_leitura: bool | None = Field(None, description="Campo 'Monitorar Leitura' (só no detalhe).")
    ordenacao: str | None = Field(None, description="Ordenação padrão das respostas (só no detalhe).")
    campos_extras: dict[str, str] = Field(default_factory=dict)


class TopicoForum(BaseModel):
    id: int = Field(description="Posição do tópico no fórum (1, 2...).")
    titulo: str
    autor: str | None = None
    respostas: int | None = None
    ultima_mensagem_autor: str | None = None
    ultima_mensagem_em: datetime | None = None


class MensagemForum(BaseModel):
    titulo: str | None = Field(None, description="Assunto da mensagem (ex.: 'Re: ...').")
    autor: str | None = None
    data: datetime | None = None
    texto: str = Field(description="Texto da mensagem (sem HTML).")
    texto_html: str | None = None
    anexo_id: int | None = Field(None, description="idArquivo do anexo ('Ver Arquivo Anexo'), quando houver.")


class ForumDetalhe(BaseModel):
    forum: ForumTurma
    topicos: list[TopicoForum] = Field(default_factory=list)


class TopicoForumDetalhe(BaseModel):
    forum_id: int
    topico: TopicoForum
    mensagem: MensagemForum = Field(description="Mensagem que abriu o tópico.")
    respostas: list[MensagemForum] = Field(default_factory=list, description="Respostas, na ordem da tela.")


# ------------------------------------------------------------------ notas e frequência
class AvaliacaoNota(BaseModel):
    """Avaliação que compõe uma unidade (o docente pode quebrar a unidade em provas/trabalhos com peso)."""

    id: int | None = Field(None, description="Id da avaliação no SIGAA.")
    abreviacao: str = Field(description="Abreviação na coluna, ex.: P1, Sem, Av1.")
    denominacao: str | None = Field(None, description="Nome completo, ex.: 'Prova 1'.")
    peso: float | None = Field(None, description="Peso da avaliação na unidade.")
    nota: float | None = Field(None, description="Nota obtida.")


class NotaUnidade(BaseModel):
    rotulo: str = Field(description="Cabeçalho da coluna como o SIGAA mostra: 'Unid. 1', 'Unid. 2'...")
    nota: float | None = Field(None, description="Nota da unidade (None quando vazia/'-').")
    avaliacoes: list[AvaliacaoNota] = Field(default_factory=list, description="Avaliações que compõem a unidade, quando o docente detalhou.")


class NotasTurma(BaseModel):
    turma_id: int | None = None
    codigo: str | None = None
    nome: str | None = None
    periodo: str | None = None
    lancadas: bool = Field(True, description="False quando o SIGAA diz 'Ainda não foram lançadas notas'.")
    mensagem: str | None = None
    unidades: list[NotaUnidade] = Field(default_factory=list)
    reposicao: float | None = Field(None, description="Nota da reposição/prova final.")
    resultado: float | None = Field(None, description="Média/resultado final.")
    faltas: int | None = None
    situacao: str | None = Field(None, description="Sigla (APR, REP, REPF, MATR...).")
    colunas: dict[str, str] = Field(default_factory=dict, description="Linha do aluno inteira: cabeçalho → valor cru.")


class RegistroFrequencia(BaseModel):
    data: date
    situacao: str = Field(description="Texto cru: 'Presente', '2 Falta(s)', 'Não Registrada'.")
    faltas: int | None = Field(None, description="Faltas naquela aula (0 = presente; None = não registrada).")
    registrada: bool = Field(description="False quando a frequência daquela aula não foi lançada.")


class Frequencia(BaseModel):
    turma_id: int | None = None
    lancada: bool = Field(True, description="False quando o SIGAA diz 'A frequência ainda não foi lançada' (os totais vêm None).")
    registros: list[RegistroFrequencia] = Field(default_factory=list)
    total_faltas: int = Field(0, description="Soma das faltas registradas (calculado pela API).")
    presencas_registradas: int | None = None
    aulas_com_registro: int | None = Field(None, description="Número de aulas com registro de frequência.")
    percentual_registradas: float | None = Field(None, description="% de frequência em relação às aulas com registro.")
    aulas_ch: int | None = Field(None, description="Número de aulas definidas pela CH do componente.")
    percentual_ch: float | None = Field(None, description="% de frequência em relação à CH.")
    minimo_percentual: float | None = Field(None, description="Mínimo exigido (ex.: 75.0).")
    duracao_aula_min: int | None = Field(None, description="Duração da aula em minutos usada no cálculo.")
    max_faltas: int | None = Field(None, description="Calculado: faltas permitidas = aulas_ch × (1 − mínimo).")
    faltas_restantes: int | None = Field(None, description="Calculado: max_faltas − total_faltas.")


class FrequenciaResumo(BaseModel):
    turma_id: int | None = None
    codigo: str | None = None
    nome: str | None = None
    frequencia: Frequencia


# ------------------------------------------------------------------ outros
class EventoLinhaTempo(BaseModel):
    autor: str | None = None
    tipo: str = Field(description="Ex.: 'Nova Notícia cadastrada'.")
    titulo: str | None = None
    data: datetime | None = None
    texto: str | None = None


class GrupoTurma(BaseModel):
    cadastrado: bool = Field(description="False quando 'você ainda não foi cadastrado em nenhum grupo'.")
    nome: str | None = None
    membros: list[str] = Field(default_factory=list)


class EstatisticasTurma(BaseModel):
    titulo: str | None = None
    vazio: bool = True
    valores: dict[str, str] = Field(default_factory=dict, description="Rótulo → valor de qualquer tabela da tela.")
