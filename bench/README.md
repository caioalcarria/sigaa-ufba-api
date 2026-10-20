# bench/ — bancada de performance da sigaa-api

Mede a API REST **local** contra o **SIGAA simulado** (`mock_sigaa.py`). Nunca contra o SIGAA real:
o `bench.py` pergunta à API (`GET /v1/status`) pra onde ela aponta e aborta se não for `127.0.0.1`/`localhost`,
e o `api_instancia.sh` recusa `sigaa_url` que não seja `http://127.0.0.1:<porta>`.

| arquivo | o quê |
|---|---|
| `mock_sigaa.py` | o SIGAA simulado (`--porta 8111`; expõe `GET /__mock/config`) |
| `_lancador.py` | sobe a API de um worktree com o `BASE_URL` trocado pro mock + https bloqueado |
| `api_instancia.sh` | sobe/para a API de **qualquer** worktree, em background, com PID gravado |
| `bench.py` | o bench: latência fria × quente por rota + carga (N alunos × C conexões) |

## Rodada típica (≈ 2 min no `--rapido`)

O `bench.py` é só cliente HTTP: roda SEMPRE com a **.venv da bancada** (ela tem o `aiohttp`), não importa
qual worktree está sendo medido. A API medida roda com a .venv DO worktree dela (o `api_instancia.sh` cuida).

```bash
BANC=~/PROJECTS/UFBA/sigaa-api-perf-bancada         # mock, lançador, bench e a .venv com aiohttp
WT=~/PROJECTS/UFBA/sigaa-api-perf-<frente>          # o worktree que você quer medir (com a .venv dele)

$BANC/.venv/bin/python $BANC/bench/mock_sigaa.py --porta 8111 &      # 1) SIGAA simulado (anote o PID)
$BANC/bench/api_instancia.sh "$WT" 8112 http://127.0.0.1:8111        # 2) a API do $WT, apontada pro mock
$BANC/.venv/bin/python $BANC/bench/bench.py --api http://127.0.0.1:8112 --mock http://127.0.0.1:8111 \
    --worktree "$WT" --rotulo minha-frente --rapido \
    --saida-md /tmp/bench-minha-frente.md --saida-json /tmp/bench-minha-frente.json
$BANC/bench/api_instancia.sh parar 8112                              # 3) mata SÓ o PID gravado
```

Portas: 8100–8199 (a 8000 é a produção, recusada). Combine a faixa com a sua frente pra não colidir.

## `api_instancia.sh`

```
api_instancia.sh <worktree> <porta> <sigaa_url>   # sobe em background, espera /v1/status (até 30 s)
api_instancia.sh parar <porta>                     # TERM (KILL após 10 s) só no PID gravado, e confere que é o nosso
api_instancia.sh status <porta>
```

Usa `<worktree>/.venv/bin/python bench/_lancador.py` (a `.venv` e o código **do worktree alvo**).
O lançador seta `SIGAA_API_MAX_LOGINS_POR_IP=1000000`, `SIGAA_API_MAX_SESSOES=100000`,
`SIGAA_API_MAX_SESSOES_POR_USUARIO=1000`, `SIGAA_API_KEEPALIVE=false` e `HTTPS_PROXY` pra um buraco negro.
PID e log: `bench/.pids/api_<porta>.{pid,log}` (gitignored). `API_LOG_LEVEL=info` mostra o access log.

## `bench.py`

Cliente: **aiohttp** (`TCPConnector(limit=C+folga, limit_per_host=0)`). O `httpx.AsyncClient` desaba acima de
~50 conexões simultâneas (medido: C=200 contra o mock com 150 ms, httpx 86 req/s × aiohttp 1220 req/s, o ideal é 1333);
com ele o bench mediria o próprio cliente. `--calibrar-cliente` prova o teto: antes da carga, dispara a mesma
carga (C, R/duração) direto num GET do mock (`--calibrar-url`, padrão `/sigaa/public/turmas/listar.jsf`) e põe
uma linha "teto do cliente" na tabela com `ideal = C / latência mediana` e a eficiência (≈ 1 = o gerador aguenta).

