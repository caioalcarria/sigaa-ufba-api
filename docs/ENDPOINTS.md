# Endpoints

Gerado de `api.main:app` — 161 rotas. Detalhes de cada campo em `/docs` (Swagger).

🔓 = não precisa de login · 🔒 = `Authorization: Bearer <token>`

## Autenticação

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `POST` | `/v1/auth/login` | Entrar com usuário e senha do SIGAA |
| 🔒 | `GET` | `/v1/auth/sessao` | Ver a sessão atual (validade, se o SIGAA ainda está logado) |
| 🔒 | `DELETE` | `/v1/auth/sessao` | Sair (logout no SIGAA e invalida o token) |
| 🔒 | `POST` | `/v1/auth/renovar` | Tocar o SIGAA pra sessão não expirar |

## portal

| | método | rota | o que faz |
|---|---|---|---|
| 🔒 | `GET` | `/v1/me` | Dados institucionais do aluno |
| 🔒 | `GET` | `/v1/portal` | Página inicial do Portal do Discente (tudo) |
| 🔒 | `GET` | `/v1/me/dados-pessoais` | Meus Dados Pessoais |
| 🔒 | `GET` | `/v1/me/perfil` | Perfil (descrição, áreas de interesse, Lattes, assinatura) |
| 🔒 | `GET` | `/v1/me/foto` | Foto do aluno |
| 🔒 | `GET` | `/v1/turmas` | Todas as turmas (atuais e anteriores) |
| 🔒 | `GET` | `/v1/grade-horaria` | Grade horária semanal |
| 🔒 | `GET` | `/v1/grade-horaria.ics` | Grade horária em iCalendar (.ics) |
| 🔒 | `GET` | `/v1/atividades` | Minhas atividades |
| 🔒 | `GET` | `/v1/atualizacoes` | Últimas atualizações das turmas |
| 🔒 | `GET` | `/v1/forum-curso` | Fórum do curso (tópicos) |
| 🔒 | `GET` | `/v1/forum-curso/topicos/{topico_id}` | Mensagens de um tópico do fórum do curso |
| 🔒 | `GET` | `/v1/modulos` | Módulos e portais acessíveis |
| 🔒 | `GET` | `/v1/mensagens` | Caixa postal (lista) |
| 🔒 | `GET` | `/v1/mensagens/{mensagem_id}` | Caixa postal (uma mensagem) |
| 🔒 | `GET` | `/v1/salas-livres/filtros` | Opções do relatório de salas livres |
| 🔒 | `GET` | `/v1/salas-livres` | Salas livres por prédio/dia/turno |
| 🔓 | `GET` | `/v1/horarios/tabela` | Tabela de horários da UFBA (M/T/N) |
| 🔓 | `GET` | `/v1/horarios/decodificar` | Decodificar um código de horário do SIGAA |
| 🔒 | `GET` | `/v1/fotos` | Abrir uma foto do SIGAA (perfil, participantes) |

## turma virtual

| | método | rota | o que faz |
|---|---|---|---|
| 🔒 | `GET` | `/v1/turmas-virtuais` | Turmas virtuais que o aluno pode abrir |
| 🔒 | `GET` | `/v1/turmas/{turma_id}` | Turma virtual (página principal) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/aulas` | Tópicos de aula (conteúdo programado) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/noticias` | Notícias da turma |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/noticias/{noticia_id}` | Uma notícia (texto completo) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/participantes` | Participantes (docentes e discentes) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/docentes` | Docentes da turma |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/plano-de-curso` | Plano de curso |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/programa` | Programa do componente |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/conteudos` | Conteúdos / páginas web |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/conteudos/{conteudo_id}` | Um conteúdo (texto completo) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/referencias` | Referências (sites, livros, artigos) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/referencias/{referencia_id}` | Uma referência (autor, ano, detalhes) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/videos` | Vídeos |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/arquivos` | Arquivos publicados pelo docente |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/arquivos/{arquivo_id}` | Baixar um arquivo |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/tarefas` | Tarefas (prazos, envio, nota) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/questionarios` | Questionários |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/enquetes` | Enquetes |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/avaliacoes` | Datas de avaliações |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/avaliacoes/{avaliacao_id}` | Uma data de avaliação |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/forum` | Fóruns da turma |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/forum/{forum_id}` | Um fórum e seus tópicos |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/forum/{forum_id}/topicos/{topico_id}` | Mensagens de um tópico do fórum |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/forum/{forum_id}/topicos/{topico_id}/anexos/{anexo_id}` | Baixar o anexo de uma mensagem do fórum |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/notas` | Ver Notas |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/frequencia` | Frequência |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/linha-do-tempo` | Linha do tempo da turma |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/grupo` | Meu grupo na turma |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/estatisticas` | Estatísticas (Situação dos Discentes) |
| 🔒 | `GET` | `/v1/turmas/{turma_id}/estatisticas/grafico` | Gráfico da situação dos discentes (PNG) |
| 🔒 | `GET` | `/v1/notas` | Notas de todas as turmas do semestre |
| 🔒 | `GET` | `/v1/frequencia` | Frequência de todas as turmas do semestre |
| 🔒 | `GET` | `/v1/tarefas` | Tarefas pendentes (todas as turmas do semestre) |
| 🔒 | `GET` | `/v1/avaliacoes` | Calendário de provas |

