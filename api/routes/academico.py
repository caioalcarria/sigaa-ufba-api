"""Rotas da vida acadêmica: histórico, índices, integralização, matrícula, documentos."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from sigaa.models.academico import (
    AtividadeAutonomaDetalhe,
    AtividadesAutonomas,
    ComponenteCursado,
    ComponentePendente,
    ComprovanteMatricula,
    DeclaracaoVinculo,
    FiltrosAvaliacao,
    EstatisticaPeriodo,
    Historico,
    Indices,
    Integralizacao,
    ListaGenerica,
    ResultadoAvaliacao,
    ResultadoProcessamento,
    Suspensoes,
    Trancamento,
)
from sigaa.parsers.historico_pdf import calcular_cr, calcular_iap
from sigaa.services import academico as svc

from ..deps import Cliente
from ..seguranca_http import CSP_HTML_SIGAA, content_disposition, resposta_arquivo

router = APIRouter(prefix="/v1", tags=["Acadêmico"])

PDF = {200: {"content": {"application/pdf": {}}, "description": "O PDF original emitido pelo SIGAA."}}


# --------------------------------------------------------------------- histórico
@router.get(
    "/historico",
    response_model=Historico,
    summary="Histórico escolar completo (extraído do PDF)",
    description="Emite o histórico no SIGAA e devolve TODAS as seções já estruturadas: dados do vínculo, "
    "índices, cada componente cursado (com docentes), carga horária integralizada/pendente, extensão, "
    "obrigatórias pendentes, equivalências, observações e estatísticas calculadas (CR por período, CR "
    "acumulado, taxa de aprovação). Cache de 5 min por sessão.",
)
async def get_historico(cli: Cliente):
    return await cli.executar(svc.historico)


@router.get("/historico/pdf", summary="Histórico escolar (PDF original)", response_class=Response, responses=PDF)
async def get_historico_pdf(cli: Cliente):
    pdf = await cli.executar(svc.historico_pdf)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="historico.pdf"'})


@router.get(
    "/historico/componentes",
    response_model=list[ComponenteCursado],
    summary="Componentes cursados (filtráveis)",
    description="Só a lista de componentes do histórico. Filtros opcionais: `periodo` (2024.2), `situacao` (APR, REP, TRANC, MATR...), `natureza` (OB, OP...).",
)
async def get_componentes(cli: Cliente, periodo: str | None = None, situacao: str | None = None, natureza: str | None = None):
    h = await cli.executar(svc.historico)
    out = h.componentes
    if periodo:
        out = [c for c in out if c.periodo == periodo]
    if situacao:
        out = [c for c in out if c.situacao.upper() == situacao.upper()]
    if natureza:
        out = [c for c in out if (c.natureza or "").upper() == natureza.upper()]
    return out


class IndicesResposta(BaseModel):
    oficiais: Indices = Field(description="Índices como o SIGAA imprime no histórico.")
    cr_calculado: float | None = None
    iap_calculado: float | None = None
    calculo_confere_com_oficial: bool | None = None
    evolucao: list[EstatisticaPeriodo] = Field(description="CR do período, CR acumulado e IAP acumulado, período a período.")


@router.get("/indices", response_model=IndicesResposta, summary="CR, IAP e a evolução por período")
async def get_indices(cli: Cliente):
    h = await cli.executar(svc.historico)
    e = h.estatisticas
    return IndicesResposta(
        oficiais=h.indices,
        cr_calculado=e.cr_calculado if e else None,
        iap_calculado=e.iap_calculado if e else None,
        calculo_confere_com_oficial=e.calculo_confere_com_oficial if e else None,
        evolucao=e.por_periodo if e else [],
    )


class NotaHipotetica(BaseModel):
    codigo: str = Field(description="Código do componente (um dos que estão como MATR, ou qualquer outro).")
    nota: float = Field(ge=0, le=10)
    carga_horaria: int | None = Field(None, description="Obrigatória se o componente não estiver no histórico.")
    reprovado_por_falta: bool = False


class SimulacaoRequest(BaseModel):
    notas: list[NotaHipotetica]


class SimulacaoResposta(BaseModel):
    cr_atual: float | None
    cr_simulado: float | None
    iap_atual: float | None
    iap_simulado: float | None
    componentes_considerados: list[ComponenteCursado]


@router.post(
    "/indices/simular",
    response_model=SimulacaoResposta,
    summary="Simular o CR com notas hipotéticas",
    description="Calcula como ficariam CR e IAP se o aluno tirasse as notas informadas (normalmente nos componentes MATR do semestre). "
    "Conta feita pela API com a mesma regra do CR oficial; nada é enviado ao SIGAA.",
)
async def post_simular(cli: Cliente, corpo: SimulacaoRequest):
    h = await cli.executar(svc.historico)
    comps = [c.model_copy() for c in h.componentes]
    por_codigo = {c.codigo: c for c in comps if c.cursando}
    considerados = []
    for n in corpo.notas:
        alvo = por_codigo.get(n.codigo)
        sit = "REPF" if n.reprovado_por_falta else ("APR" if n.nota >= 5 else "REP")
        if alvo is None:
            alvo = ComponenteCursado(
                periodo="simulado", codigo=n.codigo, nome=n.codigo, carga_horaria=n.carga_horaria or 60, situacao="MATR", aprovado=False, cursando=True
            )
            comps.append(alvo)
        alvo.nota, alvo.situacao, alvo.aprovado, alvo.cursando = n.nota, sit, sit == "APR", False
        considerados.append(alvo)
    return SimulacaoResposta(
        cr_atual=calcular_cr(h.componentes),
        cr_simulado=calcular_cr(comps),
        iap_atual=calcular_iap(h.componentes),
        iap_simulado=calcular_iap(comps),
        componentes_considerados=considerados,
    )


@router.get("/integralizacao", response_model=Integralizacao, summary="Quanto do curso já foi integralizado")
async def get_integralizacao(cli: Cliente):
    return await cli.executar(svc.integralizacao)


class Pendencias(BaseModel):
    obrigatorios: list[ComponentePendente]
    carga_horaria_optativa_pendente: int | None
    carga_horaria_complementar_pendente: int | None
    carga_horaria_total_pendente: int | None
    enade_pendente: list[str] = Field(default_factory=list)


@router.get("/pendencias", response_model=Pendencias, summary="O que falta pra se formar")
async def get_pendencias(cli: Cliente):
    i = await cli.executar(svc.integralizacao)

    def pend(prefixo: str):
        x = next((c for c in i.carga_horaria if c.categoria.lower().startswith(prefixo)), None)
        return x.pendente if x else None

    return Pendencias(
        obrigatorios=[c for c in i.obrigatorios_pendentes if c.codigo.upper() != "ENADE"],
        carga_horaria_optativa_pendente=pend("opta"),
        carga_horaria_complementar_pendente=pend("compl"),
        carga_horaria_total_pendente=pend("total"),
        enade_pendente=[c.nome for c in i.obrigatorios_pendentes if c.codigo.upper() == "ENADE"],
    )


# --------------------------------------------------------------------- matrícula
@router.get(
    "/matricula",
    response_model=ComprovanteMatricula,
    summary="Matrícula do período (comprovante de solicitação)",
    description="Todas as turmas solicitadas no período, com a situação de cada uma (DEFERIDA, INDEFERIDA, TRANCADO...), horários detalhados e a grade semanal.",
)
async def get_matricula(cli: Cliente):
    return await cli.executar(svc.matricula)


@router.get(
    "/matricula/processamento",
    response_model=list[ResultadoProcessamento],
    summary="Resultado do processamento de todas as turmas solicitadas",
    description="Pra cada turma solicitada: capacidade, vagas por curso, quantos solicitaram/foram matriculados em cada grupo e a POSIÇÃO do aluno no ranking. Nome e matrícula de outros alunos nunca são devolvidos.",
)
async def get_processamentos(cli: Cliente):
    return await cli.executar(svc.resultados_processamento)


@router.get("/matricula/processamento/{turma_id}", response_model=ResultadoProcessamento, summary="Resultado do processamento de uma turma")
async def get_processamento(cli: Cliente, turma_id: int):
    return await cli.executar(lambda c: svc.resultado_processamento(c, turma_id))


@router.get(
    "/documentos/comprovante-inscricao",
    response_model=ComprovanteMatricula,
    summary="Comprovante de inscrição semestral (o 'Atestado de Matrícula')",
    description="O item 'Emitir Atestado de Matrícula' do SIGAA da UFBA emite o Comprovante de Inscrição Semestral: turmas, docentes, local, horário, status e grade.",
)
async def get_comprovante_inscricao(cli: Cliente):
    return await cli.executar(svc.comprovante_inscricao)


@router.get("/documentos/comprovante-inscricao/html", summary="Comprovante de inscrição (HTML original, pra imprimir)", response_class=Response)
async def get_comprovante_inscricao_html(cli: Cliente):
    html = await cli.executar(svc.comprovante_inscricao_html)
    # HTML do SIGAA servido na origem da API: em sandbox (sem script, origem opaca — não lê token nem nada
    # da API), sem carregar nada de fora; continua text/html e inline pra abrir e imprimir
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Security-Policy": CSP_HTML_SIGAA, "Content-Disposition": content_disposition("comprovante-inscricao.html", inline=True)},
    )


@router.get("/documentos/declaracao-vinculo", response_model=DeclaracaoVinculo, summary="Declaração de vínculo (dados extraídos)")
async def get_declaracao(cli: Cliente):
    return await cli.executar(svc.declaracao_vinculo)


@router.get("/documentos/declaracao-vinculo/pdf", summary="Declaração de vínculo (PDF original)", response_class=Response, responses=PDF)
async def get_declaracao_pdf(cli: Cliente):
    pdf = await cli.executar(svc.declaracao_vinculo_pdf)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="declaracao-vinculo.pdf"'})


# ------------------------------------------------------------ outras consultas
@router.get("/trancamentos", response_model=list[Trancamento], summary="Solicitações de trancamento de componente")
async def get_trancamentos(cli: Cliente):
    return await cli.executar(svc.trancamentos)


@router.get("/suspensoes", response_model=Suspensoes, summary="Suspensões de programa + histórico de movimentações")
async def get_suspensoes(cli: Cliente):
    return await cli.executar(svc.suspensoes)


@router.get("/atividades-autonomas", response_model=AtividadesAutonomas, summary="Registros de atividades autônomas/complementares")
async def get_autonomas(cli: Cliente):
    return await cli.executar(svc.atividades_autonomas)


@router.get("/aproveitamentos", response_model=ListaGenerica, summary="Solicitações de aproveitamento de estudos")
async def get_aproveitamentos(cli: Cliente):
    return await cli.executar(svc.aproveitamentos)


@router.get("/diploma", response_model=ListaGenerica, summary="Diplomas digitais emitidos")
async def get_diploma(cli: Cliente):
    return await cli.executar(svc.diploma_digital)


@router.get("/avaliacao-institucional", response_model=ListaGenerica, summary="Avaliações institucionais já respondidas")
async def get_avaliacoes(cli: Cliente):
    return await cli.executar(svc.avaliacoes_institucionais)


@router.get("/avaliacao-institucional/filtros", response_model=FiltrosAvaliacao, summary="Departamentos e períodos do relatório da avaliação institucional")
async def get_filtros_avaliacao(cli: Cliente):
    return await cli.executar(svc.filtros_avaliacao)


@router.get(
    "/avaliacao-institucional/resultado",
    response_model=ResultadoAvaliacao,
    summary="Relatório sintético da avaliação institucional de um departamento",
    description="Turmas do departamento no período com docente, horário e nº de discentes (e as médias da avaliação, quando a instituição publica). "
    "`departamento_id` vem de /v1/avaliacao-institucional/filtros; `periodo` = ano-período (2025.2).",
)
async def get_resultado_avaliacao(cli: Cliente, departamento_id: str, periodo: str):
    return await cli.executar(lambda c: svc.resultado_avaliacao(c, departamento_id, periodo))


@router.get("/avaliacao-institucional/observacoes", response_model=ListaGenerica, summary="Observações dos docentes sobre as minhas turmas")
async def get_observacoes(cli: Cliente, periodo: str):
    return await cli.executar(lambda c: svc.observacoes_docentes(c, periodo))


@router.get(
    "/atividades-autonomas/{registro_id}",
    response_model=AtividadeAutonomaDetalhe,
    summary="Detalhe de um registro de atividade autônoma (com o parecer do coordenador)",
)
async def get_autonoma(cli: Cliente, registro_id: int):
    return await cli.executar(lambda c: svc.atividade_autonoma(c, registro_id))


@router.get("/atividades-autonomas/{registro_id}/comprovante", summary="Baixar o comprovante enviado", response_class=Response)
async def get_autonoma_comprovante(cli: Cliente, registro_id: int):
    dados, tipo, nome = await cli.executar(lambda c: svc.atividade_autonoma_comprovante(c, registro_id))
    # nome e tipo vêm do SIGAA: filename saneado (RFC 6266/5987) e tipo ativo (HTML/SVG...) vira download
    return resposta_arquivo(dados, tipo, nome, inline=True, padrao=f"comprovante-{registro_id}")
