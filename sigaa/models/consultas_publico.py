"""Modelos do SIGAA PÚBLICO (https://sigaa.ufba.br/sigaa/public/) — tudo que se consulta SEM login:
cursos, estruturas curriculares, componentes, turmas, docentes, departamentos/centros, responsáveis
(chefes/coordenadores/diretores) e — nas seções de baixo — biblioteca, processos seletivos, pesquisa,
extensão e afins.

Convenções: ids são os NUMÉRICOS do SIGAA (estáveis entre sessões); carga horária em horas ``int``;
datas ``date``; ausente = ``None``; listas vazias = ``[]``.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from sigaa.models.portal import Horario, LocalAula


# ----------------------------------------------------------------------------- comuns
class Pessoa(BaseModel):
    """Pessoa citada numa página pública (coordenador, chefe, docente...)."""

    nome: str = Field(description="Nome como o SIGAA mostra.")
    siape: int | None = Field(None, description="SIAPE do servidor quando a página traz o link do perfil público (portal.jsf?siape=).")
    cargo: str | None = Field(None, description="Cargo/papel quando informado: 'Coordenação', 'Vice-Coordenação', 'Chefe'...")


class OpcaoSelect(BaseModel):
    """Uma opção de um <select> de filtro do SIGAA (unidades, níveis, centros...)."""

    valor: str = Field(description="Valor enviado no formulário (normalmente o id numérico como texto).")
    rotulo: str = Field(description="Texto da opção.")


# ----------------------------------------------------------------------------- cursos
class CursoResumo(BaseModel):
    """Linha da lista pública de cursos (public/curso/lista.jsf?nivel=X)."""

    id: int = Field(description="Id do curso no SIGAA (portal.jsf?id= na graduação; parâmetro 'id' do link na pós).")
    nome: str = Field(description="Nome do curso.")
    nivel: str = Field(description="Nível consultado: G (graduação), S (stricto sensu), L (lato), T (técnico), N (técnico integrado).")
    nivel_texto: str | None = Field(None, description="Nível por extenso quando a lista traz a coluna (MESTRADO, DOUTORADO...).")
    unidade: str | None = Field(None, description="Unidade/programa que agrupa o curso na lista (ex.: 'IC - INSTITUTO DE COMPUTAÇÃO').")
    programa_id: int | None = Field(None, description="Id do programa de pós (public/programa/portal.jsf?id=) — só stricto.")
    sede: str | None = Field(None, description="Município sede.")
    modalidade: str | None = Field(None, description="Presencial, A Distância, Semi-Presencial, Remoto.")
    coordenador: str | None = Field(None, description="Nome do coordenador (graduação).")
    url_portal: str | None = Field(None, description="URL do portal público do curso (só quando é um GET direto).")


class EventoCalendarioCurso(BaseModel):
    """Evento do calendário mostrado no portal público do curso."""

    periodo: str | None = Field(None, description="Ano.período a que o evento pertence (ex.: 2026.2).")
    descricao: str = Field(description="Descrição do evento (ex.: 'Matrícula para o período 2026.2.').")
    data_inicio: date | None = Field(None, description="Data de início (ou a data única).")
    data_fim: date | None = Field(None, description="Data de fim quando o evento é um intervalo.")


class NoticiaCurso(BaseModel):
    data: date | None = Field(None, description="Data da notícia.")
    titulo: str = Field(description="Título da notícia.")
    texto: str | None = Field(None, description="Resumo/texto quando a página traz.")


class EstruturaResumo(BaseModel):
    """Uma estrutura curricular (currículo) listada na página do curso."""

    id: int = Field(description="Id da estrutura curricular no SIGAA (parâmetro 'id' do link).")
    codigo: str = Field(description="Código da estrutura, ex.: G20251X, 195140.")
    ano_criacao: str | None = Field(None, description="Ano (ou ano.período na pós) em que foi criada.")
    ativa: bool | None = Field(None, description="True se o SIGAA marca como 'Ativa'.")
    status: str | None = Field(None, description="Status cru: 'Ativa', 'Inativa'...")
    turno: str | None = Field(None, description="Grupo/turno sob o qual aparece (ex.: 'Noturno').")


class Curso(BaseModel):
    """Página pública de um curso (graduação: portal.jsf?id=; pós: 'Detalhes do Curso')."""

    id: int = Field(description="Id do curso.")
    nivel: str = Field(description="Nível consultado (G, S, L, T, N).")
    nome: str | None = Field(None, description="Nome do curso.")
    nivel_texto: str | None = Field(None, description="Nível por extenso (pós: MESTRADO/DOUTORADO).")
    unidade: str | None = Field(None, description="Unidade responsável (centro/instituto ou programa de pós).")
    unidade_id: int | None = Field(None, description="Id do centro/programa quando há link.")
    municipio: str | None = Field(None, description="Município.")
    modalidade: str | None = Field(None, description="Modalidade de ensino.")
    coordenacao: list[Pessoa] = Field(default_factory=list, description="Coordenador(es) e vice.")
    telefones: list[str] = Field(default_factory=list, description="Telefones/ramais informados.")
    emails: list[str] = Field(default_factory=list, description="E-mails informados.")
    titulo_profissional: str | None = Field(None, description="Título conferido (ex.: 'Bacharel em Sistemas de Informação').")
    area_conhecimento: str | None = Field(None, description="Área de conhecimento CNPq.")
    convenio_academico: str | None = Field(None, description="Convênio acadêmico, quando houver.")
    endereco_alternativo: str | None = Field(None, description="Endereço alternativo.")
    apresentacao: str | None = Field(None, description="Texto de apresentação.")
    pagina_oficial: str | None = Field(None, description="Página oficial externa (pós).")
    conceito: str | None = Field(None, description="Conceito CAPES (pós), quando informado.")
    portaria: str | None = Field(None, description="Portaria de reconhecimento (pós), quando informada.")
    estruturas: list[EstruturaResumo] = Field(default_factory=list, description="Estruturas curriculares listadas (pós traz na própria página).")
    calendario: list[EventoCalendarioCurso] = Field(default_factory=list, description="Resumo do calendário mostrado na apresentação (graduação).")


class ProjetoPedagogico(BaseModel):
    """Aba 'Projeto Pedagógico do Curso' (public/curso/ppp.jsf?id=)."""

    curso_id: int = Field(description="Id do curso.")
    perfil_profissional: str | None = Field(None, description="Perfil profissional do egresso.")
    competencias_habilidades: str | None = Field(None, description="Competências e habilidades do profissional.")
    metodologia: str | None = Field(None, description="Metodologia.")
    avaliacao: str | None = Field(None, description="Avaliação do curso.")
    projeto_pedagogico: str | None = Field(None, description="Texto/arquivo do PPC (URL quando é um anexo).")


class DocenteTurmaCurso(BaseModel):
    nome: str = Field(description="Nome do docente.")
    siape: int | None = Field(None, description="SIAPE (link do perfil público).")


class TurmaCurso(BaseModel):
    """Turma listada na aba 'Turmas' do portal do curso (vagas reservadas para o curso)."""

    componente_id: int | None = Field(None, description="Id do componente curricular (link de detalhes).")
    codigo_componente: str = Field(description="Código do componente.")
    nome_componente: str = Field(description="Nome do componente.")
    periodo: str | None = Field(None, description="Ano.período da turma.")
    turma: str | None = Field(None, description="Número/código da turma (ex.: '01').")
    docentes: list[DocenteTurmaCurso] = Field(default_factory=list, description="Docentes da turma.")
    vagas_reservadas: int | None = Field(None, description="Vagas reservadas para o curso.")
    horario: Horario | None = Field(None, description="Horário decodificado (código SIGAA + datas).")


class TrabalhoCurso(BaseModel):
    """Trabalho (monografia/artigo/memorial/outro) anexado e listado no portal do curso."""

    titulo: str = Field(description="Título do trabalho.")
    autor: str | None = Field(None, description="Aluno autor.")
    orientador: str | None = Field(None, description="Orientador, quando listado.")
    ano: int | None = Field(None, description="Ano.")
    url_arquivo: str | None = Field(None, description="Link do arquivo, quando houver.")


# --------------------------------------------------------------------- estrutura curricular
class ComponenteEstrutura(BaseModel):
    """Um componente dentro de uma estrutura curricular."""

    id: int | None = Field(None, description="Id do componente (link 'Visualizar Detalhes').")
    codigo: str = Field(description="Código do componente.")
    nome: str = Field(description="Nome do componente.")
    carga_horaria: int | None = Field(None, description="Carga horária em horas.")
    natureza: str | None = Field(None, description="Obrigatória, Optativa, Complementar...")
    obrigatoria: bool | None = Field(None, description="True se a natureza é 'Obrigatória'.")


class NivelEstrutura(BaseModel):
    """Um semestre/nível da estrutura (ou o bloco de optativas/complementares)."""

    nivel: int | None = Field(None, description="Número do nível/semestre (None para optativas/complementares).")
    rotulo: str = Field(description="Rótulo como o SIGAA mostra: '1º Nível', 'Optativas', 'Complementares'.")
    tipo: str = Field(description="'nivel', 'optativas' ou 'complementares'.")
    carga_horaria_total: int | None = Field(None, description="CH total que o SIGAA soma no rodapé do bloco.")
    componentes: list[ComponenteEstrutura] = Field(default_factory=list, description="Componentes do bloco.")


class EstruturaCurricular(BaseModel):
    """Detalhes de uma estrutura curricular (resumo_curriculo.jsf)."""

    id: int | None = Field(None, description="Id da estrutura curricular.")
    curso_id: int | None = Field(None, description="Id do curso de onde a estrutura foi aberta.")
    codigo: str | None = Field(None, description="Código da estrutura (ex.: G20251X).")
    matriz_curricular: str | None = Field(None, description="Matriz: 'SISTEMAS DE INFORMAÇÃO - SALVADOR - BACHARELADO - Presencial - N'.")
    periodo_vigor: str | None = Field(None, description="Período letivo de entrada em vigor (ex.: 2025.2).")
    ch_total_minima: int | None = Field(None, description="Carga horária total mínima.")
    ch_obrigatoria_aula: int | None = Field(None, description="Subtotal de CH obrigatória de aula.")
    ch_obrigatoria_orientacao: int | None = Field(None, description="Subtotal de CH obrigatória de orientação acadêmica/profissional.")
    ch_obrigatoria_total: int | None = Field(None, description="Total de CH obrigatória.")
    ch_optativa_minima: int | None = Field(None, description="CH optativa mínima.")
    ch_complementar_minima: int | None = Field(None, description="CH complementar mínima.")
    ch_atividade_academica_especifica: int | None = Field(None, description="CH obrigatória de atividade acadêmica específica.")
    ch_maxima_eletivos: int | None = Field(None, description="CH máxima de componentes eletivos.")
    ch_maxima_periodo: int | None = Field(None, description="CH máxima por período letivo.")
    prazo_minimo: int | None = Field(None, description="Prazo mínimo para conclusão (semestres).")
    prazo_medio: int | None = Field(None, description="Prazo médio (semestres).")
    prazo_maximo: int | None = Field(None, description="Prazo máximo (semestres).")
    niveis: list[NivelEstrutura] = Field(default_factory=list, description="Semestres em ordem (1º, 2º...).")
    optativas: list[ComponenteEstrutura] = Field(default_factory=list, description="Componentes optativos.")
    complementares: list[ComponenteEstrutura] = Field(default_factory=list, description="Componentes complementares.")
    ch_total_optativas_listadas: int | None = Field(None, description="Soma da CH de todas as optativas listadas (rodapé do bloco).")


# --------------------------------------------------------------------- componentes
class ComponenteResumo(BaseModel):
    """Linha de uma busca/listagem de componentes curriculares."""

    id: int | None = Field(None, description="Id do componente no SIGAA (parâmetro 'id' do link de detalhes).")
    codigo: str = Field(description="Código, ex.: MATA37.")
    nome: str = Field(description="Nome.")
    tipo: str | None = Field(None, description="DISCIPLINA, ATIVIDADE, BLOCO, MÓDULO...")
    carga_horaria: int | None = Field(None, description="CH total em horas.")
    tem_programa: bool | None = Field(None, description="True se a listagem oferece o link 'Programa Atual' (na pós só aparece quando existe).")


class CargaHorariaItem(BaseModel):
    rotulo: str = Field(description="Rótulo da linha, ex.: 'Carga Horária de Aula Teórica - Presencial'.")
    horas: int | None = Field(None, description="Horas.")
    grupo: str | None = Field(None, description="Grupo da tabela (ex.: 'Aula', 'Orientação Acadêmica').")


class CurriculoDoComponente(BaseModel):
    """Linha da tabela 'Currículos' do detalhe do componente (em quais estruturas ele aparece)."""

    codigo: str = Field(description="Código da estrutura curricular.")
    periodo_implementacao: str | None = Field(None, description="Ano.período de implementação.")
    matriz_curricular: str | None = Field(None, description="Matriz curricular.")
    obrigatoria: bool | None = Field(None, description="Se é obrigatória nessa estrutura.")
    semestre: int | None = Field(None, description="Semestre/nível em que aparece (0 = sem semestre, optativa).")
    ativo: bool | None = Field(None, description="Se a estrutura está ativa.")


class EquivalenciaHistorico(BaseModel):
    expressao: str = Field(description="Expressão de equivalência (texto, com E/OU e parênteses).")
    ativa: bool | None = Field(None, description="Se está ativa.")
    inicio_vigencia: date | None = Field(None, description="Início da vigência.")
    fim_vigencia: date | None = Field(None, description="Fim da vigência.")


class ComponenteRef(BaseModel):
    codigo: str = Field(description="Código do componente.")
    nome: str | None = Field(None, description="Nome do componente.")


class ComponenteCurricular(BaseModel):
    """Detalhe ('Resumo do Componente Curricular') — o mesmo em busca_componentes, estrutura, turmas e departamento."""

    id: int | None = Field(None, description="Id do componente.")
    codigo: str | None = Field(None, description="Código.")
    nome: str | None = Field(None, description="Nome.")
    tipo: str | None = Field(None, description="Tipo do componente (DISCIPLINA, ATIVIDADE...).")
    modalidade: str | None = Field(None, description="Modalidade de educação.")
    unidade_responsavel: str | None = Field(None, description="Unidade responsável (com código SIPAC no fim).")
    pre_requisitos: str | None = Field(None, description="Expressão de pré-requisitos (None quando '-').")
    co_requisitos: str | None = Field(None, description="Expressão de co-requisitos (None quando '-').")
    equivalencias: str | None = Field(None, description="Expressão de equivalências (None quando '-').")
    pre_requisitos_codigos: list[str] = Field(default_factory=list, description="Códigos citados nos pré-requisitos.")
    co_requisitos_codigos: list[str] = Field(default_factory=list, description="Códigos citados nos co-requisitos.")
    equivalencias_codigos: list[str] = Field(default_factory=list, description="Códigos citados nas equivalências.")
    ementa: str | None = Field(None, description="Ementa/descrição.")
    carga_horaria_total: int | None = Field(None, description="Total de carga horária do componente.")
    carga_horaria_aula: int | None = Field(None, description="Total de CH de aula.")
    carga_horaria_teorica: int | None = Field(None, description="CH de aula teórica presencial + a distância.")
    carga_horaria_pratica: int | None = Field(None, description="CH de aula prática presencial + a distância.")
    carga_horaria_extensionista: int | None = Field(None, description="CH de aula extensionista presencial + a distância.")
    carga_horaria_ead: int | None = Field(None, description="Subtotal de CH de aula a distância.")
    cargas_horarias: list[CargaHorariaItem] = Field(default_factory=list, description="Todas as linhas da tabela de cargas horárias.")
    quantidade_avaliacoes: int | None = Field(None, description="Quantidade de avaliações.")
    matriculavel_online: bool | None = Field(None, description="Matriculável on-line.")
    necessita_orientador: bool | None = Field(None, description="Necessita de orientador.")
    possui_subturmas: bool | None = Field(None, description="Possui subturmas.")
    exige_horario: bool | None = Field(None, description="Exige horário.")
    permite_multiplas_aprovacoes: bool | None = Field(None, description="Permite múltiplas aprovações.")
    atributos: dict[str, str] = Field(default_factory=dict, description="Todos os pares rótulo→valor da tabela 'Dados Gerais' (texto cru).")
    equivalente_de: list[ComponenteRef] = Field(default_factory=list, description="Outros componentes que têm ESTE como equivalente.")
    requisito_de: list[ComponenteRef] = Field(default_factory=list, description="Outros componentes que têm ESTE como pré-requisito.")
    historico_equivalencias: list[EquivalenciaHistorico] = Field(default_factory=list, description="Histórico de expressões de equivalência.")
    curriculos: list[CurriculoDoComponente] = Field(default_factory=list, description="Estruturas curriculares em que o componente aparece.")


class ProgramaComponente(BaseModel):
    """Programa atual do componente (objetivos, conteúdo, metodologia, avaliação, bibliografia)."""

    id_componente: int | None = Field(None, description="Id do componente.")
    codigo: str | None = Field(None, description="Código do componente.")
    nome: str | None = Field(None, description="Nome do componente.")
    periodo: str | None = Field(None, description="Ano.período de vigência do programa, quando informado.")
    ementa: str | None = Field(None, description="Ementa.")
    objetivos: str | None = Field(None, description="Objetivos.")
    conteudo: str | None = Field(None, description="Conteúdo programático.")
    metodologia: str | None = Field(None, description="Metodologia.")
    avaliacao: str | None = Field(None, description="Procedimentos de avaliação.")
    competencias_habilidades: str | None = Field(None, description="Competências e habilidades.")
    referencias: str | None = Field(None, description="Bibliografia/referências (texto).")
    secoes: dict[str, str] = Field(default_factory=dict, description="Todas as seções rótulo→texto encontradas.")


# ------------------------------------------------------------------------- turmas
class DocenteTurma(BaseModel):
    nome: str = Field(description="Nome do docente.")
    carga_horaria: int | None = Field(None, description="CH do docente na turma (o número entre parênteses).")


class TurmaPublica(BaseModel):
    """Turma da consulta pública (public/turmas/listar.jsf)."""

    componente_id: int | None = Field(None, description="Id do componente (link de detalhes do agrupador).")
    codigo_componente: str = Field(description="Código do componente.")
    nome_componente: str = Field(description="Nome do componente.")
    turma: str | None = Field(None, description="Código da turma (ex.: '01').")
    periodo: str | None = Field(None, description="Ano.período (ex.: 2026.2).")
    docentes: list[DocenteTurma] = Field(default_factory=list, description="Docentes e suas CH.")
    docentes_texto: str | None = Field(None, description="Coluna 'Docente' crua.")
    local: str | None = Field(None, description="Local(is) resumido(s) ('PAF 1 - 006', 'A definir', 'Smart Class I').")
    locais: list[LocalAula] = Field(default_factory=list, description="Local + dia + hora de cada slot, quando o SIGAA detalha.")
    local_texto: str | None = Field(None, description="Coluna 'Local' crua.")


# ------------------------------------------------------------------------- docentes
class DocenteResumo(BaseModel):
    """Docente numa busca ou na lista 'Corpo Docente' de um departamento."""

    siape: int | None = Field(None, description="SIAPE (id do perfil público: public/docente/portal.jsf?siape=).")
    nome: str = Field(description="Nome.")
    unidade: str | None = Field(None, description="Unidade/departamento de lotação mostrado.")
    titulacao: str | None = Field(None, description="Titulação entre parênteses (DOUTOR, MESTRE...).")
    categoria: str | None = Field(None, description="Grupo do corpo docente (ex.: 'Ativo Permanente', 'Substituto').")
    formacao_resumo: str | None = Field(None, description="Resumo da formação mostrado na lista.")
    lattes: str | None = Field(None, description="URL do Currículo Lattes.")
    foto_url: str | None = Field(None, description="URL da foto (relativa ao SIGAA).")


class FormacaoAcademica(BaseModel):
    titulo: str = Field(description="Título/curso (texto cru).")
    instituicao: str | None = Field(None, description="Instituição, quando separada.")
    periodo: str | None = Field(None, description="Período/ano, quando separado.")


class Docente(BaseModel):
    """Perfil público do docente (public/docente/portal.jsf?siape=)."""

    siape: int = Field(description="SIAPE.")
    nome: str | None = Field(None, description="Nome.")
    unidade: str | None = Field(None, description="Unidade de lotação.")
    descricao_pessoal: str | None = Field(None, description="Descrição pessoal.")
    formacao: str | None = Field(None, description="Formação acadêmica/profissional (texto livre).")
    areas_interesse: list[str] = Field(default_factory=list, description="Áreas de interesse (uma por linha).")
    lattes: str | None = Field(None, description="URL do Currículo Lattes.")
    formacao_academica: list[FormacaoAcademica] = Field(default_factory=list, description="Tabela 'Formação Acadêmica' (quando cadastrada).")
    endereco_profissional: str | None = Field(None, description="Endereço profissional.")
    sala: str | None = Field(None, description="Sala.")
    telefone: str | None = Field(None, description="Telefone/ramal.")
    email: str | None = Field(None, description="Endereço eletrônico.")
    foto_url: str | None = Field(None, description="URL da foto (relativa ao SIGAA).")


class ProducaoItem(BaseModel):
    texto: str = Field(description="Linha da produção como o SIGAA mostra (título, autores, datas).")
    titulo: str | None = Field(None, description="Título (primeiro trecho antes da vírgula), quando dá pra separar.")
    data: str | None = Field(None, description="Data 'MM/AAAA' mais recente citada, quando houver.")
    situacao: str | None = Field(None, description="'Orientação em Andamento', 'Concluída em MM/AAAA'... (orientações).")


class ProducaoCategoria(BaseModel):
    categoria: str = Field(description="Categoria (ex.: 'Trabalho de Fim de Curso', 'Orientações de Pós-Graduação', 'Artigo...').")
    quantidade: int | None = Field(None, description="Quantidade que o SIGAA mostra entre parênteses.")
    itens: list[ProducaoItem] = Field(default_factory=list, description="Itens da categoria.")


class DisciplinaMinistrada(BaseModel):
    periodo: str = Field(description="Ano.período.")
    codigo: str = Field(description="Código do componente.")
    nome: str = Field(description="Nome do componente.")
    carga_horaria: int | None = Field(None, description="CH em horas.")
    horario: Horario | None = Field(None, description="Horário decodificado (código + datas).")


# --------------------------------------------------------------- unidades (centros/departamentos)
class UnidadeRef(BaseModel):
    id: int = Field(description="Id da unidade no SIGAA.")
    nome: str = Field(description="Nome.")


class CentroResumo(BaseModel):
    """Centro/unidade especializada na lista pública (public/centro/lista.jsf)."""

    id: int = Field(description="Id do centro (public/centro/portal.jsf?id=).")
    nome: str = Field(description="Nome (sem a sigla).")
    sigla: str | None = Field(None, description="Sigla (ex.: EADM, IC/UFBA).")
    municipio: str | None = Field(None, description="Município.")
    departamentos: list[UnidadeRef] = Field(default_factory=list, description="Departamentos que o centro engloba.")


class CursoDoCentro(BaseModel):
    id: int | None = Field(None, description="Id do curso (portal.jsf?id=).")
    nome: str = Field(description="Nome.")
    municipio: str | None = Field(None, description="Município.")
    modalidade: str | None = Field(None, description="Modalidade.")
    coordenador: str | None = Field(None, description="Coordenador.")


class Centro(BaseModel):
    """Portal público do centro (portal + abas Departamentos/Graduação/Pós-graduação)."""

    id: int = Field(description="Id do centro.")
    nome: str | None = Field(None, description="Nome.")
    sigla: str | None = Field(None, description="Sigla/cabeçalho (ex.: 'IC/UFBA (SALVADOR)').")
    apresentacao: str | None = Field(None, description="Texto de apresentação.")
    diretoria: list[Pessoa] = Field(default_factory=list, description="Diretor(es) do centro.")
    telefones: list[str] = Field(default_factory=list, description="Telefones.")
    endereco_alternativo: str | None = Field(None, description="Endereço alternativo.")
    departamentos: list[UnidadeRef] = Field(default_factory=list, description="Departamentos do centro.")
    cursos: list[CursoDoCentro] = Field(default_factory=list, description="Cursos de graduação do centro.")
    programas: list[UnidadeRef] = Field(default_factory=list, description="Programas de pós-graduação do centro.")


class DepartamentoResumo(BaseModel):
    id: int = Field(description="Id do departamento (public/departamento/portal.jsf?id=).")
    nome: str = Field(description="Nome.")
    centro: str | None = Field(None, description="Centro a que pertence.")


class Departamento(BaseModel):
    """Portal público do departamento (public/departamento/portal.jsf?id=)."""

    id: int = Field(description="Id do departamento.")
    sigla: str | None = Field(None, description="Sigla (ex.: DCC/IC/UFBA).")
    nome: str | None = Field(None, description="Nome.")
    centro_id: int | None = Field(None, description="Id do centro (link do cabeçalho).")
    apresentacao: str | None = Field(None, description="Apresentação.")
    chefia: list[Pessoa] = Field(default_factory=list, description="Chefe e subchefe.")
    telefones: list[str] = Field(default_factory=list, description="Telefones.")
    endereco_alternativo: str | None = Field(None, description="Endereço alternativo.")
    noticias: list[str] = Field(default_factory=list, description="Títulos das últimas notícias.")


class UnidadeAcademica(BaseModel):
    """Unidade que oferta turmas/componentes (opções do filtro 'Unidade' da consulta de turmas)."""

    id: int = Field(description="Id da unidade (mesmo id do departamento/programa/colegiado).")
    nome: str = Field(description="Nome com o município (como no filtro).")


# --------------------------------------------------------------------------- responsáveis
class Responsavel(BaseModel):
    """Linha de 'Chefes, Coordenações e Diretores' (public/academico/busca_responsavel.jsf)."""

    tipo: str = Field(description="chefes | coordenadores_graduacao | coordenadores_pos | diretores.")
    centro: str | None = Field(None, description="Centro que agrupa a linha (sub-cabeçalho).")
    unidade: str = Field(description="Departamento, curso, programa ou centro.")
    nome: str = Field(description="Nome do responsável.")
    cargo: str | None = Field(None, description="Coordenação, Vice-Coordenação... (quando a coluna existe).")
    telefone: str | None = Field(None, description="Telefone/ramal (None se vazio ou 'NAO INFORMADO').")
    email: str | None = Field(None, description="E-mail.")


# ====================================================================================================
# BIBLIOTECA, PROCESSOS SELETIVOS, DIPLOMAS, MOBILIDADE E PROGRAMAS DE PÓS  (frente 'extras1')
# ====================================================================================================
# ------------------------------------------------------------------ biblioteca
class AcervoTitulo(BaseModel):
    """Uma linha do resultado da busca pública no acervo."""

    id: int | None = Field(None, description="idTitulo do SIGAA (usado pra abrir o detalhe).")
    autor: str | None = Field(None, description="Autor principal, como o catálogo mostra.")
    titulo: str = Field(..., description="Título da obra.")
    edicao: str | None = Field(None, description="Edição (ex.: '12. ed.').")
    ano: str | None = Field(None, description="Ano(s) de publicação como texto (pode vir '1988' ou 'c2010').")
    quantidade: int | None = Field(None, description="Quantidade de materiais (exemplares) do título.")


class AcervoExemplar(BaseModel):
    """Um exemplar/material de um título do acervo."""

    id_material: int | None = Field(None, description="idMaterial do SIGAA, quando a tela expõe.")
    biblioteca: str | None = Field(None, description="Biblioteca que guarda o exemplar.")
    localizacao: str | None = Field(None, description="Número de chamada/localização na estante.")
    tipo_material: str | None = Field(None, description="Tipo de material (Livro, DVD, Tese...).")
    colecao: str | None = Field(None, description="Coleção (Acervo Circulante, Obras de Referência...).")
    status: str | None = Field(None, description="Status do exemplar (REGULAR, NÃO CIRCULA...).")
    situacao: str | None = Field(None, description="Situação (Disponível, Emprestado, Reservado...).")


class AcervoTituloDetalhe(BaseModel):
    """Tela 'Materiais de um Título' (detalhe público de um título do acervo)."""

    id: int | None = Field(None, description="idTitulo do SIGAA.")
    registro_sistema: int | None = Field(None, description="Número do registro no sistema.")
    numero_chamada: str | None = Field(None, description="Número de chamada do título.")
    autor: str | None = Field(None, description="Autor principal.")
    titulo: str | None = Field(None, description="Título.")
    local_publicacao: str | None = Field(None, description="Local da publicação.")
    editora: str | None = Field(None, description="Editora.")
    ano_publicacao: str | None = Field(None, description="Ano de publicação como texto.")
    edicao: str | None = Field(None, description="Edição.")
    assuntos: list[str] = Field(default_factory=list, description="Assuntos (cabeçalhos) do título.")
    notas: list[str] = Field(default_factory=list, description="Notas gerais.")
    total_exemplares: int | None = Field(None, description="Total de exemplares informado na legenda da tabela.")
    exemplares: list[AcervoExemplar] = Field(default_factory=list, description="Exemplares listados.")


class AcervoArtigo(BaseModel):
    """Uma linha do resultado da busca pública de artigos."""

    id: int | None = Field(None, description="Id do artigo no SIGAA, se o link expuser.")
    titulo: str = Field(..., description="Título do artigo.")
    autor: str | None = Field(None, description="Autor(es).")
    publicacao: str | None = Field(None, description="Periódico/fonte, quando a tabela traz.")
    ano: str | None = Field(None, description="Ano, quando a tabela traz.")


class AquisicaoBiblioteca(BaseModel):
    """Um livro da consulta pública de aquisições (compras de livros)."""

    ano_aquisicao: int | None = Field(None, description="Ano da aquisição (agrupador da tabela).")
    centro: str | None = Field(None, description="Centro/unidade que solicitou.")
    departamento: str | None = Field(None, description="Departamento/coordenação que solicitou.")
    titulo: str = Field(..., description="Título do livro.")
    volume: str | None = Field(None, description="Volume, quando informado.")
    ano_publicacao: int | None = Field(None, description="Ano de publicação.")
    autor: str | None = Field(None, description="Autor.")
    quantidade: int | None = Field(None, description="Quantidade adquirida.")


class NovaAquisicaoBiblioteca(BaseModel):
    """Um material do informativo de novas aquisições."""

    area: str | None = Field(None, description="Área do conhecimento (CNPq) em que o material aparece.")
    descricao: str = Field(..., description="Texto do material como listado (referência bibliográfica).")


class NovasAquisicoesBiblioteca(BaseModel):
    """Informativo de novas aquisições das bibliotecas."""

    bibliotecas: str | None = Field(None, description="Bibliotecas filtradas ('Todas' se nenhuma).")
    area: str | None = Field(None, description="Área do conhecimento filtrada.")
    data_inicio: date | None = Field(None, description="Início do período consultado.")
    data_fim: date | None = Field(None, description="Fim do período consultado.")
    total: int = Field(0, description="Total informado em 'Novas Aquisições das Bibliotecas (N)'.")
    itens: list[NovaAquisicaoBiblioteca] = Field(default_factory=list, description="Materiais listados.")


# ---------------------------------------------------------- processos seletivos
class ProcessoSeletivoResumo(BaseModel):
    """Linha da lista pública de processos seletivos (um curso de um edital)."""

    id: int = Field(..., description="Id do processo seletivo no SIGAA.")
    edital: str | None = Field(None, description="Nome do edital/processo (agrupador da tabela).")
    curso: str | None = Field(None, description="Curso a que o processo se refere.")
    vagas: int | None = Field(None, description="Número de vagas.")
    inscricao_inicio: date | None = Field(None, description="Início do período de inscrições.")
    inscricao_fim: date | None = Field(None, description="Fim do período de inscrições.")
    aberto: bool = Field(False, description="True se o período está em aberto (verde na tela).")
    id_programa: int | None = Field(None, description="Id do programa de pós (link 'Acessar página do programa').")


class EtapaProcessoSeletivo(BaseModel):
    """Etapa do cronograma de um processo seletivo."""

    nome: str = Field(..., description="Nome da etapa.")
    descricao: str | None = Field(None, description="Descrição longa (title do nome).")
    divulgacao_resultado: datetime | None = Field(None, description="Divulgação dos resultados até.")
    interposicao_recurso: datetime | None = Field(None, description="Interposição de recursos até.")
    analise_recurso: datetime | None = Field(None, description="Análise dos recursos até.")


class MembroComissaoProcessoSeletivo(BaseModel):
    """Membro da comissão do processo seletivo."""

    nome: str = Field(..., description="Nome do membro.")
    funcao: str | None = Field(None, description="Função (MEMBRO, PRESIDENTE...).")


class DocumentoProcessoSeletivo(BaseModel):
    """Arquivo publicado no processo seletivo (edital, resultado...)."""

    descricao: str = Field(..., description="Descrição do documento.")
    tipo: str | None = Field(None, description="Tipo do documento.")
    disponibilizado_em: datetime | None = Field(None, description="Quando foi disponibilizado.")
    url: str | None = Field(None, description="Link de download (relativo ao SIGAA).")


class NoticiaProcessoSeletivo(BaseModel):
    """Notícia/comunicado do processo seletivo."""

    titulo: str = Field(..., description="Título/texto da notícia.")
    data: str | None = Field(None, description="Data como aparece na tela.")


class ProcessoSeletivo(BaseModel):
    """Detalhe público de um processo seletivo ('Dados do Processo Seletivo')."""

    id: int | None = Field(None, description="Id do processo seletivo.")
    curso: str | None = Field(None, description="Curso (com sigla e município).")
    programa: str | None = Field(None, description="Unidade/programa responsável.")
    edital: str | None = Field(None, description="Nome do edital.")
    nivel: str | None = Field(None, description="Nível (DOUTORADO, MESTRADO, TÉCNICO...).")
    inscricao_inicio: datetime | None = Field(None, description="Início das inscrições.")
    inscricao_fim: datetime | None = Field(None, description="Fim das inscrições.")
    vagas: int | None = Field(None, description="Número de vagas.")
    questionario: str | None = Field(None, description="Questionário específico da inscrição.")
    inscricoes_abertas: bool = Field(False, description="True se a tela oferece o link de inscrição.")
    etapas: list[EtapaProcessoSeletivo] = Field(default_factory=list, description="Cronograma de etapas.")
    comissao: list[MembroComissaoProcessoSeletivo] = Field(default_factory=list, description="Membros da comissão.")
    documentos: list[DocumentoProcessoSeletivo] = Field(default_factory=list, description="Arquivos publicados.")
    descricao: str | None = Field(None, description="Descrição e orientações aos candidatos.")
    orientacoes_inscritos: str | None = Field(None, description="Orientações aos inscritos.")
    noticias: list[NoticiaProcessoSeletivo] = Field(default_factory=list, description="Notícias e comunicados.")


# ------------------------------------------------------- acordos de mobilidade
class AcordoMobilidade(BaseModel):
    """Linha da lista pública de acordos de cooperação/mobilidade."""

    id: int | None = Field(None, description="Id do acordo, se o link de visualizar expuser.")
    pais: str | None = Field(None, description="País da instituição parceira.")
    instituicao: str | None = Field(None, description="Instituição parceira.")
    sigla: str | None = Field(None, description="Sigla da instituição.")
    status: str | None = Field(None, description="Status (Ativo, Encerrado, Tramitação...).")
    fim_vigencia: date | None = Field(None, description="Fim da vigência do acordo.")


# --------------------------------------------------------- programas de pós
class ProgramaPosResumo(BaseModel):
    """Linha da lista pública de programas de pós-graduação."""

    id: int = Field(..., description="Id do programa (parâmetro id do portal.jsf).")
    nome: str = Field(..., description="Nome do programa.")
    sigla: str | None = Field(None, description="Sigla (o que vem entre parênteses no fim do nome).")
    centro: str | None = Field(None, description="Centro/unidade a que o programa pertence.")


class NoticiaProgramaPos(BaseModel):
    """Notícia listada na página pública do programa."""

    id: int = Field(..., description="Id da notícia (parâmetro noticia=).")
    titulo: str = Field(..., description="Título da notícia.")
    data: datetime | None = Field(None, description="Data de cadastro (a lista completa traz hora; o portal só a data).")


class NoticiaProgramaPosDetalhe(BaseModel):
    """Texto completo de uma notícia do programa."""

    id: int | None = Field(None, description="Id da notícia.")
    id_programa: int | None = Field(None, description="Id do programa.")
    titulo: str | None = Field(None, description="Título.")
    texto: str = Field("", description="Texto da notícia (texto puro, quebras de linha preservadas).")


class ProcessoSeletivoProgramaPos(BaseModel):
    """Processo seletivo listado na página do programa."""

    id: int = Field(..., description="Id do processo seletivo (abre o mesmo detalhe da lista pública).")
    nivel: str | None = Field(None, description="Nível (Mestrado, Doutorado...).")
    edital: str | None = Field(None, description="Nome do processo/edital.")
    inscricao_inicio: date | None = Field(None, description="Início das inscrições.")
    inscricao_fim: date | None = Field(None, description="Fim das inscrições.")


class CoordenadorProgramaPos(BaseModel):
    """Pessoa do quadro 'Coordenação do Programa' (coordenador ou vice; o SIGAA não diferencia na tela)."""

    nome: str = Field(..., description="Nome.")
    siape: int | None = Field(None, description="SIAPE (link pra página pública do docente).")
    telefones: list[str] = Field(default_factory=list, description="Telefones/ramais informados.")
    email: str | None = Field(None, description="E-mail informado.")


class ApresentacaoProgramaPos(BaseModel):
    """Página 'Apresentação' do programa."""

    texto: str | None = Field(None, description="Texto de apresentação.")
    endereco_alternativo: str | None = Field(None, description="Site alternativo informado.")
    coordenacao: list[CoordenadorProgramaPos] = Field(default_factory=list, description="Quadro 'Coordenação do Programa'.")


class ProgramaPos(BaseModel):
    """Página pública de um programa de pós-graduação (portal + apresentação)."""

    id: int | None = Field(None, description="Id do programa.")
    nome: str | None = Field(None, description="Nome do programa.")
    sigla: str | None = Field(None, description="Sigla.")
    centro: str | None = Field(None, description="Centro/unidade.")
    id_centro: int | None = Field(None, description="Id do centro (portal público do centro).")
    telefone: str | None = Field(None, description="Telefone/ramal.")
    email: str | None = Field(None, description="E-mail institucional do programa.")
    site: str | None = Field(None, description="Site externo do programa.")
    apresentacao: str | None = Field(None, description="Texto da página 'Apresentação'.")
    endereco_alternativo: str | None = Field(None, description="Site alternativo (página 'Apresentação').")
    coordenacao: list[CoordenadorProgramaPos] = Field(default_factory=list, description="Coordenação do programa (página 'Apresentação').")
    secoes_extras: dict[str, int] = Field(default_factory=dict, description="Seções extras do menu 'Outras Opções' (título -> id extra).")
    noticias: list[NoticiaProgramaPos] = Field(default_factory=list, description="Últimas notícias do portal.")
    processos_seletivos: list[ProcessoSeletivoProgramaPos] = Field(default_factory=list, description="Processos seletivos em destaque.")


class LinhaPesquisaPos(BaseModel):
    """Linha de pesquisa de uma área de concentração."""

    id: int | None = Field(None, description="Id da linha de pesquisa.")
    nome: str = Field(..., description="Nome da linha.")
    descricao: str | None = Field(None, description="Descrição da linha.")


class AreaConcentracaoPos(BaseModel):
    """Área de concentração de um programa, por nível."""

    nivel: str | None = Field(None, description="Nível (Mestrado, Doutorado...).")
    nome: str = Field(..., description="Nome da área de concentração.")
    linhas_pesquisa: list[LinhaPesquisaPos] = Field(default_factory=list, description="Linhas de pesquisa.")


class CursoProgramaPos(BaseModel):
    """Curso oferecido por um programa de pós."""

    id: int | None = Field(None, description="Id do curso no SIGAA.")
    nome: str = Field(..., description="Nome do curso.")
    nivel: str | None = Field(None, description="Nível por extenso (Mestrado, Doutorado...).")
    nivel_codigo: str | None = Field(None, description="Código do nível no SIGAA (E=mestrado, D=doutorado...).")
    url_capes: str | None = Field(None, description="Link do documento de reconhecimento/conceito da CAPES.")


class DocenteProgramaPos(BaseModel):
    """Membro do corpo docente de um programa."""

    nome: str = Field(..., description="Nome.")
    grupo: str | None = Field(None, description="Grupo/área em que aparece (área de concentração, Pós-Doutorandos...).")
    vinculo: str | None = Field(None, description="Vínculo (PROFESSOR...).")
    nivel: str | None = Field(None, description="Nível no programa (PERMANENTE, COLABORADOR...).")
    ramal: str | None = Field(None, description="Telefone/ramal.")
    siape: int | None = Field(None, description="SIAPE (link pra página pública do docente).")
    lattes: str | None = Field(None, description="URL do currículo Lattes.")
    email: str | None = Field(None, description="E-mail publicado.")


# ====================================================================================================
# PESQUISA, EXTENSÃO E CURSOS ABERTOS  (frente 'extras2')
# ====================================================================================================
# ------------------------------------------------------------------ pesquisa
class MembroEquipePublica(BaseModel):
    """Pessoa da equipe de um projeto de pesquisa ou de uma ação de extensão."""

    nome: str = Field(description="Nome da pessoa como o SIGAA exibe.")
    categoria: str | None = Field(None, description="Categoria do vínculo: DOCENTE, DISCENTE, SERVIDOR, EXTERNO...")
    funcao: str | None = Field(None, description="Função/tipo na equipe: COORDENADOR(A), COLABORADOR(A), ALUNO(A) VOLUNTARIO(A)...")
    coordenador: bool = Field(False, description="True se a pessoa coordena o projeto/ação.")
    siape: int | None = Field(None, description="SIAPE do docente (link para o perfil público), quando houver.")


class ProjetoPesquisaResumo(BaseModel):
    """Linha da lista 'Quem pesquisa o que' (consulta_projetos.jsf)."""

    id: int | None = Field(None, description="Id numérico do projeto no SIGAA (parâmetro 'id' do link de visualização).")
    codigo: str | None = Field(None, description="Código do projeto, ex.: 'PVP17825-2024'.")
    titulo: str = Field(description="Título do projeto.")
    coordenador: str | None = Field(None, description="Nome do coordenador.")
    tipo: str | None = Field(None, description="Tipo do projeto: INTERNO, EXTERNO...")
    situacao: str | None = Field(None, description="Situação: EM EXECUÇÃO, FINALIZADO...")
    centro: str | None = Field(None, description="Centro/unidade sob o qual o projeto aparece agrupado na lista.")
    ano: int | None = Field(None, description="Ano sob o qual o projeto aparece agrupado na lista.")


class ProjetoPesquisa(BaseModel):
    """Visualização de um projeto de pesquisa (pesquisa/view.jsf)."""

    id: int | None = Field(None, description="Id numérico do projeto no SIGAA.")
    codigo: str | None = Field(None, description="Código do projeto, ex.: 'PVP17825-2024'.")
    titulo: str | None = Field(None, description="Título do projeto.")
    ano: int | None = Field(None, description="Ano do projeto (sufixo do código).")
    tipo: str | None = Field(None, description="Tipo do projeto, ex.: 'INTERNO (Projeto Novo)'.")
    situacao: str | None = Field(None, description="Situação do projeto.")
    centro: str | None = Field(None, description="Centro/unidade do projeto.")
    coordenador: str | None = Field(None, description="Nome do coordenador.")
    edital: str | None = Field(None, description="Edital ao qual o projeto foi submetido.")
    cota: str | None = Field(None, description="Cota de bolsas (texto cru, inclui o período).")
    data_inicio: date | None = Field(None, description="Início do período (extraído da cota), se houver.")
    data_fim: date | None = Field(None, description="Fim do período (extraído da cota), se houver.")
    palavras_chave: list[str] = Field(default_factory=list, description="Palavras-chave do projeto.")
    area_conhecimento: str | None = Field(None, description="Área de conhecimento (CNPq).")
    grupo_pesquisa: str | None = Field(None, description="Grupo de pesquisa (base) ao qual o projeto se vincula.")
    linha_pesquisa: str | None = Field(None, description="Linha de pesquisa.")
    resumo: str | None = Field(None, description="Descrição/resumo do projeto.")
    secoes: dict[str, str] = Field(default_factory=dict, description="Todas as seções de texto (título h4 → texto), ex.: Descrição, Objetivos.")
    membros: list[MembroEquipePublica] = Field(default_factory=list, description="Membros da equipe.")


class BasePesquisa(BaseModel):
    """Linha da lista de bases (grupos) de pesquisa (consulta_bases.jsf)."""

    id: int | None = Field(None, description="Id numérico da base, se a lista trouxer link de detalhe.")
    codigo: str | None = Field(None, description="Código da base (frequentemente vazio).")
    nome: str = Field(description="Nome da base/grupo de pesquisa.")
    coordenador: str | None = Field(None, description="Nome do coordenador.")


class BolsistaPesquisa(BaseModel):
    """Bolsista de iniciação científica (consulta_bolsistas.jsf)."""

    discente: str = Field(description="Nome do aluno bolsista.")
    tipo_bolsa: str | None = Field(None, description="Modalidade da bolsa, ex.: 'PIBIC-CNPQ (IC)'.")
    cota: str | None = Field(None, description="Cota sob a qual o bolsista aparece agrupado.")
    projeto_codigo: str | None = Field(None, description="Código do projeto de pesquisa do plano de trabalho.")
    projeto_titulo: str | None = Field(None, description="Título do projeto de pesquisa.")
    plano_titulo: str | None = Field(None, description="Título do plano de trabalho do bolsista.")
    orientador: str | None = Field(None, description="Nome do orientador.")
    data_inicio: date | None = Field(None, description="Início do período da bolsa.")
    data_fim: date | None = Field(None, description="Fim do período da bolsa (None se em aberto).")


class LaboratorioPesquisaResumo(BaseModel):
    """Linha da lista de laboratórios (consulta_laboratorios.jsf)."""

    id: int | None = Field(None, description="Id numérico do laboratório (parâmetro 'id' do link de visualização).")
    codigo: str | None = Field(None, description="Código do laboratório, ex.: 'LAB2291-2026'.")
    nome: str = Field(description="Nome do laboratório.")
    unidade: str | None = Field(None, description="Unidade - subunidade responsável.")
    coordenador: str | None = Field(None, description="Nome do coordenador.")


class LaboratorioPesquisa(BaseModel):
    """Visualização de um laboratório de pesquisa (view_laboratorio.jsf)."""

    id: int | None = Field(None, description="Id numérico do laboratório.")
    codigo: str | None = Field(None, description="Código do laboratório.")
    tipo: str | None = Field(None, description="Tipo: multiusuários ou uso restrito.")
    nome: str | None = Field(None, description="Nome do laboratório.")
    sigla: str | None = Field(None, description="Sigla.")
    descricao: str | None = Field(None, description="Descrição.")
    inicio_atividades: date | None = Field(None, description="Data de início das atividades.")
    em_atividade: bool | None = Field(None, description="Se o laboratório está em atividade.")
    area_m2: float | None = Field(None, description="Área física em m².")
    unidade: str | None = Field(None, description="Unidade.")
    subunidade: str | None = Field(None, description="Subunidade.")
    localizacao: str | None = Field(None, description="Localização física.")
    grupos_pesquisa: list[str] = Field(default_factory=list, description="Grupos de pesquisa vinculados.")
    programas_pos: list[str] = Field(default_factory=list, description="Programas de pós-graduação vinculados.")
    producoes: list[str] = Field(default_factory=list, description="Produções científicas listadas.")
    palavras_chave: list[str] = Field(default_factory=list, description="Palavras-chave.")
    presta_servicos: bool | None = Field(None, description="Se presta serviços a público interno/externo.")
    servicos: list[str] = Field(default_factory=list, description="Serviços prestados hoje.")
    pretende_prestar_servicos: bool | None = Field(None, description="Se pretende prestar serviços no futuro.")
    servicos_futuros: list[str] = Field(default_factory=list, description="Serviços que pretende oferecer.")
    coordenador: str | None = Field(None, description="Nome do coordenador.")
    inicio_coordenacao: date | None = Field(None, description="Início da coordenação.")
    vice_coordenador: str | None = Field(None, description="Nome do vice-coordenador.")


# ------------------------------------------------------------------ extensão
class AcaoExtensaoResumo(BaseModel):
    """Linha da lista de ações de extensão (consulta_extensao.jsf)."""

    id: int | None = Field(None, description="Id numérico da ação (idAtividadeExtensaoSelecionada).")
    ano: int | None = Field(None, description="Ano da ação.")
    titulo: str = Field(description="Título da ação.")
    tipo: str | None = Field(None, description="Tipo: PROGRAMA, PROJETO, CURSO, EVENTO, PRODUTO, PRESTAÇÃO DE SERVIÇOS.")
    tipo_id: int | None = Field(None, description="Código do tipo (1 programa, 2 projeto, 3 curso, 4 evento, 5 prestação, 6 produto).")
    unidade: str | None = Field(None, description="Departamento/unidade responsável (sigla).")


class AcaoExtensao(BaseModel):
    """Visualização de uma ação de extensão (viewDadosCursoEvento.jsf)."""

    id: int | None = Field(None, description="Id numérico da ação.")
    titulo: str | None = Field(None, description="Título.")
    ano: int | None = Field(None, description="Ano.")
    tipo: str | None = Field(None, description="Tipo da ação.")
    bolsas_concedidas: int | None = Field(None, description="Número de bolsas concedidas.")
    discentes_envolvidos: int | None = Field(None, description="Número de discentes envolvidos.")
    publico_estimado: int | None = Field(None, description="Público estimado.")
    area_principal: str | None = Field(None, description="Área temática principal.")
    area_cnpq: str | None = Field(None, description="Área do CNPq.")
    unidade_proponente: str | None = Field(None, description="Unidade proponente.")
    unidades_envolvidas: list[str] = Field(default_factory=list, description="Outras unidades envolvidas.")
    municipios: list[str] = Field(default_factory=list, description="Municípios de realização.")
    espacos: list[str] = Field(default_factory=list, description="Espaços de realização.")
    fonte_financiamento: str | None = Field(None, description="Fonte de financiamento.")
    url: str | None = Field(None, description="URL pública (bookmarkable) da ação.")
    coordenador: str | None = Field(None, description="Nome do coordenador (da equipe).")
    resumo: str | None = Field(None, description="Resumo da ação.")
    publico_alvo: str | None = Field(None, description="Público-alvo.")
    campos: dict[str, str] = Field(default_factory=dict, description="Todos os pares rótulo→valor da tabela de dados (inclui específicos de curso/evento/produto).")
    secoes: dict[str, str] = Field(default_factory=dict, description="Seções de texto (título h4 → texto).")
    membros: list[MembroEquipePublica] = Field(default_factory=list, description="Membros da equipe.")


class MiniAtividadeExtensao(BaseModel):
    """Mini atividade de um curso/evento com inscrição aberta."""

    titulo: str = Field(description="Título da mini atividade.")
    data: str | None = Field(None, description="Data de realização (texto cru).")
    hora: str | None = Field(None, description="Hora (texto cru).")
    local: str | None = Field(None, description="Local.")


class InscricaoExtensaoAberta(BaseModel):
    """Curso/evento de extensão com período de inscrição aberto (paginaListaPeriodosInscricoesAtividadesPublico.jsf)."""

    id: int | None = Field(None, description="Id numérico da ação de extensão (idAtividadeExtensaoSelecionada).")
    titulo: str = Field(description="Título do curso/evento.")
    tipo: str | None = Field(None, description="CURSO ou EVENTO.")
    coordenador: str | None = Field(None, description="Nome da coordenação.")
    inscricoes_ate: date | None = Field(None, description="Último dia de inscrição.")
    vagas_total: int | None = Field(None, description="Total de vagas.")
    vagas_aprovadas: int | None = Field(None, description="Inscrições aprovadas.")
    vagas_pendentes: int | None = Field(None, description="Inscrições pendentes.")
    vagas_restantes: int | None = Field(None, description="Vagas restantes.")
    mini_atividades: list[MiniAtividadeExtensao] = Field(default_factory=list, description="Mini atividades do curso/evento.")


# ------------------------------------------------------------ cursos abertos
class DepartamentoCursoAberto(BaseModel):
    """Departamento listado no menu de cursos abertos."""

    id: int | None = Field(None, description="Id numérico do departamento (só quando vem do select carregado por AJAX).")
    nome: str = Field(description="Nome do departamento.")


class CentroCursoAberto(BaseModel):
    """Centro acadêmico do filtro/menu de cursos abertos."""

    id: int = Field(description="Id numérico do centro (valor do select idCentro).")
    nome: str = Field(description="Nome do centro.")
    departamentos: list[DepartamentoCursoAberto] = Field(default_factory=list, description="Departamentos do menu lateral.")


class CursoAbertoTurma(BaseModel):
    """Turma com conteúdo aberto ao público (cursosabertos.jsf)."""

    id: int = Field(description="Id numérico da turma (parâmetro 'tid').")
    codigo: str | None = Field(None, description="Código do componente, ex.: 'PGEDU0151'.")
    nome: str = Field(description="Nome do componente.")


class DocenteCursoAberto(BaseModel):
    """Docente de uma turma aberta."""

    nome: str = Field(description="Nome do docente.")
    siape: int | None = Field(None, description="SIAPE (link para o perfil público).")


class MaterialCursoAberto(BaseModel):
    """Arquivo/material publicado num tópico da turma aberta."""

    titulo: str = Field(description="Texto do link.")
    descricao: str | None = Field(None, description="Descrição (atributo title do link).")
    id_producao: int | None = Field(None, description="Id do arquivo (idProducao).")
    url: str | None = Field(None, description="URL (relativa) de download do material.")


class TopicoCursoAberto(BaseModel):
    """Tópico de aula de uma turma aberta."""

    titulo: str = Field(description="Título do tópico.")
    data_inicio: date | None = Field(None, description="Início do tópico.")
    data_fim: date | None = Field(None, description="Fim do tópico.")
    conteudo: str | None = Field(None, description="Texto do tópico.")
    materiais: list[MaterialCursoAberto] = Field(default_factory=list, description="Materiais do tópico.")


class CursoAberto(BaseModel):
    """Página pública de uma turma aberta (resumo + material)."""

    id: int | None = Field(None, description="Id numérico da turma (tid).")
    codigo: str | None = Field(None, description="Código do componente.")
    nome: str | None = Field(None, description="Nome do componente.")
    periodo: str | None = Field(None, description="Data da oferta (período letivo, ex.: '2026.1').")
    ementa: str | None = Field(None, description="Ementa.")
    docentes: list[DocenteCursoAberto] = Field(default_factory=list, description="Docentes da turma.")
    topicos: list[TopicoCursoAberto] = Field(default_factory=list, description="Tópicos de aula com materiais.")
