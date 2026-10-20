# Mapeamento — SIGAA PÚBLICO (sem login)

Tudo o que se consulta em `https://sigaa.ufba.br/sigaa/public/` **sem credencial**. Código em
`sigaa/{models,parsers,services}/consultas_publico.py`, testes em `tests/test_consultas_publico.py`
(fixtures anonimizadas em `tests/fixtures/consultas/publico/`), e2e em `recon/consultas_publico_e2e.py`.

O documento tem três partes:
1. **Núcleo acadêmico**: cursos, estruturas curriculares, componentes, turmas, docentes, centros/departamentos, responsáveis.
2. **Frente extras1**: biblioteca, processos seletivos, diplomas, acordos de mobilidade, programas de pós.
3. **Frente extras2**: pesquisa, extensão, cursos abertos.

No fim está a seção **CONTRATO DOS SERVIÇOS**, com a assinatura de cada serviço e a rota sugerida.

## Avisos gerais

- **Cliente anônimo.** Os serviços recebem um `SigaaClient()` **sem** `login()` e usam só `c.get` / `c.post` / `c.clicar`. A rota deve criar um cliente por requisição (ou um pool anônimo) com `SigaaClient(min_interval=0.35)`. O padrão de 0,25 s está abaixo da regra de ≥0,3 s.
- **Encoding dos POSTs** (problema real, afeta o projeto inteiro).
  - O SIGAA decodifica o corpo do POST como **ISO-8859-1**, mas o `SigaaClient` (httpx, `data=`) manda **UTF-8**. Qualquer filtro com acento chega corrompido e a busca volta vazia. Medido nas duas frentes extras: com "educação" deu 131 resultados em latin-1 e 0 em UTF-8.
  - Contorno aqui: os serviços do núcleo usam `_submit()`, que monta o corpo com `urlencode(..., encoding="iso-8859-1")` e posta com `c.post(url, {}, content=corpo, headers=...)`. extras2 usa `_ex2_enviar` (o mesmo). extras1 manda os textos livres sem acento.
  - **Correção sugerida no `sigaa/client.py`** (fora do meu escopo): em `post()`, trocar `data=` por `content=urlencode(data, encoding="iso-8859-1", errors="xmlcharrefreplace")` com `Content-Type: application/x-www-form-urlencoded`.
- **Charset das respostas.** Os portais de centro/departamento vêm em **UTF-8**; o resto vem em **ISO-8859-1**. O `Page.html` já decodifica pelo header. Os parsers aceitam `str` ou `bytes`: em bytes tentam UTF-8 estrito e caem pra latin-1.
- **Id inexistente não dá 404.**
  - `centro/portal.jsf?id=1` devolve o template vazio (h1 `()`).
  - `curso/portal.jsf?id=1` devolve o template com nome ` / `.
  - `docente/portal.jsf?siape=1` vem sem `#perfil-docente`.
  - `visualizarComponente/1` vem sem a tabela "Dados Gerais".
  - Os serviços detectam esses casos e levantam `NaoEncontrado`. Testei **1 requisição** por caso, sem varrer ids.
- **Load balancer.** O `jsessionid` muda de nó (`sigaapl03/04/07/08`, `saomiguel`). Isso é transparente: o cookie segue a sessão.
- **Comportamento Inesperado / endereço inválido:** nenhum ocorreu em toda a exploração.

### GET direto (bookmarkable) × POST com ViewState (núcleo)

| tela | acesso |
|---|---|
| lista de cursos `curso/lista.jsf?nivel=G\|S\|L\|T\|N` | **GET** |
| portal do curso de graduação `curso/portal.jsf?id=N` + abas `curriculo`, `calendario`, `ppp`, `noticias`, `turmas`, `monografias`, `artigos`, `memoriais`, `outros` (`.jsf?lc=pt_BR&id=N`) | **GET** |
| detalhe de curso de **pós** | **POST**: clique `jsfcljs` em `formListagemCursos` com `id` |
| estrutura curricular (detalhes / relatório) | **POST**: clique em `formCurriculosCurso` (grad.) ou `form` (pós) com `id` da estrutura |
| componente por id `/sigaa/link/public/ensino/visualizarComponente/{id}` | **GET** (redireciona p/ `componentes/resumo.jsf`) |
| busca de componentes, detalhe e programa a partir da busca | **POST** |
| consulta de turmas `turmas/listar.jsf` | GET do form + **POST** |
| busca de docentes | GET do form + **POST** |
| perfil do docente `docente/portal.jsf?siape=N` + `producao.jsf`, `disciplinas.jsf` | **GET** |
| centros `centro/lista.jsf`, `centro/portal.jsf?id=N` + `lista_departamentos`, `lista_cursos`, `lista_programas`, `bases_pesquisa`, `documentos` | **GET** |
| departamentos `departamento/lista.jsf` | GET do form + **POST** |
| portal do departamento `departamento/portal.jsf?id=N` + `administrativo`, `professores`, `componentes`, `extensao`, `pesquisa`, `monitoria`, `documentos` | **GET** |
| responsáveis `academico/busca_responsavel.jsf` | GET do form + **POST** |

---

# Parte 1 — Núcleo acadêmico

## 1. Home pública — `GET /sigaa/public/home.jsf`
É o menu em abas: Acadêmico, Biblioteca, Ensino, Extensão, Graduação, Pesquisa, Stricto, Lato, Processos Seletivos, Técnico, Ouvidoria e Relações Internacionais. Quase todos os links são GET.

As exceções são as entradas de processos seletivos stricto/lato (`jsfcljs` em `j_id_jsp_1235242682_3/_13/_16`). Elas só redirecionam pra `processo_seletivo/lista.jsf?nivel=S|L` (ver extras1).

Links **externos** (não implementados):
- calendário acadêmico (`supac.ufba.br/calendario-academico`);
- regulamento da graduação (PDF);
- SISU / outros processos (`prograd.ufba.br`).

Links que **exigem login**: empréstimos e renovação da biblioteca.

A ouvidoria cria manifestação: **proibido** (só leitura).

## 2. Cursos

### 2.1 Lista — `GET /sigaa/public/curso/lista.jsf?nivel=<N>&aba=p-ensino`
- **Níveis:**
  - G: 116 cursos.
  - S: 169 cursos.
  - L, T e N: vazios hoje (a página vem só com o formulário).
- **Formulário de filtro** (`form`):
  - campos `form:checkNome` + `form:nomeDoCurso`, `form:checkModalidade` + `form:modalidadeDeEnsino`;
  - modalidades: 0 = todas, 1 = Presencial, 2 = A Distância, 3 = Semi-Presencial, 4 = Remoto;
  - botão `form:consultarCursos`.
  - **Não é preciso usar:** a página já traz todos os cursos, e o serviço filtra localmente por nome, modalidade ou unidade.
- **Tabela** `formListagemCursos` > `table.listagem`, com caption `Cursos (N)`:
  - Linhas `td.subFormulario` agrupam por unidade. Na pós, essa célula traz um link `programa/portal.jsf?id=` (o id do programa).
  - Colunas na graduação: Nome, Sede, Modalidade, Coordenador, ícone. Na pós: Nome, Nível, Sede, ícone.
  - Ícone na graduação: `<a href="portal.jsf?id=N&lc=pt_BR&nivel=G">` → **id do curso por GET**.
  - Ícone na pós: `jsfcljs(formListagemCursos, {'formListagemCursos:j_id_jsp_1302309529_17…': …, 'id': '<curso>'})` → **só POST**.

### 2.2 Portal do curso de graduação — `GET /sigaa/public/curso/portal.jsf?id=N&lc=pt_BR&nivel=G`
- **Cabeçalho** `#nomes`: `.nome_curso` ("CURSO DE SISTEMAS DE INFORMAÇÃO / IC/UFBA") e `.nome_centro`.
  - O link do centro aponta `centro/portal.jsf?id=78`. O id 78 é a **universidade** e não abre portal de centro, por isso não exponho esse id.
- **`#esquerda`**: `span.topico` com o par rótulo + `<strong>valor</strong>`:
  - Coordenação do Programa
  - Título do Profissional
  - Área de Conhecimento CNPQ
  - Convênio Acadêmico
  - Modalidade de Curso
  - Endereço Alternativo
- **`div.informacoes`**: Telefone/Ramal e E-mail, em `span.cor`.
- **Calendário resumido**: `#listagem3 li` (datas + `span.evento`).
- **Notícias**: `formNoticias ul`, vazia no curso de SI.
- **Menu do portal** (todos GET, `?lc=pt_BR&id=N`):
  - `curriculo.jsf`: estruturas curriculares (2.3).
  - `calendario.jsf`: blocos `div#listagem_tabela` > `#group_lt` (o ano.período) + `<td><b>dd/mm/aaaa à dd/mm/aaaa</b> → evento</td>`.
  - `ppp.jsf`: `span.topico2 > label` com Perfil Profissional, Competências e Habilidades, Metodologia, Avaliação do Curso e Projeto Pedagógico (anexo). No SI está tudo "Nenhum conteúdo disponível".
  - `noticias.jsf`: `#table_lt` com DATA e TÍTULO, vazia no SI.
  - `turmas.jsf`: turmas com vagas reservadas ao curso (2.5).
  - `monografias.jsf`, `artigos.jsf`, `memoriais.jsf`, `outros.jsf`: busca por Aluno/Título/Ano dos trabalhos anexados. **Não implementado**: lista pessoas (alunos) e não vi nenhum resultado.
- **Variação:** no template de id inexistente aparece também o item "· Alunos Ativos". **Não aberto**, porque é uma lista de pessoas.

### 2.3 Estruturas do curso — `GET /sigaa/public/curso/curriculo.jsf?lc=pt_BR&id=N`
- **Formulário** `formCurriculosCurso`, com `<tr class="campos">` agrupando por turno (ex.: "Noturno").
- **Cada linha:**
  - texto "Detalhes da Estrutura Curricular <CÓDIGO>, Criado em <ANO>";
  - status Ativa ou Inativa;
  - dois links `jsfcljs`: **Visualizar** (`formCurriculosCurso:j_id_jsp_1561883746_32[j_id_k]`) e **Relatório** (`…_35[j_id_k]`), os dois com `'id': '<id da estrutura>'`.
- **Estruturas na pós:** ficam no próprio "Detalhes do Curso" (2.4), form `form` (`form:j_id_jsp_335299133_33/_36…`).

### 2.4 Detalhe de curso de pós
Navegação: `GET curso/lista.jsf?nivel=S`, depois clique `jsfcljs` com `id`. O POST volta pra `lista.jsf`.

O conteúdo é a `table` com caption "Detalhes do Curso", em pares `th`/`td`:
- Nível
- "Candidato ao curso de:" (o nome)
- Unidade
- Município
- Modalidade de Ensino
- Coordenação do Curso: uma pessoa por `<br>`, com "(Coordenação)" / "(Vice-Coordenação)"
- Telefone/Ramal(s)
- E-mail (um por `<br>`)
- Página Oficial (`<a>`)
- Conceito
- Portaria
- Projeto Pedagógico
- tabela "Estrutura Curricular" (`tr.curriculo`: "Estrutura Curricular D120271, Criado em 2027.1")

### 2.5 Estrutura curricular: Detalhes e Relatório
Navegação: POST a partir de 2.3 (ou 2.4). O `action` é `curso/resumo_curriculo.jsf` e o form da página é `formulario`.

