# Bench sigaa-api — antes

- **data:** 2026-10-20T02:50:03-03:00 · **api:** http://127.0.0.1:8152 (v0.1.0) → SIGAA http://127.0.0.1:8151
- **commit:** 34664635f4df (HEAD) · **worktree:** ~/sigaa-api-perf-base
- **host:** 20 CPUs · load [1.21, 1.37, 1.5] · Python 3.12.3
- **mock:** `{"mock": "sigaa-simulado", "fator": 1.0, "jitter": 0.1, "latencias_s": {"padrao": 0.45, "pdf": 3.5, "login": 0.7, "redirect": 0.08, "publico": 0.15, "publico_pesado": 0.45, "ajax": 0.25}, "max_concorrencia": 0, "ttl_sessao_s": 1800, "views_por_sessao": 20}`
- **o mock viu (fase fria×quente):** 1317 req · 42 logins · pico 1 em voo · MISS=0 · ViewState inválido=0 · sessões expiradas=0
- **parâmetros:** frias=3 quentes=5 C=[1, 10, 50, 200] alunos=['auto'] (máx 50) req=200 duração=None timeout=120s
- **placeholders:** ano=2026, periodo=2, codigo=MATA37, componente_id=44697, curso_id=1876885, estrutura_id=2421505, unidade=1114, turma_id=393420
- **tempo total:** 4028.1 s

## Login (POST /v1/auth/login)

| contexto | n | p50 | p95 | min | max | status |
|---|--:|--:|--:|--:|--:|---|
| sequencial (fase fria) | 42 | 3.03 s | 3.12 s | 2.90 s | 3.15 s | 200×42 |
| carga (até 20 em paralelo) | 333 | 3.27 s | 3.55 s | 2.90 s | 3.68 s | 200×333 |

## Latência fria × quente (por rota)

| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 200 | 4.65 s | 4.96 s | 4.52 s | 5.00 s | 1 ms | 1 ms | 0 ms | 2 ms | 7743.0× |
| `/v1/indices` | 200 | 4.40 s | 4.41 s | 4.38 s | 4.41 s | 1 ms | 1 ms | 0 ms | 1 ms | 7325.3× |
| `/v1/integralizacao` | 200 | 4.68 s | 4.85 s | 4.66 s | 4.86 s | 0 ms | 1 ms | 0 ms | 1 ms | 9356.4× |
| `/v1/matricula` | 200 | 1.41 s | 1.44 s | 1.35 s | 1.44 s | 1.40 s | 1.44 s | 1.33 s | 1.44 s | 1.0× |
| `/v1/turmas` | 200 | 3.57 s | 3.66 s | 3.49 s | 3.67 s | 3.51 s | 3.59 s | 3.40 s | 3.64 s | 1.0× |
| `/v1/portal` | 200 | 698 ms | 728 ms | 698 ms | 731 ms | 711 ms | 749 ms | 626 ms | 760 ms | 1.0× |
| `/v1/me` | 200 | 680 ms | 723 ms | 669 ms | 728 ms | 684 ms | 734 ms | 662 ms | 743 ms | 1.0× |
| `/v1/grade-curricular` | 200 | 10.90 s | 11.18 s | 10.40 s | 11.21 s | 2 ms | 2 ms | 1 ms | 2 ms | 7268.5× |
| `/v1/planejamento/matricula` | 200 | 14.27 s | 14.51 s | 14.15 s | 14.54 s | 2 ms | 3 ms | 2 ms | 3 ms | 7509.4× |
| `/v1/notas` | 200 | 9.17 s | 9.35 s | 9.11 s | 9.37 s | 9.16 s | 9.26 s | 8.94 s | 9.26 s | 1.0× |
| `/v1/frequencia` | 200 | 9.07 s | 9.13 s | 9.03 s | 9.13 s | 9.13 s | 9.23 s | 9.05 s | 9.23 s | 1.0× |
| `/v1/turmas/{turma_id}/notas` | 200 | 4.80 s | 4.88 s | 4.80 s | 4.89 s | 2.10 s | 2.18 s | 2.03 s | 2.18 s | 2.3× |
| `/v1/turmas/{turma_id}` | 200 | 4.25 s | 4.32 s | 4.19 s | 4.33 s | 1.41 s | 1.47 s | 1.26 s | 1.48 s | 3.0× |
| `/v1/documentos/comprovante-inscricao` | 200 | 1.43 s | 1.43 s | 1.41 s | 1.43 s | 1.40 s | 1.45 s | 1.35 s | 1.46 s | 1.0× |
| `/v1/publico/turmas 🔓` | 200 | 682 ms | 714 ms | 675 ms | 717 ms | 700 ms | 790 ms | 670 ms | 801 ms | 1.0× |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | 276 ms | 289 ms | 256 ms | 290 ms | 268 ms | 297 ms | 255 ms | 341 ms | 1.0× |
| `/v1/publico/cursos/{curso_id} 🔓` | 200 | 177 ms | 191 ms | 161 ms | 192 ms | 174 ms | 190 ms | 162 ms | 191 ms | 1.0× |
| `/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id} 🔓` | 200 | 1.27 s | 1.31 s | 1.25 s | 1.32 s | 1.32 s | 1.41 s | 1.23 s | 1.44 s | 1.0× |
| `/v1/publico/cursos/{curso_id}/calendario 🔓` | 200 | 191 ms | 192 ms | 180 ms | 192 ms | 182 ms | 191 ms | 168 ms | 193 ms | 1.0× |

