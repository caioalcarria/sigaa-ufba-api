"""Rotas do Portal do Discente: /v1/me, /v1/portal, /v1/turmas, /v1/grade-horaria, /v1/atividades,
/v1/atualizacoes, /v1/forum-curso, /v1/modulos, /v1/mensagens, /v1/salas-livres e /v1/horarios."""

from __future__ import annotations

import base64

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response

from api.deps import Cliente
from sigaa.models.portal import (
    Atividade,
    Atualizacao,
    CaixaPostal,
    DadosInstitucionais,
    DadosPessoais,
    FiltrosSalasLivres,
    ForumCurso,
    GradeHoraria,
    Horario,
    ListaTurmas,
    Mensagem,
    Modulos,
    Perfil,
    PortalDiscente,
    RelatorioSalasLivres,
    TabelaHorarios,
    TopicoForumDetalhe,
)
from sigaa.services import portal as S
from sigaa.util import horario as H

router = APIRouter(prefix="/v1", tags=["portal"])

Periodo = Annotated[str | None, Query(pattern=r"^\d{4}\.\d$", description="Ano.período, ex.: 2026.1")]


# ------------------------------------------------------------------ eu
@router.get(
    "/me",
    response_model=DadosInstitucionais,
    summary="Dados institucionais do aluno",
    description="Matrícula, curso (decomposto), nível, status, e-mail institucional (o portal corta e-mails longos), "
    "entrada, unidade, semestre atual e integralização (CH pendentes e %). Fonte: página inicial do Portal do Discente.",
)
async def me(cli: Cliente, incluir_foto: bool = False):
    async def fluxo(c):
        d = await S.me(c)
        if d.foto_url:
            d.foto_api = "/v1/me/foto"
            if incluir_foto:
                try:
                    conteudo, tipo = await S.foto(c)
                    tipo = "image/png" if conteudo[:4] == b"\x89PNG" else "image/gif" if conteudo[:3] == b"GIF" else tipo
                    d.foto_base64 = f"data:{tipo};base64," + base64.b64encode(conteudo).decode()
                except Exception:  # noqa: BLE001 - sem foto não derruba o /me
                    pass
        return d

    return await cli.executar(fluxo)


@router.get(
    "/portal",
    response_model=PortalDiscente,
    summary="Página inicial do Portal do Discente (tudo)",
    description="Numa chamada: dados institucionais, integralização, turmas do semestre (com turma_id), "
    "últimas atualizações das turmas, minhas atividades, notícias, comunidades e prévia do fórum do curso.",
)
async def portal(cli: Cliente):
    return await cli.executar(S.portal)


@router.get(
    "/me/dados-pessoais",
    response_model=DadosPessoais,
    summary="Meus Dados Pessoais",
    description="Documentos, filiação, naturalidade, endereço, contatos, dados bancários e socioeconômicos "
    "cadastrados. A tela do SIGAA é de edição — a API só lê.",
)
async def dados_pessoais(cli: Cliente):
    return await cli.executar(S.dados_pessoais)


@router.get(
    "/me/perfil",
    response_model=Perfil,
    summary="Perfil (descrição, áreas de interesse, Lattes, assinatura)",
    description="Conteúdo de 'Atualizar Foto e Perfil' (perfil.jsf). Só leitura.",
)
async def perfil(cli: Cliente):
    return await cli.executar(S.perfil)


@router.get(
    "/me/foto",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "Sem foto"}},
    summary="Foto do aluno",
    description="A imagem do perfil, como o SIGAA serve.",
)
async def foto(cli: Cliente):
    conteudo, tipo = await cli.executar(S.foto)
    tipo = "image/png" if conteudo[:4] == b"\x89PNG" else tipo
    return Response(content=conteudo, media_type=tipo, headers={"Cache-Control": "private, max-age=3600"})


# --------------------------------------------------------------- turmas
@router.get(
    "/turmas",
    response_model=ListaTurmas,
    summary="Todas as turmas (atuais e anteriores)",
    description="Todas as turmas de todos os semestres, com turma_id (idTurma numérico — o id de "
    "/v1/turmas/{turma_id}/...), frontEndIdTurma, código, turma, CH, local detalhado e horário decodificado. "
    "Filtros: ?periodo=2025.2 e ?atuais=true.",
)
async def turmas(cli: Cliente, periodo: Periodo = None, atuais: Annotated[bool, Query(description="Só as do semestre atual (mais rápido).")] = False):
    return await cli.executar(lambda c: S.turmas(c, periodo=periodo, so_atuais=atuais))


@router.get(
    "/grade-horaria",
    response_model=GradeHoraria,
    summary="Grade horária semanal",
    description="Aulas por dia da semana com hora de início/fim (tabela da UFBA), sala e choques de horário. "
    "Padrão: semestre atual; ?periodo=2026.1 para outro.",
)
async def grade_horaria(cli: Cliente, periodo: Periodo = None):
    return await cli.executar(lambda c: S.grade_horaria(c, periodo))


@router.get(
    "/grade-horaria.ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
    summary="Grade horária em iCalendar (.ics)",
    description="Um evento semanal (RRULE) por bloco de aula, do início ao fim do período, fuso America/Bahia. "
    "Importável no Google Agenda/Outlook/Apple Calendar.",
)
async def grade_ics(cli: Cliente, periodo: Periodo = None):
    ics = await cli.executar(lambda c: S.grade_ics(c, periodo))
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="grade-{periodo or "atual"}.ics"'},
    )


