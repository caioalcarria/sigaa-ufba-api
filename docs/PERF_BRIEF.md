# Missão: deixar a sigaa-api MUITO mais rápida e paralela (branch perf/turbo)

## 🚨 Regras invioláveis
1. **A API de produção NÃO PODE CAIR.** Ela roda em `~/PROJECTS/UFBA/sigaa-api` (branch main) na porta **8000**, usada por outras pessoas.
   - NUNCA mexa em `~/PROJECTS/UFBA/sigaa-api` (nem arquivos, nem `.venv`, nem git checkout lá), NUNCA pare/reinicie nada na porta 8000,
     NUNCA use `pkill`/`fuser -k` genéricos (mate só o PID que VOCÊ criou). Teste em portas 8100–8199.
   - Trabalhe SÓ no seu worktree (`~/PROJECTS/UFBA/sigaa-api-perf-<frente>`, branch `perf/<frente>`), com a sua `.venv` própria
     (`python3 -m venv .venv && .venv/bin/pip install -e ".[api,dev]" requests`).
2. **Não derrube o SIGAA da UFBA.** Carga pesada/alta concorrência = SÓ contra o **SIGAA simulado** (mock/replay da frente "bancada").
   Contra o SIGAA real: no máx. 4 sessões simultâneas suas, nada de laço de estresse, ≥0,15 s entre requisições por sessão.
   "Comportamento Inesperado" manda e-mail pra STI: entenda antes de repetir.
3. **Somente leitura**, como sempre (docs/CONTRATO.md). Dados pessoais nunca entram em arquivo versionado (fixtures anonimizadas).
4. **Commits:** identidade `Caio Alcarria <caioalcarria@users.noreply.github.com>`. **NUNCA** `Co-Authored-By: Claude` nem "Generated with Claude Code".
   Não faça push; o orquestrador (dot-38-7332) integra no `perf/turbo`.
5. Todo ganho tem que vir com NÚMERO (antes × depois) e com os 175+ testes passando.

## O que já medimos (baseline, SIGAA real)
| etapa | tempo |
|---|---|
| 1 ida/volta ao SIGAA (GET portal, 38 KB) | ~450 ms |
| login (3 requisições + aviso) | ~3,1 s |
| emitir histórico (o SIGAA gera o PDF) | ~3,6 s |
| BeautifulSoup do portal | ~5 ms · parse_portal ~8 ms |
| parse do histórico PDF (pdfplumber) | ~300 ms |
| e2e: /historico 3,5 s · /matricula 2,4 s · /grade-curricular 8 s · /planejamento 15 s · /notas (todas as turmas) 17 s |

**Conclusão:** o tempo está nas VIAGENS ao SIGAA (quantidade × ~450 ms, todas em série por causa da trava por sessão), não no parse.

## Alavancas (cada frente tem as suas)
- menos viagens (atalhos GET diretos, reaproveitar o ViewState do portal em vez de rebaixar o portal a cada `menu()`)
- várias viagens AO MESMO TEMPO: **pool de sessões SIGAA por aluno** (cada JSESSIONID tem seu estado JSF → navegações independentes em paralelo)
- não repetir: cache por aluno (TTL, stale-while-revalidate), cache COMPARTILHADO entre alunos pro que é público/estático
  (estruturas, componentes, oferta, calendário, docentes), *singleflight* (pedidos iguais simultâneos = 1 busca), pré-aquecimento após o login
- servidor aguentar muita concorrência: event loop livre (parse pesado em thread), orjson, gzip, uvloop/httptools

## Arquitetura de hoje (leia antes)
`sigaa/client.py` (SigaaClient: `_req` com `min_interval`, `lock`, `executar()`, `memo()`), `api/sessions.py` (Gerenciador: token → 1 SigaaClient),
`api/deps.py`, `sigaa/services/*.py` (navegação), `sigaa/parsers/*.py` (puros). `recon/sess.py` faz login com a credencial do LastPass sem exibi-la
(`_cred()`); `recon/*_e2e.py` validam contra o SIGAA real.