- **Cabeçalho**: tabela `formulario`, pares `th`/`td`:
  - Código
  - Matriz Curricular
  - Período Letivo de Entrada em Vigor
  - Total Mínima
  - Subtotal de CH de Aula
  - Subtotal de CH de Orientação Acadêmica/Profissional
  - Total
  - Carga Horária Optativa Mínima
  - Carga Horária Complementar Mínima
  - CH Obrigatória Atividade Acadêmica Específica
  - CH Máxima de Componentes Eletivos
  - CH Máxima por Período Letivo
  - Prazo (uma linha aninhada com Mínimo/Médio/Máximo, vários `th`/`td` na mesma `tr`)
- **Detalhes**: `div#tabs-semestres`, com abas `#optativas`, `#complementares` e `#semestre1..N`.
  - Cada aba tem um `table.subFormulario` com caption, linhas `td` "CÓDIGO - NOME - 60h", a natureza (Obrigatória/Optativa) e os links Detalhes (`'id': '<componente>', 'publico': 'public'`) e Programa (`'idComponente': …`).
  - O rodapé de cada aba é "Carga Horária Total: 300h".
- **Relatório**: mesma informação em sequência: `tr.tituloRelatorio` (rótulo do bloco), `tr.componentes` e "CH Total: 7215h".
  - **Pegadinha:** as `<table>` vêm mal fechadas e o lxml aninha uma dentro da outra. O parser percorre as linhas **em ordem** e não por tabela.
- **Links de dentro da estrutura:** "Visualizar Detalhes do Componente" abre o mesmo resumo do componente (3.3). "Visualizar Programa" leva ao programa ou à mensagem "não possui um programa cadastrado".
- **Exemplo validado**, estrutura G20251X do SI: 3101h mínima, 2206h obrigatória, 480h optativa, 415h complementar, prazos 10/10/15, 10 níveis, 116 optativas, 0 complementares.

### 2.6 Turmas do curso — `GET curso/turmas.jsf?lc=pt_BR&id=N` + POST `form`
- **Campos:**
  - `form:inputAno`
  - `form:inputPeriodo` (1 a 4)
  - código do componente (`form:j_id_jsp_159980968_32`, nome gerado: o serviço acha pelo rótulo "Código")
  - hidden `form:id` e `form:lc`
  - botão `form:buscar=Buscar`
- **Resultado:** um `div#listagem_tabela` por componente.
  - `#group_lt` traz um `jsfcljs` com o `id` do componente e o texto "CÓDIGO - NOME".
  - Tabela com Período/Ano, Turma, Docente (um `<a href=docente/portal.jsf?siape=…>` por docente), **Vgs Reservadas** e Horários ("24N34 (19/08/2026 - 19/12/2026)", decodificado por `sigaa.util.horario`).
- **Validado:** SI 2026.2 → 61 turmas.

## 3. Componentes curriculares

### 3.1 Busca — `GET componentes/busca_componentes.jsf?nivel=G&aba=p-ensino` + POST `form`
- **Campos:**
  - `form:nivel`, valores I U M T N F G L R S (FORMAÇÃO COMPLEMENTAR = F, LATO RESIDÊNCIA = R).
  - `form:checkTipo` + `form:tipo`: 2 DISCIPLINA, 1 ATIVIDADE, 4 BLOCO, 3 MÓDULO.
  - `form:checkCodigo` + código (`form:j_id_jsp_1092268766_11`, nome gerado: o serviço acha pelo rótulo).
  - `form:checkNome` + nome (`…_13`).
  - `form:checkUnidade` + `form:unidades` (295 unidades, ids iguais aos de departamento/programa: DCC = 1114).
  - Botão `form:btnBuscarComponentes=Buscar Componentes`.
  - Cada checkbox precisa ir com o valor `on`.
- **Resultado** `formListagemComponentes`: Código, Nome, Tipo, CH Total, e os links:
  - **Detalhes**: `formListagemComponentes:j_id_jsp_1092268766_23[j_id_k]`, com `id` e `publico=public`.
  - **Programa Atual**: `…_27[j_id_k]`, com `idComponente`.
- **Variação:** na pós (S) o link de Programa **só aparece quando há programa**. Na graduação aparece sempre, mesmo sem programa.

### 3.2 Detalhe por id (GET) — `GET /sigaa/link/public/ensino/visualizarComponente/{id}` → `componentes/resumo.jsf`
- Achado nas Disciplinas Ministradas do docente. É a forma **bookmarkable** de abrir um componente.
- Comparado ao 3.3, este formato:
  - traz CH em linhas simples ("Carga Horária Teórica: 30 h.", "Prática", "de Ead", "Total");
  - traz "Módulo: 45";
  - **não** traz Modalidade nem a tabela de cargas horárias;
  - deixa pré/co-requisito vazio em vez de "-".

### 3.3 Detalhe a partir da busca/estrutura/turmas/departamento ("Resumo do Componente Curricular")
- **Tabela "Dados Gerais do Componente Curricular"**, pares `th`/`td`:
  - Tipo
  - Modalidade de Educação
  - Unidade Responsável
  - Código
  - Nome
  - Pré-Requisitos, Co-Requisitos, Equivalências (expressões com `<ACRONYM title="COD - NOME">` e E/OU)
  - flags Sim/Não: Matriculável On-Line, Horário Flexível, Necessita de Orientador, Possui Subturmas, Exige Horário, Permite Múltiplas Aprovações…
  - Quantidade de Avaliações
  - Ementa/Descrição
- **Tabela "Cargas Horárias"**:
  - grupo "Aula";
  - Teórica, Prática e Extensionista × Presencial e a Distância;
  - subtotais e totais (cada rótulo tem um `div.popUp` de ajuda, que o parser descarta).
- **Outras tabelas:**
  - "Outros componentes que têm esse componente como equivalente"
  - "… como pré-requisito"
  - "Histórico de Equivalências" (expressão, Ativa, início e fim de vigência)
  - `#listaCurriculosComponente` "Currículos": Código, Ano.Período, Matriz, Obrigatória, Período, Ativo.

### 3.4 Programa
Navegação: POST pelo link "Programa Atual do Componente".

- **Na UFBA hoje:** todos os componentes de graduação testados (MATA37 + 11 do DCC) respondem com a mensagem "O componente curricular XXX não possui um programa cadastrado." e a tela de busca de novo. Na pós, os do PGCOMP não têm nem o link.
- **Parser** (`parse_programa_componente`): genérico. Lê pares th/td, dt/dd e captions, e mapeia Objetivos, Conteúdo, Metodologia, Avaliação, Competências e Referências/Bibliografia. Testado só com HTML sintético; **nenhum programa real foi visto**.

## 4. Turmas — `GET turmas/listar.jsf?aba=p-ensino` + POST `formTurma`
- **Campos:**
  - `formTurma:inputNivel`: I U M T N F G L R S E(MESTRADO) D(DOUTORADO).
  - `formTurma:inputDepto`: **obrigatório**, 205 unidades.
  - `formTurma:inputAno` + `formTurma:inputPeriodo` (1 a 4): **obrigatórios**.
  - Botão: `formTurma:j_id_jsp_1788397273_11=Buscar`, nome gerado (o serviço acha pelo valor "Buscar").
  - Não há filtro de componente: `componente=` filtra no serviço.
- **Resultado** `#turmasAbertas table.listagem`:
  - `tr.agrupador` = componente, com `jsfcljs` `'id'` e `span.tituloDisciplina`;
  - linhas com `td.turma`, `td.anoPeriodo`, `td.nome` ("NOME (60h)") e Local.
  - Local vem como "PAF 1 - 006 - Quinta Horários 10:40 às 11:35PAF 1 - 006 - …" (vários slots concatenados), "A definir" ou "Smart Class I".
- **Variação:** turma com vários docentes vem em **várias linhas iguais**, uma por docente. O parser **funde** essas linhas.
- **O público não mostra:** vagas, código de horário, idTurma. Pra vagas reservadas ao curso, use 2.6.
- **Validado:** DCC 2026.2 → 57 turmas.

## 5. Docentes

### 5.1 Busca — `GET docente/busca_docentes.jsf` + POST `form`
- **Campos:** `form:nome`, `form:departamento` (0 = todos), botão `form:buscar=Buscar`.
- **Resultado:** caption "Docentes encontrados (N)", com `span.nome`, `span.departamento` e o link `portal.jsf?siape=N`. O mesmo docente aparece uma vez por unidade (centro e departamento).
- "SANTOS" → 642 resultados; DCC → 32.

### 5.2 Perfil — `GET docente/portal.jsf?siape=N`
- **Barra `#left`:** foto, nome (`h3`), unidade (`h3.departamento`) e o menu Perfil / Produção / Disciplinas.
- **`#perfil-docente`** (`dt`/`dd`): Descrição pessoal, Formação acadêmica/profissional, Áreas de Interesse (um item por `<br>`), Currículo Lattes.
- **`#formacao-academica`:** "Formação acadêmica não cadastrada" no exemplo. O parser lê tabela, `li` ou `dl`.
- **`#contato`:** Endereço profissional, Sala, Telefone/Ramal, Endereço eletrônico.

### 5.3 Produção — `GET docente/producao.jsf?siape=N`
- `#producao-docente`: `<h2>Categoria (n)</h2><ul><li>…</li></ul>`.
- Categorias vistas: Trabalho de Fim de Curso; Orientações de Pós-Graduação (nível, aluno, início-fim, situação).

### 5.4 Disciplinas ministradas — `GET docente/disciplinas.jsf?siape=N`
- `#abas-turmas` com abas `turmas-graduacao`, `-pos`, `-tecnico`, `-medio`, `-integrado`, `-infantil`, `-fundamental`.
- Cada aba tem `tr > td.anoPeriodo` (o período) e linhas `td.codigo`, link `visualizarComponente/{id}`, `td.ch` e `td.horario` ("2T34 4T34 (24/03/2025 - 26/07/2025)").
- Exemplo: 129 turmas desde 2021.

## 6. Centros e departamentos

### 6.1 Centros — `GET centro/lista.jsf`
- Uma `table.listagem` por centro.
- **Caption:** `a.nomeCentro` ("NOME - SIGLA") e `a.iconeCentro href=portal.jsf?id=N`.
- **`td.subListagem`:** "LOCALIZADO NO MUNICÍPIO DE X".
- **Linhas:** `a.nomeDepartamento href=departamento/portal.jsf?id=N`.
- 34 centros.

### 6.2 Portal do centro — `GET centro/portal.jsf?lc=pt_BR&id=N` (página em UTF-8)
- **`#colDirTop`:** h1 (sigla e município) e h2 (nome).
- **`#colDirCorpo`:** apresentação ou `p.vazio`, e `dl` com Diretoria do Centro (link siape), Telefone(s) e Endereço Alternativo.
- **Abas por GET:**
  - `lista_departamentos.jsf`
  - `lista_cursos.jsf`: Nome, Município, Modalidade, Coordenador (com siape) e link do curso.
  - `lista_programas.jsf`: links `programa/portal.jsf?id=`.
  - `bases_pesquisa.jsf`: vazia no IC.
  - `documentos.jsf`: vazia.
- O serviço `centro()` junta portal, departamentos, cursos e programas (4 GETs).

### 6.3 Departamentos — `GET departamento/lista.jsf` + POST `form`
- **Campos:** `form:programas`, que **é o id do centro** (0 = todos), e o botão `form:buscar`.
- **Resultado:** caption "DEPARTAMENTOS ENCONTRADOS", com `td.subListagem` = centro e links `portal.jsf?lc=pt_BR&id=N`.
- Todos → 83 departamentos; IC → 2.

