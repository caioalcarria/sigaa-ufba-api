# Servidor sob carga (frente `cpu`)

Como a API aguenta muita requisição em paralelo sem engasgar, o que foi medido e o que configurar.
Todos os números vêm do SIGAA **simulado** (nunca do real), na mesma máquina (20 núcleos).

## Números (antes × depois, mesma máquina, mesmo SIGAA simulado da bancada)

"antes" = `perf/turbo` em 3466463 (o código original + a correção do SIGAA_URL); "depois" = este branch.
A **sonda** é uma requisição a `/` (que não toca no SIGAA) a cada 50 ms durante a carga: mede quanto
UMA rota leve espera porque o processo está ocupado com as outras. Respostas JSON idênticas nas 19
rotas da bancada (`scripts/cpu/igualdade.py`).

**Latência calibrada** (tela 450 ms, PDF 3,5 s, login ≈ 3 s):

| cenário | req/s | p50 | sonda p99 | CPU por req |
|---|---|---|---|---|
| `/v1/portal`, 300 alunos × 300 conexões | 86,7 → 108,5 ¹ | 3,3 s → 2,7 s | 2830 → **3,8 ms** | 12,1 → 11,5 ms |
| `/v1/historico`, 120 alunos (1ª emissão de cada) | 39 s → **11,9 s** pros 120 | 22,0 s → 8,1 s | 11020 → **2,4 ms** | 161 → 19 ms |
| `/v1/turmas`, 200 × 200 | 18,3 → 21,8 | 10,6 s → 9,0 s | 2075 → **8,7 ms** | 40 → 33 ms |
| `/v1/notas` (todas as turmas), 100 × 100 | 5,1 → **8,4** | 19,3 s → 11,8 s | 1342 → **5,4 ms** | 115 → 50 ms |
| `/v1/publico/cursos/{id}`, 100 conexões | 15,9 → 25,2 ² | 6,3 s → 3,9 s | 59 → 2,7 ms | 27,6 → 8,0 ms |

¹ teto de 50 conexões ao SIGAA (50 ÷ 0,45 s ≈ 110 idas/s). ² teto de 4 sessões anônimas (`MAX_ANONIMOS`).
Com o SIGAA respondendo em 450 ms o req/s é limitado pelas idas ao SIGAA (o que as frentes de
sessões/cache atacam); o que esta frente muda é a API não ENGASGAR: a rota leve passou de segundos
pra milissegundos, e a CPU foi pros outros núcleos.

**Capacidade pura** (SIGAA simulado SEM latência — só a CPU da API conta):

| cenário | antes req/s | depois req/s | ganho |
|---|---|---|---|
| `/v1/portal`, 300 × 300 | 95 | **625** | 6,6× |
| `/v1/historico`, 120 alunos | 3,0 | **172** | 57× |
| `/v1/turmas`, 200 × 200 | 20,9 | **114** | 5,4× |
| `/v1/notas`, 100 × 100 | 6,6 | **29,6** | 4,5× |

A CPU TOTAL por requisição quase não muda no portal/turmas (o parse continua sendo feito, só que em
paralelo nos outros núcleos); cai onde o motor ficou mais rápido (PDF 12x, navegação lxml ~9x).

**SIGAA lento + rajada** (tela 4,5 s; 600 alunos × 600 conexões, 40 s):

| | antes | depois |
|---|---|---|
| requisições simultâneas que chegam no SIGAA | **600** | **50** (o teto) |
| respostas 200 / 503 | 2811 / 0 | 666 / 697 (`sigaa_ocupado`, `Retry-After`) |
| sonda p99 | 2677 ms | **2,2 ms** |

O teto é o trade-off: protege o SIGAA (e a API) da rajada, ao custo de req/s quando o SIGAA está
lento mas aguentando. `SIGAA_API_MAX_CONCORRENCIA_SIGAA` ajusta (o teto é o `Carga` da frente de sessões, 64 por padrão; as medições acima foram com o teto antigo desta frente, 50).

