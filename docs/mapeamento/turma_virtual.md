# Mapeamento — Turma Virtual (AVA)

Frente `turma_virtual`. Código: `sigaa/models|parsers|services/turma_virtual.py`, `api/routes/turma_virtual.py`,
`tests/test_turma_virtual.py` (+ `tests/fixtures/turma_virtual/`, anonimizadas por `recon/tv_anonimizar.py`).
Validação ponta a ponta: `recon/turma_virtual_e2e.py`. Recon cru (gitignored): `recon/tv_crawl.py`, `recon/tv_detail*.py`,
páginas em `recon/pages/turma_virtual/<turma>/NN_<item>.html` (37 turmas × 20 itens) e `.../_detalhe/`.

SIGAA UFBA v4.13.8. Tudo aqui é **leitura**. Botões que NÃO podem ser clicados pela API: "Seguir tópico"
(`form:seguirTopico`), "Alterar" nome do grupo, Gerenciar Perfil, enviar tarefa, responder questionário/enquete,
postar/responder no fórum.

---

## 1. Identificadores e como entrar numa turma

| id | onde aparece | estável? |
|---|---|---|
| `idTurma` (numérico, ex. 393420) | portal (`formAtualizacoesTurmas` — só turma com novidade), comprovante de matrícula, **mobile** (todas) | sim |
| `frontEndIdTurma` (hash 40 hex) | portal `form_acessarTurmaVirtual*`, `turmas.jsf`, "Trocar de Turma" | sim (igual entre logins; testado em 2 sessões) |

O desktop só abre a turma virtual com `frontEndIdTurma`. A API expõe `turma_id = idTurma` (contrato com a frente portal)
e casa os dois assim:

1. `GET /sigaa/portais/discente/turmas.jsf` → "Todas as Turmas Virtuais (N)": linhas agrupadas por período
   (`<td>2026.2</td>`), cada uma com código - nome, turma, CH, horário `46N12 (19/08/2026 - 19/12/2026)` e o link
   jsfcljs `{'frontEndIdTurma':..., 'inciadoPelaBusca':'true', 'paginaListaTurmasOrigem':'/portais/discente/turmas.jsp'}`.
2. Versão **mobile**, com a MESMA sessão do desktop:
   `GET /sigaa/mobile/touch/menu.jsf` → clique `form-portal-discente:lnkMinhasTurmas` → (turmas do semestre)
   → clique `form-turmas-discente:lnkVerTodas` → `/sigaa/mobile/touch/ava/turmas_discente.jsf` com TODAS as turmas:
   `<li data-role="list-divider">2026.2 - GRADUAÇÃO</li>` + `<a ... {'form-turmas-discente:cmdEntrarTurma…','idTurma':'393420','msgSwipe':'true'}>`
   com `CÓDIGO - NOME`, `<small>Local: …</small>`, `<small>Horário: 46N12 (19/08/2026 - 19/12/2026)</small>`.
3. Casamento por (período, código, horário-com-datas sem espaços); cai pra (período, código) quando único.
   Resultado real: 37/37 turmas casadas (MATD04 aparece 3× em semestres diferentes — o horário com datas desempata).
4. Abrir: POST do link `frontEndIdTurma` de `turmas.jsf` (serve pro semestre atual e anteriores) →
   `/sigaa/ava/index.jsf` (página principal). Fallback: o mesmo link no portal.

`abrir_turma(c, turma_id)` faz 1→4 e guarda o mapa idTurma↔frontEndIdTurma em `c._tv_mapa` (dado estável, não é
estado de tela). Cada chamada de serviço recomeça de `turmas.jsf` (2 requisições pra entrar + 1 por tela), então as
rotas podem ser chamadas em qualquer ordem. Abrir outra turma troca o estado JSF da sessão (o bean da turma virtual é
um só por sessão) — por isso nunca reaproveitamos uma página de turma entre chamadas.

O `turma_id` das rotas também aceita o `frontEndIdTurma` (40 hex).

---

## 2. Página principal — `/sigaa/ava/index.jsf`

