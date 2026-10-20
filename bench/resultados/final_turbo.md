# Bench sigaa-api — turbo

- **data:** 2026-10-20T02:57:15-03:00 · **api:** http://127.0.0.1:8153 (v0.1.0) → SIGAA http://127.0.0.1:8151
- **commit:** 544740939f19 (perf/turbo) · **worktree:** ~/PROJECTS/UFBA/sigaa-api-perf
- **host:** 20 CPUs · load [1.59, 1.47, 1.48] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **o mock viu (fase fria×quente):** 715 req · 88 logins · pico 3 em voo · MISS=0 · ViewState inválido=0 · sessões expiradas=0
- **parâmetros:** frias=3 quentes=5 C=[1, 10, 50, 200] alunos=['auto'] (máx 50) req=200 duração=None timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 432.5 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| sequencial (fase fria) | 42 | 2.80 s | 2.91 s | 2.69 s | 2.94 s | 200×42 |
| carga (até 20 em paralelo) | 333 | 2.80 s | 2.91 s | 2.60 s | 2.95 s | 200×333 |

## Latência fria × quente (por rota)

| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 200 | 3.58 s | 3.95 s | 3.55 s | 3.99 s | 0 ms | 1 ms | 0 ms | 1 ms | 17895.0× |
| `/v1/indices` | 200 | 3.55 s | 3.97 s | 3.52 s | 4.02 s | 0 ms | 1 ms | 0 ms | 1 ms | 11830.0× |
| `/v1/integralizacao` | 200 | 3.71 s | 3.97 s | 3.63 s | 4.00 s | 0 ms | 1 ms | 0 ms | 1 ms | 9276.7× |
| `/v1/matricula` | 200 | 636 ms | 640 ms | 603 ms | 640 ms | 0 ms | 1 ms | 0 ms | 1 ms | 1590.5× |
| `/v1/turmas` | 200 | 2.99 s | 3.05 s | 2.97 s | 3.06 s | 0 ms | 1 ms | 0 ms | 1 ms | 7481.7× |
| `/v1/portal` | 200 | 629 ms | 644 ms | 624 ms | 646 ms | 0 ms | 1 ms | 0 ms | 1 ms | 1257.2× |
| `/v1/me` | 200 | 606 ms | 642 ms | 577 ms | 646 ms | 0 ms | 1 ms | 0 ms | 1 ms | 1515.2× |
| `/v1/grade-curricular` | 200 | 3.94 s | 7.19 s | 3.45 s | 7.55 s | 0 ms | 1 ms | 0 ms | 1 ms | 9854.2× |
| `/v1/planejamento/matricula` | 200 | 3.91 s | 5.22 s | 3.41 s | 5.37 s | 0 ms | 0 ms | 0 ms | 0 ms | 13043.7× |
| `/v1/notas` | 200 | 4.78 s | 4.78 s | 4.71 s | 4.78 s | 0 ms | 1 ms | 0 ms | 1 ms | 9556.0× |
| `/v1/frequencia` | 200 | 4.89 s | 4.91 s | 4.81 s | 4.92 s | 0 ms | 1 ms | 0 ms | 1 ms | 16290.7× |
| `/v1/turmas/{turma_id}/notas` | 200 | 3.65 s | 3.75 s | 3.53 s | 3.76 s | 0 ms | 1 ms | 0 ms | 1 ms | 7306.6× |
| `/v1/turmas/{turma_id}` | 200 | 3.06 s | 3.10 s | 2.98 s | 3.11 s | 1 ms | 1 ms | 0 ms | 1 ms | 5099.8× |
| `/v1/documentos/comprovante-inscricao` | 200 | 609 ms | 643 ms | 579 ms | 647 ms | 0 ms | 1 ms | 0 ms | 1 ms | 2030.7× |
| `/v1/publico/turmas 🔓` | 200 | 0 ms | 486 ms | 0 ms | 540 ms | 0 ms | 0 ms | 0 ms | 0 ms | 2.0× |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | 0 ms | 230 ms | 0 ms | 256 ms | 0 ms | 1 ms | 0 ms | 1 ms | 0.5× |
| `/v1/publico/cursos/{curso_id} 🔓` | 200 | 0 ms | 147 ms | 0 ms | 163 ms | 0 ms | 1 ms | 0 ms | 1 ms | 1.2× |
| `/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id} 🔓` | 200 | 0 ms | 963 ms | 0 ms | 1.07 s | 0 ms | 1 ms | 0 ms | 1 ms | 2.0× |
| `/v1/publico/cursos/{curso_id}/calendario 🔓` | 200 | 0 ms | 143 ms | 0 ms | 159 ms | 0 ms | 1 ms | 0 ms | 1 ms | 1.0× |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/historico` | 1 | 1 | 200 | 200 | 54.7 | 0 ms | 0 ms | 1 ms | 3.61 s | 3.65 s | 6 · 2 · 0 | 200×200 |
| `/v1/historico` | 10 | 10 | 200 | 200 | 52.5 | 1 ms | 585 ms | 3.57 s | 3.80 s | 3.81 s | 60 · 20 · 0 | 200×200 |
| `/v1/historico` | 50 | 50 | 200 | 200 | 45.2 | 66 ms | 3.73 s | 3.87 s | 4.42 s | 4.42 s | 153 · 69 · 0 | 200×200 |
| `/v1/historico` | 200 | 50 | 200 | 200 | 49.7 | 3.60 s | 4.00 s | 4.02 s | 4.02 s | 4.02 s | 113 · 69 · 0 | 200×200 |
| `/v1/turmas` | 1 | 1 | 200 | 200 | 65.9 | 0 ms | 0 ms | 0 ms | 3.00 s | 3.04 s | 10 · 2 · 0 | 200×200 |
| `/v1/turmas` | 10 | 10 | 200 | 200 | 64.5 | 1 ms | 334 ms | 2.97 s | 3.09 s | 3.1 s | 100 · 20 · 0 | 200×200 |
| `/v1/turmas` | 50 | 50 | 200 | 200 | 65.8 | 71 ms | 2.94 s | 2.99 s | 3.04 s | 3.04 s | 250 · 50 · 0 | 200×200 |
| `/v1/turmas` | 200 | 50 | 200 | 200 | 66.7 | 1.53 s | 2.98 s | 2.99 s | 3.00 s | 3.0 s | 252 · 49 · 0 | 200×200 |
| `/v1/notas` | 1 | 1 | 200 | 200 | 41.3 | 0 ms | 0 ms | 0 ms | 4.81 s | 4.84 s | 20 · 3 · 0 | 200×200 |
| `/v1/notas` | 10 | 10 | 200 | 200 | 41.5 | 1 ms | 433 ms | 4.76 s | 4.81 s | 4.82 s | 200 · 30 · 0 | 200×200 |
| `/v1/notas` | 50 | 50 | 200 | 200 | 30.6 | 271 ms | 6.10 s | 6.49 s | 6.54 s | 6.54 s | 698 · 78 · 0 | 200×200 |
| `/v1/notas` | 200 | 50 | 200 | 200 | 30.1 | 4.86 s | 6.42 s | 6.63 s | 6.64 s | 6.64 s | 711 · 76 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 1 | — | 200 | 200 | 5084.0 | 0 ms | 0 ms | 1 ms | 1 ms | 0.04 s | 0 · 0 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 10 | — | 200 | 200 | 15384.5 | 1 ms | 1 ms | 1 ms | 1 ms | 0.01 s | 0 · 0 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 50 | — | 200 | 200 | 15571.9 | 3 ms | 4 ms | 4 ms | 4 ms | 0.01 s | 0 · 0 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | — | 200 | 200 | 16223.0 | 7 ms | 7 ms | 7 ms | 7 ms | 0.01 s | 0 · 0 · 0 | 200×200 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
