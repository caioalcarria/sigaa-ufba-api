"""Serviços da TURMA VIRTUAL (AVA): a navegação até cada tela + o parser.

Como uma turma é aberta (ver docs/mapeamento/turma_virtual.md):

* O SIGAA abre a turma virtual com ``frontEndIdTurma`` (um hash estável), nunca com o ``idTurma``.
* A API expõe o ``idTurma`` NUMÉRICO (contrato com a frente 'portal'). A única tela que lista o idTurma de
  TODAS as turmas é a versão mobile (``/sigaa/mobile/touch/ava/turmas_discente.jsf``), que funciona com a
  mesma sessão do desktop. Casamos as duas listas por (período, código, horário com datas).
* Esse mapa idTurma ↔ frontEndIdTurma é dado estável (não é estado de tela JSF), então fica guardado nos
  dados do aluno (``c.dados``, divididos entre as sessões do pool) pra não custar 4 requisições a cada
  chamada. Num id desconhecido o mapa é refeito uma vez.
* As rotas AGREGADAS (notas/frequência/tarefas/avaliações de todas as turmas) abrem cada turma numa
  sessão própria do pool, ao mesmo tempo (``c.paralelo``).
* Toda chamada recomeça do zero: ``turmas.jsf`` → clique no frontEndIdTurma → item do menu lateral. Assim a
  ordem das rotas não importa (abrir outra turma troca o estado JSF da sessão).

SOMENTE LEITURA: nada aqui envia tarefa, responde questionário/enquete, vota, posta no fórum, "segue" tópico
ou altera grupo/perfil.
"""

from __future__ import annotations

import mimetypes
import re
import unicodedata
from datetime import datetime

from sigaa.client import JsfLink, Page, SigaaClient
from sigaa.errors import NaoEncontrado, NavegacaoInvalida, SigaaError
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
from sigaa.parsers import turma_virtual as P

URL_TURMAS = "/sigaa/portais/discente/turmas.jsf"
URL_MOBILE_MENU = "/sigaa/mobile/touch/menu.jsf"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


# ===================================================================== mapa de turmas
async def _lista_mobile(c: SigaaClient) -> list[TurmaVirtualResumo]:
    menu = await c.get(URL_MOBILE_MENU)
    turmas = await c.clicar(menu, "lnkMinhasTurmas")
    if "lnkVerTodas" in turmas.html:
        turmas = await c.clicar(turmas, "lnkVerTodas")
    return P.parse_turmas_mobile(turmas.html)


async def listar_turmas(c: SigaaClient, *, com_ids: bool = True) -> list[TurmaVirtualResumo]:
    """Todas as turmas virtuais do aluno (semestre atual + anteriores), com o idTurma numérico."""
    pag = await c.get(URL_TURMAS)
    lista = P.parse_turmas_anteriores(pag.html)
    m = re.search(r"Semestre atual:\s*(?:<[^>]+>\s*)*(\d{4}\.\d)", pag.html)
    atual = m.group(1) if m else (lista[0].periodo if lista else None)
    for t in lista:
        t.atual = t.periodo == atual
    if com_ids:
        try:
            mobile = await _lista_mobile(c)
        except SigaaError:
            mobile = []
        P.casar_turmas(lista, mobile)
    c.dados["_tv_mapa"] = {t.turma_id: t for t in lista if t.turma_id}
    c.dados["_tv_lista"] = lista
    return lista


async def _resumo(c: SigaaClient, turma_id: int | str) -> TurmaVirtualResumo:
    """Acha a turma pelo idTurma (ou pelo próprio frontEndIdTurma, se vier um hash)."""
    if isinstance(turma_id, str) and not turma_id.isdigit():
        lista = c.dados.get("_tv_lista") or await listar_turmas(c)
        achou = next((t for t in lista if t.front_end_id == turma_id.upper()), None)
        return achou or TurmaVirtualResumo(front_end_id=turma_id.upper())
    tid = int(turma_id)
    mapa = c.dados.get("_tv_mapa")
    if not mapa or tid not in mapa:
        await listar_turmas(c)
        mapa = c.dados.get("_tv_mapa", {})
    if tid not in mapa:
        raise NaoEncontrado(f"Turma {tid} não está entre as turmas virtuais deste aluno.")
    return mapa[tid]


