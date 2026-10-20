"""Navegação das consultas acadêmicas (histórico, matrícula, documentos...).

Todas partem do menu do Portal do Discente (``c.menu("<bean>")``). Documentos que
alimentam várias rotas (o histórico) passam pelo ``c.memo`` pra não serem reemitidos
a cada chamada — cada emissão gera um código de verificação novo no SIGAA.
"""

from __future__ import annotations

from ..client import Page, SigaaClient
from ..errors import NaoEncontrado
from ..models.academico import (
    AtividadeAutonomaDetalhe,
    AtividadesAutonomas,
    ComprovanteMatricula,
    DeclaracaoVinculo,
    FiltrosAvaliacao,
    Historico,
    Integralizacao,
    ListaGenerica,
    ResultadoAvaliacao,
    ResultadoProcessamento,
    Suspensoes,
    Trancamento,
)
from ..parsers.academico import (
    mensagens_sigaa,
    parse_atividade_autonoma_detalhe,
    parse_atividades_autonomas,
    parse_comprovante_inscricao,
    parse_comprovante_solicitacao,
    parse_declaracao_vinculo_pdf,
    parse_filtros_avaliacao,
    parse_listagem,
    parse_resultado_avaliacao,
    parse_resultado_processamento,
    parse_suspensoes,
    parse_trancamentos,
)
from ..parsers.historico_pdf import parse_historico_pdf

TTL_DOCUMENTO = 300.0  # 5 min

MENU = {
    "historico": "portalDiscente.historico",
    "atestado": "portalDiscente.atestadoMatricula",
    "declaracao": "declaracaoVinculo.emitirDeclaracao",
    "diploma": "buscaDiplomaDigitalMBean.iniciarBuscaDiscente",
    "aproveitamentos": "solicitacaoAproveitamentoEstudosMBean.listar",
    "avaliacoes_anteriores": "avaliacaoInstitucionalAnterior.listaAnterior",
    "comprovante": "matriculaGraduacao.verComprovanteSolicitacoes",
    "trancamentos": "trancamentoMatricula.iniciarMeusTrancamentos",
    "suspensoes": "trancamentoPrograma.exibirMinhasSolicitacoes",
    "autonomas": "solicitacaoRegistroAtividadeAutonomaMBean.listar",
    "avaliacao_resultado": "relatorioAvaliacaoMBean.iniciarConsultaPublica",
    "observacoes": "relatorioAvaliacaoMBean.iniciarObservacoesTurmasDiscente",
}


def _exigir_pdf(page: Page, oque: str) -> bytes:
    if page.is_pdf:
        return page.content
    msgs = mensagens_sigaa(page.html) if page.is_html else []
    raise NaoEncontrado(f"O SIGAA não gerou o PDF de {oque}." + (f" Mensagem: {msgs[0]}" if msgs else ""))


# ------------------------------------------------------------------ histórico
async def historico_pdf(c: SigaaClient) -> bytes:
    async def emitir():
        return _exigir_pdf(await c.menu(MENU["historico"]), "histórico")

    return await c.memo("historico_pdf", TTL_DOCUMENTO, emitir)


async def historico(c: SigaaClient) -> Historico:
    pdf = await historico_pdf(c)
    return await c.memo("historico", TTL_DOCUMENTO, _async(lambda: parse_historico_pdf(pdf)))


def _async(fn):
    async def run():
        return fn()

    return run


async def integralizacao(c: SigaaClient) -> Integralizacao:
    h = await historico(c)
    total = next((x for x in h.carga_horaria if x.categoria.lower().startswith("total")), None)
    pct = None
    if total and total.exigido and total.pendente is not None:
        pct = round(100 * (total.exigido - total.pendente) / total.exigido, 2)
    return Integralizacao(
        curriculo=h.vinculo.curriculo,
        percentual=pct,
        carga_horaria=h.carga_horaria,
        obrigatorios_pendentes=h.obrigatorios_pendentes,
        atividades_autonomas=h.atividades_autonomas,
        carga_horaria_extensionista=h.carga_horaria_extensionista,
        periodo_letivo_atual=h.vinculo.periodo_letivo_atual,
        prazo_conclusao_padrao=h.vinculo.prazo_conclusao_padrao,
        prazo_conclusao_maximo=h.vinculo.prazo_conclusao_maximo,
    )


