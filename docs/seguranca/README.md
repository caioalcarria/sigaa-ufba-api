# Segurança da sigaa-api

Documentos desta pasta:

* [modelo de ameaças](modelo-de-ameacas.md): ativos, atores e fronteiras;
* [camada HTTP](http.md): cabeçalhos, CORS, limites, downloads e proxy de fotos;
* [privacidade / LGPD](privacidade.md): o que a API trata, onde fica, por quanto tempo e o que quem
  hospeda consegue ver;
* [parecer das ações de escrita](acoes.md);
* como reportar uma falha: [`SECURITY.md`](../../SECURITY.md).

## O que a API garante

**Senha**
* Nunca é gravada em disco nem em log.
* Com `lembrar`, fica cifrada (Fernet, chave gerada no boot) só na memória.
* O logout, a expiração e a sessão derrubada esquecem a senha e cancelam qualquer relogin pendente.
* O processo sobe sem core dump e sem ptrace.

**Token**
* Opaco, de 256 bits. O servidor guarda só o SHA-256.
* Morre em 12 h, ou em 120 min sem uso.
* O logout invalida o token, faz logout no SIGAA de todas as sessões do pool, apaga o cache do aluno
  (L1, L2 e Redis) e cancela o pré-aquecimento.

**Força bruta**
* Dois limites: por IP (todas as tentativas; no IPv6, por bloco /64) e por usuário (só as falhas,
  vindas de qualquer IP). Estourou, dá 429 antes de ir ao SIGAA.
* A mensagem de recusa é única, então não há enumeração de usuário.
* As confirmações de senha das ações de escrita contam no mesmo limite do login.

**Basic auth** vem desligado.

**Transporte da senha**
* HTTPS obrigatório fora do localhost: login e Basic por HTTP puro só de 127.0.0.1/::1; de fora,
  `403 https_obrigatorio` sem ler a senha (`SIGAA_API_EXIGIR_HTTPS`). Atrás de proxy TLS, o esquema vem
  do `X-Forwarded-Proto` do proxy confiável.
* Corpo do login cifrado, opcional: `GET /v1/auth/chave` dá uma chave RSA 2048 (gerada no boot) e o
  cliente manda `{"cifrado": base64(RSA-OAEP-SHA256({"usuario","senha","ts"}))}`. O envelope vale
  5 min e uma vez só, e a mensagem de erro é única. Protege de quem vê o corpo depois do TLS (proxy ou
  APM que loga corpo); **não** protege do dono do servidor.
* O corpo do login nunca vai pro log: nem no 500, nem no 401, nem no 422 ou com JSON quebrado
  (teste `test_corpo_do_login_nunca_vai_pro_log`).

**Isolamento entre alunos**
* A chave do cache de aluno leva HMAC(segredo, aluno).
* As rotas compartilhadas formam uma lista fechada e ancorada; qualquer rota nova é por aluno.
* Quem diz quem é o aluno é sempre a sessão validada, nunca o cliente. Pedido com dois
  `Authorization` não usa o cache.
* No Redis, o dado de aluno só entra cifrado e amarrado à própria chave.

**Entrada**
* O proxy de fotos só aceita a forma canônica `/shared/verFoto?idFoto=&key=`, e só imagem raster.
* Ids de texto são curtos e sem CR/LF.
* Limites de corpo (413), URL (414) e cabeçalhos (431); TRACE/TRACK dão 405.

**Saída**
* Erros sem traceback, sem `input` do pydantic e sem exceção interna. A mensagem do SIGAA é limitada.
* Downloads com nome saneado (RFC 6266/5987). Tipo ativo (html/svg/xml/js) vira anexo em
  `octet-stream`, e o comprovante HTML abre em sandbox.

**HTTP**
* Toda resposta, inclusive HIT do cache, 304 e erros, leva: nosniff, Referrer-Policy, frame DENY,
  CORP/COOP e CSP.
* `no-store` em tudo que tem dado pessoal e não passou pelo cache; HSTS quando chegou por HTTPS.
* CORS fechado por padrão e nunca com credenciais.
* Não há CSRF: nada autentica por cookie.

**Disponibilidade**
* Teto por token, por IP (rotas públicas) e global.
* Resposta do SIGAA limitada em bytes, já descomprimida (anti-bomba).
* `/v1/status` reaproveita a sondagem do SIGAA por 10 s.
* `?fresco=true` limitado por aluno.
* O teto global ao SIGAA e o ritmo por sessão protegem a UFBA.

