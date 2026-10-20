# Cache da sigaa-api

O tempo da API está nas VIAGENS ao SIGAA (~450 ms cada, em série por sessão), não no parse.
O cache corta as viagens repetidas. Ele tem duas camadas:

| camada | onde | guarda | chave |
|---|---|---|---|
| **L1: resposta HTTP** | `api/cache.py` (middleware ASGI `CacheHTTP`) | o corpo pronto de cada `GET` (+ gzip, ETag) | rota + query ordenada + escopo (público / compartilhado / HMAC do aluno) |
| **L2: serviço compartilhado** | `sigaa/cache.py` (`compartilhado`, `instalar`) | o resultado de funções de navegação de **dado público** (estrutura, componente/pré-requisitos, oferta de turmas, unidades, calendários...) | função + argumentos, **sem** o aluno |

O L2 serve às rotas COMPOSTAS. O `/v1/planejamento/matricula` de um aluno reaproveita a oferta do
curso e os pré-requisitos de cada componente que outro aluno do mesmo curso já buscou: o SIGAA real
caiu de 24,7 s pra 3,3 s (só sobra o histórico do próprio aluno).

## Escopos e TTL (L1)

A tabela `REGRAS` em `api/cache.py` decide. Vale a primeira regex que casar.

| rotas | escopo | TTL | stale-while-revalidate |
|---|---|--:|--:|
| `/v1/auth/*`, `/v1/status`, `/v1/cache/*`, `/docs` | **não cacheia** | | |
| `/v1/horarios/*` | público | 7 d | 30 d |
| `/v1/publico/turmas`, `/v1/publico/cursos/{id}/turmas` | público | 10 min | 1 h |
| `/v1/publico/cursos/{id}/noticias`, `/v1/publico/biblioteca/*` | público | 1 h | 1 d |
| `/v1/publico/{processos-seletivos,extensao,pesquisa,cursos-abertos,acordos-mobilidade}` | público | 6 h | 1 d |
| demais `/v1/publico/*` (cursos, estruturas, componentes, docentes, unidades, centros...) | público | 24 h | 7 d |
| `/v1/consultas/turmas` | compartilhado | 10 min | 1 h |
| `/v1/consultas/turmas/historico[/lote]` | compartilhado | 6 h | 7 d |
| `/v1/consultas/turmas/{id}[/processamento]` | compartilhado | 5 min | 30 min |
| `/v1/consultas/estruturas/{id}/declaracao-prazo-maximo` | aluno (documento emitido) | 1 h | 1 h |
| `/v1/consultas/{cursos[/ids],componentes[/filtros\|/{id}],estruturas[/{id}],turmas/filtros,unidades[/tipos]}`, `/v1/calendario/lista`, `/v1/calendario?ano&periodo` (ou `?id`) | compartilhado | 24 h | 7 d |
| qualquer OUTRA rota sob `/v1/consultas/*` (lista fechada: rota nova é por aluno até alguém provar que é dado público) | aluno | 1 min | 30 min |
| `/v1/calendario` sem ano/período (semestre atual DO ALUNO) | aluno | 6 h | 7 d |
| `/v1/me/foto` | aluno | 1 d | 7 d |
| `/v1/me/dados-pessoais`, `/v1/me/perfil` | aluno | 1 h | 1 d |
| `/v1/me`, `/v1/portal` | aluno | 5 min | 6 h |
| `/v1/turmas`, `/v1/grade-horaria[.ics]` | aluno | 30 min | 1 d |
| `/v1/turmas/{id}/notas`, `/frequencia`; `/v1/notas`, `/frequencia`, `/tarefas`, `/avaliacoes` | aluno | 10 min | 6 h |
| `/v1/turmas/{id}/arquivos/{id}`, anexos de fórum | aluno | 1 h | 1 d |
| demais `/v1/turmas/{id}/*` (notícias, aulas, fórum...) | aluno | 5 min | 6 h |
| `/v1/historico*`, `/indices`, `/integralizacao`, `/pendencias`, `/grade-curricular`, `/carga-horaria`, `/planejamento/*` | aluno | 30 min | 1 d |
| `/v1/matricula*` | aluno | 5 min | 6 h |
| `/v1/documentos/*` | aluno | 1 h | 1 h |
| `/v1/mensagens`, `/atualizacoes`, `/atividades`, `/forum-curso` | aluno | 2 min | 1 h |
| qualquer outra rota `GET /v1/*` | aluno | 1 min | 30 min |

