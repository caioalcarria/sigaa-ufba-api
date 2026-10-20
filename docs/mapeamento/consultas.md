# Mapeamento — área "consultas"

Frente: **Consultas Gerais** do Portal do Discente + **Calendário Acadêmico** (logado) e o **SIGAA
público** sem login. A parte pública está detalhada em [`consultas_publico.md`](consultas_publico.md);
este arquivo cobre as telas logadas e as rotas de toda a área.

Visto no SIGAA UFBA v4.13.8_41_hotfix em 19/10/2026, aluno de graduação.

Código: `sigaa/models/consultas.py` · `sigaa/parsers/consultas.py` · `sigaa/services/consultas.py` ·
`api/routes/consultas.py` · `tests/test_consultas.py` (+ `tests/fixtures/consultas/`) ·
E2E: `recon/consultas_e2e.py` · anonimização das fixtures: `recon/anonimizar_consultas.py`.

## Convenções que valem pra todas as telas

- Toda tela abre pelo **menu JSCook** do portal: `POST /sigaa/portais/discente/discente.jsf` com
  `menu:form_menu_discente`, `jscook_action=<item>` e o ViewState do portal (`c.menu("bean.metodo")`).
- Os formulários são JSF: o POST leva **todos** os campos do form + o **nome do botão** (`Buscar`).
  Sem o botão o SIGAA só re-renderiza o formulário, sem resultado e sem mensagem.
  ⚠ `recon/sess.py:submit(..., button=(nome, valor))` usa a tupla como CHAVE (bug); passe o botão em `extra`.
- Checkbox sem `value` vai como `on` (é o que o navegador manda).
- Os ids `j_id_jsp_*` são gerados pelo JSP; não estão fixos no código: o serviço acha o botão pelo
  texto (`_botao`) e o campo de texto pela linha do checkbox de id fixo (`_campo_na_linha`).
- Vários detalhes saem por **GET direto com id** (painéis AJAX que o próprio SIGAA usa) — mais rápido
  e sem ViewState. Eles exigem sessão logada (sem login → `/sigaa/expirada.jsp`).

## Telas

### 1. Calendário Acadêmico

| | |
|---|---|
| Menu | `calendario.iniciarBusca` (Ensino › Calendário Acadêmico) |
| Lista | `/sigaa/administracao/calendario_academico/consulta.jsf` — `table.listagem`, `tr.secao` "Calendário AAAA.P" + uma linha por tipo (`CALENDÁRIO GERAL`, `ENSINO A DISTÂNCIA`), link jsfcljs `{'form:visualizar…', 'id': '<idCalendario>'}` |
| Detalhe | clique no link → `/sigaa/administracao/calendario_academico/view.jsf` — `table.visualizacao`, pares `th`/`td`; seções em `td.subFormulario` |

Conteúdo do detalhe: unidade responsável, nível, ano/semestre, vigente, ano-período de férias vigente,
ano-período das turmas na solicitação, período letivo, período de férias e os grupos
*Datas para Turmas Regulares* (consolidação, solicitação/cadastro de turmas, trancamento de turmas e de programa),
*Turmas de Férias*, *Ensino Individualizado*, *Matrículas, Rematrícula e Processamentos* (matrícula on-line,
ingressantes, aluno especial, extraordinária, análises, processamento, ajustes, rematrícula...) e
*Docência Assistida*. Datas no formato "De dd/mm/aaaa até dd/mm/aaaa" ou "Não Definido".

Variações: 120 calendários (1969.1 → 2027.1); de 2025.1 a 2026.2 há também o EAD.
⚠ **Abrir o calendário EAD (2026.1) deu "Comportamento Inesperado"** (o SIGAA manda e-mail pra STI a cada um).
O serviço **bloqueia** calendários EAD de propósito — não reabra sem necessidade.

### 2. Consulta geral de cursos

| | |
|---|---|
| Menu | `curso.popularBuscaGeral` → `/sigaa/geral/curso/busca_geral.jsf`, form `busca` |
| Campos | `busca:niveis` (I, U, M, T, N, F, **G**, L, R, S, E, D), rádio `paramBusca` = `nome`/`todos`, `busca:param1` (nome), botão `Buscar` |
| Resultado | `table.listagem` "Lista de cursos encontrados": Curso (`NOME/UNIDADE`), Nível, Coordenador (vários separados por `<br>`) |

Não há id nem link de detalhe nessa tela. Os cursos **com id** vêm do combo `busca:curso` da tela de
Estrutura Curricular (mesmo id do filtro `form:selectCurso` da busca de turmas).

