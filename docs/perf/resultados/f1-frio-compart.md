# Bench sigaa-api — f1-frio-compart

- **data:** 2026-10-20T01:56:39-03:00 · **api:** http://127.0.0.1:8122 (v0.1.0) → SIGAA http://127.0.0.1:8120
- **commit:** — (None) · **worktree:** <tmp>
- **host:** 20 CPUs · load [2.07, 1.99, 2.44] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 10}`
- **parâmetros:** frias=3 quentes=5 C=[200] alunos=['auto'] (máx 200) req=400 duração=120.0 timeout=120.0s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 139.0 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 50 em paralelo) | 400 | 2.84 s | 3.42 s | 2.64 s | 3.77 s | 200×400 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/turmas` | 200 | 200 | 400 | 400 | 10.9 | 16.23 s | 23.39 s | 27.62 s | 27.92 s | 36.71 s | 2236 · 244 · 0 | 200×400 |
| `/v1/notas` | 200 | 200 | 400 | 400 | 7.3 | 23.80 s | 41.53 s | 45.24 s | 47.32 s | 54.67 s | 3672 · 256 · 0 | 200×400 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