## Carga (N alunos × C conexões simultâneas)

| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `/v1/historico` | 1 | 1 | 200 | 200 | 43.1 | 0 ms | 1 ms | 1 ms | 4.58 s | 4.64 s | 2 · 1 · 0 | 200×200 |
| `/v1/historico` | 10 | 10 | 200 | 200 | 30.3 | 2 ms | 1.75 s | 6.09 s | 6.56 s | 6.6 s | 20 · 10 · 0 | 200×200 |
| `/v1/historico` | 50 | 50 | 200 | 200 | 10.9 | 1.94 s | 15.33 s | 17.74 s | 18.28 s | 18.31 s | 100 · 50 · 0 | 200×200 |
| `/v1/historico` | 200 | 50 | 200 | 200 | 11.1 | 17.94 s | 17.94 s | 17.94 s | 17.94 s | 17.95 s | 100 · 50 · 0 | 200×200 |
| `/v1/turmas` | 1 | 1 | 200 | 200 | 0.3 | 3.52 s | 3.61 s | 3.65 s | 3.67 s | 702.95 s | 1001 · 2 · 0 | 200×200 |
| `/v1/turmas` | 10 | 10 | 200 | 200 | 2.8 | 3.54 s | 3.77 s | 3.82 s | 3.85 s | 70.66 s | 1000 · 10 · 0 | 200×200 |
| `/v1/turmas` | 50 | 50 | 200 | 200 | 12.2 | 4.02 s | 4.37 s | 4.53 s | 4.57 s | 16.35 s | 1000 · 50 · 0 | 200×200 |
| `/v1/turmas` | 200 | 50 | 200 | 200 | 12.2 | 10.19 s | 16.37 s | 16.43 s | 16.45 s | 16.46 s | 1000 · 50 · 0 | 200×200 |
| `/v1/notas` | 1 | 1 | 200 | 200 | 0.1 | 9.12 s | 9.29 s | 9.32 s | 9.34 s | 1824.45 s | 2600 · 1 · 0 | 200×200 |
| `/v1/notas` | 10 | 10 | 200 | 200 | 1.1 | 9.17 s | 9.64 s | 9.94 s | 10.01 s | 184.35 s | 2600 · 10 · 0 | 200×200 |
| `/v1/notas` | 50 | 50 | 200 | 200 | 4.3 | 11.49 s | 11.87 s | 11.96 s | 12.08 s | 46.35 s | 2600 · 50 · 0 | 200×200 |
| `/v1/notas` | 200 | 50 | 200 | 200 | 4.2 | 29.60 s | 47.09 s | 47.16 s | 47.18 s | 47.19 s | 2600 · 50 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 1 | — | 200 | 200 | 3.7 | 268 ms | 295 ms | 338 ms | 672 ms | 54.42 s | 400 · 1 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 10 | — | 200 | 200 | 11.2 | 835 ms | 1.10 s | 1.14 s | 1.18 s | 17.81 s | 400 · 4 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 50 | — | 200 | 200 | 11.3 | 4.32 s | 4.64 s | 4.69 s | 4.71 s | 17.71 s | 400 · 4 · 0 | 200×200 |
| `/v1/publico/componentes/{componente_id} 🔓` | 200 | — | 200 | 200 | 11.3 | 9.00 s | 17.03 s | 17.67 s | 17.69 s | 17.7 s | 400 · 4 · 0 | 200×200 |

_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._
