# Privacidade e LGPD

O que a sigaa-api trata, onde isso fica, por quanto tempo, o que **quem hospeda** consegue ver e o que
recomendamos a quem roda uma instância pra outras pessoas. É um texto técnico, não um parecer jurídico.

> **Resumo honesto:** a API entra no SIGAA **com a senha do aluno**. Quem controla o servidor (o dono da
> máquina, o admin do Redis, quem lê a memória do processo ou o tráfego depois do HTTPS) consegue, em tese,
> ver tudo: a senha no momento do login, os tokens, os cookies do SIGAA e todos os dados que passam pelo
> cache. As proteções abaixo diminuem o que fica guardado e o que vaza por acidente (log, repr, core dump,
> Redis), mas **não protegem o aluno de um operador mal-intencionado**. Use a sua própria instância, ou só a
> de quem você confia como confiaria a sua senha do SIGAA.

## 1. Que dado passa pela API

| categoria | exemplos | rota(s) |
|---|---|---|
| **credencial** | usuário e senha do SIGAA; token Bearer da API; cookie de sessão do SIGAA (`JSESSIONID`) | `/v1/auth/*`, todas com login |
| **acadêmico do aluno** | histórico, índices/CR, notas, frequência, matrícula, integralização, documentos emitidos (PDF) | `/v1/historico*`, `/v1/turmas/*`, `/v1/matricula*`, `/v1/documentos/*`... |
| **pessoal do aluno** | nome, matrícula, e-mail, CPF, RG, endereço, telefone, filiação, foto | `/v1/me`, `/v1/me/dados-pessoais`, `/v1/me/foto` |
| **pessoal SENSÍVEL** (LGPD art. 5º, II) | raça/cor (`raca`), necessidades especiais / deficiência (`necessidades_especiais`) | `/v1/me/dados-pessoais` |
| **de TERCEIROS** | colegas de turma (participantes, nomes, e-mails, fotos), docentes, autores de fórum e mensagens, membros de grupos/projetos | `/v1/turmas/{id}/participantes`, fóruns, `/v1/fotos`, `/v1/publico/*` |
| **público** | cursos, componentes, turmas ofertadas, calendário, docentes e responsáveis (páginas públicas do SIGAA) | `/v1/publico/*`, `/v1/consultas/*` |

Os terceiros **não usam a API e não consentiram nada** — é o ponto mais delicado. A API repassa o que o
SIGAA já mostra ao aluno logado; ela não junta dado de turmas em que o aluno não está.

## 2. Onde fica e por quanto tempo

| o quê | onde | quanto tempo | proteção |
|---|---|---|---|
| **senha** (login normal) | memória, durante o login + aquecimento do pool (cifrada com Fernet, chave aleatória do processo) | segundos; depois é esquecida | nunca gravada em disco nem log |
| **senha** com `"lembrar": true` | memória do processo, cifrada (Fernet, chave gerada no boot) | até o token acabar (logout, `SIGAA_API_TOKEN_TTL_HORAS`=12 h, ou `SIGAA_API_TOKEN_OCIOSO_MIN`=120 min sem uso) | desligável: `SIGAA_API_PERMITIR_LEMBRAR=false` |
| **senha** via `Authorization: Basic` | idem (é tratada como `lembrar`) | idem | **desligado por padrão** (`SIGAA_API_PERMITIR_BASIC=false`) |
| **token** da API | memória: só o SHA-256 | até expirar / logout | o token em claro só aparece na resposta do login |
| **cookies do SIGAA** (`JSESSIONID`, pool de sessões) | memória | até o token acabar; o SIGAA derruba antes por inatividade | logout fecha as sessões no SIGAA |
| **cache L1** (respostas prontas do aluno) | memória do processo, ou Redis (`SIGAA_API_CACHE_URL`) | TTL da rota (1 min a 1 dia) + janela "stale" (até 7 dias) — ver [cache.md](../cache.md) | chave com HMAC do aluno; no Redis, entrada de aluno **cifrada** com `SIGAA_API_CACHE_SEGREDO`; sem esse segredo, dado de aluno **nunca sai da memória local** |
| **cache L2** (navegações de dado público) | memória ou Redis | horas a dias | sem identificação de aluno |
| **logs** | stdout do processo (quem hospeda decide onde vão parar) | o que o hospedeiro configurar | máscara automática (seção 4) |

**Apagar** — o aluno pode:
* `DELETE /v1/auth/sessao` (logout): invalida o token, faz logout no SIGAA, esquece a senha e **apaga o cache dele**;
* `DELETE /v1/cache/meu`: apaga só o cache dele (sem sair);
* não fazer nada: quando o token **expira** (TTL ou ociosidade), o cache do aluno é apagado junto
  (`SIGAA_API_CACHE_APAGAR_AO_EXPIRAR=true`, padrão), a não ser que ele tenha outro token ainda válido.
  A varredura roda a cada `SIGAA_API_KEEPALIVE_MIN` (10 min).

