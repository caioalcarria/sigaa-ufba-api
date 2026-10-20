# Política de segurança

## Como reportar uma vulnerabilidade

**Não abra issue pública** pra falha de segurança. Use o reporte privado do GitHub:
aba **Security → Report a vulnerability** deste repositório (GitHub Private Vulnerability
Reporting). Se não der, abra uma issue pedindo um canal privado, **sem detalhes da falha**.

No reporte, mande se puder:

* o que dá pra fazer (impacto) e em qual versão/commit;
* passos pra reproduzir — **contra uma instância sua apontada pro SIGAA simulado**
  (`bench/mock_sigaa.py`, ver [docs/bench.md](docs/bench.md));
* se a falha já é pública ou está sendo explorada.

O que esperar: confirmação de recebimento em até 7 dias, avaliação em até 14 dias e, se for
confirmada, correção + aviso no histórico de versões dando crédito a você (se quiser).

## Regras pra quem testa

* **Nunca teste contra o SIGAA real da UFBA.** Força bruta, fuzzing, carga e logins com senha
  errada podem bloquear contas de alunos e sobrecarregar um sistema público. Use o SIGAA simulado.
* Nunca teste contra instâncias da API de outras pessoas sem autorização delas.
* Não acesse, guarde nem divulgue dados de terceiros. Se um dado pessoal real aparecer, pare e
  reporte.

## Escopo

Dentro: o código deste repositório (API `api/`, cliente `sigaa/`, Dockerfile, CI).
Fora: o próprio SIGAA da UFBA (reporte à STI/UFBA), instâncias de terceiros e problemas que
dependem de o atacante já controlar o servidor onde a API roda.

## Versões suportadas

Só a última versão do branch principal recebe correções de segurança.

O que a API garante e como configurá-la com segurança em produção: [docs/seguranca/README.md](docs/seguranca/README.md).