# ------------------------------------------------------------------ documentos
async def comprovante_inscricao(c: SigaaClient) -> ComprovanteMatricula:
    page = await c.menu(MENU["atestado"])
    if "relatorio" not in page.html:
        raise NaoEncontrado(_msg(page, "O SIGAA não emitiu o comprovante de inscrição."))
    return parse_comprovante_inscricao(page.html)


async def comprovante_inscricao_html(c: SigaaClient) -> str:
    page = await c.menu(MENU["atestado"])
    return page.html


async def declaracao_vinculo_pdf(c: SigaaClient) -> bytes:
    async def emitir():
        return _exigir_pdf(await c.menu(MENU["declaracao"]), "declaração de vínculo")

    return await c.memo("declaracao_pdf", TTL_DOCUMENTO, emitir)


async def declaracao_vinculo(c: SigaaClient) -> DeclaracaoVinculo:
    return parse_declaracao_vinculo_pdf(await declaracao_vinculo_pdf(c))


# ------------------------------------------------------------------ matrícula
async def matricula(c: SigaaClient) -> ComprovanteMatricula:
    page = await c.menu(MENU["comprovante"])
    if "comprovante_solicitacoes" not in page.url and "Comprovante" not in page.html:
        raise NaoEncontrado(_msg(page, "Não há comprovante de solicitação de matrícula disponível."))
    return parse_comprovante_solicitacao(page.html)


async def resultado_processamento(c: SigaaClient, turma_id: int) -> ResultadoProcessamento:
    comp = await matricula(c)
    alvo = next((t for t in comp.turmas if t.turma_id == turma_id), None)
    if alvo is None:
        raise NaoEncontrado(f"A turma {turma_id} não está no comprovante de matrícula do período {comp.periodo}.")
    q = f"/sigaa/relatorioProcessamento?idTurma={turma_id}" + ("&rematricula=true" if alvo.rematricula else "")
    page = await c.get(q)
    return parse_resultado_processamento(page.html, turma_id, comp.matricula, alvo.rematricula)


async def resultados_processamento(c: SigaaClient) -> list[ResultadoProcessamento]:
    comp = await matricula(c)

    def fluxo(t):
        async def f(s: SigaaClient) -> ResultadoProcessamento:
            q = f"/sigaa/relatorioProcessamento?idTurma={t.turma_id}" + ("&rematricula=true" if t.rematricula else "")
            page = await s.get(q)  # GET direto (sem ViewState): cada turma numa sessão do pool, ao mesmo tempo
            return parse_resultado_processamento(page.html, t.turma_id, comp.matricula, t.rematricula)

        return f

    return await c.paralelo([fluxo(t) for t in comp.turmas if t.turma_id is not None])


# --------------------------------------------------------- outras consultas
async def trancamentos(c: SigaaClient) -> list[Trancamento]:
    page = await c.menu(MENU["trancamentos"])
    return parse_trancamentos(page.html)


async def suspensoes(c: SigaaClient) -> Suspensoes:
    page = await c.menu(MENU["suspensoes"])
    return parse_suspensoes(page.html)


async def atividades_autonomas(c: SigaaClient) -> AtividadesAutonomas:
    page = await c.menu(MENU["autonomas"])
    return parse_atividades_autonomas(page.html)


async def aproveitamentos(c: SigaaClient) -> ListaGenerica:
    return parse_listagem((await c.menu(MENU["aproveitamentos"])).html)


async def diploma_digital(c: SigaaClient) -> ListaGenerica:
    return parse_listagem((await c.menu(MENU["diploma"])).html)


