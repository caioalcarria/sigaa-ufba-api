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
| portal guardado depois de entrar na TURMA VIRTUAL | **não vale**: o menu cai na tela atual (`/ava/index.jsf`), mesmo com só 7 navegações | achado na comparação e2e |
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
| `sigaa/client.py` | `c.paralelo([...])` (sem pool = serial, mesmo resultado); `Compartilhado` (memo + dados do aluno entre as sessões) e **singleflight** no `memo`; `c.pagina(path)` + `menu()` reaproveitando o ViewState do portal (conta conservadora de navegações, renovação no uso, detecção de "voltou pro portal" → baixa e repete); **um transporte httpx por sessão** (keep-alive 4,5 s, contexto SSL compartilhado) e `Carga` (teto global de requisições ao SIGAA) |
| `api/sessions.py` | token → pool (a sessão do login + extras); aquecimento de `POOL_AQUECER` sessões logo após o login; sem `lembrar` a senha cifrada só vive até o aquecimento acabar; keep-alive e logout do pool inteiro |
| `api/config.py` | `POOL_MAX` (4), `POOL_AQUECER` (2), `POOL_TAREFAS_POR_SESSAO` (2), `POOL_PRESSAO_MAX` (0,5), `REUSAR_VIEWS` (8), `MIN_INTERVALO` (0,3 s entre INÍCIOS), `MIN_FOLGA` (0,15 s depois do FIM), `MAX_CONCORRENCIA_SIGAA` (64), `CONEXOES_POR_SESSAO` (4), `HTTP2` (false) |
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

### Ritmo por sessão (achado da bancada)

O `min_interval=0,25` antigo contava do FIM da requisição anterior: somava 250 ms a cada viagem
consecutiva. Agora são duas regras: ≥ 0,3 s entre os INÍCIOS (teto de ~3 req/s por sessão, a regra do
CONTRATO) e ≥ 0,15 s de folga depois do FIM (o mínimo combinado pro SIGAA real). Com o SIGAA
respondendo em ~0,45 s, a espera por viagem cai de 0,25 s pra 0,15 s. Simulado, média de 2 rodadas:

| rota | antigo (0,25 do fim) | novo (0,3 início + 0,15 fim) | folga 0 (SÓ no mock; fura a regra do real) |
|---|--:|--:|--:|
| login | 2,99 s | 2,81 s | 2,59 s |
| `/v1/notas` (1ª) | 5,69 s | 4,76 s | 3,86 s |
| `/v1/tarefas` | 1,37 s | 1,24 s | 0,95 s |
| `/v1/avaliacoes` | 1,41 s | 1,18 s | 0,98 s |
| `/v1/planejamento/matricula` | 9,41 s | 8,66 s | 7,41 s |
| rajada de 6 rotas | 5,75 s | 5,24 s | 4,24 s |

### Mesmo resultado (SIGAA real, JSON comparado byte a byte)

Antes (sequencial, 1 sessão) × depois (pool; na 2ª rodada as 8 rotas disparadas JUNTAS no mesmo token):
`/v1/notas`, `/v1/frequencia`, `/v1/tarefas`, `/v1/avaliacoes`, `/v1/matricula/processamento`,
`/v1/planejamento/matricula` **idênticos**; `/v1/matricula` e `/v1/historico` idênticos salvo
`emitido_em`/`codigo_verificacao` (o SIGAA gera a cada emissão). A 1ª comparação pegou um bug real —
o portal reaproveitado depois da turma virtual levava o menu pra `/ava/index.jsf` (404 no
processamento) — corrigido: navegar em `/ava/` ou `/mobile/` descarta o portal guardado, e menu que
cai lá é repetido com portal novo.

### Transporte: um por sessão, não um compartilhado (achado da bancada)

A piscina de conexões do httpcore degrada com muita requisição simultânea. Microbench (servidor local de
150 ms, N sessões `SigaaClient`): C=16 → 103 × 99 req/s · C=64 → 356 × 360 · **C=200 → compartilhado 76 ×
um por sessão 793 req/s**. Por isso cada sessão tem o seu `AsyncHTTPTransport` (4 conexões), e só o contexto
SSL é dividido. Simulado, `/v1/notas`:

| cenário | transporte compartilhado | um por sessão |
|---|--:|--:|
| 50 alunos × 50, teto 64 | p50 8,32 s · 5,5 req/s | p50 7,17 s · 5,7 req/s |
| 200 × 200, teto 256 | p50 45,1 s · 3,9 req/s (pico no SIGAA: 128) | p50 27,3 s · 7,0 req/s (pico 256) |
| 200 × 200, teto 64 (padrão) | — | p50 31,8 s · 5,3 req/s, 0 erro |

Matriz pedida pelo orquestrador — `perf/turbo` (6c5f8f8 + `SIGAA_API_TRANSPORTE_COMPARTILHADO` pra
alternar), cache DESLIGADO (`SIGAA_API_CACHE=false`, toda requisição vai ao SIGAA), 200 alunos × 200
conexões, 400 requisições por rota, teto global 256 (pra C=200 chegar ao transporte):

