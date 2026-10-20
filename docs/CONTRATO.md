# Contrato de código — sigaa-api (leia antes de escrever qualquer linha)

Projeto: API pública (open-source, vai pro GitHub) de **LEITURA** dos dados do aluno no SIGAA da UFBA
(https://sigaa.ufba.br). Python 3.12, `httpx` (async), `beautifulsoup4`+`lxml`, `pydantic` v2, `FastAPI`,
`pdfplumber` pra PDF. venv em `.venv/` (`.venv/bin/python`, `.venv/bin/pip install ...`).

## Camadas (cada frente escreve os SEUS arquivos — não edite arquivo de outra frente)
| camada | arquivo | regra |
|---|---|---|
| modelos | `sigaa/models/<area>.py` | pydantic v2 `BaseModel`, campos `snake_case` em português, `Field(description=...)` em todos (vira a doc do Swagger). Datas `date`/`datetime`, números como `int`/`float` (nunca string), ausente = `None`, listas vazias = `[]`. Enum quando o domínio é fechado (situação APR/REP/REPF/TRANC/MATR...), mas sempre guarde também o texto cru (`situacao_texto`). |
| parsers | `sigaa/parsers/<area>.py` | funções PURAS `parse_xxx(html: str ou bytes) -> Modelo`. Zero rede. TOLERANTES: cada aluno vê telas diferentes (campo que some, tabela vazia, "Não há...", rótulo com/sem acento, ordem diferente) — procure por RÓTULO, não por posição; nunca quebre por falta de um campo (vira `None`). |
| serviços | `sigaa/services/<area>.py` | `async def xxx(c: SigaaClient, ...) -> Modelo` — a NAVEGAÇÃO (quais telas, quais cliques) + chama o parser. Use só a API do `sigaa/client.py`: `c.portal()`, `c.menu("bean.metodo")`, `c.clicar(page, "trecho do onclick" ou texto)`, `c.submit(page, form_id, extra, botao)`, `c.get/post`. Nunca segure estado entre chamadas (a rota pode ser chamada em qualquer ordem). |
| rotas | `api/routes/<area>.py` | `router = APIRouter(prefix="/v1/...", tags=["..."])`. Cada rota: `async def rota(cli: Cliente, ...)` e `return await cli.executar(lambda c: servico(c, ...))` — `Cliente` vem de `from api.deps import Cliente` (o orquestrador escreve; já pode importar). `response_model` sempre, `summary` e `description` em PT. |
| testes | `tests/test_<area>.py` + `tests/fixtures/<area>/` | pytest dos parsers com HTML/PDF de fixture. **Fixture ANONIMIZADA** (ver abaixo). |
| doc | `docs/mapeamento/<area>.md` | TODA tela que você viu: como chegar (passo a passo exato: link/bean/form/params), o que tem, variações, AJAX (a4j) que dispara, e os endpoints propostos/implementados. |

## Convenções da API
- prefixo `/v1`; recursos em português, kebab-case, plural: `/v1/turmas`, `/v1/turmas/{turma_id}/noticias`, `/v1/historico`.
- JSON `snake_case`; datas ISO 8601; horários `"18:30"`; carga horária em horas `int`; notas `float`.
- Identificadores: use o id NUMÉRICO do SIGAA quando existir (ex.: `idTurma`); se só houver hash (`frontEndIdTurma`), exponha como string. O id tem que ser estável entre logins.
- Erros: levante as exceções de `sigaa/errors.py` (`NaoEncontrado`, `NavegacaoInvalida`, ...) — a API converte em HTTP.
- Binários (PDF original) também podem ser servidos: rota `.../pdf` com `Response(media_type="application/pdf")`.

## Regras de ouro do SIGAA
1. **SOMENTE LEITURA.** Proibido submeter o que altera estado: matrícula, trancamento, suspensão, qualquer "Solicitar", avaliação institucional, enviar mensagem, postar/responder fórum, enviar tarefa, responder questionário/enquete, alterar dados/foto/senha, confirmar declaração. Abrir telas de CONSULTA e emitir documentos (histórico/atestado/declaração) pode.
2. JSF é stateful: todo clique vem de uma tela que o sistema gerou (ViewState). URL "digitada" costuma dar "O endereço digitado não é válido". Sempre navegue a partir do portal.
3. **Não bombardeie**: ≥0,3 s entre requisições, sem força bruta de ids. Cada "Comportamento Inesperado" manda e-mail pra STI da UFBA — se uma navegação deu erro, entenda antes de repetir.
4. Página em ISO-8859-1 (o `Page.html` já decodifica).

## Dados pessoais (o repo é PÚBLICO)
- `recon/` é gitignored: páginas cruas, PDFs, cookies ficam lá (`recon/pages/<area>/`).
- Nada de dado real em `tests/fixtures`, `docs/` ou código: troque nome, matrícula, CPF, RG, nascimento, e-mail, telefone, endereço, nomes de colegas/professores por fictícios (ex.: "FULANO DE TAL", 200000000, 000.000.000-00) mantendo a ESTRUTURA do HTML intacta.
- Nunca imprima a senha. A credencial só entra por `recon/sess.py` (`login("<area>")`) e `recon/web_login.sh`.

## Ferramentas de recon
- `recon/sess.py` (síncrono, requests) — `s, r = login("<area>")` cria sua sessão própria; `menu(s, "bean")`, `jsf_links(html)`, `jsf_click(s, html, "trecho")`, `submit(...)`, `dump(r, "pages/<area>/x.html")`. Leia o docstring.
- `sigaa/client.py` (assíncrono, o de produção) — use pra validar o serviço de ponta a ponta: `recon/test_client.py` é um exemplo.
- Nó web no canvas (o Caio quer VER): `web_criar` → `bash recon/web_login.sh` → `node ~/.config/dot/dot-web.js navegar|ler|snapshot|fazer|gravar ligar|mapa resumo` (o gravador mostra as chamadas AJAX a4j que o requests não vê).