**Integrado** — `perf/turbo` 95fb918 (cache + sessões + bancada, SEM esta frente) × este branch por cima
dele (8a0dc3a), com `Cache-Control: no-cache` (toda requisição vai ao SIGAA; o HIT do cache é outra
história). JSON idêntico nas 19 rotas.

| cenário | latência calibrada: req/s · sonda p99 | sem latência: req/s |
|---|---|---|
| `/v1/portal`, 300 × 300 | 50,7 → **138,3** · 470 → 6,3 ms | 71,7 → **411,6** (5,7×) |
| `/v1/historico`, 120 alunos | 45,2 s → **9,2 s** pros 120 · 10382 → 5,6 ms | 3,0 → **248,7** (83×) |
| `/v1/turmas`, 200 × 200 | 12,3 → **26,6** · 471 → 19,8 ms | 17,3 → **76,6** (4,4×) |
| `/v1/notas`, 100 × 100 | 6,5 → **20,1** · 1092 → 20 ms | 8,2 → **50,7** (6,2×) |

Com o pool de sessões (navegações do mesmo aluno em paralelo) a CPU por requisição SOBE (mais logins e
mais telas ao mesmo tempo) — é justamente onde parse fora do event loop rende mais.

**HIT do cache durante uma rajada de logins** (`scripts/cpu/preaquecer.py`): uma sessão pede
`/v1/historico` (HIT) a cada 50 ms enquanto N alunos fazem login AO MESMO TEMPO — cada login dispara o
pré-aquecimento do cache, que emite e parseia o histórico. Latência calibrada; `perf/turbo` 46bfc09 × este branch.

| | HIT p95 | HIT p99 | HIT máx | conexões derrubadas |
|---|---|---|---|---|
| 50 logins — turbo | 66,7 ms | 231 ms | **11,8 s** | 0 |
| 50 logins — turbo + cpu | **1,3 ms** | 1,6 ms | 7,9 ms | 0 |
| 150 logins — turbo | 261 ms | 614 ms | **16,2 s** | 3 |
| 150 logins — turbo + cpu | **1,4 ms** | 2,3 ms | 58 ms | 0 |

## Desenho

```
             ┌──────────────── 1 processo de API (uvicorn + uvloop + httptools) ─────────────────┐
cliente ───► │ Prazo (504) → CORS → GZip → rotas → SigaaClient ──(teto global de conexões)──► SIGAA
             │                                │ parse de HTML/PDF                                 │
             └────────────────────────────────┼───────────────────────────────────────────────────┘
                                              ▼
                       pool de processos de parse (sigaa/cpu.py, núcleos-1, máx. 8)
```

* **Um processo de API só**: as sessões (token → `SigaaClient` com cookies e trava JSF) vivem na
  memória dele. Com `--workers N` do uvicorn, cada worker teria as SUAS sessões e o kernel espalha as
  conexões: o token criado no worker A dá `401 token_invalido` em ~(N-1)/N das chamadas. Não use
  `--workers` enquanto as sessões estiverem em memória (ver "Mais de um processo de API" abaixo).
* **O parse sai do event loop e vai pros outros núcleos** (`sigaa/cpu.py`): todo `parse_*` dos
  serviços é chamado via `await rodar(P.parse_x, page.html)`, e o "clique"/"submit" do
  `SigaaClient` (parse da página + achar o link + campos do form) também. O BeautifulSoup e o layout
  do PDF são Python puro e seguram o GIL — em thread (`asyncio.to_thread`) eles só disputariam a CPU
  com o loop (medido: o PDF em 8 threads rende *menos* que em série); em processos, rodam em paralelo.
  Argumento pequeno (< 1,5 KB; a ida e volta custa 0,1–0,5 ms de CPU aqui) ou objeto que não é texto (soup, Page) roda na hora, no próprio processo.
  Sem `cpu.iniciar()` (uso como biblioteca, testes) tudo roda na hora — o comportamento antigo.