| `--fator` | estado | rota | compartilhado: req/s · p50 | um por sessão: req/s · p50 |
|---|---|---|--:|--:|
| 1 (~0,45 s/req) | frio | `/v1/turmas` | 10,9 · 16,2 s | **57,9 · 3,3 s** |
| 1 | frio | `/v1/notas` | 7,3 · 23,8 s | **43,0 · 4,0 s** |
| 1 | quente | `/v1/turmas` | 11,3 · 14,8 s | **57,4 · 3,4 s** |
| 1 | quente | `/v1/notas` | 8,4 · 22,6 s | **41,5 · 4,3 s** |
| 0 (sem latência) | frio | `/v1/turmas` | 77,3 · 2,0 s | **114,8 · 1,6 s** |
| 0 | frio | `/v1/notas` | 37,0 · 4,3 s | **63,0 · 2,5 s** |
| 0 | quente | `/v1/turmas` | 77,1 · 2,1 s | **113,9 · 1,7 s** |
| 0 | quente | `/v1/notas` | 39,3 · 4,6 s | **75,3 · 2,2 s** |
| 1, teto 64 (padrão) | frio | `/v1/turmas` | 25,6 · 7,2 s | 25,6 · 7,2 s |
| 1, teto 64 (padrão) | frio | `/v1/notas` | 16,4 · 11,7 s | 16,4 · 11,6 s |

Zero erro em todos. Com o teto 64 os dois empatam (a piscina nunca vê mais que 64 em voo); acima disso o
compartilhado desaba (5–6× pior com latência real). Fica **um transporte por sessão** (padrão desde 530cf83);
o compartilhado sobrevive só como `SIGAA_API_TRANSPORTE_COMPARTILHADO=true` pra reproduzir a comparação.

O teto padrão continua 64 pra proteger o SIGAA real (a capacidade dele com centenas de sessões não foi
medida); `SIGAA_API_MAX_CONCORRENCIA_SIGAA` sobe se o SIGAA aguentar.

## Riscos e limites

* **Mais logins no SIGAA**: cada login da API vira 2 logins (aquecimento) e até 4 sob demanda. Some
  com `SIGAA_API_POOL_MAX=1` (comportamento antigo) ou `POOL_AQUECER=1` (sem aquecimento).
* **Contexto JSF**: além da janela, a turma virtual e o módulo mobile invalidam o portal guardado
  (tratado). Outro módulo com o mesmo efeito ainda não visto faria o menu cair numa tela errada;
  `REUSAR_VIEWS=0` desliga todo o reuso se aparecer algo assim.
* **Janela de views**: o reuso assume a janela de 10 do MyFaces da UFBA (`REUSAR_VIEWS=8`). Se o SIGAA
  mudar, a view morta devolve o portal — o `menu()` e o `abrir_turma` detectam e repetem com página
  nova (custa 1 viagem), sem erro pro usuário. `REUSAR_VIEWS=0` desliga.
* **Sem `lembrar`**: o pool fica com as sessões abertas no aquecimento; sessão extra que cai sai do
  pool. A principal caindo → 401 `sessao_expirada`, como antes.
* `c.paralelo` exige fluxos INDEPENDENTES (cada um começa do zero na sua sessão; nada de passar uma
  `Page` de uma sessão pra outra).
* O transporte próprio de cada sessão ignora `HTTPS_PROXY` do ambiente (a trava "buraco negro" do
  lançador da bancada não vale nele); o alvo continua sendo `SIGAA_URL`.

## Integração (pro orquestrador)

* `perf/turbo`, `perf/cache`, `perf/bancada`: merge sem conflito.
* `perf/cpu`: 2 trechos em `sigaa/client.py` (função `transporte()` e o `httpx.AsyncClient` do
  `SigaaClient`). Fique com o lado SESSÕES (um transporte por sessão: `transport=_Transporte(transport) if
  transport is not None else transporte(http2=http2, max_conexoes=conexoes)`) e troque `ssl_compartilhado()`
  por `_ssl_ctx()` da cpu (é a mesma ideia: um contexto SSL por processo) — ou deixe
  `def ssl_compartilhado(): return _ssl_ctx()`.

## Prioridade baixa (pro pré-aquecimento do cache)

`from sigaa.pool import prioridade_baixa` — o que roda dentro de `with prioridade_baixa():` (inclusive as
tarefas criadas ali) só pega sessão do pool se sobrar OUTRA livre pro aluno, não recruta a última sessão
livre no `paralelo` e nunca abre sessão nova (pool de 1 sessão: divide, como antes). Integração no cache é
uma linha em `api/cache.py`, `_preaquecer`: `with prioridade_baixa(): await self._aquecer(...)`.

Simulado, 4 alunos: login → 0,6 s → `/v1/notas` (bem no meio do aquecimento):

| variante | 1ª `/v1/notas` p50 | requisições ao SIGAA |
|---|--:|--:|
| hoje (o aquecimento divide o pool e cede cancelando o passo) | 4,86 s | 164 |
| `prioridade_baixa()` | 4,68 s | 160 |
| `prioridade_baixa()` + sem cancelar o passo | 4,70 s | 160 |

Ganho pequeno (o "ceder" do cache já resolvia a maior parte); vale pela garantia de que o fundo nunca
pega a última sessão livre nem gasta login.