async def abrir_turma(c: SigaaClient, turma_id: int | str) -> Page:
    """Entra na turma virtual (página principal) a partir de 'Todas as Turmas Virtuais' (turmas.jsf),
    que lista as turmas do semestre E as anteriores. Se não achar lá, tenta o portal."""
    r = await _resumo(c, turma_id)
    pag = await c.pagina(URL_TURMAS)  # reaproveita a lista desta sessão enquanto o ViewState dela vale
    link = next((ln for ln in pag.links_jsf() if ln.params.get("frontEndIdTurma") == r.front_end_id), None)
    if link is None and c.reusar_views:
        pag = await c.pagina(URL_TURMAS, reusar=False)
        link = next((ln for ln in pag.links_jsf() if ln.params.get("frontEndIdTurma") == r.front_end_id), None)
    if link is None:
        pag = await c.portal()
        link = next((ln for ln in pag.links_jsf() if ln.params.get("frontEndIdTurma") == r.front_end_id), None)
    if link is None:
        raise NaoEncontrado(f"A turma {turma_id} não aparece na lista de turmas virtuais.")
    tv = await c.clicar(pag, link)
    if "formMenu" not in tv.html and c.reusar_views:
        # a lista reaproveitada pode ter saído da janela de views do servidor: baixa de novo e repete
        pag = await c.pagina(URL_TURMAS, reusar=False)
        link = next((ln for ln in pag.links_jsf() if ln.params.get("frontEndIdTurma") == r.front_end_id), link)
        tv = await c.clicar(pag, link)
    if "formMenu" not in tv.html:
        msgs = P.mensagens(tv.html)
        raise NavegacaoInvalida("Não foi possível abrir a turma virtual" + (f": {msgs[0]}" if msgs else "."))
    return tv


def _link_menu(page: Page, rotulo: str) -> JsfLink | None:
    alvo = _norm(rotulo)
    return next((ln for ln in page.links_jsf() if ln.form_id == "formMenu" and _norm(ln.texto) == alvo), None)


async def abrir_item(c: SigaaClient, turma_id: int | str, *rotulos: str, tv: Page | None = None) -> Page:
    """Abre a turma e clica no item do menu lateral (aceita rótulos alternativos)."""
    tv = tv or await abrir_turma(c, turma_id)
    for rot in rotulos:
        ln = _link_menu(tv, rot)
        if ln is not None:
            return await c.clicar(tv, ln)
    raise NaoEncontrado(f"O item '{rotulos[0]}' não existe no menu desta turma virtual.")


def _link_id(page: Page, id_: int | str, chave: str = "id") -> JsfLink | None:
    alvo = str(id_)
    return next((ln for ln in page.links_jsf() if ln.params.get(chave) == alvo), None)


# ===================================================================== principal
async def turma(c: SigaaClient, turma_id: int | str) -> TurmaVirtual:
    """Página principal: cabeçalho, andamento, última notícia, tópicos de aula com materiais, quadros laterais."""
    r = await _resumo(c, turma_id)
    tv = await abrir_turma(c, turma_id)
    t = P.parse_principal(tv.html, r.front_end_id)
    t.turma_id = r.turma_id
    t.carga_horaria = t.carga_horaria or r.carga_horaria
    t.turma = t.turma or r.turma
    return t


async def aulas(c: SigaaClient, turma_id: int | str) -> list[TopicoAula]:
    return (await turma(c, turma_id)).topicos


# ===================================================================== notícias
async def noticias(c: SigaaClient, turma_id: int | str) -> list[Noticia]:
    return P.parse_noticias((await abrir_item(c, turma_id, "Notícias")).html)


