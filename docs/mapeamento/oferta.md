# Oferta histórica, paridade e pré-requisitos de sequência

Recon de 20/10/2026 no SIGAA real da UFBA (1 sessão, ritmo ≥ 0,3 s). Código: `sigaa/services/oferta.py`,
`sigaa/services/planejamento.py` (`previsao_oferta`, `inferir_sequencias`), `sigaa/models/oferta.py`.

## 1. A Consulta de Turmas sem ano/período

Tela: menu `buscaTurmaBean.popularBuscaGeral` → `/sigaa/ensino/turma/busca_turma.jsf`, form `form`.

O checkbox `form:checkAnoPeriodo` vem **marcado** e `inputAno`/`inputPeriodo` vêm com o período atual. Se o
POST for **sem** `form:checkAnoPeriodo` (como um navegador faz quando o usuário desmarca), o SIGAA busca em
**todos os períodos** que guarda. Com o filtro de componente (`checkCodigo` + `inputCodDisciplina`), uma
requisição traz o histórico inteiro do componente: MATA37 = 53 turmas de 2023.1 a 2026.2, MATA02 = 148 turmas.
O checkbox `checkNivel` vem marcado com G (graduação) e fica assim.

O mesmo vale com o filtro de curso (`checkCurso` + `selectCurso`): sem período, devolve todas as turmas com
reserva pro curso (Sistemas de Informação: 156 turmas, 2025.2 a 2026.2).

## 2. Até que período dá pra voltar

| consulta | resultado |
|---|---|
| componente MATA37, 2019.1 / 2022.1 / 2022.2 | "Nenhuma turma encontrada" |
| componente MATA37, 2023.1 → 2026.2 | turmas em todos os 8 períodos |
| componente MATA02, sem período | 148 turmas, a mais antiga em 2023.1 |

**O SIGAA da UFBA só tem turmas a partir de 2023.1** (`oferta.PRIMEIRO_PERIODO`). Pedir `desde` antes disso
gera um aviso, e a janela começa em 2023.1.

## 3. Por que `/v1/consultas/turmas?ano=2025&periodo=1&curso=...` volta vazio

Não é retenção, nem o filtro de situação, nem bug do parser:

| busca | turmas |
|---|--:|
| curso SI, 2024.2 | 0 |
| curso SI, 2025.1 | 0 |
| curso SI, 2025.2 | 47 (todas CONSOLIDADAS) |
| curso SI, 2026.1 | 48 (CONSOLIDADAS) |
| componente MATA37, 2025.1 (sem curso) | 7 (CONSOLIDADAS) |

O filtro "Curso" da consulta significa **"turma com vaga RESERVADA pro curso"**, e o SIGAA só tem dado de reserva
a partir de **2025.2** (`oferta.PRIMEIRO_PERIODO_RESERVA`). As turmas de 2025.1 existem; só não aparecem nesse filtro.
O filtro de situação não interfere: o `selectSituacaoTurma` vem com ABERTA selecionada, mas o checkbox
`checkSituacao` vem desmarcado, e 2025.2 (todas CONSOLIDADAS) volta cheio.

O que mudou na API:
* `/v1/consultas/turmas` responde `avisos` (campo novo do envelope `Pagina`) explicando o vazio quando há `curso` e
  período anterior a 2025.2, ou período anterior a 2023.1. `ano` e `periodo` agora são validados (422 se fora da faixa);
* `/v1/planejamento/matricula?ano=2025&periodo=1` avisa a mesma coisa;
* pra saber o que abriu antes de 2025.2: `/v1/consultas/turmas?componente=...` ou `/v1/consultas/turmas/historico`.

## 4. Rotas

### `GET /v1/consultas/turmas/historico?componente=MATC73[&desde=2023.1&alvo=2027.1&curso=1876885&incluir_turmas=true]`
`HistoricoOferta`: os períodos com turma (cada um com turmas, docentes, vagas, matriculados), o `resumo` e a `previsao`.
Custa 1 busca no SIGAA (2 com `curso`, em paralelo). Com `curso`, `reserva_para_o_curso` de cada período diz se alguma
turma tinha vaga reservada pro curso (null antes de 2025.2).

### `GET /v1/consultas/turmas/historico/lote?componentes=MATC73,MATA37,...` (até 40)
`list[HistoricoOferta]`, `incluir_turmas=false` por padrão. Um componente que falha volta com o erro em `avisos`,
sem derrubar o lote.