async def avaliacoes_institucionais(c: SigaaClient) -> ListaGenerica:
    return parse_listagem((await c.menu(MENU["avaliacoes_anteriores"])).html)


def _msg(page: Page, padrao: str) -> str:
    msgs = mensagens_sigaa(page.html) if page.is_html else []
    return msgs[0] if msgs else padrao



async def filtros_avaliacao(c: SigaaClient) -> FiltrosAvaliacao:
    return parse_filtros_avaliacao((await c.menu(MENU["avaliacao_resultado"])).html)


async def resultado_avaliacao(c: SigaaClient, departamento_id: str, periodo: str) -> ResultadoAvaliacao:
    """``periodo`` aceita o ano-período ("2025.2") ou o id interno do SIGAA."""
    page = await c.menu(MENU["avaliacao_resultado"])
    filtros = parse_filtros_avaliacao(page.html)
    per = next((p for p in filtros.periodos if periodo in (p.id, p.nome)), None)
    if per is None:
        raise NaoEncontrado(f"Período {periodo} sem relatório. Disponíveis: {', '.join(p.nome for p in filtros.periodos)}")
    if not any(d.id == departamento_id for d in filtros.departamentos):
        raise NaoEncontrado(f"Departamento {departamento_id} não existe (veja /v1/avaliacao-institucional/filtros).")
    res = await c.submit(page, "form", extra={"form:escolha_relatorio": departamento_id, "form:anoPeriodo": per.id}, botao="form:botaoRelatorio")
    msgs = mensagens_sigaa(res.html)
    out = parse_resultado_avaliacao(res.html)
    if not out.linhas and msgs:
        raise NaoEncontrado(msgs[0])
    return out


async def observacoes_docentes(c: SigaaClient, periodo: str) -> ListaGenerica:
    """Observações que os docentes deixaram sobre as turmas do aluno na avaliação institucional.
    (Formato com dados ainda não observado — devolvido como listagem genérica.)"""
    page = await c.menu(MENU["observacoes"])
    sel = page.soup.find("select", attrs={"name": "form:anoPeriodo"})
    opcoes = {(o.get_text(strip=True)): o.get("value") for o in sel.find_all("option")} if sel else {}
    valor = opcoes.get(periodo) or (periodo if periodo in opcoes.values() else None)
    if not valor:
        raise NaoEncontrado(f"Período {periodo} indisponível. Disponíveis: {', '.join(k for k in opcoes if not k.startswith('--'))}")
    res = await c.submit(page, "form", extra={"form:anoPeriodo": valor}, botao="form:consultar")
    lista = parse_listagem(res.html)
    msgs = mensagens_sigaa(res.html)
    if lista.vazio and msgs:
        lista.mensagem = msgs[0]
    return lista


async def _abrir_atividade(c: SigaaClient, registro_id: int) -> Page:
    lista = await c.menu(MENU["autonomas"])
    link = next((ln for ln in lista.links_jsf() if ln.params.get("id") == str(registro_id)), None)
    if link is None:
        raise NaoEncontrado(f"Registro de atividade {registro_id} não encontrado.")
    return await c.clicar(lista, link)


async def atividade_autonoma(c: SigaaClient, registro_id: int) -> AtividadeAutonomaDetalhe:
    return parse_atividade_autonoma_detalhe((await _abrir_atividade(c, registro_id)).html, registro_id)


async def atividade_autonoma_comprovante(c: SigaaClient, registro_id: int) -> tuple[bytes, str, str]:
    det = await _abrir_atividade(c, registro_id)
    link = next((ln for ln in det.links_jsf() if "Baixar" in (ln.element.get("title") or "") or ln.texto), None)
    if link is None:
        raise NaoEncontrado("Este registro não tem comprovante.")
    arq = await c.clicar(det, link)
    if arq.is_html and "Detalhes do Registro" in arq.html:
        raise NaoEncontrado("O SIGAA não entregou o arquivo do comprovante.")
    return arq.content, arq.content_type or "application/octet-stream", arq.nome_arquivo or link.texto or f"comprovante-{registro_id}"
