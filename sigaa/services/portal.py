"""Serviços do Portal do Discente: a NAVEGAÇÃO (quais telas, quais cliques) + os parsers.

Todas as telas daqui são de CONSULTA. "Meus Dados Pessoais" e perfil.jsf são telas de
EDIÇÃO: o serviço só abre e lê — nunca submete o formulário. No fórum do curso, nunca clicar
em "Cadastrar novo tópico", "Remover" nem nas bandeirinhas de seguir tópico.
"""

from __future__ import annotations

import re
import unicodedata

from sigaa.client import Page, SigaaClient, form_fields
from sigaa.errors import NaoEncontrado, NavegacaoInvalida, SigaaError, SistemaIndisponivel
from sigaa.models.portal import (
    Atividade,
    Atualizacao,
    CaixaPostal,
    DadosInstitucionais,
    DadosPessoais,
    FiltrosSalasLivres,
    ForumCurso,
    GradeHoraria,
    ListaTurmas,
    Mensagem,
    Modulos,
    Perfil,
    PortalDiscente,
    RelatorioSalasLivres,
    TopicoForumDetalhe,
    Turma,
)
from sigaa.parsers import portal as P
from sigaa.util.horario import dia_por_nome, gerar_ics, montar_grade

URL_TURMAS = "/sigaa/portais/discente/turmas.jsf"
URL_PERFIL = "/sigaa/portais/discente/perfil.jsf"
URL_MODULOS = "/sigaa/verMenuPrincipal.do?dialog=true"
URL_CAIXA_POSTAL = "/sigaa/abrirCaixaPostal.jsf?sistema=2"
URL_MOBILE_MENU = "/sigaa/mobile/touch/menu.jsf"
URL_GERENCIADOR_SALAS = "/sigaa/verMenuGerenciadorSalas.do"


# ------------------------------------------------------------------ portal
async def portal(c: SigaaClient) -> PortalDiscente:
    """Página inicial do Portal do Discente, tudo junto."""
    page = await c.portal()
    return P.parse_portal(page.html)


async def me(c: SigaaClient) -> DadosInstitucionais:
    return (await portal(c)).dados


async def atividades(c: SigaaClient) -> list[Atividade]:
    return (await portal(c)).atividades


async def atualizacoes(c: SigaaClient) -> list[Atualizacao]:
    return (await portal(c)).atualizacoes


# ------------------------------------------------------- dados pessoais/perfil
async def dados_pessoais(c: SigaaClient) -> DadosPessoais:
    """Portal → 'Meus Dados Pessoais' (commandLink meusDadosPessoais). SÓ LEITURA."""
    inicio = await c.portal()
    page = await c.clicar(inicio, "meusDadosPessoais")
    if page.form("formDiscente") is None and "dados pessoais" not in page.html.lower():
        raise NavegacaoInvalida("A tela 'Meus Dados Pessoais' não abriu.")
    return P.parse_dados_pessoais(page.html)


async def perfil(c: SigaaClient) -> Perfil:
    """Portal → 'Atualizar Foto e Perfil' (perfil.jsf). SÓ LEITURA."""
    await c.portal()
    page = await c.get(URL_PERFIL)
    return P.parse_perfil(page.html)


async def foto(c: SigaaClient) -> tuple[bytes, str]:
    """Bytes da foto do perfil (o mesmo /shared/verFoto?idFoto=..&key=.. do portal)."""
    page = await c.portal()
    url = P.parse_portal(page.html).dados.foto_url
    if not url:
        raise NaoEncontrado("O aluno não tem foto cadastrada.")
    img = await c.get(url)
    tipo = img.content_type.split(";")[0] or "image/jpeg"
    if not tipo.startswith("image/"):
        raise NaoEncontrado("O SIGAA não devolveu uma imagem para a foto.")
    return img.content, tipo


# -------------------------------------------------------------------- turmas
async def _turmas_mobile(c: SigaaClient, semestre_atual: str | None) -> list[Turma]:
    """Interface mobile (mesma sessão do portal clássico): menu.jsf → 'Minhas Turmas' → 'Ver Todas'.
    É a ÚNICA tela que lista todas as turmas com o idTurma numérico."""
    menu = await c.get(URL_MOBILE_MENU)
    minhas = await c.clicar(menu, "lnkMinhasTurmas")
    try:
        todas = await c.clicar(minhas, "lnkVerTodas")
    except NavegacaoInvalida:
        todas = minhas  # sem 'Ver Todas' (poucas turmas): a própria lista basta
    return P.parse_turmas_mobile(todas.html, semestre_atual)


