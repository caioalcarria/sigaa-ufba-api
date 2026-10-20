# Bench sigaa-api — baseline

- **data:** 2026-10-20T01:02:39-03:00 · **api:** http://127.0.0.1:8182 (v0.1.0) → SIGAA http://127.0.0.1:8181
- **commit:** 1382279cf642 (perf/cache, SUJO) · **worktree:** ~/PROJECTS/UFBA/sigaa-api-perf-cache
- **host:** 20 CPUs · load [3.18, 3.56, 3.61] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 1.2, "redirect": 0.08, "publico": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **parâmetros:** frias=2 quentes=5 C=[1, 10, 50] alunos=['auto', '1'] (máx 50) req=300 duração=40.0 timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, curso_id=1876885, turma_id=393420
- **tempo total:** 1398.5 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| sequencial (fase fria) | 24 | 3.57 s | 3.70 s | 3.37 s | 3.72 s | 200×24 |
| carga (até 20 em paralelo) | 189 | 3.67 s | 4.01 s | 3.38 s | 4.09 s | 200×189 |

## Latência fria × quente (por rota)

| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 200 | 4.64 s | 4.73 s | 4.53 s | 4.75 s | 1 ms | 2 ms | 1 ms | 2 ms | 4637.3× |
| `/v1/indices` | 200 | 4.74 s | 4.98 s | 4.47 s | 5.01 s | 1 ms | 1 ms | 1 ms | 1 ms | 6768.0× |
| `/v1/integralizacao` | 200 | 4.79 s | 4.96 s | 4.60 s | 4.98 s | 1 ms | 2 ms | 0 ms | 2 ms | 4356.0× |
| `/v1/matricula` | 200 | 1.44 s | 1.45 s | 1.43 s | 1.45 s | 1.41 s | 1.47 s | 1.35 s | 1.48 s | 1.0× |
| `/v1/turmas` | 200 | 3.57 s | 3.57 s | 3.57 s | 3.57 s | 3.52 s | 3.60 s | 3.41 s | 3.61 s | 1.0× |
| `/v1/portal` | 200 | 728 ms | 733 ms | 722 ms | 733 ms | 721 ms | 743 ms | 658 ms | 747 ms | 1.0× |
| `/v1/me` | 200 | 702 ms | 717 ms | 684 ms | 719 ms | 703 ms | 733 ms | 664 ms | 737 ms | 1.0× |
| `/v1/notas` | 200 | 9.20 s | 9.25 s | 9.15 s | 9.26 s | 9.07 s | 9.26 s | 8.84 s | 9.35 s | 1.0× |
| `/v1/frequencia` | 200 | 9.09 s | 9.18 s | 9.00 s | 9.19 s | 9.14 s | 9.30 s | 8.93 s | 9.30 s | 1.0× |
| `/v1/turmas/{turma_id}/notas` | 200 | 4.90 s | 4.92 s | 4.89 s | 4.92 s | 2.13 s | 2.17 s | 2.02 s | 2.18 s | 2.3× |
| `/v1/turmas/{turma_id}` | 200 | 4.23 s | 4.31 s | 4.14 s | 4.32 s | 1.43 s | 1.50 s | 1.30 s | 1.51 s | 3.0× |
| `/v1/documentos/comprovante-inscricao` | 200 | 1.43 s | 1.45 s | 1.41 s | 1.46 s | 1.40 s | 1.44 s | 1.36 s | 1.45 s | 1.0× |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/historico` | 1 | 1 | 300 | 300 | 61.4 | 1 ms | 2 ms | 2 ms | 4.59 s | 4.89 s | 200×300 |
| `/v1/historico` | 10 | 10 | 300 | 300 | 45.1 | 4 ms | 987 ms | 5.76 s | 6.47 s | 6.65 s | 200×300 |
| `/v1/historico` | 10 | 1 | 300 | 300 | 60.5 | 4 ms | 36 ms | 4.76 s | 4.76 s | 4.96 s | 200×300 |
| `/v1/historico` | 50 | 50 | 300 | 300 | 16.5 | 142 ms | 13.56 s | 16.93 s | 17.74 s | 18.18 s | 200×300 |
| `/v1/historico` | 50 | 1 | 300 | 300 | 59.7 | 95 ms | 4.49 s | 4.50 s | 4.50 s | 5.02 s | 200×300 |
| `/v1/turmas` | 1 | 1 | 12 | 12 | 0.3 | 3.52 s | 3.61 s | 3.65 s | 3.66 s | 42.2 s | 200×12 |
| `/v1/turmas` | 10 | 10 | 120 | 120 | 2.8 | 3.46 s | 3.91 s | 4.01 s | 4.06 s | 42.27 s | 200×120 |
| `/v1/turmas` | 10 | 1 | 21 | 21 | 0.3 | 34.82 s | 35.21 s | 35.26 s | 35.28 s | 73.67 s | 200×21 |
| `/v1/turmas` | 50 | 50 | 300 | 300 | 11.8 | 4.17 s | 4.58 s | 4.67 s | 4.82 s | 25.44 s | 200×300 |
| `/v1/turmas` | 50 | 1 | 61 | 34 | 0.4 | 61.40 s | 113.34 s | 118.05 s | 119.26 s | 158.49 s | 200×34 timeout×27 — timeout ×27 |
| `/v1/notas` | 1 | 1 | 5 | 5 | 0.1 | 9.17 s | 9.19 s | 9.19 s | 9.19 s | 45.62 s | 200×5 |
| `/v1/notas` | 10 | 10 | 50 | 50 | 1.1 | 9.16 s | 9.51 s | 9.65 s | 9.67 s | 46.27 s | 200×50 |
| `/v1/notas` | 10 | 1 | 14 | 14 | 0.1 | 68.68 s | 91.58 s | 91.61 s | 91.62 s | 128.04 s | 200×14 |
| `/v1/notas` | 50 | 50 | 200 | 200 | 4.1 | 12.32 s | 12.56 s | 12.65 s | 12.72 s | 49.06 s | 200×200 |
| `/v1/notas` | 50 | 1 | 54 | 13 | 0.3 | 64.36 s | 113.38 s | 117.68 s | 118.76 s | 156.92 s | 200×13 timeout×41 — timeout ×41 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
