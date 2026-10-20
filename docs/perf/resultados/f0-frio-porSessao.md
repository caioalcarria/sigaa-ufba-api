# Bench sigaa-api — f0-frio-porSessao

- **data:** 2026-10-20T01:56:57-03:00 · **api:** http://127.0.0.1:8123 (v0.1.0) → SIGAA http://127.0.0.1:8125
- **commit:** — (None) · **worktree:** <tmp>
- **host:** 20 CPUs · load [2.72, 2.14, 2.48] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 0.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 10}`
- **parâmetros:** frias=3 quentes=5 C=[200] alunos=['auto'] (máx 200) req=400 duração=120.0 timeout=120.0s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 18.4 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 50 em paralelo) | 400 | 640 ms | 697 ms | 603 ms | 712 ms | 200×400 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/turmas` | 200 | 200 | 400 | 400 | 114.8 | 1.60 s | 1.96 s | 2.03 s | 2.03 s | 3.49 s | 2210 · 1 · 0 | 200×400 |
| `/v1/notas` | 200 | 200 | 400 | 400 | 63.0 | 2.54 s | 4.71 s | 4.97 s | 5.01 s | 6.35 s | 3967 · 1 · 0 | 200×400 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
