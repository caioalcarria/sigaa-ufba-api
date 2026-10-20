# BASELINE — código atual (perf/turbo @ 70a6ea5 + só a pasta bench/)

> Gerado por `bench/rodar_baseline.sh . baseline` (mock fator 1, ±10 % jitter) em 20/10/2026. Pra ter o "depois",
> rode o MESMO script no seu worktree: `~/PROJECTS/UFBA/sigaa-api-perf-bancada/bench/rodar_baseline.sh <worktree> <rotulo> <porta_mock> <porta_api>`.
> Sem latência (só CPU da API): `MOCK_FATOR=0 … -- --sem-frias --alunos auto --duracao 20 --rotas-carga …` → `baseline_cpu.md`.

## Leitura (o que os números dizem)

1. **Cada viagem ao SIGAA custa a latência + 0,25 s de `min_interval`** (o cliente espera 0,25 s contados do FIM da
   viagem anterior). Login = 3,0 s; `/v1/notas` (todas as turmas) = 9,2 s **sempre** (sem cache: quente = fria);
   `/v1/turmas` 3,5 s sempre; `/v1/matricula` 1,4 s sempre.
2. **Só o que passa pelo `memo` fica rápido depois da 1ª vez**: histórico/índices/integralização (4,7 s → 1 ms),
   grade-curricular (11 s → 2 ms), planejamento (14,5 s → 2 ms). O resto não tem cache nenhum.
3. **A trava por sessão serializa o aluno**: 1 aluno com 10 conexões em `/v1/turmas` → p50 **33 s**; com 50 → p50 62 s e
   **24 de 58 em timeout (120 s)**; com 200 → 174 de 208 em timeout. `/v1/notas` idem (190 timeouts com C=200, N=1).
4. **Muitos alunos escalam só até a CPU**: `/v1/turmas` 50 alunos × 50 conexões = 11,3 req/s (p50 4,2 s); com 200 conexões
   = 12 req/s e p50 16,5 s (cada aluno com 4 na fila). Sem latência nenhuma (`baseline_cpu.md`) a API inteira para em
   **~23 req/s em /v1/turmas e ~8 req/s em /v1/notas** — é o parse (BeautifulSoup) no event loop de 1 processo, numa
   máquina de 20 CPUs.
5. **Rotas públicas: teto fixo de ~11 req/s** com qualquer C≥10 (o mock nunca vê mais de 4 em voo): é o
   `MAX_ANONIMOS = 4` + `min_interval=0.35` do `cliente_anonimo()`; com C=200 o p50 vai a 18 s. Sem latência: 26 req/s.
6. **Rota cacheada (histórico quente) aguenta ~4 000 req/s** com 1–10 alunos, mas cai pra 1 800 (C=50, N=50) e 1 380 req/s
   (C=200, N=50, p95 140 ms): 50 sessões disputando o mesmo event loop (serialização do JSON do Historico).
7. O gerador (aiohttp) não é gargalo: 1 323 req/s a C=200 direto no mock (eficiência 1,0).

### Mock × SIGAA real (ponta a ponta pela API)

| rota | mock (este baseline) | real (brief, medição anterior) |
|---|--:|--:|
| login | 3,0 s | ~3,1 s |
| `/v1/historico` (fria) | 4,7 s | ~3,5 s |
| `/v1/matricula` | 1,4 s | ~2,4 s |
| `/v1/grade-curricular` (fria) | 11,1 s | ~8 s |
| `/v1/planejamento/matricula` (fria) | 14,5 s | ~15 s |
| `/v1/notas` (todas as turmas) | 9,2 s | ~17 s (o aluno real tem mais turmas) |
| públicas (`bench/resultados/calibracao_sigaa_real.md`) | 0,18–1,3 s | 0,4–1,6 s (com o intervalo do proxy) |

Mesma ordem de grandeza; o "antes × depois" vale porque as duas pontas rodam no MESMO mock.

---

## Saída do bench

- **data:** 2026-10-20T01:28:27-03:00 · **api:** http://127.0.0.1:8118 (v0.1.0) → SIGAA http://127.0.0.1:8117
- **commit:** c0aa0f3f6ab1 (perf/bancada) · **worktree:** ~/sigaa-api-perf-bancada
- **host:** 20 CPUs · load [3.12, 2.27, 2.62] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **o mock viu (fase fria×quente):** 1317 req · 42 logins · pico 1 em voo · MISS=0 · ViewState inválido=0 · sessões expiradas=0
- **parâmetros:** frias=3 quentes=5 C=[1, 10, 50, 200] alunos=['auto', '1'] (máx 50) req=0 duração=30.0 timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 2572.5 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| sequencial (fase fria) | 42 | 3.02 s | 3.14 s | 2.89 s | 3.19 s | 200×42 |
| carga (até 20 em paralelo) | 342 | 3.20 s | 3.62 s | 2.88 s | 3.79 s | 200×342 |

## Latência fria × quente (por rota)

| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 200 | 4.72 s | 4.78 s | 4.44 s | 4.79 s | 1 ms | 2 ms | 0 ms | 2 ms | 6745.0× |
| `/v1/indices` | 200 | 4.78 s | 5.01 s | 4.65 s | 5.04 s | 0 ms | 1 ms | 0 ms | 1 ms | 9561.6× |
| `/v1/integralizacao` | 200 | 4.81 s | 4.93 s | 4.46 s | 4.94 s | 1 ms | 1 ms | 0 ms | 1 ms | 6875.9× |
| `/v1/matricula` | 200 | 1.39 s | 1.46 s | 1.37 s | 1.47 s | 1.39 s | 1.44 s | 1.32 s | 1.44 s | 1.0× |
| `/v1/turmas` | 200 | 3.59 s | 3.60 s | 3.48 s | 3.60 s | 3.50 s | 3.60 s | 3.39 s | 3.62 s | 1.0× |
| `/v1/portal` | 200 | 680 ms | 719 ms | 669 ms | 723 ms | 707 ms | 744 ms | 658 ms | 746 ms | 1.0× |
| `/v1/me` | 200 | 721 ms | 726 ms | 679 ms | 726 ms | 693 ms | 746 ms | 616 ms | 753 ms | 1.0× |
| `/v1/grade-curricular` | 200 | 11.06 s | 11.20 s | 11.03 s | 11.21 s | 2 ms | 2 ms | 2 ms | 2 ms | 6145.6× |
| `/v1/planejamento/matricula` | 200 | 14.48 s | 14.65 s | 14.12 s | 14.66 s | 2 ms | 2 ms | 2 ms | 2 ms | 7622.8× |
| `/v1/notas` | 200 | 9.15 s | 9.24 s | 9.14 s | 9.25 s | 9.15 s | 9.27 s | 8.93 s | 9.28 s | 1.0× |
| `/v1/frequencia` | 200 | 9.19 s | 9.34 s | 9.09 s | 9.35 s | 9.15 s | 9.32 s | 8.98 s | 9.34 s | 1.0× |
| `/v1/turmas/{turma_id}/notas` | 200 | 4.95 s | 4.98 s | 4.84 s | 4.98 s | 2.10 s | 2.17 s | 2.01 s | 2.20 s | 2.4× |
| `/v1/turmas/{turma_id}` | 200 | 4.27 s | 4.30 s | 4.08 s | 4.30 s | 1.41 s | 1.48 s | 1.29 s | 1.50 s | 3.0× |
| `/v1/documentos/comprovante-inscricao` | 200 | 1.45 s | 1.47 s | 1.38 s | 1.47 s | 1.40 s | 1.48 s | 1.33 s | 1.48 s | 1.0× |
| `/v1/publico/turmas 🔓` | 200 | 699 ms | 710 ms | 694 ms | 711 ms | 701 ms | 783 ms | 680 ms | 799 ms | 1.0× |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | 254 ms | 259 ms | 249 ms | 260 ms | 282 ms | 313 ms | 254 ms | 362 ms | 0.9× |
| `/v1/publico/cursos/{curso_id} 🔓` | 200 | 183 ms | 192 ms | 171 ms | 193 ms | 179 ms | 191 ms | 164 ms | 197 ms | 1.0× |
| `/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id} 🔓` | 200 | 1.30 s | 1.31 s | 1.27 s | 1.31 s | 1.31 s | 1.36 s | 1.24 s | 1.37 s | 1.0× |
| `/v1/publico/cursos/{curso_id}/calendario 🔓` | 200 | 182 ms | 189 ms | 166 ms | 190 ms | 176 ms | 187 ms | 169 ms | 187 ms | 1.0× |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| _teto do cliente (direto no mock)_ | 1 | — | 198 | 198 | 6.6 | 152 ms | 165 ms | 166 ms | 167 ms | 30.0 s | ideal 6.6 req/s · eficiência 1.0 | 200×198 |
| _teto do cliente (direto no mock)_ | 10 | — | 1995 | 1995 | 66.2 | 151 ms | 164 ms | 166 ms | 178 ms | 30.11 s | ideal 66.3 req/s · eficiência 1.0 | 200×1995 |
| _teto do cliente (direto no mock)_ | 50 | — | 9995 | 9995 | 331.4 | 150 ms | 164 ms | 166 ms | 168 ms | 30.16 s | ideal 332.2 req/s · eficiência 1.0 | 200×9995 |
| _teto do cliente (direto no mock)_ | 200 | — | 39884 | 39884 | 1322.8 | 151 ms | 164 ms | 166 ms | 233 ms | 30.15 s | ideal 1327.1 req/s · eficiência 1.0 | 200×39884 |
| `/v1/historico` | 1 | 1 | 71295 | 71295 | 2376.5 | 0 ms | 1 ms | 1 ms | 4.64 s | 30.0 s | 2 · 1 · 0 | 200×71295 |
| `/v1/historico` | 10 | 10 | 121150 | 121150 | 4038.1 | 2 ms | 4 ms | 4 ms | 6.72 s | 30.0 s | 20 · 10 · 0 | 200×121150 |
| `/v1/historico` | 10 | 1 | 117725 | 117725 | 3923.9 | 2 ms | 4 ms | 4 ms | 5.01 s | 30.0 s | 2 · 1 · 0 | 200×117725 |
| `/v1/historico` | 50 | 50 | 53838 | 53838 | 1794.0 | 11 ms | 12 ms | 22 ms | 18.11 s | 30.01 s | 100 · 50 · 0 | 200×53838 |
| `/v1/historico` | 50 | 1 | 128738 | 128738 | 4289.9 | 10 ms | 11 ms | 19 ms | 4.77 s | 30.01 s | 2 · 1 · 0 | 200×128738 |
| `/v1/historico` | 200 | 50 | 41430 | 41430 | 1379.2 | 51 ms | 140 ms | 151 ms | 18.07 s | 30.04 s | 100 · 50 · 0 | 200×41430 |
| `/v1/historico` | 200 | 1 | 115815 | 115815 | 3855.2 | 42 ms | 52 ms | 109 ms | 4.85 s | 30.04 s | 2 · 1 · 0 | 200×115815 |
| `/v1/turmas` | 1 | 1 | 9 | 9 | 0.3 | 3.54 s | 3.58 s | 3.58 s | 3.58 s | 31.79 s | 45 · 1 · 0 | 200×9 |
| `/v1/turmas` | 10 | 10 | 90 | 90 | 2.8 | 3.53 s | 3.78 s | 3.79 s | 3.82 s | 32.05 s | 450 · 10 · 0 | 200×90 |
| `/v1/turmas` | 10 | 1 | 18 | 18 | 0.3 | 33.22 s | 35.10 s | 35.14 s | 35.15 s | 62.98 s | 90 · 1 · 0 | 200×18 |
| `/v1/turmas` | 50 | 50 | 386 | 386 | 11.3 | 4.24 s | 4.61 s | 4.73 s | 4.78 s | 34.08 s | 1930 · 50 · 0 | 200×386 |
| `/v1/turmas` | 50 | 1 | 58 | 34 | 0.4 | 61.82 s | 113.90 s | 118.58 s | 119.75 s | 148.59 s | 211 · 1 · 0 | 200×34 timeout×24 — timeout ×24 |
| `/v1/turmas` | 200 | 50 | 550 | 550 | 12.0 | 16.53 s | 17.19 s | 17.37 s | 17.52 s | 45.99 s | 2750 · 50 · 0 | 200×550 |
| `/v1/turmas` | 200 | 1 | 208 | 34 | 1.4 | 61.26 s | 113.43 s | 118.07 s | 119.23 s | 148.86 s | 212 · 1 · 0 | 200×34 timeout×174 — timeout ×174 |
| `/v1/notas` | 1 | 1 | 4 | 4 | 0.1 | 9.20 s | 9.23 s | 9.24 s | 9.24 s | 36.78 s | 52 · 1 · 0 | 200×4 |
| `/v1/notas` | 10 | 10 | 40 | 40 | 1.1 | 9.20 s | 9.47 s | 9.52 s | 9.55 s | 37.24 s | 520 · 10 · 0 | 200×40 |
| `/v1/notas` | 10 | 1 | 13 | 13 | 0.1 | 63.98 s | 91.45 s | 91.51 s | 91.52 s | 118.77 s | 169 · 1 · 0 | 200×13 |
| `/v1/notas` | 50 | 50 | 150 | 150 | 4.3 | 11.79 s | 12.03 s | 12.10 s | 12.11 s | 35.2 s | 1950 · 50 · 0 | 200×150 |
| `/v1/notas` | 50 | 1 | 53 | 13 | 0.4 | 64.19 s | 113.73 s | 118.08 s | 119.17 s | 147.38 s | 209 · 1 · 0 | 200×13 timeout×40 — timeout ×40 |
| `/v1/notas` | 200 | 50 | 300 | 300 | 4.2 | 40.51 s | 47.57 s | 47.69 s | 47.81 s | 70.9 s | 3900 · 50 · 0 | 200×300 |
| `/v1/notas` | 200 | 1 | 203 | 13 | 1.4 | 64.28 s | 113.22 s | 117.62 s | 118.71 s | 147.89 s | 210 · 1 · 0 | 200×13 timeout×190 — timeout ×190 |
| `/v1/publico/componentes/{componente_id} 🔓` | 1 | — | 110 | 110 | 3.7 | 270 ms | 291 ms | 365 ms | 385 ms | 30.09 s | 221 · 1 · 0 | 200×110 |
| `/v1/publico/componentes/{componente_id} 🔓` | 10 | — | 338 | 338 | 11.0 | 863 ms | 1.14 s | 1.17 s | 1.19 s | 30.76 s | 676 · 4 · 0 | 200×338 |
| `/v1/publico/componentes/{componente_id} 🔓` | 50 | — | 382 | 382 | 11.1 | 4.40 s | 4.71 s | 4.77 s | 4.81 s | 34.38 s | 764 · 4 · 0 | 200×382 |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | — | 528 | 528 | 11.1 | 18.01 s | 18.24 s | 18.30 s | 18.31 s | 47.73 s | 1056 · 4 · 0 | 200×528 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
