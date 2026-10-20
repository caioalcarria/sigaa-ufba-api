# Frente "sessões": paralelismo e menos viagens ao SIGAA

Branch `perf/sessoes`. O tempo da API está nas VIAGENS ao SIGAA (~0,45 s cada, todas em série porque
uma sessão JSF só navega uma tela por vez). Esta frente ataca as duas coisas: mais viagens AO MESMO
TEMPO (várias sessões do aluno) e MENOS viagens (reaproveitar o ViewState, não repetir navegação).

## O que o SIGAA real aceita (recon de 20/10/2026, 2 logins, só leitura)

| pergunta | resposta | número |
|---|---|---|
| 2ª sessão do mesmo usuário derruba a 1ª? | **não**: JSESSIONIDs independentes convivem | — |
| custo do login | verTelaLogin + POST logOn + tela de avisos + portal | 2,6–3,6 s (POST ~1,6 s) |
| JSF | MyFaces, estado **no servidor** (ViewState = `j_idN`) | — |
| quantas views a sessão guarda | **10**: uma página sobrevive a 9 navegações e morre na 10ª | — |
| usar uma view a renova? | **sim** (vira a mais recente): 25 reusos seguidos funcionam | — |
| o que acontece com view morta | **sem erro**: o SIGAA ignora o clique e devolve o PORTAL | 39 KB em vez da tela |
| 2 cliques da mesma `turmas.jsf` / Notas + Frequência da mesma página da turma | funcionam | — |
| GETs diretos (relatorioProcessamento, view_painel, turmas.jsf, mobile) | aceitos, até 3 ao mesmo tempo na mesma sessão | 3 GETs em 0,59 s |
| HTTP/2 | **não** (ALPN → HTTP/1.1) | — |
| keep-alive | sim, `timeout=5, max=97` | conexão nova +0,1 s |
| gzip | sim | 39 KB → 8,9 KB |
| min_interval 0,15 s | sem reação em 6 GETs | (mantido 0,25 s) |

## O que mudou

| arquivo | mudança |
|---|---|
| `sigaa/pool.py` (novo) | `PoolSigaa`: as sessões do aluno. `executar(fluxo)` na 1ª sessão livre; `paralelo(fluxos)` espalha fluxos independentes; sessões novas sob demanda (login em 2º plano) até `maximo`, só se a fila compensa o login e o SIGAA está folgado (`Carga.pressao`); relogin por sessão; sessão extra que cai sem credencial sai do pool e o fluxo dela vai pra outra |
| `sigaa/client.py` | `c.paralelo([...])` (sem pool = serial, mesmo resultado); `Compartilhado` (memo + dados do aluno entre as sessões) e **singleflight** no `memo`; `c.pagina(path)` + `menu()` reaproveitando o ViewState do portal (conta conservadora de navegações, renovação no uso, detecção de "voltou pro portal" → baixa e repete); transporte httpx **compartilhado** (keep-alive 4,5 s) e `Carga` (teto global de requisições ao SIGAA) |
| `api/sessions.py` | token → pool (a sessão do login + extras); aquecimento de `POOL_AQUECER` sessões logo após o login; sem `lembrar` a senha cifrada só vive até o aquecimento acabar; keep-alive e logout do pool inteiro |
| `api/config.py` | `POOL_MAX` (4), `POOL_AQUECER` (2), `POOL_TAREFAS_POR_SESSAO` (2), `POOL_PRESSAO_MAX` (0,5), `REUSAR_VIEWS` (8), `MIN_INTERVALO` (0,25), `MAX_CONCORRENCIA_SIGAA` (64), `MAX_CONEXOES` (128), `HTTP2` (false) |
| `sigaa/services/turma_virtual.py` | agregadas (`notas_todas`, `frequencia_todas`, `tarefas_pendentes`, `avaliacoes_todas`) em paralelo, uma turma por sessão; lista de turmas memorizada 10 min (`_do_periodo`); `turmas.jsf` × lista mobile em paralelo; `abrir_turma` reaproveita `turmas.jsf`; mapa idTurma↔frontEnd em `c.dados` (era `c.__dict__`) |
| `sigaa/services/academico.py` | `resultados_processamento`: os GETs `relatorioProcessamento` em paralelo |
| `sigaa/services/planejamento.py` | pré-requisitos (`view_painel` por componente) em paralelo; grade × oferta em paralelo |
| `tests/test_pool.py` | 18 testes sem rede (ordem, erro, sessão que cai, relogin, singleflight, pressão, reuso de view, view descartada) |
| `scripts/bench_sessoes.py` | bench e2e de um aluno: seq + rajada |

Parsers: intocados.