## Acadêmico

| | método | rota | o que faz |
|---|---|---|---|
| 🔒 | `GET` | `/v1/historico` | Histórico escolar completo (extraído do PDF) |
| 🔒 | `GET` | `/v1/historico/pdf` | Histórico escolar (PDF original) |
| 🔒 | `GET` | `/v1/historico/componentes` | Componentes cursados (filtráveis) |
| 🔒 | `GET` | `/v1/indices` | CR, IAP e a evolução por período |
| 🔒 | `POST` | `/v1/indices/simular` | Simular o CR com notas hipotéticas |
| 🔒 | `GET` | `/v1/integralizacao` | Quanto do curso já foi integralizado |
| 🔒 | `GET` | `/v1/pendencias` | O que falta pra se formar |
| 🔒 | `GET` | `/v1/matricula` | Matrícula do período (comprovante de solicitação) |
| 🔒 | `GET` | `/v1/matricula/processamento` | Resultado do processamento de todas as turmas solicitadas |
| 🔒 | `GET` | `/v1/matricula/processamento/{turma_id}` | Resultado do processamento de uma turma |
| 🔒 | `GET` | `/v1/documentos/comprovante-inscricao` | Comprovante de inscrição semestral (o 'Atestado de Matrícula') |
| 🔒 | `GET` | `/v1/documentos/comprovante-inscricao/html` | Comprovante de inscrição (HTML original, pra imprimir) |
| 🔒 | `GET` | `/v1/documentos/declaracao-vinculo` | Declaração de vínculo (dados extraídos) |
| 🔒 | `GET` | `/v1/documentos/declaracao-vinculo/pdf` | Declaração de vínculo (PDF original) |
| 🔒 | `GET` | `/v1/trancamentos` | Solicitações de trancamento de componente |
| 🔒 | `GET` | `/v1/suspensoes` | Suspensões de programa + histórico de movimentações |
| 🔒 | `GET` | `/v1/atividades-autonomas` | Registros de atividades autônomas/complementares |
| 🔒 | `GET` | `/v1/aproveitamentos` | Solicitações de aproveitamento de estudos |
| 🔒 | `GET` | `/v1/diploma` | Diplomas digitais emitidos |
| 🔒 | `GET` | `/v1/avaliacao-institucional` | Avaliações institucionais já respondidas |
| 🔒 | `GET` | `/v1/avaliacao-institucional/filtros` | Departamentos e períodos do relatório da avaliação institucional |
| 🔒 | `GET` | `/v1/avaliacao-institucional/resultado` | Relatório sintético da avaliação institucional de um departamento |
| 🔒 | `GET` | `/v1/avaliacao-institucional/observacoes` | Observações dos docentes sobre as minhas turmas |
| 🔒 | `GET` | `/v1/atividades-autonomas/{registro_id}` | Detalhe de um registro de atividade autônoma (com o parecer do coordenador) |
| 🔒 | `GET` | `/v1/atividades-autonomas/{registro_id}/comprovante` | Baixar o comprovante enviado |

## Planejamento