### 6.4 Portal do departamento — `GET departamento/portal.jsf?id=N` (UTF-8)
- **Conteúdo:**
  - `#colDirTop`: sigla (h1) e nome (h2);
  - `#noticiasDestaque`: as notícias;
  - `dl`: Chefia do Departamento (um `dd` por chefe, com siape), Telefone(s), Endereço Alternativo.
- **Abas por GET:**
  - `professores.jsf`: `h2` = categoria ("Ativo Permanente"…); cada docente numa tabela com `span.nome` "NOME (DOUTOR)", `span.departamento` (resumo da formação), Lattes e siape.
  - `componentes.jsf`: `h2` = tipo; `td.cod`, `td.nome`, `td.ch` e `jsfcljs` com `id`.
  - `administrativo.jsf`, `extensao.jsf`, `pesquisa.jsf`, `monitoria.jsf`, `documentos.jsf`: todas vazias no DCC ("Nenhum… cadastrado"). **Não implementadas**, por falta de exemplo com dados.

## 7. Chefes, coordenações e diretores — `GET academico/busca_responsavel.jsf` + POST `form`
- **Campos:** `form:tipoConsulta`, com 1 = chefes de departamento, 2 = coordenadores/vice da graduação, 3 = da pós, 4 = diretores de centro. Botão `form:btnBuscar`.
- **Resultado:** caption "Resultados Encontrados (N)" e `td.subListagem` = centro (nos tipos 1 a 3).
  - Colunas: Departamento/Curso/Unidade, Nome, [Cargo], Telefone, E-mail.
  - Telefone pode vir "NAO INFORMADO", que o parser trata como `None`.
- Resultados: 77 / 192 / 162 / 34.

## 8. Cobertura e o que ficou de fora (núcleo)

- **Implementado e validado no e2e (0 falhas):** tudo o que está nas seções 2 a 7. O e2e também confirmou `NaoEncontrado` pra centro, curso, docente e componente inexistentes.
- **Fora do escopo:**
  - Programas de componentes: não existem na UFBA hoje (só o parser genérico).
  - Monografias, artigos, memoriais e outros do curso, e "Alunos Ativos": listam alunos. Não implementado.
  - Abas do departamento sem dados: administrativo, extensão, pesquisa, monitoria, documentos.
  - Calendário acadêmico geral: link externo pra SUPAC. O calendário do curso **está** implementado.
  - Idiomas `lc=en_US|es_ES|fr_FR` do portal do curso: só trocam os rótulos, e o parser usa os rótulos em PT.

## 9. Fixtures e anonimização (núcleo)
- `recon/anon_publico.py` gera as 37 fixtures a partir das páginas cruas (`recon/pages/consultas/publico/core/`, gitignored). O processo:
  - coleta os nomes de pessoas com os próprios parsers (496 nomes) e troca cada um por "FULANO DA SILVA 010" etc. em **todas** as páginas;
  - troca SIAPE (`siape=9000001…`), e-mail (`fulano@exemplo.br`), Lattes (`0000000000000000`), foto (`idFoto=1&key=0`) e telefones de pessoas;
  - confere no fim que nenhum nome real sobrou.
- O que fica real: nomes de cursos, componentes e unidades (institucionais), e títulos de TCC na produção do docente (os alunos citados foram trocados).
- As fixtures das frentes estão em `tests/fixtures/consultas/publico/extras1/` e `/extras2/` (anonimizadas pelos filhos).

---

# Parte 2 — Frente extras1: biblioteca, processos seletivos, diplomas, mobilidade, programas de pós

> Código fundido em `sigaa/*/consultas_publico.py` (seção "extras1"); fixtures em `tests/fixtures/consultas/publico/extras1/`.

Biblioteca · processos seletivos · diplomas · acordos de mobilidade · programas de pós.
Recon em 19/10/2026, SIGAA UFBA v4.13.8_41_hotfix. Páginas cruas em `recon/pages/consultas/publico/extras1/`.

### Avisos gerais (valem pra todas as telas)

- **Encoding do POST (bug do `SigaaClient`, afeta todas as áreas):** o SIGAA lê o corpo `application/x-www-form-urlencoded`
  como **ISO-8859-1**; o httpx manda **UTF-8**. Resultado: qualquer texto acentuado chega corrompido e a busca volta vazia
  (testado: `nomePrograma=computação` em UTF-8 → "Nenhum programa foi encontrado"; em ISO-8859-1 → 4 programas;
  `computacao` sem acento → 4). **Correção sugerida no `client.py`:** em `post()`, mandar
  `content=urlencode(data, encoding="iso-8859-1", errors="xmlcharrefreplace")` com o header de form, em vez de `data=`.
  Enquanto isso, meus serviços tiram o acento dos textos livres (`_ex1s_sem_acento`); as buscas públicas ignoram acento.
- **Encoding da resposta:** quase tudo vem `charset=ISO-8859-1`; o **portal público dos programas** (`/sigaa/public/programa/*.jsf`)
  vem `charset=utf-8` no header (o `<meta>` diz iso-8859-1, ignore). Alguns `title=` do menu do programa vêm com mojibake
  (`ApresentaÃ§Ã£o`) direto do servidor — o parser conserta (`_ex1_mojibake`).
- **ids `j_id_jsp_*` mudam por deploy:** os serviços acham os campos pelo checkbox/rótulo estável da mesma `<tr>`, nunca pelo id.
- Validação de formulário aparece em `#painel-erros` (ex.: "Título: No mínimo 3 caracteres."). "Nada encontrado" também aparece lá.
  Serviço: "nada encontrado" → `[]`; outra mensagem → `SigaaError("O SIGAA recusou a busca: ...")`.
- Nenhuma tela desta área deu "Comportamento Inesperado" ou "endereço digitado não é válido" no recon.

#### GET direto (bookmarkable) × POST com ViewState

| tela | acesso |
|---|---|
| `biblioteca/buscaPublica*.jsf` (formulários) | GET |
| resultado/detalhe do acervo, artigos, aquisições, novas aquisições | **POST** (form da tela anterior) |
| `processo_seletivo/lista.jsf?nivel=S\|L\|T\|I\|F` | **GET** (inclusive S e L, que na home são `jsfcljs`: o clique só redireciona pra `lista.jsf?aba=p-stricto&nivel=S` / `...&nivel=L`) |
| detalhe do processo seletivo (`processo_seletivo/view.jsf`) | **POST** a partir da lista pública ou da lista do programa |
| `diploma/consulta_publica.jsf`, `diploma_digital/consulta_publica.jsf` | GET (formulário); busca = POST |
| `acordo_mobilidade/acordos_mobilidade.jsf` | GET (formulário); lista = POST |
| `programa/lista.jsf` | GET (só formulário, sem lista); lista = POST "Buscar" |
| `programa/{portal,apresentacao,areas,cursos,curriculo,alunos,equipe,defesas,turma,pesquisa,calendario,processo_seletivo,noticias}.jsf?lc=pt_BR&id=<programa>` | **GET** |
| `programa/noticias_desc.jsf?lc=pt_BR&id=<programa>&noticia=<id>` | **GET** |
| `programa/documentos.jsf?...&idTipo=1..5`, `programa/secao_extra.jsf?...&extra=<id>` | GET (não implementados) |
| detalhe do curso (`cursos.jsf` → "Detalhes do Curso") | POST jsfcljs `{id, nivel}` (não implementado) |

---

### 1. Biblioteca

> **Situação na UFBA:** o módulo de biblioteca do SIGAA **não é usado pela UFBA** — select "Biblioteca" vazio, coleções
> herdadas da UFRN (Zila Mamede, Mossoroense…), toda busca do acervo/artigos/aquisições volta "Não foram encontrados",
> e as novas aquisições dos últimos 6 meses dão `(0)`. Os serviços funcionam e devolvem `[]`.
> Pra ter fixture com dados, a **estrutura** das telas de resultado foi capturada no SIGAA público da **UFRN** (mesmo
> software/versão, 4 requisições de consulta): `ufrn_bib_*.html` → fixtures `bib_acervo_resultado.html`,
> `bib_acervo_detalhe.html`, `bib_aquisicoes.html` (autores trocados por nomes fictícios).

#### 1.1 Busca do acervo — `GET /sigaa/public/biblioteca/buscaPublicaAcervo.jsf?aba=p-biblioteca`
Form `formBuscaPublica` (POST, action com `;jsessionid=`). Aba "Busca Multi Campo" (padrão). Links jsfcljs pras outras abas:
`formBuscaPublica:buscaSimples`, `:buscaAvancada`, `:buscaSimplesAutoridades` (não mapeadas).

| rótulo | checkbox (estável) | campo (id dinâmico) | valores |
|---|---|---|---|
| modo do título | — | radio `…_41` | 1=Inicia com, **2=Contém** (padrão), 3=Busca Exata |
| Título | `formBuscaPublica:checkTitulo` | text `…_46` | ≥ 3 caracteres |
| modo do autor | — | radio `…_47` | 1/2/3 idem |
| Autor | `checkAutor` | text `…_52` | |
| Assunto Principal | — | checkbox `…_53` | |
| Assunto | `checkAssunto` | text `…_55` | |
| Local de Publicação | `checkLocalPublicao` (sic) | text `…_57` | |
| Editora | `checkEditora` | text `…_59` | |
| Ano de Publicação de/até | `checkAnoPublicacao` | text `…_61`, `…_62` | |
| Exibir Somente Títulos Digitais | `checkSomenteDigitaisBuscaSimples` | — | |
| Ordenação | — | select `…_64` | 1 Título, 2 Autor, 3 Assunto, 4 Ano, 5 Edição, 6 Com mais Materiais, 7 Mais Recentes, 8 Mais Buscados, 9 Mais Visualizados, 10 Mais Emprestados |
| Registros por página | — | select `…_66` | 25, 50, 100 |
| Biblioteca | `checkBiblioteca` | select `…_69` | **vazio na UFBA** (só `-1`) |
| Coleção | `checkColecao` | select `…_73` | -1, 792651 BRAIL, 1 CIRC, 724181 CORDEL, 1398690 DESBASTE, 723671 DISSERT, 675717 EVEN, 792649 FOLH, 6 HEMER, 724183 MONOG, 792652 MOSS, 694419 MULTI, 3 OR, 661401 PER, 1598574 PR, 792648 PRN, 2 REF, 724315 RELAT, 723673 TESE, 792650 UFRN, 661429 ZILA |
| Tipo de Material | `checkTipoMaterial` | select `…_77` | 1760453 Blu-ray, 9 CD de Áudio, 8 CD-ROM, 21 DVD, 1708643 DVD-ROM, 10 Disco, 11 Disquete, 7 Dissertação, 14 Fita Cassete, 12 Folheto, 13 Fotografia, 22 LD, **1 Livro**, 15 Mapa, 17 Microficha, 16 Microfilme, 5 Monografia Externa, 6 Monografia UFRN, 20 Partitura, 2 Periódico, 1158955 Perspectiva, 1158953 Prancha, 1158954 Projeto de Pesquisa, 1893272 Pôster, 23 Relatório Acadêmico, 18 Slide, 19 Tese, 4 Vídeo |

Botão: `formBuscaPublica:botaoPesquisarPublicaMulti=Pesquisar` (há também `fakeBotao…`, `…_83 Limpar`, `cancelarBuscaMultiCampo`).
Checkbox marcado = `"true"` (aceito). Sem filtro nenhum o SIGAA valida.