### 3. Componente curricular

| | |
|---|---|
| Menu | `componenteCurricular.popularBuscaDiscente` → `/sigaa/geral/componente_curricular/busca_geral.jsf`, form `formBusca` |
| Filtros | checkbox + campo: `checkNivel`+select, `checkCodigo`+texto, `checkNome`+texto, `checkPreRequisito`/`checkCoRequisito`/`checkEquivalencia` (autocomplete AJAX — não usados), `checkPeriodoEquivalencia` (datas), `checkUnidade`+`formBusca:unidades`, `checkTipo`+`formBusca:tipos` (1 atividade, 2 disciplina, 3 módulo, 4 bloco), `checkModalidade`+`formBusca:modalidades`, `checkRel` (formato relatório); botão `formBusca:btnBuscar` |
| Resultado | "Componentes curriculares encontrados (N)": Código, Nome, Nível, CH, Tipo + 3 links jsfcljs por linha |

Links de cada linha (form `j_id_jsp_…_1041`):
1. **Visualizar componente curricular** (`'id': N`) — ⚠ **dá "Comportamento Inesperado"** no SIGAA UFBA
   (`#{componenteCurricularGraduacao.obj.unidade.nomeMunicipioCodigo}`); **não usar**.
2. **Relatório para impressão** (`'id': N`) — tudo do componente: dados gerais, pré/co-requisitos e
   equivalências (`<ACRONYM title="COD - NOME">`), flags (Matriculável On-Line, Exige Horário, Permite Múltiplas
   Aprovações...), ementa, cargas horárias detalhadas, **outros componentes que têm este como equivalente /
   pré-requisito / co-requisito**, **histórico de equivalências** e **currículos** que o incluem (código,
   ano.período, matriz, obrigatória, período, ativo).
3. **Programa atual do componente** (`'idComponente': N`) — na UFBA quase sempre volta ao formulário com
   "O componente curricular X não possui um programa cadastrado." (testado em MATA37, MATA55, MATA62).

**Detalhe por GET direto** (usado pela tela de estrutura, `PainelComponente.show(id)` em
`/shared/javascript/paineis/turma_componentes.js`):
`GET /sigaa/graduacao/componente/view_painel.jsf?ajaxRequest=true&id=<idComponente>` — dados gerais,
requisitos, equivalências, CH, ementa e "Outras informações" num pedido só.
O serviço usa o painel e, com `completo=true`, busca por código e abre o *Relatório* pra mesclar o resto.

Variações: ementa "Não definido" (→ `null`), requisitos "-" (→ `null`), códigos de pós com barra (`PGCOMP/IC0050`).

### 4. Estrutura curricular

| | |
|---|---|
| Menu | `curriculo.popularBuscaGeral` → `/sigaa/geral/estrutura_curricular/busca_geral.jsf`, form `busca` |
| Campos | `busca:checkCurso` + `busca:curso` (o `onchange` faz `submit()` do form inteiro pra carregar `busca:matriz`), `busca:checkMatriz`+`busca:matriz`, `busca:checkCodigo`+`busca:codigo`, `busca:somenteAtivas`, botão `Buscar` |
| Passos | menu → POST com curso (sem botão) → POST com curso + `Buscar` |
| Resultado | `/sigaa/graduacao/curriculo/lista.jsf`, "Lista de Estruturas Curriculares Encontradas (N)": Cód, Ano-Período, Matriz ("(Inativa)" no fim), Situação + links do form `resultado`: `resultado:detalhar`, `resultado:relatorio`, `resultado:declaracaoPrazoMaximo` (cada um com `id`) |

- **Relatório**: cabeçalho (código, matriz, unidade de vinculação, município, período de entrada, prazos
  mín/médio/máx, CH obrigatória / optativa (+ optativa livre) / complementar / total) e os componentes por
  semestre (`tr.tituloRelatorio` "1º Semestre"... "Componentes Optativos", `tr.componentes` com código,
  "NOME - 60h", CH detalhada, tipo, natureza) + "CH Total" do bloco.
- **Detalhar**: CH extras (mínima, máxima por período, máxima de eletivos, subtotais) e abas RichFaces
  (Optativos, Complementares, 1º...10º) onde cada componente tem `PainelComponente.show(<idComponente>)`.
  O serviço mescla: Relatório (estrutura/natureza) + Detalhar (id e modalidade de cada componente).
