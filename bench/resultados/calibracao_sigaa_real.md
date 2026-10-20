# Calibração contra o SIGAA REAL (só páginas públicas, sem login)

Medido em 2026-10-20 00:34:58 · 1 sessão anônima por vez, tudo em série, ≥0,35 s entre requisições, 3 repetições · 51 requisições no total.
Telas LOGADAS não foram medidas de novo (o login com a credencial pessoal foi vetado); pra elas o mock usa os números do brief (GET portal ≈ 450 ms, PDF do histórico ≈ 3,5 s, login ≈ 3,1 s).

## Por requisição ao SIGAA (tempo do servidor + rede, medido no proxy)

| método | caminho | status | n | mediana ms | mín | máx |
|---|---|---|---|---|---|---|
| GET | `/sigaa/public/curso/curriculo.jsf` | 200 | 6 | 453 | 438 | 491 |
| POST | `/sigaa/public/curso/curriculo.jsf` | 200 | 3 | 424 | 393 | 430 |
| GET | `/sigaa/link/public/ensino/visualizarComponente/44697` | 302 | 3 | 195 | 154 | 212 |
| GET | `/sigaa/public/departamento/componentes.jsf` | 200 | 3 | 187 | 174 | 222 |
| GET | `/sigaa/public/curso/portal.jsf` | 200 | 3 | 160 | 139 | 174 |
| POST | `/sigaa/public/turmas/listar.jsf` | 200 | 3 | 154 | 95 | 239 |
| POST | `/sigaa/public/componentes/busca_componentes.jsf` | 200 | 9 | 89 | 56 | 329 |
| GET | `/sigaa/public/componentes/busca_componentes.jsf` | 200 | 6 | 89 | 86 | 214 |
| GET | `/sigaa/public/curso/lista.jsf` | 200 | 3 | 88 | 78 | 92 |
| GET | `/sigaa/public/turmas/listar.jsf` | 200 | 6 | 86 | 55 | 94 |
| GET | `/sigaa/public/componentes/resumo.jsf` | 200 | 3 | 28 | 27 | 28 |
| GET | `/sigaa/verTelaLogin.do` | 200 | 3 | 13 | 12 | 40 |

**Todas:** n=51 · mediana 95 ms · média 176 ms · p90 438 ms

## Ponta a ponta pela API (inclui o intervalo de 0,35 s do cliente anônimo e do proxy)

| rota | rep 1 | rep 2 | rep 3 |
|---|---|---|---|
| `__tela_login__` | 0.04 s | 0.32 s | 0.32 s |
| `/v1/publico/cursos/1876885` | 0.54 s | 0.49 s | 0.52 s |
| `/v1/publico/cursos/1876885/estruturas` | 0.80 s | 0.79 s | 0.79 s |
| `/v1/publico/cursos/1876885/estruturas/2421505` | 1.62 s | 1.68 s | 1.65 s |
| `/v1/publico/componentes/44697` | 0.91 s | 0.82 s | 0.86 s |
| `/v1/publico/componentes/codigo/MATA37` | 1.57 s | 1.50 s | 1.55 s |
| `/v1/publico/componentes?codigo=MATA37` | 0.85 s | 1.03 s | 0.77 s |
| `/v1/publico/turmas?ano=2026&periodo=2&unidade=1114` | 0.96 s | 1.03 s | 0.91 s |
| `/v1/publico/cursos?nivel=G&nome=computa%C3%A7%C3%A3o` | 0.43 s | 0.45 s | 0.44 s |
| `/v1/publico/unidades` | 0.39 s | 0.41 s | 0.42 s |
| `/v1/publico/departamentos/1114/componentes` | 0.56 s | 0.57 s | 0.61 s |

## O que mudou no mock por causa disto

* classe `publico` 0,45 → **0,15 s** (o público é bem mais leve que o logado); `publico_pesado` = 0,45 s pra `curriculo.jsf` (GET e o clique da estrutura, ~430 ms medidos);
* `visualizarComponente/{id}` responde **302** → `resumo.jsf` (como o real);
* o mock aceita `;jsessionid=` na URL (o real reescreve URL nas sessões anônimas).
