"""Serviços da área "consultas" (logada) — a NAVEGAÇÃO até cada tela + o parser.

Telas (passo a passo completo em ``docs/mapeamento/consultas.md``):

* Calendário Acadêmico ........ menu ``calendario.iniciarBusca`` → link "Visualizar" (``id``)
* Consulta geral de cursos .... menu ``curso.popularBuscaGeral`` → form ``busca``
* Componente curricular ....... menu ``componenteCurricular.popularBuscaDiscente`` → form ``formBusca``;
  detalhe por GET direto ``/sigaa/graduacao/componente/view_painel.jsf?ajaxRequest=true&id=``;
  relatório completo = busca por código → link "Relatório para impressão".
  ⚠ o link "Visualizar componente curricular" dá *Comportamento Inesperado* no SIGAA UFBA — não usar.
* Estrutura curricular ........ menu ``curriculo.popularBuscaGeral`` → combo curso (submit) → Buscar →
  links ``resultado:detalhar|relatorio|declaracaoPrazoMaximo`` (o SIGAA aceita qualquer ``id``).
* Turma ....................... menu ``buscaTurmaBean.popularBuscaGeral`` → form ``form``;
  painel por GET ``/sigaa/graduacao/turma/view_painel.jsf?ajaxRequest=true&contarMatriculados=true&id=``;
  processamento por GET ``/sigaa/relatorioProcessamento?idTurma=`` (só agregados saem daqui).
* Unidades acadêmicas ......... menu ``unidade.popularBuscaGeral`` → form ``formBuscaUnidade``.
* (Salas livres — módulo Gerenciamento de Salas — ficam na frente *portal*: ``/v1/salas-livres``.)

Nenhum serviço guarda estado entre chamadas. Filtro inválido/faltando → ``ValueError`` (a rota devolve 422). Para as rotas SEM login (SIGAA público) use
:func:`cliente_anonimo`.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import urlencode, urljoin

from sigaa.client import Page, SigaaClient, form_fields
from sigaa.errors import NaoEncontrado, NavegacaoInvalida
from sigaa.models.consultas import (
    Calendario,
    CalendarioResumo,
    ComponenteDetalhe,
    ComponenteResumo,
    CursoConsulta,
    CursoOpcao,
    DeclaracaoPrazoMaximo,
    EstruturaDetalhe,
    EstruturaResumo,
    Opcao,
    ProcessamentoTurma,
    TurmaDetalhe,
    TurmaOferta,
    UnidadeConsulta,
)
from sigaa.parsers import consultas as P

# --------------------------------------------------------------- utilidades


#: no máximo N sessões anônimas navegando ao mesmo tempo (as rotas públicas não têm token:
#: sem isso, um cliente qualquer poderia martelar o SIGAA abrindo sessões em paralelo)
MAX_ANONIMOS = 4
_anonimos = asyncio.Semaphore(MAX_ANONIMOS)


@asynccontextmanager
async def cliente_anonimo() -> AsyncIterator[SigaaClient]:
    """Um ``SigaaClient`` SEM login, criado por requisição e fechado no fim (rotas /v1/publico).

    Cada requisição pública abre a sua própria sessão anônima: o JSF do SIGAA guarda o estado
    da tela no servidor, então duas requisições não podem dividir a mesma sessão. Intervalo de
    0,35 s entre pedidos e no máximo ``MAX_ANONIMOS`` sessões simultâneas (as demais esperam)."""
    async with _anonimos:
        c = SigaaClient(min_interval=0.35)
        try:
            yield c
        finally:
            await c.close()


async def _submit(
    c: SigaaClient, page: Page, form_id: str, extra: dict[str, str] | None = None, botao: tuple[str, str] | None = None
) -> Page:
    """Como ``c.submit``, mas com o corpo em ISO-8859-1: o SIGAA decodifica o POST como latin-1 e o httpx
    manda UTF-8 — sem isso, filtro com acento ('LÓGICA', 'JOSÉ') chega corrompido e a busca volta vazia."""
    form = page.form(form_id)
    if form is None:
        raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página.")
    data = form_fields(form)
    if botao:
        data[botao[0]] = botao[1]
    if extra:
        data.update({k: str(v) for k, v in extra.items()})
    corpo = urlencode(list(data.items()), encoding="iso-8859-1", errors="xmlcharrefreplace").encode("ascii")
    return await c.post(
        urljoin(page.url, form.get("action") or page.url),
        {},
        content=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"},
    )


def _botao(page: Page, form_id: str, valor: str) -> tuple[str, str]:
    """Nome do ``<input type=submit>`` pelo texto (os ids j_id_jsp_* podem mudar entre versões)."""
    form = page.form(form_id)
    if form is None:
        raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página.")
    for b in form.find_all("input", type="submit"):
        if (b.get("value") or "").strip().lower().startswith(valor.lower()):
            return b["name"], b["value"]
    raise NavegacaoInvalida(f"Botão '{valor}' não encontrado em '{form_id}'.")


def _campo_na_linha(page: Page, form_id: str, checkbox_id: str, tag: str = "input") -> str | None:
    """Nome do campo (text/select) que fica na MESMA linha do checkbox ``checkbox_id``.

    Os campos de texto do formulário de componentes têm nomes gerados (``j_id_jsp_...``);
    o checkbox ao lado tem id fixo, então achamos o campo por ele."""
    form = page.form(form_id)
    cb = form.find("input", id=checkbox_id) if form else None
    tr = cb.find_parent("tr") if cb else None
    if tr is None:
        return None
    if tag == "select":
        el = tr.find("select")
    else:
        el = next((i for i in tr.find_all("input") if (i.get("type") or "text") == "text"), None)
    return el.get("name") if el else None


def _sem_resultado(page: Page) -> bool:
    msgs = " ".join(P.mensagens_sigaa(page.content)).lower()
    return "nenhum" in msgs and "encontrad" in msgs


# =============================================================== calendário


async def listar_calendarios(c: SigaaClient) -> list[CalendarioResumo]:
    """Todos os calendários acadêmicos (1969.1 → próximo período), geral e EAD."""
    page = await c.menu("calendario.iniciarBusca")
    return P.parse_lista_calendarios(page.content)


def _semestre_atual(page: Page) -> tuple[int, int] | None:
    el = page.soup.select_one("p.periodo-atual strong")
    m = re.search(r"(\d{4})\.(\d)", el.get_text() if el else "")
    return (int(m.group(1)), int(m.group(2))) if m else None


async def calendario(
    c: SigaaClient,
    ano: int | None = None,
    periodo: int | None = None,
    ead: bool = False,
    id_calendario: int | None = None,
) -> Calendario:
    """Um calendário com todos os prazos. Sem ``ano``/``periodo``: o do semestre atual do aluno."""
    page = await c.menu("calendario.iniciarBusca")
    lista = P.parse_lista_calendarios(page.content)
    if id_calendario is not None:
        alvo = next((x for x in lista if x.id == id_calendario), None)
    else:
        if ano is None or periodo is None:
            atual = _semestre_atual(page)
            if atual is None and lista:
                atual = (lista[0].ano, lista[0].periodo)
            ano, periodo = (ano, periodo) if ano and periodo else atual or (None, None)
        alvo = next((x for x in lista if x.ano == ano and x.periodo == periodo and x.ead == ead), None)
    if alvo is None:
        raise NaoEncontrado("Calendário acadêmico não encontrado para os filtros informados.")
    if alvo.ead:
        # Abrir o calendário de ENSINO A DISTÂNCIA dá "Comportamento Inesperado" no SIGAA UFBA
        # (visto em 19/10/2026 com 2026.1) — e cada erro manda e-mail pra STI. Bloqueado de propósito.
        raise ValueError(
            "O SIGAA da UFBA quebra ('Comportamento Inesperado') ao abrir calendários de Ensino a Distância; consulta bloqueada."
        )
    det = await c.clicar(page, f"'id':'{alvo.id}'")
    return P.parse_calendario(det.content, alvo)


# =================================================================== cursos


async def buscar_cursos(c: SigaaClient, nivel: str = "G", nome: str | None = None) -> list[CursoConsulta]:
    """'Consulta geral de cursos'. ``nivel``: G=graduação, L=lato, S=stricto, E=mestrado, D=doutorado..."""
    page = await c.menu("curso.popularBuscaGeral")
    extra = {"busca:niveis": nivel, "paramBusca": "nome" if nome else "todos"}
    if nome:
        extra["busca:param1"] = nome
    res = await _submit(c, page, "busca", extra, botao=_botao(page, "busca", "Buscar"))
    return P.parse_busca_cursos(res.content)


async def cursos_com_id(c: SigaaClient) -> list[CursoOpcao]:
    """Cursos de graduação com o id do SIGAA (combo da tela de Estrutura Curricular)."""
    page = await c.menu("curriculo.popularBuscaGeral")
    return P.parse_opcoes_cursos(page.content, "busca:curso")


# ============================================================== componentes


async def opcoes_componentes(c: SigaaClient) -> dict[str, list[Opcao]]:
    """Valores aceitos nos filtros da busca de componentes (níveis, unidades, tipos, modalidades)."""
    page = await c.menu("componenteCurricular.popularBuscaDiscente")
    nivel = _campo_na_linha(page, "formBusca", "formBusca:checkNivel", "select") or ""
    return {
        "niveis": P.opcoes_select(page.content, nivel),
        "unidades": P.opcoes_select(page.content, "formBusca:unidades"),
        "tipos": P.opcoes_select(page.content, "formBusca:tipos"),
        "modalidades": P.opcoes_select(page.content, "formBusca:modalidades"),
    }


async def buscar_componentes(
    c: SigaaClient,
    codigo: str | None = None,
    nome: str | None = None,
    nivel: str | None = None,
    unidade: int | None = None,
    tipo: int | None = None,
    modalidade: int | None = None,
) -> list[ComponenteResumo]:
    """'Consulta geral de componentes curriculares' (pelo menos um filtro)."""
    if not any([codigo, nome, nivel, unidade, tipo, modalidade]):
        raise ValueError("Informe pelo menos um filtro (codigo, nome, nivel, unidade, tipo ou modalidade).")
    page = await c.menu("componenteCurricular.popularBuscaDiscente")
    f = "formBusca"
    extra: dict[str, str] = {}
    if codigo and (campo := _campo_na_linha(page, f, "formBusca:checkCodigo")):
        extra |= {"formBusca:checkCodigo": "on", campo: codigo.strip().upper()}
    if nome and (campo := _campo_na_linha(page, f, "formBusca:checkNome")):
        extra |= {"formBusca:checkNome": "on", campo: nome.strip()}
    if nivel and (campo := _campo_na_linha(page, f, "formBusca:checkNivel", "select")):
        extra |= {"formBusca:checkNivel": "on", campo: nivel}
    if unidade:
        extra |= {"formBusca:checkUnidade": "on", "formBusca:unidades": str(unidade)}
    if tipo:
        extra |= {"formBusca:checkTipo": "on", "formBusca:tipos": str(tipo)}
    if modalidade:
        extra |= {"formBusca:checkModalidade": "on", "formBusca:modalidades": str(modalidade)}
    res = await _submit(c, page, f, extra, botao=_botao(page, f, "Buscar"))
    return P.parse_busca_componentes(res.content)


async def componente(c: SigaaClient, id_componente: int, completo: bool = False) -> ComponenteDetalhe:
    """Detalhe pelo id (painel por GET direto). ``completo=True`` acrescenta o 'Relatório para
    impressão' (quem tem este como pré-requisito/equivalente, histórico, currículos) — +3 telas."""
    page = await c.get(f"/sigaa/graduacao/componente/view_painel.jsf?ajaxRequest=true&id={int(id_componente)}")
    comp = P.parse_componente(page.content, id_componente)
    if comp.codigo is None and comp.nome is None:
        raise NaoEncontrado(f"Componente {id_componente} não encontrado.")
    if not completo:
        return comp
    busca = await c.menu("componenteCurricular.popularBuscaDiscente")
    campo = _campo_na_linha(busca, "formBusca", "formBusca:checkCodigo")
    if not campo:
        return comp
    res = await _submit(
        c, busca, "formBusca", {"formBusca:checkCodigo": "on", campo: comp.codigo}, botao=_botao(busca, "formBusca", "Buscar")
    )
    alvo = next(
        (ln for ln in res.links_jsf() if ln.params.get("id") == str(id_componente) and "Relat" in (ln.element.get("title") or "")),
        None,
    )
    if alvo is None:
        return comp
    rel = await c.clicar(res, alvo)
    return P.mesclar_componente(comp, P.parse_componente(rel.content, id_componente))


