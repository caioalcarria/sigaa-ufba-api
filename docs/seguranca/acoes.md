# Parecer de segurança: ações de escrita (`feat/acoes`)

Revisão do branch `feat/acoes` nos commits `23e377d` (catálogo + `PATCH /v1/me/perfil`,
`PATCH /v1/me/dados-pessoais`, `PUT /v1/me/foto`) e `52a1c90` (limite de falhas de confirmação).
Revisão só de leitura: nada foi editado naquele branch.

## O que está certo

* **Confirmar/simular:** sem `confirmar: true` dá 422 e nada vai ao SIGAA; `simular: true` abre o
  formulário e devolve o que seria enviado, com a senha mascarada.
* **Step-up:** senha, CPF e data de nascimento vêm **só no corpo** de cada envio. Nunca são guardados,
  devolvidos ou tirados do `lembrar` (o `senha_guardada` do rascunho foi removido, como pedimos).
* **Uma escrita por aluno de cada vez** (trava por `usuario_hash`).
* **Saída:** `Cache-Control: no-store` em toda resposta de escrita, e o cache do aluno é invalidado
  depois de cada envio (ou de uma recusa).
* **Sessão caída durante o POST** vira "resultado desconhecido", sem relogar e reenviar.
* **CSRF:** não se aplica. A autenticação é só pelo cabeçalho `Authorization` e o corpo é JSON.
* **Ação irreversível bloqueada:** `DELETE /v1/me/foto` responde 403.
* **Upload de foto:** só JPEG/PNG/GIF verificados pelos bytes, até 2 MB. O nome do arquivo é saneado
  e o `Content-Type` é fixo.

## Achados

| id | sev. | achado | correção recomendada |
|---|---|---|---|
| AC-1 | **média** | `limite_step_up` é um contador **separado**, com o teto do login **por IP** (20 em 10 min), aplicado por usuário. Com um token roubado, o atacante ganha 20 tentativas de senha a cada 10 min pela tela de confirmação, que somam às do login e podem fazer o SIGAA bloquear a conta. | Usar o limite de falhas **por usuário** do `feat/seguranca` (`SIGAA_API_MAX_FALHAS_POR_USUARIO`, 5 em 15 min), **compartilhado com o login**: `gerenciador.confirmacao_bloqueada(sess)` / `gerenciador.falha_confirmacao(sess)` (já existem no `feat/seguranca`, com teste `tests/seguranca/test_auth_step_up.py`). Apagar `limite_step_up`. |
| AC-2 | **média** | Corrida check-then-act: `limite.bloqueado()` é consultado **antes** de pegar a trava do aluno. N pedidos em paralelo passam todos pelo teste e depois executam em série, então o limite é furado na proporção do paralelismo. | Fazer a consulta **dentro** do `async with trava:`, imediatamente antes de `sess.cliente.executar(fluxo)`. |
| AC-3 | baixa | `PedidoAcao.senha` e `.cpf` são `str` comuns. `repr()` do pedido (traceback, log de depuração, erro do pydantic) mostra os valores. | `SecretStr` (como no `LoginRequest` do `feat/seguranca`) ou `Field(repr=False)`; `step_up()` faz o `get_secret_value()`. |
| AC-4 | baixa | `_travas` é um `dict` que só cresce, com um `asyncio.Lock` por aluno que já escreveu. | `weakref.WeakValueDictionary`, ou remover a trava quando ninguém estiver esperando por ela. |
| AC-5 | baixa | Com o Basic ligado (`SIGAA_API_PERMITIR_BASIC=true`), as escritas aceitam Basic. Aí a senha viaja em toda requisição e a sessão é criada sob demanda. | Exigir `sess.origem == "token"` nas rotas de escrita (403 `acesso_negado` com Basic). |
| AC-6 | baixa | O prazo total por requisição (`SIGAA_API_TIMEOUT_S`, 120 s) **cancela** a tarefa. Se isso cair no meio do POST de escrita, o estado fica desconhecido e o cache pode não ser invalidado. | Proteger o envio com `asyncio.shield` e invalidar o cache no `finally`. Um 504 depois de iniciado o envio deve dizer "resultado desconhecido, confira com GET". |
| AC-7 | baixa | O 422 `acao_recusada` repassa `e.mensagens` (o painel do SIGAA) sem limite de tamanho. O texto pode ecoar o que o aluno digitou. | Passar cada mensagem pelo `limitar()` de `api/seguranca_http.py` (já usado no handler de `SigaaError`). |
| AC-8 | info | Idempotência: os PATCH são naturalmente idempotentes, porque gravam valores. O PUT da foto gera um `idFoto` novo a cada envio, o que é inofensivo. | Opcional: aceitar `Idempotency-Key` se aparecer ação não idempotente (inscrição, trancamento...). Para as de risco médio/alto do catálogo, isso deve ser **obrigatório**. |

## Pontos de integração com `feat/seguranca`

Já preparados do nosso lado:

* **Limite de corpo:** o `feat/seguranca` limita a 64 KiB (`SIGAA_API_MAX_CORPO_BYTES`). O
  `PUT /v1/me/foto` tem um limite próprio de 4 MiB (`SIGAA_API_MAX_CORPO_UPLOAD_BYTES`), porque a
  foto de 2 MB em base64 tem cerca de 2,7 MB.
* **CORS** e o `Allow` do 405 já incluem `PUT` e `PATCH`.
* **422:** o `feat/seguranca` tira o `input` de **todo** erro de validação. É mais estrito que o filtro
  do `feat/acoes` (que tira só de senha/cpf/data_nascimento), então no merge fica a versão do `feat/seguranca`.
* **Cache:** a regra `^/v1/acoes(/|$)` (catálogo público) precisa entrar na lista nova de `REGRAS` do
  `api/cache.py`. No `feat/seguranca`, as rotas compartilhadas viraram lista fechada e o resto é
  por aluno. Cair no padrão "por aluno" também é seguro; só perde o compartilhamento.
* **Concorrência:** o teto por token (`SIGAA_API_CONC_POR_TOKEN`, 6) também vale para as escritas.
* **Ordem do merge:** `feat/seguranca` primeiro, depois `feat/acoes`. Os conflitos esperados são em
  `api/main.py` (handler do 422), `api/sessions.py` (`LimiteLogin` foi reescrito; trocar
  `limite_step_up` pelas funções acima) e `api/cache.py` (`REGRAS`).

## Parecer

O padrão está **aprovado com ressalvas**. AC-1 e AC-2 devem ser corrigidos antes de qualquer ação ir
pra produção. Os outros podem vir junto ou logo depois. Para ações de risco médio/alto do catálogo,
exigir também `Idempotency-Key`, trilha mínima sem dado pessoal (ação, horário, resultado, hash do
aluno) e um limite de escritas por aluno por hora.