* **público**: sem login, uma cópia pra todo mundo. Responde `Cache-Control: public`.
* **compartilhado**: a mesma cópia pra todos os alunos, mas só pra quem tem sessão válida.
  Sem token, ou com token inválido, a rota responde 401 como sempre.
* **aluno**: a chave leva `HMAC(SIGAA_API_CACHE_SEGREDO, hash do usuário)`. Dois tokens do mesmo
  aluno dividem o cache. Um aluno nunca recebe o dado de outro: a identidade vem da sessão
  validada no `gerenciador`, nunca do que o cliente manda. No Basic auth, o cache só entra depois que a
  senha já foi validada uma vez (existe a sessão `basic:` daquela credencial). Sessão vencida OU ociosa
  (`SIGAA_API_TOKEN_OCIOSO_MIN`) nunca recebe HIT — vale pro Bearer e pro Basic.
* a chave é `escopo:path?query` com a query ordenada pelo NOME (valores repetidos mantêm a ordem: a rota
  vê o último). Pedido com MAIS DE UM `Authorization` não usa o cache (a rota responde direto).
* `DELETE /v1/cache/meu` e o logout apagam o cache do aluno, e o que já estava indo ao SIGAA naquela
  hora (MISS, revalidação STALE, pré-aquecimento) não é regravado depois.

Só entram no cache respostas **200** sem `Set-Cookie` e com até 8 MB. Erro (401, 404, 502, 503) nunca
fica guardado.

## O que o cliente vê

| cabeçalho | |
|---|---|
| `X-Cache` | `HIT` (do cache, fresco), `STALE` (do cache, vencido, atualizando em 2º plano), `MISS` (foi ao SIGAA), `BYPASS` (forçou fresco) |
| `Age` | idade do dado em segundos |
| `X-Cache-Gerado-Em` | quando o dado veio do SIGAA (ISO 8601, UTC) |
| `ETag` | hash do corpo; `If-None-Match` igual → **304** sem corpo |
| `Cache-Control` | `private` (ou `public`), `max-age=<o que falta do TTL>, stale-while-revalidate=<s>` |
| `Vary` | `Authorization, Accept-Encoding` |
| `Content-Encoding: gzip` | quando o cliente manda `Accept-Encoding: gzip` e o corpo passa de 800 B (comprimido UMA vez, na gravação) |
| `X-Cache-Singleflight: seguiu` | a resposta veio da busca de OUTRO pedido igual, feita ao mesmo tempo |

Esses cabeçalhos estão no `expose_headers` do CORS, então o JavaScript do navegador consegue ler.
O corpo JSON não muda: nenhum `response_model` foi alterado.

### Forçar dado fresco
* `?fresco=true` (ou `?fresco`), `Cache-Control: no-cache`, `Cache-Control: max-age=0` ou `Pragma: no-cache`
  → vai ao SIGAA e **atualiza** o cache (`X-Cache: BYPASS`);
* `Cache-Control: no-store` → vai ao SIGAA e **não** grava;
* `DELETE /v1/cache/meu` → apaga todo o cache do aluno logado;
* `DELETE /v1/auth/sessao` (logout) também apaga o cache do aluno.

`GET /v1/cache/estatisticas` mostra os contadores (`hit`, `miss`, `stale`, `bypass`, `juntou`,
`revalidou`, `preaquecido`, `preaquecimento_cedeu`, `l2_hit`, `l2_miss`), a `taxa_acerto` e o uso de
memória. Só agregados, nada de aluno.

## Stale-while-revalidate
Depois do TTL, e até TTL + SWR, a resposta sai **na hora** do cache (`STALE`) e uma tarefa em segundo
plano refaz a rota com o MESMO `Authorization` do pedido. Vários `STALE` iguais disparam uma
revalidação só. Se a revalidação falha (SIGAA fora, sessão caiu), o dado velho continua sendo servido
até o fim da janela.

