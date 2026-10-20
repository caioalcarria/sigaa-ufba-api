"""Rotas de consulta: Calendário Acadêmico e Consultas Gerais do Portal do Discente (logadas,
em ``/v1/calendario`` e ``/v1/consultas/...``) + o SIGAA público sem login (``/v1/publico/...``).

Rotas públicas: cada requisição abre um ``SigaaClient`` ANÔNIMO próprio
(``sigaa.services.consultas.cliente_anonimo``) e fecha no fim — sem token, sem estado.
Quando a mesma informação existe nas duas versões, prefira a pública (não exige login)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query

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
    Pagina,
    ProcessamentoTurma,
    TurmaDetalhe,
    TurmaOferta,
    UnidadeConsulta,
)
from sigaa.client import SigaaClient
from sigaa.models import consultas_publico as MP
from sigaa.services import consultas as S
from sigaa.services import consultas_publico as SP

from ..deps import Cliente
from ..seguranca_http import mensagem_publica

router = APIRouter(prefix="/v1")


def _422(e: ValueError) -> HTTPException:
    # só a mensagem de propósito do serviço; ValueError do Python (parse do HTML do SIGAA) não vaza
    return HTTPException(422, detail={"codigo": "filtro_invalido", "mensagem": mensagem_publica(e, "Filtro inválido.")})


async def _logado(cli: SigaaClient, fluxo: Callable[[SigaaClient], Awaitable[Any]]) -> Any:
    """``cli.executar`` + filtro inválido (``ValueError`` do serviço) → 422."""
    try:
        return await cli.executar(fluxo)
    except ValueError as e:
        raise _422(e) from None


async def _publico(fluxo: Callable[[SigaaClient], Awaitable[Any]]) -> Any:
    """Roda o fluxo num ``SigaaClient`` ANÔNIMO novo (sem token), fechado no fim."""
    try:
        async with S.cliente_anonimo() as c:
            return await fluxo(c)
    except ValueError as e:
        raise _422(e) from None

LOGADO = ["Consultas (logado)"]
CAL = ["Calendário acadêmico"]

PaginaQ = Annotated[int, Query(ge=1, description="Página (começa em 1).")]
PorPaginaQ = Annotated[int, Query(ge=1, le=500, description="Itens por página (máx. 500).")]


# =================================================================== calendário
@router.get(
    "/calendario",
    response_model=Calendario,
    tags=CAL,
    summary="Calendário acadêmico de um período",
    description="Todos os prazos do calendário (período letivo, férias, matrícula, rematrícula, ajustes, "
    "trancamento, consolidação, turmas de férias, docência assistida...), cada um com início/fim ISO. "
    "Sem `ano`/`periodo`: o semestre atual do aluno. `id` (de /v1/calendario/lista) tem precedência. "
    "Calendários de Ensino a Distância estão bloqueados: abri-los dá 'Comportamento Inesperado' no SIGAA UFBA.",
)
async def get_calendario(
    cli: Cliente,
    ano: Annotated[int | None, Query(ge=1960, le=2100, description="Ano letivo.")] = None,
    periodo: Annotated[int | None, Query(ge=1, le=9, description="Período letivo.")] = None,
    id: Annotated[int | None, Query(description="Id do calendário (de /v1/calendario/lista).")] = None,
):
    return await _logado(cli, lambda c: S.calendario(c, ano, periodo, ead=False, id_calendario=id))


@router.get(
    "/calendario/lista",
    response_model=list[CalendarioResumo],
    tags=CAL,
    summary="Todos os calendários acadêmicos",
    description="Lista de calendários (1969.1 até o próximo período), geral e EAD, com o id de cada um.",
)
async def get_calendarios(cli: Cliente, ano: Annotated[int | None, Query(description="Filtra por ano.")] = None):
    lista = await _logado(cli, S.listar_calendarios)
    return [x for x in lista if ano is None or x.ano == ano]


# ======================================================================= cursos
@router.get(
    "/consultas/cursos",
    response_model=Pagina[CursoConsulta],
    tags=LOGADO,
    summary="Consulta geral de cursos",
    description="Cursos por nível com o(s) coordenador(es). `nivel`: G=graduação, L=especialização, "
    "R=residência, S=stricto, E=mestrado, D=doutorado, T=técnico, M=médio... A tela não expõe id do curso: "
    "pra isso use /v1/consultas/cursos/ids.",
)
async def get_cursos(
    cli: Cliente,
    nivel: Annotated[str, Query(pattern="^[IUMTNFGLRSED]$", description="Letra do nível.")] = "G",
    nome: Annotated[str | None, Query(min_length=2, description="Trecho do nome.")] = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _logado(cli, lambda c: S.buscar_cursos(c, nivel, nome))
    return Pagina[CursoConsulta].de(itens, pagina, por_pagina)


@router.get(
    "/consultas/cursos/ids",
    response_model=list[CursoOpcao],
    tags=LOGADO,
    summary="Cursos de graduação com id",
    description="Cursos (com o id do SIGAA, município e grau) aceitos em /v1/consultas/estruturas e no filtro `curso` de /v1/consultas/turmas.",
)
async def get_cursos_ids(cli: Cliente, nome: Annotated[str | None, Query(description="Filtra pelo trecho do nome.")] = None):
    itens = await _logado(cli, S.cursos_com_id)
    return [x for x in itens if not nome or nome.upper() in x.texto.upper()]


# ================================================================== componentes
@router.get(
    "/consultas/componentes",
    response_model=Pagina[ComponenteResumo],
    tags=LOGADO,
    summary="Buscar componentes curriculares",
    description="Busca por código, trecho do nome, nível (letra), unidade responsável (id), tipo e modalidade "
    "(ids de /v1/consultas/componentes/filtros). Pelo menos um filtro.",
)
async def get_componentes(
    cli: Cliente,
    codigo: Annotated[str | None, Query(description="Código (ex.: MATA37).")] = None,
    nome: Annotated[str | None, Query(min_length=3, description="Trecho do nome.")] = None,
    nivel: Annotated[str | None, Query(description="Letra do nível (G=graduação...).")] = None,
    unidade: Annotated[int | None, Query(description="Id da unidade responsável.")] = None,
    tipo: Annotated[int | None, Query(description="1=atividade, 2=disciplina, 3=módulo, 4=bloco.")] = None,
    modalidade: Annotated[int | None, Query(description="1=presencial, 2=a distância.")] = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _logado(cli, lambda c: S.buscar_componentes(c, codigo, nome, nivel, unidade, tipo, modalidade))
    return Pagina[ComponenteResumo].de(itens, pagina, por_pagina)


@router.get(
    "/consultas/componentes/filtros",
    response_model=dict[str, list[Opcao]],
    tags=LOGADO,
    summary="Opções dos filtros de componentes",
    description="Níveis, unidades responsáveis, tipos e modalidades aceitos em /v1/consultas/componentes.",
)
async def get_componentes_filtros(cli: Cliente):
    return await _logado(cli, S.opcoes_componentes)


@router.get(
    "/consultas/componentes/{componente_id}",
    response_model=ComponenteDetalhe,
    tags=LOGADO,
    summary="Componente curricular (ementa, CH, requisitos, equivalências)",
    description="Detalhe pelo id: ementa, carga horária detalhada, pré/co-requisitos e equivalências (expressão + "
    "componentes citados) e demais informações. `completo=true` acrescenta quem tem este componente como "
    "pré-requisito/equivalente, o histórico de equivalências e as estruturas curriculares que o incluem (+3 telas).",
)
async def get_componente(cli: Cliente, componente_id: int, completo: bool = False):
    return await _logado(cli, lambda c: S.componente(c, componente_id, completo))


# =================================================================== estruturas
@router.get(
    "/consultas/estruturas",
    response_model=list[EstruturaResumo],
    tags=LOGADO,
    summary="Estruturas curriculares de um curso",
    description="Estruturas (currículos) de um curso (`curso` = id de /v1/consultas/cursos/ids) ou por `codigo`.",
)
async def get_estruturas(
    cli: Cliente,
    curso: Annotated[int | None, Query(description="Id do curso.")] = None,
    codigo: Annotated[str | None, Query(description="Código da estrutura (ex.: G20251X).")] = None,
    somente_ativas: bool = False,
):
    return await _logado(cli, lambda c: S.buscar_estruturas(c, curso, codigo, somente_ativas))


@router.get(
    "/consultas/estruturas/{estrutura_id}",
    response_model=EstruturaDetalhe,
    tags=LOGADO,
    summary="Estrutura curricular completa",
    description="Prazos, cargas horárias (obrigatória, optativa, complementar, máxima por período) e TODOS os "
    "componentes por semestre + optativos, com id, CH, tipo, natureza e modalidade.",
)
async def get_estrutura(cli: Cliente, estrutura_id: int):
    return await _logado(cli, lambda c: S.estrutura(c, estrutura_id))


@router.get(
    "/consultas/estruturas/{estrutura_id}/declaracao-prazo-maximo",
    response_model=DeclaracaoPrazoMaximo,
    tags=LOGADO,
    summary="Declaração de prazo máximo de integralização",
    description="Documento emitido pelo SIGAA com o prazo máximo do curso, identificador e código de verificação.",
)
async def get_declaracao_prazo(cli: Cliente, estrutura_id: int):
    return await _logado(cli, lambda c: S.declaracao_prazo_maximo(c, estrutura_id))


# ======================================================================= turmas
@router.get(
    "/consultas/turmas",
    response_model=Pagina[TurmaOferta],
    tags=LOGADO,
    summary="Turmas ofertadas (consulta geral)",
    description="Oferta de turmas: docentes, horário (código + decodificado), local por dia, situação, "
    "matriculados/capacidade. Sem `ano`/`periodo` o SIGAA usa o período atual. Pelo menos um filtro além "
    "do período. Ids de unidade/curso/etc. em /v1/consultas/turmas/filtros.",
)
async def get_turmas(
    cli: Cliente,
    ano: int | None = None,
    periodo: int | None = None,
    componente: Annotated[str | None, Query(description="Código do componente (ex.: MATA37).")] = None,
    nome: Annotated[str | None, Query(description="Trecho do nome do componente.")] = None,
    unidade: Annotated[int | None, Query(description="Id da unidade.")] = None,
    docente: Annotated[str | None, Query(description="Trecho do nome do docente.")] = None,
    curso: Annotated[int | None, Query(description="Id do curso.")] = None,
    turma: Annotated[str | None, Query(description="Código da turma (ex.: 01).")] = None,
    local: Annotated[str | None, Query(description="Trecho do local.")] = None,
    horario: Annotated[str | None, Query(description="Código de horário (ex.: 35T12).")] = None,
    nivel: Annotated[str | None, Query(description="Letra do nível.")] = None,
    situacao: Annotated[int | None, Query(description="1=aberta, 2=a definir docente, 3=consolidada.")] = None,
    tipo: Annotated[int | None, Query(description="1=regular, 2=férias, 3=ensino individual.")] = None,
    modalidade: Annotated[int | None, Query(description="1=presencial, 2=a distância, 3=semipresencial, 4=remoto.")] = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _logado(
        cli,
        lambda c: S.buscar_turmas(
            c, ano, periodo, componente, nome, unidade, docente, curso, turma, local, horario, nivel, situacao, tipo, modalidade
        )
    )
    return Pagina[TurmaOferta].de(itens, pagina, por_pagina)


@router.get(
    "/consultas/turmas/filtros",
    response_model=dict[str, list[Opcao]],
    tags=LOGADO,
    summary="Opções dos filtros de turmas",
    description="Níveis, unidades, cursos, situações, tipos, modalidades e ordenações aceitos em /v1/consultas/turmas.",
)
async def get_turmas_filtros(cli: Cliente):
    return await _logado(cli, S.opcoes_turmas)


@router.get(
    "/consultas/turmas/{turma_id}",
    response_model=TurmaDetalhe,
    tags=LOGADO,
    summary="Informações da turma (vagas e solicitações)",
    description="Painel da turma: período letivo, local e horário, capacidade, solicitações na matrícula e na "
    "rematrícula, matriculados, professores e vagas reservadas por curso.",
)
async def get_turma(cli: Cliente, turma_id: int):
    return await _logado(cli, lambda c: S.turma(c, turma_id))


@router.get(
    "/consultas/turmas/{turma_id}/processamento",
    response_model=ProcessamentoTurma,
    tags=LOGADO,
    summary="Resultado do processamento da matrícula (agregado)",
    description="Reserva de vagas e contagem de solicitações por situação (MATRICULADO, INDEFERIDO...) de QUALQUER "
    "turma. A tela original lista nome e matrícula de outros alunos; esta API só devolve números. "
    "`rematricula=true` = processamento da rematrícula.",
)
async def get_processamento(cli: Cliente, turma_id: int, rematricula: bool = False):
    return await _logado(cli, lambda c: S.processamento_turma(c, turma_id, rematricula))


# ===================================================================== unidades
@router.get(
    "/consultas/unidades",
    response_model=list[UnidadeConsulta],
    tags=LOGADO,
    summary="Buscar unidades acadêmicas",
    description="Por trecho do `nome` ou por `tipo` (ids em /v1/consultas/unidades/tipos: 1=Departamento, "
    "4=Centro Acadêmico, 6=Coordenação de Curso...). O `id` devolvido é o mesmo dos filtros de turma/componente.",
)
async def get_unidades(
    cli: Cliente,
    nome: Annotated[str | None, Query(min_length=3)] = None,
    tipo: int | None = None,
    ativa: bool | None = None,
):
    return await _logado(cli, lambda c: S.buscar_unidades(c, nome, tipo, ativa))


@router.get(
    "/consultas/unidades/tipos",
    response_model=list[Opcao],
    tags=LOGADO,
    summary="Tipos de unidade acadêmica",
    description="Valores aceitos no filtro `tipo` de /v1/consultas/unidades.",
)
async def get_tipos_unidade(cli: Cliente):
    return await _logado(cli, S.tipos_unidade)


# ##############################################################################
# SIGAA PÚBLICO — sem login, sem token (cada requisição abre uma sessão anônima)
# ##############################################################################

PUB_ENSINO = ["Público · cursos, componentes e turmas"]
PUB_PESSOAS = ["Público · docentes e unidades"]
PUB_BIB = ["Público · biblioteca"]
PUB_POS = ["Público · pós-graduação e processos seletivos"]
PUB_PESQ = ["Público · pesquisa, extensão e cursos abertos"]

NivelCursoQ = Annotated[str, Query(pattern="^[GSLTN]$", description="G=graduação, S=stricto, L=lato, T=técnico, N=técnico integrado.")]
NivelCompQ = Annotated[str, Query(pattern="^[IUMTNFGLRSED]$", description="Letra do nível (G=graduação, S=stricto...).")]


def _pag(itens: list, pagina: int, por_pagina: int) -> Pagina:
    return Pagina.de(itens, pagina, por_pagina)


# ---------------------------------------------------------------- cursos
@router.get(
    "/publico/cursos",
    response_model=Pagina[MP.CursoResumo],
    tags=PUB_ENSINO,
    summary="Cursos (público)",
    description="Cursos de um nível com sede, modalidade, coordenador e o id usado nas outras rotas. Filtros locais por trecho do nome, modalidade e unidade.",
)
async def pub_cursos(
    nivel: NivelCursoQ = "G",
    nome: str | None = None,
    modalidade: str | None = None,
    unidade: str | None = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 200,
):
    itens = await _publico(lambda c: SP.listar_cursos(c, nivel, nome=nome, modalidade=modalidade, unidade=unidade))
    return _pag(itens, pagina, por_pagina)


@router.get(
    "/publico/cursos/{curso_id}",
    response_model=MP.Curso,
    tags=PUB_ENSINO,
    summary="Página pública do curso",
    description="Coordenação, título profissional, área CNPq, modalidade, contatos, calendário resumido. Pós: `nivel=S` (traz também as estruturas).",
)
async def pub_curso(curso_id: int, nivel: NivelCursoQ = "G"):
    return await _publico(lambda c: SP.curso(c, curso_id, nivel))


@router.get(
    "/publico/cursos/{curso_id}/estruturas",
    response_model=list[MP.EstruturaResumo],
    tags=PUB_ENSINO,
    summary="Estruturas curriculares do curso (público)",
    description="Estruturas (currículos) do curso com id, código, ano de criação e se está ativa.",
)
async def pub_estruturas_curso(curso_id: int, nivel: NivelCursoQ = "G"):
    return await _publico(lambda c: SP.estruturas_curso(c, curso_id, nivel))


@router.get(
    "/publico/cursos/{curso_id}/estruturas/{estrutura_id}",
    response_model=MP.EstruturaCurricular,
    tags=PUB_ENSINO,
    summary="Estrutura curricular completa (público)",
    description="Componentes por semestre, optativas, complementares, cargas horárias e prazos. O SIGAA público só abre a "
    "estrutura a partir do curso. `relatorio=true` usa o 'Relatório' em vez dos 'Detalhes'.",
)
async def pub_estrutura(curso_id: int, estrutura_id: int, nivel: NivelCursoQ = "G", relatorio: bool = False):
    return await _publico(lambda c: SP.estrutura_curricular(c, estrutura_id, curso_id, nivel, relatorio=relatorio))


@router.get(
    "/publico/estruturas/{estrutura_id}",
    response_model=MP.EstruturaCurricular,
    tags=PUB_ENSINO,
    summary="Estrutura curricular (atalho, exige ?curso=)",
    description="Igual a /v1/publico/cursos/{curso}/estruturas/{id}: o SIGAA público só abre estruturas a partir do curso.",
)
async def pub_estrutura_atalho(
    estrutura_id: int,
    curso: Annotated[int, Query(description="Id do curso dono da estrutura.")],
    nivel: NivelCursoQ = "G",
    relatorio: bool = False,
):
    return await _publico(lambda c: SP.estrutura_curricular(c, estrutura_id, curso, nivel, relatorio=relatorio))


@router.get("/publico/cursos/{curso_id}/calendario", response_model=list[MP.EventoCalendarioCurso], tags=PUB_ENSINO,
            summary="Calendário do curso (público)", description="Eventos do calendário do curso por ano.período.")
async def pub_calendario_curso(curso_id: int):
    return await _publico(lambda c: SP.calendario_curso(c, curso_id))


@router.get("/publico/cursos/{curso_id}/projeto-pedagogico", response_model=MP.ProjetoPedagogico, tags=PUB_ENSINO,
            summary="Projeto pedagógico do curso", description="Perfil profissional, competências, metodologia, avaliação e anexo do PPC.")
async def pub_ppp(curso_id: int):
    return await _publico(lambda c: SP.projeto_pedagogico(c, curso_id))


@router.get("/publico/cursos/{curso_id}/noticias", response_model=list[MP.NoticiaCurso], tags=PUB_ENSINO,
            summary="Notícias do curso", description="Notícias publicadas no portal público do curso.")
async def pub_noticias_curso(curso_id: int):
    return await _publico(lambda c: SP.noticias_curso(c, curso_id))


@router.get(
    "/publico/cursos/{curso_id}/turmas",
    response_model=list[MP.TurmaCurso],
    tags=PUB_ENSINO,
    summary="Turmas com vagas reservadas ao curso",
    description="Turmas do período com docentes (SIAPE), vagas reservadas ao curso e horário decodificado.",
)
async def pub_turmas_curso(curso_id: int, ano: int, periodo: Annotated[int, Query(ge=1, le=4)], codigo: str | None = None):
    return await _publico(lambda c: SP.turmas_curso(c, curso_id, ano, periodo, codigo=codigo))


# ----------------------------------------------------------- componentes
@router.get(
    "/publico/componentes",
    response_model=Pagina[MP.ComponenteResumo],
    tags=PUB_ENSINO,
    summary="Buscar componentes curriculares (público)",
    description="Por código, trecho do nome, unidade (id de /v1/publico/unidades) e tipo (DISCIPLINA, ATIVIDADE, BLOCO, MÓDULO). Pelo menos um filtro.",
)
async def pub_componentes(
    nivel: NivelCompQ = "G",
    codigo: str | None = None,
    nome: str | None = None,
    unidade: int | None = None,
    tipo: str | None = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _publico(lambda c: SP.buscar_componentes(c, nivel, codigo=codigo, nome=nome, unidade_id=unidade, tipo=tipo))
    return _pag(itens, pagina, por_pagina)


@router.get(
    "/publico/componentes/codigo/{codigo}",
    response_model=MP.ComponenteCurricular,
    tags=PUB_ENSINO,
    summary="Componente pelo código (formato completo)",
    description="Busca o código e abre 'Detalhes': ementa, modalidade, requisitos, equivalências, tabela de cargas horárias, "
    "quem tem este como pré-requisito/equivalente, histórico de equivalências e currículos.",
)
async def pub_componente_codigo(codigo: str, nivel: NivelCompQ = "G"):
    return await _publico(lambda c: SP.componente_por_codigo(c, codigo, nivel))


@router.get(
    "/publico/componentes/codigo/{codigo}/programa",
    response_model=MP.ProgramaComponente,
    tags=PUB_ENSINO,
    summary="Programa do componente",
    description="Objetivos, conteúdo, metodologia, avaliação e referências. 404 quando não há programa cadastrado (o caso comum na UFBA).",
)
async def pub_programa(codigo: str, nivel: NivelCompQ = "G"):
    return await _publico(lambda c: SP.programa_componente(c, codigo, nivel))


@router.get(
    "/publico/componentes/{componente_id}",
    response_model=MP.ComponenteCurricular,
    tags=PUB_ENSINO,
    summary="Componente pelo id (GET direto)",
    description="Detalhe por `/sigaa/link/public/ensino/visualizarComponente/{id}` (1 pedido; sem modalidade e sem a tabela de CHs — pra isso use /componentes/codigo/{codigo}).",
)
async def pub_componente(componente_id: int):
    return await _publico(lambda c: SP.componente(c, componente_id))


# ---------------------------------------------------------------- turmas
@router.get(
    "/publico/turmas",
    response_model=Pagina[MP.TurmaPublica],
    tags=PUB_ENSINO,
    summary="Turmas ofertadas por unidade (público)",
    description="Turmas de uma unidade no período: componente, turma, docentes com CH e local/horário. `ano`, `periodo` e `unidade` "
    "obrigatórios (o SIGAA exige). O público não mostra vagas nem idTurma — pra isso, a consulta logada /v1/consultas/turmas.",
)
async def pub_turmas(
    ano: int,
    periodo: Annotated[int, Query(ge=1, le=4)],
    unidade: Annotated[int, Query(description="Id da unidade (de /v1/publico/unidades).")],
    nivel: NivelCompQ = "G",
    componente: Annotated[str | None, Query(description="Filtra por código do componente.")] = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 200,
):
    itens = await _publico(lambda c: SP.buscar_turmas(c, ano, periodo, unidade, nivel, componente=componente))
    return _pag(itens, pagina, por_pagina)


@router.get("/publico/unidades", response_model=list[MP.UnidadeAcademica], tags=PUB_PESSOAS,
            summary="Unidades que ofertam turmas", description="Ids aceitos em /publico/turmas, /publico/componentes e /publico/departamentos/{id}.")
async def pub_unidades():
    return await _publico(SP.unidades_academicas)


# --------------------------------------------------------------- docentes
@router.get(
    "/publico/docentes",
    response_model=Pagina[MP.DocenteResumo],
    tags=PUB_PESSOAS,
    summary="Buscar docentes",
    description="Por trecho do nome e/ou departamento de lotação (id). Devolve o SIAPE usado no perfil.",
)
async def pub_docentes(
    nome: Annotated[str | None, Query(min_length=3)] = None,
    departamento: int | None = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _publico(lambda c: SP.buscar_docentes(c, nome=nome, departamento_id=departamento))
    return _pag(itens, pagina, por_pagina)


@router.get("/publico/docentes/{siape}", response_model=MP.Docente, tags=PUB_PESSOAS,
            summary="Perfil público do docente", description="Unidade, descrição, formação, áreas de interesse, Lattes e contatos profissionais.")
async def pub_docente(siape: int):
    return await _publico(lambda c: SP.docente(c, siape))


@router.get("/publico/docentes/{siape}/producao", response_model=list[MP.ProducaoCategoria], tags=PUB_PESSOAS,
            summary="Produção intelectual do docente", description="Categorias (TCCs, orientações, artigos...) com os itens.")
async def pub_producao(siape: int):
    return await _publico(lambda c: SP.producao_docente(c, siape))


@router.get("/publico/docentes/{siape}/disciplinas", response_model=list[MP.DisciplinaMinistrada], tags=PUB_PESSOAS,
            summary="Disciplinas ministradas pelo docente", description="Todas as turmas por período, com id do componente, CH e horário.")
async def pub_disciplinas_docente(siape: int):
    return await _publico(lambda c: SP.disciplinas_docente(c, siape))


# ------------------------------------------------- centros/departamentos
@router.get("/publico/centros", response_model=list[MP.CentroResumo], tags=PUB_PESSOAS,
            summary="Centros / unidades acadêmicas", description="Centros com município e departamentos.")
async def pub_centros():
    return await _publico(SP.listar_centros)


@router.get("/publico/centros/{centro_id}", response_model=MP.Centro, tags=PUB_PESSOAS,
            summary="Portal do centro", description="Apresentação, diretoria, contatos, departamentos, cursos, programas, bases de pesquisa e documentos.")
async def pub_centro(centro_id: int):
    return await _publico(lambda c: SP.centro(c, centro_id))


@router.get("/publico/departamentos", response_model=list[MP.DepartamentoResumo], tags=PUB_PESSOAS,
            summary="Departamentos", description="Todos os departamentos, ou os de um centro (`centro` = id de /publico/centros).")
async def pub_departamentos(centro: int | None = None):
    return await _publico(lambda c: SP.listar_departamentos(c, centro_id=centro))


@router.get("/publico/departamentos/{departamento_id}", response_model=MP.Departamento, tags=PUB_PESSOAS,
            summary="Portal do departamento", description="Chefia (SIAPE), apresentação e notícias. O id é o mesmo de /publico/unidades.")
async def pub_departamento(departamento_id: int):
    return await _publico(lambda c: SP.departamento(c, departamento_id))


@router.get("/publico/departamentos/{departamento_id}/docentes", response_model=list[MP.DocenteResumo], tags=PUB_PESSOAS,
            summary="Corpo docente do departamento", description="Docentes com titulação, categoria, Lattes e SIAPE.")
async def pub_docentes_departamento(departamento_id: int):
    return await _publico(lambda c: SP.docentes_departamento(c, departamento_id))


@router.get("/publico/departamentos/{departamento_id}/componentes", response_model=list[MP.ComponenteResumo], tags=PUB_PESSOAS,
            summary="Componentes do departamento", description="Componentes curriculares ofertados pelo departamento, com id.")
async def pub_componentes_departamento(departamento_id: int):
    return await _publico(lambda c: SP.componentes_departamento(c, departamento_id))


@router.get(
    "/publico/responsaveis",
    response_model=list[MP.Responsavel],
    tags=PUB_PESSOAS,
    summary="Chefes, coordenadores e diretores",
    description="`tipo`: chefes (de departamento), coordenadores_graduacao, coordenadores_pos ou diretores (de centro).",
)
async def pub_responsaveis(
    tipo: Annotated[str, Query(pattern="^(chefes|coordenadores_graduacao|coordenadores_pos|diretores)$")] = "chefes",
):
    return await _publico(lambda c: SP.responsaveis(c, tipo))


# -------------------------------------------------------------- biblioteca
@router.get(
    "/publico/biblioteca/acervo",
    response_model=Pagina[MP.AcervoTitulo],
    tags=PUB_BIB,
    summary="Buscar no acervo das bibliotecas",
    description="Título, autor, assunto, editora, local, intervalo de anos, tipo de material e coleção (textos com 3+ letras). "
    "Lê até `max_paginas` páginas de 100 do SIGAA.",
)
async def pub_acervo(
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
    max_paginas: Annotated[int, Query(ge=1, le=10)] = 5,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _publico(
        lambda c: SP.buscar_acervo(
            c, titulo=titulo, autor=autor, assunto=assunto, editora=editora, local_publicacao=local_publicacao,
            ano_inicio=ano_inicio, ano_fim=ano_fim, tipo_material=tipo_material, colecao=colecao, ordenacao=ordenacao,
            max_paginas=max_paginas,
        )
    )
    return _pag(itens, pagina, por_pagina)


@router.get(
    "/publico/biblioteca/acervo/{titulo_id}",
    response_model=MP.AcervoTituloDetalhe,
    tags=PUB_BIB,
    summary="Exemplares de um título",
    description="Exemplares, biblioteca, situação e localização. O SIGAA só abre o título a partir da busca: repita os filtros que o acharam.",
)
async def pub_titulo_acervo(
    titulo_id: int,
    titulo: str | None = None,
    autor: str | None = None,
    assunto: str | None = None,
    editora: str | None = None,
    ano_inicio: int | None = None,
    ano_fim: int | None = None,
):
    return await _publico(
        lambda c: SP.titulo_acervo(c, titulo_id, titulo=titulo, autor=autor, assunto=assunto, editora=editora, ano_inicio=ano_inicio, ano_fim=ano_fim)
    )


@router.get("/publico/biblioteca/artigos", response_model=Pagina[MP.AcervoArtigo], tags=PUB_BIB,
            summary="Buscar artigos de periódicos", description="Por título, autor e palavras-chave.")
async def pub_artigos(
    titulo: str | None = None,
    autor: str | None = None,
    palavras_chave: str | None = None,
    ordenacao: int = 1,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _publico(lambda c: SP.buscar_artigos(c, titulo=titulo, autor=autor, palavras_chave=palavras_chave, ordenacao=ordenacao))
    return _pag(itens, pagina, por_pagina)


@router.get("/publico/biblioteca/aquisicoes", response_model=list[MP.AquisicaoBiblioteca], tags=PUB_BIB,
            summary="Aquisições das bibliotecas", description="Compras de livros por título, autor e/ou ano.")
async def pub_aquisicoes(titulo: str | None = None, autor: str | None = None, ano: int | None = None):
    return await _publico(lambda c: SP.buscar_aquisicoes(c, titulo=titulo, autor=autor, ano=ano))


@router.get("/publico/biblioteca/novas-aquisicoes", response_model=MP.NovasAquisicoesBiblioteca, tags=PUB_BIB,
            summary="Informativo de novas aquisições", description="Novidades de todas as bibliotecas desde `desde` (no máximo 6 meses atrás), opcionalmente por área CNPq.")
async def pub_novas_aquisicoes(desde: date | None = None, area_cnpq: int | None = None):
    return await _publico(lambda c: SP.novas_aquisicoes(c, desde=desde, area_cnpq=area_cnpq))


# ------------------------------------------- pós e processos seletivos
@router.get("/publico/processos-seletivos", response_model=list[MP.ProcessoSeletivoResumo], tags=PUB_POS,
            summary="Processos seletivos", description="Últimos processos de um nível: S=stricto, L=lato, T=técnico, I=infantil/fundamental, F=formação complementar.")
async def pub_processos(nivel: Annotated[str, Query(pattern="^[SLTIF]$")] = "S"):
    return await _publico(lambda c: SP.listar_processos_seletivos(c, nivel=nivel))


@router.get("/publico/processos-seletivos/{processo_id}", response_model=MP.ProcessoSeletivo, tags=PUB_POS,
            summary="Processo seletivo", description="Edital, período de inscrição, vagas, etapas, comissão, documentos e notícias.")
async def pub_processo(processo_id: int, nivel: Annotated[str, Query(pattern="^[SLTIF]$")] = "S", programa: int | None = None):
    return await _publico(lambda c: SP.processo_seletivo(c, processo_id, nivel=nivel, programa_id=programa))


@router.get("/publico/programas-pos", response_model=list[MP.ProgramaPosResumo], tags=PUB_POS,
            summary="Programas de pós-graduação", description="Filtráveis por palavra do nome e centro.")
async def pub_programas(nome: str | None = None, centro: int | None = None):
    return await _publico(lambda c: SP.listar_programas_pos(c, nome=nome, id_centro=centro))


@router.get("/publico/programas-pos/{programa_id}", response_model=MP.ProgramaPos, tags=PUB_POS,
            summary="Programa de pós", description="Contato, apresentação, coordenação, últimas notícias e processos em destaque.")
async def pub_programa_pos(programa_id: int):
    return await _publico(lambda c: SP.programa_pos(c, programa_id))


@router.get("/publico/programas-pos/{programa_id}/areas", response_model=list[MP.AreaConcentracaoPos], tags=PUB_POS,
            summary="Áreas de concentração e linhas de pesquisa", description="Por nível (mestrado/doutorado).")
async def pub_programa_areas(programa_id: int):
    return await _publico(lambda c: SP.programa_pos_areas(c, programa_id))


@router.get("/publico/programas-pos/{programa_id}/cursos", response_model=list[MP.CursoProgramaPos], tags=PUB_POS,
            summary="Cursos do programa", description="Mestrado, doutorado... do programa.")
async def pub_programa_cursos(programa_id: int):
    return await _publico(lambda c: SP.programa_pos_cursos(c, programa_id))


@router.get("/publico/programas-pos/{programa_id}/docentes", response_model=list[MP.DocenteProgramaPos], tags=PUB_POS,
            summary="Corpo docente do programa", description="Por grupo/área.")
async def pub_programa_docentes(programa_id: int):
    return await _publico(lambda c: SP.programa_pos_docentes(c, programa_id))


@router.get("/publico/programas-pos/{programa_id}/processos-seletivos", response_model=list[MP.ProcessoSeletivoProgramaPos], tags=PUB_POS,
            summary="Processos seletivos do programa", description="Os listados na página do programa.")
async def pub_programa_processos(programa_id: int):
    return await _publico(lambda c: SP.programa_pos_processos_seletivos(c, programa_id))


@router.get("/publico/programas-pos/{programa_id}/noticias", response_model=list[MP.NoticiaProgramaPos], tags=PUB_POS,
            summary="Notícias do programa", description="Todas as notícias do programa.")
async def pub_programa_noticias(programa_id: int):
    return await _publico(lambda c: SP.programa_pos_noticias(c, programa_id))


@router.get("/publico/programas-pos/{programa_id}/noticias/{noticia_id}", response_model=MP.NoticiaProgramaPosDetalhe, tags=PUB_POS,
            summary="Notícia do programa", description="Texto completo de uma notícia.")
async def pub_programa_noticia(programa_id: int, noticia_id: int):
    return await _publico(lambda c: SP.programa_pos_noticia(c, programa_id, noticia_id))


@router.get("/publico/acordos-mobilidade", response_model=list[MP.AcordoMobilidade], tags=PUB_POS,
            summary="Acordos de cooperação/mobilidade internacional", description="Filtros: país (id), instituição, sigla, ano de assinatura, status.")
async def pub_acordos(pais: int | None = None, instituicao: str | None = None, sigla: str | None = None, ano_assinatura: int | None = None, status: int | None = None):
    return await _publico(lambda c: SP.listar_acordos_mobilidade(c, pais=pais, instituicao=instituicao, sigla=sigla, ano_assinatura=ano_assinatura, status=status))


# --------------------------------------- pesquisa, extensão, cursos abertos
@router.get("/publico/pesquisa/projetos", response_model=Pagina[MP.ProjetoPesquisaResumo], tags=PUB_PESQ,
            summary="Projetos de pesquisa ('quem pesquisa o quê')", description="Por título, objetivos, pesquisador, ano, centro, departamento, área e agência.")
async def pub_projetos(
    titulo: str | None = None,
    objetivos: str | None = None,
    pesquisador: str | None = None,
    ano: int | None = None,
    centro: int | None = None,
    departamento: int | None = None,
    area: int | None = None,
    agencia: int | None = None,
    pagina: PaginaQ = 1,
    por_pagina: PorPaginaQ = 100,
):
    itens = await _publico(
        lambda c: SP.buscar_projetos_pesquisa(
            c, titulo=titulo, objetivos=objetivos, pesquisador=pesquisador, ano=ano, centro_id=centro, departamento_id=departamento, area_id=area, agencia_id=agencia
        )
    )
    return _pag(itens, pagina, por_pagina)


@router.get("/publico/pesquisa/projetos/{projeto_id}", response_model=MP.ProjetoPesquisa, tags=PUB_PESQ,
            summary="Projeto de pesquisa", description="Abre a partir da lista: repita os filtros (ano, título...) que acharam o projeto.")
async def pub_projeto(projeto_id: int, titulo: str | None = None, pesquisador: str | None = None, ano: int | None = None, centro: int | None = None):
    return await _publico(lambda c: SP.obter_projeto_pesquisa(c, projeto_id, titulo=titulo, pesquisador=pesquisador, ano=ano, centro_id=centro))


@router.get("/publico/pesquisa/bases", response_model=list[MP.BasePesquisa], tags=PUB_PESQ,
            summary="Bases/grupos de pesquisa", description="Por nome e/ou coordenador.")
async def pub_bases(nome: str | None = None, coordenador: str | None = None):
    return await _publico(lambda c: SP.buscar_bases_pesquisa(c, nome=nome, coordenador=coordenador))


@router.get("/publico/pesquisa/bolsistas", response_model=list[MP.BolsistaPesquisa], tags=PUB_PESQ,
            summary="Bolsistas de iniciação científica", description="⚠ Na UFBA o SIGAA responde com erro de configuração (502).")
async def pub_bolsistas(discente: str | None = None, orientador: str | None = None, modalidade: int | None = None, centro: int | None = None, curso: int | None = None):
    return await _publico(lambda c: SP.buscar_bolsistas_pesquisa(c, discente=discente, orientador=orientador, modalidade_id=modalidade, centro_id=centro, curso_id=curso))


@router.get("/publico/pesquisa/laboratorios", response_model=list[MP.LaboratorioPesquisaResumo], tags=PUB_PESQ,
            summary="Laboratórios de pesquisa", description="`tipo`: 3 multiusuários, 4 uso restrito. Filtros por nome, ano, servidor, atividade e serviços.")
async def pub_laboratorios(
    nome: str | None = None,
    ano: int | None = None,
    tipo: int | None = None,
    servidor: str | None = None,
    em_atividade: bool | None = None,
    presta_servicos: bool | None = None,
    servico: str | None = None,
):
    return await _publico(
        lambda c: SP.buscar_laboratorios(c, nome=nome, ano=ano, tipo_id=tipo, servidor=servidor, em_atividade=em_atividade, presta_servicos=presta_servicos, servico=servico)
    )


@router.get("/publico/pesquisa/laboratorios/{laboratorio_id}", response_model=MP.LaboratorioPesquisa, tags=PUB_PESQ,
            summary="Laboratório de pesquisa", description="Abre a partir da lista filtrada (nome/ano/tipo).")
async def pub_laboratorio(laboratorio_id: int, nome: str | None = None, ano: int | None = None, tipo: int | None = None):
    return await _publico(lambda c: SP.obter_laboratorio(c, laboratorio_id, nome=nome, ano=ano, tipo_id=tipo))


@router.get("/publico/extensao/acoes", response_model=Pagina[MP.AcaoExtensaoResumo], tags=PUB_PESQ,
            summary="Ações de extensão", description="`tipo`: 1 programa, 2 projeto, 3 curso, 4 evento, 6 produto. Filtros por título, unidade e ano.")
async def pub_acoes(tipo: int | None = None, titulo: str | None = None, unidade: int | None = None, ano: int | None = None, pagina: PaginaQ = 1, por_pagina: PorPaginaQ = 100):
    itens = await _publico(lambda c: SP.buscar_acoes_extensao(c, tipo_id=tipo, titulo=titulo, unidade_id=unidade, ano=ano))
    return _pag(itens, pagina, por_pagina)


@router.get("/publico/extensao/inscricoes-abertas", response_model=list[MP.InscricaoExtensaoAberta], tags=PUB_PESQ,
            summary="Cursos/eventos de extensão com inscrição aberta", description="Só lista (não inscreve). `tipo`: 3 curso, 4 evento.")
async def pub_inscricoes(titulo: str | None = None, tipo: int | None = None):
    return await _publico(lambda c: SP.listar_inscricoes_extensao(c, titulo=titulo, tipo_id=tipo))


@router.get("/publico/extensao/acoes/{acao_id}", response_model=MP.AcaoExtensao, tags=PUB_PESQ,
            summary="Ação de extensão", description="Detalhe (sem filtros = GET direto pelo id).")
async def pub_acao(acao_id: int, tipo: int | None = None, titulo: str | None = None, ano: int | None = None):
    return await _publico(lambda c: SP.obter_acao_extensao(c, acao_id, tipo_id=tipo, titulo=titulo, ano=ano))


@router.get("/publico/cursos-abertos", response_model=Pagina[MP.CursoAbertoTurma], tags=PUB_PESQ,
            summary="Cursos abertos (turmas com conteúdo público)", description="Sem filtros: as últimas publicadas. `departamento` exige `centro`.")
async def pub_cursos_abertos(palavra_chave: str | None = None, centro: int | None = None, departamento: int | None = None, pagina: PaginaQ = 1, por_pagina: PorPaginaQ = 100):
    itens = await _publico(lambda c: SP.buscar_cursos_abertos(c, palavra_chave=palavra_chave, centro_id=centro, departamento_id=departamento))
    return _pag(itens, pagina, por_pagina)


@router.get("/publico/cursos-abertos/centros", response_model=list[MP.CentroCursoAberto], tags=PUB_PESQ,
            summary="Centros com cursos abertos", description="Centros (e departamentos do menu) que aparecem em Cursos Abertos.")
async def pub_centros_abertos():
    return await _publico(SP.listar_centros_cursos_abertos)


@router.get("/publico/cursos-abertos/centros/{centro_id}/departamentos", response_model=list[MP.DepartamentoCursoAberto], tags=PUB_PESQ,
            summary="Departamentos de um centro (cursos abertos)", description="O mesmo AJAX que a tela faz ao trocar o centro.")
async def pub_deptos_abertos(centro_id: int):
    return await _publico(lambda c: SP.listar_departamentos_cursos_abertos(c, centro_id))


@router.get("/publico/cursos-abertos/{turma_id}", response_model=MP.CursoAberto, tags=PUB_PESQ,
            summary="Curso aberto", description="Ementa, docentes, tópicos e materiais de uma turma aberta.")
async def pub_curso_aberto(turma_id: int, palavra_chave: str | None = None):
    return await _publico(lambda c: SP.obter_curso_aberto(c, turma_id, palavra_chave=palavra_chave))