**Resultado** (mesma URL): `table#listagem.listagem`, caption `Títulos Encontrados ( 1 a 25 de 47 )`, thead
`Autor | Título | Edição | Ano | Qtd. | (ver) | (opções)`. Ano vem numa tabela aninhada. Link de detalhe:
`jsfcljs(formBuscaPublica, {'formBuscaPublica:ClinkView…', 'idTitulo':'<id>', 'idsBibliotecasAcervoPublicoFormatados':'…', 'apenasSituacaoVisivelUsuarioFinal':'true'})`.
Menu de contexto RichFaces por título (`_id_titulo_context_menu`) — não usado.
**Paginação**: jsfcljs `formBuscaPublica:botaoPaginaj_id_N` / `botaoProximaPagina` / `botaoUltimaPagina` com `_numero_pagina_atual`.
**Nada encontrado**: `#painel-erros` "Não foram encontrados resultados para a busca com estes parâmetros."

#### 1.2 Detalhe do título — POST (clique no `idTitulo`) → `paginaDetalhesMateriaisPublica.jsf`
`h2` "Materiais de um Título", form `formDetalhesMateriaisPublico` (hidden `idTituloVisaulizandoMateriais`=idTitulo).
- `table.visualizacao` caption "Dados do Título": th → td: Registro no Sistema, Número de Chamada, Autor, Título, Local da
  Publicação, Editora, Ano Publicação, Notas Gerais, Edição, Assunto (multivalorados em `table#tabelaInterna*`, um `<td>` por valor).
- Navegação entre títulos do resultado: jsfcljs `navegaPrimeiro…/navegaAnterior…/navegaProximo…/navegaUltima…`.
- Filtros dos exemplares (submit no onchange): `comboBoxBibliotecasExemplares` (-2 = todas), `exemplarVolume` (a4j onblur),
  `situacaoMaterial` (-2 todas, 1 Disponível, 2 Emprestado, 10 Fora de Empréstimo, 11 Reservado).
- `table.subFormulario` caption "Exemplar(es) 1 a N de T": `tr.biblioteca` (agrupador) + linhas `Localização | Tipo de Material |
  Coleção | Status | Situação`; abaixo de cada uma, link a4j "Mostrar Detalhes" com `idMaterialMostrarDetalhes` (modal; não aberto).
- Não há GET direto: o detalhe só abre a partir de um resultado de busca (o serviço refaz a busca).

#### 1.3 Artigos — `GET /sigaa/public/biblioteca/buscaPublicaAcervoArtigos.jsf?aba=p-biblioteca`
Form `formBuscaPublica`: `checkTitulo`+`inputTextTituloArtigo`, `checkAutor`+`inputTextAutorArtigo`,
`checkAssunto`+`inputTextPalavrasChaves`; ordenação select `…_8` (1 Título, 2 Autor, 11 Palavras-Chave, 7 Mais Recentes);
registros `…_10` (25/50/100). Botão `formBuscaPublica:botaoPesquisar`. Na UFBA e na UFRN o teste voltou vazio, então a tabela
de resultado **não foi vista**: o parser é genérico (lê o `thead` por rótulo: título/autor/periódico/ano).

#### 1.4 Aquisições — `GET /sigaa/public/biblioteca/buscaPublicaAquisicoes.jsf?aba=p-biblioteca`
Form `j_id_jsp_…_1` (id dinâmico): Título (text), Autor (text), Ano da Aquisição (text maxlength 4). Botão "Pesquisar".
Resultado (visto na UFRN): `table.listagem` caption `Títulos Encontrados ( 200 )` (parece limitado a 200), agrupadores
`th.ano` "Ano da Aquisição: 2024" > `th.centro` > `th.depto`, linhas `td.titulo` "TÍTULO - Vol. N , AAAA" | autor | quantidade.
Nada: "Nenhum resultado foi encontrado para os critérios utilizados."

#### 1.5 Novas aquisições — `GET /sigaa/public/biblioteca/buscaPublicaNovasAquisicoes.jsf?aba=p-biblioteca`
Form `form`: `form:smlbxBibliotecas` (select múltiplo — **vazio na UFBA; não mandar o campo**), `form:somAreaCNPQ`
(-1 Todas, 50000004 Agrárias, 20000006 Biológicas, 10000003 Exatas e da Terra, 70000000 Humanas, 60000007 Sociais Aplicadas,
40000001 Saúde, 30000009 Engenharias, 80000002 Linguística/Letras/Artes, 90000005 Outra), `form:inicio` (dd/mm/aaaa,
padrão = hoje−1 mês, máx. 6 meses). Botão `form:cmdButtonPesquisar`.
Resultado `resultadoBuscaPublicaNovasAquisicoes.jsf`: `table#tabelaFiltros` (Biblioteca(s), Área de Conhecimento, Período
"dd/mm/aaaa a dd/mm/aaaa") + `table#tabelaResultado` caption "Novas Aquisições das Bibliotecas (N)" com `tr.infoaltrem` por área.
Com N=0 não vi o formato dos itens (parser pega o texto de cada linha sob a área).

---

### 2. Processos seletivos

#### 2.1 Lista — `GET /sigaa/public/processo_seletivo/lista.jsf?nivel=<N>` (aba opcional)
Níveis: **S** stricto (156 linhas, 24 abertas em 19/10/2026), **L** lato, **T** técnico, **I** infantil/fundamental, **F** formação
complementar (L/T/I/F vazios hoje: `div.aviso` "Nenhum processo seletivo encontra-se aberto para inscrições neste nível de ensino.").
Na home, S e L são `jsfcljs` (forms `j_id_jsp_1235242682_3/_9/_13/_16`, param `aba`), mas só redirecionam pro GET acima.

Form `form` no topo = "Consultar inscrições" (CPF + **captcha** `/sigaa/captcha.jpg`) → **área do candidato, NÃO usar**.

`table.listagem` caption "Últimos Processos Seletivos", thead `Curso | Nº Vagas | Período de Inscrições`:
- `td.agrupador` com o link do edital (jsfcljs `{'j_id_jsp_967837914_20…', 'id':'<processo>'}`) + link
  `/sigaa/public/programa/portal.jsf?lc=pt_BR&id=<programa>` ("Acessar página do programa");
- uma linha por curso: curso | `td.colVagas` | `td.colData periodo [fechado]` "dd/mm/aaaa a dd/mm/aaaa" |
  seta "Visualizar dados do processo seletivo" (jsfcljs `{'j_id_jsp_967837914_27…', 'id':'<processo>'}`).
  Classe `fechado` = fora do período (ainda não abriu ou já encerrou); sem ela = aberto (verde).
- Sem paginação (lista "últimos" processos).

#### 2.2 Detalhe — POST (seta da lista) → `processo_seletivo/view.jsf`
Também abre pela lista do programa (`programa/processo_seletivo.jsf`, jsfcljs `visualizarProcessoSeletivo…` `{id}` — `_blank`)
e pelo box do `programa/portal.jsf` (`formProcessos:visualizarProcessoSeletivo…`).
`table.visualizacao` "Dados do Processo Seletivo": Curso (+ `span.unidade` = programa), Edital, Nível, Período de Inscrições
("dd/mm/aaaa às HH:MM - dd/mm/aaaa às HH:MM"), Número de Vagas, Questionário Específico (link jsfcljs — não abrir),
"Clique AQUI para inscrever-se!" (só no período; jsfcljs `{id}` — **inscrição, NÃO clicar**; é dele que o parser tira o id).
Sub-tabelas `table.subFormulario`: **Etapas** (Etapa | Divulgação dos resultados até | Interposição de recursos até |
Análise dos recursos até; `span[title]` = descrição), **Membros da Comissão** (Nome | Função), **Documentos** (Descrição com
link `/sigaa/verProducao?idProducao=…&key=…` | Tipo | Disponibilizado). Depois `td.subFormulario` "Descrição e Orientações aos
Candidatos" / "Orientações aos Inscritos" + `td.texto`. `div#noticias` (vazio: "Não há notícias cadastradas").

---

### 3. Diplomas (SÓ mapeado — nenhuma busca foi feita, nada implementado)

#### 3.1 Registro de diplomas — `GET /sigaa/public/diploma/consulta_publica.jsf?aba=p-graduacao`
`h2` "Consulte os Registros de Diplomas Emitidos pela Instituição". Form `form` (POST), **sem captcha**:

| checkbox | campo | obs |
|---|---|---|
| `form:filtroNome` | `form:inputNome` | Nome do Aluno Diplomado |
| `form:filtroCurso` | `form:inputCurso` | Nome do Curso Superior — autocomplete a4j (`form:suggestion`, `form:suggestion_selection`, `A4J.AJAX.Submit` no keyup) |
| `form:filtroCodigo` | `form:inputCodigo` | Código do e-MEC |
| `form:filtroExpedicao` | `form:dataInicioExpedicao`, `form:dataFimExpedicao` | período de expedição |
| `form:filtroRegistro` | `form:dataInicioRegistro`, `form:dataFimRegistro` | período de registro |
| `form:filtroPublicacao` | `form:dataInicioPublicacao`, `form:dataFimPublicacao` | período de publicação no DOU |

Botões `form:btBuscar` / `form:limpar`. Estado inicial mostra "Nenhum registro encontrado".
**Não implementado**: mesmo sem nome, qualquer busca (por curso/período) devolve a lista de pessoas diplomadas — é busca de
pessoa real, fora do escopo pedido.

#### 3.2 Diploma digital — `GET /sigaa/public/diploma_digital/consulta_publica.jsf?aba=p-graduacao`
Form `form`: `form:inputNome` (rótulo "Código de Verificação do diploma", obrigatório), `form:captcha` (obrigatório, imagem
`/sigaa/captcha.jpg`). Botões `form:btBuscar` / `form:limpar`. Estado inicial: "Nenhum Diploma Digital Encontrado".
**Não implementável** sem resolver captcha (e é validação de documento de pessoa).

---

### 4. Acordos de mobilidade — `GET /sigaa/public/acordo_mobilidade/acordos_mobilidade.jsf?aba=p-relacoes-internacionais`
`h2` "Acordos de Cooperação". Form `formulario` (+ hidden `paginaInicial=0`):

| checkbox | campo | valores |
|---|---|---|
| `formulario:filtroPais` | select `formulario:pais` | 242 países (`0`=SELECIONE, 31 Brasil, 187 Alemanha, 10 Argentina, …) |
| `formulario:filtroInstituicao` | text `formulario:j_id_jsp_1997965821_7` | |
| `formulario:filtroSigla` | text `…_9` | |
| `formulario:filtroAnoAssinatura` | text `…_11` | |
| `formulario:filtroStatus` | select `formulario:status` | 0 SELECIONE **e** 0 Tramitação (valor repetido — bug do SIGAA), 1 Ativo, 2 Aguardando Renovação, 3 Encerrado, 4 Negado, 5 Nova Solicitação |
| `formulario:filtroPeriodoVigencia` | `formulario:dataInicio`, `formulario:dataFim` | |

Botão `formulario:btnBusca=Buscar`. Resultado: `table.listagem` caption "Lista de Acordos (N)" com tabela interna
`País | Instituição | Sigla | Status | Fim de Vigência | (visualizar)`. **Na UFBA: 0 acordos** com qualquer filtro (sem filtro, Ativo,
Brasil) → `#painel-erros` "Não foram encontrados resultados para a busca com estes parâmetros" + linha "Não há acordos disponíveis".
Como nunca apareceu linha, o link "Visualizar Acordo de Cooperação" e seu parâmetro não foram vistos; a fixture
`mobilidade_sintetico.html` é a tabela real com 2 linhas **inventadas** no padrão SIGAA (pra testar o parser por rótulo).

---

### 5. Programas de pós-graduação