async def programa_componente(c: SigaaClient, codigo: str) -> str | None:
    """HTML (texto) do 'Programa atual do componente' — quase nunca cadastrado na UFBA.
    Levanta ``NaoEncontrado`` com a mensagem do SIGAA quando não há programa."""
    busca = await c.menu("componenteCurricular.popularBuscaDiscente")
    campo = _campo_na_linha(busca, "formBusca", "formBusca:checkCodigo")
    res = await _submit(c, busca, "formBusca", {"formBusca:checkCodigo": "on", campo or "": codigo.upper()}, botao=_botao(busca, "formBusca", "Buscar"))
    alvo = next((ln for ln in res.links_jsf() if "idComponente" in ln.params), None)
    if alvo is None:
        raise NaoEncontrado(f"Componente {codigo} não encontrado.")
    prog = await c.clicar(res, alvo)
    msgs = P.mensagens_sigaa(prog.content)
    if any("programa" in m.lower() for m in msgs):
        raise NaoEncontrado(msgs[0])
    return prog.text()


# =============================================================== estruturas


async def _resultado_estruturas(c: SigaaClient, curso_id: int | None = None, codigo: str | None = None, somente_ativas: bool = False) -> Page:
    page = await c.menu("curriculo.popularBuscaGeral")
    extra: dict[str, str] = {}
    if curso_id is None and codigo is None:
        cursos = P.parse_opcoes_cursos(page.content, "busca:curso")
        if not cursos:
            raise NaoEncontrado("Nenhum curso disponível na consulta de estruturas.")
        curso_id = cursos[0].id
    if curso_id is not None:
        extra = {"busca:checkCurso": "on", "busca:curso": str(curso_id)}
        # o combo de curso dispara submit() pra carregar as matrizes; o Buscar vem depois
        page = await _submit(c, page, "busca", extra)
    if codigo:
        extra |= {"busca:checkCodigo": "on", "busca:codigo": codigo.strip().upper()}
    if somente_ativas:
        extra["busca:somenteAtivas"] = "on"
    return await _submit(c, page, "busca", extra, botao=_botao(page, "busca", "Buscar"))


