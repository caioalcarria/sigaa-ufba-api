# Deploy no servidor de aplicações da Rede IC (Dokku)

O IC/UFBA hospeda aplicações da comunidade num [Dokku](https://dokku.com/) em `app.ic.ufba.br`: o código vai por
`git push`, o servidor constrói pelo `Dockerfile` e só atende por HTTPS ([guia do IC](https://graco-ufba.github.io/app/)).
O serviço é experimental e sem backup — a API não grava nada em disco, então isso não afeta nada além das sessões
(que já vivem só na memória).

O que já está no repositório pra isso:

| arquivo | pra quê |
|---|---|
| `Dockerfile` | build (o Dokku detecta sozinho). A API escuta na **porta 8000** |
| `app.json` | o Dokku lê da raiz do repositório: **1 instância** (`web=1`, as sessões vivem em memória) e o healthcheck em `/` |
| `SIGAA_API_ROTAS_PERMITIDAS` | expõe só as rotas que o front usa (o resto dá 404) — [api/rotas_permitidas.py](../api/rotas_permitidas.py) |

## 1. Pedir a aplicação ao suporte do IC

Gere uma chave só pra isso, **com senha** (sem senha, quem copiar o arquivo faz deploy no seu lugar):

```bash
ssh-keygen -t rsa -b 4096 -f ~/.ssh/dokku
cat ~/.ssh/dokku.pub
```

Abra um chamado em <https://suporteic.ufba.br/>, tópico **"Suporte TI: hospedagem de aplicação"**. Modelo:

> Solicito a criação da aplicação **cadee-api** (endereço `cadee-api.app.ic.ufba.br`) para a {sigaa} api, usada
> pelo CADEE (planejamento de semestre, IC/UFBA). Orientador: Prof. ___. Chave pública em anexo.
>
> Configurações necessárias:
> 1. Build por Dockerfile (`builder:set cadee-api selected dockerfile`).
> 2. Mapeamento de portas para a porta 8000 do contêiner: `ports:set cadee-api http:80:8000 https:443:8000`
>    (em Dokku anterior à 0.31: `proxy:ports-set`).
> 3. Uma única instância (o `app.json` já pede `web=1`; por favor não escalar).
> 4. Se possível, as travas de segurança do contêiner:
>    `docker-options:add cadee-api deploy,run "--read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop=ALL --security-opt=no-new-privileges --ulimit core=0 --pids-limit=256"`
> 5. Saída HTTPS liberada para `sigaa.ufba.br`.
> 6. Por favor, informar o IP pelo qual o nginx do Dokku conecta no contêiner (normalmente `172.17.0.1`).
>
> Uso de recursos: 1 processo Python, poucos MB de RAM por aluno logado; o pico de CPU é na época de matrícula
> (leitura de PDFs do histórico). Não usa banco de dados nem disco.

## 2. Configurar o acesso

`~/.ssh/config` (como no [guia do IC](https://graco-ufba.github.io/app/ambiente-local/)):

```
Host app.ic.ufba.br 200.128.51.137
  HostName 200.128.51.137
  Port 9999
  User dokku
  IdentityFile ~/.ssh/dokku
  RequestTTY yes
```

## 3. Variáveis de ambiente

```bash
ssh dokku@app.ic.ufba.br config:set cadee-api \
  SIGAA_URL=https://sigaa.ufba.br \
  FORWARDED_ALLOW_IPS=172.17.0.1 \
  SIGAA_API_CORS=https://cadee.netlify.app,https://cadee.app.ic.ufba.br \
  SIGAA_API_EXIGIR_HTTPS=true \
  SIGAA_API_HSTS=true \
  SIGAA_API_DOCS=false \
  SIGAA_API_PERMITIR_BASIC=false \
  SIGAA_API_STATUS_DETALHADO=false \
  SIGAA_API_MAX_CONCORRENCIA_SIGAA=32 \
  SIGAA_API_TOKEN_TTL_HORAS=12 \
  SIGAA_API_ROTAS_PERMITIDAS='/v1/status,/v1/auth/*,/v1/historico,/v1/indices*,/v1/integralizacao,/v1/carga-horaria,/v1/planejamento/*,/v1/grade-horaria.ics,/v1/publico/componentes/*'
```

* **`FORWARDED_ALLOW_IPS`** é o ponto que mais quebra: é o IP do nginx do Dokku (item 6 do chamado). Errado ou
  vazio, a API não lê o `X-Forwarded-Proto`, acha que o login veio por HTTP e responde `403 https_obrigatorio`
  a todo mundo. Nunca use `*` (qualquer um forjaria o IP e furaria o limite de tentativas).
* **`SIGAA_API_CORS`** lista as origens do site, separadas por vírgula: o CADEE no Netlify e, se o site também for pra
  Rede IC, `cadee.app.ic.ufba.br`. Sem barra no fim.
* **`SIGAA_API_HOSTS` não é usado aqui:** o nginx do Dokku já só repassa o domínio da aplicação, e o healthcheck
  do Dokku chama o contêiner pelo IP (com a lista de hosts ligada, ele daria 400 e o deploy falharia).
* **`SIGAA_API_ROTAS_PERMITIDAS`** acima é a lista do CADEE. Se a instância for servir outros fronts, junte as
  rotas deles (ou deixe vazia = todas).

## 4. Deploy

```bash
git clone https://github.com/ic-ufba/sigaa-ufba-api && cd sigaa-ufba-api   # fork do IC (com app.json e rotas permitidas)
git remote add dokku dokku@app.ic.ufba.br:cadee-api   # o remoto PRECISA se chamar "dokku"
git push -f dokku HEAD:master                         # nos próximos, sem o -f
```

Conferir:

```bash
curl https://cadee-api.app.ic.ufba.br/v1/status          # {"api":"ok", ... "no_ar":true}
curl -o /dev/null -w '%{http_code}\n' https://cadee-api.app.ic.ufba.br/v1/me   # 404 (fora da lista)
ssh dokku@app.ic.ufba.br logs cadee-api
ssh dokku@app.ic.ufba.br ps:report cadee-api              # Processes: 1
```

## Problemas comuns

| sintoma | causa provável |
|---|---|
| login dá `403 https_obrigatorio` | `FORWARDED_ALLOW_IPS` não é o IP do nginx — confira com o suporte ou em `ps:inspect cadee-api` (campo `Gateway`) |
| o navegador acusa CORS | `SIGAA_API_CORS` diferente da origem exata do site (sem barra no fim) |
| deploy falha no healthcheck | `SIGAA_API_HOSTS` definido (remova) ou porta não mapeada pra 8000 |
| `401 token_invalido` aleatório | mais de uma instância rodando (`ps:report`): peça `web=1` |
| `503 sigaa_ocupado` | pico de uso; o teto `SIGAA_API_MAX_CONCORRENCIA_SIGAA` está protegendo o SIGAA |

Atualizar = `git pull` + `git push dokku HEAD:master`. Isso reinicia o processo e derruba as sessões (os alunos
precisam entrar de novo): faça fora do período de matrícula.
