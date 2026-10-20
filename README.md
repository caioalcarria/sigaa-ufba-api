<div align="center">

# 🎓 SIGAA UFBA API

**Seus dados do SIGAA da UFBA em JSON, prontos pra usar em qualquer app.**

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![somente leitura](https://img.shields.io/badge/modo-somente%20leitura-6e7781)
![licença](https://img.shields.io/badge/licen%C3%A7a-MIT-yellow)

</div>

## O que é

O SIGAA não tem API. Esta é uma API **não oficial** que entra no SIGAA com o **seu** login e devolve
suas informações organizadas em JSON. É útil pra fazer app, bot, planilha, dashboard ou qualquer sistema
que precise dos dados do aluno.

**Ela só lê.** Não matricula, não tranca e não envia nada.

## O que você consegue

- 📜 **Histórico** completo, com **CR e IAP** e a evolução do CR semestre a semestre
- 📚 **Turmas** de todos os semestres, com a grade horária (também em `.ics`, pro Google Agenda)
- 📝 **Notas, frequência, tarefas e provas** de cada turma virtual
- 🗺️ **Planejamento de matrícula**:
  - o que falta pra se formar;
  - o que você pode pegar no semestre;
  - simulação de choque de horário.
- 🧾 **Matrícula do semestre e documentos**: comprovante, declaração de vínculo, histórico em PDF
- 🌐 **Dados públicos sem login**: cursos, disciplinas, ementas, turmas ofertadas, professores, calendário

São mais de 160 rotas. A lista completa está em [**docs/ENDPOINTS.md**](docs/ENDPOINTS.md).

## Como usar em 3 passos

**1. Suba a API**

```bash
git clone https://github.com/caioalcarria/sigaa-ufba-api && cd sigaa-ufba-api
docker compose up -d
```

Sem Docker: `pip install -e ".[api]"` e depois `uvicorn api.main:app`.

**2. Faça login** com o seu usuário e a sua senha do SIGAA:

```bash
curl -X POST localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"usuario": "seu.login", "senha": "sua-senha", "lembrar": true}'
```

A resposta traz um `token`.

**3. Use o token** nas outras rotas:

```bash
curl localhost:8000/v1/indices -H "Authorization: Bearer SEU_TOKEN"
```

```json
{
  "oficiais": { "cr": 7.45, "iap": 0.81 },
  "evolucao": [
    { "periodo": "2024.1", "cr_periodo": 6.9, "cr_acumulado": 6.9 },
    { "periodo": "2024.2", "cr_periodo": 8.1, "cr_acumulado": 7.45 }
  ]
}
```

Pra testar tudo pelo navegador, abra **http://localhost:8000/docs**: cada rota tem o botão *Try it out*.

## Bom saber

- **Rápida:** quando você pede o mesmo dado de novo, ele sai do cache em menos de 1 milissegundo. Pra forçar o dado
  mais novo, use `?fresco=true`.
- **Sessão:** com `"lembrar": true`, a API entra de novo sozinha quando o SIGAA desconecta você por inatividade.
- **Sua senha nunca é gravada:** com `lembrar`, ela fica só na memória do servidor, cifrada.
- **Erros** vêm sempre no mesmo formato: `{"erro": {"codigo": "...", "mensagem": "..."}}`.

## Mais detalhes

| quero… | leia |
|---|---|
| ver todas as rotas | [docs/ENDPOINTS.md](docs/ENDPOINTS.md) |
| entender login, cache, erros e desempenho | [docs/GUIA.md](docs/GUIA.md) |
| usar como biblioteca Python ou em JavaScript | [examples/](examples) |
| saber como cada tela do SIGAA foi mapeada | [docs/mapeamento/](docs/mapeamento) |
| contribuir | [docs/CONTRATO.md](docs/CONTRATO.md) |
| saber o que a API garante de segurança e configurar produção | [docs/seguranca/](docs/seguranca/README.md) · reportar falha: [SECURITY.md](SECURITY.md) |

## Aviso

Este é um projeto **independente**, sem vínculo com a UFBA nem com a UFRN, que criou o SIGAA. Use só com as **suas**
credenciais. Se você hospedar a API pra outras pessoas, use HTTPS e deixe claro pra elas que a senha passa pelo seu
servidor.

Licença [MIT](LICENSE). Feito por estudante, pra estudante. 💙
