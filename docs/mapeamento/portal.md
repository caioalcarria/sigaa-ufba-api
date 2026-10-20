# Mapeamento — frente `portal` (Portal do Discente)

SIGAA UFBA v4.13.8. Todas as telas abaixo são de **consulta**. Duas são telas de **edição**
(Meus Dados Pessoais e perfil.jsf): a API abre e LÊ, nunca submete. Arquivos da frente:
`sigaa/models/portal.py`, `sigaa/parsers/portal.py`, `sigaa/services/portal.py`,
`sigaa/util/horario.py`, `api/routes/portal.py`, `tests/test_portal.py` (+ `tests/fixtures/portal/`),
`recon/portal_e2e.py` (E2E contra o SIGAA real).

> ⚠️ Lição aprendida: `GET /sigaa/mobile/touch/portal_discente.jsf` (URL chutada) gera
> **Comportamento Inesperado** (JasperException, e-mail pra STI). Só use URLs que o próprio sistema
> gera. As URLs "diretas" abaixo foram todas vistas como `href` em alguma tela.

---

## 1. Página inicial — `/sigaa/verPortalDiscente.do`

**Como chegar:** `GET /sigaa/verPortalDiscente.do` (redireciona pra `/sigaa/portais/discente/discente.jsf`).
`SigaaClient.portal()` já faz isso.

**O que tem (por id/rótulo):**

| bloco | onde no HTML | dado |
|---|---|---|
| cabeçalho | `p.periodo-atual strong` | semestre atual (`2026.2`) |
| | `#info-usuario p.usuario span[title]` | nome abreviado |
| | `#info-usuario p.unidade` | unidade + código (`INSTITUTO DE COMPUTAÇÃO (12.28)`) |
| menu JSCook | `form#menu:form_menu_discente input[name=id]` | **id interno do discente** |
| perfil | `#perfil-docente .foto img[src*=verFoto]` | foto (`/shared/verFoto?idFoto=..&key=..`) |
| | `p.info-docente span.nome` | nome completo |
| Dados Institucionais | `div#agenda-docente` cujo `h4` = "Dados Institucionais" — tabela `td rótulo: / td valor` | Matrícula, Curso, Nível, Status, E-Mail (**cortado com "..."**), Entrada |
| Integralizações | tabela aninhada `CH. Obrigatória Pendente / Optativa / Total Currículo / Complementar` + `div style="width: 55.83%"` + "56% Integralizado" | CH em horas e % (com decimais pela barra) |
| notícias | `#noticias-portal` (`p.noticia`; vazio = "Não há notícias cadastradas.") | `PainelNoticias.init('/sigaa/portais/docente/viewNoticia.jsf')` abre cada notícia |
| Últimas Atualizações | `form#formAtualizacoesTurmas` → cada `table` = data + link (jsfcljs com **`idTurma`**) + texto "Nova Notícia: ..." | rotador puro JS (sem AJAX) |
| Turmas do Semestre | `#turmas-portal table` (Componente, Local, Horário); link com `frontEndIdTurma`; **a linha seguinte tem `<td id="linha_<idTurma>">`** → mapeamento frontEndIdTurma↔idTurma | local, horário |
| Ver turmas anteriores | `a[href=/sigaa/portais/discente/turmas.jsf]` | |
| Comunidades Virtuais | `#participantes` (oculto; `p.vazio`) | |
| Minhas atividades | `form#formAtividades #avaliacao-portal` (vazio = `p.vazio` "Não há atividades cadastradas para os próximos 15 dias ou decorridos 7 dias.") | parser tolerante: qualquer `tr` com data |
| Fórum de Cursos | `#forum-portal` — links `...:listarTopicosForum` (**só leitura**) e `...:novoTopicoForum` (**NUNCA**) | prévia ("Nenhum item foi encontrado") |
| rodapé | `#rodape` | versão `v4.13.8_41_hotfix` |

**AJAX:** nenhum a4j nesta tela (o letreiro de atualizações é JS local).

## 2. Todas as turmas — `/sigaa/portais/discente/turmas.jsf`

**Como chegar:** depois do portal, `GET /sigaa/portais/discente/turmas.jsf` (é o `href` de "Ver turmas anteriores").

**O que tem:** `table.listagem` "Todas as Turmas Virtuais (N)": linhas `td.periodo` (2026.2...) + linhas
Disciplina (`MATC89 - NOME`), Turma (`01`), CH Total (`60h`), Horário (`46N12 (19/08/2026 - 19/12/2026)`)
e um link "Acessar Turma Virtual" com **só `frontEndIdTurma`** (hash SHA-1-like de 40 hex; estável entre
logins, mas não é derivável do idTurma — testado sha1/md5/sha256 do id, não bate).
**Não tem** idTurma numérico nem local.