- **Declaração de Prazo Máximo**: documento com curso, turno, modalidade, prazo máximo, identificador e
  código de verificação (validável em `/sigaa/documentos/`).

✔ O bean carrega a estrutura pelo `id` enviado, **de qualquer lista de resultados** (testado: lista de CC +
id de SI → relatório de SI). Por isso `GET /v1/consultas/estruturas/{id}` não pede o curso: o serviço faz uma
busca qualquer (1º curso do combo) e clica com o id pedido.

### 5. Turma

| | |
|---|---|
| Menu | `buscaTurmaBean.popularBuscaGeral` → `/sigaa/ensino/turma/busca_turma.jsf`, form `form` |
| Campos | `form:checkAnoPeriodo` + `form:inputAno`/`form:inputPeriodo` (pré-preenchidos com o período atual), e pares checkbox+campo: `checkNivel/selectNivelTurma` (A4J), `checkUnidade/selectUnidade`, `checkCodigo/inputCodDisciplina`, `checkCodigoTurma/inputCodTurma`, `checkLocal/inputLocal`, `checkHorario/inputHorario`, `checkDisciplina/inputNomeDisciplina`, `checkDocente/inputNomeDocente`, `checkCurso/selectCurso` (A4J), `checkSituacao/selectSituacaoTurma` (1 aberta, 2 a definir docente, 3 consolidada), `checkTipo/selectTipoTurma` (1 regular, 2 férias, 3 ensino individual), `checkModalidade/selectModalidade`, `checkConvenio`, `checkRel`/`checkRelDep` (relatório), `checkOrdenacao/selectOpcaoOrdenacao`; botão `form:buttonBuscar` |
| AJAX | `selectNivelTurma` e `selectCurso` disparam `A4J.AJAX.Submit` (só re-renderizam/marcam o checkbox) — um POST normal com os valores funciona |
| Resultado | `table#lista-turmas` "Turmas Encontradas (N)": `tr.destaque` = componente ("COD - NOME (NÍVEL)"), depois uma linha por turma: Ano.Período, "Turma 01" (`PainelTurma.show(<idTurma>)`), Docente(s) "NOME (60h), NOME (15h) e NOME (15h)", Tipo, Modalidade, Situação, Horário "35T12 (19/08/2026 - 19/12/2026)", Local ("PAF 1 - 106 - Quinta Horários 13:00 às 13:55…", "A definir", "Smart Class I"), Mat./Cap. "38/45 alunos" |

Menu de cada turma (`tr#trOpcoes<id>`, oculto):
- **Processamento da Matrícula / Rematrícula** — `GET /sigaa/relatorioProcessamento?idTurma=<id>[&rematricula=true]`:
  reserva de vagas (ingressantes/demais) e a lista de solicitações **com nome e matrícula de outros alunos**.
  🔒 A API **só devolve contagens** (por grupo e situação) — nenhum dado de colega sai.
