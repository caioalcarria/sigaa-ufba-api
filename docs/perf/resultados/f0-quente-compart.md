# Bench sigaa-api — f0-quente-compart

- **data:** 2026-10-20T02:02:31-03:00 · **api:** http://127.0.0.1:8124 (v0.1.0) → SIGAA http://127.0.0.1:8125
- **commit:** — (None) · **worktree:** <tmp>
- **host:** 20 CPUs · load [2.88, 2.71, 2.64] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 0.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 10}`
- **parâmetros:** frias=3 quentes=5 C=[200] alunos=['auto'] (máx 200) req=400 duração=120.0 timeout=120.0s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 35.6 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 50 em paralelo) | 400 | 644 ms | 818 ms | 603 ms | 871 ms | 200×400 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/turmas` | 200 | 200 | 400 | 400 | 77.1 | 2.08 s | 3.05 s | 3.61 s | 4.01 s | 5.19 s | 2000 · 1 · 0 | 200×400 |
| `/v1/notas` | 200 | 200 | 400 | 400 | 39.3 | 4.55 s | 7.06 s | 8.41 s | 9.07 s | 10.18 s | 3522 · 1 · 0 | 200×400 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
