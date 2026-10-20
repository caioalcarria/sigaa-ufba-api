"""Planejamento acadêmico — junta três fontes do SIGAA:

* o HISTÓRICO do aluno (o que já foi aprovado, cursado, trancado; equivalências; pendências);
* a ESTRUTURA CURRICULAR do curso dele (Consultas Gerais → Estrutura Curricular);
* a OFERTA de turmas do período (Consultas Gerais → Turma, filtro "Curso" = turmas com reserva
  pro curso — uma busca só traz a oferta inteira).

e devolve a grade curricular marcada, os candidatos à matrícula (aptos? atrasados? quantos
pendentes cada um destrava?), a simulação de uma combinação de turmas (choques, CH máxima,
pré-requisitos, integralização depois) e uma sugestão automática de grade sem choque.

Nada é enviado ao SIGAA além de consultas; a matrícula de verdade continua sendo do aluno.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from ..client import SigaaClient
from ..errors import NaoEncontrado, SessaoExpirada
from ..models.academico import Historico
from ..models.consultas import EstruturaDetalhe, TurmaOferta
from ..models.planejamento import (
    CargaHorariaGestao,
    Choque,
    ComponenteCandidato,
    ComponenteGrade,
    GradeCurricular,
    ItemSimulado,
    PlanejamentoMatricula,
    SemestreGrade,
    SimulacaoMatricula,
    StatusComponente,
    Tentativa,
    TurmaCandidata,
)
from ..parsers.historico_pdf import APROVADO, REPROVADO, TRANCADO
from . import academico, consultas

TTL_ESTRUTURA = 6 * 3600.0
TTL_OFERTA = 15 * 60.0


def _norm(s: str | None) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


# ------------------------------------------------------- pré-requisitos
_TOKEN = re.compile(r"\(|\)|\bE\b|\bOU\b|[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*")


def avaliar_requisito(expr: str | None, cumpridos: set[str]) -> tuple[bool | None, list[str]]:
    """Avalia '( MATA55 ) E ( MATA40 OU MATA57 )' contra o conjunto de códigos cumpridos.
    Devolve (cumpre?, códigos que faltam). Expressão vazia = cumpre."""
    if not expr or not expr.strip():
        return True, []
    toks = _TOKEN.findall(expr.upper())
    if not toks:
        return None, []
    pos = 0

    def ou():
        nonlocal pos
        v, falt = e()
        while pos < len(toks) and toks[pos] == "OU":
            pos += 1
            v2, f2 = e()
            if v or v2:
                v, falt = True, []
            else:
                falt = falt + f2
        return v, falt

    def e():
        nonlocal pos
        v, falt = atomo()
        while pos < len(toks) and toks[pos] == "E":
            pos += 1
            v2, f2 = atomo()
            v, falt = v and v2, falt + f2
        return v, falt

    def atomo():
        nonlocal pos
        if pos >= len(toks):
            return True, []
        t = toks[pos]
        pos += 1
        if t == "(":
            v, falt = ou()
            if pos < len(toks) and toks[pos] == ")":
                pos += 1
            return v, falt
        return (t in cumpridos), ([] if t in cumpridos else [t])

    try:
        v, falt = ou()
        return v, list(dict.fromkeys(falt))
    except Exception:  # noqa: BLE001 - expressão estranha: não arrisca
        return None, []


# ------------------------------------------------------- estrutura do aluno
def _partes_curso(h: Historico) -> tuple[str, str | None]:
    curso = h.vinculo.curso or ""
    nome = _norm(curso.split("/")[0])
    turno = _norm(curso.split(" - ")[-1]) if " - " in curso else None
    return nome, turno


async def estrutura_do_aluno(c: SigaaClient) -> EstruturaDetalhe:
    async def carregar():
        h = await academico.historico(c)
        codigo = (h.vinculo.curriculo or "").split(" ")[0].strip()
        if not codigo:
            raise NaoEncontrado("O histórico não informa o currículo do aluno.")
        nome, turno = _partes_curso(h)
        resumos = await consultas.buscar_estruturas(c, codigo=codigo)
        cands = [r for r in resumos if _norm(r.matriz).startswith(nome)]
        if turno:
            cands = [r for r in cands if _norm(r.matriz).endswith(f"- {turno}")] or cands
        if not cands:
            raise NaoEncontrado(f"Não achei a estrutura {codigo} da matriz '{nome}'.")
        return await consultas.estrutura(c, cands[0].id)

    return await c.memo("estrutura_do_aluno", TTL_ESTRUTURA, carregar)


def _indice_historico(h: Historico):
    aprovados: dict[str, tuple[str, str, float | None]] = {}  # código → (via, período, nota)
    for comp in h.componentes:
        if comp.situacao in APROVADO:
            aprovados[comp.codigo] = (comp.codigo, comp.periodo, comp.nota)
    equiv_de: dict[str, list[str]] = {}
    for eq in h.equivalencias:
        via = [r.codigo for r in eq.atraves_de]
        equiv_de[eq.componente.codigo] = via
        if eq.tipo.lower().startswith("cumpr"):
            orig = next((aprovados.get(v) for v in via if v in aprovados), None)
            aprovados.setdefault(eq.componente.codigo, (" + ".join(via) or "?", orig[1] if orig else "", orig[2] if orig else None))
    cursando = {comp.codigo for comp in h.componentes if comp.cursando}
    pendentes = {p.codigo for p in h.obrigatorios_pendentes}
    return aprovados, equiv_de, cursando, pendentes


def _tentativas(codigo: str, h: Historico, equiv_de: dict[str, list[str]]) -> list[Tentativa]:
    alvos = {codigo, *equiv_de.get(codigo, [])}
    return [
        Tentativa(periodo=x.periodo, codigo_cursado=x.codigo, situacao=x.situacao, nota=x.nota)
        for x in h.componentes
        if x.codigo in alvos or (x.codigo[:-1] == codigo and x.codigo[-1:].isalpha())
    ]


async def grade_curricular(c: SigaaClient) -> GradeCurricular:
    h = await academico.historico(c)
    est = await estrutura_do_aluno(c)
    aprovados, equiv_de, cursando, pendentes = _indice_historico(h)

    def marcar(cd, natureza: str, semestre: int | None) -> ComponenteGrade:
        tent = _tentativas(cd.codigo, h, equiv_de)
        if cd.codigo in aprovados:
            via, per, nota = aprovados[cd.codigo]
            status, cumprido_por = StatusComponente.aprovado, (None if via == cd.codigo else via)
        elif any(t.situacao in APROVADO for t in tent):
            t = next(t for t in tent if t.situacao in APROVADO)
            status, cumprido_por, per, nota = StatusComponente.aprovado, t.codigo_cursado, t.periodo, t.nota
        elif cd.codigo in cursando or any(t.situacao == "MATR" for t in tent):
            status, cumprido_por, per, nota = StatusComponente.cursando, None, None, None
        elif natureza == "OBRIGATORIO" and pendentes and cd.codigo not in pendentes:
            # o próprio SIGAA não lista como pendente → foi cumprido (equivalência/aproveitamento)
            status, cumprido_por, per, nota = StatusComponente.aprovado, "equivalência/aproveitamento", None, None
        else:
            status, cumprido_por, per, nota = StatusComponente.pendente, None, None, None
        return ComponenteGrade(
            id=cd.id,
            codigo=cd.codigo,
            nome=cd.nome,
            carga_horaria=cd.carga_horaria,
            natureza=natureza,
            semestre_ideal=semestre,
            status=status,
            cumprido_por=cumprido_por,
            periodo_conclusao=per or None,
            nota=nota,
            tentativas=tent,
            reprovacoes=sum(t.situacao in REPROVADO for t in tent),
            trancamentos=sum(t.situacao in TRANCADO for t in tent),
        )

    semestres, optativas = [], []
    for nivel in est.niveis:
        if nivel.semestre is None:
            optativas += [marcar(cd, "OPTATIVO", None) for cd in nivel.componentes]
            continue
        comps = [marcar(cd, "OBRIGATORIO" if "OPTAT" not in _norm(cd.natureza) else "OPTATIVO", nivel.semestre) for cd in nivel.componentes]
        semestres.append(
            SemestreGrade(
                nome=nivel.nome,
                semestre=nivel.semestre,
                carga_horaria=sum(x.carga_horaria or 0 for x in comps),
                carga_horaria_cumprida=sum(x.carga_horaria or 0 for x in comps if x.status == StatusComponente.aprovado),
                componentes=comps,
            )
        )
    obrig = [x for s in semestres for x in s.componentes]
    atrasados = [s.semestre for s in semestres if any(x.status == StatusComponente.pendente for x in s.componentes)]
    return GradeCurricular(
        estrutura_id=est.id,
        estrutura_codigo=est.codigo,
        matriz=est.matriz,
        ch_total=est.ch_total,
        ch_obrigatoria=est.ch_obrigatoria,
        ch_optativa=est.ch_optativa,
        ch_complementar=est.ch_complementar,
        ch_maxima_periodo=est.ch_maxima_periodo,
        prazos_semestres={"minimo": est.prazos.minimo, "medio": est.prazos.medio, "maximo": est.prazos.maximo},
        semestres=semestres,
        optativas=optativas,
        obrigatorias_pendentes=sum(x.status != StatusComponente.aprovado for x in obrig),
        obrigatorias_cumpridas=sum(x.status == StatusComponente.aprovado for x in obrig),
        optativas_cursadas_ch=sum(x.carga_horaria or 0 for x in optativas if x.status == StatusComponente.aprovado),
        semestre_mais_atrasado=min(atrasados) if atrasados else None,
    )


# ------------------------------------------------------------------ oferta
async def _curso_id(c: SigaaClient, h: Historico) -> str | None:
    ops = await c.memo("opcoes_turmas", TTL_ESTRUTURA, lambda: consultas.opcoes_turmas(c))
    alvo = _norm(h.vinculo.curso)
    melhores = [o for o in ops.get("cursos", []) if alvo.startswith(_norm(o.nome))]
    return max(melhores, key=lambda o: len(o.nome)).id if melhores else None


async def oferta_do_curso(c: SigaaClient, ano: int | None = None, periodo: int | None = None) -> list[TurmaOferta]:
    h = await academico.historico(c)
    cid = await _curso_id(c, h)
    if cid is None:
        raise NaoEncontrado("Não encontrei o curso do aluno na consulta de turmas.")
    return await c.memo(f"oferta:{cid}:{ano}:{periodo}", TTL_OFERTA, lambda: consultas.buscar_turmas(c, ano=ano, periodo=periodo, curso=cid))


async def _requisitos(c: SigaaClient, comp_id: int | None) -> tuple[str | None, str | None]:
    if not comp_id:
        return None, None

    async def carregar():
        d = await consultas.componente(c, comp_id)
        return d.pre_requisitos.expressao, d.co_requisitos.expressao

    return await c.memo(f"req:{comp_id}", TTL_ESTRUTURA, carregar)


def _turma_candidata(t: TurmaOferta) -> TurmaCandidata:
    livres = (t.capacidade - t.matriculados) if (t.capacidade is not None and t.matriculados is not None) else None
    return TurmaCandidata(
        turma_id=t.id,
        codigo_turma=t.codigo_turma,
        docentes=[d.nome for d in t.docentes],
        horario_codigo=t.horario_codigo,
        horarios=t.horarios,
        local=t.local,
        capacidade=t.capacidade,
        matriculados=t.matriculados,
        vagas_livres=livres,
        situacao=t.situacao,
    )


async def planejamento(
    c: SigaaClient,
    ano: int | None = None,
    periodo: int | None = None,
    considerar_cursando_como_aprovado: bool = True,
    verificar_requisitos: bool = True,
) -> PlanejamentoMatricula:
    h = await academico.historico(c)
    # grade (estrutura curricular) e oferta são navegações independentes: uma sessão do pool pra cada
    grade, oferta = await c.paralelo([grade_curricular, lambda s: oferta_do_curso(s, ano, periodo)])
    aprovados, _, cursando, _ = _indice_historico(h)
    cumpridos = set(aprovados) | {x.codigo for s in grade.semestres for x in s.componentes if x.status == StatusComponente.aprovado}
    cumpridos |= {x.codigo for x in grade.optativas if x.status == StatusComponente.aprovado}
    if considerar_cursando_como_aprovado:
        cumpridos |= cursando

    na_grade: dict[str, ComponenteGrade] = {x.codigo: x for s in grade.semestres for x in s.componentes}
    na_grade.update({x.codigo: x for x in grade.optativas})
    por_codigo: dict[str, list[TurmaOferta]] = defaultdict(list)
    for t in oferta:
        if t.componente_codigo:
            por_codigo[t.componente_codigo].append(t)

    # pré-requisitos de TODOS os pendentes da grade (pra calcular o que cada um destrava)
    pendentes = [x for x in na_grade.values() if x.status == StatusComponente.pendente]
    reqs: dict[str, tuple[str | None, str | None]] = {}
    avisos: list[str] = []
    if verificar_requisitos:
        alvos = [x for x in pendentes if x.codigo in por_codigo or x.natureza == "OBRIGATORIO"]

        def fluxo(x):
            async def f(s: SigaaClient):
                try:
                    return await _requisitos(s, x.id)
                except SessaoExpirada:
                    raise  # o pool reloga/troca de sessão
                except Exception as e:  # noqa: BLE001
                    return e

            return f

        # GET direto por componente (view_painel): espalhado pelas sessões do pool, ao mesmo tempo
        for x, r in zip(alvos, await c.paralelo([fluxo(x) for x in alvos])):
            if isinstance(r, Exception):
                avisos.append(f"Não consegui ler os pré-requisitos de {x.codigo}: {r}")
            else:
                reqs[x.codigo] = r
    desbloqueia: dict[str, list[str]] = defaultdict(list)
    for cod, (pre, _co) in reqs.items():
        for dep in set(_TOKEN.findall((pre or "").upper())) - {"E", "OU", "(", ")"}:
            desbloqueia[dep].append(cod)

    atual = h.vinculo.periodo_letivo_atual
    candidatos = []
    for cod, turmas in por_codigo.items():
        g = na_grade.get(cod)
        if g and g.status != StatusComponente.pendente:
            continue
        if cod in aprovados or (cod in cursando and considerar_cursando_como_aprovado):
            continue
        pre, co = reqs.get(cod, (None, None))
        apto, falt = (avaliar_requisito(pre, cumpridos) if cod in reqs else (None, []))
        candidatos.append(
            ComponenteCandidato(
                codigo=cod,
                nome=(g.nome if g else turmas[0].componente_nome) or cod,
                componente_id=g.id if g else None,
                carga_horaria=g.carga_horaria if g else None,
                natureza=g.natureza if g else "FORA_DA_ESTRUTURA",
                semestre_ideal=g.semestre_ideal if g else None,
                atrasado=bool(g and g.semestre_ideal and atual and g.semestre_ideal < atual),
                pre_requisitos=pre,
                co_requisitos=co,
                apto=apto,
                faltando=falt,
                desbloqueia=sorted(desbloqueia.get(cod, [])),
                reprovacoes_anteriores=g.reprovacoes if g else 0,
                turmas=[_turma_candidata(t) for t in turmas],
            )
        )
    ordem = {"OBRIGATORIO": 0, "OPTATIVO": 1, "FORA_DA_ESTRUTURA": 2}
    candidatos.sort(key=lambda x: (ordem.get(x.natureza, 3), x.apto is False, x.semestre_ideal or 99, -len(x.desbloqueia), x.codigo))
    nao_ofertadas = [x.codigo for x in pendentes if x.natureza == "OBRIGATORIO" and x.codigo not in por_codigo]
    if nao_ofertadas:
        avisos.append("Obrigatórias pendentes SEM turma reservada pro curso neste período: " + ", ".join(sorted(nao_ofertadas)))
    t0 = oferta[0] if oferta else None
    return PlanejamentoMatricula(
        ano=t0.ano if t0 else ano,
        periodo=t0.periodo if t0 else periodo,
        curso=h.vinculo.curso,
        considerou_cursando_como_aprovado=considerar_cursando_como_aprovado,
        ch_maxima_periodo=grade.ch_maxima_periodo,
        ch_pendente=h.carga_horaria,
        candidatos=candidatos,
        total_ofertados_para_o_curso=len(por_codigo),
        avisos=avisos,
    )


# ---------------------------------------------------------------- simulação
_DIAS = {2: "Segunda", 3: "Terça", 4: "Quarta", 5: "Quinta", 6: "Sexta", 7: "Sábado", 1: "Domingo"}


def _slots(t: TurmaCandidata) -> set[tuple[int, str, int]]:
    return {(hh.dia_numero, hh.turno, hh.aula) for hh in t.horarios}


def simular(plano: PlanejamentoMatricula, escolhas: list[tuple[str, str | None]], grade: GradeCurricular) -> SimulacaoMatricula:
    """``escolhas`` = [(código, código_da_turma ou None=primeira), ...] ou [(str(turma_id), None)]."""
    cand = {x.codigo: x for x in plano.candidatos}
    por_id = {str(t.turma_id): (x, t) for x in plano.candidatos for t in x.turmas if t.turma_id}
    aprovados = {x.codigo for s in grade.semestres for x in s.componentes if x.status == StatusComponente.aprovado}
    itens: list[ItemSimulado] = []
    escolhidas: list[tuple[ComponenteCandidato, TurmaCandidata]] = []
    problemas: list[str] = []
    for cod, turma in escolhas:
        if cod in por_id:
            comp, t = por_id[cod]
        else:
            comp = cand.get(cod.upper())
            if comp is None:
                problemas.append(f"{cod}: sem turma ofertada pro curso neste período (ou já cumprido).")
                itens.append(ItemSimulado(codigo=cod.upper(), ja_aprovado=cod.upper() in aprovados))
                continue
            t = next((x for x in comp.turmas if not turma or x.codigo_turma == turma), None)
            if t is None:
                problemas.append(f"{cod}: turma {turma} não existe. Turmas: {', '.join(x.codigo_turma or '?' for x in comp.turmas)}")
                continue
        escolhidas.append((comp, t))
        itens.append(
            ItemSimulado(
                codigo=comp.codigo, turma=t.codigo_turma, turma_id=t.turma_id, carga_horaria=comp.carga_horaria,
                apto=comp.apto, faltando=comp.faltando, natureza=comp.natureza,
            )
        )
        if comp.apto is False:
            problemas.append(f"{comp.codigo}: falta pré-requisito ({', '.join(comp.faltando)}).")
        if t.vagas_livres is not None and t.vagas_livres <= 0:
            problemas.append(f"{comp.codigo} T{t.codigo_turma}: turma lotada ({t.matriculados}/{t.capacidade}).")
    codigos = [c.codigo for c, _ in escolhidas]
    for dup in {x for x in codigos if codigos.count(x) > 1}:
        problemas.append(f"{dup}: escolhido mais de uma vez.")
    # choques
    ocup: dict[tuple[int, str, int], list[str]] = defaultdict(list)
    faixa: dict[tuple[int, str, int], str] = {}
    for comp, t in escolhidas:
        for hh in t.horarios:
            k = (hh.dia_numero, hh.turno, hh.aula)
            ocup[k].append(f"{comp.codigo} T{t.codigo_turma}")
            faixa[k] = f"{hh.turno}{hh.aula} {hh.inicio}-{hh.fim}"
    choques = [Choque(turmas=v, dia=_DIAS.get(k[0], str(k[0])), horario=faixa[k]) for k, v in sorted(ocup.items()) if len(v) > 1]
    for ch in choques:
        problemas.append(f"Choque {ch.dia} {ch.horario}: {' × '.join(ch.turmas)}")
    ch_total = sum(c.carga_horaria or 0 for c, _ in escolhidas)
    excede = bool(plano.ch_maxima_periodo and ch_total > plano.ch_maxima_periodo)
    if excede:
        problemas.append(f"CH {ch_total}h passa do máximo por período ({plano.ch_maxima_periodo}h).")
    # integralização projetada
    def pend(prefixo):
        x = next((c for c in plano.ch_pendente if _norm(c.categoria).startswith(prefixo)), None)
        return x
    ob, op, tot = pend("OBRIG"), pend("OPTAT"), pend("TOTAL")
    ch_ob = sum(c.carga_horaria or 0 for c, _ in escolhidas if c.natureza == "OBRIGATORIO")
    ch_op = sum(c.carga_horaria or 0 for c, _ in escolhidas if c.natureza == "OPTATIVO")
    ob_dep = max(0, (ob.pendente or 0) - ch_ob) if ob else None
    op_dep = max(0, (op.pendente or 0) - ch_op) if op else None
    pct = None
    if tot and tot.exigido and tot.pendente is not None:
        pct = round(100 * (tot.exigido - max(0, tot.pendente - ch_ob - min(ch_op, op.pendente if op and op.pendente else ch_op))) / tot.exigido, 2)
    grade_txt: dict[str, list[str]] = defaultdict(list)
    for comp, t in escolhidas:
        for hh in sorted(t.horarios, key=lambda x: (x.dia_numero, x.turno, x.aula)):
            grade_txt[hh.dia].append(f"{hh.inicio}-{hh.fim} {comp.codigo}")
    return SimulacaoMatricula(
        itens=itens,
        ch_total=ch_total,
        ch_maxima_periodo=plano.ch_maxima_periodo,
        excede_ch_maxima=excede,
        choques=choques,
        problemas=problemas,
        valida=not choques and not excede and not any(i.apto is False for i in itens) and not any("sem turma" in p or "não existe" in p for p in problemas),
        ch_obrigatoria_pendente_depois=ob_dep,
        ch_optativa_pendente_depois=op_dep,
        percentual_integralizado_depois=pct,
        grade={d: sorted(v) for d, v in sorted(grade_txt.items(), key=lambda kv: next((n for n, nome in _DIAS.items() if nome == kv[0]), 9))},
    )


def sugerir(
    plano: PlanejamentoMatricula,
    grade: GradeCurricular,
    ch_maxima: int | None = None,
    turnos: set[str] | None = None,
    incluir_optativas: bool = True,
    evitar_lotadas: bool = True,
) -> SimulacaoMatricula:
    """Guloso: obrigatórias aptas primeiro (atrasadas, semestre ideal menor, mais destravam),
    depois optativas aptas; pega a primeira turma sem choque até bater a CH máxima."""
    limite = ch_maxima or plano.ch_maxima_periodo or 10_000
    ocupado: set[tuple[int, str, int]] = set()
    escolhas: list[tuple[str, str | None]] = []
    ch = 0
    for comp in plano.candidatos:
        if comp.apto is False or (comp.natureza == "OPTATIVO" and not incluir_optativas) or comp.natureza == "FORA_DA_ESTRUTURA":
            continue
        if ch + (comp.carga_horaria or 0) > limite:
            continue
        for t in comp.turmas:
            s = _slots(t)
            if not s or s & ocupado:
                continue
            if turnos and any(hh.turno not in turnos for hh in t.horarios):
                continue
            if evitar_lotadas and t.vagas_livres is not None and t.vagas_livres <= 0:
                continue
            ocupado |= s
            ch += comp.carga_horaria or 0
            escolhas.append((comp.codigo, t.codigo_turma))
            break
    return simular(plano, escolhas, grade)


# ------------------------------------------------------- gestão de horas
async def gestao_horas(c: SigaaClient) -> CargaHorariaGestao:
    h = await academico.historico(c)
    try:
        aut = await academico.atividades_autonomas(c)
        regs = [r for g in aut.grupos for r in g.registros]
    except Exception:  # noqa: BLE001
        regs = []

    def soma(pred):
        return sum(r.carga_horaria or 0 for r in regs if pred(_norm(r.status)))

    comp = next((x for x in h.carga_horaria if _norm(x.categoria).startswith("COMPLEMENT")), None)
    tot = next((x for x in h.carga_horaria if _norm(x.categoria).startswith("TOTAL")), None)
    pct = round(100 * (tot.exigido - tot.pendente) / tot.exigido, 2) if tot and tot.exigido and tot.pendente is not None else None
    dicas = []
    if comp and comp.pendente:
        dicas.append(f"Faltam {comp.pendente}h complementares: registre em 'Registro de Atividades Autônomas' (certificados, cursos, eventos, monitoria, extensão).")
    if comp and comp.integralizado and comp.exigido and comp.integralizado > comp.exigido:
        dicas.append(f"CH complementar já passou do exigido ({comp.integralizado}h de {comp.exigido}h) — o excedente não reduz outras pendências.")
    rej = soma(lambda s: s.startswith("REJEIT") or s.startswith("INDEFER"))
    if rej:
        dicas.append(f"{rej:g}h de atividades foram rejeitadas — veja o motivo no detalhe do registro no SIGAA e reenvie se couber.")
    return CargaHorariaGestao(
        categorias=h.carga_horaria,
        percentual_integralizado=pct,
        complementar_exigida=comp.exigido if comp else None,
        complementar_integralizada=comp.integralizado if comp else None,
        complementar_pendente=comp.pendente if comp else None,
        atividades_aceitas_ch=soma(lambda s: s.startswith("ACEIT") or s.startswith("APROV") or s.startswith("DEFER")),
        atividades_rejeitadas_ch=rej,
        atividades_em_analise_ch=soma(lambda s: s.startswith(("PEND", "SUBMET", "EM ANAL", "CADASTR"))),
        atividades=regs,
        extensao=h.carga_horaria_extensionista,
        extensao_total_ch=sum(x.carga_horaria or 0 for x in h.carga_horaria_extensionista),
        dicas=dicas,
    )