Reiniciar o processo apaga tudo o que está em memória. Entradas no Redis expiram pelo TTL delas.

## 3. O que quem hospeda consegue ver

Sem rodeio: **tudo**, se quiser. A senha passa em claro pelo processo no login (ela precisa ser enviada ao
SIGAA); a chave que cifra o "lembrar" está na mesma memória; os dados do aluno passam decifrados pelo
processo a cada resposta. O que o projeto garante é que nada disso fica gravado **por acidente**:

* a senha nunca é gravada (nem em disco, nem em log, nem no Redis);
* log, `repr()` e traceback não mostram senha, token, cookie, HTML do SIGAA nem dado do cache (seção 4);
* core dump desligado (o contêiner roda com `ulimit -c 0`; o processo também pede isso — `SEM_CORE_DUMP`);
* no Redis, entrada de aluno vai cifrada; quem só tem acesso ao Redis (sem o segredo) não lê;
* `/v1/status` (sem login) não mostra contadores internos (`SIGAA_API_STATUS_DETALHADO=false`).

Um operador com acesso ao processo (depurador, `/proc/<pid>/mem`, código modificado) contorna tudo isso.

## 4. Log sem segredo

`api/log_seguro.py` liga uma máscara em **todo** logger do processo (app, `httpx`, `uvicorn`), antes de
qualquer handler: `Authorization`/`Bearer`/`Basic`, `Cookie`/`Set-Cookie`, `JSESSIONID` (inclusive
`;jsessionid=` na URL), `senha=`/`token=`/`password=`… (em `chave=valor` e em JSON), `usuario:senha@` em URL,
tokens Fernet, CPF e e-mail. Vale pra mensagem, argumentos, traceback e stack. É rede de proteção — o código
já evita logar dado. O access log do uvicorn registra **IP do cliente, rota e status** (sem corpo nem
cabeçalho): é dado pessoal (IP) — defina retenção curta ou rode com `--no-access-log`.

## 5. Recomendações pra quem hospeda pra outras pessoas

Se você roda a API **só pra você**, é uso pessoal (LGPD art. 4º, I). Se roda **pra outras pessoas**, você
vira **controlador** dos dados delas (e dos terceiros que aparecem nas telas). Então:

1. **Base legal:** o aluno pede o serviço e entrega a própria credencial — execução de contrato/serviço a
   pedido do titular (art. 7º, V) ou consentimento (art. 7º, I). Pro dado **sensível** (raça, deficiência)
   só vale consentimento específico e destacado (art. 11, I) — ou não exponha `/v1/me/dados-pessoais`.
   Dado de terceiros: minimize; não guarde além do cache e não reutilize pra outra finalidade.
2. **Aviso de privacidade** curto e visível: o que a instância guarda, por quanto tempo, quem a opera, como
   apagar (logout / `DELETE /v1/cache/meu`) e um contato.
3. **HTTPS sempre**, com proxy reverso; `FORWARDED_ALLOW_IPS` com o IP dele (ver [servidor](../servidor.md)).
4. **Redis**: rede privada + senha + TLS, e **sempre** `SIGAA_API_CACHE_SEGREDO` (32+ bytes aleatórios,
   fora do git — `.env`/secret do orquestrador).
5. **Mínimo de retenção**: `SIGAA_API_CACHE_APAGAR_AO_EXPIRAR=true` (padrão), `SIGAA_API_PERMITIR_LEMBRAR=false`
   se não precisar, TTL de token curto, logs com retenção curta.
6. **Nada de core dump, swap sem criptografia ou snapshot de memória** da máquina.
7. **Incidente** (vazamento, servidor invadido): avise os titulares e a ANPD (art. 48) e, como as senhas do
   SIGAA podem ter sido expostas, oriente todos a **trocar a senha no SIGAA**.
8. Lembre que usar a credencial do aluno num serviço de terceiro pode contrariar as regras de uso da
   instituição — isso é entre quem hospeda, os alunos e a UFBA.

## 6. Repositório

* Fixtures de teste vêm de páginas reais do SIGAA **anonimizadas** (CPF com dígito verificador inválido,
  matrículas sequenciais, e-mails `@exemplo.br`, "FULANO DE TAL", `JSESSIONID` zerado).
  `tests/seguranca/test_segredos_dados_pessoais.py` falha se aparecer CPF válido, e-mail real ou cookie real.
* `gitleaks` roda no CI sobre o **histórico inteiro** (`.gitleaks.toml`, `.github/workflows/seguranca.yml`).
* Credenciais dos scripts de medição vêm só de variável de ambiente (`SIGAA_USUARIO`/`SIGAA_SENHA`) ou de
  `recon/` (fora do git).