async def buscar_estruturas(
    c: SigaaClient, curso_id: int | None = None, codigo: str | None = None, somente_ativas: bool = False
) -> list[EstruturaResumo]:
    """Estruturas curriculares de um curso (id de :func:`cursos_com_id`) ou por código."""
    if curso_id is None and not codigo:
        raise ValueError("Informe curso_id ou codigo.")
    res = await _resultado_estruturas(c, curso_id, codigo, somente_ativas)
    return P.parse_busca_estruturas(res.content)


async def _clicar_estrutura(c: SigaaClient, res: Page, acao: str, id_estrutura: int) -> Page:
    """Clica 'resultado:<acao>' com o id pedido. O bean carrega a estrutura pelo ``id`` enviado,
    então qualquer lista de resultados serve de ponto de partida."""
    form = res.form("resultado")
    if form is None:
        raise NaoEncontrado("A busca de estruturas não retornou resultados.")
    link = next((ln for ln in res.links_jsf() if any(k == f"resultado:{acao}" for k in ln.params)), None)
    if link is None:
        raise NavegacaoInvalida(f"Ação '{acao}' não disponível na lista de estruturas.")
    link.params["id"] = str(int(id_estrutura))
    return await c.clicar(res, link)


async def estrutura(c: SigaaClient, id_estrutura: int, curso_id: int | None = None) -> EstruturaDetalhe:
    """Estrutura completa: Relatório (semestres, tipo, natureza) + Detalhar (ids dos componentes, CH extras)."""
    res = await _resultado_estruturas(c, curso_id)
    rel_page = await _clicar_estrutura(c, res, "relatorio", id_estrutura)
    rel = P.parse_estrutura_relatorio(rel_page.content, id_estrutura)
    if rel.codigo is None and not rel.niveis:
        raise NaoEncontrado(f"Estrutura curricular {id_estrutura} não encontrada.")
    try:
        det_page = await _clicar_estrutura(c, res, "detalhar", id_estrutura)
    except NavegacaoInvalida:
        res = await _resultado_estruturas(c, curso_id)
        det_page = await _clicar_estrutura(c, res, "detalhar", id_estrutura)
    det = P.parse_estrutura_detalhar(det_page.content, id_estrutura)
    return P.mesclar_estrutura(rel, det)