async def noticia(c: SigaaClient, turma_id: int | str, noticia_id: int) -> Noticia:
    pag = await abrir_item(c, turma_id, "Notícias")
    ln = _link_id(pag, noticia_id)
    if ln is None:
        raise NaoEncontrado(f"Notícia {noticia_id} não encontrada nesta turma.")
    n = P.parse_noticia((await c.clicar(pag, ln)).html)
    n.id = n.id or noticia_id
    return n


# ===================================================================== participantes / plano
async def participantes(c: SigaaClient, turma_id: int | str) -> Participantes:
    return P.parse_participantes((await abrir_item(c, turma_id, "Participantes")).html)


async def docentes(c: SigaaClient, turma_id: int | str) -> list[Participante]:
    return (await participantes(c, turma_id)).docentes


async def plano_curso(c: SigaaClient, turma_id: int | str) -> PlanoCurso:
    return P.parse_plano_curso((await abrir_item(c, turma_id, "Plano de Curso")).html)


async def programa(c: SigaaClient, turma_id: int | str) -> ProgramaComponente:
    """'Visualizar Programa'. Quando não há programa o SIGAA fica na tela anterior com uma mensagem de erro."""
    return P.parse_programa((await abrir_item(c, turma_id, "Visualizar Programa")).html)


# ===================================================================== materiais
async def conteudos(c: SigaaClient, turma_id: int | str) -> list[ConteudoTurma]:
    return P.parse_conteudos((await abrir_item(c, turma_id, "Conteúdo/Página web", "Conteúdo")).html)


async def conteudo(c: SigaaClient, turma_id: int | str, conteudo_id: int) -> ConteudoTurma:
    pag = await abrir_item(c, turma_id, "Conteúdo/Página web", "Conteúdo")
    lista = {x.id: x for x in P.parse_conteudos(pag.html)}
    ln = _link_id(pag, conteudo_id)
    if ln is None:
        raise NaoEncontrado(f"Conteúdo {conteudo_id} não encontrado nesta turma.")
    det = P.parse_conteudo((await c.clicar(pag, ln)).html, conteudo_id)
    if conteudo_id in lista:
        det.criado_em = det.criado_em or lista[conteudo_id].criado_em
        det.titulo = det.titulo or lista[conteudo_id].titulo
    return det


async def referencias(c: SigaaClient, turma_id: int | str) -> list[ReferenciaTurma]:
    return P.parse_referencias((await abrir_item(c, turma_id, "Referências")).html)


async def referencia(c: SigaaClient, turma_id: int | str, referencia_id: int) -> ReferenciaTurma:
    pag = await abrir_item(c, turma_id, "Referências")
    base = next((r for r in P.parse_referencias(pag.html) if r.id == referencia_id), None)
    ln = _link_id(pag, referencia_id)
    if ln is None:
        raise NaoEncontrado(f"Referência {referencia_id} não encontrada nesta turma.")
    det = P.parse_referencia((await c.clicar(pag, ln)).html, referencia_id)
    if base:
        det.topico = det.topico or base.topico
        det.url = det.url or base.url
    return det


async def videos(c: SigaaClient, turma_id: int | str) -> list[Video]:
    return P.parse_videos((await abrir_item(c, turma_id, "Vídeos")).html)


async def arquivos(c: SigaaClient, turma_id: int | str) -> list[Arquivo]:
    return P.parse_arquivos((await abrir_item(c, turma_id, "Arquivos")).html)


_RE_COMBINANTE = re.compile(r"([A-Za-z])(768|769|770|771|776|807)")


def _consertar_nome(nome: str) -> str:
    """O SIGAA manda nomes com acento decomposto (NFD) estragado: 'Regulac807a771o' = 'Regulação'
    (letra + código decimal do caractere combinante: 769 agudo, 771 til, 807 cedilha...). Recompõe."""
    nome = _RE_COMBINANTE.sub(lambda m: m.group(1) + chr(int(m.group(2))), nome)
    return unicodedata.normalize("NFC", nome)