#### 5.1 Lista — `GET /sigaa/public/programa/lista.jsf?aba=p-stricto` (ou `p-academico`) + POST "Buscar"
O GET só traz o form `form`: `form:nomePrograma` (palavra-chave, sem acento — ver aviso), `form:programas` (centro: 0 Todos,
1283 Esc. Administração, 1235 Belas Artes, 1354 Dança, 1252 Enfermagem, 1336 Med. Veterinária, 1292 Música, 1302 Nutrição,
1361 Teatro, 1200 Politécnica, 1274 Arquitetura, 1369 Contábeis, 1348 Comunicação, 1193 Direito, 1245 Economia, 1316 Educação,
1258 Farmácia, 1218 FFCH, 1175 Medicina, 1266 Odontologia, 1137 Biologia, 1308 ICI, 1167 ICS, 2435 Computação, 1120 Física,
1144 Geociências, 1780 IHAC, 1158 Letras, 1112 IME, 1779 IPS, 1128 Química, 1105 ISC, 2439 IMRS, 1791 IMS).
Botão `form:buscar`. Resultado: `table.listagem` caption "(100) Programas encontrados", `td.subListagem` = centro, linhas com
`portal.jsf?lc=pt_BR&id=<programa>`. Nada: `#painel-erros` "Nenhum programa foi encontrado de acordo com os critérios de busca informados".

#### 5.2 Página pública do programa — tudo GET `…/programa/<pagina>.jsf?lc=pt_BR&id=<programa>`
Idiomas: `lc=en_US|es_ES|fr_FR`. Cabeçalho comum a todas (`div#nomes`): `span.sigla`, `span.nome_programa`, centro
(`/sigaa/public/centro/portal.jsf?id=`), `span.telefone_programa`, `span.email_programa`, `span.url_programa`.
Menu: Programa (apresentacao, areas, cursos, curriculo) · Ensino (alunos, equipe, defesas, turma) · pesquisa · calendario ·
processo_seletivo · noticias · Documentos (`documentos.jsf?idTipo=4 Formulários, 3 Resolução, 2 Regimento, 1 Outros,
5 Material Didático`) · Outras Opções (`secao_extra.jsf?extra=<id>`).

| página | conteúdo | parser |
|---|---|---|
| `portal.jsf` | `#esquerda #listagem` últimas 5 notícias (`noticias_desc.jsf?…&noticia=`, `span.data`), box "Processos Seletivos" (`form#formProcessos`, jsfcljs `{id}` → detalhe), seções extras | `parse_programa_portal` |
| `apresentacao.jsf` | `#conteudo` com pares `div.titulo` + `div.texto`/`div.texto_afastado`: "Apresentação" (HTML rico), "Endereço Alternativo", "Coordenação do Programa" (`ul#listagem li`: link `docente/portal.jsf?siape=`, `.dados p` Telefone/Ramal, Telefone/Ramal 2, E-mail — coordenador e vice sem distinção) | `parse_programa_apresentacao` |
| `areas.jsf` | por nível (`div#listagem_tabela` > `#group_lt`): `tr.campos` = área de concentração; `td.denominacao` = linha de pesquisa, `img onclick=exibirResumo(…'#trOpcoes<id>')` → `td.descricao#trOpcoes<id>` | `parse_programa_areas` |
| `cursos.jsf` | por curso (`#group_lt` "NOME - Nível"): link CAPES + jsfcljs "Detalhes do Curso" `{id, nivel}` (D=doutorado, E=mestrado) | `parse_programa_cursos` |
| `equipe.jsf` | grupos (`span#group_lt`: áreas de concentração, "Pós-Doutorandos") + `table#table_lt`: Nome (link `docente/portal.jsf?siape=` quando há) \| Vínculo \| Nível \| Telefone/Ramal \| C.Lattes \| E-mail (mailto) | `parse_programa_docentes` |
| `processo_seletivo.jsf` | por nível (`#group_lt`): Período \| link jsfcljs `visualizarProcessoSeletivo…` `{id}` (`span.destaqueProcessoeletivo` = edital) | `parse_programa_processos_seletivos` |
| `noticias.jsf` | `ul#listagem li`: `span.data` "(dd/mm/aaaa HH:MM)" + link `noticias_desc.jsf` | `parse_programa_noticias` |
| `noticias_desc.jsf?…&noticia=` | `#conteudo .texto`: `h2` título + texto livre (bancas de defesa trazem discente, data, local, título, resumo, banca) | `parse_programa_noticia` |
| `alunos`, `defesas`, `turma`, `pesquisa`, `calendario`, `curriculo`, `documentos`, `secao_extra` | não implementados (alunos = lista de pessoas) | — |

Programa inexistente: não testado (sem força bruta de id); o serviço levanta `NaoEncontrado` se a página vier sem `#nomes`/`#conteudo`
ou sem nome.

---

### Resultado do pytest

```
$ .venv/bin/python -m pytest tests/test_consultas_publico.py -q
.....................                                                    [100%]
21 passed in 0.24s
```

### Resultado do e2e (`.venv/bin/python recon/parts/extras1/e2e.py`, 19/10/2026)

```
- buscar_acervo(titulo='calculo diferencial'): 0 títulos
- buscar_acervo(titulo='ab'): erro esperado -> O SIGAA recusou a busca: Título: No mínimo 3 caracteres.
- buscar_artigos(titulo='educacao'): 0 artigos
- buscar_aquisicoes(ano=2025): 0 livros
- novas_aquisicoes(): total=0 período=2026-09-19..2026-10-19
- listar_processos_seletivos(nivel=S): 156 linhas, 24 abertas
    ex.: 40043 | PROCESSO SELETIVO PARA INGRESSO NO CURSO DE DOUTORADO 2027.1 | DOUTORADO EM BIODIVERSIDADE E EVOLUÇÃO | vagas=6 | 2026-10-19..2026-12-13
    detalhe: DOUTORADO | PROCESSO SELETIVO PARA INGRESSO NO CURSO DE DOUTORADO 2027.1 | etapas=3 comissão=4 docs=1 inscricoes_abertas=True
- listar_processos_seletivos(nivel=L): 0 linhas, 0 abertas
- listar_processos_seletivos(nivel=T): 0 linhas, 0 abertas
- listar_processos_seletivos(nivel=I): 0 linhas, 0 abertas
- listar_processos_seletivos(nivel=F): 0 linhas, 0 abertas
- listar_acordos_mobilidade(): 0 acordos
- listar_programas_pos(): 100 programas | ex.: id=1289 nome='PROGRAMA DE PÓS-GRADUAÇÃO EM ADMINISTRAÇÃO (NPGA)' sigla='NPGA' centro='ESCOLA DE ADMINISTRAÇÃO'
- listar_programas_pos(nome='computação'): ['PPGEEC', 'PGCOMP', 'PMCC', 'PROFCOMP']
- programa_pos(1825): PPGBIOEVO | INSTITUTO DE BIOLOGIA | ppgbioevo@ufba.br | apresentação=2869 chars | coordenação=2 | notícias=5 | processos=2
- programa_pos_areas: 4 áreas, 9 linhas
- programa_pos_cursos: ['DOUTORADO EM BIODIVERSIDADE E EVOLUÇÃO', 'DOUTORADO EM DIVERSIDADE ANIMAL', 'MESTRADO EM BIODIVERSIDADE E EVOLUÇÃO', 'MESTRADO EM DIVERSIDADE ANIMAL']
- programa_pos_docentes: 34 pessoas em 2 grupos
- programa_pos_processos_seletivos: [(40043, 'Doutorado'), (40039, 'Mestrado')]
- processo_seletivo(via programa): 40043 PROCESSO SELETIVO PARA INGRESSO NO CURSO DE DOUTORADO 2027.1
- programa_pos_noticias: 98 notícias
- programa_pos_noticia: 'Banca de DEFESA: FULANO DE TAL' (2869 chars)   ← nome real trocado aqui no doc
```

---


---

# Parte 3 — Frente extras2: pesquisa, extensão, cursos abertos

> Código fundido em `sigaa/*/consultas_publico.py` (seção "extras2"); fixtures em `tests/fixtures/consultas/publico/extras2/`.

Mapeado em 19/10/2026 no SIGAA UFBA **v4.13.8_41_hotfix**, sem login. Páginas cruas em
`recon/pages/consultas/publico/extras2/` (UFBA). As referências de estrutura com dados ficam em `.../extras2/ufpb/`
(SIGAA UFPB) e `.../extras2/ufrn/` (SIGAA UFRN v4.20).

### Resumo do que existe na UFBA

| tela | situação na UFBA (out/2026) |
|---|---|
| Pesquisa · projetos (`consulta_projetos.jsf`) | form funciona, mas **toda busca** dá "Não foram encontrados resultados para a busca com estes parâmetros." Testei ano 2012/2018/2024/2025, centro IC, título, pesquisador "SILVA", agência CNPq |
| Pesquisa · bases (`consulta_bases.jsf`) | busca vazia: "Nenhum grupo de pesquisa foi encontrado de acordo com os critérios de busca utilizados." |
| Pesquisa · bolsistas IC (`consulta_bolsistas.jsf`) | **página de erro de configuração**: "O parâmetro de código "2_10500_1047" deveria ser uma lista de números separados por vírgulas, mas o seu valor está ""." (não é "Comportamento Inesperado", mas não repeti) |
| Pesquisa · laboratórios (`consulta_laboratorios.jsf`) | busca sem filtro: "Não foram encontrados resultados..." |
| Extensão · ações (`consulta_extensao.jsf`) | toda busca: "Nenhuma ação de extensão localizada" (tipo 2/3, ano 2015/2025, título "saude"/"Saúde") |
| Extensão · inscrições abertas | "Nenhum Curso ou Evento de Extensão com período de inscrição aberto" |
| Cursos abertos (`cursosabertos.jsf`) | **funciona com dados**: 35 centros, 88 departamentos no menu, 1 turma publicada (PGEDU0151) com detalhe e 6 materiais |

Conclusão: a UFBA quase não usa os módulos de pesquisa e extensão do SIGAA. Mesmo assim os parsers e serviços estão
implementados e testados sobre as MESMAS telas de outra instalação do SIGAA (UFPB/UFRN): fixtures `ref_*`,
validação de ponta a ponta mais abaixo. Assim, quando a UFBA publicar dados, tudo já funciona.

### ⚠️ Encoding dos POSTs (vale pro projeto inteiro)
O SIGAA lê os campos do form como **ISO-8859-1**. Testado na UFPB, ações de extensão com título "educação":
- corpo em latin-1 → **131** resultados
- corpo em UTF-8 (o que o `httpx`/`c.submit`/`c.clicar` mandam hoje) → **0** (chega "educaÃ§Ã£o")
- sem acento ("educacao") → **0** (a busca não ignora acento)

Por isso `sigaa/services/consultas_publico.py` tem o `_ex2_enviar(c, page, form_id, extra, botao)`: monta `form_fields` + `urlencode(..., encoding="iso-8859-1")`
e posta via `c.post(action, {}, content=corpo, headers={"Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"})`.
**Sugestão pro core:** `SigaaClient.submit/clicar/post` codificarem o corpo em latin-1. Qualquer filtro de texto acentuado
de outras áreas está quebrado hoje por causa disso.

