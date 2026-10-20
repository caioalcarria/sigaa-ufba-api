# Mapeamento — área acadêmica (histórico, matrícula, documentos)

SIGAA UFBA v4.13.8. Tudo parte do **menu JSCook do Portal do Discente**: um POST em
`/sigaa/portais/discente/discente.jsf` com `menu:form_menu_discente`, `jscook_action=<ação>` e o
`javax.faces.ViewState` do portal (`SigaaClient.menu("<bean>")` faz isso).

| Tela (menu do SIGAA) | ação (`bean.metodo`) | resposta | parser | rota |
|---|---|---|---|---|
| Ensino › Emitir Histórico | `portalDiscente.historico` | **PDF** (texto, 4 págs) | `parsers/historico_pdf.py` | `GET /v1/historico`, `/historico/pdf`, `/historico/componentes`, `/indices`, `POST /indices/simular`, `/integralizacao`, `/pendencias` |
| Ensino › Emitir Atestado de Matrícula | `portalDiscente.atestadoMatricula` | HTML `#relatorio` (é o *Comprovante de Inscrição Semestral*) | `parse_comprovante_inscricao` | `GET /v1/documentos/comprovante-inscricao` (+ `/html`) |
| Ensino › Emitir Declaração de Vínculo | `declaracaoVinculo.emitirDeclaracao` | **PDF** | `parse_declaracao_vinculo_pdf` | `GET /v1/documentos/declaracao-vinculo` (+ `/pdf`) |
| Matrícula On-Line › Ver Comprovante / Ver Resultado do Processamento | `matriculaGraduacao.verComprovanteSolicitacoes` | HTML `/sigaa/graduacao/matricula/comprovante_solicitacoes.jsf` | `parse_comprovante_solicitacao` | `GET /v1/matricula` |
| (link da situação de cada turma no comprovante) | GET `/sigaa/relatorioProcessamento?idTurma=<id>[&rematricula=true]` | HTML (popup) | `parse_resultado_processamento` | `GET /v1/matricula/processamento`, `/processamento/{turma_id}` |
| Trancamento › Exibir Andamento | `trancamentoMatricula.iniciarMeusTrancamentos` | HTML `table.listagem` | `parse_trancamentos` | `GET /v1/trancamentos` |
| Suspensão de Programa › Exibir Solicitações | `trancamentoPrograma.exibirMinhasSolicitacoes` | HTML (lista + **Histórico de Movimentações**) | `parse_suspensoes` | `GET /v1/suspensoes` |
| Registro de Atividades Autônomas | `solicitacaoRegistroAtividadeAutonomaMBean.listar` | HTML (grupos `td.subFormulario`) | `parse_atividades_autonomas` | `GET /v1/atividades-autonomas` |
| Minhas Solicitações de Aproveitamento | `solicitacaoAproveitamentoEstudosMBean.listar` | HTML listagem | `parse_listagem` | `GET /v1/aproveitamentos` |
| Impressão de Diploma Digital | `buscaDiplomaDigitalMBean.iniciarBuscaDiscente` | HTML listagem | `parse_listagem` | `GET /v1/diploma` |
| Avaliação Institucional › Rever a Avaliação Anterior | `avaliacaoInstitucionalAnterior.listaAnterior` | HTML `table.formulario` | `parse_listagem` | `GET /v1/avaliacao-institucional` |
| Avaliação Institucional › Consultar o Resultado | `relatorioAvaliacaoMBean.iniciarConsultaPublica` → submit `form` (`form:escolha_relatorio`, `form:anoPeriodo`, `form:botaoRelatorio`) | HTML | `parse_filtros_avaliacao`, `parse_resultado_avaliacao` | `GET /v1/avaliacao-institucional/filtros`, `/resultado?departamento_id=&periodo=` |
| Avaliação Institucional › Observações dos Docentes | `relatorioAvaliacaoMBean.iniciarObservacoesTurmasDiscente` → submit (`form:anoPeriodo`, `form:consultar`) | HTML | `parse_listagem` | `GET /v1/avaliacao-institucional/observacoes?periodo=` |

