# Segurança da camada HTTP (entrada, saída, cabeçalhos)

O que a API faz na borda HTTP e por quê. Código em `api/seguranca_http.py`; testes em
`tests/seguranca/test_http_*.py` e `tests/seguranca/test_entrada_*.py`.

## Pilha

```
cliente ─► SegurancaHTTP ─► [erro 500] ─► TrustedHost (opcional) ─► Prazo (504) ─► CORS (opcional) ─► GZip ─► cache L1 ─► rotas
```

`SegurancaHTTP` é ASGI puro (sem `BaseHTTPMiddleware`) e fica POR FORA de tudo, inclusive do tratador
de 500 do Starlette: o HIT do cache, o 304, o 504, os erros e o 500 saem com os mesmos cabeçalhos. Ele só
**acrescenta** o que falta: `Cache-Control` e `Content-Security-Policy` que a rota/o cache já puseram ficam.

## Limites da requisição

| limite | padrão | resposta | variável |
|---|--:|---|---|
| corpo | 64 KiB | `413 corpo_grande` | `SIGAA_API_MAX_CORPO_BYTES` |
| caminho + query | 8 KiB | `414 url_grande` | `SIGAA_API_MAX_URL_BYTES` |
| cabeçalhos (soma) | 32 KiB | `431 cabecalhos_grandes` | `SIGAA_API_MAX_CABECALHOS_BYTES` |
| cabeçalhos (quantidade) | 100 | `431 cabecalhos_grandes` | `SIGAA_API_MAX_CABECALHOS` |
| métodos `TRACE`/`TRACK`/`CONNECT` | — | `405 metodo_nao_permitido` | — |

Com `Content-Length`, o 413 sai antes de ler o corpo. Sem ele (`chunked`), o corpo é lido até o limite antes
de a aplicação ver qualquer byte e depois reapresentado inteiro. `0` desliga cada limite.

## Cabeçalhos em toda resposta

| cabeçalho | valor | |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | o navegador não "adivinha" HTML num JSON/arquivo |
| `Referrer-Policy` | `no-referrer` | URL com id/filtro não vaza pra terceiros |
| `X-Frame-Options` | `DENY` | + `frame-ancestors 'none'` na CSP: sem clickjacking |
| `Cross-Origin-Resource-Policy` | `same-origin` | outro site não embute foto/arquivo por `<img>`/`<script>` |
| `Cross-Origin-Opener-Policy` | `same-origin` | |
| `Permissions-Policy` | câmera, microfone, geolocalização… `()` | |
| `Content-Security-Policy` | JSON/erros: `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` | aberto como documento, é inerte |
| | `/docs` e `/redoc`: só `cdn.jsdelivr.net` (+ fontes do ReDoc); o script inline do Swagger entra por **hash** calculado na hora (sem `'unsafe-inline'` em script) | |
| | PDF: só `frame-ancestors`/`base-uri`/`form-action` (o leitor de PDF do navegador não abre com `sandbox`) | |
| | arquivos repassados e o comprovante HTML: `default-src 'none'; … sandbox` | |
| `Cache-Control` | `no-store` quando a resposta não trouxe um (login, sessão, 401, `/v1/me`…); as rotas `/v1/publico/` e o que o cache L1 serve mantêm o deles | |
| `Strict-Transport-Security` | `max-age=31536000` só quando a requisição chegou por HTTPS (`SIGAA_API_HSTS=auto`) | |

**HTTPS atrás de proxy:** o `scheme` só vira `https` se o uvicorn confiar no proxy — rode com
`--proxy-headers --forwarded-allow-ips <ip do proxy>` (o padrão do uvicorn confia só em 127.0.0.1). Sem
proxy confiável, use `SIGAA_API_HSTS=true` se a API só é servida por HTTPS.

**`Server: uvicorn`:** o uvicorn põe esse cabeçalho no nível do protocolo (a app não tira). O `Dockerfile`
roda com `--no-server-header`; faça o mesmo em qualquer outro jeito de subir.

## CORS

