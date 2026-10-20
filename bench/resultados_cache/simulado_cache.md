# Bench sigaa-api — cache

- **data:** 2026-10-20T00:46:07-03:00 · **api:** http://127.0.0.1:8183 (v0.1.0) → SIGAA http://127.0.0.1:8181
- **commit:** 1382279cf642 (perf/cache, SUJO) · **worktree:** ~/PROJECTS/UFBA/sigaa-api-perf-cache
- **host:** 20 CPUs · load [3.53, 3.75, 3.76] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 1.2, "redirect": 0.08, "publico": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **parâmetros:** frias=2 quentes=5 C=[1, 10, 50] alunos=['auto', '1'] (máx 50) req=300 duração=40.0 timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, curso_id=1876885, turma_id=393420
- **tempo total:** 406.6 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| sequencial (fase fria) | 24 | 3.53 s | 3.68 s | 3.37 s | 3.70 s | 200×24 |
| carga (até 20 em paralelo) | 189 | 3.76 s | 4.05 s | 3.37 s | 4.15 s | 200×189 |

## Latência fria × quente (por rota)

| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 200 | 4.67 s | 4.88 s | 4.43 s | 4.91 s | 1 ms | 2 ms | 1 ms | 2 ms | 5838.9× |
| `/v1/indices` | 200 | 4.84 s | 4.96 s | 4.70 s | 4.98 s | 1 ms | 1 ms | 0 ms | 1 ms | 5376.8× |
| `/v1/integralizacao` | 200 | 4.73 s | 4.96 s | 4.48 s | 4.98 s | 1 ms | 2 ms | 0 ms | 2 ms | 5257.4× |
| `/v1/matricula` | 200 | 1.39 s | 1.40 s | 1.38 s | 1.40 s | 1 ms | 1 ms | 1 ms | 1 ms | 1544.6× |
| `/v1/turmas` | 200 | 3.50 s | 3.58 s | 3.42 s | 3.59 s | 1 ms | 1 ms | 1 ms | 1 ms | 3890.6× |
| `/v1/portal` | 200 | 713 ms | 737 ms | 686 ms | 740 ms | 1 ms | 2 ms | 1 ms | 2 ms | 712.8× |
| `/v1/me` | 200 | 713 ms | 719 ms | 707 ms | 720 ms | 1 ms | 1 ms | 0 ms | 1 ms | 1018.9× |
| `/v1/notas` | 200 | 9.12 s | 9.22 s | 9.00 s | 9.23 s | 1 ms | 1 ms | 1 ms | 1 ms | 11398.4× |
| `/v1/frequencia` | 200 | 8.99 s | 9.02 s | 8.96 s | 9.02 s | 1 ms | 1 ms | 0 ms | 1 ms | 14980.3× |
| `/v1/turmas/{turma_id}/notas` | 200 | 4.92 s | 4.96 s | 4.87 s | 4.96 s | 1 ms | 1 ms | 1 ms | 1 ms | 4917.5× |
| `/v1/turmas/{turma_id}` | 200 | 4.26 s | 4.29 s | 4.23 s | 4.30 s | 1 ms | 2 ms | 1 ms | 2 ms | 4260.9× |
| `/v1/documentos/comprovante-inscricao` | 200 | 1.43 s | 1.46 s | 1.40 s | 1.47 s | 1 ms | 1 ms | 1 ms | 1 ms | 1591.0× |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/historico` | 1 | 1 | 300 | 300 | 60.9 | 1 ms | 1 ms | 2 ms | 4.72 s | 4.93 s | 200×300 |
| `/v1/historico` | 10 | 10 | 300 | 300 | 43.3 | 4 ms | 1.13 s | 5.89 s | 6.73 s | 6.92 s | 200×300 |
| `/v1/historico` | 10 | 1 | 300 | 300 | 59.9 | 4 ms | 33 ms | 4.78 s | 4.78 s | 5.01 s | 200×300 |
| `/v1/historico` | 50 | 50 | 300 | 300 | 15.6 | 149 ms | 14.42 s | 17.74 s | 18.77 s | 19.23 s | 200×300 |
| `/v1/historico` | 50 | 1 | 300 | 300 | 53.4 | 94 ms | 5.08 s | 5.09 s | 5.09 s | 5.62 s | 200×300 |
| `/v1/turmas` | 1 | 1 | 300 | 300 | 78.8 | 1 ms | 1 ms | 2 ms | 3.59 s | 3.81 s | 200×300 |
| `/v1/turmas` | 10 | 10 | 300 | 300 | 78.2 | 5 ms | 202 ms | 3.39 s | 3.69 s | 3.84 s | 200×300 |
| `/v1/turmas` | 10 | 1 | 300 | 300 | 81.2 | 4 ms | 31 ms | 3.48 s | 3.48 s | 3.69 s | 200×300 |
| `/v1/turmas` | 50 | 50 | 300 | 300 | 79.0 | 28 ms | 2.15 s | 3.75 s | 3.78 s | 3.8 s | 200×300 |
| `/v1/turmas` | 50 | 1 | 300 | 300 | 73.0 | 97 ms | 3.56 s | 3.57 s | 3.57 s | 4.11 s | 200×300 |
| `/v1/notas` | 1 | 1 | 300 | 300 | 31.9 | 1 ms | 1 ms | 1 ms | 9.22 s | 9.42 s | 200×300 |
| `/v1/notas` | 10 | 10 | 300 | 300 | 32.0 | 3 ms | 74 ms | 9.13 s | 9.21 s | 9.36 s | 200×300 |
| `/v1/notas` | 10 | 1 | 300 | 300 | 32.0 | 4 ms | 38 ms | 9.13 s | 9.14 s | 9.37 s | 200×300 |
| `/v1/notas` | 50 | 50 | 300 | 300 | 24.4 | 90 ms | 11.84 s | 11.94 s | 11.98 s | 12.3 s | 200×300 |
| `/v1/notas` | 50 | 1 | 300 | 300 | 31.8 | 90 ms | 8.94 s | 8.95 s | 8.95 s | 9.45 s | 200×300 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
