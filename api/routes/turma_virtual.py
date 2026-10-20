"""Rotas da TURMA VIRTUAL (AVA): /v1/turmas/{turma_id}/... e as agregadas /v1/notas, /v1/frequencia,
/v1/tarefas, /v1/avaliacoes. Somente leitura."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Query, Response

from api.deps import Cliente
from api.seguranca_http import resposta_arquivo, tipo_imagem
from sigaa.models.turma_virtual import (
    Arquivo,
    Avaliacao,
    AvaliacaoAgendada,
    ConteudoTurma,
    Enquete,
    EstatisticasTurma,
    EventoLinhaTempo,
    ForumDetalhe,
    ForumTurma,
    Frequencia,
    FrequenciaResumo,
    GrupoTurma,
    NotasTurma,
    Noticia,
    Participante,
    Participantes,
    PlanoCurso,
    ProgramaComponente,
    Questionario,
    ReferenciaTurma,
    Tarefa,
    TarefaPendente,
    TopicoAula,
    TopicoForumDetalhe,
    TurmaVirtual,
    TurmaVirtualResumo,
    Video,
)
from sigaa.services import turma_virtual as S

router = APIRouter(prefix="/v1", tags=["turma virtual"])

TurmaId = Annotated[
    str,
    Path(
        pattern=r"^(\d+|[0-9A-Fa-f]{40})$",
        description="idTurma numérico do SIGAA (o `turma_id` de GET /v1/turmas). Também aceita o frontEndIdTurma (hash de 40 caracteres).",
    ),
]
Periodo = Annotated[str | None, Query(pattern=r"^\d{4}\.\d$", description="Ano.período (padrão: semestre atual), ex.: 2026.1")]
BINARIO = {200: {"content": {"application/octet-stream": {}}, "description": "O arquivo como o SIGAA entrega."}}


def _tid(turma_id: str) -> int | str:
    return int(turma_id) if turma_id.isdigit() else turma_id


def _download(conteudo: bytes, tipo: str, nome: str) -> Response:
    # nome e tipo vêm do SIGAA: filename saneado e tipo ativo (HTML/SVG/XML/JS) vira octet-stream
    return resposta_arquivo(conteudo, tipo, nome)


# ------------------------------------------------------------------ turmas
@router.get(
    "/turmas-virtuais",
    response_model=list[TurmaVirtualResumo],
    summary="Turmas virtuais que o aluno pode abrir",
    description="Todas as turmas de 'Todas as Turmas Virtuais' (semestre atual + anteriores) com turma_id (idTurma) "
    "e frontEndIdTurma. É a tabela que a API usa pra achar a turma em /v1/turmas/{turma_id}/...",
)
async def turmas_virtuais(cli: Cliente):
    return await cli.executar(S.listar_turmas)


@router.get(
    "/turmas/{turma_id}",
    response_model=TurmaVirtual,
    summary="Turma virtual (página principal)",
    description="Cabeçalho, andamento das aulas, última notícia, tópicos de aula com materiais (arquivos, conteúdos, links), "
    "quadros laterais (notícias, atividades, avaliações, enquete), menu disponível e a lista 'Trocar de Turma'.",
)
async def turma(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.turma(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/aulas", response_model=list[TopicoAula], summary="Tópicos de aula (conteúdo programado)",
            description="Cada tópico com datas, texto, links citados e materiais vinculados (arquivo, conteúdo, referência, vídeo, tarefa...).")
async def aulas(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.aulas(c, _tid(turma_id)))


# ------------------------------------------------------------------ notícias
@router.get("/turmas/{turma_id}/noticias", response_model=list[Noticia], summary="Notícias da turma",
            description="Título, data e id. O texto vem em /noticias/{noticia_id}.")
async def noticias(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.noticias(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/noticias/{noticia_id}", response_model=Noticia, summary="Uma notícia (texto completo)")
async def noticia(cli: Cliente, turma_id: TurmaId, noticia_id: int):
    return await cli.executar(lambda c: S.noticia(c, _tid(turma_id), noticia_id))


# ------------------------------------------------------------------ pessoas e plano
@router.get("/turmas/{turma_id}/participantes", response_model=Participantes, summary="Participantes (docentes e discentes)",
            description="Docentes vêm completos (nome, e-mail, departamento, formação, foto). Dos COLEGAS discentes, por padrão "
            "só nome, curso e papel — privacidade de quem não está usando a API. `?dados_completos=true` devolve tudo que o "
            "SIGAA mostra ao aluno logado (matrícula, e-mail, login, foto, on-line): uso pessoal, não colete em massa.")
async def participantes(cli: Cliente, turma_id: TurmaId, dados_completos: bool = False):
    p = await cli.executar(lambda c: S.participantes(c, _tid(turma_id)))
    for x in p.docentes + p.discentes:
        if x.foto_url:
            x.foto_api = "/v1/fotos?url=" + quote(x.foto_url, safe="")
    if not dados_completos:
        p.discentes = [
            x.model_copy(update={"email": None, "matricula": None, "usuario": None, "foto_url": None, "foto_api": None, "online": None, "campos_extras": {}})
            for x in p.discentes
        ]
    return p


@router.get("/turmas/{turma_id}/docentes", response_model=list[Participante], summary="Docentes da turma")
async def docentes(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.docentes(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/plano-de-curso", response_model=PlanoCurso, summary="Plano de curso",
            description="Metodologia, procedimentos de avaliação, horário de atendimento, cronograma de aulas, avaliações previstas e referências básicas/complementares.")
async def plano_curso(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.plano_curso(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/programa", response_model=ProgramaComponente, summary="Programa do componente",
            description="Ementa, objetivos, conteúdo e bibliografia ('Visualizar Programa'). `disponivel=false` quando o componente não tem programa cadastrado.")
async def programa(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.programa(c, _tid(turma_id)))


# ------------------------------------------------------------------ materiais
@router.get("/turmas/{turma_id}/conteudos", response_model=list[ConteudoTurma], summary="Conteúdos / páginas web")
async def conteudos(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.conteudos(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/conteudos/{conteudo_id}", response_model=ConteudoTurma, summary="Um conteúdo (texto completo)")
async def conteudo(cli: Cliente, turma_id: TurmaId, conteudo_id: int):
    return await cli.executar(lambda c: S.conteudo(c, _tid(turma_id), conteudo_id))


@router.get("/turmas/{turma_id}/referencias", response_model=list[ReferenciaTurma], summary="Referências (sites, livros, artigos)")
async def referencias(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.referencias(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/referencias/{referencia_id}", response_model=ReferenciaTurma, summary="Uma referência (autor, ano, detalhes)")
async def referencia(cli: Cliente, turma_id: TurmaId, referencia_id: int):
    return await cli.executar(lambda c: S.referencia(c, _tid(turma_id), referencia_id))


@router.get("/turmas/{turma_id}/videos", response_model=list[Video], summary="Vídeos")
async def videos(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.videos(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/arquivos", response_model=list[Arquivo], summary="Arquivos publicados pelo docente",
            description="Use o `id` em /arquivos/{arquivo_id} pra baixar.")
async def arquivos(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.arquivos(c, _tid(turma_id)))


@router.get(
    "/turmas/{turma_id}/arquivos/{arquivo_id}",
    summary="Baixar um arquivo",
    description="`arquivo_id` = `id` de /arquivos ou o `id_hash` de um material de /aulas. Devolve o binário com o nome original.",
    response_class=Response,
    responses=BINARIO,
)
async def baixar_arquivo(cli: Cliente, turma_id: TurmaId, arquivo_id: Annotated[str, Path(pattern=r"^(\d+|[0-9A-Fa-f]{20,64})$")]):
    return _download(*await cli.executar(lambda c: S.baixar_arquivo(c, _tid(turma_id), arquivo_id)))


# ------------------------------------------------------------------ atividades
@router.get("/turmas/{turma_id}/tarefas", response_model=list[Tarefa], summary="Tarefas (prazos, envio, nota)")
async def tarefas(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.tarefas(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/questionarios", response_model=list[Questionario], summary="Questionários")
async def questionarios(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.questionarios(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/enquetes", response_model=list[Enquete], summary="Enquetes")
async def enquetes(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.enquetes(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/avaliacoes", response_model=list[Avaliacao], summary="Datas de avaliações")
async def avaliacoes(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.avaliacoes(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/avaliacoes/{avaliacao_id}", response_model=Avaliacao, summary="Uma data de avaliação")
async def avaliacao(cli: Cliente, turma_id: TurmaId, avaliacao_id: int):
    return await cli.executar(lambda c: S.avaliacao(c, _tid(turma_id), avaliacao_id))


# ------------------------------------------------------------------ fórum
@router.get("/turmas/{turma_id}/forum", response_model=list[ForumTurma], summary="Fóruns da turma",
            description="O SIGAA não mostra id numérico de fórum pro aluno: `id` é a posição na lista (estável).")
async def foruns(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.foruns(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/forum/{forum_id}", response_model=ForumDetalhe, summary="Um fórum e seus tópicos")
async def forum(cli: Cliente, turma_id: TurmaId, forum_id: Annotated[int, Path(ge=1)]):
    return await cli.executar(lambda c: S.forum(c, _tid(turma_id), forum_id))


@router.get("/turmas/{turma_id}/forum/{forum_id}/topicos/{topico_id}", response_model=TopicoForumDetalhe, summary="Mensagens de um tópico do fórum")
async def topico_forum(cli: Cliente, turma_id: TurmaId, forum_id: Annotated[int, Path(ge=1)], topico_id: Annotated[int, Path(ge=1)]):
    return await cli.executar(lambda c: S.topico_forum(c, _tid(turma_id), forum_id, topico_id))


@router.get(
    "/turmas/{turma_id}/forum/{forum_id}/topicos/{topico_id}/anexos/{anexo_id}",
    summary="Baixar o anexo de uma mensagem do fórum",
    response_class=Response,
    responses=BINARIO,
)
async def anexo_forum(cli: Cliente, turma_id: TurmaId, forum_id: Annotated[int, Path(ge=1)], topico_id: Annotated[int, Path(ge=1)], anexo_id: int):
    return _download(*await cli.executar(lambda c: S.baixar_anexo_forum(c, _tid(turma_id), forum_id, topico_id, anexo_id)))


# ------------------------------------------------------------------ notas e frequência
@router.get("/turmas/{turma_id}/notas", response_model=NotasTurma, summary="Ver Notas",
            description="Notas por unidade (com as avaliações que compõem cada unidade, nome e peso), reposição, resultado, faltas e situação.")
async def notas(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.notas(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/frequencia", response_model=Frequencia, summary="Frequência",
            description="Situação de cada aula, totais e % do SIGAA, e o cálculo de faltas permitidas/restantes.")
async def frequencia(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.frequencia(c, _tid(turma_id)))


# ------------------------------------------------------------------ outros
@router.get("/turmas/{turma_id}/linha-do-tempo", response_model=list[EventoLinhaTempo], summary="Linha do tempo da turma")
async def linha_tempo(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.linha_tempo(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/grupo", response_model=GrupoTurma, summary="Meu grupo na turma")
async def grupo(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.grupo(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/estatisticas", response_model=EstatisticasTurma, summary="Estatísticas (Situação dos Discentes)")
async def estatisticas(cli: Cliente, turma_id: TurmaId):
    return await cli.executar(lambda c: S.estatisticas(c, _tid(turma_id)))


@router.get("/turmas/{turma_id}/estatisticas/grafico", summary="Gráfico da situação dos discentes (PNG)", response_class=Response,
            responses={200: {"content": {"image/png": {}}}})
async def grafico(cli: Cliente, turma_id: TurmaId):
    conteudo, tipo = await cli.executar(lambda c: S.grafico_estatisticas(c, _tid(turma_id)))
    img = tipo_imagem(tipo)
    if img is None:  # página de erro do SIGAA (HTML) ou SVG não são servidos no domínio da API
        raise HTTPException(404, detail={"codigo": "nao_encontrado", "mensagem": "O SIGAA não devolveu a imagem do gráfico."})
    return Response(conteudo, media_type=img)


# ------------------------------------------------------------------ agregadas
@router.get("/notas", response_model=list[NotasTurma], summary="Notas de todas as turmas do semestre",
            description="Abre cada turma do semestre (ou do `periodo`) e lê 'Ver Notas'. ~3 requisições por turma.")
async def notas_todas(cli: Cliente, periodo: Periodo = None):
    return await cli.executar(lambda c: S.notas_todas(c, periodo))


@router.get("/frequencia", response_model=list[FrequenciaResumo], summary="Frequência de todas as turmas do semestre")
async def frequencia_todas(cli: Cliente, periodo: Periodo = None):
    return await cli.executar(lambda c: S.frequencia_todas(c, periodo))


@router.get("/tarefas", response_model=list[TarefaPendente], summary="Tarefas pendentes (todas as turmas do semestre)",
            description="Tarefas ainda não enviadas, ordenadas pelo prazo. `encerradas=true` inclui as de prazo vencido.")
async def tarefas_pendentes(cli: Cliente, encerradas: Annotated[bool, Query(description="Incluir tarefas com prazo vencido.")] = False):
    return await cli.executar(lambda c: S.tarefas_pendentes(c, incluir_encerradas=encerradas))


@router.get("/avaliacoes", response_model=list[AvaliacaoAgendada], summary="Calendário de provas",
            description="Datas de avaliação de todas as turmas do semestre (ou do `periodo`), em ordem de data.")
async def avaliacoes_todas(cli: Cliente, periodo: Periodo = None):
    return await cli.executar(lambda c: S.avaliacoes_todas(c, periodo))
