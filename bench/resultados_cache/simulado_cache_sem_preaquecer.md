# Bench sigaa-api — cache-sem-preaquecer

- **data:** 2026-10-20T00:46:06-03:00 · **api:** http://127.0.0.1:8184 (v0.1.0) → SIGAA http://127.0.0.1:8181
- **commit:** 1382279cf642 (perf/cache, SUJO) · **worktree:** ~/PROJECTS/UFBA/sigaa-api-perf-cache
- **host:** 20 CPUs · load [3.53, 3.75, 3.76] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 1.2, "redirect": 0.08, "publico": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **parâmetros:** frias=2 quentes=5 C=[1, 10, 50] alunos=['auto', '1'] (máx 50) req=300 duração=40.0 timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, curso_id=1876885, turma_id=393420
- **tempo total:** 405.6 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| sequencial (fase fria) | 24 | 3.54 s | 3.64 s | 3.41 s | 3.68 s | 200×24 |
| carga (até 20 em paralelo) | 189 | 3.67 s | 4.05 s | 3.37 s | 4.18 s | 200×189 |

## Latência fria × quente (por rota)

| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 200 | 4.64 s | 4.89 s | 4.35 s | 4.92 s | 1 ms | 2 ms | 1 ms | 2 ms | 5150.9× |
| `/v1/indices` | 200 | 4.70 s | 4.82 s | 4.56 s | 4.84 s | 1 ms | 1 ms | 1 ms | 1 ms | 5218.6× |
| `/v1/integralizacao` | 200 | 4.46 s | 4.48 s | 4.44 s | 4.49 s | 1 ms | 1 ms | 1 ms | 1 ms | 4960.7× |
| `/v1/matricula` | 200 | 1.44 s | 1.47 s | 1.41 s | 1.47 s | 1 ms | 1 ms | 1 ms | 1 ms | 1596.9× |
| `/v1/turmas` | 200 | 3.49 s | 3.50 s | 3.47 s | 3.50 s | 1 ms | 1 ms | 1 ms | 1 ms | 3485.6× |
| `/v1/portal` | 200 | 702 ms | 721 ms | 682 ms | 723 ms | 1 ms | 2 ms | 0 ms | 2 ms | 585.4× |
| `/v1/me` | 200 | 735 ms | 744 ms | 726 ms | 745 ms | 1 ms | 1 ms | 1 ms | 1 ms | 1050.6× |
| `/v1/notas` | 200 | 9.12 s | 9.16 s | 9.09 s | 9.16 s | 1 ms | 2 ms | 1 ms | 2 ms | 10138.1× |
| `/v1/frequencia` | 200 | 9.13 s | 9.23 s | 9.02 s | 9.24 s | 1 ms | 1 ms | 0 ms | 1 ms | 13044.9× |
| `/v1/turmas/{turma_id}/notas` | 200 | 4.87 s | 4.88 s | 4.85 s | 4.88 s | 1 ms | 1 ms | 1 ms | 1 ms | 6081.5× |
| `/v1/turmas/{turma_id}` | 200 | 4.26 s | 4.34 s | 4.16 s | 4.35 s | 1 ms | 1 ms | 0 ms | 1 ms | 5323.1× |
| `/v1/documentos/comprovante-inscricao` | 200 | 1.43 s | 1.45 s | 1.42 s | 1.45 s | 1 ms | 1 ms | 1 ms | 1 ms | 2049.6× |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/historico` | 1 | 1 | 300 | 300 | 62.2 | 1 ms | 2 ms | 2 ms | 4.58 s | 4.82 s | 200×300 |
| `/v1/historico` | 10 | 10 | 300 | 300 | 42.4 | 4 ms | 1.13 s | 6.04 s | 6.87 s | 7.08 s | 200×300 |
| `/v1/historico` | 10 | 1 | 300 | 300 | 63.4 | 4 ms | 40 ms | 4.52 s | 4.52 s | 4.73 s | 200×300 |
| `/v1/historico` | 50 | 50 | 300 | 300 | 15.7 | 156 ms | 14.30 s | 17.99 s | 18.72 s | 19.17 s | 200×300 |
| `/v1/historico` | 50 | 1 | 300 | 300 | 55.4 | 105 ms | 4.86 s | 4.87 s | 4.88 s | 5.42 s | 200×300 |
| `/v1/turmas` | 1 | 1 | 300 | 300 | 81.4 | 1 ms | 1 ms | 2 ms | 3.46 s | 3.68 s | 200×300 |
| `/v1/turmas` | 10 | 10 | 300 | 300 | 79.0 | 5 ms | 127 ms | 3.49 s | 3.64 s | 3.8 s | 200×300 |
| `/v1/turmas` | 10 | 1 | 300 | 300 | 78.0 | 5 ms | 21 ms | 3.67 s | 3.67 s | 3.84 s | 200×300 |
| `/v1/turmas` | 50 | 50 | 300 | 300 | 65.2 | 129 ms | 4.03 s | 4.14 s | 4.16 s | 4.6 s | 200×300 |
| `/v1/turmas` | 50 | 1 | 300 | 300 | 73.8 | 103 ms | 3.51 s | 3.52 s | 3.52 s | 4.07 s | 200×300 |
| `/v1/notas` | 1 | 1 | 300 | 300 | 32.0 | 0 ms | 1 ms | 1 ms | 9.17 s | 9.36 s | 200×300 |
| `/v1/notas` | 10 | 10 | 300 | 300 | 31.7 | 4 ms | 234 ms | 9.03 s | 9.32 s | 9.47 s | 200×300 |
| `/v1/notas` | 10 | 1 | 300 | 300 | 31.6 | 4 ms | 46 ms | 9.26 s | 9.26 s | 9.48 s | 200×300 |
| `/v1/notas` | 50 | 50 | 300 | 300 | 24.6 | 80 ms | 11.73 s | 11.89 s | 11.91 s | 12.18 s | 200×300 |
| `/v1/notas` | 50 | 1 | 300 | 300 | 30.8 | 88 ms | 9.22 s | 9.23 s | 9.23 s | 9.75 s | 200×300 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