def _nome_arquivo(page: Page, base: str | None, padrao: str) -> str:
    """Nome do Content-Disposition (Page.nome_arquivo); sem ele, o nome da listagem + extensão do content-type."""
    if page.nome_arquivo:
        return _consertar_nome(page.nome_arquivo)
    ext = mimetypes.guess_extension((page.content_type or "").split(";")[0].strip()) or ""
    nome = re.sub(r"[^\w.\- ]+", "_", base or padrao).strip() or padrao
    return nome if not ext or nome.lower().endswith(ext) else nome + ext


async def baixar_arquivo(c: SigaaClient, turma_id: int | str, arquivo_id: int | str) -> tuple[bytes, str, str]:
    """Baixa um arquivo: id numérico (menu Arquivos) ou id_hash (material de tópico na página principal).
    Devolve (conteúdo, content-type, nome do arquivo)."""
    aid = str(arquivo_id)
    if aid.isdigit():
        pag = await abrir_item(c, turma_id, "Arquivos")
        nome = next((a.nome for a in P.parse_arquivos(pag.html) if a.id == int(aid)), None)
    else:
        aid = aid.upper()
        pag = await abrir_turma(c, turma_id)
        nome = next((m.titulo for t in P.parse_principal(pag.html).topicos for m in t.materiais if m.id_hash == aid), None)
    ln = _link_id(pag, aid)
    if ln is None:
        raise NaoEncontrado(f"Arquivo {arquivo_id} não encontrado nesta turma.")
    arq = await c.clicar(pag, ln)
    if arq.is_html and "formMenu" in arq.html:
        msgs = P.mensagens(arq.html)
        raise NaoEncontrado(msgs[0] if msgs else f"O SIGAA não entregou o arquivo {arquivo_id}.")
    return arq.content, (arq.content_type or "application/octet-stream"), _nome_arquivo(arq, nome, f"arquivo_{aid}")


# ===================================================================== atividades
async def tarefas(c: SigaaClient, turma_id: int | str) -> list[Tarefa]:
    return P.parse_tarefas((await abrir_item(c, turma_id, "Tarefas")).html)


async def questionarios(c: SigaaClient, turma_id: int | str) -> list[Questionario]:
    return P.parse_questionarios((await abrir_item(c, turma_id, "Questionários")).html)


async def enquetes(c: SigaaClient, turma_id: int | str) -> list[Enquete]:
    return P.parse_enquetes((await abrir_item(c, turma_id, "Enquetes")).html)


async def avaliacoes(c: SigaaClient, turma_id: int | str) -> list[Avaliacao]:
    return P.parse_avaliacoes((await abrir_item(c, turma_id, "Avaliações")).html)


async def avaliacao(c: SigaaClient, turma_id: int | str, avaliacao_id: int) -> Avaliacao:
    pag = await abrir_item(c, turma_id, "Avaliações")
    ln = _link_id(pag, avaliacao_id)
    if ln is None:
        raise NaoEncontrado(f"Avaliação {avaliacao_id} não encontrada nesta turma.")
    return P.parse_avaliacao((await c.clicar(pag, ln)).html, avaliacao_id)


# ===================================================================== fórum
def _links_coluna(page: Page, trecho: str) -> list[JsfLink]:
    """Links de uma coluna em ordem (form:btnViewForum, form:btnViewForumj_id_1, ...)."""
    rx = re.compile(r"'form:%s(?:j_id_\d+)?'" % re.escape(trecho))
    return [ln for ln in page.links_jsf() if rx.search(ln.onclick)]


async def foruns(c: SigaaClient, turma_id: int | str) -> list[ForumTurma]:
    return P.parse_foruns((await abrir_item(c, turma_id, "Fóruns")).html)