# ------------------------------------------------------ atividades etc.
@router.get(
    "/atividades",
    response_model=list[Atividade],
    summary="Minhas atividades",
    description="Atividades das turmas (avaliações, tarefas, questionários) dos próximos 15 dias e dos últimos 7, "
    "como no quadro 'Minhas atividades' do portal.",
)
async def atividades(cli: Cliente):
    return await cli.executar(S.atividades)


@router.get(
    "/atualizacoes",
    response_model=list[Atualizacao],
    summary="Últimas atualizações das turmas",
    description="O letreiro 'Últimas Atualizações' do portal: data, turma (com turma_id), tipo (Nova Notícia, ...) e título.",
)
async def atualizacoes(cli: Cliente):
    return await cli.executar(S.atualizacoes)


@router.get(
    "/forum-curso",
    response_model=ForumCurso,
    summary="Fórum do curso (tópicos)",
    description="Listagem de tópicos do fórum do curso (todos os alunos do curso + coordenação). Só leitura.",
)
async def forum_curso(cli: Cliente):
    return await cli.executar(S.forum_curso)


@router.get(
    "/forum-curso/topicos/{topico_id}",
    response_model=TopicoForumDetalhe,
    summary="Mensagens de um tópico do fórum do curso",
    description="Abre o tópico pela listagem e devolve as mensagens. Só leitura.",
)
async def topico_forum(cli: Cliente, topico_id: Annotated[int, Path(description="id do tópico (de /v1/forum-curso)")]):
    return await cli.executar(lambda c: S.topico_forum(c, topico_id))


@router.get(
    "/modulos",
    response_model=Modulos,
    summary="Módulos e portais acessíveis",
    description="O painel 'Módulos' do SIGAA: todos os módulos/portais, quais o usuário pode abrir e o link.",
)
async def modulos(cli: Cliente):
    return await cli.executar(S.modulos)


# --------------------------------------------------------- caixa postal
@router.get(
    "/mensagens",
    response_model=CaixaPostal,
    summary="Caixa postal (lista)",
    description="Mensagens da Caixa Postal do SIGAA. ATENÇÃO: na UFBA a caixa postal fica em caixapostal.ufba.br, "
    "que só resolve dentro da rede da universidade — fora dela a rota responde 503 (sigaa_indisponivel).",
)
async def mensagens(cli: Cliente):
    return await cli.executar(S.mensagens)


@router.get(
    "/mensagens/{mensagem_id}",
    response_model=Mensagem,
    summary="Caixa postal (uma mensagem)",
    description="Conteúdo de uma mensagem. Mesma limitação de rede de /v1/mensagens.",
)
async def mensagem(cli: Cliente, mensagem_id: str):
    return await cli.executar(lambda c: S.mensagem(c, mensagem_id))


# ---------------------------------------------------------- salas livres
@router.get(
    "/salas-livres/filtros",
    response_model=FiltrosSalasLivres,
    summary="Opções do relatório de salas livres",
    description="Prédios, dias, turnos e níveis aceitos por /v1/salas-livres (módulo Gerenciamento de salas).",
)
async def filtros_salas_livres(cli: Cliente):
    return await cli.executar(S.filtros_salas_livres)


@router.get(
    "/salas-livres",
    response_model=RelatorioSalasLivres,
    summary="Salas livres por prédio/dia/turno",
    description="'Relatório de Salas Livres' do módulo Gerenciamento de salas: cada linha é uma sala livre num horário "
    "(sala, capacidade, dia, início, fim). Prédio pelo nome ('PAF 1', 'IC') ou id de /v1/salas-livres/filtros.",
)
async def salas_livres(
    cli: Cliente,
    predio: Annotated[str, Query(description="Nome do prédio ('PAF 1') ou id.")],
    dia: Annotated[str | None, Query(description="segunda..sábado ou 2..7")] = None,
    turno: Annotated[str | None, Query(description="M, T, N (ou manha/tarde/noite)")] = None,
    nivel: Annotated[str, Query(description="Nível (G = graduação)")] = "G",
    ano: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    periodo: Annotated[int | None, Query(ge=1, le=4)] = None,
):
    return await cli.executar(lambda c: S.salas_livres(c, predio=predio, dia=dia, turno=turno, nivel=nivel, ano=ano, periodo=periodo))


# -------------------------------------------- horários (públicas, sem login)
@router.get(
    "/horarios/tabela",
    response_model=TabelaHorarios,
    tags=["horarios"],
    summary="Tabela de horários da UFBA (M/T/N)",
    description="Slots M1..M6, T1..T6, N1..N4 com hora de início e fim. Não precisa de login.",
)
async def tabela_horarios():
    return H.tabela_horarios()


@router.get(
    "/horarios/decodificar",
    response_model=Horario,
    tags=["horarios"],
    summary="Decodificar um código de horário do SIGAA",
    description="Ex.: ?codigo=46N12 (19/08/2026 - 19/12/2026) → quarta e sexta 18:30–20:20. Não precisa de login.",
)
async def decodificar(codigo: Annotated[str, Query(min_length=2, max_length=200, description="'2N1234 4N4', '46N12 (19/08/2026 - 19/12/2026)'")]):
    h = H.decodificar(codigo)
    if h is None:
        raise HTTPException(422, detail={"codigo": "horario_vazio", "mensagem": "Código de horário vazio."})
    return h