## Singleflight
N pedidos iguais ao mesmo tempo (mesma chave) = **1** navegação no SIGAA. Os outros esperam o
resultado do primeiro. Se o primeiro falhar, cada um tenta por conta própria; assim, a sessão expirada
de um aluno não vira erro pra outro. Vale nas duas camadas: no L2, alunos diferentes pedindo a mesma
estrutura curricular ao mesmo tempo também geram uma busca só.

## Pré-aquecimento após o login
Depois de um `POST /v1/auth/login` com sucesso, o middleware lê o token da resposta e, em segundo
plano, busca `SIGAA_API_PREAQUECER_ROTAS`. O padrão é
`/v1/portal, /v1/me, /v1/turmas, /v1/grade-horaria, /v1/historico, /v1/indices, /v1/integralizacao, /v1/matricula`.

Ele não atrapalha o aluno:
1. começa `SIGAA_API_PREAQUECER_ESPERA` (0,4 s) depois do login, e cada passo só começa depois de o aluno
   ficar `SIGAA_API_PREAQUECER_SILENCIO` (0,3 s) sem requisição;
2. se o aluno pede OUTRA rota no meio de um passo, o passo é **cancelado**: a trava da sessão é solta na
   hora, e a rota volta pro fim da fila (até 2 vezes);
3. se o aluno pede a MESMA rota que está sendo aquecida, ele entra no singleflight e recebe o resultado do aquecimento;
4. roda um aquecimento por aluno (dois logins seguidos não duplicam). Para no logout ou quando a sessão é invalidada.

Desligar: `SIGAA_API_PREAQUECER=false`.

## Backends
* **Memória** (padrão): LRU por bytes (`SIGAA_API_CACHE_MAX_MB`, padrão 256), por processo.
* **Redis** (`SIGAA_API_CACHE_URL=redis://host:6379/0`, precisa do pacote `redis`): compartilhado entre
  processos/workers. Tem um L0 em memória de 5 s por cima, então o HIT quente nem vai ao Redis. Se o Redis
  cair, a API segue (vira MISS) e conta os erros em `estatisticas`.
  * dado de aluno (escopo `aluno`) vai pro Redis **cifrado** (Fernet, chave derivada de
    `SIGAA_API_CACHE_SEGREDO` por scrypt; o HMAC das chaves usa outra subchave). A cifra leva a própria
    chave dentro: valor de um aluno copiado pra chave de outro é recusado, e chave de aluno com valor em
    claro também. **Sem segredo configurado, dado de aluno nunca vai pro Redis**: fica
    só na memória local do processo. Público/compartilhado vai em claro (é dado público);
  * `SIGAA_API_CACHE_SEGREDO` precisa de pelo menos `SIGAA_API_CACHE_SEGREDO_MIN` caracteres (padrão
    16; menos que isso é IGNORADO, com erro no log) e o recomendado é 32+ aleatórios
    (`python -c 'import secrets;print(secrets.token_urlsafe(48))'`). O mesmo valor em todos os workers;
  * Redis fora desta máquina: use `rediss://` (TLS) e senha (`rediss://:senha@host:6380/0`) — a API
    avisa no log quando falta. Quem escreve no Redis consegue envenenar o cache público/compartilhado;
  * as chaves de aluno são `u:<HMAC>:/rota?query`: não há login nem token em claro;
  * o TTL no Redis é TTL + SWR (+1 s): o próprio Redis expira.
* `SIGAA_API_CACHE=false` desliga tudo: o middleware passa direto e o L2 chama a função original.

Hoje as sessões (tokens) vivem na memória de cada processo. Com `--workers N`, o token só vale no
worker que fez o login, a não ser que a frente "sessões" compartilhe isso. O Redis já ajuda nas rotas
públicas e no L2 entre workers. O cache por aluno fica útil entre workers quando as sessões também
forem compartilhadas, ou com balanceamento por token (sticky).