### Bookmarkable × POST
| tela | GET direto? |
|---|---|
| todas as telas de busca (`consulta_*.jsf`, `cursosabertos.jsf`, inscrições) | GET abre o form (aceita `?aba=...`, ignorado) |
| `consulta_extensao.jsf?acao=N` | GET; o `acao` só pré-seleciona o tipo no select. **Fica grudado na sessão**: depois do 1º `?acao=1` as próximas GETs com outro `acao` continuaram em PROGRAMA |
| detalhe de ação de extensão | **GET bookmarkable**: `/sigaa/link/public/extensao/visualizacaoAcaoExtensao/{id}` (redireciona pra `viewDadosCursoEvento.jsf`). Validado na UFPB; na UFBA não testei porque não há nenhum id listado. Também abre por POST na lista (`idAtividadeExtensaoSelecionada`) |
| detalhe de projeto de pesquisa | só POST a partir da lista (`formConsultaProjeto`, param `id`) → `pesquisa/view.jsf` |
| detalhe de laboratório | só POST a partir da lista (form `form`, param `id`) → `pesquisa/view_laboratorio.jsf` |
| detalhe de turma aberta | só POST a partir da lista (`formPrincipal`, param `tid`) → mesma URL `cursosabertos.jsf`, form `formResumoCursoAberto` |
| `/sigaa/link/public/extensao/acessarAreaInscrito` | **NÃO aberto** (área do inscrito, fora do escopo) |

Paginação: nenhuma das listas pagina. A UFPB devolveu 131 ações, a UFRN 450 laboratórios e a UFPB 3.325 bolsistas (3,4 MB),
tudo numa página só. Não há `max_paginas`.

---

### 1. Pesquisa · Projetos ("Quem pesquisa o que")
- **URL:** `/sigaa/public/pesquisa/consulta_projetos.jsf` (GET abre o form)
- **Form:** `formConsulta`, botão `formConsulta:buscar=Buscar` (também `formConsulta:cancelar`)
- **Campos:** cada filtro tem um checkbox `checkX=on` que precisa ir marcado (o `onchange`/`onfocus` marca no navegador)
  | checkbox | campo | valores |
  |---|---|---|
  | `formConsulta:checkTitulo` | `formConsulta:titulo` | texto |
  | `formConsulta:checkObjetivos` | `formConsulta:objetivos` | texto (palavras-chave) |
  | `formConsulta:checkPesquisador` | `formConsulta:nomePesquisador` | texto |
  | `formConsulta:checkAno` | `formConsulta:ano` | inteiro |
  | `formConsulta:checkCentro` | `formConsulta:centro` | select, 36 centros (ex. 1283 ESCOLA DE ADMINISTRAÇÃO, 1316 FACED); `0` = nenhum |
  | `formConsulta:checkUnidade` | `formConsulta:unidade` | select, 94 departamentos |
  | `formConsulta:checkArea` | `formConsulta:area` | select, 1.380 áreas CNPq (ex. 10502033 Acústica) |
  | `formConsulta:checkGrupo` | `formConsulta:grupo` | select **vazio** na UFBA (só "-- SELECIONE --") |
  | `formConsulta:checkAgencia` | `formConsulta:agencia` | select, 41 agências (3 CNPQ, 4 CAPES, 7 BNB, 13 ANP...) |
- **Nada encontrado:** `#painel-erros ul.erros li` = "Não foram encontrados resultados para a busca com estes parâmetros."
- **Resultado** (ref. UFPB): `form#formConsultaProjeto` > `table.listagem`, caption "Lista de Projetos de Pesquisa Encontrados";
  thead `Código | Título / Coordenador | Tipo | Situação`. Linhas `tr.centro` (agrupa por centro), `tr.ano` (agrupa por ano), e cada projeto
  ocupa 3 `tr`: (1) `td[rowspan=2]` código + título em `<i>`; (2) coordenador | tipo | situação | link ver;
  (3) `p.descricao` (vazio). Link: `jsfcljs(formConsultaProjeto, {...:'...', 'id':'35733465'})`.
- **Detalhe** (`pesquisa/view.jsf`): `table.visualizacao` caption "Projeto de Pesquisa", rótulos th: Código, Título, Tipo do Projeto,
  Situação, E-mail, Centro, Coordenador, Edital, Cota (com período "(01/09/2024 a 31/08/2025)"), Palavra-Chave,
  Área de Conhecimento, Grupo de Pesquisa, Linha de Pesquisa. Depois `h4 Descrição + p` e `h4 Membros da Equipe` com
  `table.equipeProjeto` (span.nome com link `portal.jsf?siape=`, "Categoria: DOCENTE", "Tipo : COORDENADOR(A)").
  O e-mail **não** entra no modelo (dado pessoal).

### 2. Pesquisa · Bases de pesquisa
- **URL:** `/sigaa/public/pesquisa/consulta_bases.jsf`. **Form** `formConsulta`, botão `formConsulta:buscar`
- **Campos:** `checkNome`+`nome`, `checkCoordenador`+`nomeCoordenador`
- **Nada encontrado:** "Nenhum grupo de pesquisa foi encontrado de acordo com os critérios de busca utilizados."
- **Resultado** (ref. UFPB): `table.listagem` caption "Bases de Pesquisa encontradas", thead `Código | Nome | Coordenador`,
  tfoot "N bases encontradas". **Sem link de detalhe** na lista (UFPB); o parser pega `id` se algum dia vier link.

### 3. Pesquisa · Bolsistas de IC
- **URL:** `/sigaa/public/pesquisa/consulta_bolsistas.jsf`. **Form** `formConsulta`, botão `formConsulta:buscar`
- **Campos:** `checkAluno`+`nomeDiscente`, `checkOrientador`+`nomeOrientador`, `checkModalidade`+`modalidade`
  (UFBA: 11491050 DINTER (IC), 11491051 DINTER (IT), 6 PROPESQ - INDUÇÃO (IC), 2178879 REUNI - NUPLAM (IT), 13266400 REUNI-DINTER (IT)),
  `checkCentro`+`centro` (35), `checkCurso`+`curso` (116 cursos), `checkGrupo`+`grupo` (vazio)
- **UFBA:** a busca (modalidade 6) devolve a página de erro do parâmetro `2_10500_1047`. O serviço detecta e levanta `SigaaError`.
- **Resultado** (ref. UFPB): `table.listagem` caption "Alunos encontrados"; `tr.cota` (agrupador "Cota 2026-2027 PIBIC-..."),
  `tr.topo` = discente | tipo de bolsa; depois linhas com `<i>Projeto de Pesquisa:</i> CÓDIGO - título`, `<i>Título:</i>` (plano),
  `<i>Orientador:</i>`, `<i>Período:</i> dd/mm/aaaa [a dd/mm/aaaa]`. Nomes de alunos anonimizados nas fixtures.

### 4. Pesquisa · Laboratórios
- **URL:** `/sigaa/public/pesquisa/consulta_laboratorios.jsf`. **Form** `form`, botão `form:btnBuscar=Buscar` (`form:btnCancelar` tem confirm)
- **Campos:** `selectBuscaAno`+`buscaAno`, `selectBuscaNome`+`buscaNome`, `selectBuscaTipoLaboratorio`+`buscaTipoLaboratorio`
  (3 Multiusuários, 4 Uso Restrito), `selectBuscaUnidade`+`unidade` (**autocomplete a4j** `form:suggestion`, id em
  `form:suggestion_selection`, não implementado), `selectBuscaSubUnidade`+`buscaSubUnidade` (preenchido por a4j a partir da unidade),
  `selectBuscaServidor`+`nomeServidor`, `selectBuscaLaboratorioEmAtividade`+`buscaEmAtividade` (true/false),
  `selectBuscaLaboratorioComPrestacaoServicos`+`buscaPrestaServicos` (true/false), `selectBuscaServicoPrestado`+`servicoPrestado`
  (autocomplete), `selectGerarRelatorio` (não usado)
- **Nada encontrado:** "Não foram encontrados resultados para a busca com estes parâmetros."
- **Resultado** (ref. UFRN): `table#tableLaboratoriosEncontrados` caption "Laboratórios Encontrados (N)", thead
  `Código | Nome | Unidade - Subunidade | Coordenador`, link `jsfcljs(form, {..., 'id':'186483611'})`. O link está no
  **próprio form de busca**, por isso o clique também vai em latin-1.
- **Detalhe** (`view_laboratorio.jsf`): `table.formulario` caption "Dados do Laboratório", pares th/td; valores múltiplos continuam
  em linhas `<td></td><td>valor</td>` (Grupos de Pesquisa, Programas de Pós, Produções Científicas, Serviços). Seções: Identificação,
  Serviços (perguntas "Existe prestação..."/"Existe intenção...", cada uma seguida da sua lista "Serviços:"), Coordenação
  (Coordenador, Email (ignorado), Início da Coordenação, Vice-Coordenador).

### 5. Extensão · Ações de extensão
- **URL:** `/sigaa/public/extensao/consulta_extensao.jsf[?acao=1|2|3|4|6]`. **Form** `formBuscaAtividade`, botão `formBuscaAtividade:btBuscar=Buscar`
- **Campos:** `selectBuscaTitulo`+`buscaTitulo`; `selectBuscaTipoAtividade`+`buscaTipoAcao` (3 CURSO, 4 EVENTO, 5 PRESTAÇÃO DE SERVIÇOS,
  6 PRODUTO, 1 PROGRAMA, 2 PROJETO). A tela já vem com esse checkbox **marcado** (JS no fim); sem tipo pedido o serviço desmarca.
  `selectBuscaUnidadeProponente`+`buscaUnidade` (572 unidades), `selectBuscaServidor`+`nomeServidor` (autocomplete a4j
  `suggestionNomeServ`, id em `suggestionNomeServ_selection`, não implementado), `selectBuscaAno`+`buscaAno` (vem 2026 desmarcado)
- **Nada encontrado:** `<h3><i>Nenhuma ação de extensão localizada</i></h3>` (aparece também no GET inicial)
- **Resultado** (ref. UFRN/UFPB, idênticos): `form#form` > `table.listagem` caption "Ações de extensão localizadas (N)", thead
  `Ano/Título | Tipo | Departamento`, link "Visualizar Ação" `{'idAtividadeExtensaoSelecionada':'13035','acao':'2'}`.
- **Detalhe** (`viewDadosCursoEvento.jsf`): `table.visualizacao` caption "Ação de Extensão": Título, Ano, Nº Bolsas Concedidas,
  Nº Discentes Envolvidos, Público Estimado, Área Principal, Área do CNPq, Unidade Proponente, Unidades Envolvidas (span.label),
  Tipo, Municípios de Realização, Espaços de Realização (separados por `<br>`), Fonte de Financiamento, Url da Acão. Seções h4:
  Resumo, Público Alvo (curso/evento/produto trazem outros campos e seções: vão para `campos`/`secoes`). Equipe em `table.equipeProjeto`
  ("Função : COORDENADOR(A)").
  Obs.: na UFRN (v4.20) o detalhe redireciona para login gov.br; na UFPB é público.

### 6. Extensão · Cursos e eventos com inscrição aberta (só listagem)
- **URL:** `/sigaa/public/extensao/paginaListaPeriodosInscricoesAtividadesPublico.jsf` (GET já lista)
- **Form** `formListaCursosEventosExtensao`, botão `cmdFiltarPeriodosInscricao=Filtrar`. Campos: `selectBuscaTitulo`+`buscaTitulo`,
  `selectBuscaTipoAtividade`+`buscaTipoAcao` (0 TODOS, 3 CURSO, 4 EVENTO), `selectBuscaArea`+`buscaArea` (vazio na UFBA),
  `selectBuscaServidor`+`buscaServidor`(hidden)/`buscaNome`, `selectBuscaPeriodo`+`periodoInicio`/`periodoFim` (dd/mm/aaaa)
