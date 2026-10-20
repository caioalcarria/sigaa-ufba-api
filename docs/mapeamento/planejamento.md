# Planejamento acadêmico (grade curricular, matrícula, horas)

Não é uma tela do SIGAA: é a API **juntando três telas** pra responder "o que eu pego no semestre?".

| fonte | tela do SIGAA | serviço |
|---|---|---|
| o que o aluno já fez | Histórico (PDF) | `academico.historico` |
| a grade do curso | Consultas Gerais › Consultar Estrutura Curricular (busca pelo **código do currículo** do histórico, ex. `T20252`, + casamento pela **matriz**: nome do curso + turno — o mesmo código existe em ~160 cursos) | `planejamento.estrutura_do_aluno` |
| pré/co-requisitos | Consultas Gerais › Consultar Componente Curricular (detalhe) | `consultas.componente` (cache 6 h) |
| a oferta | Consultas Gerais › Consultar Turma com filtro **Curso** = turmas com vaga reservada pro curso (1 busca traz tudo, ~4 s) | `planejamento.oferta_do_curso` (cache 15 min) |

## Regras
- **Status na grade**: APROVADO se o código (ou um equivalente "Cumpriu X através de Y" do histórico, ou o mesmo código com sufixo de letra, ex. `MATA02A`) tem situação aprovada; CURSANDO se está MATR; obrigatória que **o próprio SIGAA não lista como pendente** conta como cumprida (equivalência/aproveitamento); senão PENDENTE.
- **Apto** = a expressão de pré-requisito (`(A) E (B OU C)`) avaliada contra o conjunto de cumpridos (+ os cursando, com `considerar_cursando_como_aprovado=true`, pra planejar o próximo semestre). `faltando` lista os códigos que bloqueiam.
- **Desbloqueia** = pendentes da grade cujo pré-requisito cita o componente.
- **Atrasado** = semestre ideal < período letivo atual do aluno.
- **Simulação**: choque = mesmo (dia, turno, aula) do código de horário; CH total × CH máxima por período da estrutura; turma lotada (matriculados ≥ capacidade); integralização projetada assumindo aprovação.
- **Sugestão** (gulosa): obrigatórias aptas por (semestre ideal, mais destrava), depois optativas aptas; primeira turma sem choque, com vaga e nos turnos pedidos, até a CH máxima.

## Rotas
`GET /v1/grade-curricular` · `GET /v1/planejamento/matricula` (filtros `natureza`, `so_aptos`, `turnos`, `sem_dias`, `com_vagas`) ·
`POST /v1/planejamento/simular` · `GET /v1/planejamento/sugestao` · `GET /v1/carga-horaria` ·
`GET /v1/atividades-autonomas/{id}` (detalhe com **parecer do coordenador**) · `GET /v1/atividades-autonomas/{id}/comprovante`.

## Limitações
- A oferta usada é a **com reserva pro curso**. Obrigatórias sem turma reservada saem em `avisos` (o aluno ainda pode achar turma de outro curso em `/v1/publico/turmas?codigo=`).
- Pré-requisitos cumpridos via equivalência do **pré-requisito** (não do componente) podem aparecer como faltando — confira `faltando`.
- Vagas = capacidade − matriculados no momento da consulta (não considera reservas por curso/ingressantes).