async def declaracao_prazo_maximo(c: SigaaClient, id_estrutura: int, curso_id: int | None = None) -> DeclaracaoPrazoMaximo:
    """'Declaração de Prazo Máximo' de integralização (documento com código de verificação)."""
    res = await _resultado_estruturas(c, curso_id)
    page = await _clicar_estrutura(c, res, "declaracaoPrazoMaximo", id_estrutura)
    return P.parse_declaracao_prazo(page.content)


# =================================================================== turmas


async def opcoes_turmas(c: SigaaClient) -> dict[str, list[Opcao]]:
    """Valores aceitos nos filtros da busca de turmas."""
    page = await c.menu("buscaTurmaBean.popularBuscaGeral")
    h = page.content
    return {
        "niveis": P.opcoes_select(h, "form:selectNivelTurma"),
        "unidades": P.opcoes_select(h, "form:selectUnidade"),
        "cursos": P.opcoes_select(h, "form:selectCurso"),
        "situacoes": P.opcoes_select(h, "form:selectSituacaoTurma"),
        "tipos": P.opcoes_select(h, "form:selectTipoTurma"),
        "modalidades": P.opcoes_select(h, "form:selectModalidade"),
        "ordenacoes": P.opcoes_select(h, "form:selectOpcaoOrdenacao"),
    }