## 3. Interface mobile — `/sigaa/mobile/touch/` ⭐ (fonte do idTurma de TODAS as turmas)

Avaliação: é bem mais leve (jQuery Mobile, ~8–40 KB) e **compartilha a sessão do portal clássico**
(o mesmo JSESSIONID: depois do login clássico, `GET /sigaa/mobile/touch/menu.jsf` já abre logado).
Usar o mobile **não** estraga o estado do portal clássico (verificado no E2E).

* `GET /sigaa/mobile/touch/` → `public/principal.jsf` (área pública: Calendário, Cursos, Componentes,
  Docentes, Autenticação de Documentos, Serviços Digitais, link "Entrar").
* Login próprio (se precisar): "Entrar" → `form-login` em `/sigaa/mobile/touch/login.jsf`.
* **Logado:** `GET /sigaa/mobile/touch/menu.jsf` → `form-portal-discente` com: `lnkMinhasTurmas`,
  `lnkMinhasNotas` (abre em `_blank`), `lnkAtestadoMatricula`, `lnkAtestadoMatriculaSuplementar`,
  `lnkConsultarHistorico`, `lnkSair` (**nunca**).
* `lnkMinhasTurmas` → `menu.jsf` "Turmas do Discente" (semestre atual) com links
  `form-turmas-discente:cmdEntrarTurma*` **`'idTurma':'393420'`** + `lnkVerTodas`.
* `lnkVerTodas` → `/sigaa/mobile/touch/ava/turmas_discente.jsf`: TODAS as turmas, agrupadas por
  `li[data-role=list-divider]` "2026.2 - GRADUAÇÃO", cada uma com `idTurma`, `MATC89 - NOME`,
  `<small>Local: ...</small>` (detalhado: "PAF 1 - 021 - Terça Horários 18:30 às 19:25...") e
  `<small>Horário: ...</small>`.
* `cmdEntrarTurma` (idTurma) abre a turma virtual mobile — validado: `idTurma=19186` = MATA60 (2025.2).
  Obs.: as turmas de 2025.2 têm idTurma "pequeno" (17047, 18275, 19186) — são válidos.

**Junção (serviço `turmas`)**: turmas.jsf (código/turma/CH/frontEndId) + mobile (idTurma/local/nível) +
portal (idTurma↔frontEndId das atuais), casando por idTurma → frontEndIdTurma → (período, código, turma)
→ (período, nome). Resultado: 37/37 turmas do autor com `turma_id`.

## 4. Meus Dados Pessoais — `/sigaa/graduacao/discente/dados_discente.jsf` (EDIÇÃO → só leitura)

**Como chegar:** portal → commandLink `j_id_jsp_..._349:meusDadosPessoais` (texto "Meus Dados Pessoais").
`c.clicar(portal, "meusDadosPessoais")`.

**O que tem:** `form#formDiscente table.formulario` com seções `td.subFormulario`:
Dados do discente (Matrícula, Nome, Curso, Sexo, Estado civil, Data de nascimento, Naturalidade, Raça,
Tipo Sanguíneo, Nacionalidade, País, Escola/Tipo/Ano de conclusão do Ensino Médio, Tipos de NEE, Nome do
pai/mãe) · Documentos (CPF, RG + órgão/UF, Data de Expedição, Título de Eleitor com `<b>Zona:</b>`,
`<b>UF:</b>` **embutidos no mesmo td**, Certificado Militar, Série, Categoria, Órgão) · Endereço (inputs
`formDiscente:endCEP`, `selectTipoLogradouro`, `txtLogradouro`, `txtNumero`, `txtComplemento`, `txtBairro`,
`selectUF`, `selectMunicipio`) · Contatos (`telFixoDDD`+`txtTelefone`, `telCelDDD`+`txtCelular`, `txtEmail`
= e-mail pessoal **completo**) · Dados bancários (`formDiscente:banco`) · Situação sócio-econômica (renda,
membros, zona de residência, transporte — radios) · Confirmação de senha (**ignorada**).
Hidden `formDiscente:j_id_..._377` = id do discente.
**AJAX** (não disparado pela API): `selectUF` onchange a4j (recarrega municípios), `banco` a4j suggestion,
`ConsultadorCep`.

## 5. Perfil — `/sigaa/portais/discente/perfil.jsf` (EDIÇÃO → só leitura)

**Como chegar:** portal → link `a.perfil href="perfil.jsf"` ("Atualizar Foto e Perfil").
**O que tem:** foto (`img#fotoPerfil`), `textarea#descricaoPessoal`, `textarea#areasInteresse`,
`input#curriculoLattes`, assinatura da caixa postal (`textarea[title^=Assinatura]`). Links proibidos:
`btnExcluirFoto`, "Gravar perfil".
**Foto:** `GET /shared/verFoto?idFoto=..&key=..` (com a sessão) devolve `image/jpeg`.