## Histórico (PDF)
Texto real (não é imagem) — `pdfplumber` extrai linha a linha. O parser é uma máquina de estados pelos
**títulos de seção**: `Dados Pessoais`, `Dados do Vínculo do Discente`, `Componentes Curriculares Cursados/Cursando`,
`Legenda`, `Atividades Autônomas do Discente`, `Carga Horária e Créditos Integralizados/Pendentes`,
`Carga Horária Extensionista`, `Componentes Curriculares Obrigatórios Pendentes:N`, `Equivalências:`, `Observações:`.
Cabeçalho (instituição, endereço, "Documento Oficial", "Emitido em") e rodapé (verificação, "Página X de Y")
se repetem em cada página e são removidos. Linha não reconhecida vai pra `linhas_nao_reconhecidas` (nunca quebra).

Bloco de cada componente:
```
NOME DO COMPONENTE                      ← pode quebrar em mais de uma linha
2024.2 OB MATA58 60 7.0 APR             ← período [natureza] código CH [freq%] nota|-- situação [marcadores]
Dr. FULANO (30h), MSc. BELTRANO         ← docentes (opcional; pode quebrar no meio)
(30h)
```
Situações vistas/da legenda: APR, CANC, DISP, MATR, REP, REPF, REPMF, TRANC, TRANS, INCORP, CUMP.
Naturezas: OB, OP, EB, EP, LV, EC.

### Índices — fórmulas conferidas contra o histórico real (bate na 4ª casa)
- **CR** = Σ(nota × CH) / Σ(CH) dos componentes **com nota**, **excluindo reprovação por falta** (REPF; REPMF/REPNF por analogia).
- **IAP** = CH aprovada (APR) / CH de **todos os componentes encerrados** (inclui TRANC; exclui MATR).
- Com isso a API devolve CR do período, **CR acumulado** e IAP acumulado período a período, e `POST /v1/indices/simular`
  calcula o CR com notas hipotéticas. `calculo_confere_com_oficial` avisa se a regra deixou de bater.
- **% integralizado** = (CH exigida total − CH pendente total) / CH exigida total — igual ao "% Integralizado" do portal.

## Matrícula
- O "Atestado de Matrícula" da UFBA é o **Comprovante de Inscrição Semestral**: lista também as turmas
  INDEFERIDAS (com status). A grade semanal é preenchida por **JavaScript**: spans `id="<dia>_<slot>"`
  (dia: 1=dom … 7=sáb; slot: 1–6 manhã, 7–12 tarde, 13–16 noite) + `elem.innerHTML = 'MATC72'` — o parser lê o script.
- `Local` traz os horários detalhados colados: `PAF 1 - 006 - Terça Horários 18:30 às 19:25PAF 1 - ...` → `horarios[]`.
- `relatorioProcessamento` mostra capacidade, vagas reservadas por curso e o **ranking com nome e matrícula de
  outros alunos**. **Por privacidade a API só devolve contagens por grupo e a posição do próprio aluno.**

## Variações e limitações conhecidas
- Testado com 1 aluno real de graduação (UFBA) + histórico sintético com variações (transferência, ênfase,
  outros índices, DISP sem nota, docentes quebrados, marcadores, seções ausentes) — `tests/test_academico.py`.
- Histórico de pós-graduação/técnico tem outro layout: não testado.
- Observações dos docentes: o aluno de teste não tinha nenhuma — formato com dados não observado (listagem genérica).
- Resultado da avaliação institucional: a UFBA não publica as médias (colunas vêm vazias); a rota devolve as turmas
  do departamento (docente, componente, horário, nº de discentes) e `medias_publicadas=false`.
- Validador público de documentos (`/sigaa/documentos` → `/sigaa/public/autenticidade/form.jsf`) exige **CAPTCHA** —
  NÃO automatizado de propósito. Fase 2: rota em duas etapas que repassa a imagem do captcha pra um humano digitar.
- Cada emissão de histórico/declaração gera um código de verificação novo no SIGAA → cache de 5 min por sessão.