- **Visualizar turma** (jsfcljs `form:sltbtnView`, `id`) — relatório resumido; o painel abaixo é mais rico.
- **Visualizar Turma Virtual** (`form:sltbtnTurmaVirtual`, `idTurma`) — entra na turma virtual (frente *turma_virtual*); não usado aqui.
- **Ver agenda da turma** — `GET /sigaa/ensino/turma/view_calendario.jsf?idTurma=<id>` (FullCalendar; "Não há evento
  registrado" nas turmas vistas). O único botão da tela, "Exportar Calendário para E-Mail", **envia e-mail** → fora (somente leitura).

**Painel da turma por GET**: `GET /sigaa/graduacao/turma/view_painel.jsf?ajaxRequest=true&contarMatriculados=true&id=<idTurma>`
— período letivo, componente e turma, CH, tipo, local e horário, capacidade, **solicitações na matrícula e
na rematrícula**, matriculados, professores e **vagas reservadas por curso** "(ingressantes/demais)".

Horário: código SIGAA `<dias><turno><aulas>` (2=seg … 7=sáb; M/T/N; aulas 1–6 de 55 min:
M 07:00…12:30, T 13:00…18:30, N 18:30…22:10). Vários blocos separados por espaço ("3N34 6N3").
O parser decodifica (`horarios`) e também lê as salas por dia do texto do local (`alocacoes`).
Variações vistas: docentes múltiplos, local "A definir", sala "Smart Class Ii" (caixa irregular), dois blocos de horário.

### 6. Unidades acadêmicas

| | |
|---|---|
| Menu | `unidade.popularBuscaGeral` → `/sigaa/geral/unidade/busca_geral.jsf`, form `formBuscaUnidade` |
| Campos | rádio `paramBusca` = `nome`/`tipo`, `paramNome`, `tipo` (4 Centro Acadêmico, 1 Departamento, 2 Escola, 3 Programa de Pós, 5 Unidade Especializada, 6 Coord. de Curso, 8 Coord. Lato, 10 Coord. Stricto, 7 Órgão Suplementar, 9 Programa de Residência), `checkAtivo` + rádio Sim/Não, `paramRelatorio`, botão `btnBuscar` |
| Resultado | "Lista de Unidades Acadêmicas (N)": Código, Unidade, Sigla, Tipo, Ativa (coluna some quando se filtra por ativa) + link "Detalhar" (`id`) |
| Detalhe | só repete código/nome/sigla/tipo → não exposto |

O `id` da unidade é o mesmo dos combos `formBusca:unidades` (componentes) e `form:selectUnidade` (turmas).

### Fora desta frente / não acessível

- **Gerenciamento de Salas** (Módulos): *Relatório de Salas Livres* é exposto pela frente **portal** (`/v1/salas-livres`).
  *Relatório de distribuição de salas* e *Mapa de Salas* dão **Acesso Negado** pra aluno (papéis DISTRIBUIÇÃO SALAS /
  RESPONSAVEL_RESERVA_ESPACO_FISICO).
- Os demais módulos do diálogo "Módulos" estão desabilitados pra discente (exceto Portal do Discente,
  Gerenciamento de salas e Avaliação Institucional — esta é de outra frente e altera estado).

## Nó web (o Caio vendo)

Nó `80272484` ("SIGAA · consultas"): logado com `recon/web_login.sh`, `gravar ligar`, navegados o Calendário
2026.2, a Consulta de Cursos (busca "SISTEMAS") e a Consulta de Turmas (MATA37 + painel da turma).
`mapa resumo` registrou `POST /sigaa/geral/curso/busca_geral.jsf` (corpo `busca, busca:niveis, paramBusca,
busca:param1, busca:j_id_jsp_747103860_835=Buscar, ViewState` — foi o que revelou o botão faltando),
`POST .../calendario_academico/consulta.jsf` (`form:visualizarj_id_1`, `id`), `POST .../busca_turma.jsf` e
`GET /sigaa/graduacao/turma/view_painel.jsf`, além do `A4J` de `formRelatSalaLivre.jsf` (`AJAXREQUEST=…`,
ao trocar o prédio).

## Endpoints (logados — `Authorization: Bearer`)

| método | rota | devolve |
|---|---|---|
| GET | `/v1/calendario?ano=&periodo=&id=` | `Calendario` — todos os prazos do período (padrão: semestre atual) |
| GET | `/v1/calendario/lista?ano=` | `CalendarioResumo[]` — todos os calendários com id |
| GET | `/v1/consultas/cursos?nivel=G&nome=&pagina=&por_pagina=` | `Pagina[CursoConsulta]` — cursos + coordenadores |
| GET | `/v1/consultas/cursos/ids?nome=` | `CursoOpcao[]` — cursos de graduação com id |
| GET | `/v1/consultas/componentes?codigo=&nome=&nivel=&unidade=&tipo=&modalidade=` | `Pagina[ComponenteResumo]` |
| GET | `/v1/consultas/componentes/filtros` | níveis, unidades, tipos, modalidades |
| GET | `/v1/consultas/componentes/{id}?completo=` | `ComponenteDetalhe` |
| GET | `/v1/consultas/estruturas?curso=&codigo=&somente_ativas=` | `EstruturaResumo[]` |
| GET | `/v1/consultas/estruturas/{id}` | `EstruturaDetalhe` — componentes por semestre com id |
| GET | `/v1/consultas/estruturas/{id}/declaracao-prazo-maximo` | `DeclaracaoPrazoMaximo` |
| GET | `/v1/consultas/turmas?ano=&periodo=&componente=&nome=&unidade=&docente=&curso=&turma=&local=&horario=&nivel=&situacao=&tipo=&modalidade=` | `Pagina[TurmaOferta]` |
| GET | `/v1/consultas/turmas/filtros` | níveis, unidades, cursos, situações, tipos, modalidades, ordenações |
| GET | `/v1/consultas/turmas/{id}` | `TurmaDetalhe` — vagas, solicitações, matriculados, reservas |
| GET | `/v1/consultas/turmas/{id}/processamento?rematricula=` | `ProcessamentoTurma` — só agregados |
| GET | `/v1/consultas/unidades?nome=&tipo=&ativa=` | `UnidadeConsulta[]` |
| GET | `/v1/consultas/unidades/tipos` | tipos de unidade |

## Endpoints públicos (`/v1/publico/...` — sem token)

Cada requisição abre um `SigaaClient` **anônimo** novo (`sigaa.services.consultas.cliente_anonimo`):
0,35 s entre pedidos e no máximo 4 sessões anônimas simultâneas (as demais esperam), pra uma rota
sem autenticação não virar um martelo no SIGAA. Filtro faltando/inválido → **422**; id inexistente → **404**.
Listas grandes vêm em `Pagina` (`?pagina=&por_pagina=`). Telas e navegação: [`consultas_publico.md`](consultas_publico.md).

| método | rota | o que devolve |
|---|---|---|
| GET | `/v1/publico/cursos`?nivel=&nome=&modalidade=&unidade= | Cursos (público) (paginado) |
| GET | `/v1/publico/cursos/{curso_id}`?nivel= | Página pública do curso |
| GET | `/v1/publico/cursos/{curso_id}/estruturas`?nivel= | Estruturas curriculares do curso (público) |
| GET | `/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id}`?nivel=&relatorio= | Estrutura curricular completa (público) |
| GET | `/v1/publico/estruturas/{estrutura_id}`?curso=&nivel=&relatorio= | Estrutura curricular (atalho, exige ?curso=) |
| GET | `/v1/publico/cursos/{curso_id}/calendario` | Calendário do curso (público) |
| GET | `/v1/publico/cursos/{curso_id}/projeto-pedagogico` | Projeto pedagógico do curso |
| GET | `/v1/publico/cursos/{curso_id}/noticias` | Notícias do curso |
| GET | `/v1/publico/cursos/{curso_id}/turmas`?ano=&periodo=&codigo= | Turmas com vagas reservadas ao curso |
| GET | `/v1/publico/componentes`?nivel=&codigo=&nome=&unidade=&tipo= | Buscar componentes curriculares (público) (paginado) |
| GET | `/v1/publico/componentes/codigo/{codigo}`?nivel= | Componente pelo código (formato completo) |
| GET | `/v1/publico/componentes/codigo/{codigo}/programa`?nivel= | Programa do componente |
| GET | `/v1/publico/componentes/{componente_id}` | Componente pelo id (GET direto) |
| GET | `/v1/publico/turmas`?ano=&periodo=&unidade=&nivel=&componente= | Turmas ofertadas por unidade (público) (paginado) |
| GET | `/v1/publico/unidades` | Unidades que ofertam turmas |
| GET | `/v1/publico/docentes`?nome=&departamento= | Buscar docentes (paginado) |
| GET | `/v1/publico/docentes/{siape}` | Perfil público do docente |
| GET | `/v1/publico/docentes/{siape}/producao` | Produção intelectual do docente |
| GET | `/v1/publico/docentes/{siape}/disciplinas` | Disciplinas ministradas pelo docente |
| GET | `/v1/publico/centros` | Centros / unidades acadêmicas |
| GET | `/v1/publico/centros/{centro_id}` | Portal do centro |
| GET | `/v1/publico/departamentos`?centro= | Departamentos |
| GET | `/v1/publico/departamentos/{departamento_id}` | Portal do departamento |
| GET | `/v1/publico/departamentos/{departamento_id}/docentes` | Corpo docente do departamento |
| GET | `/v1/publico/departamentos/{departamento_id}/componentes` | Componentes do departamento |
| GET | `/v1/publico/responsaveis`?tipo= | Chefes, coordenadores e diretores |
| GET | `/v1/publico/biblioteca/acervo`?titulo=&autor=&assunto=&editora=&local_publicacao=&ano_inicio=&ano_fim=&tipo_material=&colecao=&ordenacao=&max_paginas= | Buscar no acervo das bibliotecas (paginado) |
| GET | `/v1/publico/biblioteca/acervo/{titulo_id}`?titulo=&autor=&assunto=&editora=&ano_inicio=&ano_fim= | Exemplares de um título |
| GET | `/v1/publico/biblioteca/artigos`?titulo=&autor=&palavras_chave=&ordenacao= | Buscar artigos de periódicos (paginado) |
| GET | `/v1/publico/biblioteca/aquisicoes`?titulo=&autor=&ano= | Aquisições das bibliotecas |
| GET | `/v1/publico/biblioteca/novas-aquisicoes`?desde=&area_cnpq= | Informativo de novas aquisições |
| GET | `/v1/publico/processos-seletivos`?nivel= | Processos seletivos |
| GET | `/v1/publico/processos-seletivos/{processo_id}`?nivel=&programa= | Processo seletivo |
| GET | `/v1/publico/programas-pos`?nome=&centro= | Programas de pós-graduação |
| GET | `/v1/publico/programas-pos/{programa_id}` | Programa de pós |
| GET | `/v1/publico/programas-pos/{programa_id}/areas` | Áreas de concentração e linhas de pesquisa |
| GET | `/v1/publico/programas-pos/{programa_id}/cursos` | Cursos do programa |
| GET | `/v1/publico/programas-pos/{programa_id}/docentes` | Corpo docente do programa |
| GET | `/v1/publico/programas-pos/{programa_id}/processos-seletivos` | Processos seletivos do programa |
| GET | `/v1/publico/programas-pos/{programa_id}/noticias` | Notícias do programa |
| GET | `/v1/publico/programas-pos/{programa_id}/noticias/{noticia_id}` | Notícia do programa |
| GET | `/v1/publico/acordos-mobilidade`?pais=&instituicao=&sigla=&ano_assinatura=&status= | Acordos de cooperação/mobilidade internacional |
| GET | `/v1/publico/pesquisa/projetos`?titulo=&objetivos=&pesquisador=&ano=&centro=&departamento=&area=&agencia= | Projetos de pesquisa ('quem pesquisa o quê') (paginado) |
| GET | `/v1/publico/pesquisa/projetos/{projeto_id}`?titulo=&pesquisador=&ano=&centro= | Projeto de pesquisa |
| GET | `/v1/publico/pesquisa/bases`?nome=&coordenador= | Bases/grupos de pesquisa |
| GET | `/v1/publico/pesquisa/bolsistas`?discente=&orientador=&modalidade=&centro=&curso= | Bolsistas de iniciação científica |
| GET | `/v1/publico/pesquisa/laboratorios`?nome=&ano=&tipo=&servidor=&em_atividade=&presta_servicos=&servico= | Laboratórios de pesquisa |
| GET | `/v1/publico/pesquisa/laboratorios/{laboratorio_id}`?nome=&ano=&tipo= | Laboratório de pesquisa |
| GET | `/v1/publico/extensao/acoes`?tipo=&titulo=&unidade=&ano= | Ações de extensão (paginado) |
| GET | `/v1/publico/extensao/inscricoes-abertas`?titulo=&tipo= | Cursos/eventos de extensão com inscrição aberta |
| GET | `/v1/publico/extensao/acoes/{acao_id}`?tipo=&titulo=&ano= | Ação de extensão |
| GET | `/v1/publico/cursos-abertos`?palavra_chave=&centro=&departamento= | Cursos abertos (turmas com conteúdo público) (paginado) |
| GET | `/v1/publico/cursos-abertos/centros` | Centros com cursos abertos |
| GET | `/v1/publico/cursos-abertos/centros/{centro_id}/departamentos` | Departamentos de um centro (cursos abertos) |
| GET | `/v1/publico/cursos-abertos/{turma_id}`?palavra_chave= | Curso aberto |

### Público × logado — qual usar

| informação | prefira | por quê |
|---|---|---|
| lista de cursos, coordenador, página do curso | **público** `/publico/cursos` | traz id, sede, modalidade; o logado não tem id |
| componente (ementa, requisitos, currículos) | **público** `/publico/componentes/codigo/{codigo}` | mesmo conteúdo do relatório logado, sem login |
| estrutura curricular | **público** `/publico/cursos/{id}/estruturas/{id}` | igual; o logado (`/consultas/estruturas/{id}`) dispensa o curso |
| turmas ofertadas | **logado** `/consultas/turmas` quando precisar de **vagas, idTurma, código de horário e filtros** (docente, horário, local); público `/publico/turmas` exige unidade e não mostra vagas |
| vagas/solicitações de uma turma | **logado** `/consultas/turmas/{id}` | só existe logado |
| calendário acadêmico geral | **logado** `/calendario` | o público só tem o calendário de cada curso (`/publico/cursos/{id}/calendario`) e um link externo da SUPAC |
| unidades | público `/publico/unidades`, `/publico/departamentos`, `/publico/centros` | mais ricos; o logado `/consultas/unidades` traz código hierárquico, sigla, tipo e ativa |

