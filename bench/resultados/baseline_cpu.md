# Bench sigaa-api — baseline_cpu

- **data:** 2026-10-20T01:38:36-03:00 · **api:** http://127.0.0.1:8118 (v0.1.0) → SIGAA http://127.0.0.1:8117
- **commit:** c0aa0f3f6ab1 (perf/bancada) · **worktree:** ~/PROJECTS/UFBA/sigaa-api-perf-bancada
- **host:** 20 CPUs · load [5.7, 4.33, 3.47] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 0.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **parâmetros:** frias=3 quentes=5 C=[1, 10, 50, 200] alunos=['auto'] (máx 50) req=0 duração=20.0 timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 574.5 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| carga (até 20 em paralelo) | 444 | 892 ms | 1.14 s | 528 ms | 1.19 s | 200×444 |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| _teto do cliente (direto no mock)_ | 1 | — | 121473 | 121473 | 6073.6 | 0 ms | 0 ms | 1 ms | 55 ms | 20.0 s | ideal 10000.0 req/s · eficiência 0.61 | 200×121473 |
| _teto do cliente (direto no mock)_ | 10 | — | 278954 | 278954 | 13947.2 | 1 ms | 1 ms | 1 ms | 168 ms | 20.0 s | ideal 16666.7 req/s · eficiência 0.84 | 200×278954 |
| _teto do cliente (direto no mock)_ | 50 | — | 279807 | 279807 | 13988.0 | 3 ms | 4 ms | 7 ms | 269 ms | 20.0 s | ideal 14705.9 req/s · eficiência 0.95 | 200×279807 |
| _teto do cliente (direto no mock)_ | 200 | — | 245870 | 245870 | 12285.3 | 15 ms | 17 ms | 28 ms | 472 ms | 20.01 s | ideal 13605.4 req/s · eficiência 0.9 | 200×245870 |
| `/v1/historico` | 1 | 1 | 53749 | 53749 | 2687.4 | 0 ms | 1 ms | 1 ms | 754 ms | 20.0 s | 2 · 1 · 0 | 200×53749 |
| `/v1/historico` | 10 | 10 | 92371 | 92371 | 4618.1 | 2 ms | 3 ms | 4 ms | 3.03 s | 20.0 s | 20 · 1 · 0 | 200×92371 |
| `/v1/historico` | 50 | 50 | 27971 | 27971 | 1397.8 | 11 ms | 12 ms | 22 ms | 13.92 s | 20.01 s | 100 · 1 · 0 | 200×27971 |
| `/v1/historico` | 200 | 50 | 19191 | 19191 | 957.9 | 52 ms | 137 ms | 8.18 s | 14.18 s | 20.03 s | 100 · 1 · 0 | 200×19191 |
| `/v1/turmas` | 1 | 1 | 16 | 16 | 0.8 | 1.26 s | 1.28 s | 1.30 s | 1.30 s | 20.16 s | 80 · 1 · 0 | 200×16 |
| `/v1/turmas` | 10 | 10 | 160 | 160 | 7.7 | 1.27 s | 1.36 s | 1.38 s | 1.41 s | 20.72 s | 800 · 1 · 0 | 200×160 |
| `/v1/turmas` | 50 | 50 | 500 | 500 | 23.7 | 2.10 s | 2.44 s | 2.53 s | 2.58 s | 21.13 s | 2500 · 1 · 0 | 200×500 |
| `/v1/turmas` | 200 | 50 | 636 | 636 | 22.4 | 8.79 s | 9.31 s | 9.41 s | 9.53 s | 28.38 s | 3180 · 1 · 0 | 200×636 |
| `/v1/notas` | 1 | 1 | 7 | 7 | 0.3 | 3.27 s | 3.30 s | 3.31 s | 3.31 s | 22.95 s | 91 · 1 · 0 | 200×7 |
| `/v1/notas` | 10 | 10 | 60 | 60 | 2.9 | 3.41 s | 3.52 s | 3.56 s | 3.56 s | 20.71 s | 780 · 1 · 0 | 200×60 |
| `/v1/notas` | 50 | 50 | 200 | 200 | 7.9 | 6.12 s | 6.96 s | 7.09 s | 7.17 s | 25.46 s | 2600 · 1 · 0 | 200×200 |
| `/v1/notas` | 200 | 50 | 340 | 340 | 7.7 | 24.53 s | 26.84 s | 27.46 s | 27.51 s | 44.4 s | 4420 · 1 · 0 | 200×340 |
| `/v1/turmas/{turma_id}/notas` | 1 | 1 | 26 | 26 | 1.3 | 756 ms | 758 ms | 1.51 s | 1.77 s | 20.67 s | 82 · 1 · 0 | 200×26 |
| `/v1/turmas/{turma_id}/notas` | 10 | 10 | 250 | 250 | 12.1 | 758 ms | 916 ms | 1.89 s | 1.91 s | 20.64 s | 790 · 1 · 0 | 200×250 |
| `/v1/turmas/{turma_id}/notas` | 50 | 50 | 646 | 646 | 29.5 | 1.55 s | 2.63 s | 3.05 s | 3.16 s | 21.91 s | 2138 · 1 · 0 | 200×646 |
| `/v1/turmas/{turma_id}/notas` | 200 | 50 | 752 | 752 | 28.5 | 6.40 s | 7.44 s | 8.04 s | 8.59 s | 26.42 s | 2456 · 1 · 0 | 200×752 |
| `/v1/publico/componentes/{componente_id} 🔓` | 1 | — | 508 | 508 | 25.4 | 36 ms | 46 ms | 129 ms | 223 ms | 20.03 s | 1016 · 1 · 0 | 200×508 |
| `/v1/publico/componentes/{componente_id} 🔓` | 10 | — | 530 | 530 | 26.0 | 373 ms | 496 ms | 534 ms | 572 ms | 20.38 s | 1060 · 1 · 0 | 200×530 |
| `/v1/publico/componentes/{componente_id} 🔓` | 50 | — | 565 | 565 | 25.9 | 1.92 s | 2.08 s | 2.14 s | 2.17 s | 21.8 s | 1130 · 1 · 0 | 200×565 |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | — | 746 | 746 | 27.8 | 7.10 s | 7.29 s | 7.80 s | 8.08 s | 26.82 s | 1492 · 1 · 0 | 200×746 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
