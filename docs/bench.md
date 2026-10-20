# Bancada de medição (SIGAA simulado + bench)

Tudo em `bench/`. Serve pra medir a sigaa-api **sem tocar no SIGAA da UFBA**: a API roda numa porta
81xx apontada pra um SIGAA de mentira local, que responde com as mesmas telas e as mesmas regras de
sessão do real, com latência configurável.

## Peças

| arquivo | o que é |
|---|---|
| `bench/mock_sigaa.py` | o SIGAA simulado (Starlette/uvicorn, 1 processo asyncio) |
| `bench/sintetico.py` | PDFs sintéticos (histórico com 45 componentes em 2 páginas + declaração de vínculo) |
| `bench/_lancador.py` | sobe a API de QUALQUER worktree apontada pro mock, sem vazar pro SIGAA real |
| `bench/bench.py` | mede latência fria/quente e carga (N alunos × C conexões) → markdown + JSON |
| `bench/api_instancia.sh` | sobe/para uma instância da API (usa o `_lancador.py`) |
| `bench/gravar.py` | proxy gravador (pra calibrar com páginas PÚBLICAS do SIGAA real) |
| `bench/resultados/` | resultados versionados (`baseline.md`, …) |

## Uso rápido

```bash
cd ~/PROJECTS/UFBA/sigaa-api-perf-<frente>
# 1) o SIGAA simulado (cada frente sobe o SEU, na SUA faixa de portas)
~/PROJECTS/UFBA/sigaa-api-perf-bancada/.venv/bin/python ~/PROJECTS/UFBA/sigaa-api-perf-bancada/bench/mock_sigaa.py --porta 8121 &
# 2) a API do SEU worktree apontada pro mock (bloqueia https: nada escapa pra UFBA)
.venv/bin/python ~/PROJECTS/UFBA/sigaa-api-perf-bancada/bench/_lancador.py --worktree . --porta 8122 --sigaa http://127.0.0.1:8121 &
# 3) medir
.venv/bin/python ~/PROJECTS/UFBA/sigaa-api-perf-bancada/bench/bench.py --api http://127.0.0.1:8122 --mock http://127.0.0.1:8121 --rapido
```

Faixas de porta sugeridas (pra ninguém pisar em ninguém): bancada 8110–8119 · sessões 8120–8129 ·
cache 8130–8139 · cpu 8140–8149 · orquestrador 8150–8159. **Nunca a 8000** (produção).

## O SIGAA simulado

* **Telas**: as fixtures anonimizadas de `tests/fixtures/**` (HTML real do SIGAA com dados fictícios)
  + PDFs sintéticos. Nenhum dado pessoal. Fixtures salvas em UTF-8 são servidas em ISO-8859-1, como o real.
* **Login**: `GET verTelaLogin.do` → `POST logar.do?dispatch=logOn` (302) → `telaAvisoLogon.jsf`
  (form "Continuar") → 302 → `portais/discente/discente.jsf`. Qualquer usuário entra; senha `errada`
  → "Usuário e/ou senha inválidos" (a API devolve 401 `credenciais_invalidas`).
* **Sessão**: cookie `JSESSIONID` próprio; sem sessão/ociosa há mais de `--ttl-sessao` (padrão 1800 s)
  → 302 pra `/sigaa/expirada.jsp` (a API reloga sozinha com `lembrar=true`, senão 401 `sessao_expirada`).
  `logar.do?dispatch=logOff` mata a sessão.
* **ViewState**: cada tela servida ganha um `j_idN` NOVO da sessão; a sessão lembra as últimas
  `--views` (padrão 20). POST com ViewState que a sessão não emitiu (ou que saiu da janela) →
  "O endereço digitado não é válido" (a API devolve 502 `navegacao_invalida`).
* **Navegação**: menu JSCook do portal (`jscook_action`), cliques `jsfcljs` (o mock descobre QUAL link
  da tela de origem foi clicado), submits de formulário, GETs diretos (turmas.jsf, mobile, painéis,
  páginas públicas). Abrir uma turma guarda o `frontEndIdTurma` na sessão (estado JSF por sessão).
* **Tela não mapeada** → "Comportamento Inesperado" (a API devolve 502) e o pedido aparece em
  `GET /__mock/stats` → `misses`. Rota nova da API que navega diferente = MISS: adicione a regra em
  `bench/mock_sigaa.py` (tabelas `MENU`, `CLIQUES`, `SUBMITS`, `GETS`, `TV_MENU`).

### Latência (padrão; tudo × `--fator`, com `--jitter` ±10 %)

