# Bench sigaa-api — f0-quente-porSessao

- **data:** 2026-10-20T02:01:56-03:00 · **api:** http://127.0.0.1:8123 (v0.1.0) → SIGAA http://127.0.0.1:8125
- **commit:** — (None) · **worktree:** <tmp>
- **host:** 20 CPUs · load [2.68, 2.64, 2.61] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 0.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 10}`
- **parâmetros:** frias=3 quentes=5 C=[200] alunos=['auto'] (máx 200) req=400 duração=120.0 timeout=120.0s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 23.6 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 50 em paralelo) | 400 | 638 ms | 700 ms | 603 ms | 741 ms | 200×400 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/turmas` | 200 | 200 | 400 | 400 | 113.9 | 1.66 s | 1.82 s | 1.90 s | 1.91 s | 3.51 s | 2000 · 1 · 0 | 200×400 |
| `/v1/notas` | 200 | 200 | 400 | 400 | 75.3 | 2.18 s | 3.49 s | 3.49 s | 3.54 s | 5.31 s | 3335 · 1 · 0 | 200×400 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