| | método | rota | o que faz |
|---|---|---|---|
| 🔒 | `GET` | `/v1/grade-curricular` | A grade curricular do aluno, marcada com o que já fez |
| 🔒 | `GET` | `/v1/planejamento/matricula` | O que dá pra pegar no semestre (oferta × grade × histórico) |
| 🔒 | `POST` | `/v1/planejamento/simular` | Simular uma matrícula (choques, CH máxima, pré-requisitos, integralização) |
| 🔒 | `GET` | `/v1/planejamento/sugestao` | Sugestão automática de matrícula sem choque |
| 🔒 | `GET` | `/v1/planejamento/previsao-oferta` | Previsão de oferta dos pendentes do aluno (por paridade, com o histórico do SIGAA) |
| 🔒 | `GET` | `/v1/carga-horaria` | Gerenciamento de horas (obrigatória, optativa, complementar, extensão) |

## Calendário acadêmico

| | método | rota | o que faz |
|---|---|---|---|
| 🔒 | `GET` | `/v1/calendario` | Calendário acadêmico de um período |
| 🔒 | `GET` | `/v1/calendario/lista` | Todos os calendários acadêmicos |

## Consultas (logado)

| | método | rota | o que faz |
|---|---|---|---|
| 🔒 | `GET` | `/v1/consultas/cursos` | Consulta geral de cursos |
| 🔒 | `GET` | `/v1/consultas/cursos/ids` | Cursos de graduação com id |
| 🔒 | `GET` | `/v1/consultas/componentes` | Buscar componentes curriculares |
| 🔒 | `GET` | `/v1/consultas/componentes/filtros` | Opções dos filtros de componentes |
| 🔒 | `GET` | `/v1/consultas/componentes/{componente_id}` | Componente curricular (ementa, CH, requisitos, equivalências) |
| 🔒 | `GET` | `/v1/consultas/estruturas` | Estruturas curriculares de um curso |
| 🔒 | `GET` | `/v1/consultas/estruturas/{estrutura_id}` | Estrutura curricular completa |
| 🔒 | `GET` | `/v1/consultas/estruturas/{estrutura_id}/declaracao-prazo-maximo` | Declaração de prazo máximo de integralização |
| 🔒 | `GET` | `/v1/consultas/turmas` | Turmas ofertadas (consulta geral) |
| 🔒 | `GET` | `/v1/consultas/turmas/historico` | Oferta histórica de um componente (todos os períodos) + paridade e previsão |
| 🔒 | `GET` | `/v1/consultas/turmas/historico/lote` | Oferta histórica de vários componentes de uma vez |
| 🔒 | `GET` | `/v1/consultas/turmas/filtros` | Opções dos filtros de turmas |
| 🔒 | `GET` | `/v1/consultas/turmas/{turma_id}` | Informações da turma (vagas e solicitações) |
| 🔒 | `GET` | `/v1/consultas/turmas/{turma_id}/processamento` | Resultado do processamento da matrícula (agregado) |
| 🔒 | `GET` | `/v1/consultas/unidades` | Buscar unidades acadêmicas |
| 🔒 | `GET` | `/v1/consultas/unidades/tipos` | Tipos de unidade acadêmica |

## Público · cursos, componentes e turmas

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `GET` | `/v1/publico/cursos` | Cursos (público) |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}` | Página pública do curso |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}/estruturas` | Estruturas curriculares do curso (público) |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id}` | Estrutura curricular completa (público) |
| 🔓 | `GET` | `/v1/publico/estruturas/{estrutura_id}` | Estrutura curricular (atalho, exige ?curso=) |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}/calendario` | Calendário do curso (público) |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}/projeto-pedagogico` | Projeto pedagógico do curso |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}/noticias` | Notícias do curso |
| 🔓 | `GET` | `/v1/publico/cursos/{curso_id}/turmas` | Turmas com vagas reservadas ao curso |
| 🔓 | `GET` | `/v1/publico/componentes` | Buscar componentes curriculares (público) |
| 🔓 | `GET` | `/v1/publico/componentes/codigo/{codigo}` | Componente pelo código (formato completo) |
| 🔓 | `GET` | `/v1/publico/componentes/codigo/{codigo}/programa` | Programa do componente |
| 🔓 | `GET` | `/v1/publico/componentes/{componente_id}` | Componente pelo id (GET direto) |
| 🔓 | `GET` | `/v1/publico/turmas` | Turmas ofertadas por unidade (público) |