## Números (antes = `main` 70a6ea5 · depois = `perf/sessoes`)

### SIGAA real, 1 aluno (3 turmas no semestre), leve (1 rodada cada, ≤4 sessões)

| rota | antes | depois |
|---|--:|--:|
| login | 3,03 s | 2,55 s |
| `/v1/notas` (1ª, fria) | 9,43 s | 6,63 s |
| `/v1/frequencia` | 6,09 s | 1,32 s |
| `/v1/tarefas` | 4,75 s | 0,99 s |
| `/v1/avaliacoes` | 4,75 s | 0,91 s |
| `/v1/matricula/processamento` | 4,47 s | 2,92 s |
| `/v1/planejamento/matricula` | 24,26 s | 9,09 s |
| **rajada** (me, turmas, notas, tarefas, avaliações, frequência juntas) | **27,77 s** | **5,95 s** |

### SIGAA simulado (bancada: ~450 ms/req, login ~3 s, janela de 10 views)

Fria × quente por rota (p50, 2 alunos novos × 3 quentes):

| rota | antes fria / quente | depois fria / quente |
|---|--:|--:|
| `/v1/matricula` (menu) | 1,38 / 1,44 s | 0,69 / 0,71 s |
| `/v1/historico` | 4,74 s / (memo) | 3,68 s / (memo) |
| `/v1/notas` | 9,11 / 9,22 s | 5,57 / 1,44 s |
| `/v1/frequencia` | 9,18 / 9,16 s | 5,61 / 1,48 s |
| `/v1/tarefas` | 9,10 / 9,06 s | 5,58 / 1,42 s |
| `/v1/avaliacoes` | 9,12 / 9,13 s | 5,67 / 1,44 s |
| `/v1/matricula/processamento` | 6,23 / 6,27 s | 4,35 / 1,90 s |
| `/v1/planejamento/matricula` | 14,24 s / (memo) | 8,85 s / (memo) |
| rajada de 6 rotas (1 aluno) | 39,55 s | 5,66 s |
| requisições ao SIGAA no roteiro seq+rajada | 139 | 102 (incl. 3 logins extras) |

Carga em `/v1/notas` (bench.py da bancada, 60 req por cenário):

| N alunos × C conexões | antes p50 · req/s | depois p50 · req/s | requisições ao SIGAA |
|---|--:|--:|--:|
| 1 × 1 | 9,04 s · 0,1 | 1,41 s · 0,7 | — |
| 10 × 10 | 9,15 s · 1,1 | 1,78 s · 3,9 | 780 → 554 |
| 1 × 10 (mesmo aluno) | 90,6 s · 0,1 | 10,0 s · 0,9 | — |
| 1 × 50 (mesmo aluno) | 64 s · 0,3, **46 timeouts** | 38,0 s · 0,9, 0 erro | — |
| 50 × 50 (todos frios) | 11,6 s · 2,8 | 9,4 s · 4,3 | 780 → 735 |
| 50 × 50 com teto 256 | — | 12,5 s · 3,6 (pior: 941 req) | — |

Leitura: com muitos alunos frios ao mesmo tempo o gargalo é o próprio SIGAA (o teto global de 64
requisições simultâneas fica cheio); abrir mais sessões ali só gasta login. Por isso o pool só cresce
com o SIGAA abaixo de 50% do teto. O ganho grande é no aluno que abre o app (rajada) e nas rotas
agregadas; o "mesmo aluno × muitas conexões" fica limitado a `POOL_MAX` sessões (a frente de cache,
com singleflight por rota, resolve o resto).

## Riscos e limites

* **Mais logins no SIGAA**: cada login da API vira 2 logins (aquecimento) e até 4 sob demanda. Some
  com `SIGAA_API_POOL_MAX=1` (comportamento antigo) ou `POOL_AQUECER=1` (sem aquecimento).
* **Janela de views**: o reuso assume a janela de 10 do MyFaces da UFBA (`REUSAR_VIEWS=8`). Se o SIGAA
  mudar, a view morta devolve o portal — o `menu()` e o `abrir_turma` detectam e repetem com página
  nova (custa 1 viagem), sem erro pro usuário. `REUSAR_VIEWS=0` desliga.
* **Sem `lembrar`**: o pool fica com as sessões abertas no aquecimento; sessão extra que cai sai do
  pool. A principal caindo → 401 `sessao_expirada`, como antes.
* `c.paralelo` exige fluxos INDEPENDENTES (cada um começa do zero na sua sessão; nada de passar uma
  `Page` de uma sessão pra outra).
* O transporte compartilhado ignora `HTTPS_PROXY` do ambiente (transporte próprio); o alvo continua
  sendo `SIGAA_URL`.