async def buscar_turmas(
    c: SigaaClient,
    ano: int | None = None,
    periodo: int | None = None,
    codigo: str | None = None,
    nome: str | None = None,
    unidade: int | None = None,
    docente: str | None = None,
    curso: int | None = None,
    codigo_turma: str | None = None,
    local: str | None = None,
    horario: str | None = None,
    nivel: str | None = None,
    situacao: int | None = None,
    tipo: int | None = None,
    modalidade: int | None = None,
    ordenacao: int | None = None,
) -> list[TurmaOferta]:
    """'Consulta de turmas'. Sem ano/período, o SIGAA usa o período atual (pré-preenchido)."""
    if not any([codigo, nome, unidade, docente, curso, codigo_turma, local, horario]):
        raise ValueError("Informe pelo menos um filtro além de ano/período (codigo, nome, unidade, docente, curso...).")
    page = await c.menu("buscaTurmaBean.popularBuscaGeral")
    e: dict[str, str] = {"form:checkAnoPeriodo": "on"}
    if ano:
        e["form:inputAno"] = str(ano)
    if periodo:
        e["form:inputPeriodo"] = str(periodo)
    pares = [
        (codigo, "form:checkCodigo", "form:inputCodDisciplina"),
        (nome, "form:checkDisciplina", "form:inputNomeDisciplina"),
        (unidade, "form:checkUnidade", "form:selectUnidade"),
        (docente, "form:checkDocente", "form:inputNomeDocente"),
        (curso, "form:checkCurso", "form:selectCurso"),
        (codigo_turma, "form:checkCodigoTurma", "form:inputCodTurma"),
        (local, "form:checkLocal", "form:inputLocal"),
        (horario, "form:checkHorario", "form:inputHorario"),
        (nivel, "form:checkNivel", "form:selectNivelTurma"),
        (situacao, "form:checkSituacao", "form:selectSituacaoTurma"),
        (tipo, "form:checkTipo", "form:selectTipoTurma"),
        (modalidade, "form:checkModalidade", "form:selectModalidade"),
        (ordenacao, "form:checkOrdenacao", "form:selectOpcaoOrdenacao"),
    ]
    for valor, check, campo in pares:
        if valor not in (None, ""):
            e[check] = "on"
            e[campo] = str(valor).strip().upper() if campo == "form:inputCodDisciplina" else str(valor).strip()
    res = await _submit(c, page, "form", e, botao=("form:buttonBuscar", "Buscar"))
    return P.parse_busca_turmas(res.content)