Layout em 3 colunas: `#barraEsquerda` (menu), `#conteudo` (centro), `#barraDireita` (quadros).

- **Cabeçalho**: `#linkCodigoTurma` ("MATC89 - "), `#linkNomeTurma`, `#linkPeriodoTurma` ("- T01 (2026.2)"); o
  `title` traz o horário.
- **Trocar de Turma**: `form#formTurma` com `a.linkTurma` (só as turmas do semestre): "CÓDIGO - NOME (60h) (2026.2)".
- **Última Notícia**: `#ultimaNoticia h4` ("Título - dd/mm/aaaa HH:MM"), `.conteudoNoticia`, "Cadastrado por: <i>".
- **Tópicos de aula**: `div.topico-aula` → `div.titulo` ("Título (dd/mm/aaaa - dd/mm/aaaa)") + `div.conteudotopico`
  com o texto do docente e `div.item` (materiais). Cada item: ícone `/sigaa/img/porta_arquivos/icones/<x>.png`
  (pdf.png, conteudo.png, ...) + link jsfcljs do `formAva` + `div.descricao-item`.
  - conteúdo: `{'…idMostrarMaterialConteudo', 'id':'6371183'}` (id numérico = o do menu Conteúdo).
  - arquivo: `{'…:j_id_…_378', 'id':'<HASH 40 hex>', 'key':'<md5>'}` com target `_blank` → POST devolve o binário.
    O hash NÃO é o id do menu Arquivos (lá é numérico) — exposto como `id_hash`.
- **Turma sem tópicos**: texto "Turma Virtual! Ampliando os horizontes… O Sistema detectou que até agora seu professor
  não criou nenhum tópico de aula" → `sem_topicos=true`. Algumas turmas mostram só "Ementa: (datas) texto".
- **Quadros da direita** (`.rich-stglpanel` com `.headerBloco`): "Andamento das Aulas" (Aulas (Ministradas/Total): 36 / 72,
  50% da CH), "Notícias" (5 últimas, cada uma num form com `<input name="id">` + "(Visualizar)"), "Enquete",
  "Atividades" (dd/mm + "Nova Notícia: …", "Avaliação marcada para…"), "Avaliações" (dd/mm HH:MM + descrição),
  "Mensagens dos Fóruns" (prévia das últimas mensagens).
- Botões do topo (`formAcoesTurma`): Menu Discente, Imprimir (PrimeFaces AJAX), "Visualizar aulas paginadas"
  (`linkExibirPaginados` `paginados=true`), Trocar de Turma (abre `dialogTurmas`).
- AJAX a4j na principal: `formAva:bExibirTopico` (A4J.AJAX.Submit — exibe um tópico), drag-and-drop de materiais
  (só docente). O gravador do nó web (`gravar ligar` + `mapa resumo`) mostrou que a navegação do aluno é toda POST
  "cheio" (não a4j): `POST /sigaa/ava/index.jsf` e `POST /sigaa/ava/<Tela>/<acao>.jsf` com `formMenu`,
  `formMenu:j_id_jsp_…_72`, `javax.faces.ViewState` + o id do item clicado.

### Menu lateral (`form#formMenu`, rich:panelBar)

Os ids `formMenu:j_id_jsp_<N>_<M>` MUDAM de tela pra tela (o N é por JSP) — o serviço clica pelo TEXTO.