* **PDF do histórico ~12x mais rápido** com resultado idêntico: os caracteres saem do PDFium
  (`pypdfium2`, que já vinha com o pdfplumber) e passam pelo MESMO layout do pdfplumber
  (`scripts/bench_pdf.py` prova texto e modelo idênticos e mede).
* **Navegação sem BeautifulSoup**: `Page.links_jsf()` e os campos do formulário do clique/submit saem
  do lxml direto (~9x mais rápido); form aninhado ou documento estranho cai no caminho antigo. Teste
  de igualdade em TODAS as fixtures (`tests/test_navegacao_lxml.py`).
* **Um contexto SSL pro processo** (`client._ssl_ctx`): o httpx criava um por cliente, recarregando o
  bundle de CAs — ~11 ms de CPU no event loop por login, por rota pública e por `/v1/status`.
* **GC**: `gc.freeze()` depois do boot e geração 0 bem menos frequente; e a soup do portal guardado
  na sessão é descartada no fim de cada fluxo (o HTML fica). Com centenas de sessões retendo essa
  árvore cheia de ciclos, uma varredura completa do GC parava o processo por ~300 ms.

## Limites (backpressure)

| variável | padrão | o quê |
|---|---|---|
| `SIGAA_API_MAX_CONCORRENCIA_SIGAA` | 64 | teto GLOBAL de requisições simultâneas ao SIGAA (o `Carga` da frente de sessões; todas as sessões somadas). Protege o SIGAA de rajada |
| `SIGAA_ESPERA_MAX_S` | 20 | quanto uma requisição espera por vaga; passou → `503 sigaa_ocupado` com `Retry-After: 5` (falha rápido em vez de empilhar) |
| `SIGAA_API_TIMEOUT_S` | 120 | prazo total de uma requisição na API; passou → `504 tempo_esgotado` e a navegação é cancelada (a trava da sessão é liberada) |
| `SIGAA_PARSE_PROCESSOS` | núcleos-1 (1–8) | processos do pool de parse; respeita `docker --cpus` (cota do cgroup). 0 = desliga |
| `SIGAA_PARSE_LIMIAR_BYTES` | 1500 | abaixo disso o parse roda no próprio processo |
| `SIGAA_PARSE_PRAZO_S` | 30 | um parse que não volta nisso = pool travado: recria o pool e faz no próprio processo |
| `SIGAA_API_GZIP_MIN_BYTES` | 2048 | gzip (nível 5) nas respostas maiores que isso, se o cliente mandar `Accept-Encoding: gzip`. 0 = desliga |
| `SIGAA_API_GC_LIMIARES` | `50000,20,20` | `gc.set_threshold` (o padrão do Python é `700,10,10`) |

O teto de conexões é o que manda no req/s quando o SIGAA é o gargalo: com ~450 ms por ida/volta,
64 vagas ≈ 140 idas/s (50 ≈ 110 na medição). Subir o teto aumenta o req/s da API **e a carga no SIGAA da UFBA** — é decisão
de operação, não de código. Uma rota lenta ocupa no máximo as vagas que está usando: as outras rotas
continuam (o event loop não trava mais) e, se o SIGAA inteiro ficar lento, a fila tem prazo.

`/v1/status` mostra `servidor.processos_de_parse`, `conexoes_sigaa_em_uso` e `conexoes_sigaa_max` — só com
`SIGAA_API_STATUS_DETALHADO=true` (padrão `false`: os campos vêm `null`, junto com `sessoes_ativas`, porque a
rota não tem login). A sonda "o SIGAA está no ar?" é reaproveitada por `SIGAA_API_STATUS_CACHE_S` (padrão 15 s):
uma ida ao SIGAA por janela, não por requisição.

## Rodar

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers \
    --loop uvloop --http httptools --backlog 4096 --timeout-keep-alive 30