## L2: como ligar o cache compartilhado numa função nova
```python
from sigaa.cache import compartilhado

@compartilhado(ttl=24 * 3600)
async def minha_consulta(c: SigaaClient, codigo: str) -> MeuModelo: ...
```
Ou ponha `("sigaa.services.x", "minha_consulta", ttl)` em `REGISTRO_COMPARTILHADO`.
(Exemplo direto no serviço: `sigaa/services/oferta.py` — `turmas_do_componente` e `turmas_reservadas`, 6 h. O histórico
de um período fechado não muda; os 6 h só limitam o atraso de uma oferta recém-publicada. No L1 a rota tem
stale-while-revalidate de 7 dias, então depois do TTL a resposta continua instantânea e é refeita em 2º plano.) O `instalar()`,
chamado no `api/main.py`, troca o atributo do módulo pelo wrapper, sem editar o arquivo do serviço.
**Só pra função cujo resultado não depende de quem está logado.** O primeiro argumento (a sessão) fica
fora da chave. O valor é serializado em JSON pelo tipo de retorno anotado, então cada HIT devolve um
objeto novo (ninguém altera o objeto de outro aluno) e o mesmo valor serve no Redis.

## Números (20/10/2026)

Medido nesta máquina (20 CPUs), 1 processo uvicorn. "SIMULADO" = `bench/mock_sigaa.py` da frente
bancada (≈450 ms por tela, PDF ≈3,5 s). "REAL" = SIGAA da UFBA, só leve: 1 aluno, em série, até 2 sessões.

### Latência por requisição: fria × quente (p50)
| rota | SIMULADO sem cache (fria / 2ª chamada) | SIMULADO com cache (fria / quente) | REAL sem cache (fria / 2ª) | REAL com cache (fria / quente) |
|---|--:|--:|--:|--:|
| `/v1/portal` | 728 ms / 721 ms | 713 ms / **1,0 ms** | 697 ms / 686 ms | 750 ms / **11 ms**¹ |
| `/v1/me` | 702 ms / 703 ms | 713 ms / **0,7 ms** | 681 ms / 622 ms | 659 ms / **11 ms**¹ |
| `/v1/turmas` | 3,57 s / 3,52 s | 3,50 s / **0,9 ms** | 1,90 s / 1,95 s | 1,95 s / **11 ms**¹ |
| `/v1/matricula` | 1,44 s / 1,41 s | 1,39 s / **0,9 ms** | 2,49 s / 2,30 s | 2,28 s / **11 ms**¹ |
| `/v1/notas` (todas as turmas) | 9,20 s / 9,07 s | 9,12 s / **0,8 ms** | | |
| `/v1/frequencia` | 9,09 s / 9,14 s | 8,99 s / **0,6 ms** | | |
| `/v1/turmas/{id}/notas` | 4,90 s / 2,13 s | 4,92 s / **1,0 ms** | | |
| `/v1/turmas/{id}` | 4,23 s / 1,43 s | 4,26 s / **1,0 ms** | | |
| `/v1/documentos/comprovante-inscricao` | 1,43 s / 1,40 s | 1,43 s / **0,9 ms** | | |
| `/v1/historico` | 4,64 s / 1,0 ms² | 4,67 s / **0,8 ms** | 3,31 s / 13 ms² | 3,86 s / **11 ms**¹ |
| `/v1/publico/unidades` | | | | 144 ms / **1,1 ms** |
| `/v1/publico/cursos/{id}/estruturas` | | | | 552 ms / **0,9 ms** |

¹ medido com `httpx.get` abrindo conexão nova a cada chamada. Com conexão reaproveitada, o HIT fica em ~1 ms, como no simulado.
² o histórico já tinha o `memo` de 5 min por sessão. O cache não piora o caso dele, e mantém o histórico mesmo com login novo ou sessão nova do mesmo aluno.

**Custo de CPU de um HIT dentro da app** (ASGI direto, sem rede, passando por CORS + cache + validação do token):
**~18 µs** (≈55 mil HIT/s por núcleo), com ou sem gzip. Uma requisição fria custa de 0,7 s a 9 s.