| grupo | item | tela (action do form) | serviço / rota |
|---|---|---|---|
| Turma | Principal | `/ava/index.jsf` | `turma` · `GET /v1/turmas/{id}` |
| Turma | Gerenciar Perfil | (edição — não usado) | — |
| Turma | Plano de Curso | `/ava/PlanoCurso/visualizar.jsf` | `plano_curso` · `/plano-de-curso` |
| Turma | Participantes | `/ava/participantes.jsf` | `participantes` · `/participantes`, `/docentes` |
| Turma | Visualizar Programa | (programa do componente) | `programa` · `/programa` |
| Turma | Fóruns | `/ava/ForumTurma/lista.jsf` | `foruns` · `/forum` |
| Turma | Notícias | `/ava/NoticiaTurma/listar.jsf` | `noticias` · `/noticias` |
| Alunos | Frequência | `/ava/FrequenciaAluno/mapa.jsf` | `frequencia` · `/frequencia` |
| Alunos | Ver Grupo | `/ava/GrupoDiscentes/ver_grupo.jsf` | `grupo` · `/grupo` |
| Alunos | Ver Notas | relatório (página sem menu) | `notas` · `/notas` |
| Materiais | Conteúdo/Página web | `/ava/ConteudoTurma/listar.jsf` | `conteudos` · `/conteudos` |
| Materiais | Referências | `/ava/IndicacaoReferencia/listar.jsf` | `referencias` · `/referencias` |
| Materiais | Vídeos | (lista) | `videos` · `/videos` |
| Materiais | Arquivos | `/ava/ArquivoTurma/listar_discente.jsf` | `arquivos` · `/arquivos` |
| Atividades | Avaliações | `/ava/DataAvaliacao/listar.jsf` | `avaliacoes` · `/avaliacoes` |
| Atividades | Enquetes | (lista) | `enquetes` · `/enquetes` |
| Atividades | Tarefas | (lista) | `tarefas` · `/tarefas` |
| Atividades | Questionários | (lista) | `questionarios` · `/questionarios` |
| Estatística | Situação dos Discentes | `/ava/estatisticas.jsf` | `estatisticas` · `/estatisticas` (+ `/grafico` PNG) |
| Estatística | Linha do Tempo | `/ava/Relatorios/timeline.jsf` | `linha_tempo` · `/linha-do-tempo` |
| Ajuda | Manual da Turma Virtual | target `_BLANK` (manual) | — |

Mensagens do SIGAA ficam em `#painel-erros ul.erros|warning|info li` (função `mensagens()`); quando um item "não tem
nada" o SIGAA às vezes fica NA TELA ANTERIOR com a mensagem (Visualizar Programa, Ver Notas).

---

## 3. Cada tela

Listas usam `table.listing` (thead com rótulos); o parser lê pelo texto do `th`. Vazio = `p.empty-listing`
("Nenhum item foi encontrado", "Nenhum fórum foi encontrado.").

### Notícias
Lista: colunas Título | Data | (lupa jsfcljs `'id':'6729370'`). Detalhe (clique na lupa) → `/ava/NoticiaTurma/mostrar.jsf`:
`ul.form li label "Título:" / "Data:" + span`, `th "Texto:" td.conteudoNoticia`, `<input name="id">`.