**Segredos em log**
* Todo logger (app, httpx, uvicorn, traceback) passa por uma máscara de Bearer/Basic, JSESSIONID,
  senha, CPF e e-mail.
* O `repr` de sessão, página, cache e cliente não mostra segredo nem HTML.

**Cadeia de suprimentos**
* Dependências instaladas do lock com hash.
* Imagem em 2 etapas, base fixada por digest, uid 10001, só leitura.
* CI com testes de segurança, bandit, pip-audit e gitleaks no histórico inteiro.

## Configuração segura de produção (checklist)

- [ ] **HTTPS na frente** (nginx/traefik/caddy), com timeouts de conexão e de corpo (o slowloris é
      papel do proxy). Depois, `SIGAA_API_HSTS=true` ou `--proxy-headers` com o IP do proxy.
- [ ] **`FORWARDED_ALLOW_IPS=<IP do proxy>`**, nunca `*`. Sem proxy, deixe vazio (o padrão da imagem).
- [ ] **1 processo** (as sessões vivem em memória). Imagem oficial, ou `uvicorn --no-server-header`.
- [ ] `SIGAA_API_CORS` só com as origens do seu front, se ele chamar a API pelo navegador.
- [ ] `SIGAA_API_PERMITIR_BASIC` continua `false`.
- [ ] Com Redis: `SIGAA_API_CACHE_SEGREDO` com 32+ caracteres aleatórios, o mesmo em todos os
      processos, e `rediss://` com senha. Sem segredo, o dado de aluno nunca sai do processo.
- [ ] `SIGAA_API_HOSTS=<seu domínio>` e, se quiser esconder o mapa da API, `SIGAA_API_DOCS=false`.
- [ ] Core dump desligado (`SIGAA_API_SEM_CORE_DUMP=true`, o padrão; a imagem já faz `ulimit -c 0`)
      e swap cifrada ou desligada no host.
- [ ] Access log com retenção curta, ou `--no-access-log` (o IP do cliente é dado pessoal).
- [ ] Contêiner `read_only`, `cap_drop: [ALL]`, `no-new-privileges` (o `docker-compose.yml` já faz).
- [ ] Hospedando pra outras pessoas: leia [privacidade.md](privacidade.md). Avalie desligar
      `/v1/me/dados-pessoais`, que traz dado sensível (art. 11 da LGPD).

Variáveis novas da auditoria (todas com padrão seguro; tabela completa no [GUIA](../GUIA.md), em "Variáveis de ambiente"):

* `SIGAA_API_MAX_FALHAS_POR_USUARIO` / `_JANELA_FALHAS_USUARIO_MIN`
* `SIGAA_API_SEM_CORE_DUMP`
* `SIGAA_API_MAX_CORPO_BYTES` / `_MAX_CORPO_UPLOAD_BYTES` / `_MAX_URL_BYTES` / `_MAX_CABECALHOS*`
* `SIGAA_API_HSTS`, `SIGAA_API_HOSTS`, `SIGAA_API_DOCS`, `SIGAA_API_FOTO_MAX_BYTES`
* `SIGAA_API_CONC_POR_TOKEN` / `_POR_IP` / `_GLOBAL` / `_ESPERA_S`
* `SIGAA_MAX_RESP_HTML_MB` / `_PDF_MB`
* `SIGAA_API_STATUS_CACHE_S`, `SIGAA_API_STATUS_DETALHADO`
* `SIGAA_API_MAX_FRESCO_POR_MIN`
* `SIGAA_API_CACHE_SEGREDO_MIN`, `SIGAA_API_CACHE_APAGAR_AO_EXPIRAR`

Mudaram de padrão (também `SIGAA_API_EXIGIR_HTTPS=auto`: login por HTTP só do localhost):

* `SIGAA_API_PERMITIR_BASIC`: `true` → **`false`**
* `SIGAA_API_CORS`: `*` → **vazio**

## Achados da auditoria

Auditoria de 20/10/2026. Cada achado corrigido tem um teste em `tests/seguranca/` que falha no código
anterior e passa no atual.