async def _abrir_forum(c: SigaaClient, turma_id: int | str, forum_id: int) -> Page:
    pag = await abrir_item(c, turma_id, "Fóruns")
    links = _links_coluna(pag, "btnViewForum")
    if not 1 <= forum_id <= len(links):
        raise NaoEncontrado(f"Fórum {forum_id} não existe nesta turma ({len(links)} fórum(ns)).")
    return await c.clicar(pag, links[forum_id - 1])


async def _abrir_topico(c: SigaaClient, turma_id: int | str, forum_id: int, topico_id: int) -> tuple[Page, Page]:
    pag = await _abrir_forum(c, turma_id, forum_id)
    links = _links_coluna(pag, "btnView")
    if not 1 <= topico_id <= len(links):
        raise NaoEncontrado(f"Tópico {topico_id} não existe no fórum {forum_id}.")
    return pag, await c.clicar(pag, links[topico_id - 1])


async def forum(c: SigaaClient, turma_id: int | str, forum_id: int) -> ForumDetalhe:
    return P.parse_forum((await _abrir_forum(c, turma_id, forum_id)).html, forum_id)


async def topico_forum(c: SigaaClient, turma_id: int | str, forum_id: int, topico_id: int) -> TopicoForumDetalhe:
    """Mensagens de um tópico. Só LÊ: não clica em 'Seguir tópico' nem responde."""
    pag, top = await _abrir_topico(c, turma_id, forum_id, topico_id)
    detalhe = P.parse_forum(pag.html, forum_id)
    res = P.parse_topico_forum(top.html, forum_id, topico_id)
    if topico_id <= len(detalhe.topicos):
        base = detalhe.topicos[topico_id - 1]
        base.respostas = len(res.respostas)
        res.topico = base
    return res


async def baixar_anexo_forum(c: SigaaClient, turma_id: int | str, forum_id: int, topico_id: int, anexo_id: int) -> tuple[bytes, str, str]:
    _, top = await _abrir_topico(c, turma_id, forum_id, topico_id)
    ln = _link_id(top, anexo_id, "idArquivo")
    if ln is None:
        raise NaoEncontrado(f"Anexo {anexo_id} não encontrado no tópico.")
    arq = await c.clicar(top, ln)
    if arq.is_html and "formMenu" in arq.html:
        raise NaoEncontrado(f"O SIGAA não entregou o anexo {anexo_id}.")
    return arq.content, (arq.content_type or "application/octet-stream"), _nome_arquivo(arq, None, f"anexo_{anexo_id}")


# ===================================================================== notas / frequência
async def notas(c: SigaaClient, turma_id: int | str) -> NotasTurma:
    r = await _resumo(c, turma_id)
    n = P.parse_notas((await abrir_item(c, turma_id, "Ver Notas")).html)
    n.turma_id = r.turma_id
    n.codigo = n.codigo or r.codigo
    n.nome = n.nome or r.nome
    n.periodo = n.periodo or r.periodo
    return n


async def frequencia(c: SigaaClient, turma_id: int | str) -> Frequencia:
    r = await _resumo(c, turma_id)
    f = P.parse_frequencia((await abrir_item(c, turma_id, "Frequência")).html)
    f.turma_id = r.turma_id
    return f


# ===================================================================== outros
async def linha_tempo(c: SigaaClient, turma_id: int | str) -> list[EventoLinhaTempo]:
    return P.parse_linha_tempo((await abrir_item(c, turma_id, "Linha do Tempo")).html)


async def grupo(c: SigaaClient, turma_id: int | str) -> GrupoTurma:
    return P.parse_grupo((await abrir_item(c, turma_id, "Ver Grupo")).html)


async def estatisticas(c: SigaaClient, turma_id: int | str) -> EstatisticasTurma:
    return P.parse_estatisticas((await abrir_item(c, turma_id, "Situação dos Discentes", "Estatísticas")).html)