### Tela inicial do app depois do login (pré-aquecimento), SIMULADO
8 rotas: portal, me, turmas, grade-horaria, historico, indices, integralizacao, matricula.
| quando o app pede | sem cache | cache sem pré-aquecimento | cache com pré-aquecimento |
|---|--:|--:|--:|
| 20 s depois do login | 13,48 s | 13,81 s | **0,01 s** (8/8 HIT) |
| 3 s depois do login | 13,23 s | | **10,64 s** (junta às buscas em andamento) |

No REAL, 25 s depois do login, as 6 primeiras rotas responderam todas HIT, em 10–20 ms (conexão nova a cada chamada).

### Rota composta com o cache compartilhado (L2), REAL
`/v1/planejamento/matricula?fresco=true` numa sessão NOVA (o L1 é ignorado, e o histórico da sessão é novo, como um
colega do curso pedindo): **24,7 s → 3,3 s**. A oferta do curso, os pré-requisitos dos ~30 componentes e a estrutura vieram do L2;
só o histórico do próprio aluno foi buscado.

### Carga, SIMULADO (300 req ou 40 s por cenário; inclui o 1º MISS frio de cada aluno)
| rota | C conexões × N alunos | sem cache | com cache |
|---|---|--:|--:|
| `/v1/turmas` | 1 × 1 | 0,3 req/s · p50 3,52 s | **78,8 req/s · p50 0,7 ms** |
| `/v1/turmas` | 10 × 10 | 2,8 req/s · p50 3,46 s | **78,2 req/s · p50 4,7 ms** |
| `/v1/turmas` | 50 × 1 (o mesmo aluno) | 0,4 req/s · p50 61 s · 27 erros | **73 req/s · p50 97 ms · 0 erros** |
| `/v1/turmas` | 50 × 50 | 11,8 req/s · p50 4,17 s | **79 req/s · p50 28 ms** |
| `/v1/notas` | 10 × 10 | 1,1 req/s · p50 9,16 s | **32 req/s · p50 3,4 ms** |
| `/v1/notas` | 50 × 1 (o mesmo aluno) | 0,3 req/s · p50 64 s · 41 erros | **31,8 req/s · p50 90 ms · 0 erros** |
| `/v1/notas` | 50 × 50 | 4,1 req/s · p50 12,3 s | **24,4 req/s · p50 90 ms** |

Com o cache quente (`--aquecer`, 50 alunos, 20 s por cenário, sem pré-aquecimento):
`/v1/historico` 1.098 req/s (p50 34 ms) com C=50 e 733 req/s (p50 194 ms) com C=200; `/v1/turmas` 911 e 654 req/s;
`/v1/notas` 925 e 696 req/s. Zero erros. O teto aqui é o uvicorn de 1 processo + o cliente de carga em
Python, não o cache (18 µs). Isso é trabalho da frente "cpu" (uvloop/httptools, workers).

Reproduzir: `bench/cache_real.py` (REAL, leve), `bench/cache_preaquecer.py` (SIMULADO) e
`bench/cache_comparar.py base.json cache.json` (tabela a partir dos JSONs do `bench.py` da bancada).

## Limitações conhecidas
* A 1ª requisição de cada aluno continua fria (é a viagem ao SIGAA). Quem corta essa é a frente "sessões" (pool por
  aluno, menos viagens). O pré-aquecimento esconde essa espera quando o app demora alguns segundos pra pedir.
* Pré-aquecimento × sessão única: um passo já começado no SIGAA é cancelado quando o aluno pede outra rota, mas o
  SIGAA ainda processa aquele pedido. Com o pool de sessões da frente "sessões", o aquecimento deveria usar uma
  sessão própria. Hoje o parse do PDF do histórico (~0,3 s de CPU) roda no event loop. Com 50 logins
  simultâneos, os 50 pré-aquecimentos travam o loop por segundos: o p95 dos HITs vai a 2 s. A correção (parse em
  thread) é da frente "cpu". Até lá, `SIGAA_API_PREAQUECER=false` pra rajadas de login.
* O dado pode ficar desatualizado por até TTL + SWR (ex.: nota lançada agora aparece em até 10 min, ou na hora com `?fresco=true`).
* Tokens são por processo: o cache por aluno no Redis só serve entre workers quando as sessões também forem compartilhadas.