| id | sev. | área | achado | status |
|---|---|---|---|---|
| H1 | alta | entrada | `/v1/fotos?url=` virava proxy pra qualquer tela do SIGAA com a sessão do aluno (`/sigaa/foto/../logar.do…`, `%2e%2e`, query livre) | corrigido |
| H2 | alta | saída | SVG e outros tipos ativos eram servidos no domínio da API (XSS) em fotos e gráficos | corrigido |
| H3 | alta | saída | Downloads repassavam o content-type do SIGAA (`text/html`, svg, js) | corrigido |
| H6/A9 | alta | saída | O 422 ecoava a senha no campo `input` | corrigido |
| ISO-01 | alta | isolamento | A declaração de prazo máximo (documento do aluno) vazava pra outro aluno com id não canônico (`+5`, `5.0`, `%205`) | corrigido |
| A1 | alta | auth | O logout via Basic deixava a sessão (com a senha cifrada) viva | corrigido |
| A2 | alta | auth | Não havia limite por usuário: força bruta de muitos IPs chegava à conta no SIGAA | corrigido |
| SEC-1 | alta | segredos | Log sem máscara: Bearer/Basic, JSESSIONID, senha e URL do Redis podiam ir pro log | corrigido |
| DOS-1 | alta | disponib. | `/v1/status` público sondava o SIGAA a cada chamada (amplificação contra a UFBA) | corrigido |
| DOS-2 | alta | disponib. | Resposta do SIGAA lida inteira, com descompressão sem limite (bomba gzip) | corrigido |
| DOS-3 | alta | disponib. | Sem teto de concorrência por token ou IP (um aluno esgotava o teto global) | corrigido |
| A3 | média | auth | A chave da sessão Basic era `sha256(usuario\0senha)` sem sal (quebrável a partir de um dump) | corrigido (HMAC) |
| A4 | média | auth | Basic ligado por padrão | corrigido (padrão `false`) |
| A5 | média | auth | Closures de relogin e `_cred` sobreviviam a logout, expiração e sessão derrubada | corrigido |
| A6 | média | auth | Logout no meio do aquecimento deixava uma sessão órfã logada no SIGAA | corrigido |
| A7 | média | disponib. | O limitador de login nunca apagava chaves (memória sem limite) | corrigido |
| A8 | média | auth | Cada requisição Basic contava como tentativa de login | corrigido |
| ISO-02 | média | isolamento | A cifra do Redis não era amarrada à chave (valor de A copiado pra chave de B); texto claro era aceito | corrigido |
| ISO-03 | média | isolamento | Segredo do cache curto, usado direto como chave | corrigido (mínimo + scrypt) |
| ISO-05 | média | isolamento | Com dois `Authorization`, a resposta do B era gravada na chave do A | corrigido |
| H4 | média | saída | Nome de arquivo cru no `Content-Disposition` (header injection; 500 com acento) | corrigido |
| H5 | média | saída | Comprovante HTML do SIGAA servido sem isolamento | corrigido (CSP sandbox) |
| H7 | média | saída | `str(ValueError)` vazava detalhe interno e HTML do SIGAA | corrigido |
| H9 | média | HTTP | Nenhum cabeçalho de segurança; sem `no-store` em login, sessão e /me | corrigido |
| H10 | média | entrada | Sem limite de corpo, URL ou cabeçalhos | corrigido |
| H12 | média | HTTP | CORS padrão `*` com métodos e cabeçalhos `*` | corrigido (fechado por padrão) |
| SEC-2 | média | segredos | `repr` de Page/Entrada/Capturada mostrava HTML e dado do aluno | corrigido |
| SEC-3 | média | LGPD | Token expirado não apagava o cache do aluno (retenção de dias) | corrigido |
| SEC-4 | média | auth/infra | `FORWARDED_ALLOW_IPS` errado no contêiner | corrigido |
| SEC-5 | média | infra | Imagem como root, sem lock, sem HEALTHCHECK; compose em 0.0.0.0, gravável, `CORS *` | corrigido |
| SEC-6 | média | privacidade | Fixture com 19 nomes reais | corrigido (o histórico mantém) |
| DOS-7 | média | disponib. | `?fresco=true` em laço furava o cache e martelava o SIGAA | corrigido |
| A10 | baixa | auth | O texto de recusa do SIGAA repassado permitia enumeração de usuário | corrigido |
| A11 | baixa | segredos | `repr(Sessao)` mostrava `_cred`; senha do login como `str` | corrigido (`SecretStr`) |
| A12 | baixa | isolamento | Cache e pré-aquecimento ignoravam a ociosidade; o logout não cancelava o pré-aquecimento | corrigido |
| A13 | baixa | segredos | Core dump ligado | corrigido |
| A14 | baixa | auth | IPv6 furava o limite por IP (o cliente tem um /64 inteiro) | corrigido |
| ISO-04 | baixa | isolamento | Sessão ociosa recebia HIT | corrigido |
| ISO-06 | baixa | isolamento | `?x=1&x=2` e `?x=2&x=1` davam a mesma chave (envenenamento da cópia compartilhada) | corrigido |
| ISO-07 | baixa | isolamento | Uma busca em voo regravava o dado do aluno depois do logout | corrigido |
| H8 | baixa | saída | Mensagem de `SigaaError` sem limite nem filtro | corrigido |
| H11 | baixa | HTTP | TRACE/TRACK/CONNECT chegavam ao roteador | corrigido (405) |
| H13 | baixa | entrada | Ids de texto repassados ao SIGAA sem validação | corrigido |
| H15/H16 | baixa | HTTP | Host header, docs e `Server: uvicorn` | corrigido (opcional por variável) |
| SEC-7 | baixa | segredos | `/v1/status` sem login expunha contadores internos | corrigido |
| SEC-8 | baixa | deps | Sem lock; pisos de versão (pdfminer.six, h11, starlette) | corrigido (pip-audit: 0) |
| SEC-11 | baixa | CI | Sem CI de segurança; actions por tag, sem `permissions` | corrigido |
| SEC-9 | baixa | código | Bandit: 6 baixos, todos falsos positivos | aceito (`# nosec` justificado) |
| SEC-10 | baixa | git | Nenhum segredo no histórico; ficam caminhos `/home/…` e os 19 nomes em commits antigos | documentado |
| DOS-5 | baixa | disponib. | ReDoS: as regex suspeitas foram medidas e são lineares | aceito |
| ISO-10/11 | baixa | cache | Período padrão de `/v1/consultas/turmas`; resultado anômalo no L2 compartilhado | documentado |
| T1 | média | auth | A senha era aceita por HTTP puro de qualquer lugar | corrigido (HTTPS fora do localhost) |
| T2 | baixa | auth | Não havia como proteger a senha de proxy/APM que loga corpo depois do TLS | corrigido (login cifrado opcional) |
| H14 | info | HTTP | CSRF não se aplica (nada autentica por cookie) | documentado |

