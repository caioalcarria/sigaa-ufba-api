"""Serviços do SIGAA PÚBLICO (sem login): a navegação de cada consulta + o parser.

Todos funcionam com um ``SigaaClient`` ANÔNIMO (sem ``login``)::

    async with SigaaClient() as c:
        cursos = await listar_cursos(c, nivel="G")

Nenhum serviço guarda estado: cada chamada abre a(s) tela(s) que precisa a partir de uma URL de
entrada pública. Onde o SIGAA aceita GET direto (``?id=``/``?siape=``) usamos o GET; onde só há
POST com ViewState (botões ``jsfcljs``), abrimos primeiro a tela que gera o link e "clicamos" nele.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from urllib.parse import urlencode, urljoin

from sigaa.client import JsfLink, Page, SigaaClient, form_fields
from sigaa.errors import NaoEncontrado, NavegacaoInvalida, SigaaError
from sigaa.models.consultas_publico import (
    AcaoExtensao,
    AcaoExtensaoResumo,
    AcervoArtigo,
    AcervoTitulo,
    AcervoTituloDetalhe,
    AcordoMobilidade,
    AquisicaoBiblioteca,
    AreaConcentracaoPos,
    BasePesquisa,
    BolsistaPesquisa,
    Centro,
    CentroCursoAberto,
    CentroResumo,
    ComponenteCurricular,
    ComponenteResumo,
    Curso,
    CursoAberto,
    CursoAbertoTurma,
    CursoProgramaPos,
    CursoResumo,
    Departamento,
    DepartamentoCursoAberto,
    DepartamentoResumo,
    DisciplinaMinistrada,
    Docente,
    DocenteProgramaPos,
    DocenteResumo,
    EstruturaCurricular,
    EstruturaResumo,
    EventoCalendarioCurso,
    InscricaoExtensaoAberta,
    LaboratorioPesquisa,
    LaboratorioPesquisaResumo,
    NoticiaCurso,
    NoticiaProgramaPos,
    NoticiaProgramaPosDetalhe,
    NovasAquisicoesBiblioteca,
    ProcessoSeletivo,
    ProcessoSeletivoProgramaPos,
    ProcessoSeletivoResumo,
    ProducaoCategoria,
    ProgramaComponente,
    ProgramaPos,
    ProgramaPosResumo,
    ProjetoPedagogico,
    ProjetoPesquisa,
    ProjetoPesquisaResumo,
    Responsavel,
    TurmaCurso,
    TurmaPublica,
    UnidadeAcademica,
)
from sigaa.parsers.consultas_publico import (
    TIPOS_RESPONSAVEL,
    docente_existe,
    mensagem_erro_publico,
    parse_acao_extensao,
    parse_acervo_detalhe,
    parse_acervo_resultado,
    parse_acoes_extensao,
    parse_acordos_mobilidade,
    parse_aquisicoes,
    parse_artigos_resultado,
    parse_bases_pesquisa,
    parse_bolsistas_pesquisa,
    parse_busca_componentes,
    parse_busca_docentes,
    parse_calendario_curso,
    parse_centro,
    parse_centro_cursos,
    parse_centro_departamentos,
    parse_centro_programas,
    parse_centros_cursos_abertos,
    parse_componente,
    parse_componentes_departamento,
    parse_curso_aberto,
    parse_curso_detalhe_pos,
    parse_curso_portal,
    parse_cursos_abertos,
    parse_departamento,
    parse_departamentos_cursos_abertos,
    parse_disciplinas_docente,
    parse_docente,
    parse_docentes_departamento,
    parse_estrutura_curricular,
    parse_estruturas_curso,
    parse_inscricoes_extensao,
    parse_laboratorio,
    parse_laboratorios,
    parse_lista_centros,
    parse_lista_cursos,
    parse_lista_departamentos,
    parse_noticias_curso,
    parse_novas_aquisicoes,
    parse_ppp,
    parse_processo_seletivo,
    parse_processos_seletivos,
    parse_producao_docente,
    parse_programa_apresentacao,
    parse_programa_areas,
    parse_programa_componente,
    parse_programa_cursos,
    parse_programa_docentes,
    parse_programa_noticia,
    parse_programa_noticias,
    parse_programa_portal,
    parse_programa_processos_seletivos,
    parse_programas_pos,
    parse_projeto_pesquisa,
    parse_projetos_pesquisa,
    parse_responsaveis,
    parse_turmas_curso,
    parse_turmas_publicas,
    parse_unidades_turmas,
    sem_programa,
    unidade_existe,
)

PUB = "/sigaa/public"
NIVEIS_CURSO = {"G", "S", "L", "T", "N"}
NIVEIS_COMPONENTE = {"I", "U", "M", "T", "N", "F", "G", "L", "R", "S"}
NIVEIS_TURMA = NIVEIS_COMPONENTE | {"E", "D"}
TIPOS_COMPONENTE = {"DISCIPLINA": "2", "ATIVIDADE": "1", "BLOCO": "4", "MODULO": "3", "MÓDULO": "3"}


# --------------------------------------------------------------------------- auxiliares
def _norm(s: str | None) -> str:
    s = (s or "").lower().strip()
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def _link_por_param(page: Page, nome: str, valor: int | str, titulo: str | None = None) -> JsfLink:
    """O commandLink da página cujo parâmetro ``nome`` vale ``valor`` (e cujo título/texto contém ``titulo``)."""
    alvo = str(valor)
    for ln in page.links_jsf():
        if ln.params.get(nome) != alvo:
            continue
        if titulo:
            rot = _norm(ln.texto) + " " + _norm(ln.element.get("title") if ln.element is not None else "")
            if _norm(titulo) not in rot:
                continue
        return ln
    raise NaoEncontrado(f"Não há link com {nome}={valor} nesta tela do SIGAA.")


def _campo_por_rotulo(page: Page, form_id: str, rotulo: str) -> str:
    """``name`` do input de texto na mesma linha do rótulo (o SIGAA gera nomes tipo ``form:j_id_jsp_123_11``)."""
    form = page.form(form_id)
    if form is None:
        raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página.")
    for tr in form.find_all("tr"):
        if _norm(rotulo) in _norm(tr.get_text(" ")):
            el = tr.find("input", attrs={"type": "text"})
            if el is not None and el.get("name"):
                return el["name"]
    for lab in form.find_all(["label", "span"]):
        if _norm(rotulo) in _norm(lab.get_text(" ")):
            el = lab.find_next("input", attrs={"type": "text"})
            if el is not None and el.get("name"):
                return el["name"]
    raise NavegacaoInvalida(f"Campo '{rotulo}' não encontrado no formulário '{form_id}'.")


def _botao(page: Page, form_id: str, valor: str) -> tuple[str, str]:
    form = page.form(form_id)
    if form is None:
        raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página.")
    for el in form.find_all("input", attrs={"type": "submit"}):
        if _norm(el.get("value")) == _norm(valor) and el.get("name"):
            return el["name"], el.get("value", valor)
    raise NavegacaoInvalida(f"Botão '{valor}' não encontrado no formulário '{form_id}'.")


async def _submit(
    c: SigaaClient, page: Page, form_id: str, extra: dict[str, str] | None = None, botao: tuple[str, str] | None = None
) -> Page:
    """Igual a ``c.submit``, mas com o corpo em ISO-8859-1: o SIGAA decodifica o POST como latin-1, e o httpx
    manda UTF-8 — texto acentuado ('computação', 'JOSÉ') chegaria corrompido e a busca voltaria vazia."""
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


def _nivel(n: str, validos: set[str]) -> str:
    n = (n or "").upper().strip()
    if n not in validos:
        raise ValueError(f"Nível inválido: {n!r}. Use um de {sorted(validos)}.")
    return n


# ------------------------------------------------------------------------------- cursos
async def listar_cursos(
    c: SigaaClient,
    nivel: str = "G",
    *,
    nome: str | None = None,
    modalidade: str | None = None,
    unidade: str | None = None,
) -> list[CursoResumo]:
    """Cursos do nível (G graduação, S stricto, L lato, T técnico, N técnico integrado) — GET ``curso/lista.jsf?nivel=``.
    A página já traz todos os cursos do nível; os filtros (trecho do nome/modalidade/unidade) são aplicados aqui."""
    nivel = _nivel(nivel, NIVEIS_CURSO)
    page = await c.get(f"{PUB}/curso/lista.jsf?nivel={nivel}&aba=p-ensino")
    cursos = parse_lista_cursos(page.html, nivel)
    if nome:
        cursos = [x for x in cursos if _norm(nome) in _norm(x.nome)]
    if modalidade:
        cursos = [x for x in cursos if _norm(modalidade) in _norm(x.modalidade)]
    if unidade:
        cursos = [x for x in cursos if _norm(unidade) in _norm(x.unidade)]
    return cursos


async def _abrir_curso_pos(c: SigaaClient, curso_id: int, nivel: str) -> Page:
    lista = await c.get(f"{PUB}/curso/lista.jsf?nivel={nivel}&aba=p-ensino")
    try:
        link = _link_por_param(lista, "id", curso_id)
    except NaoEncontrado:
        raise NaoEncontrado(f"Curso {curso_id} não está na lista pública do nível {nivel}.") from None
    return await c.clicar(lista, link)


async def curso(c: SigaaClient, curso_id: int, nivel: str = "G") -> Curso:
    """Página pública do curso. Graduação: GET ``curso/portal.jsf?id=`` (apresentação, coordenação, títulos,
    calendário resumido). Pós (S): abre a lista do nível e clica no curso ('Detalhes do Curso', com estruturas)."""
    nivel = _nivel(nivel, NIVEIS_CURSO)
    if nivel == "S":
        page = await _abrir_curso_pos(c, curso_id, nivel)
        cur = parse_curso_detalhe_pos(page.html, curso_id, nivel)
        if not cur.nome and not cur.unidade:
            raise NaoEncontrado(f"Curso {curso_id} sem detalhes públicos.")
        return cur
    page = await c.get(f"{PUB}/curso/portal.jsf?id={curso_id}&lc=pt_BR&nivel={nivel}")
    cur = parse_curso_portal(page.html, curso_id, nivel)
    if not cur.nome:
        raise NaoEncontrado(f"Curso {curso_id} não encontrado no portal público.")
    return cur


async def estruturas_curso(c: SigaaClient, curso_id: int, nivel: str = "G") -> list[EstruturaResumo]:
    """Estruturas curriculares do curso: GET ``curso/curriculo.jsf?id=`` (graduação) ou a tela de detalhes (pós)."""
    nivel = _nivel(nivel, NIVEIS_CURSO)
    if nivel == "S":
        return (await curso(c, curso_id, nivel)).estruturas
    page = await c.get(f"{PUB}/curso/curriculo.jsf?lc=pt_BR&id={curso_id}")
    return parse_estruturas_curso(page.html)


async def estrutura_curricular(
    c: SigaaClient, estrutura_id: int, curso_id: int, nivel: str = "G", *, relatorio: bool = False
) -> EstruturaCurricular:
    """Detalhes da estrutura curricular: componentes por nível/semestre, optativas, complementares, CHs e prazos.
    Só existe via POST: abre a lista de currículos do curso e clica em 'Visualizar' (ou 'Relatório')."""
    nivel = _nivel(nivel, NIVEIS_CURSO)
    if nivel == "S":
        origem = await _abrir_curso_pos(c, curso_id, nivel)
    else:
        origem = await c.get(f"{PUB}/curso/curriculo.jsf?lc=pt_BR&id={curso_id}")
    titulo = "Relat" if relatorio else "Visualizar"
    try:
        link = _link_por_param(origem, "id", estrutura_id, titulo)
    except NaoEncontrado:
        raise NaoEncontrado(f"Estrutura {estrutura_id} não pertence ao curso {curso_id}.") from None
    page = await c.clicar(origem, link)
    est = parse_estrutura_curricular(page.html, estrutura_id, curso_id)
    if not est.codigo:
        raise NaoEncontrado(f"Estrutura {estrutura_id} sem detalhes.")
    return est


async def calendario_curso(c: SigaaClient, curso_id: int) -> list[EventoCalendarioCurso]:
    """Calendário do curso (GET ``curso/calendario.jsf?id=``): eventos por ano.período."""
    page = await c.get(f"{PUB}/curso/calendario.jsf?lc=pt_BR&id={curso_id}")
    return parse_calendario_curso(page.html)


async def projeto_pedagogico(c: SigaaClient, curso_id: int) -> ProjetoPedagogico:
    """Aba 'Projeto Pedagógico do Curso' (GET ``curso/ppp.jsf?id=``)."""
    page = await c.get(f"{PUB}/curso/ppp.jsf?lc=pt_BR&id={curso_id}")
    return parse_ppp(page.html, curso_id)


async def noticias_curso(c: SigaaClient, curso_id: int) -> list[NoticiaCurso]:
    """Notícias do portal do curso (GET ``curso/noticias.jsf?id=``)."""
    page = await c.get(f"{PUB}/curso/noticias.jsf?lc=pt_BR&id={curso_id}")
    return parse_noticias_curso(page.html)


async def turmas_curso(
    c: SigaaClient, curso_id: int, ano: int, periodo: int, *, codigo: str | None = None
) -> list[TurmaCurso]:
    """Turmas com vagas reservadas ao curso (aba Ensino › Turmas): GET ``curso/turmas.jsf?id=`` + POST do form 'form'
    com Ano/Período (e Código do componente, opcional). Traz docentes com SIAPE, vagas reservadas e horário."""
    page = await c.get(f"{PUB}/curso/turmas.jsf?lc=pt_BR&id={curso_id}")
    extra = {"form:inputAno": str(ano), "form:inputPeriodo": str(periodo)}
    if codigo:
        extra[_campo_por_rotulo(page, "form", "Código")] = codigo.strip().upper()
    res = await _submit(c, page, "form", extra, botao=("form:buscar", "Buscar"))
    return parse_turmas_curso(res.html)


# --------------------------------------------------------------------------- componentes
async def _buscar_componentes_page(
    c: SigaaClient,
    nivel: str,
    codigo: str | None,
    nome: str | None,
    unidade_id: int | None,
    tipo: str | None,
) -> Page:
    nivel = _nivel(nivel, NIVEIS_COMPONENTE)
    if not any((codigo, nome, unidade_id, tipo)):
        raise ValueError("Informe ao menos um filtro: codigo, nome, unidade_id ou tipo.")
    page = await c.get(f"{PUB}/componentes/busca_componentes.jsf?nivel={nivel}&aba=p-ensino")
    extra: dict[str, str] = {"form:nivel": nivel}
    if tipo:
        t = TIPOS_COMPONENTE.get(tipo.strip().upper(), tipo)
        extra.update({"form:checkTipo": "on", "form:tipo": str(t)})
    if codigo:
        extra.update({"form:checkCodigo": "on", _campo_por_rotulo(page, "form", "Código do Componente"): codigo.strip().upper()})
    if nome:
        extra.update({"form:checkNome": "on", _campo_por_rotulo(page, "form", "Nome do Componente"): nome.strip()})
    if unidade_id:
        extra.update({"form:checkUnidade": "on", "form:unidades": str(unidade_id)})
    return await _submit(c, page, "form", extra, botao=("form:btnBuscarComponentes", "Buscar Componentes"))


async def buscar_componentes(
    c: SigaaClient,
    nivel: str = "G",
    *,
    codigo: str | None = None,
    nome: str | None = None,
    unidade_id: int | None = None,
    tipo: str | None = None,
) -> list[ComponenteResumo]:
    """Busca pública de componentes curriculares (POST de ``componentes/busca_componentes.jsf``).
    Exige ao menos um filtro. ``tipo``: DISCIPLINA, ATIVIDADE, BLOCO, MODULO. ``unidade_id``: id da unidade responsável."""
    page = await _buscar_componentes_page(c, nivel, codigo, nome, unidade_id, tipo)
    return parse_busca_componentes(page.html)


async def componente(c: SigaaClient, componente_id: int) -> ComponenteCurricular:
    """Detalhe do componente pelo id numérico: GET ``/sigaa/link/public/ensino/visualizarComponente/{id}``
    (redireciona para ``componentes/resumo.jsf``). Ementa, CH, pré/co-requisitos, equivalências, currículos."""
    page = await c.get(f"/sigaa/link/public/ensino/visualizarComponente/{componente_id}")
    comp = parse_componente(page.html, componente_id)
    if not comp.codigo:
        raise NaoEncontrado(f"Componente {componente_id} não encontrado.")
    return comp


async def componente_por_codigo(c: SigaaClient, codigo: str, nivel: str = "G") -> ComponenteCurricular:
    """Detalhe pelo CÓDIGO: busca o código e clica em 'Detalhes' (formato mais completo: modalidade e tabela de CHs)."""
    page = await _buscar_componentes_page(c, nivel, codigo, None, None, None)
    achados = [x for x in parse_busca_componentes(page.html) if x.codigo.upper() == codigo.strip().upper()]
    if not achados or achados[0].id is None:
        raise NaoEncontrado(f"Componente {codigo} não encontrado no nível {nivel}.")
    link = _link_por_param(page, "id", achados[0].id, "Detalhes")
    det = await c.clicar(page, link)
    comp = parse_componente(det.html, achados[0].id)
    if not comp.codigo:
        raise NaoEncontrado(f"Componente {codigo} sem detalhes.")
    return comp


async def programa_componente(c: SigaaClient, codigo: str, nivel: str = "G") -> ProgramaComponente:
    """Programa atual do componente (objetivos, conteúdo, metodologia, avaliação, referências).
    Busca o código e clica em 'Programa Atual do Componente'. ``NaoEncontrado`` quando o SIGAA diz que não há
    programa cadastrado (é o caso da maioria dos componentes de graduação da UFBA hoje)."""
    page = await _buscar_componentes_page(c, nivel, codigo, None, None, None)
    achados = [x for x in parse_busca_componentes(page.html) if x.codigo.upper() == codigo.strip().upper()]
    if not achados or achados[0].id is None:
        raise NaoEncontrado(f"Componente {codigo} não encontrado no nível {nivel}.")
    try:
        link = _link_por_param(page, "idComponente", achados[0].id, "Programa")
    except NaoEncontrado:
        raise NaoEncontrado(f"O componente {codigo} não tem programa público.") from None
    res = await c.clicar(page, link)
    if sem_programa(res.html):
        raise NaoEncontrado(f"O componente {codigo} não possui um programa cadastrado.")
    prog = parse_programa_componente(res.html, achados[0].id)
    if prog is None:
        raise NaoEncontrado(f"Programa do componente {codigo} não pôde ser lido.")
    prog.codigo = prog.codigo or achados[0].codigo
    prog.nome = prog.nome or achados[0].nome
    return prog


# ------------------------------------------------------------------------------- turmas
async def unidades_academicas(c: SigaaClient) -> list[UnidadeAcademica]:
    """Unidades que ofertam turmas (o filtro 'Unidade' da consulta pública de turmas). O id é o mesmo dos
    departamentos/programas e do filtro de unidade da busca de componentes."""
    page = await c.get(f"{PUB}/turmas/listar.jsf?aba=p-ensino")
    return parse_unidades_turmas(page.html)


async def buscar_turmas(
    c: SigaaClient,
    ano: int,
    periodo: int,
    unidade_id: int,
    nivel: str = "G",
    *,
    componente: str | None = None,
) -> list[TurmaPublica]:
    """Consulta pública de turmas (``turmas/listar.jsf``, POST do form 'formTurma'): turmas da unidade no
    ano.período, com docentes (e a CH de cada um) e local/horários. ``componente`` filtra por código (prefixo)
    ou trecho do nome — o SIGAA não tem esse filtro, é aplicado aqui."""
    nivel = _nivel(nivel, NIVEIS_TURMA)
    page = await c.get(f"{PUB}/turmas/listar.jsf?aba=p-ensino")
    extra = {
        "formTurma:inputNivel": nivel,
        "formTurma:inputDepto": str(unidade_id),
        "formTurma:inputAno": str(ano),
        "formTurma:inputPeriodo": str(periodo),
    }
    res = await _submit(c, page, "formTurma", extra, botao=_botao(page, "formTurma", "Buscar"))
    turmas = parse_turmas_publicas(res.html)
    if componente:
        alvo = _norm(componente)
        turmas = [t for t in turmas if _norm(t.codigo_componente).startswith(alvo) or alvo in _norm(t.nome_componente)]
    return turmas


# ----------------------------------------------------------------------------- docentes
async def buscar_docentes(
    c: SigaaClient, *, nome: str | None = None, departamento_id: int | None = None
) -> list[DocenteResumo]:
    """Busca de docentes (``docente/busca_docentes.jsf``, POST do form 'form'): por nome e/ou departamento de lotação.
    O mesmo docente pode aparecer uma vez por unidade (centro e departamento)."""
    if not nome and not departamento_id:
        raise ValueError("Informe nome e/ou departamento_id.")
    page = await c.get(f"{PUB}/docente/busca_docentes.jsf?aba=p-academico")
    extra = {"form:nome": (nome or "").strip(), "form:departamento": str(departamento_id or 0)}
    res = await _submit(c, page, "form", extra, botao=("form:buscar", "Buscar"))
    return parse_busca_docentes(res.html)


async def _pagina_docente(c: SigaaClient, aba: str, siape: int) -> Page:
    page = await c.get(f"{PUB}/docente/{aba}.jsf?siape={siape}")
    if not docente_existe(page.html):
        raise NaoEncontrado(f"Docente SIAPE {siape} não tem página pública.")
    return page


async def docente(c: SigaaClient, siape: int) -> Docente:
    """Perfil público do docente (GET ``docente/portal.jsf?siape=``): formação, áreas de interesse, Lattes, contatos."""
    page = await _pagina_docente(c, "portal", siape)
    return parse_docente(page.html, siape)


async def producao_docente(c: SigaaClient, siape: int) -> list[ProducaoCategoria]:
    """Produção intelectual (GET ``docente/producao.jsf?siape=``): categorias com itens (TCCs, orientações, artigos...)."""
    page = await _pagina_docente(c, "producao", siape)
    return parse_producao_docente(page.html)


async def disciplinas_docente(c: SigaaClient, siape: int) -> list[DisciplinaMinistrada]:
    """Disciplinas ministradas (GET ``docente/disciplinas.jsf?siape=``): todas as turmas por período, com horário."""
    page = await _pagina_docente(c, "disciplinas", siape)
    return parse_disciplinas_docente(page.html)


# ---------------------------------------------------------------- centros e departamentos
async def listar_centros(c: SigaaClient) -> list[CentroResumo]:
    """Centros/unidades especializadas com seus departamentos (GET ``centro/lista.jsf``)."""
    page = await c.get(f"{PUB}/centro/lista.jsf?aba=p-academico")
    return parse_lista_centros(page.html)


async def centro(c: SigaaClient, centro_id: int) -> Centro:
    """Portal do centro: GET ``centro/portal.jsf?id=`` + abas ``lista_departamentos``, ``lista_cursos`` e
    ``lista_programas`` (4 GETs). Id inexistente faz o SIGAA mostrar a home pública → ``NaoEncontrado``."""
    page = await c.get(f"{PUB}/centro/portal.jsf?lc=pt_BR&id={centro_id}")
    if not unidade_existe(page.html):
        raise NaoEncontrado(f"Centro {centro_id} não encontrado.")
    cen = parse_centro(page.html, centro_id)
    deps = await c.get(f"{PUB}/centro/lista_departamentos.jsf?lc=pt_BR&id={centro_id}")
    cen.departamentos = parse_centro_departamentos(deps.html)
    cur = await c.get(f"{PUB}/centro/lista_cursos.jsf?lc=pt_BR&id={centro_id}")
    cen.cursos = parse_centro_cursos(cur.html)
    pro = await c.get(f"{PUB}/centro/lista_programas.jsf?lc=pt_BR&id={centro_id}")
    cen.programas = parse_centro_programas(pro.html)
    return cen


async def listar_departamentos(c: SigaaClient, *, centro_id: int | None = None) -> list[DepartamentoResumo]:
    """Departamentos (``departamento/lista.jsf``, POST do form 'form' com o centro — 0 = todos)."""
    page = await c.get(f"{PUB}/departamento/lista.jsf?aba=p-academico")
    res = await _submit(c, page, "form", {"form:programas": str(centro_id or 0)}, botao=("form:buscar", "Buscar"))
    return parse_lista_departamentos(res.html)


async def departamento(c: SigaaClient, departamento_id: int) -> Departamento:
    """Portal do departamento (GET ``departamento/portal.jsf?id=``): chefia (com SIAPE), apresentação, notícias."""
    page = await c.get(f"{PUB}/departamento/portal.jsf?id={departamento_id}")
    if not unidade_existe(page.html):
        raise NaoEncontrado(f"Departamento {departamento_id} não encontrado.")
    return parse_departamento(page.html, departamento_id)


async def docentes_departamento(c: SigaaClient, departamento_id: int) -> list[DocenteResumo]:
    """Corpo docente do departamento (GET ``departamento/professores.jsf?id=``): titulação, categoria, Lattes, SIAPE."""
    page = await c.get(f"{PUB}/departamento/professores.jsf?id={departamento_id}")
    if not unidade_existe(page.html):
        raise NaoEncontrado(f"Departamento {departamento_id} não encontrado.")
    return parse_docentes_departamento(page.html)


async def componentes_departamento(c: SigaaClient, departamento_id: int) -> list[ComponenteResumo]:
    """Componentes curriculares do departamento (GET ``departamento/componentes.jsf?id=``), com o id de cada um."""
    page = await c.get(f"{PUB}/departamento/componentes.jsf?id={departamento_id}")
    if not unidade_existe(page.html):
        raise NaoEncontrado(f"Departamento {departamento_id} não encontrado.")
    return parse_componentes_departamento(page.html)


# --------------------------------------------------------------------------- responsáveis
async def responsaveis(c: SigaaClient, tipo: str = "chefes") -> list[Responsavel]:
    """Chefes de departamento, coordenadores (graduação/pós) ou diretores de centro (``academico/busca_responsavel.jsf``).
    ``tipo``: chefes | coordenadores_graduacao | coordenadores_pos | diretores."""
    if tipo not in TIPOS_RESPONSAVEL:
        raise ValueError(f"tipo inválido: {tipo!r}. Use um de {sorted(TIPOS_RESPONSAVEL)}.")
    page = await c.get(f"{PUB}/academico/busca_responsavel.jsf?aba=p-academico")
    res = await _submit(c, page, "form", {"form:tipoConsulta": TIPOS_RESPONSAVEL[tipo]}, botao=("form:btnBuscar", "Buscar"))
    return parse_responsaveis(res.html, tipo)


# ====================================================================================================
# BIBLIOTECA, PROCESSOS SELETIVOS, DIPLOMAS, MOBILIDADE E PROGRAMAS DE PÓS  (frente 'extras1')
# ====================================================================================================
BIB = "/sigaa/public/biblioteca"
NIVEIS_PROCESSO = {"S": "Stricto sensu", "L": "Lato sensu", "T": "Técnico", "I": "Infantil/Fundamental", "F": "Formação complementar"}
_NADA = re.compile(r"Não foram encontrad|Nenhum[^.]*encontrad|Nenhum (resultado|registro)|Não há", re.I)


def _ex1s_sem_acento(v) -> str:
    """O SIGAA lê o corpo do POST como ISO-8859-1 e o SigaaClient (httpx) manda UTF-8: texto acentuado
    chega corrompido e a busca volta vazia. As buscas públicas ignoram acento, então mandamos sem."""
    return unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode()


# ------------------------------------------------------------------ helpers
def _ex1s_campo_da_linha(page: Page, form_id: str, ancora: str, tipo: str = "text", n: int = 0) -> str | None:
    """Nome do n-ésimo <input type=tipo>/<select> na mesma <tr> do elemento cujo name termina em ``ancora``
    (os ids j_id_jsp_* mudam a cada deploy; o checkbox/rótulo é estável)."""
    form = page.form(form_id)
    if form is None:
        return None
    el = form.find(attrs={"name": re.compile(re.escape(ancora) + "$")})
    tr = el.find_parent("tr") if el is not None else None
    if tr is None:
        return None
    alvos = tr.find_all("select") if tipo == "select" else tr.find_all("input", type=tipo)
    return alvos[n]["name"] if len(alvos) > n else None


def _ex1s_campo_por_rotulo(page: Page, form_id: str, rotulo: str, tag: str = "select") -> str | None:
    form = page.form(form_id)
    if form is None:
        return None
    for tr in form.find_all("tr"):
        if tr.find("tr"):
            continue
        if rotulo.lower() in tr.get_text(" ", strip=True).lower():
            el = tr.find(tag)
            if el is not None and el.get("name"):
                return el["name"]
    return None


def _ex1s_validar(page: Page) -> None:
    """Mensagem de validação do formulário (ex.: 'No mínimo 3 caracteres') vira erro; 'nada encontrado' não."""
    msg = mensagem_erro_publico(page.html)
    if msg and not _NADA.search(msg):
        raise SigaaError(f"O SIGAA recusou a busca: {msg}")


async def _ex1s_proxima(c: SigaaClient, page: Page) -> Page | None:
    link = next((ln for ln in page.links_jsf() if "botaoProximaPagina" in ln.onclick), None)
    return await c.clicar(page, link) if link else None


async def _ex1s_post_form(c: SigaaClient, page: Page, form_id: str, extra: dict[str, str], tirar: tuple[str, ...] = ()) -> Page:
    """Como c.submit, mas permite TIRAR campos (select múltiplo vazio não pode ir com valor '')."""
    form = page.form(form_id)
    if form is None:
        raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página.")
    data = {k: v for k, v in form_fields(form).items() if k not in tirar}
    data.update(extra)
    return await c.post(urljoin(page.url, form.get("action") or page.url), data)


# ------------------------------------------------------------------ biblioteca
async def _ex1s_pesquisar_acervo(
    c: SigaaClient,
    *,
    titulo: str | None,
    autor: str | None,
    assunto: str | None,
    editora: str | None,
    local_publicacao: str | None,
    ano_inicio: int | None,
    ano_fim: int | None,
    tipo_material: int | None,
    colecao: int | None,
    ordenacao: int,
    registros_por_pagina: int,
) -> Page:
    page = await c.get(f"{BIB}/buscaPublicaAcervo.jsf?aba=p-biblioteca")
    f = "formBuscaPublica"
    extra: dict[str, str] = {}

    def texto(check: str, valor, n: int = 0):
        nome = _ex1s_campo_da_linha(page, f, check, "text", n)
        if nome is None:
            raise NavegacaoInvalida(f"Campo '{check}' não encontrado na busca do acervo.")
        extra[f"{f}:{check}"] = "true"
        extra[nome] = _ex1s_sem_acento(valor)

    if titulo:
        texto("checkTitulo", titulo)
    if autor:
        texto("checkAutor", autor)
    if assunto:
        texto("checkAssunto", assunto)
    if local_publicacao:
        texto("checkLocalPublicao", local_publicacao)
    if editora:
        texto("checkEditora", editora)
    if ano_inicio or ano_fim:
        texto("checkAnoPublicacao", ano_inicio or "", 0)
        texto("checkAnoPublicacao", ano_fim or "", 1)
    for check, valor in (("checkTipoMaterial", tipo_material), ("checkColecao", colecao)):
        if valor:
            nome = _ex1s_campo_da_linha(page, f, check, "select")
            if nome:
                extra[f"{f}:{check}"] = "true"
                extra[nome] = str(valor)
    if not extra:
        raise SigaaError("Informe ao menos um filtro (título, autor, assunto, editora, local, ano, tipo ou coleção).")
    for rot, valor in (("Ordenação", ordenacao), ("Registros por página", registros_por_pagina)):
        nome = _ex1s_campo_por_rotulo(page, f, rot)
        if nome:
            extra[nome] = str(valor)
    res = await c.submit(page, f, extra, botao=(f"{f}:botaoPesquisarPublicaMulti", "Pesquisar"))
    _ex1s_validar(res)
    return res


async def buscar_acervo(
    c: SigaaClient,
    *,
    titulo: str | None = None,
    autor: str | None = None,
    assunto: str | None = None,
    editora: str | None = None,
    local_publicacao: str | None = None,
    ano_inicio: int | None = None,
    ano_fim: int | None = None,
    tipo_material: int | None = None,
    colecao: int | None = None,
    ordenacao: int = 1,
    registros_por_pagina: int = 100,
    max_paginas: int = 5,
) -> list[AcervoTitulo]:
    """Busca multi-campo no acervo das bibliotecas (cada texto com no mínimo 3 caracteres)."""
    page = await _ex1s_pesquisar_acervo(
        c, titulo=titulo, autor=autor, assunto=assunto, editora=editora, local_publicacao=local_publicacao,
        ano_inicio=ano_inicio, ano_fim=ano_fim, tipo_material=tipo_material, colecao=colecao,
        ordenacao=ordenacao, registros_por_pagina=registros_por_pagina,
    )
    out = parse_acervo_resultado(page.html)
    for _ in range(max_paginas - 1):
        nxt = await _ex1s_proxima(c, page)
        if nxt is None:
            break
        page = nxt
        out += parse_acervo_resultado(page.html)
    return out


async def titulo_acervo(
    c: SigaaClient,
    titulo_id: int,
    *,
    titulo: str | None = None,
    autor: str | None = None,
    assunto: str | None = None,
    editora: str | None = None,
    ano_inicio: int | None = None,
    ano_fim: int | None = None,
    max_paginas: int = 5,
) -> AcervoTituloDetalhe:
    """Detalhe ('Materiais de um Título': exemplares, biblioteca, situação, localização).
    O SIGAA só abre o detalhe a partir de um resultado de busca: refaz a busca com os filtros dados
    (os mesmos que acharam o título) e clica no título ``titulo_id``."""
    page = await _ex1s_pesquisar_acervo(
        c, titulo=titulo, autor=autor, assunto=assunto, editora=editora, local_publicacao=None,
        ano_inicio=ano_inicio, ano_fim=ano_fim, tipo_material=None, colecao=None, ordenacao=1, registros_por_pagina=100,
    )
    for _ in range(max_paginas):
        link = next((ln for ln in page.links_jsf() if f"'idTitulo':'{titulo_id}'" in ln.onclick), None)
        if link is not None:
            det = parse_acervo_detalhe((await c.clicar(page, link)).html)
            if det.id is None:
                det.id = titulo_id
            return det
        page = await _ex1s_proxima(c, page)
        if page is None:
            break
    raise NaoEncontrado(f"Título {titulo_id} não apareceu na busca informada.")


async def buscar_artigos(
    c: SigaaClient,
    *,
    titulo: str | None = None,
    autor: str | None = None,
    palavras_chave: str | None = None,
    ordenacao: int = 1,
    registros_por_pagina: int = 100,
    max_paginas: int = 5,
) -> list[AcervoArtigo]:
    """Busca pública de artigos de periódicos (buscaPublicaAcervoArtigos.jsf)."""
    page = await c.get(f"{BIB}/buscaPublicaAcervoArtigos.jsf?aba=p-biblioteca")
    f = "formBuscaPublica"
    extra: dict[str, str] = {}
    for check, campo, valor in (
        ("checkTitulo", "inputTextTituloArtigo", titulo),
        ("checkAutor", "inputTextAutorArtigo", autor),
        ("checkAssunto", "inputTextPalavrasChaves", palavras_chave),
    ):
        if valor:
            extra[f"{f}:{check}"] = "true"
            extra[f"{f}:{campo}"] = _ex1s_sem_acento(valor)
    if not extra:
        raise SigaaError("Informe título, autor ou palavras-chave.")
    for rot, valor in (("Ordenação", ordenacao), ("Registros por página", registros_por_pagina)):
        nome = _ex1s_campo_por_rotulo(page, f, rot)
        if nome:
            extra[nome] = str(valor)
    page = await c.submit(page, f, extra, botao=(f"{f}:botaoPesquisar", "Pesquisar"))
    _ex1s_validar(page)
    out = parse_artigos_resultado(page.html)
    for _ in range(max_paginas - 1):
        nxt = await _ex1s_proxima(c, page)
        if nxt is None:
            break
        page = nxt
        out += parse_artigos_resultado(page.html)
    return out


async def buscar_aquisicoes(
    c: SigaaClient, *, titulo: str | None = None, autor: str | None = None, ano: int | None = None
) -> list[AquisicaoBiblioteca]:
    """Consulta pública de aquisições (compras de livros) por título, autor e/ou ano da aquisição."""
    page = await c.get(f"{BIB}/buscaPublicaAquisicoes.jsf?aba=p-biblioteca")
    form = next((fm for fm in page.soup.find_all("form") if fm.find("input", attrs={"value": "Pesquisar"})), None)
    if form is None:
        raise NavegacaoInvalida("Formulário de aquisições não encontrado.")
    fid = form.get("id")
    extra: dict[str, str] = {}
    for rot, valor in (("Título", titulo), ("Autor", autor), ("Ano da Aquisição", ano)):
        if valor:
            nome = _ex1s_campo_por_rotulo(page, fid, rot, "input")
            if nome:
                extra[nome] = _ex1s_sem_acento(valor)
    botao = form.find("input", attrs={"value": "Pesquisar"})
    page = await c.submit(page, fid, extra, botao=(botao["name"], "Pesquisar"))
    _ex1s_validar(page)
    return parse_aquisicoes(page.html)


async def novas_aquisicoes(
    c: SigaaClient, *, desde: date | None = None, area_cnpq: int | None = None
) -> NovasAquisicoesBiblioteca:
    """Informativo de novas aquisições (todas as bibliotecas). ``desde``: no máximo 6 meses atrás
    (padrão do SIGAA: 1 mês)."""
    page = await c.get(f"{BIB}/buscaPublicaNovasAquisicoes.jsf?aba=p-biblioteca")
    extra = {"form:cmdButtonPesquisar": "Pesquisar"}
    if desde:
        extra["form:inicio"] = desde.strftime("%d/%m/%Y")
    if area_cnpq:
        extra["form:somAreaCNPQ"] = str(area_cnpq)
    page = await _ex1s_post_form(c, page, "form", extra, tirar=("form:smlbxBibliotecas",))
    _ex1s_validar(page)
    return parse_novas_aquisicoes(page.html)


# ---------------------------------------------------------- processos seletivos
def _ex1s_nivel(nivel: str) -> str:
    nivel = (nivel or "").upper()
    if nivel not in NIVEIS_PROCESSO:
        raise SigaaError(f"Nível inválido '{nivel}'. Use um de: {', '.join(NIVEIS_PROCESSO)}.")
    return nivel


async def listar_processos_seletivos(c: SigaaClient, *, nivel: str = "S") -> list[ProcessoSeletivoResumo]:
    """Últimos processos seletivos de um nível (S=stricto, L=lato, T=técnico, I=infantil/fundamental,
    F=formação complementar). GET direto: processo_seletivo/lista.jsf?nivel=X."""
    page = await c.get(f"/sigaa/public/processo_seletivo/lista.jsf?nivel={_ex1s_nivel(nivel)}")
    return parse_processos_seletivos(page.html)


async def processo_seletivo(
    c: SigaaClient, processo_id: int, *, nivel: str = "S", programa_id: int | None = None
) -> ProcessoSeletivo:
    """Detalhe público de um processo seletivo (edital, período, vagas, etapas, comissão, documentos).
    Só abre por POST a partir de uma lista: a pública do ``nivel`` ou, se ``programa_id`` vier, a do programa."""
    alvo = f"'id':'{processo_id}'"
    if programa_id:
        page = await c.get(f"/sigaa/public/programa/processo_seletivo.jsf?lc=pt_BR&id={programa_id}")
        links = [ln for ln in page.links_jsf() if alvo in ln.onclick]
    else:
        page = await c.get(f"/sigaa/public/processo_seletivo/lista.jsf?nivel={_ex1s_nivel(nivel)}")
        links = [ln for ln in page.links_jsf() if alvo in ln.onclick]
        # a seta "Visualizar dados do processo seletivo" (o link do edital no agrupador é outro botão)
        links.sort(key=lambda ln: 0 if "Visualizar" in (ln.element.get("title") or "") else 1)
    if not links:
        raise NaoEncontrado(f"Processo seletivo {processo_id} não está na lista consultada.")
    det = parse_processo_seletivo((await c.clicar(page, links[0])).html)
    if det.id is None:
        det.id = processo_id
    return det


# ------------------------------------------------------- acordos de mobilidade
async def listar_acordos_mobilidade(
    c: SigaaClient,
    *,
    pais: int | None = None,
    instituicao: str | None = None,
    sigla: str | None = None,
    ano_assinatura: int | None = None,
    status: int | None = None,
) -> list[AcordoMobilidade]:
    """Acordos de cooperação/mobilidade (acordos_mobilidade.jsf). ``pais`` = id do select de países;
    ``status``: 1=Ativo, 2=Aguardando Renovação, 3=Encerrado, 4=Negado, 5=Nova Solicitação."""
    page = await c.get("/sigaa/public/acordo_mobilidade/acordos_mobilidade.jsf?aba=p-relacoes-internacionais")
    f = "formulario"
    extra: dict[str, str] = {}
    if pais:
        extra.update({f"{f}:filtroPais": "on", f"{f}:pais": str(pais)})
    if status is not None:
        extra.update({f"{f}:filtroStatus": "on", f"{f}:status": str(status)})
    for check, valor in (("filtroInstituicao", instituicao), ("filtroSigla", sigla), ("filtroAnoAssinatura", ano_assinatura)):
        if valor:
            nome = _ex1s_campo_da_linha(page, f, check, "text")
            if nome:
                extra[f"{f}:{check}"] = "on"
                extra[nome] = _ex1s_sem_acento(valor)
    page = await c.submit(page, f, extra, botao=(f"{f}:btnBusca", "Buscar"))
    _ex1s_validar(page)
    return parse_acordos_mobilidade(page.html)


# --------------------------------------------------------- programas de pós
PROG = "/sigaa/public/programa"


async def listar_programas_pos(c: SigaaClient, *, nome: str | None = None, id_centro: int | None = None) -> list[ProgramaPosResumo]:
    """Programas de pós-graduação (programa/lista.jsf + 'Buscar'), filtráveis por palavra e centro."""
    page = await c.get(f"{PROG}/lista.jsf?aba=p-stricto")
    extra = {"form:nomePrograma": _ex1s_sem_acento(nome or ""), "form:programas": str(id_centro or 0)}
    page = await c.submit(page, "form", extra, botao=("form:buscar", "Buscar"))
    _ex1s_validar(page)
    return parse_programas_pos(page.html)


async def _ex1s_prog(c: SigaaClient, pagina: str, programa_id: int, extra_qs: str = "") -> Page:
    page = await c.get(f"{PROG}/{pagina}.jsf?lc=pt_BR&id={int(programa_id)}{extra_qs}")
    if page.soup.find(id="nomes") is None and page.soup.find(id="conteudo") is None:
        raise NaoEncontrado(f"Programa {programa_id} não encontrado.")
    return page


async def programa_pos(c: SigaaClient, programa_id: int) -> ProgramaPos:
    """Página pública do programa (contato, últimas notícias, processos em destaque) + apresentação e coordenação."""
    portal = parse_programa_portal((await _ex1s_prog(c, "portal", programa_id)).html)
    if not portal.nome:
        raise NaoEncontrado(f"Programa {programa_id} não encontrado.")
    portal.id = portal.id or programa_id
    ap = parse_programa_apresentacao((await _ex1s_prog(c, "apresentacao", programa_id)).html)
    portal.apresentacao, portal.endereco_alternativo, portal.coordenacao = ap.texto, ap.endereco_alternativo, ap.coordenacao
    return portal


async def programa_pos_areas(c: SigaaClient, programa_id: int) -> list[AreaConcentracaoPos]:
    """Áreas de concentração e linhas de pesquisa do programa (por nível)."""
    return parse_programa_areas((await _ex1s_prog(c, "areas", programa_id)).html)


async def programa_pos_cursos(c: SigaaClient, programa_id: int) -> list[CursoProgramaPos]:
    """Cursos (mestrado/doutorado...) do programa."""
    return parse_programa_cursos((await _ex1s_prog(c, "cursos", programa_id)).html)


async def programa_pos_docentes(c: SigaaClient, programa_id: int) -> list[DocenteProgramaPos]:
    """Corpo docente do programa (por grupo/área)."""
    return parse_programa_docentes((await _ex1s_prog(c, "equipe", programa_id)).html)


async def programa_pos_processos_seletivos(c: SigaaClient, programa_id: int) -> list[ProcessoSeletivoProgramaPos]:
    """Processos seletivos listados na página do programa."""
    return parse_programa_processos_seletivos((await _ex1s_prog(c, "processo_seletivo", programa_id)).html)


async def programa_pos_noticias(c: SigaaClient, programa_id: int) -> list[NoticiaProgramaPos]:
    """Todas as notícias do programa."""
    return parse_programa_noticias((await _ex1s_prog(c, "noticias", programa_id)).html)


async def programa_pos_noticia(c: SigaaClient, programa_id: int, noticia_id: int) -> NoticiaProgramaPosDetalhe:
    """Texto de uma notícia do programa."""
    det = parse_programa_noticia((await _ex1s_prog(c, "noticias_desc", programa_id, f"&noticia={int(noticia_id)}")).html)
    if not det.titulo and not det.texto:
        raise NaoEncontrado(f"Notícia {noticia_id} não encontrada no programa {programa_id}.")
    det.id, det.id_programa = noticia_id, programa_id
    return det


# ====================================================================================================
# PESQUISA, EXTENSÃO E CURSOS ABERTOS  (frente 'extras2')
# ====================================================================================================
URL_PROJETOS = "/sigaa/public/pesquisa/consulta_projetos.jsf"
URL_BASES = "/sigaa/public/pesquisa/consulta_bases.jsf"
URL_BOLSISTAS = "/sigaa/public/pesquisa/consulta_bolsistas.jsf"
URL_LABORATORIOS = "/sigaa/public/pesquisa/consulta_laboratorios.jsf"
URL_EXTENSAO = "/sigaa/public/extensao/consulta_extensao.jsf"
URL_EXTENSAO_LINK = "/sigaa/link/public/extensao/visualizacaoAcaoExtensao/{id}"
URL_INSCRICOES = "/sigaa/public/extensao/paginaListaPeriodosInscricoesAtividadesPublico.jsf"
URL_CURSOS_ABERTOS = "/sigaa/public/cursosabertos.jsf"

_EX2_PARAMS = re.compile(r"'([^']+)'\s*:\s*'([^']*)'")


# ------------------------------------------------------------------ infra
async def _ex2_enviar(
    c: SigaaClient,
    page: Page,
    form_id: str,
    extra: dict[str, str] | None = None,
    botao: tuple[str, str] | None = None,
    sem: tuple[str, ...] = (),
) -> Page:
    """Submete ``form_id`` de ``page`` (ViewState incluso) codificando o corpo em ISO-8859-1."""
    form = page.form(form_id)
    if form is None:
        raise NavegacaoInvalida(f"Formulário '{form_id}' não está na página {page.url}.")
    data = form_fields(form)
    for k in sem:
        data.pop(k, None)
    if botao:
        data[botao[0]] = botao[1]
    if extra:
        data.update({k: str(v) for k, v in extra.items()})
    corpo = urlencode(list(data.items()), encoding="iso-8859-1", errors="xmlcharrefreplace").encode("ascii")
    action = urljoin(page.url, form.get("action") or page.url)
    return await c.post(
        action,
        {},
        content=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"},
    )


def _ex2_filtros(pares: list[tuple[str, str, object]]) -> dict[str, str]:
    """[(checkbox, campo, valor)] → campos do form, marcando o checkbox de cada filtro informado."""
    out: dict[str, str] = {}
    for check, campo, valor in pares:
        if valor is None or valor == "":
            continue
        if isinstance(valor, bool):
            valor = "true" if valor else "false"
        if check:
            out[check] = "on"
        out[campo] = str(valor)
    return out


def _ex2_link(page: Page, param: str, valor: int):
    """O h:commandLink da página cujo parâmetro ``param`` vale ``valor``."""
    for ln in page.links_jsf():
        if ln.params.get(param) == str(valor):
            return ln
    return None


async def _ex2_clicar(c: SigaaClient, page: Page, link) -> Page:
    """Clique num commandLink. Igual a ``c.clicar``, mas em latin-1: o form do link pode ser o
    próprio form de busca (laboratórios), com o texto acentuado digitado."""
    return await _ex2_enviar(c, page, link.form_id, link.params)


# ------------------------------------------------------------------ pesquisa
async def _buscar_projetos_page(c: SigaaClient, **f) -> Page:
    F = "formConsulta"
    page = await c.get(URL_PROJETOS)
    extra = _ex2_filtros([
        (f"{F}:checkTitulo", f"{F}:titulo", f.get("titulo")),
        (f"{F}:checkObjetivos", f"{F}:objetivos", f.get("objetivos")),
        (f"{F}:checkPesquisador", f"{F}:nomePesquisador", f.get("pesquisador")),
        (f"{F}:checkAno", f"{F}:ano", f.get("ano")),
        (f"{F}:checkCentro", f"{F}:centro", f.get("centro_id")),
        (f"{F}:checkUnidade", f"{F}:unidade", f.get("departamento_id")),
        (f"{F}:checkArea", f"{F}:area", f.get("area_id")),
        (f"{F}:checkAgencia", f"{F}:agencia", f.get("agencia_id")),
    ])
    return await _ex2_enviar(c, page, F, extra, botao=(f"{F}:buscar", "Buscar"))


async def buscar_projetos_pesquisa(
    c: SigaaClient,
    *,
    titulo: str | None = None,
    objetivos: str | None = None,
    pesquisador: str | None = None,
    ano: int | None = None,
    centro_id: int | None = None,
    departamento_id: int | None = None,
    area_id: int | None = None,
    agencia_id: int | None = None,
) -> list[ProjetoPesquisaResumo]:
    """'Quem pesquisa o que': projetos de pesquisa. A lista vem inteira (sem paginação)."""
    page = await _buscar_projetos_page(
        c, titulo=titulo, objetivos=objetivos, pesquisador=pesquisador, ano=ano,
        centro_id=centro_id, departamento_id=departamento_id, area_id=area_id, agencia_id=agencia_id,
    )
    return parse_projetos_pesquisa(page.html)


async def obter_projeto_pesquisa(
    c: SigaaClient,
    projeto_id: int,
    *,
    titulo: str | None = None,
    pesquisador: str | None = None,
    ano: int | None = None,
    centro_id: int | None = None,
) -> ProjetoPesquisa:
    """Detalhe de um projeto. O SIGAA só abre o detalhe a partir da lista: informe filtros que
    tragam o projeto (ex.: o ``ano`` e o ``titulo`` que vieram na busca)."""
    page = await _buscar_projetos_page(c, titulo=titulo, pesquisador=pesquisador, ano=ano, centro_id=centro_id)
    link = _ex2_link(page, "id", projeto_id)
    if link is None:
        raise NaoEncontrado(f"Projeto de pesquisa {projeto_id} não está na lista com esses filtros.")
    det = await _ex2_clicar(c, page, link)
    proj = parse_projeto_pesquisa(det.html)
    if not proj.titulo and not proj.codigo:
        raise NaoEncontrado(f"Projeto de pesquisa {projeto_id} não abriu.")
    return proj.model_copy(update={"id": projeto_id})


async def buscar_bases_pesquisa(
    c: SigaaClient, *, nome: str | None = None, coordenador: str | None = None
) -> list[BasePesquisa]:
    """Bases (grupos) de pesquisa por nome e/ou coordenador."""
    F = "formConsulta"
    page = await c.get(URL_BASES)
    extra = _ex2_filtros([
        (f"{F}:checkNome", f"{F}:nome", nome),
        (f"{F}:checkCoordenador", f"{F}:nomeCoordenador", coordenador),
    ])
    res = await _ex2_enviar(c, page, F, extra, botao=(f"{F}:buscar", "Buscar"))
    return parse_bases_pesquisa(res.html)


async def buscar_bolsistas_pesquisa(
    c: SigaaClient,
    *,
    discente: str | None = None,
    orientador: str | None = None,
    modalidade_id: int | None = None,
    centro_id: int | None = None,
    curso_id: int | None = None,
) -> list[BolsistaPesquisa]:
    """Bolsistas de iniciação científica.

    Na UFBA (v4.13.8) a busca cai numa página de erro de configuração ("O parâmetro de código
    ... deveria ser uma lista de números") — aí levantamos ``SigaaError``."""
    F = "formConsulta"
    page = await c.get(URL_BOLSISTAS)
    extra = _ex2_filtros([
        (f"{F}:checkAluno", f"{F}:nomeDiscente", discente),
        (f"{F}:checkOrientador", f"{F}:nomeOrientador", orientador),
        (f"{F}:checkModalidade", f"{F}:modalidade", modalidade_id),
        (f"{F}:checkCentro", f"{F}:centro", centro_id),
        (f"{F}:checkCurso", f"{F}:curso", curso_id),
    ])
    res = await _ex2_enviar(c, page, F, extra, botao=(f"{F}:buscar", "Buscar"))
    if "deveria ser uma lista de n" in res.html:
        raise SigaaError("Consulta de bolsistas indisponível neste SIGAA (parâmetro de sistema não configurado).")
    return parse_bolsistas_pesquisa(res.html)


async def _buscar_laboratorios_page(c: SigaaClient, **f) -> Page:
    F = "form"
    page = await c.get(URL_LABORATORIOS)
    extra = _ex2_filtros([
        (f"{F}:selectBuscaAno", f"{F}:buscaAno", f.get("ano")),
        (f"{F}:selectBuscaNome", f"{F}:buscaNome", f.get("nome")),
        (f"{F}:selectBuscaTipoLaboratorio", f"{F}:buscaTipoLaboratorio", f.get("tipo_id")),
        (f"{F}:selectBuscaServidor", f"{F}:nomeServidor", f.get("servidor")),
        (f"{F}:selectBuscaLaboratorioEmAtividade", f"{F}:buscaEmAtividade", f.get("em_atividade")),
        (f"{F}:selectBuscaLaboratorioComPrestacaoServicos", f"{F}:buscaPrestaServicos", f.get("presta_servicos")),
        (f"{F}:selectBuscaServicoPrestado", f"{F}:servicoPrestado", f.get("servico")),
    ])
    return await _ex2_enviar(c, page, F, extra, botao=(f"{F}:btnBuscar", "Buscar"))


async def buscar_laboratorios(
    c: SigaaClient,
    *,
    nome: str | None = None,
    ano: int | None = None,
    tipo_id: int | None = None,
    servidor: str | None = None,
    em_atividade: bool | None = None,
    presta_servicos: bool | None = None,
    servico: str | None = None,
) -> list[LaboratorioPesquisaResumo]:
    """Laboratórios de pesquisa. ``tipo_id``: 3 = multiusuários, 4 = uso restrito."""
    page = await _buscar_laboratorios_page(
        c, nome=nome, ano=ano, tipo_id=tipo_id, servidor=servidor,
        em_atividade=em_atividade, presta_servicos=presta_servicos, servico=servico,
    )
    return parse_laboratorios(page.html)


async def obter_laboratorio(
    c: SigaaClient,
    laboratorio_id: int,
    *,
    nome: str | None = None,
    ano: int | None = None,
    tipo_id: int | None = None,
) -> LaboratorioPesquisa:
    """Detalhe de um laboratório (aberto a partir da lista filtrada por ``nome``/``ano``/``tipo_id``)."""
    page = await _buscar_laboratorios_page(c, nome=nome, ano=ano, tipo_id=tipo_id)
    link = _ex2_link(page, "id", laboratorio_id)
    if link is None:
        raise NaoEncontrado(f"Laboratório {laboratorio_id} não está na lista com esses filtros.")
    det = await _ex2_clicar(c, page, link)
    lab = parse_laboratorio(det.html)
    if not lab.nome and not lab.codigo:
        raise NaoEncontrado(f"Laboratório {laboratorio_id} não abriu.")
    return lab.model_copy(update={"id": laboratorio_id})


# ------------------------------------------------------------------ extensão
async def _buscar_extensao_page(c: SigaaClient, **f) -> Page:
    F = "formBuscaAtividade"
    page = await c.get(URL_EXTENSAO)
    extra = _ex2_filtros([
        (f"{F}:selectBuscaTitulo", f"{F}:buscaTitulo", f.get("titulo")),
        (f"{F}:selectBuscaTipoAtividade", f"{F}:buscaTipoAcao", f.get("tipo_id")),
        (f"{F}:selectBuscaUnidadeProponente", f"{F}:buscaUnidade", f.get("unidade_id")),
        (f"{F}:selectBuscaAno", f"{F}:buscaAno", f.get("ano")),
    ])
    # a tela já vem com "Tipo de Atividade" marcado (PROGRAMA); sem tipo pedido, desmarca
    sem = () if f.get("tipo_id") else (f"{F}:selectBuscaTipoAtividade",)
    return await _ex2_enviar(c, page, F, extra, botao=(f"{F}:btBuscar", "Buscar"), sem=sem)


async def buscar_acoes_extensao(
    c: SigaaClient,
    *,
    tipo_id: int | None = None,
    titulo: str | None = None,
    unidade_id: int | None = None,
    ano: int | None = None,
) -> list[AcaoExtensaoResumo]:
    """Ações de extensão. ``tipo_id``: 1 programa, 2 projeto, 3 curso, 4 evento,
    5 prestação de serviços, 6 produto. A lista vem inteira (sem paginação)."""
    page = await _buscar_extensao_page(c, tipo_id=tipo_id, titulo=titulo, unidade_id=unidade_id, ano=ano)
    return parse_acoes_extensao(page.html)


async def obter_acao_extensao(
    c: SigaaClient,
    acao_id: int,
    *,
    tipo_id: int | None = None,
    titulo: str | None = None,
    ano: int | None = None,
) -> AcaoExtensao:
    """Detalhe de uma ação de extensão.

    Com filtros: refaz a busca e clica na ação (caminho JSF). Sem filtros: GET no link público
    bookmarkable ``/sigaa/link/public/extensao/visualizacaoAcaoExtensao/{id}`` (que redireciona
    para viewDadosCursoEvento.jsf)."""
    if tipo_id or titulo or ano:
        page = await _buscar_extensao_page(c, tipo_id=tipo_id, titulo=titulo, ano=ano)
        link = _ex2_link(page, "idAtividadeExtensaoSelecionada", acao_id)
        if link is None:
            raise NaoEncontrado(f"Ação de extensão {acao_id} não está na lista com esses filtros.")
        det = await _ex2_clicar(c, page, link)
    else:
        det = await c.get(URL_EXTENSAO_LINK.format(id=int(acao_id)))
    acao = parse_acao_extensao(det.html)
    if not acao.titulo:
        raise NaoEncontrado(f"Ação de extensão {acao_id} não encontrada.")
    return acao.model_copy(update={"id": acao_id})


async def listar_inscricoes_extensao(
    c: SigaaClient, *, titulo: str | None = None, tipo_id: int | None = None
) -> list[InscricaoExtensaoAberta]:
    """Cursos/eventos de extensão com inscrição aberta (SÓ lista; não inscreve). ``tipo_id``: 3 curso, 4 evento."""
    page = await c.get(URL_INSCRICOES)
    if titulo or tipo_id:
        F = "formListaCursosEventosExtensao"
        extra = _ex2_filtros([
            (f"{F}:selectBuscaTitulo", f"{F}:buscaTitulo", titulo),
            (f"{F}:selectBuscaTipoAtividade", f"{F}:buscaTipoAcao", tipo_id),
        ])
        page = await _ex2_enviar(c, page, F, extra, botao=(f"{F}:cmdFiltarPeriodosInscricao", "Filtrar"))
    return parse_inscricoes_extensao(page.html)


# ------------------------------------------------------------ cursos abertos
async def listar_centros_cursos_abertos(c: SigaaClient) -> list[CentroCursoAberto]:
    """Centros (com os departamentos do menu) que aparecem em Cursos Abertos."""
    page = await c.get(URL_CURSOS_ABERTOS)
    return parse_centros_cursos_abertos(page.html)


async def _ex2_a4j_centro(c: SigaaClient, page: Page, centro_id: int) -> Page:
    """Dispara o a4j do select de centro (preenche o select de departamento no servidor)."""
    sel = page.soup.find("select", id="formPrincipal:idCentro")
    onchange = (sel.get("onchange") or "") if sel else ""
    params = dict(_EX2_PARAMS.findall(onchange))
    container = params.pop("containerId", None)
    params.pop("similarityGroupingId", None)
    if not container:
        raise NavegacaoInvalida("Select de centro sem a4j reconhecível em Cursos Abertos.")
    extra = {"AJAXREQUEST": container, "formPrincipal:idCentro": str(centro_id), **params}
    return await _ex2_enviar(c, page, "formPrincipal", extra)


async def listar_departamentos_cursos_abertos(c: SigaaClient, centro_id: int) -> list[DepartamentoCursoAberto]:
    """Departamentos (com id) de um centro — o mesmo AJAX que a tela faz ao trocar o centro."""
    page = await c.get(URL_CURSOS_ABERTOS)
    resp = await _ex2_a4j_centro(c, page, centro_id)
    return parse_departamentos_cursos_abertos(resp.html)


async def _buscar_cursos_abertos_page(
    c: SigaaClient, palavra_chave: str | None, centro_id: int | None, departamento_id: int | None
) -> Page:
    page = await c.get(URL_CURSOS_ABERTOS)
    if not (palavra_chave or centro_id or departamento_id):
        return page  # sem filtro a própria tela traz as "Últimas Turmas Publicadas"
    extra = {"formPrincipal:tipoBusca": "true", "formPrincipal:palavraChave": palavra_chave or ""}
    if centro_id:
        extra["formPrincipal:idCentro"] = str(centro_id)
    if departamento_id:
        if not centro_id:
            raise ValueError("departamento_id exige centro_id (o select de departamento depende do centro).")
        resp = await _ex2_a4j_centro(c, page, centro_id)
        if resp.viewstate:  # o a4j pode avançar o ViewState da tela
            extra["javax.faces.ViewState"] = resp.viewstate
        extra["formPrincipal:idDepartamento"] = str(departamento_id)
    return await _ex2_enviar(c, page, "formPrincipal", extra, botao=("formPrincipal:buscarTurmas", "Buscar"))


async def buscar_cursos_abertos(
    c: SigaaClient,
    *,
    palavra_chave: str | None = None,
    centro_id: int | None = None,
    departamento_id: int | None = None,
) -> list[CursoAbertoTurma]:
    """Turmas com conteúdo aberto. Sem filtros: as últimas turmas publicadas."""
    page = await _buscar_cursos_abertos_page(c, palavra_chave, centro_id, departamento_id)
    return parse_cursos_abertos(page.html)


async def obter_curso_aberto(
    c: SigaaClient, turma_id: int, *, palavra_chave: str | None = None
) -> CursoAberto:
    """Página pública de uma turma aberta (ementa, docentes, tópicos e materiais).
    A turma precisa estar na lista inicial ou no resultado de ``palavra_chave``."""
    page = await _buscar_cursos_abertos_page(c, palavra_chave, None, None)
    link = _ex2_link(page, "tid", turma_id)
    if link is None:
        raise NaoEncontrado(f"Turma aberta {turma_id} não está na lista.")
    det = await _ex2_clicar(c, page, link)
    curso = parse_curso_aberto(det.html)
    if not curso.nome:
        raise NaoEncontrado(f"Turma aberta {turma_id} não abriu.")
    return curso.model_copy(update={"id": turma_id})


__all__ = [
    "buscar_projetos_pesquisa",
    "obter_projeto_pesquisa",
    "buscar_bases_pesquisa",
    "buscar_bolsistas_pesquisa",
    "buscar_laboratorios",
    "obter_laboratorio",
    "buscar_acoes_extensao",
    "obter_acao_extensao",
    "listar_inscricoes_extensao",
    "listar_centros_cursos_abertos",
    "listar_departamentos_cursos_abertos",
    "buscar_cursos_abertos",
    "obter_curso_aberto",
]