Fases:
0. **descoberta**: 1 login; `{turma_id}` = 1º id de `/v1/turmas-virtuais` (senão `/v1/turmas`); `{unidade}` = 1º id de `/v1/publico/unidades`.
1. **fria × quente** (por rota): `--amostras-frias` sessões NOVAS (cada uma um aluno novo: `aluno001`, `aluno002`…);
   em cada uma, a 1ª chamada é a **fria** e as `--quentes` seguintes (em série, mesma sessão) são as **quentes**.
   Rotas `/v1/publico/*` vão sem login; como o cache delas pode ser compartilhado, só a 1ª amostra fria é garantidamente fria.
2. **carga** (por rota de `--rotas-carga` × C de `--conexoes` × N de `--alunos`): N logins ANTES (não contam no tempo;
   até `--login-paralelo` por vez), depois `--requisicoes` R (e/ou `--duracao` s) com C sempre em voo, em rodízio
   entre os N tokens. Mede req/s, p50/p95/p99/max, status por código e os erros (`502 navegacao_invalida: …`, `timeout`, `ConnectError`…).
   Cada cenário usa alunos novos e faz logout no fim. Antes de cada rajada (depois dos logins) o bench faz
   `POST /__mock/reset` e, no fim, lê `/__mock/stats`: o JSON de cada cenário traz `mock` com `total_misses`,
   `pico_concorrencia`, `por_regra`, `requisicoes`, `viewstate_invalido`, `expiradas`; a tabela mostra req · pico · MISS.
   (`--sem-reset-mock` se o mock estiver sendo usado por outra rodada ao mesmo tempo.)
   Com `--duracao`, as requisições já em voo no prazo terminam e contam (o tempo do cenário passa um pouco do prazo).

Opções principais (`--help` mostra todas, com os padrões):

| opção | padrão | |
|---|---|---|
| `--api` | `http://127.0.0.1:8112` | tem que ser local |
| `--mock` | o `sigaa.url` de `/v1/status` | lê `/__mock/config` e `/__mock/stats`, zera com `/__mock/reset` |
| `--calibrar-cliente` | não | linha "teto do cliente" por C (direto no mock) |
| `--worktree` | — | grava commit/branch/sujo nos metadados |
| `--rotulo` | — | nome da rodada (baseline, cache, sessoes…) |
| `--rotas` / `--rotas-carga` | 19 rotas (14 logadas + 5 públicas) / historico, turmas, notas, `/v1/publico/componentes/{componente_id}` | lista por vírgula; placeholders abaixo |
| `--param k=v` | — | valor de placeholder (vence `/__mock/config`, que vence a descoberta e o padrão) |

Placeholders e padrões (ids que existem nas fixtures do mock): `{turma_id}` descoberto (393420), `{componente_id}`=44697 (MATA37),
`{codigo}`=MATA37, `{curso_id}`=1876885, `{estrutura_id}`=2421505, `{unidade}`=1114, `{ano}`=2026, `{periodo}`=2.

| opção | padrão | |
|---|---|---|
| `--amostras-frias` / `--quentes` | 3 / 5 | |
| `--conexoes` | `1,10,50,200` | C |
| `--alunos` / `--alunos-max` | `auto` / 50 | N: `auto` = min(C, máx); `auto,1` também mede "o mesmo aluno com C conexões" |
| `--requisicoes` / `--duracao` | 200 / — | o que vier primeiro; `--requisicoes 0 --duracao 30` = só tempo |
| `--aquecer` | não | 1 chamada por sessão antes de medir a carga (mede só o "quente") |
| `--paralelo-frias` | 1 | rotas medidas ao mesmo tempo na fase fria (1 = medida limpa) |
| `--rapido` | — | smoke (< 2 min): 1 fria, 2 quentes, C=1,10, 20 req (máx 5 s) por cenário, todas as rotas frias em paralelo |
| `--sem-frias` / `--sem-carga` | — | pula a fase |
| `--saida-md` / `--saida-json` | — | a tabela vai sempre pro stdout; o progresso vai pro stderr |

O JSON traz tudo: metadados (data, commit, mock config, nproc, loadavg, parâmetros, placeholders usados),
os tempos de cada chamada (`ms_todas`), status e erros por rota/cenário.

### Comparar duas versões

Suba duas APIs (ex.: 8112 = baseline, 8113 = sua frente) apontadas pro MESMO mock e rode o bench com o mesmo
comando e `--rotulo` diferentes. Rode as duas na mesma máquina, sem outra carga pesada (o `loadavg` vai nos metadados).