## Público · docentes e unidades

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `GET` | `/v1/publico/unidades` | Unidades que ofertam turmas |
| 🔓 | `GET` | `/v1/publico/docentes` | Buscar docentes |
| 🔓 | `GET` | `/v1/publico/docentes/{siape}` | Perfil público do docente |
| 🔓 | `GET` | `/v1/publico/docentes/{siape}/producao` | Produção intelectual do docente |
| 🔓 | `GET` | `/v1/publico/docentes/{siape}/disciplinas` | Disciplinas ministradas pelo docente |
| 🔓 | `GET` | `/v1/publico/centros` | Centros / unidades acadêmicas |
| 🔓 | `GET` | `/v1/publico/centros/{centro_id}` | Portal do centro |
| 🔓 | `GET` | `/v1/publico/departamentos` | Departamentos |
| 🔓 | `GET` | `/v1/publico/departamentos/{departamento_id}` | Portal do departamento |
| 🔓 | `GET` | `/v1/publico/departamentos/{departamento_id}/docentes` | Corpo docente do departamento |
| 🔓 | `GET` | `/v1/publico/departamentos/{departamento_id}/componentes` | Componentes do departamento |
| 🔓 | `GET` | `/v1/publico/responsaveis` | Chefes, coordenadores e diretores |

## Público · biblioteca

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `GET` | `/v1/publico/biblioteca/acervo` | Buscar no acervo das bibliotecas |
| 🔓 | `GET` | `/v1/publico/biblioteca/acervo/{titulo_id}` | Exemplares de um título |
| 🔓 | `GET` | `/v1/publico/biblioteca/artigos` | Buscar artigos de periódicos |
| 🔓 | `GET` | `/v1/publico/biblioteca/aquisicoes` | Aquisições das bibliotecas |
| 🔓 | `GET` | `/v1/publico/biblioteca/novas-aquisicoes` | Informativo de novas aquisições |

## Público · pós-graduação e processos seletivos

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `GET` | `/v1/publico/processos-seletivos` | Processos seletivos |
| 🔓 | `GET` | `/v1/publico/processos-seletivos/{processo_id}` | Processo seletivo |
| 🔓 | `GET` | `/v1/publico/programas-pos` | Programas de pós-graduação |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}` | Programa de pós |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}/areas` | Áreas de concentração e linhas de pesquisa |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}/cursos` | Cursos do programa |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}/docentes` | Corpo docente do programa |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}/processos-seletivos` | Processos seletivos do programa |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}/noticias` | Notícias do programa |
| 🔓 | `GET` | `/v1/publico/programas-pos/{programa_id}/noticias/{noticia_id}` | Notícia do programa |
| 🔓 | `GET` | `/v1/publico/acordos-mobilidade` | Acordos de cooperação/mobilidade internacional |

## Público · pesquisa, extensão e cursos abertos

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `GET` | `/v1/publico/pesquisa/projetos` | Projetos de pesquisa ('quem pesquisa o quê') |
| 🔓 | `GET` | `/v1/publico/pesquisa/projetos/{projeto_id}` | Projeto de pesquisa |
| 🔓 | `GET` | `/v1/publico/pesquisa/bases` | Bases/grupos de pesquisa |
| 🔓 | `GET` | `/v1/publico/pesquisa/bolsistas` | Bolsistas de iniciação científica |
| 🔓 | `GET` | `/v1/publico/pesquisa/laboratorios` | Laboratórios de pesquisa |
| 🔓 | `GET` | `/v1/publico/pesquisa/laboratorios/{laboratorio_id}` | Laboratório de pesquisa |
| 🔓 | `GET` | `/v1/publico/extensao/acoes` | Ações de extensão |
| 🔓 | `GET` | `/v1/publico/extensao/inscricoes-abertas` | Cursos/eventos de extensão com inscrição aberta |
| 🔓 | `GET` | `/v1/publico/extensao/acoes/{acao_id}` | Ação de extensão |
| 🔓 | `GET` | `/v1/publico/cursos-abertos` | Cursos abertos (turmas com conteúdo público) |
| 🔓 | `GET` | `/v1/publico/cursos-abertos/centros` | Centros com cursos abertos |
| 🔓 | `GET` | `/v1/publico/cursos-abertos/centros/{centro_id}/departamentos` | Departamentos de um centro (cursos abertos) |
| 🔓 | `GET` | `/v1/publico/cursos-abertos/{turma_id}` | Curso aberto |

## Sistema

| | método | rota | o que faz |
|---|---|---|---|
| 🔓 | `GET` | `/v1/status` | A API e o SIGAA estão no ar? |