async def turmas(c: SigaaClient, periodo: str | None = None, so_atuais: bool = False) -> ListaTurmas:
    """Todas as turmas de todos os semestres.

    Fontes (casadas por idTurma/frontEndIdTurma/período+código):
    1. portal (turmas do semestre: idTurma via ``<td id="linha_<idTurma>">``, local);
    2. /sigaa/portais/discente/turmas.jsf (código, turma, CH, horário, frontEndIdTurma);
    3. mobile 'Turmas do Discente' (idTurma de TODAS, local detalhado, nível).
    Se a tela mobile falhar, as turmas antigas vêm sem turma_id (só front_end_id).
    """
    inicio = await c.portal()
    pd = P.parse_portal(inicio.html)
    atual = pd.dados.semestre_atual
    if so_atuais:
        fontes: list[list[Turma]] = []
    else:
        classico = await c.get(URL_TURMAS)
        fontes = [P.parse_turmas_classico(classico.html)]
    try:
        fontes.append(await _turmas_mobile(c, atual))
    except SigaaError:
        pass
    fontes.append(pd.turmas_semestre)
    lista = P.mesclar_turmas(*fontes)
    if so_atuais:
        lista = [t for t in lista if t.atual]
    if periodo:
        lista = [t for t in lista if t.periodo == periodo]
    periodos = list(dict.fromkeys(t.periodo for t in lista if t.periodo))
    return ListaTurmas(semestre_atual=atual, total=len(lista), periodos=periodos, turmas=lista)


async def grade_horaria(c: SigaaClient, periodo: str | None = None) -> GradeHoraria:
    """Grade semanal do período (padrão: semestre atual)."""
    lt = await turmas(c, periodo=periodo, so_atuais=periodo is None)
    per = periodo or lt.semestre_atual
    return montar_grade([t for t in lt.turmas if t.periodo == per] or lt.turmas, per)


async def grade_ics(c: SigaaClient, periodo: str | None = None) -> str:
    lt = await turmas(c, periodo=periodo, so_atuais=periodo is None)
    per = periodo or lt.semestre_atual
    sel = [t for t in lt.turmas if t.periodo == per] or lt.turmas
    return gerar_ics(sel, nome_calendario=f"Aulas {per or ''}".strip())


# --------------------------------------------------------------------- fórum
async def _abrir_forum(c: SigaaClient) -> Page:
    inicio = await c.portal()
    try:
        return await c.clicar(inicio, "listarTopicosForum")
    except NavegacaoInvalida:
        # variação: só o botão-imagem 'form_links:forumCursos' (input type=image)
        return await c.submit(inicio, "form_links", {"form_links:forumCursos.x": "1", "form_links:forumCursos.y": "1"})


async def forum_curso(c: SigaaClient) -> ForumCurso:
    """Portal → 'Visualizar todos os tópicos para este fórum' (/sigaa/graduacao/ForumCurso/listar.jsf)."""
    return P.parse_forum_curso((await _abrir_forum(c)).html)


async def topico_forum(c: SigaaClient, topico_id: int) -> TopicoForumDetalhe:
    lista = await _abrir_forum(c)
    alvo = None
    for ln in lista.links_jsf():
        if any(v == str(topico_id) for v in ln.params.values()):
            txt = (ln.texto or "").lower()
            if any(p in txt for p in ("remov", "cadastr", "seguir", "excluir")) or "remov" in ln.onclick.lower():
                continue
            alvo = ln
            break
    if alvo is None:
        raise NaoEncontrado(f"Tópico {topico_id} não está no fórum do curso.")
    page = await c.clicar(lista, alvo)
    det = P.parse_topico_forum(page.html)
    det.id = topico_id
    return det


# ------------------------------------------------------------------- módulos
async def modulos(c: SigaaClient) -> Modulos:
    """Painel 'Módulos' do cabeçalho (GET /sigaa/verMenuPrincipal.do?dialog=true)."""
    await c.portal()
    page = await c.get(URL_MODULOS)
    return P.parse_modulos(page.html)


# -------------------------------------------------------------- caixa postal
_MSG_CXP = (
    "A Caixa Postal do SIGAA UFBA redireciona para caixapostal.ufba.br, um host que só existe "
    "no DNS interno da UFBA (fora da rede da universidade nem o navegador abre)."
)


async def _abrir_caixa(c: SigaaClient) -> Page:
    await c.portal()
    try:
        page = await c.get(URL_CAIXA_POSTAL)
    except SistemaIndisponivel as e:
        raise SistemaIndisponivel(_MSG_CXP) from e
    if "caixapostal" not in page.url and "cxpostal" not in page.url:
        raise SistemaIndisponivel(_MSG_CXP)
    return page


async def mensagens(c: SigaaClient) -> CaixaPostal:
    return P.parse_caixa_postal((await _abrir_caixa(c)).html)


async def mensagem(c: SigaaClient, mensagem_id: str) -> Mensagem:
    caixa = await _abrir_caixa(c)
    for ln in caixa.links_jsf():
        if mensagem_id in ln.params.values():
            msg = P.parse_mensagem((await c.clicar(caixa, ln)).html)
            msg.id = mensagem_id
            return msg
    raise NaoEncontrado(f"Mensagem {mensagem_id} não encontrada na caixa de entrada.")


