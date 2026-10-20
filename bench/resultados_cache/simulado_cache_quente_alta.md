# Bench sigaa-api — cache-sem-preaq-quente-alta

- **data:** 2026-10-20T01:00:35-03:00 · **api:** http://127.0.0.1:8184 (v0.1.0) → SIGAA http://127.0.0.1:8181
- **commit:** 1382279cf642 (perf/cache, SUJO) · **worktree:** ~/PROJECTS/UFBA/sigaa-api-perf-cache
- **host:** 20 CPUs · load [4.09, 3.83, 3.7] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 1.2, "redirect": 0.08, "publico": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **parâmetros:** frias=3 quentes=5 C=[50, 200] alunos=['50'] (máx 50) req=20000 duração=20.0 timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, curso_id=1876885, turma_id=393420
- **tempo total:** 230.8 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 50 em paralelo) | 300 | 4.59 s | 4.76 s | 3.73 s | 4.88 s | 200×300 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/historico` | 50 | 50 | 20000 | 20000 | 1097.7 | 34 ms | 125 ms | 190 ms | 427 ms | 18.22 s | 200×20000 |
| `/v1/historico` | 200 | 50 | 14798 | 14798 | 732.7 | 194 ms | 785 ms | 1.21 s | 2.32 s | 20.2 s | 200×14798 |
| `/v1/turmas` | 50 | 50 | 18255 | 18255 | 911.3 | 38 ms | 155 ms | 277 ms | 835 ms | 20.03 s | 200×18255 |
| `/v1/turmas` | 200 | 50 | 13213 | 13213 | 654.2 | 207 ms | 899 ms | 1.54 s | 4.37 s | 20.2 s | 200×13213 |
| `/v1/notas` | 50 | 50 | 18540 | 18540 | 925.2 | 38 ms | 154 ms | 270 ms | 734 ms | 20.04 s | 200×18540 |
| `/v1/notas` | 200 | 50 | 14049 | 14049 | 696.0 | 192 ms | 856 ms | 1.44 s | 3.60 s | 20.19 s | 200×14049 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