### Participantes
`legend "Docentes (n)"` / `"Discentes (n)"` + `table.participantes`. Docente: foto `/shared/verFoto?idFoto=..&key=..`,
`<strong><a href="/sigaa/public/RedirectDocente?login=…">NOME</a>`, "Departamento: <em>", "Formação: <em>", "E-Mail: <em>".
Discente: 2 por linha, "Curso:", "Matrícula:", "E-mail:", ícone `online.png/offline.png`. O "(Perfil)" de cada aluno é
a4j (`A4J.AJAX.Submit` + `bVisualizarPerfil`) — não implementado (perfil de colega).
Há comentários HTML entre os rótulos (REDMINE #41513) — o parser ignora `Comment`.

### Plano de Curso
`table.listagem caption "Metodologia de Ensino e Avaliação"` com th/td (Metodologia, Procedimentos de Avaliação da
Aprendizagem, Horário de atendimento); link "Programa atual do componente" `{'idComponente':'45094'}` (com
`idComponente` vazio quando não há); `#listaTopicosAula` (Início | Fim | Descrição); `#listaAvaliacoes` (Data | Descrição);
`caption "Referências Básicas"/"Referências Complementares"` (Tipo de material | Descrição; ícone `destaque.png` =
consta na biblioteca).

### Visualizar Programa
Em TODAS as 37 turmas testadas: "O componente curricular X não possui um programa cadastrado." (fica na tela anterior).
O parser lê th/td genericamente (ementa, objetivos, conteúdo, competências, metodologia, avaliação, referências) para
quando existir — **variação não vista ao vivo**.

### Conteúdo / Página web
Lista: Titulo | Criado em | lupa `'id'`. Detalhe `/ava/ConteudoTurma/mostrar.jsf`: `table.formAva` (Título:, Conteúdo: HTML,
Data Cadastro:).

### Referências
Lista: Nome | Tipo | URL (`<a target=_blank>`) | Tópico de Aula | lupa. Detalhe `/ava/IndicacaoReferencia/mostrar.jsf`:
Descrição, Tipo, Autor, Ano, URL (vem `http://` vazio quando não há), Detalhes.

### Arquivos
Lista `listar_discente.jsf`: Título | Descrição | Tópico de Aula | ícone "Baixar Arquivo" `{'id':'2542120','key':'…'}`.
O POST do link devolve o binário: `application/pdf`, `Content-Disposition: attachment; filename="…"`.
"Baixar todos os arquivos" (zip) não implementado. Arquivos de tópico (hash) também baixam pela mesma rota.

### Avaliações
Lista: Data | Hora | Descrição | lupa. Detalhe `/ava/DataAvaliacao/mostrar.jsf`: Descrição, Data da Avaliação, Hora.

### Fóruns
Lista `/ava/ForumTurma/lista.jsf`, `fieldset "Fóruns da Turma"`: Título (link + `<br/>` + `[<b>Aula: </b><i>…</i>]` +
descrição) | Tipo | Tópicos (link) | Autor(a) | Criado em | Início | Fim. Os links **não têm id** (`form:btnViewForum`,
`form:btnViewForumj_id_1`…) → a API usa a POSIÇÃO (1..n).
Fórum `/ava/Foruns/view.jsf`: `table.formAva` (Título, Descrição, Autor(a), Arquivo, Monitorar Leitura, Tipo, Ordenação
Padrão, Tópico de Aula, Criado em, Início, Fim) + tabela de tópicos: Mensagem (`form:btnView…`) | Autor(a) | Respostas |
Última Mensagem (autor + dd/mm/aaaa HH:MM:SS).
Tópico `/ava/Foruns/Mensagem/view.jsf`: select `form:ordem` (3 lista, 4 aninhadas, 1 antigas, 2 recentes — muda via
submit; não usamos), `table.formAva` (Assunto, Mensagem, Autor(a), Arquivo, Criado em) e cada resposta em
`span#form:comConteudo…` (`<b>título</b>`, "por AUTOR", `<i>dd/mm/aaaa HH:MM:SS</i>`, `td.conteudoMensagemForum`,
"Ver Arquivo Anexo" `{'form:verArquivoResposta…','idArquivo':'2672347'}` → POST devolve o PDF).
**Pegadinha**: essa página tem um `<form id="form:paginacaoForm">` ANINHADO dentro de `form`. O lxml fecha o form externo
ali e perde o `javax.faces.ViewState` — o POST sem ViewState volta a própria página. O `Page.form()` do cliente detecta
o form sem ViewState e relê com `html.parser`. O navegador manda:
`form, form:ordem, form:showModalOpenedState, form:paginacaoForm, form:paginacaoForm:j_id_jsp_…_350=0, javax.faces.ViewState, form:verArquivoResposta, idArquivo`.

### Ver Notas
Página de relatório (`#relatorio-cabecalho`, sem menu). `h3 "MATB19 - NOME (60h) - Turma: 01 (2026.1)"`,
`table.tabelaRelatorio caption "Alunos Matriculados"`: 1ª linha do thead = Matrícula | Nome | `Unid. 1` (colspan=n) |
Reposição | Resultado | Faltas | Sit.; 2ª linha (`#trAval`, só quando o docente detalhou) = as avaliações da unidade
(`th#aval_<id>` com a abreviação + `input#denAval_<id>` nome, `#pesoAval_<id>` peso) e "Nota". Só a linha do próprio aluno.
Variações vistas: 1 unidade sem detalhe (APR 9,0), 1 unidade com 3–4 avaliações + pesos. Sem notas: fica na tela anterior
com "Ainda não foram lançadas notas.".

### Frequência
`/ava/FrequenciaAluno/mapa.jsf`: texto das regras (75% da CH, aula de 55 min), `table.listing` Data | Situação
("Presente", "2 Falta(s)", "Não Registrada"), e o rodapé: Presenças Registradas, Número de Aulas com Registro de
Frequência, % em relação às aulas com registro, Número de Aulas definidas pela CH, % em relação à CH.
**Pegadinha**: com "A frequência ainda não foi lançada." o SIGAA imprime totais de lixo (sempre 59/59/100%) —
o parser marca `lancada=false` e zera os totais. A API calcula `max_faltas = aulas_ch × (1 − 75%)` e `faltas_restantes`.

### Linha do Tempo
`/ava/Relatorios/timeline.jsf`: filtro de datas (`formAva:Inicio`/`formAva:Fim` + "Filtrar" — não usado) e
`.box-conversation` em 2 colunas: autor (`strong`), "Nova Notícia cadastrada: Título", `Data: dd/mm/aa H:MM`, `.content`.

### Ver Grupo
`p.empty-listing "Caro aluno, você ainda não foi cadastrado em nenhum grupo."` (todas as turmas). Há um painel
"ALTERAR NOME DO GRUPO" (a4j `formAva:j_id_…_307`) — NÃO usar.

### Situação dos Discentes (Estatísticas)
Só um gráfico cewolf: `<img src="/sigaa/cewolf;jsessionid=…?img=…&width=650&height=400&iehack=.png">` (PNG, ~35 KB,
vale só na sessão). Rota `/estatisticas/grafico` devolve o PNG.

### Tarefas, Questionários, Enquetes, Vídeos
"Nenhum item foi encontrado" em TODAS as 37 turmas (professores da UFBA praticamente não usam). Os parsers seguem o
layout `table.listing` do SIGAA e procuram por rótulo (título/período/início/fim/prazo/enviada/nota/situação),
juntando a 2ª linha de descrição das tarefas — **não validados com dado real**.

---

## 4. Endpoints implementados (35)

Todos `GET`, 🔒 Bearer. `{id}` = idTurma (ou frontEndIdTurma).

| rota | devolve |
|---|---|
| `/v1/turmas-virtuais` | `TurmaVirtualResumo[]`: todas as turmas virtuais com turma_id, front_end_id, código, turma, período, CH, horário, local, atual |
| `/v1/turmas/{id}` | `TurmaVirtual`: principal completa |
| `/v1/turmas/{id}/aulas` | `TopicoAula[]` (datas, texto, links, materiais) |
| `/v1/turmas/{id}/noticias` · `/noticias/{noticia_id}` | `Noticia[]` · `Noticia` com texto |
| `/v1/turmas/{id}/participantes` · `/docentes` | `Participantes` · `Participante[]` |
| `/v1/turmas/{id}/plano-de-curso` | `PlanoCurso` |
| `/v1/turmas/{id}/programa` | `ProgramaComponente` |
| `/v1/turmas/{id}/conteudos` · `/conteudos/{conteudo_id}` | `ConteudoTurma[]` · `ConteudoTurma` com texto |
| `/v1/turmas/{id}/referencias` · `/referencias/{referencia_id}` | `ReferenciaTurma[]` · detalhe (autor, ano) |
| `/v1/turmas/{id}/videos` | `Video[]` |
| `/v1/turmas/{id}/arquivos` · `/arquivos/{arquivo_id}` | `Arquivo[]` · binário (id numérico ou id_hash) |
| `/v1/turmas/{id}/tarefas` · `/questionarios` · `/enquetes` | `Tarefa[]` · `Questionario[]` · `Enquete[]` |
| `/v1/turmas/{id}/avaliacoes` · `/avaliacoes/{avaliacao_id}` | `Avaliacao[]` · `Avaliacao` |
| `/v1/turmas/{id}/forum` · `/forum/{forum_id}` | `ForumTurma[]` · `ForumDetalhe` (dados + tópicos) |
| `/v1/turmas/{id}/forum/{forum_id}/topicos/{topico_id}` | `TopicoForumDetalhe` (mensagem + respostas + anexo_id) |
| `/v1/turmas/{id}/forum/{f}/topicos/{t}/anexos/{anexo_id}` | binário do anexo |
| `/v1/turmas/{id}/notas` | `NotasTurma` (unidades com avaliações/pesos, reposição, resultado, faltas, situação) |
| `/v1/turmas/{id}/frequencia` | `Frequencia` (por aula + totais + faltas restantes) |
| `/v1/turmas/{id}/linha-do-tempo` · `/grupo` · `/estatisticas` · `/estatisticas/grafico` | eventos · grupo · estatísticas · PNG |
| `/v1/notas?periodo=` | `NotasTurma[]` de todas as turmas do semestre (ou do período) |
| `/v1/frequencia?periodo=` | `FrequenciaResumo[]` |
| `/v1/tarefas?encerradas=` | `TarefaPendente[]` (não enviadas, ordenadas pelo prazo) |
| `/v1/avaliacoes?periodo=` | `AvaliacaoAgendada[]` (calendário de provas) |

Custo: entrar na turma = 2 requisições (+4 na 1ª vez pro mapa de ids); cada tela +1; detalhe +1. Agregadas ≈ 3 por turma.

## 5. Resultado do e2e (SIGAA real, `recon/turma_virtual_e2e.py`, 19/10/2026)

```
listar_turmas: 37 turmas, 37 com turma_id, atuais=[MATC89, MATC72, ADMF01]
turma MATC89: andamento 36/72 (50%), 1 tópico, menu 21 itens · aulas MATA07: 30 tópicos, 29 materiais
noticias 12 + detalhe · participantes 1+48 · plano MATC72: cronograma 28, 1 avaliação · programa: indisponível
conteudos 3 + detalhe · referencias + detalhe (autor/ano) · arquivos MATB19: 13; download PDF 177 KB (id) e 109 KB (hash)
avaliacoes 3 + detalhe · foruns MATB19: 2; fórum 1: 2 tópicos; tópico 2/1: 17 respostas, 17 anexos; anexo PDF 6,5 MB
notas MATB19: Unid.1 6,0 = Sem 9,5 (peso 20) · P1 3,5 (25) · P2 1,0 (25) · Jude 10,0 (30) → APR
frequencia MATC89: 18 aulas, 6 faltas, 81% da CH, 10 faltas restantes · grafico PNG 35 KB
agregadas: notas/frequência/tarefas/avaliações do semestre; notas 2026.1 = 5 turmas APR
```

## 6. Variações não cobertas / fora

- Tarefas, questionários, enquetes, vídeos e programa do componente: nenhuma turma do aluno de teste tinha → parsers
  por rótulo, sem validação real. Detalhe de tarefa/questionário (enunciado, arquivo enviado, correção) não implementado.
- Fórum: ids por posição (o SIGAA não mostra id ao aluno); paginação de tópicos (`form:paginacaoForm`) e respostas
  aninhadas além de 1 nível não testadas (a ordem "aninhadas" vem como lista plana).
- "Baixar todos os arquivos" (zip), "Visualizar aulas paginadas", perfil de colega (a4j), chat, manual.
- Turma com mais de uma unidade (Unid. 2/3) não apareceu — o parser trata qualquer `Unid. N` com ou sem colspan.
- Turmas de outros níveis (pós, técnico) e turmas com subturmas/docentes múltiplos não testadas.
- Downloads: o nome vem do `Content-Disposition` (`Page.nome_arquivo`). O SIGAA manda nomes com acento decomposto
  estragado (`Regulac807a771o` = "Regulação": letra + código decimal do caractere combinante) — `_consertar_nome` recompõe.
  O form aninhado do tópico do fórum é resolvido pelo `Page.form()` do cliente (cai pro html.parser).
