# Modelo de ameaças da sigaa-api

Escopo: o servidor FastAPI desta pasta (`api/` + `sigaa/`), do jeito que ele roda em produção — um
processo uvicorn, sessões em memória, cache L1 (HTTP) e L2 (funções de serviço) em memória ou Redis,
atrás (ou não) de um proxy reverso com HTTPS. A API é **de leitura**; as ações de escrita (frente
`feat/acoes`) têm um parecer à parte (seção 7).

Método: STRIDE por fronteira, a partir dos ativos. Cada ameaça aponta a defesa e o teste de
regressão em `tests/seguranca/`. A lista de achados da auditoria, com severidade e status, está em
[`README.md`](README.md#achados-da-auditoria).

## 1. O sistema em uma figura

```
 navegador / app / script                 servidor da API (quem hospeda)                 UFBA
┌──────────────────────┐   HTTPS   ┌─────────────┐   HTTP   ┌───────────────────────────┐  HTTPS  ┌───────┐
│ cliente (front, curl)│──────────▶│ proxy (TLS) │────────▶│ uvicorn + FastAPI          │────────▶│ SIGAA │
│ token Bearer         │   (F1)    │  opcional   │  (F2)    │  sessões (token→pool)      │  (F4)   │       │
└──────────────────────┘           └─────────────┘          │  cache L1/L2, Fernet, logs │         └───────┘
                                                            │        │ (F3)              │
                                                            └────────┼───────────────────┘
                                                                     ▼
                                                              Redis (opcional)
```

Fronteiras de confiança:

* **F1 — internet → API.** Tudo o que chega do cliente é hostil: corpo, query, path, headers
  (inclusive `X-Forwarded-For`, `Host`, `Origin`).
* **F2 — proxy → uvicorn.** Só aqui `X-Forwarded-*` podem ser confiáveis, e só se o uvicorn
  souber o IP do proxy (`--forwarded-allow-ips`).
* **F3 — API → Redis.** Rede e servidor do Redis podem ser de terceiros: o que sai do processo
  sai cifrado (entradas de aluno) e nunca com o login/token em claro.
* **F4 — API → SIGAA.** O HTML/PDF do SIGAA é **entrada não confiável** (pode conter conteúdo
  postado por qualquer usuário do SIGAA: notícias, fórum, nomes de arquivo, mensagens). E a API é
  cliente de um sistema de terceiros que precisa ser protegido do próprio uso da API.

## 2. Ativos

| ativo | onde vive | por quanto tempo | impacto se vazar |
|---|---|---|---|
| **senha do SIGAA** | corpo do login; com `lembrar=true`, cifrada (Fernet, chave aleatória do processo) na memória | login: só a requisição; `lembrar`: até o token morrer; aquecimento do pool: segundos | **crítico** — é a conta institucional do aluno (e-mail, matrícula, SSO). Tentativas erradas bloqueiam a conta no SIGAA |
| **token da API** | cliente; servidor guarda **só o SHA-256** | TTL absoluto (12 h) e ociosidade (120 min) | alto — lê todos os dados acadêmicos do aluno enquanto vale |
| **cookie JSESSIONID** do SIGAA | memória do processo (cliente httpx de cada sessão do pool) | até logout/expiração | alto — sessão do SIGAA do aluno, utilizável fora da API |
| **dados acadêmicos e pessoais** do aluno (histórico, notas, CPF/RG/endereço em dados pessoais, foto, documentos) | resposta; cache L1/L2 (memória ou Redis cifrado) | TTL do cache (minutos a 1 dia + stale) | alto (LGPD — dado pessoal, parte sensível) |
| **dados de terceiros** (colegas de turma, docentes, participantes, fotos, mensagens, fórum) | idem | idem | alto (LGPD — titulares que nem usam a API) |
| **segredos do servidor** (`SIGAA_API_CACHE_SEGREDO`, chave Fernet, senha do Redis) | env / memória | vida do processo | alto — com o segredo do cache e acesso ao Redis, dá pra decifrar o cache |
| **disponibilidade do SIGAA da UFBA** | — | — | alto — a API não pode virar amplificador de carga contra a UFBA |

## 3. Atores

| ator | o que quer | o que tem |
|---|---|---|
| **outro aluno** (usuário legítimo da mesma instância) | ver dado de colega | um token válido dele; consegue escolher path/query/headers |
| **cliente malicioso / anônimo na internet** | senhas (força bruta via API), DoS, SSRF, usar a API como proxy contra o SIGAA | só a rede; rotas públicas e de login |
| **atacante na rede** (Wi-Fi, ISP, entre proxy e API, entre API e Redis) | capturar senha/token/cookie | tráfego sem TLS |
| **front-end com XSS** (um app que usa a API foi comprometido, ou conteúdo do SIGAA vira script no domínio da API) | roubar o token do `localStorage`, ler dados pela API com o token da vítima | JavaScript na origem do front ou da API |
| **quem hospeda a API** (dono do servidor, admin do Redis, quem lê os logs) | — (honesto-curioso) ou abusar | memória, logs, env, Redis, tráfego decifrado no proxy. **Este ator vê tudo em tese** — ver [privacidade](privacidade.md) |
| **o próprio SIGAA** (ou conteúdo postado nele) | — | controla o HTML/PDF que a API parseia e repassa |

## 4. Ameaças por categoria (STRIDE) e defesas

### 4.1 Falsificação de identidade (Spoofing)

| # | ameaça | defesa | teste |
|---|---|---|---|
| S1 | adivinhar/forjar token | `secrets.token_urlsafe(32)` (256 bits); servidor guarda só hash; token morre por TTL e ociosidade | `test_auth_*` |
| S2 | força bruta de senha usando a API como oráculo (e bloquear a conta do aluno no SIGAA) | limite de **falhas por usuário** (independente do IP) + limite por IP; mensagem única pra usuário/senha errados | `test_auth_*` |
| S3 | `X-Forwarded-For` forjado pra fugir do limite por IP | uvicorn só honra XFF de proxy listado em `--forwarded-allow-ips` (padrão 127.0.0.1); documentado | `test_auth_*` |
| S4 | Basic auth: senha em cada requisição (log de proxy, histórico do shell, cache de navegador) | **desligado por padrão** (`SIGAA_API_PERMITIR_BASIC=false`); chave da sessão por HMAC com chave do processo, não `sha256(senha)` | `test_auth_*` |
| S5 | token velho continua valendo depois do logout | logout encerra token, pool inteiro (logout no SIGAA) e cache do aluno | `test_auth_*`, `test_isolamento_*` |
| S6 | CSRF | nenhuma rota autentica por cookie (só `Authorization`), então um site de terceiros não consegue "pegar carona" no navegador | `test_http_*` |

### 4.2 Adulteração (Tampering)

| # | ameaça | defesa | teste |
|---|---|---|---|
| T1 | injeção em parâmetros repassados ao SIGAA (ids, filtros de busca, `url` de foto) | validação pydantic/`Query` (ids numéricos, tamanhos), proxy de foto com lista estrita de caminhos | `test_entrada_*` |
| T2 | header injection pelo nome de arquivo vindo do SIGAA (`Content-Disposition`) | nome saneado + `filename*` (RFC 5987) | `test_entrada_*` |
| T3 | envenenamento de cache (resposta de A gravada na chave de B, ou na compartilhada) | chave de aluno = HMAC(segredo, hash do aluno); rotas "compartilhadas" revisadas uma a uma; só 200 sem `Set-Cookie` entra | `test_isolamento_*` |
| T4 | Redis adulterado | entradas de aluno cifradas e autenticadas (Fernet = AES-CBC + HMAC); falha de decifra = ausente | `test_isolamento_*` |

### 4.3 Repúdio

A API não registra quem acessou o quê (por desenho: menos dado pessoal em log). Logs de acesso,
se existirem, são do proxy. Risco aceito e documentado; ações de escrita (seção 7) exigem trilha.

### 4.4 Vazamento de informação (Information disclosure)

| # | ameaça | defesa | teste |
|---|---|---|---|
| I1 | cache servir dado de um aluno pra outro | ver T3; `Cache-Control: private` + `Vary: Authorization` nas respostas de aluno | `test_isolamento_*` |
| I2 | senha/token/cookie em log, exceção, `repr` | filtro de log que mascara `Bearer`/`Basic`/`JSESSIONID`/senha; `repr=False` nos campos sensíveis; erros sem traceback pro cliente | `test_segredos_*` |
| I3 | erro de validação ecoando o corpo (inclusive a senha) | handler de 422 sem o campo `input` | `test_entrada_*` |
| I4 | SSRF/abuso do proxy de fotos pra ler outras telas do SIGAA com a sessão do aluno | lista estrita, sem traversal, só `image/*` | `test_entrada_*` |
| I5 | HTML/SVG vindo do SIGAA servido na origem da API (XSS) | `X-Content-Type-Options: nosniff`, CSP restritiva, tipos ativos como anexo | `test_http_*` |
| I6 | proxy/CDN compartilhado guardando resposta de aluno | `private`/`no-store` em rota com dado pessoal | `test_http_*` |
| I7 | `/v1/status` e `/v1/cache/estatisticas` (sem login) expondo detalhe interno ou por aluno | só agregados | `test_segredos_*`, `test_isolamento_*` |
| I8 | core dump / swap com a senha decifrada | `PR_SET_DUMPABLE=0` no boot (Linux) + `ulimit -c 0` no container; limite de linguagem: `str` do Python não é zerável — documentado | `test_auth_*` |
| I9 | dado pessoal versionado (fixtures, recon, histórico do git) | varredura gitleaks no histórico + CI | CI |

### 4.5 Negação de serviço

| # | ameaça | defesa | teste |
|---|---|---|---|
| D1 | regex catastrófica nos parsers (HTML/PDF do SIGAA ou parâmetro) | regex revisadas; parse fora do event loop com teto | `test_dos_*` |
| D2 | resposta gigante / bomba de descompressão vinda do upstream | teto de bytes por resposta; PDF com teto de páginas | `test_dos_*` |
| D3 | um token disparando dezenas de rotas caras em paralelo, ou `?fresco=true` em laço | limite de concorrência por token e global (fila com teto → 429/503 + `Retry-After`) | `test_dos_*` |
| D4 | usar a API pra martelar a UFBA (rotas públicas, `/v1/status`) | teto global ao SIGAA (`MAX_CONCORRENCIA_SIGAA`), ritmo por sessão, cache do status | `test_dos_*` |
| D5 | crescimento de memória sem limite (dicionários por IP/usuário, sessões) | expurgo periódico e tetos | `test_dos_*`, `test_auth_*` |
| D6 | corpo/query/headers enormes, slowloris | limite de corpo/query na API; slowloris é papel do proxy (documentado) | `test_entrada_*` |

### 4.6 Elevação de privilégio

A API não tem papéis: todo token tem exatamente o poder do aluno no SIGAA. O que existe é
"elevação lateral" (agir como outro aluno), coberta por S1–S5 e T3/I1.

## 5. Suposições (fora do alcance da API)

* Em produção há **HTTPS na frente** (proxy reverso). Sem TLS, senha e token trafegam em claro —
  a API não tem como compensar isso. `SIGAA_API_HSTS=true` quando o proxy terminar o TLS.
* O host é de confiança de quem usa: **o dono do servidor consegue, em tese, ler a senha no
  momento do login** (ela passa em claro pela memória do processo). Quem não confia no servidor
  deve rodar a própria instância. Ver [privacidade](privacidade.md).
* O SIGAA continua aplicando a autorização dele: a API nunca concede acesso a algo que a sessão
  do aluno no SIGAA não teria (ex.: turma de que ele não participa).

## 6. Riscos residuais (aceitos e documentados)

Ver a seção "Riscos que ficaram" em [`README.md`](README.md#riscos-que-ficaram).

## 7. Ações de escrita

O padrão das ações (`feat/acoes`) é revisado à parte quando a frente tiver commits:
confirmação/simulação antes de executar, autorização (token do próprio aluno, nunca Basic),
idempotência (chave de idempotência por ação), CSRF (sem cookie), abuso (limite por aluno, trilha
mínima sem dado pessoal). Parecer em [`acoes.md`](acoes.md).