async def grafico_estatisticas(c: SigaaClient, turma_id: int | str) -> tuple[bytes, str]:
    """PNG do gráfico 'Situação dos Discentes' (gerado pelo cewolf; o link só vale na sessão)."""
    pag = await abrir_item(c, turma_id, "Situação dos Discentes", "Estatísticas")
    url = P.url_grafico_estatisticas(pag.html)
    if not url:
        raise NaoEncontrado("Esta turma não tem gráfico de estatísticas.")
    img = await c.get(url)
    return img.content, img.content_type or "image/png"


# ===================================================================== agregadas
TTL_LISTA = 600  # a lista de turmas do aluno quase não muda; 10 min poupa 4 viagens por rota agregada


async def _do_periodo(c: SigaaClient, periodo: str | None = None) -> list[TurmaVirtualResumo]:
    lista = await c.memo("tv_lista", TTL_LISTA, lambda: listar_turmas(c))
    return [t for t in lista if (t.periodo == periodo if periodo else t.atual)]


async def _por_turma(c: SigaaClient, turmas: list[TurmaVirtualResumo], fn, *, pular_nao_encontrado: bool = False) -> list:
    """``fn(sessao, turma)`` pra cada turma, em PARALELO (uma sessão do pool por turma)."""

    def fluxo(t):
        async def f(s: SigaaClient):
            try:
                return await fn(s, t)
            except NaoEncontrado:
                if pular_nao_encontrado:
                    return None
                raise

        return f

    return await c.paralelo([fluxo(t) for t in turmas])


async def notas_todas(c: SigaaClient, periodo: str | None = None) -> list[NotasTurma]:
    """Notas de todas as turmas do semestre atual (ou do ``periodo`` pedido)."""
    return await _por_turma(c, await _do_periodo(c, periodo), lambda s, t: notas(s, t.turma_id or t.front_end_id))


async def frequencia_todas(c: SigaaClient, periodo: str | None = None) -> list[FrequenciaResumo]:
    turmas = await _do_periodo(c, periodo)
    freqs = await _por_turma(c, turmas, lambda s, t: frequencia(s, t.turma_id or t.front_end_id))
    return [FrequenciaResumo(turma_id=t.turma_id, codigo=t.codigo, nome=t.nome, frequencia=f) for t, f in zip(turmas, freqs)]


async def tarefas_pendentes(c: SigaaClient, *, incluir_encerradas: bool = False) -> list[TarefaPendente]:
    """Tarefas das turmas do semestre atual ainda não enviadas (com prazo aberto, a menos que incluir_encerradas)."""
    agora = datetime.now()
    out = []
    turmas = await _do_periodo(c)
    listas = await _por_turma(c, turmas, lambda s, t: tarefas(s, t.turma_id or t.front_end_id), pular_nao_encontrado=True)
    for t, lista in zip(turmas, listas):
        for tf in lista or []:
            if tf.enviada:
                continue
            if not incluir_encerradas and tf.fim and tf.fim < agora:
                continue
            out.append(TarefaPendente(**tf.model_dump(), turma_id=t.turma_id, turma_codigo=t.codigo, turma_nome=t.nome))
    out.sort(key=lambda x: x.fim or datetime.max)
    return out


async def avaliacoes_todas(c: SigaaClient, periodo: str | None = None) -> list[AvaliacaoAgendada]:
    """Calendário de provas: datas de avaliação de todas as turmas do semestre, em ordem de data."""
    out = []
    turmas = await _do_periodo(c, periodo)
    listas = await _por_turma(c, turmas, lambda s, t: avaliacoes(s, t.turma_id or t.front_end_id), pular_nao_encontrado=True)
    for t, lista in zip(turmas, listas):
        for a in lista or []:
            out.append(AvaliacaoAgendada(**a.model_dump(), turma_id=t.turma_id, turma_codigo=t.codigo, turma_nome=t.nome))
    out.sort(key=lambda x: (x.data is None, x.data or datetime.min.date(), x.hora or ""))
    return out