### `GET /v1/planejamento/previsao-oferta[?alvo=2027.1&desde=&incluir_optativas=false]`
Pros pendentes da grade do aluno: `resumo` + `previsao` + `requisito` (pré/co-requisitos do SIGAA e a sequência
inferida), `sem_turma` pras ATIVIDADES, e as listas `provaveis` / `improvaveis` / `sem_historico`.

### Cache
L2 compartilhado (`turmas_do_componente`, `turmas_reservadas`): 6 h. L1: as duas rotas `historico` são
**compartilhadas**, com 6 h de TTL e 7 d de stale-while-revalidate. `previsao-oferta` é por **aluno** (regra
`planejamento/`: 30 min / 1 d), mas o histórico de cada componente vem do L2, igual pra todo aluno.

## 5. Resumo e previsão (regras)

* janela = períodos regulares (x.1, x.2) de `max(desde, 2023.1)` até o período atual do SIGAA (ou até o último
  período com turma, se a oferta do próximo já saiu). Períodos 3/4 vão em `periodos_especiais`, fora da paridade;
* `paridade`: `impar` (só abriu em x.1), `par`, `ambos`, `sem_oferta`. É o fato bruto, sem peso;
* `chance_impar` / `chance_par`: frequência nos semestres daquela paridade, com **peso 2 para os 2 mais recentes**
  (o padrão muda com currículo novo). Exemplo real, MATC73: abriu em 2023.1 e 2024.1, mas não em 2025.1 nem em 2026.1.
  A frequência simples daria 50%; a chance ponderada dá (1+1)/(1+1+2+2) = 33%. `tendencia` = lado(s) com chance ≥ 0,5,
  ou `irregular`;
* `previsao` pro `alvo` (padrão: o período seguinte ao atual): se o SIGAA já publicou turma no alvo, `ja_publicada=true`;
  se não, `probabilidade` = chance ponderada da paridade do alvo, `provavel` = ≥ 0,5, e `confianca` pelo nº de
  semestres da mesma paridade observados (≥3 alta, 2 média, 1 baixa).

Números reais (SI, 20/10/2026, alvo 2027.1): MATC73 33% (tende a par), MATB09 17% (par), MAT236 100% (abre todo
semestre; a observação só por curso, 2025.2 a 2026.2, sugeria "só par"), MATB02 / MATC84 / MATC94 100% no ímpar.

## 6. Pré-requisito de TCC I → TCC II

No SIGAA o dado **existe**: no painel do componente (`/sigaa/graduacao/componente/view_painel.jsf?id=`), e também no
público. GICC0004 (TCC II, ATIVIDADE) tem pré-requisito `( GICC0003 )`, e GICC0003 (TCC I) tem `( LETA09 )`.
Equivalências: MATC97/MATC97A e MATC98/MATC98A. O "Relatório" lista GICC0004 em "pré-requisito de" do GICC0003.

O pré-requisito sumia por nossa causa: o cliente lia `pre_requisitos` dos `candidatos` de `/v1/planejamento/matricula`,
e ATIVIDADE não tem turma, então nunca vira candidato. Correção:

* `/v1/planejamento/matricula` agora devolve `requisitos`: pré/co-requisitos, tipo, `apto` e `faltando` de **todos** os
  pendentes lidos, inclusive os sem turma. Os avisos separam "atividades sem turma (matrícula pelo colegiado)" das
  disciplinas sem turma no período;
* **regra explícita de sequência** (`planejamento.inferir_sequencias`), pra quando o SIGAA não cita o antecessor:
  mesmo nome-base terminado em I/II/III… (ou 1/2/3), mesmo prefixo de letras do código (GICC, MATC…) e mesma natureza
  (obrigatório/optativo) → o de número n vem depois do n−1. O resultado vai em `sequencia_apos`, com
  `origem_sequencia: "inferido"`, entra no `apto`/`faltando` e no `desbloqueia`. Quando o SIGAA já cita o antecessor
  (caso do GICC0004), a origem continua `sigaa` e nada é inferido. A `sugestao` deixa de pôr I e II no mesmo semestre,
  porque o II fica não-apto até o I estar cumprido (ou cursando, com `considerar_cursando_como_aprovado`).