| classe | s | quando |
|---|---|---|
| `padrao` | 0,45 | qualquer tela |
| `pdf` | 3,5 | histórico / declaração (o SIGAA gerando o PDF) |
| `login` | 0,7 | o POST `logar.do` (login inteiro ≈ 3 s, como no real) |
| `redirect` | 0,08 | 302 sem trabalho |
| `publico` | 0,15 | telas públicas (medido: mediana 95 ms) |
| `publico_pesado` | 0,45 | `curriculo.jsf` (medido ~430 ms) |
| `ajax` | 0,25 | painéis `view_painel.jsf?ajaxRequest=true` |

`--lat pdf=3.6 --lat padrao=0.5` muda uma classe; `--fator 0` zera tudo (mede só a CPU da API);
`--max-concorrencia N` faz o "servidor" atender no máximo N respostas ao mesmo tempo (fila) — pra
simular o SIGAA saturado.

### Controle em tempo real

```
GET  /__mock/config            → parâmetros atuais
POST /__mock/config  {"fator":1,"jitter":0.1,"latencias":{"pdf":3.5},"max_concorrencia":0,"ttl_sessao":1800,"views":20}
GET  /__mock/stats             → requisições por regra/caminho, misses, sessões, pico de concorrência
POST /__mock/reset             → zera as estatísticas
POST /__mock/expirar           → derruba todas as sessões (testa o relogin)
```

### Rotas da API cobertas (verificado: 200 contra o mock)

Login/logout · `/v1/me` `/v1/portal` `/v1/me/dados-pessoais` `/v1/me/perfil` `/v1/modulos` `/v1/turmas`
`/v1/grade-horaria` `/v1/atividades` `/v1/atualizacoes` · `/v1/turmas-virtuais` `/v1/turmas/{id}` e
`/notas` `/frequencia` `/noticias` `/aulas` `/avaliacoes` `/tarefas` `/plano-de-curso` `/conteudos`
`/participantes` `/docentes` `/forum` `/estatisticas` · `/v1/notas` `/v1/frequencia` `/v1/tarefas`
`/v1/avaliacoes` · `/v1/historico` (+`/pdf`, `/componentes`) `/v1/indices` `/v1/integralizacao`
`/v1/pendencias` `/v1/matricula` (+`/processamento`) `/v1/documentos/comprovante-inscricao`
`/v1/documentos/declaracao-vinculo` `/v1/trancamentos` `/v1/suspensoes` `/v1/atividades-autonomas`
`/v1/aproveitamentos` `/v1/diploma` `/v1/avaliacao-institucional` · `/v1/grade-curricular`
`/v1/planejamento/matricula` `/v1/carga-horaria` · `/v1/calendario` (+`/lista`) · `/v1/consultas/componentes/{id}`
`/v1/consultas/estruturas` (+`/{id}`) `/v1/consultas/turmas` (+`/filtros`) · públicas: `/v1/publico/cursos`
(+`/{id}`, `/estruturas`, `/estruturas/{id}`, `/calendario`) `/v1/publico/componentes/{id}`
`/v1/publico/componentes/codigo/{codigo}` `/v1/publico/turmas` `/v1/publico/unidades`.

IDs que existem nas fixtures: turma virtual `393420` (e as de `/v1/turmas-virtuais`), componente `44697`
(MATA37), curso `1876885` (SI), estrutura `2421505` (G20251X), unidade `1114` (DCC).

## Segurança (por que `_lancador.py`)

`sigaa/services/consultas.py::cliente_anonimo()` cria `SigaaClient()` **sem `base_url`** → as rotas
`/v1/publico/*` iriam no SIGAA **real** mesmo com `SIGAA_URL` apontado pro mock. O lançador troca o
padrão do construtor antes de importar a API e põe `HTTPS_PROXY` num buraco negro (127.0.0.1:9): se
algo ainda tentar `https://sigaa.ufba.br`, falha na hora. **Não rode carga com `uvicorn api.main:app`
direto.** (Correção definitiva sugerida no código: `cliente_anonimo` usar `config.SIGAA_URL`.)

## Limitações conhecidas

* As telas são as MESMAS pra todo aluno (o mock não personaliza por usuário) e a turma virtual
  serve um conjunto fixo de páginas (a principal varia por turma entre 4 fixtures).
* Latência dos fluxos LOGADOS vem do brief (medição anterior) — a calibração nova (`bench/resultados/calibracao_sigaa_real.md`) só pôde usar
  páginas PÚBLICAS (o login com a credencial do Caio foi bloqueado pelo classificador de dados
  pessoais e o orquestrador decidiu não gravar telas logadas).
* O PDF sintético tem 2 páginas/45 componentes: parse ≈ 220 ms (o real ≈ 300 ms).
* Concorrência DENTRO de uma mesma sessão: o mock não serializa nem quebra (o real pode misturar
  estado de bean JSF); a regra de ViewState com janela de 20 telas é uma aproximação do JSF.