## Riscos que ficaram

1. **Quem hospeda vê tudo, em tese:** a senha passa em claro pela memória no login, e a chave Fernet
   mora no mesmo processo. Isso é inerente ao desenho. Quem não confia no servidor deve rodar a
   própria instância ([privacidade](privacidade.md)).
2. **O Python não zera strings:** a defesa é soltar as referências cedo, cifrar e desligar core dump.
   Root lendo a memória ao vivo lê tudo.
3. **Bloqueio de conta na API:** 5 senhas erradas bloqueiam o login daquela conta por 15 min, mesmo
   com a senha certa. É a troca por proteger a conta no SIGAA. O 429 é idêntico em todos os casos,
   então não revela se a conta existe.
4. **NAT e proxy:** todo mundo atrás do mesmo IP divide a cota por IP. Configure `FORWARDED_ALLOW_IPS`.
5. **Slowloris e TLS** dependem do proxy reverso.
6. **CSP do `/docs`:** estilo com `'unsafe-inline'` e scripts do CDN jsDelivr (Swagger/ReDoc). Em
   produção, considere `SIGAA_API_DOCS=false`.
7. **Dado sensível:** `/v1/me/dados-pessoais` traz raça e necessidades especiais. Hospedar pra
   terceiros pede consentimento específico, ou desligar a rota. **Decisão do Caio.**
8. **Histórico do git:** os 19 nomes reais (de página pública) e caminhos `/home/…` continuam em
   commits antigos. Limpar exige reescrever o histórico. **Decisão do Caio**, se o repositório for público.
9. **Heurísticas:** a máscara de log não pega nome solto em texto livre, e a regra que esconde
   `ValueError` interno é heurística (um teste de contrato cobre as mensagens atuais).
10. **Basic religado** serializa os logins novos num lock global.