## 6. Fórum do curso — `/sigaa/graduacao/ForumCurso/listar.jsf`

**Como chegar:** portal → `j_id_jsp_..._421:listarTopicosForum` ("Visualizar todos os tópicos para este
fórum"). O botão-imagem `form_links:forumCursos` (input type=image, "portal de cursos") leva à MESMA tela.
**O que tem:** `form#listagem`, h2 "FÓRUM DO CURSO DE SISTEMAS DE INFORMAÇÃO", legenda (Cadastrar novo
tópico · Remover · Seguindo/Não seguido — **todos proibidos**), "Nenhum item foi encontrado".
**Variação não vista:** o fórum do autor está **vazio**; o parser de tópicos é genérico (tabela com
cabeçalho Título/Tópico/Assunto, Autor, Respostas, Última postagem; id pelos params `id/idTopico` do
jsfcljs) e o de mensagens do tópico é best-effort.

## 7. Módulos — `/sigaa/verMenuPrincipal.do?dialog=true`

**Como chegar:** cabeçalho "Módulos" (`#show-modulos`) faz `GET /sigaa/verMenuPrincipal.do?dialog=true`
(visto no gravador) e mostra `#painel-modulos`. Cada `li` tem classe `<chave> on|off` (ex.:
`graduacao off`, `discente on`, `gerenciador_salas on`, `portal_avaliacao false`); habilitado tem `href`.
Grupos: Módulos · Outros Sistemas (SIPAC/SIGRH/SIGAdmin) · Portais.
Habilitados pro autor: **Gerenciamento de salas** (`/sigaa/verMenuGerenciadorSalas.do`) e Portal do Discente.

### 7.1 Gerenciamento de salas → Relatório de Salas Livres ⭐

* `GET /sigaa/verMenuGerenciadorSalas.do` → `/sigaa/geral/gerenciador_salas/geral.jsf`: "Relatório
  Espaço Físico" com 3 links. **Distribuição de salas** e **Mapa de Salas** = Acesso Negado (papéis
  DISTRIBUIÇÃO SALAS / RESPONSAVEL_RESERVA_ESPACO_FISICO). **Salas Livres = acessível ao aluno.**
* "Relatório de Salas Livres" → `/sigaa/ensino/DistribuicaoTurma/formRelatSalaLivre.jsf`,
  `form#formularioDistribuicao`: `inputAno`, `inputPeriodo`, `selectNivelTurma` (G=graduação...),
  `checkDiaSemana`+`selectDiaSemana` (1=dom..7=sáb), `checkTurno`+`selectTurno` (1 manhã, 2 tarde, 3 noite),
  `checkPredio`+`selectPredio` (46 prédios: PAF 1=31, IC=41...), `checkSala`+`selectSala`.
* **AJAX a4j obrigatório:** o `onchange` do `selectPredio` faz `A4J.AJAX.Submit(... 'parameters':
  {'formularioDistribuicao:j_id_jsp_..._28': ...})` com `AJAXREQUEST` — carrega as salas do prédio no
  servidor. Sem esse POST, "Gerar Relatório" volta pro formulário sem resultado. A API faz: POST AJAX →
  POST com o botão "Gerar Relatório>".
* Resultado: "Relatório de Salas disponiveis por horário" — tabela predio | nome do predio | sala |
  capacidade | dia da semana | inicio | fim | turno (uma linha por sala×slot livre). Vazio: "Nenhuma
  turma foi encontrada com os critérios utilizados". **Sem filtros o SIGAA devolve TODOS os prédios e
  dias (relatório enorme)** → a API exige `predio`.

## 8. Caixa Postal — `/sigaa/abrirCaixaPostal.jsf?sistema=2` ❌ (fora da rede UFBA)

`GET` → **302** pra `https://caixapostal.ufba.br/cxpostal/verCaixadeEntrada.jsf?idUsuario=..&sistema=2&id=..&key=..&passaporte=..`.
`caixapostal.ufba.br` **não existe no DNS público** (nem o navegador abre: `ERR_NAME_NOT_RESOLVED`);
forçar o IP público do SIGAA (200.128.56.76) com esse Host cai num 404 de outro app (Next.js), e o mesmo
caminho em `sigaa.ufba.br/cxpostal/...` dá 404. Conclusão: a caixa postal só funciona dentro da rede
da UFBA. A API responde **503 `sigaa_indisponivel`** com essa explicação; os parsers de lista/mensagem
são best-effort (não validados) pra quem rodar a API de dentro da rede.

## 9. Horários — `sigaa/util/horario.py`