Padrão: **nenhuma origem** (`SIGAA_API_CORS` vazio). A API é consumida por servidor, script ou app; um site
qualquer não precisa (nem deve) chamá-la pelo navegador da vítima. Pra um front no navegador, liste as
origens: `SIGAA_API_CORS=https://meu-front.exemplo.br`. `*` continua possível, mas **nunca com credenciais**
(`allow_credentials=False` sempre; a API não usa cookie). Métodos liberados: `GET, POST, DELETE`; cabeçalhos:
`Authorization, Content-Type, If-None-Match, Cache-Control, Pragma`.

> Mudança de padrão: antes era `*`. Quem usa a API pelo navegador de outra origem precisa setar
> `SIGAA_API_CORS`. O `docker-compose.yml` deixou de forçar `*`.

## CSRF

Nenhuma rota autentica por cookie: só `Authorization: Bearer <token>` (ou `Basic`). O navegador não manda esse
cabeçalho sozinho, então um site malicioso não consegue agir em nome do aluno. A API não lê nem grava cookie
(teste `test_nenhuma_rota_autentica_por_cookie`).

## Host e docs

* `SIGAA_API_HOSTS=api.exemplo.br,*.exemplo.br` liga o `TrustedHostMiddleware` (Host fora da lista = 400).
  Padrão vazio = aceita qualquer Host (não quebra quem já usa).
* `SIGAA_API_DOCS=false` tira `/docs`, `/redoc` e `/openapi.json` do ar.

## Entrada

* **`GET /v1/fotos?url=`** aceita só `/shared/verFoto?idFoto=<dígitos>&key=<alfanumérico>` (relativo ou
  absoluto no MESMO esquema+host do `SIGAA_URL`). A URL é remontada — nada do que o cliente mandou vai cru
  pro SIGAA. Antes, qualquer `/sigaa/…foto…` passava (inclusive `../`, `%2e%2e`, query livre): era um GET
  com a sessão do aluno em qualquer tela do SIGAA (ex.: `/sigaa/foto/../logar.do?dispatch=logOff`).
  Só imagem raster (`jpeg/png/gif/webp/bmp`) é repassada — SVG é documento com script — e até
  `SIGAA_API_FOTO_MAX_BYTES` (2 MiB).
* Ids de texto que viram opção do SIGAA (`mensagem_id`, `departamento_id`, `periodo`, filtros do histórico):
  até 64 caracteres, sem controle (CR/LF/NUL). Ids numéricos já eram `int` no FastAPI; os demais parâmetros de
  busca vão como campo de formulário (codificados pelo httpx), nunca colados em URL.

## Saída (arquivos e erros)

* Downloads repassados do SIGAA (arquivos e anexos da turma virtual, comprovante de atividade autônoma):
  `Content-Disposition` com `filename="<ascii saneado>"; filename*=UTF-8''<pct>` (RFC 6266/5987) — aspas,
  `;`, CR/LF, `/` e unicode do nome original não entram crus. Tipo ativo (`html`, `svg`, `xml`, `javascript`…)
  ou vazio vira `application/octet-stream` + `attachment`. CSP com `sandbox` (menos PDF).
* `GET /v1/documentos/comprovante-inscricao/html` continua `text/html` (pra abrir e imprimir), mas com
  `Content-Security-Policy: default-src 'none'; img-src data:; style-src 'unsafe-inline'; …; sandbox`: nenhum
  script roda e o documento tem origem opaca (não alcança token/armazenamento da origem da API).
* Gráfico de estatísticas e `/v1/me/foto`: só imagem raster; senão `404`.
* Erros: o 422 de validação não devolve `input`/`ctx`/`url` do pydantic (ecoava a senha num login malformado);
  `ValueError` só mostra a mensagem se for uma frase de propósito dos serviços (`ValueError` puro, sem padrão
  de mensagem do Python) — senão "Parâmetros inválidos."; mensagens de `SigaaError` (às vezes tiradas do HTML
  do SIGAA) saem sem caractere de controle e com no máximo 300 caracteres; 500 é sempre genérico.