```

(é o `CMD` do Dockerfile, que também tem `--no-server-header` e `ulimit -c 0`).

**`FORWARDED_ALLOW_IPS` no contêiner:** lá dentro o proxy reverso nunca é `127.0.0.1` (o padrão do uvicorn).
A imagem vem com ele VAZIO (não confia em ninguém: o IP do cliente é o da conexão). Atrás de proxy, passe o
IP dele — senão todo aluno aparece com o IP do proxy e o limite de login por IP vira um limite global. O
`docker-compose.yml` reserva `172.31.250.10` pro proxy numa rede própria e confia só nele (nem o gateway,
por onde chega a porta publicada, consegue forjar `X-Forwarded-For`). Nunca use `*`. Memória: o processo da API cai de ~1,2 GB pra ~0,1 GB depois de centenas de
sessões (a soup não fica retida); cada processo do pool ocupa ~60–80 MB (8 processos ≈ 0,6 GB).
Numa VPS pequena, `SIGAA_PARSE_PROCESSOS=1` ou `2` já tira o parse do event loop.

## O que NÃO compensou (medido)

* **orjson / ORJSONResponse**: o FastAPI 0.150 já serializa o `response_model` com o pydantic-core
  (Rust) direto pra bytes — 0,4% da CPU no perfil do `/v1/portal`. Nada a ganhar.
* **brotli**: no JSON do histórico (27 KB) dá 4,4 KB contra 4,7 KB do gzip-5, custando mais CPU e uma
  dependência. Ficou só o gzip.
* **`asyncio.to_thread` pro parse**: o GIL. 8 PDFs (motor antigo) em 8 threads: 2,2 PDF/s, contra
  3,2 em série e 17,4 em 8 processos.
* **Trocar o BeautifulSoup por selectolax/lxml nos parsers**: ~7.000 linhas de parser testadas contra
  fixture; com o pool, o parse já não trava nada e o tempo de uma requisição é dominado pelas idas ao
  SIGAA (450 ms cada). Fica como otimização futura de CPU total, rota a rota, se o pool saturar.
* **uvloop + httptools**: já vinham ligados (o `uvicorn[standard]` escolhe os dois sozinho; o perfil
  confirma). O Dockerfile agora só deixa explícito.

## Mais de um processo de API (futuro, depende da frente de sessões)

Pra passar de 1 processo de API, o token precisa achar o processo dono da sessão:
1. **N instâncias + roteamento por token**: cada instância põe o seu id no começo do token
   (`w3.<aleatório>`) e um nginx escolhe o upstream pelo prefixo (`map $http_authorization`); o
   login (sem token) vai pra qualquer uma. Muda só o formato do token.
2. **Sessão fora do processo** (Redis): cookies dá pra serializar, mas a trava da navegação JSF e o
   estado das telas são por sessão — precisaria de trava distribuída. Bem mais caro.
Com o pool de parse, 1 processo de API gasta ~2 ms de CPU de event loop por requisição (o resto foi pro
pool), então o teto dele está bem acima do que o teto de conexões ao SIGAA deixa passar.

## Pra quem escreve serviço novo

Chame o parser com `await rodar(P.parse_x, page.html, ...)` (de `sigaa.cpu`). Pra conferir/aplicar
em lote: `python scripts/cpu/offload_parsers.py --checar` (sai 1 se sobrou parse no event loop) e
`python scripts/cpu/offload_parsers.py` (reescreve; idempotente — rode depois de um merge).

## Como medir (scripts/cpu)

* `mock_min.py` — SIGAA simulado mínimo (o completo é o `bench/mock_sigaa.py` da bancada; use o dela).
* `carga.py` — gerador de carga (aiohttp, vários processos) com SONDA: uma requisição a `/` a cada 50 ms
  em paralelo à carga mede se o event loop está livre.
* `cenarios.py` — roda os cenários e lê a CPU do processo da API + pool em `/proc` (ms de CPU por req).
* `igualdade.py` — compara o JSON de duas APIs (base × frente) rota a rota.
* `offload_parsers.py` — ver acima.

Suba as APIs SEMPRE pelo `bench/api_instancia.sh` da bancada (troca o `BASE_URL`, bloqueia https e
recusa a porta 8000) — nunca `uvicorn api.main:app` direto apontando pro simulado.