Código `<dias><turno><slots>`: dias 1=dom, 2=seg … 7=sáb; turno M/T/N; tokens separados por espaço;
período opcional `(dd/mm/aaaa - dd/mm/aaaa)`. O mesmo dia pode vir em vários tokens (`7T2 7T3 7T4 7T5`).
**Tabela real da UFBA** (grade do Comprovante de Matrícula + locais "Terça Horários 18:30 às 19:25"):

| | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| M | 07:00–07:55 | 07:55–08:50 | 08:50–09:45 | 09:45–10:40 | 10:40–11:35 | 11:35–12:30 |
| T | 13:00–13:55 | 13:55–14:50 | 14:50–15:45 | 15:45–16:40 | 16:40–17:35 | 17:35–18:30 |
| N | 18:30–19:25 | 19:25–20:20 | 20:20–21:15 | 21:15–22:10 | | |

Funções: `decodificar(texto)` (blocos contínuos por dia, minutos, datas; nunca levanta — pedaços
estranhos vão em `nao_reconhecido`), `separar_locais(local)` (quebra o "Local" detalhado em
sala/dia/início/fim), `montar_grade(turmas)` (grade semanal + conflitos), `gerar_ics(turmas)`
(RRULE semanal até a data final, TZ America/Bahia), `tabela_horarios()`, `dia_por_nome()`.

---

## Endpoints implementados (`api/routes/portal.py`)

| método | rota | devolve | telas |
|---|---|---|---|
| GET | `/v1/me` | `DadosInstitucionais` (matrícula, curso decomposto, nível, status, e-mail, entrada, unidade, semestre atual, id_discente, foto_url, integralização) | 1 |
| GET | `/v1/portal` | `PortalDiscente` (tudo da página inicial) | 1 |
| GET | `/v1/me/dados-pessoais` | `DadosPessoais` (documentos, filiação, endereço, contatos, banco, socioeconômico) | 1→4 |
| GET | `/v1/me/perfil` | `Perfil` (descrição, áreas, Lattes, assinatura, foto) | 1→5 |
| GET | `/v1/me/foto` | `image/jpeg` | 1→verFoto |
| GET | `/v1/turmas?periodo=&atuais=` | `ListaTurmas` (todas, com `turma_id`, `front_end_id`, código, turma, CH, nível, local detalhado, horário decodificado) | 1+2+3 |
| GET | `/v1/grade-horaria?periodo=` | `GradeHoraria` (por dia, início/fim, sala, conflitos) | 1+3 (+2 se periodo) |
| GET | `/v1/grade-horaria.ics?periodo=` | `text/calendar` | idem |
| GET | `/v1/atividades` | `list[Atividade]` | 1 |
| GET | `/v1/atualizacoes` | `list[Atualizacao]` (com `turma_id`) | 1 |
| GET | `/v1/forum-curso` | `ForumCurso` | 1→6 |
| GET | `/v1/forum-curso/topicos/{topico_id}` | `TopicoForumDetalhe` (best-effort) | 1→6→tópico |
| GET | `/v1/modulos` | `Modulos` | 7 |
| GET | `/v1/mensagens` · `/v1/mensagens/{id}` | `CaixaPostal` / `Mensagem` — 503 fora da rede UFBA | 8 |
| GET | `/v1/salas-livres/filtros` | `FiltrosSalasLivres` | 7.1 |
| GET | `/v1/salas-livres?predio=&dia=&turno=&nivel=&ano=&periodo=` | `RelatorioSalasLivres` | 7.1 (+AJAX) |
| GET | `/v1/horarios/tabela` | `TabelaHorarios` (**sem login**) | — |
| GET | `/v1/horarios/decodificar?codigo=` | `Horario` (**sem login**) | — |

Rotas `/v1/turmas/{turma_id}/...` são da frente turma_virtual (contrato: `turma_id` = idTurma numérico).

## Validação

* `pytest tests/test_portal.py` — 35 testes (fixtures anonimizadas geradas por `recon/anonimizar_portal.py`,
  que confere vazamento).
* `recon/portal_e2e.py` — 23 checagens contra o SIGAA real com `sigaa/client.py` (todas ok em 19/10/2026).

## Variações conhecidas não cobertas / não vistas

* Minhas atividades, notícias do portal, comunidades virtuais e tópicos do fórum: **vazios** pro autor —
  parsers tolerantes escritos pela estrutura padrão do SIGAA, validados só com HTML sintético.
* Aluno com mais de um vínculo / pós-graduação / formando: não visto (rótulos extras caem em `campos_extras`).
* Caixa postal: inacessível de fora da rede.
* Mobile "Minhas Notas", "Atestado de Matrícula (Suplementar)", "Consultar Histórico": mapeados mas são
  da frente acadêmica.
