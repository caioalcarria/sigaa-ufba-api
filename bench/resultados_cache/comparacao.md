### Fria × quente (p50 por rota)

| rota | baseline fria | baseline quente | cache fria | cache quente | cache-sem-preaquecer fria | cache-sem-preaquecer quente |
|---|--:|--:|--:|--:|--:|--:|
| `/v1/historico` | 4.64 s | 1.0 ms | 4.67 s | 0.8 ms | 4.64 s | 0.9 ms |
| `/v1/indices` | 4.74 s | 0.7 ms | 4.84 s | 0.9 ms | 4.70 s | 0.9 ms |
| `/v1/integralizacao` | 4.79 s | 1.1 ms | 4.73 s | 0.9 ms | 4.46 s | 0.9 ms |
| `/v1/matricula` | 1.44 s | 1.41 s | 1.39 s | 0.9 ms | 1.44 s | 0.9 ms |
| `/v1/turmas` | 3.57 s | 3.52 s | 3.50 s | 0.9 ms | 3.49 s | 1.0 ms |
| `/v1/portal` | 727.8 ms | 721.2 ms | 712.8 ms | 1.0 ms | 702.5 ms | 1.2 ms |
| `/v1/me` | 701.7 ms | 702.8 ms | 713.2 ms | 0.7 ms | 735.4 ms | 0.7 ms |
| `/v1/notas` | 9.20 s | 9.07 s | 9.12 s | 0.8 ms | 9.12 s | 0.9 ms |
| `/v1/frequencia` | 9.09 s | 9.14 s | 8.99 s | 0.6 ms | 9.13 s | 0.7 ms |
| `/v1/turmas/{turma_id}/notas` | 4.90 s | 2.13 s | 4.92 s | 1.0 ms | 4.87 s | 0.8 ms |
| `/v1/turmas/{turma_id}` | 4.23 s | 1.43 s | 4.26 s | 1.0 ms | 4.26 s | 0.8 ms |
| `/v1/documentos/comprovante-inscricao` | 1.43 s | 1.40 s | 1.43 s | 0.9 ms | 1.43 s | 0.7 ms |

### Carga (req/s · p50 · p95)

| rota | C | N | baseline | cache | cache-sem-preaquecer |
|---|--:|--:|---|---|---|
| `/v1/historico` | 1 | 1 | 61.4 req/s · 0.9 ms · 1.8 ms | 60.9 req/s · 0.6 ms · 1.4 ms | 62.2 req/s · 0.7 ms · 1.5 ms |
| `/v1/historico` | 10 | 10 | 45.1 req/s · 4.1 ms · 986.7 ms | 43.3 req/s · 4.0 ms · 1.13 s | 42.4 req/s · 4.3 ms · 1.13 s |
| `/v1/historico` | 10 | 1 | 60.5 req/s · 3.8 ms · 36.0 ms | 59.9 req/s · 4.1 ms · 32.9 ms | 63.4 req/s · 3.8 ms · 40.0 ms |
| `/v1/historico` | 50 | 50 | 16.5 req/s · 141.9 ms · 13.56 s | 15.6 req/s · 149.3 ms · 14.42 s | 15.7 req/s · 156.1 ms · 14.30 s |
| `/v1/historico` | 50 | 1 | 59.7 req/s · 95.0 ms · 4.49 s | 53.4 req/s · 94.5 ms · 5.08 s | 55.4 req/s · 104.9 ms · 4.86 s |
| `/v1/turmas` | 1 | 1 | 0.3 req/s · 3.52 s · 3.61 s | 78.8 req/s · 0.7 ms · 1.1 ms | 81.4 req/s · 0.7 ms · 1.3 ms |
| `/v1/turmas` | 10 | 10 | 2.8 req/s · 3.46 s · 3.91 s | 78.2 req/s · 4.7 ms · 201.6 ms | 79.0 req/s · 5.3 ms · 127.2 ms |
| `/v1/turmas` | 10 | 1 | 0.3 req/s · 34.82 s · 35.21 s | 81.2 req/s · 4.3 ms · 31.3 ms | 78.0 req/s · 5.0 ms · 20.7 ms |
| `/v1/turmas` | 50 | 50 | 11.8 req/s · 4.17 s · 4.58 s | 79.0 req/s · 27.9 ms · 2.15 s | 65.2 req/s · 128.9 ms · 4.03 s |
| `/v1/turmas` | 50 | 1 | 0.4 req/s · 61.40 s · 113.34 s · 27 erros | 73.0 req/s · 96.7 ms · 3.56 s | 73.8 req/s · 102.6 ms · 3.51 s |
| `/v1/notas` | 1 | 1 | 0.1 req/s · 9.17 s · 9.19 s | 31.9 req/s · 0.7 ms · 1.0 ms | 32.0 req/s · 0.5 ms · 1.0 ms |
| `/v1/notas` | 10 | 10 | 1.1 req/s · 9.16 s · 9.51 s | 32.0 req/s · 3.4 ms · 74.1 ms | 31.7 req/s · 3.5 ms · 234.3 ms |
| `/v1/notas` | 10 | 1 | 0.1 req/s · 68.68 s · 91.58 s | 32.0 req/s · 4.2 ms · 37.5 ms | 31.6 req/s · 3.9 ms · 46.3 ms |
| `/v1/notas` | 50 | 50 | 4.1 req/s · 12.32 s · 12.56 s | 24.4 req/s · 90.1 ms · 11.84 s | 24.6 req/s · 79.7 ms · 11.73 s |
| `/v1/notas` | 50 | 1 | 0.3 req/s · 64.36 s · 113.38 s · 41 erros | 31.8 req/s · 89.8 ms · 8.94 s | 30.8 req/s · 88.2 ms · 9.22 s |