async def turma(c: SigaaClient, id_turma: int) -> TurmaDetalhe:
    """Painel 'Informações da Turma' (GET direto): solicitações, matriculados, vagas reservadas."""
    page = await c.get(f"/sigaa/graduacao/turma/view_painel.jsf?ajaxRequest=true&contarMatriculados=true&id={int(id_turma)}")
    t = P.parse_turma_painel(page.content, id_turma)
    if t.componente_codigo is None and t.capacidade is None:
        raise NaoEncontrado(f"Turma {id_turma} não encontrada.")
    return t


async def processamento_turma(c: SigaaClient, id_turma: int, rematricula: bool = False) -> ProcessamentoTurma:
    """Resultado do processamento da (re)matrícula — SÓ contagens (a tela lista outros alunos)."""
    url = f"/sigaa/relatorioProcessamento?idTurma={int(id_turma)}" + ("&rematricula=true" if rematricula else "")
    page = await c.get(url)
    p = P.parse_processamento(page.content, id_turma, rematricula)
    if p.componente is None and p.total_solicitacoes == 0:
        raise NaoEncontrado(f"Processamento da turma {id_turma} não encontrado.")
    return p


# ================================================================= unidades


async def buscar_unidades(
    c: SigaaClient, nome: str | None = None, tipo: int | None = None, ativa: bool | None = None
) -> list[UnidadeConsulta]:
    """'Buscar Unidade Acadêmica' por nome (trecho) ou tipo (1=Departamento, 4=Centro Acadêmico...)."""
    if not nome and not tipo:
        raise ValueError("Informe nome ou tipo.")
    page = await c.menu("unidade.popularBuscaGeral")
    e: dict[str, str] = {"paramBusca": "nome" if nome else "tipo"}
    if nome:
        e["paramNome"] = nome.strip().upper()
    if tipo:
        e["tipo"] = str(tipo)
    if ativa is not None:
        form = page.form("formBuscaUnidade")
        radio = form.find("input", type="radio", attrs={"onclick": re.compile("setCheckAtivo")}) if form else None
        e["checkAtivo"] = "on"
        if radio is not None:
            e[radio["name"]] = "true" if ativa else "false"
    res = await _submit(c, page, "formBuscaUnidade", e, botao=("btnBuscar", "Buscar"))
    unidades = P.parse_busca_unidades(res.content)
    if ativa is not None:  # com o filtro, o SIGAA esconde a coluna "Ativa"
        for u in unidades:
            u.ativa = ativa if u.ativa is None else u.ativa
    return unidades


async def tipos_unidade(c: SigaaClient) -> list[Opcao]:
    page = await c.menu("unidade.popularBuscaGeral")
    return P.opcoes_select(page.content, "tipo")