- **Nada encontrado:** "Nenhum Curso ou Evento de Extensão com período de inscrição aberto"
- **Resultado** (ref. UFPB): `table.listagem` caption "Inscrições Abertas ( N )": Título (span bold + "Coordenação: X") | Tipo |
  Inscrições até | Vagas Total/Aprovadas/Pendentes/Restantes | ver detalhe (`idAtividadeExtensaoSelecionada`,
  `idQtdSubatividadeExtensao`) | "Inscrever-se" (`/sigaa/link/public/extensao/acessarAreaInscrito`, **ignorado**). Cada registro tem
  uma linha escondida `tr#atividade<ID>` com `table.listagemSub` "Mini Atividades" (Título | Data | Hora | Local).

### 7. Cursos abertos
- **URL:** `/sigaa/public/cursosabertos.jsf?aba=p-ensino` (GET). Layout próprio (sem `#conteudo`).
- **Menu lateral** (`form#menuForm`): `dl > dt a.centro` + `dd id="<id do centro>"` > `a.departamento` (commandLink
  `menuForm:j_id_jsp_955622233_2[j_id_N]`, sem id do depto). Clicar em "DEP. DE EDUCACAO I/FACED" deu "Não foram encontrados resultados".
- **Form de busca** `formPrincipal`, botão `formPrincipal:buscarTurmas=Buscar`:
  - `formPrincipal:tipoBusca`: radio `true` = Turmas (padrão) / `false` = Comunidades Virtuais (o clique dispara a4j, mas dá pra mandar direto)
  - `formPrincipal:palavraChave`: texto (maxlength 200)
  - `formPrincipal:idCentro`: select (0 TODOS + 35 centros). `onchange` = **a4j** `AJAXREQUEST=j_id_jsp_955622233_0`
    + `formPrincipal:j_id_jsp_955622233_19=formPrincipal:j_id_jsp_955622233_19`. A resposta é XHTML (UTF-8) com o
    `select#formPrincipal:idDepartamento` preenchido (FACED=1316 → 8 departamentos, ex. 1322, 2677, 2640, 1899, 1321, 1317...)
  - `formPrincipal:idDepartamento`: select (só "-- TODOS --" até o a4j do centro)
- **Lista:** `div#turmasAbertas table.listagem`, caption "Últimas Turmas Publicadas" (sem busca) ou "N Turma(s) encontrada(s)";
  `td.turma`: código + link `{'formPrincipal:j_id_jsp_955622233_27':..., 'tid':'376591'}`. tfoot "N Turma(s) encontrada(s)".
- **Nada encontrado:** "Não foram encontrados resultados para a busca com estes parâmetros." Comunidades sem palavra-chave dão
  "Por favor, digite uma palavra que identifique a comunidade virtual."; com "ufba", "grupo" e "pesquisa" nada foi encontrado
  (a estrutura da lista de comunidades fica sem mapear).
- **Detalhe** (POST com `tid`): `form#formResumoCursoAberto`, `h4 NOME (CÓDIGO)`, `table.visualizacao` "Informações Gerais"
  (Data da Oferta = "2026.1", Ementa, `td.docentes div.bloco` com `span.nome`, link `../public/docente/portal.jsf?siape=` e mailto),
  `h2 Material do Curso` + `div.topico-aula` (h3 "Título (dd/mm/aaaa - dd/mm/aaaa)", `ul li p` texto, `li a[href^=/sigaa/verProducao?idProducao=..&key=..]`).
- Variações: 1 turma publicada na UFBA (PGEDU0151). Filtro por centro 1316 / depto 1319 voltou vazio (a turma de pós não fica
  sob o departamento).

### Fixtures (`fixtures/`)
`ufba_*` = telas reais da UFBA; `ref_*` = mesmas telas na UFPB (projetos, projeto, bases, bolsistas, ações, ação, inscrições) e
UFRN (laboratórios, laboratório). Todas anonimizadas: pessoas → FULANO DE TAL/CICLANO DA SILVA/..., e-mails → fulano@example.org,
SIAPE → 1000001+, fotos → no_picture.png, `key=` de material zerada, jsessionid removido, listas encurtadas para 2 a 3 registros,
selects para 5 opções (menos o `idCentro` de cursos abertos). Uma checagem automática cruzou os 2.660 nomes extraídos das páginas cruas
com as fixtures: nenhum vazou.

### Testes
`.venv/bin/python -m pytest tests/test_consultas_publico.py` → **15 passed in 0.23s**

### E2E (UFBA real, `recon/parts/extras2/e2e.py`)
```
- projetos de pesquisa (ano=2024): 0
- projetos de pesquisa (título='educação'): 0
- bases de pesquisa (nome='educação'): 0
- laboratórios (todos): 0
- ações de extensão (projetos 2025): 0
- ações de extensão (título='educação'): 0
- inscrições de extensão abertas: 0
- centros (cursos abertos): 35 | ex.: {'id': 1283, 'nome': 'ESCOLA DE ADMINISTRAÇÃO', 'departamentos': [{'nome': 'COORDENAÇÃO ACADÊMICA/EADM'}]}
  departamentos no menu: 88
- departamentos a4j (FACED=1316): 8 | ex.: {'id': 1322, 'nome': 'COLEGIADO DO CURSO DE GRADUAÇÃO DE LICENCIATURA EM EDUCAÇÃO FÍSICA/FACED'}
- cursos abertos (últimas publicadas): 1 | ex.: {'id': 376591, 'codigo': 'PGEDU0151', 'nome': 'PROJETO DE TESE I'}
- cursos abertos (palavra-chave='tese'): 1 | ex.: {'id': 376591, 'codigo': 'PGEDU0151', 'nome': 'PROJETO DE TESE I'}
- cursos abertos (centro 1316, depto 1319): 0
- detalhe turma 376591: PGEDU0151 PROJETO DE TESE I | período 2026.1 | 2 docente(s) | 1 tópico(s), 6 material(is)
```
(`--bolsistas` liga a chamada de bolsistas, que na UFBA cai no erro de configuração; deixei desligada por padrão.)

**Os mesmos serviços contra instalações com dados** (`SigaaClient("https://sigaa.ufpb.br")` / ufrn):
```
UFPB ações 'educação' 2024: 131
  detalhe via link GET: 13035 QUEBRA GELO: Karaokê como Ponte entre Be 8 membros
  detalhe via lista: 12954 (Co)Laboratório de Invenções de Educação
UFPB projetos 'semiótica' 2024: 2
  detalhe: 35733465 PVP17825-2024 Lingüística Aplicada 2 membros
UFPB bases 'educação': 10
UFPB inscrições abertas: 4
UFRN labs 'História': 10
  detalhe: 186483611 LAB2291-2026 ANTIQVA True
```

### Fora do escopo / pendências
- Autocompletes a4j (coordenador/servidor da extensão, unidade e serviço prestado dos laboratórios) e o select `grupo` (vazio na UFBA).
- Lista de **comunidades virtuais** (`tipoBusca=false`): nenhuma busca trouxe resultado, então a estrutura não foi vista.
- Turmas por clique no **menu de departamento** (`menuForm`): serviço não feito; use `buscar_cursos_abertos(centro_id, departamento_id)`.
- Detalhe de base de pesquisa: a lista não tem link (UFPB), então não existe tela pública de detalhe.
- O link bookmarkable de extensão não foi testado na UFBA (não há id listado).
- Download do material (`/sigaa/verProducao?idProducao=..&key=..`): só exposto como URL.


---

## CONTRATO DOS SERVIÇOS

Todos ficam em `sigaa/services/consultas_publico.py`. São `async def`, e o primeiro argumento é `c: SigaaClient`, **anônimo** (sem login). Use `SigaaClient(min_interval=0.35)`.

Os serviços não guardam estado. Os que devolvem lista trazem a lista **inteira**: a paginação fica na rota. Nenhuma tela pública do núcleo pagina no SIGAA.

Erros possíveis:
- `NaoEncontrado` → 404;
- `ValueError` (filtro obrigatório faltando, nível ou tipo inválido) → 422;
- `NavegacaoInvalida` e `SigaaError` → tratamento padrão.

Prefixo das rotas sugeridas: `/v1/publico`. Parâmetros de query em kebab-case.

### Núcleo acadêmico

| função | retorno | rota sugerida |
|---|---|---|
| `listar_cursos(c, nivel: str = "G", *, nome: str \| None = None, modalidade: str \| None = None, unidade: str \| None = None)` | `list[CursoResumo]` | `GET /v1/publico/cursos?nivel=G&nome=&modalidade=&unidade=` |
| `curso(c, curso_id: int, nivel: str = "G")` | `Curso` | `GET /v1/publico/cursos/{curso_id}?nivel=G` (pós: `nivel=S`) |
| `estruturas_curso(c, curso_id: int, nivel: str = "G")` | `list[EstruturaResumo]` | `GET /v1/publico/cursos/{curso_id}/estruturas?nivel=G` |
| `estrutura_curricular(c, estrutura_id: int, curso_id: int, nivel: str = "G", *, relatorio: bool = False)` | `EstruturaCurricular` | `GET /v1/publico/cursos/{curso_id}/estruturas/{estrutura_id}?nivel=G` (*) |
| `calendario_curso(c, curso_id: int)` | `list[EventoCalendarioCurso]` | `GET /v1/publico/cursos/{curso_id}/calendario` |
| `projeto_pedagogico(c, curso_id: int)` | `ProjetoPedagogico` | `GET /v1/publico/cursos/{curso_id}/projeto-pedagogico` |
| `noticias_curso(c, curso_id: int)` | `list[NoticiaCurso]` | `GET /v1/publico/cursos/{curso_id}/noticias` |
| `turmas_curso(c, curso_id: int, ano: int, periodo: int, *, codigo: str \| None = None)` | `list[TurmaCurso]` | `GET /v1/publico/cursos/{curso_id}/turmas?ano=&periodo=&codigo=` |
| `buscar_componentes(c, nivel: str = "G", *, codigo: str \| None = None, nome: str \| None = None, unidade_id: int \| None = None, tipo: str \| None = None)` (exige 1 filtro) | `list[ComponenteResumo]` | `GET /v1/publico/componentes?nivel=G&codigo=&nome=&unidade=&tipo=` |
| `componente(c, componente_id: int)` | `ComponenteCurricular` | `GET /v1/publico/componentes/{componente_id}` (GET direto) |
| `componente_por_codigo(c, codigo: str, nivel: str = "G")` | `ComponenteCurricular` | `GET /v1/publico/componentes/codigo/{codigo}?nivel=G` (formato mais completo) |
| `programa_componente(c, codigo: str, nivel: str = "G")` | `ProgramaComponente` (404 se não houver) | `GET /v1/publico/componentes/codigo/{codigo}/programa?nivel=G` |
| `unidades_academicas(c)` | `list[UnidadeAcademica]` | `GET /v1/publico/unidades` |
| `buscar_turmas(c, ano: int, periodo: int, unidade_id: int, nivel: str = "G", *, componente: str \| None = None)` | `list[TurmaPublica]` | `GET /v1/publico/turmas?ano=&periodo=&unidade=&nivel=G&componente=` (ano, periodo e unidade obrigatórios) |
| `buscar_docentes(c, *, nome: str \| None = None, departamento_id: int \| None = None)` (exige 1) | `list[DocenteResumo]` | `GET /v1/publico/docentes?nome=&departamento=` |
| `docente(c, siape: int)` | `Docente` | `GET /v1/publico/docentes/{siape}` |
| `producao_docente(c, siape: int)` | `list[ProducaoCategoria]` | `GET /v1/publico/docentes/{siape}/producao` |
| `disciplinas_docente(c, siape: int)` | `list[DisciplinaMinistrada]` | `GET /v1/publico/docentes/{siape}/disciplinas` |
| `listar_centros(c)` | `list[CentroResumo]` | `GET /v1/publico/centros` |
| `centro(c, centro_id: int)` | `Centro` | `GET /v1/publico/centros/{centro_id}` |
| `listar_departamentos(c, *, centro_id: int \| None = None)` | `list[DepartamentoResumo]` | `GET /v1/publico/departamentos?centro=` |
| `departamento(c, departamento_id: int)` | `Departamento` | `GET /v1/publico/departamentos/{departamento_id}` (sugestão: alias `/v1/publico/unidades/{id}`) |
| `docentes_departamento(c, departamento_id: int)` | `list[DocenteResumo]` | `GET /v1/publico/departamentos/{departamento_id}/docentes` |
| `componentes_departamento(c, departamento_id: int)` | `list[ComponenteResumo]` | `GET /v1/publico/departamentos/{departamento_id}/componentes` |
| `responsaveis(c, tipo: str = "chefes")` (`chefes` \| `coordenadores_graduacao` \| `coordenadores_pos` \| `diretores`) | `list[Responsavel]` | `GET /v1/publico/responsaveis?tipo=chefes` |