# -------------------------------------------------------------- salas livres
def _sem_acento(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn").lower().strip()


async def _form_salas_livres(c: SigaaClient) -> Page:
    """Módulos → Gerenciamento de salas → 'Relatório de Salas Livres'."""
    menu = await c.get(URL_GERENCIADOR_SALAS)
    page = await c.clicar(menu, "Relatório de Salas Livres")
    if page.form("formularioDistribuicao") is None:
        raise NavegacaoInvalida("O formulário de salas livres não abriu.")
    return page


async def filtros_salas_livres(c: SigaaClient) -> FiltrosSalasLivres:
    return P.parse_filtros_salas_livres((await _form_salas_livres(c)).html)


def _resolver(valor: str | int | None, opcoes, extra: dict[str, str] | None = None) -> str | None:
    if valor is None or valor == "":
        return None
    v = str(valor).strip()
    if extra and _sem_acento(v) in extra:
        return extra[_sem_acento(v)]
    for o in opcoes:
        if v == o.valor:
            return o.valor
    for o in opcoes:
        if _sem_acento(v) == _sem_acento(o.rotulo):
            return o.valor
    raise NaoEncontrado(f"Opção '{valor}' não existe. Válidas: {', '.join(o.rotulo for o in opcoes)}")


async def salas_livres(
    c: SigaaClient,
    predio: str | int,
    dia: str | int | None = None,
    turno: str | None = None,
    nivel: str = "G",
    ano: int | None = None,
    periodo: int | None = None,
) -> RelatorioSalasLivres:
    """Relatório de Salas Livres. O select de prédio dispara um AJAX a4j (que carrega as salas
    no servidor) — sem ele o 'Gerar Relatório' volta pro formulário sem resultado."""
    page = await _form_salas_livres(c)
    filtros = P.parse_filtros_salas_livres(page.html)
    form = page.form("formularioDistribuicao")
    pref = "formularioDistribuicao:"
    dados = form_fields(form)
    v_predio = _resolver(predio, filtros.predios)
    dia_num = None
    if dia is not None:
        dia_num = str(dia) if str(dia).isdigit() else str(dia_por_nome(str(dia)) or "")
        dia_num = _resolver(dia_num or str(dia), filtros.dias)
    v_turno = _resolver(turno, filtros.turnos, {"m": "1", "t": "2", "n": "3", "manha": "1", "tarde": "2", "noite": "3"})
    v_nivel = _resolver(nivel, filtros.niveis)
    dados[pref + "selectNivelTurma"] = v_nivel or "G"
    if ano:
        dados[pref + "inputAno"] = str(ano)
    if periodo:
        dados[pref + "inputPeriodo"] = str(periodo)
    if dia_num:
        dados[pref + "checkDiaSemana"] = "on"
        dados[pref + "selectDiaSemana"] = dia_num
    if v_turno:
        dados[pref + "checkTurno"] = "on"
        dados[pref + "selectTurno"] = v_turno
    if v_predio:
        dados[pref + "checkPredio"] = "on"
        dados[pref + "selectPredio"] = v_predio
    action = form.get("action") or page.url
    # 1) AJAX do select de prédio (a4j: parâmetro = id do a4j:support, extraído do onchange)
    sel = form.find("select", attrs={"name": pref + "selectPredio"})
    m = re.search(r"'parameters':\{'([^']+)'", (sel.get("onchange") if sel is not None else "") or "")
    if v_predio and m:
        aj = dict(dados)
        aj["AJAXREQUEST"] = "_viewRoot"
        aj[m.group(1)] = m.group(1)
        await c.post(action, aj)
    # 2) Gerar Relatório
    botao = next(
        (i for i in form.find_all("input", attrs={"type": "submit"}) if "gerar" in (i.get("value") or "").lower()),
        None,
    )
    if botao is None:
        raise NavegacaoInvalida("Botão 'Gerar Relatório' não encontrado.")
    dados[botao["name"]] = botao["value"]
    res = await c.post(action, dados)
    rel = P.parse_salas_livres(res.html)
    if not rel.salas and not P.resultado_salas_vazio(res.html) and res.form("formularioDistribuicao") is not None:
        erro = res.soup.select_one(".erros, #painel-erros")
        raise NavegacaoInvalida(erro.get_text(" ", strip=True) if erro else "O SIGAA não gerou o relatório.")
    rel.filtros = {
        k: v
        for k, v in {
            "predio": next((o.rotulo for o in filtros.predios if o.valor == v_predio), None),
            "dia": next((o.rotulo for o in filtros.dias if o.valor == dia_num), None),
            "turno": next((o.rotulo for o in filtros.turnos if o.valor == v_turno), None),
            "nivel": next((o.rotulo for o in filtros.niveis if o.valor == (v_nivel or "G")), None),
            "ano_periodo": f"{dados.get(pref + 'inputAno')}.{dados.get(pref + 'inputPeriodo')}",
        }.items()
        if v
    }
    return rel
