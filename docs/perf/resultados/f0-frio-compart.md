# Bench sigaa-api — f0-frio-compart

- **data:** 2026-10-20T01:57:23-03:00 · **api:** http://127.0.0.1:8124 (v0.1.0) → SIGAA http://127.0.0.1:8125
- **commit:** — (None) · **worktree:** <tmp>
- **host:** 20 CPUs · load [3.25, 2.32, 2.53] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 0.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 10}`
- **parâmetros:** frias=3 quentes=5 C=[200] alunos=['auto'] (máx 200) req=400 duração=120.0 timeout=120.0s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 25.8 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 50 em paralelo) | 400 | 636 ms | 791 ms | 603 ms | 856 ms | 200×400 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/turmas` | 200 | 200 | 400 | 400 | 77.3 | 2.01 s | 3.05 s | 3.69 s | 3.85 s | 5.18 s | 2174 · 1 · 0 | 200×400 |
| `/v1/notas` | 200 | 200 | 400 | 400 | 37.0 | 4.34 s | 8.30 s | 9.48 s | 9.69 s | 10.81 s | 3622 · 1 · 0 | 200×400 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