(*) A estrutura curricular **só abre a partir do curso** (POST com ViewState). Por isso a rota pede o `curso_id`. Se quiser manter também `/v1/publico/estruturas/{id}`, aceite `?curso=` como query obrigatória.

Os ids de `unidade` (turmas e componentes), de `departamento` e do filtro de docentes são **o mesmo id** (ex.: DCC = 1114). O `centro_id` é outro espaço de ids (ex.: IC = 2435).

### Frente extras1

Todos em `services.py`, `async`, primeiro argumento `c: SigaaClient` (sem login). Textos livres vão sem acento (ver aviso).

| função | retorno | rota sugerida |
|---|---|---|
| `buscar_acervo(c, *, titulo=None, autor=None, assunto=None, editora=None, local_publicacao=None, ano_inicio=None, ano_fim=None, tipo_material: int\|None=None, colecao: int\|None=None, ordenacao: int=1, registros_por_pagina: int=100, max_paginas: int=5)` | `list[AcervoTitulo]` | `GET /v1/publico/biblioteca/acervo?titulo=&autor=&assunto=&editora=&local-publicacao=&ano-inicio=&ano-fim=&tipo-material=&colecao=&ordenacao=` |
| `titulo_acervo(c, titulo_id: int, *, titulo=None, autor=None, assunto=None, editora=None, ano_inicio=None, ano_fim=None, max_paginas: int=5)` | `AcervoTituloDetalhe` | `GET /v1/publico/biblioteca/acervo/{titulo_id}?titulo=…` (os filtros que acharam o título são obrigatórios na prática) |
| `buscar_artigos(c, *, titulo=None, autor=None, palavras_chave=None, ordenacao: int=1, registros_por_pagina: int=100, max_paginas: int=5)` | `list[AcervoArtigo]` | `GET /v1/publico/biblioteca/artigos` |
| `buscar_aquisicoes(c, *, titulo=None, autor=None, ano: int\|None=None)` | `list[AquisicaoBiblioteca]` | `GET /v1/publico/biblioteca/aquisicoes` |
| `novas_aquisicoes(c, *, desde: date\|None=None, area_cnpq: int\|None=None)` | `NovasAquisicoesBiblioteca` | `GET /v1/publico/biblioteca/novas-aquisicoes` |
| `listar_processos_seletivos(c, *, nivel: str="S")` (S, L, T, I, F) | `list[ProcessoSeletivoResumo]` | `GET /v1/publico/processos-seletivos?nivel=S` |
| `processo_seletivo(c, processo_id: int, *, nivel: str="S", programa_id: int\|None=None)` | `ProcessoSeletivo` | `GET /v1/publico/processos-seletivos/{processo_id}?nivel=S&programa-id=` |
| `listar_acordos_mobilidade(c, *, pais: int\|None=None, instituicao=None, sigla=None, ano_assinatura: int\|None=None, status: int\|None=None)` | `list[AcordoMobilidade]` | `GET /v1/publico/acordos-mobilidade` |
| `listar_programas_pos(c, *, nome=None, id_centro: int\|None=None)` | `list[ProgramaPosResumo]` | `GET /v1/publico/programas-pos?nome=&centro-id=` |
| `programa_pos(c, programa_id: int)` | `ProgramaPos` | `GET /v1/publico/programas-pos/{programa_id}` |
| `programa_pos_areas(c, programa_id: int)` | `list[AreaConcentracaoPos]` | `GET /v1/publico/programas-pos/{programa_id}/areas` |
| `programa_pos_cursos(c, programa_id: int)` | `list[CursoProgramaPos]` | `GET /v1/publico/programas-pos/{programa_id}/cursos` |
| `programa_pos_docentes(c, programa_id: int)` | `list[DocenteProgramaPos]` | `GET /v1/publico/programas-pos/{programa_id}/docentes` |
| `programa_pos_processos_seletivos(c, programa_id: int)` | `list[ProcessoSeletivoProgramaPos]` | `GET /v1/publico/programas-pos/{programa_id}/processos-seletivos` |
| `programa_pos_noticias(c, programa_id: int)` | `list[NoticiaProgramaPos]` | `GET /v1/publico/programas-pos/{programa_id}/noticias` |
| `programa_pos_noticia(c, programa_id: int, noticia_id: int)` | `NoticiaProgramaPosDetalhe` | `GET /v1/publico/programas-pos/{programa_id}/noticias/{noticia_id}` |

Erros: `NaoEncontrado` (título fora da busca, processo fora da lista, programa/notícia inexistente), `SigaaError`
(validação do formulário, nível inválido, busca sem filtro), `NavegacaoInvalida` (formulário/campo sumiu da tela).

Modelos (fundir em `sigaa/models/consultas_publico.py`): `AcervoTitulo, AcervoExemplar, AcervoTituloDetalhe, AcervoArtigo,
AquisicaoBiblioteca, NovaAquisicaoBiblioteca, NovasAquisicoesBiblioteca, ProcessoSeletivoResumo, EtapaProcessoSeletivo,
MembroComissaoProcessoSeletivo, DocumentoProcessoSeletivo, NoticiaProcessoSeletivo, ProcessoSeletivo, AcordoMobilidade,
ProgramaPosResumo, NoticiaProgramaPos, NoticiaProgramaPosDetalhe, ProcessoSeletivoProgramaPos, CoordenadorProgramaPos,
ApresentacaoProgramaPos, ProgramaPos, LinhaPesquisaPos, AreaConcentracaoPos, CursoProgramaPos, DocenteProgramaPos`.
Parsers (fundir em `sigaa/parsers/consultas_publico.py`): todos os `parse_*` + `mensagem_erro_publico`; helpers privados `_ex1_*`
(services usam `_ex1s_*`).

### Frente extras2

Prefixo sugerido `/v1/publico`. Todos sem login; listas devolvem `[]` quando o SIGAA diz "nada encontrado".

| função | rota sugerida |
|---|---|
| `async def buscar_projetos_pesquisa(c: SigaaClient, *, titulo: str \| None = None, objetivos: str \| None = None, pesquisador: str \| None = None, ano: int \| None = None, centro_id: int \| None = None, departamento_id: int \| None = None, area_id: int \| None = None, agencia_id: int \| None = None) -> list[ProjetoPesquisaResumo]` | `GET /v1/publico/pesquisa/projetos` |
| `async def obter_projeto_pesquisa(c: SigaaClient, projeto_id: int, *, titulo: str \| None = None, pesquisador: str \| None = None, ano: int \| None = None, centro_id: int \| None = None) -> ProjetoPesquisa` (NaoEncontrado se o id não está na lista dos filtros) | `GET /v1/publico/pesquisa/projetos/{projeto_id}?ano=&titulo=` |
| `async def buscar_bases_pesquisa(c: SigaaClient, *, nome: str \| None = None, coordenador: str \| None = None) -> list[BasePesquisa]` | `GET /v1/publico/pesquisa/bases` |
| `async def buscar_bolsistas_pesquisa(c: SigaaClient, *, discente: str \| None = None, orientador: str \| None = None, modalidade_id: int \| None = None, centro_id: int \| None = None, curso_id: int \| None = None) -> list[BolsistaPesquisa]` (SigaaError na UFBA: parâmetro não configurado) | `GET /v1/publico/pesquisa/bolsistas` |
| `async def buscar_laboratorios(c: SigaaClient, *, nome: str \| None = None, ano: int \| None = None, tipo_id: int \| None = None, servidor: str \| None = None, em_atividade: bool \| None = None, presta_servicos: bool \| None = None, servico: str \| None = None) -> list[LaboratorioPesquisaResumo]` | `GET /v1/publico/pesquisa/laboratorios` |
| `async def obter_laboratorio(c: SigaaClient, laboratorio_id: int, *, nome: str \| None = None, ano: int \| None = None, tipo_id: int \| None = None) -> LaboratorioPesquisa` | `GET /v1/publico/pesquisa/laboratorios/{laboratorio_id}?nome=` |
| `async def buscar_acoes_extensao(c: SigaaClient, *, tipo_id: int \| None = None, titulo: str \| None = None, unidade_id: int \| None = None, ano: int \| None = None) -> list[AcaoExtensaoResumo]` | `GET /v1/publico/extensao/acoes` (atalhos: `/programas` tipo 1, `/projetos` 2, `/cursos` 3, `/eventos` 4, `/produtos` 6) |
| `async def obter_acao_extensao(c: SigaaClient, acao_id: int, *, tipo_id: int \| None = None, titulo: str \| None = None, ano: int \| None = None) -> AcaoExtensao` (sem filtros = GET bookmarkable) | `GET /v1/publico/extensao/acoes/{acao_id}` |
| `async def listar_inscricoes_extensao(c: SigaaClient, *, titulo: str \| None = None, tipo_id: int \| None = None) -> list[InscricaoExtensaoAberta]` | `GET /v1/publico/extensao/inscricoes-abertas` |
| `async def listar_centros_cursos_abertos(c: SigaaClient) -> list[CentroCursoAberto]` | `GET /v1/publico/cursos-abertos/centros` |
| `async def listar_departamentos_cursos_abertos(c: SigaaClient, centro_id: int) -> list[DepartamentoCursoAberto]` | `GET /v1/publico/cursos-abertos/centros/{centro_id}/departamentos` |
| `async def buscar_cursos_abertos(c: SigaaClient, *, palavra_chave: str \| None = None, centro_id: int \| None = None, departamento_id: int \| None = None) -> list[CursoAbertoTurma]` (`departamento_id` exige `centro_id`) | `GET /v1/publico/cursos-abertos` |
| `async def obter_curso_aberto(c: SigaaClient, turma_id: int, *, palavra_chave: str \| None = None) -> CursoAberto` | `GET /v1/publico/cursos-abertos/{turma_id}` |

Parser auxiliar exportado: `mensagens_publico(html) -> list[str]` (mensagens do `#painel-erros`).
Modelos (para fundir em `sigaa/models/consultas_publico.py`): `MembroEquipePublica`, `ProjetoPesquisaResumo`, `ProjetoPesquisa`,
`BasePesquisa`, `BolsistaPesquisa`, `LaboratorioPesquisaResumo`, `LaboratorioPesquisa`, `AcaoExtensaoResumo`, `AcaoExtensao`,
`MiniAtividadeExtensao`, `InscricaoExtensaoAberta`, `DepartamentoCursoAberto`, `CentroCursoAberto`, `CursoAbertoTurma`,
`DocenteCursoAberto`, `MaterialCursoAberto`, `TopicoCursoAberto`, `CursoAberto`.
Helpers privados com prefixo `_ex2_` (parsers e services).
