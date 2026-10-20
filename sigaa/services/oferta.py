"""Oferta HISTÓRICA de turmas por componente — base da previsão de oferta por PARIDADE
(o que abriu em 2026.1 tende a abrir em 2027.1).

Como o SIGAA da UFBA responde (recon de 20/10/2026, ``docs/mapeamento/oferta.md``):

* a Consulta de Turmas (``buscaTurmaBean.popularBuscaGeral``) com o filtro de componente e SEM o filtro
  de ano/período devolve TODOS os períodos que o sistema guarda, numa requisição só;
* o sistema só guarda turmas a partir de **2023.1** (2022.2 e antes: "Nenhuma turma encontrada");
* o filtro "Curso" significa "turma com VAGA RESERVADA pro curso", e a reserva só existe a partir de
  **2025.2** — por isso ``/v1/consultas/turmas?ano=2025&periodo=1&curso=...`` volta vazio, embora as
  turmas de 2025.1 existam (consolidadas). Pra trás de 2025.2, pesquise por componente.

Cache: :func:`turmas_do_componente` e :func:`turmas_reservadas` ficam no L2 compartilhado (dado público,
igual pra todo aluno). O histórico de um período fechado não muda; o TTL de 6 h só limita o atraso de uma
oferta recém-publicada ou das vagas do período corrente (a consulta ao vivo é ``/v1/consultas/turmas``).
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..cache import compartilhado
from ..client import SigaaClient
from ..errors import SessaoExpirada
from ..models.consultas import TurmaOferta
from ..models.oferta import (
    Confianca,
    HistoricoOferta,
    OfertaPeriodo,
    Paridade,
    PrevisaoPeriodo,
    ResumoOferta,
    TurmasDoComponente,
)
from ..parsers import consultas as P
from ..cpu import rodar
from . import consultas

#: primeiro período com turmas no SIGAA da UFBA (antes disso a consulta não acha nada)
PRIMEIRO_PERIODO = (2023, 1)
#: primeiro período com reserva de vagas por curso (o filtro "Curso" da consulta de turmas)
PRIMEIRO_PERIODO_RESERVA = (2025, 2)
TTL_HISTORICO = 6 * 3600.0

_CODIGO = re.compile(r"^[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*$")
_PERIODO = re.compile(r"^(\d{4})\.([1-4])$")

Periodo = tuple[int, int]


# ---------------------------------------------------------------- períodos
def rotulo(p: Periodo) -> str:
    return f"{p[0]}.{p[1]}"


def ler_periodo(texto: str | None, campo: str = "periodo") -> Periodo | None:
    """'2025.1' → (2025, 1). Vazio → None. Formato errado → ``ValueError`` (a rota devolve 422)."""
    if texto is None or not str(texto).strip():
        return None
    m = _PERIODO.match(str(texto).strip())
    if not m:
        raise ValueError(f"'{campo}' deve ser ANO.PERIODO, ex.: 2025.1 (veio '{texto}').")
    return int(m.group(1)), int(m.group(2))


def proximo(p: Periodo) -> Periodo:
    """Próximo período REGULAR: 2026.1 → 2026.2 → 2027.1 (3/4 também vão pro próximo .1/.2)."""
    return (p[0], 2) if p[1] == 1 else (p[0] + 1, 1)


def regulares(desde: Periodo, ate: Periodo) -> list[Periodo]:
    """Períodos x.1 e x.2 de ``desde`` a ``ate`` (inclusive)."""
    out, p = [], (desde if desde[1] in (1, 2) else proximo(desde))
    while p <= ate:
        out.append(p)
        p = proximo(p)
    return out


def normalizar_codigo(codigo: str) -> str:
    cod = (codigo or "").strip().upper()
    if not _CODIGO.match(cod):
        raise ValueError(f"Código de componente inválido: '{codigo}' (ex.: MATC73).")
    return cod


# ----------------------------------------------------------------- SIGAA
def _periodo_do_form(page) -> str | None:
    form = page.form("form")
    if form is None:
        return None
    ano = form.find("input", attrs={"name": "form:inputAno"})
    per = form.find("input", attrs={"name": "form:inputPeriodo"})
    a, p = (ano.get("value") if ano else None), (per.get("value") if per else None)
    return f"{a}.{p}" if a and p and a.isdigit() and p.isdigit() else None


async def _buscar_sem_periodo(c: SigaaClient, extra: dict[str, str]):
    page = await c.menu("buscaTurmaBean.popularBuscaGeral")
    # o checkbox "Ano-Período" vem MARCADO: tirá-lo do POST é o que faz o SIGAA buscar em todos os períodos
    res = await consultas._submit(c, page, "form", extra, botao=("form:buttonBuscar", "Buscar"), remover=("form:checkAnoPeriodo",))
    return page, res


@compartilhado(TTL_HISTORICO, nome="oferta.turmas_do_componente")
async def turmas_do_componente(c: SigaaClient, codigo: str) -> TurmasDoComponente:
    """Todas as turmas de um componente (graduação), de todos os períodos que o SIGAA guarda."""
    cod = normalizar_codigo(codigo)
    page, res = await _buscar_sem_periodo(c, {"form:checkCodigo": "on", "form:inputCodDisciplina": cod})
    turmas = await rodar(P.parse_busca_turmas, res.content)
    # a busca por código é "começa com": MATA37 também traria MATA37A — fica só o código exato
    turmas = [t for t in turmas if (t.componente_codigo or "").upper() == cod]
    return TurmasDoComponente(componente=cod, periodo_atual=_periodo_do_form(page), turmas=turmas)


@compartilhado(TTL_HISTORICO, nome="oferta.turmas_reservadas")
async def turmas_reservadas(c: SigaaClient, codigo: str, curso: int) -> list[int]:
    """Ids das turmas do componente com vaga reservada pro curso (só existe de 2025.2 em diante)."""
    cod = normalizar_codigo(codigo)
    _, res = await _buscar_sem_periodo(
        c, {"form:checkCodigo": "on", "form:inputCodDisciplina": cod, "form:checkCurso": "on", "form:selectCurso": str(int(curso))}
    )
    turmas = await rodar(P.parse_busca_turmas, res.content)
    return sorted({t.id for t in turmas if t.id and (t.componente_codigo or "").upper() == cod})


# ------------------------------------------------------- montagem (pura)
def _per(t: TurmaOferta) -> Periodo | None:
    return (t.ano, t.periodo) if t.ano and t.periodo else None


def _media(xs: list[int]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


PESO_RECENTE = 2  #: peso dos 2 semestres mais recentes de cada paridade na chance


def chance(por_periodo: dict[Periodo, list[TurmaOferta]], mesma: list[Periodo]) -> float | None:
    """Frequência ponderada em ``mesma`` (períodos da mesma paridade, em ordem): os 2 últimos valem
    ``PESO_RECENTE``. Ex.: abriu em 2023.1 e 2024.1, não em 2025.1 e 2026.1 → (1+1)/(1+1+2+2) = 0,33."""
    if not mesma:
        return None
    pesos = [PESO_RECENTE if i >= len(mesma) - 2 else 1 for i in range(len(mesma))]
    return round(sum(w for w, p in zip(pesos, mesma) if por_periodo.get(p)) / sum(pesos), 3)


def resumir(por_periodo: dict[Periodo, list[TurmaOferta]], janela: list[Periodo]) -> ResumoOferta:
    com = [p for p in janela if por_periodo.get(p)]
    imp = [p for p in janela if p[1] == 1]
    par = [p for p in janela if p[1] == 2]
    ki, kp = sum(1 for p in com if p[1] == 1), sum(1 for p in com if p[1] == 2)
    paridade = Paridade.ambos if ki and kp else Paridade.impar if ki else Paridade.par if kp else Paridade.sem_oferta
    todos = sorted(p for p, ts in por_periodo.items() if ts)
    especiais = [rotulo(p) for p in todos if p[1] not in (1, 2)]
    vagas = [sum(t.capacidade for t in por_periodo[p] if t.capacidade is not None) for p in com if any(t.capacidade is not None for t in por_periodo[p])]
    regs = [p for p in todos if p[1] in (1, 2)]
    ci, cp = chance(por_periodo, imp), chance(por_periodo, par)
    ti, tp = (ci or 0) >= 0.5, (cp or 0) >= 0.5
    tendencia = "ambos" if ti and tp else "impar" if ti else "par" if tp else ("irregular" if com else "sem_oferta")
    return ResumoOferta(
        periodos_analisados=[rotulo(p) for p in janela],
        periodos_com_oferta=[rotulo(p) for p in com],
        periodos_sem_oferta=[rotulo(p) for p in janela if not por_periodo.get(p)],
        periodos_especiais=especiais,
        paridade=paridade,
        ofertas_impar=ki,
        ofertas_par=kp,
        impares_analisados=len(imp),
        pares_analisados=len(par),
        frequencia=round(len(com) / len(janela), 3) if janela else None,
        frequencia_impar=round(ki / len(imp), 3) if imp else None,
        frequencia_par=round(kp / len(par), 3) if par else None,
        chance_impar=ci,
        chance_par=cp,
        tendencia=tendencia,
        ultima_oferta=rotulo(com[-1]) if com else (rotulo(regs[-1]) if regs else None),
        primeira_oferta=rotulo(com[0]) if com else (rotulo(regs[0]) if regs else None),
        media_turmas_por_oferta=_media([len(por_periodo[p]) for p in com]),
        media_vagas_por_oferta=_media(vagas),
    )


def prever(por_periodo: dict[Periodo, list[TurmaOferta]], janela: list[Periodo], alvo: Periodo) -> PrevisaoPeriodo:
    """Previsão pro ``alvo`` pela frequência histórica nos semestres da MESMA paridade."""
    ja = por_periodo.get(alvo) or []
    if ja:
        return PrevisaoPeriodo(
            periodo=rotulo(alvo), provavel=True, probabilidade=1.0, confianca=Confianca.alta, ja_publicada=True,
            motivo=f"O SIGAA já publicou {len(ja)} turma(s) em {rotulo(alvo)}.",
        )
    if alvo[1] not in (1, 2):
        return PrevisaoPeriodo(periodo=rotulo(alvo), confianca=Confianca.sem_dados, motivo="Período especial (3/4): a paridade não se aplica.")
    if janela and alvo <= janela[-1]:
        return PrevisaoPeriodo(
            periodo=rotulo(alvo), provavel=False, probabilidade=0.0, confianca=Confianca.alta,
            motivo=f"{rotulo(alvo)} já está publicado e não teve turma deste componente.",
        )
    mesma = [p for p in janela if p[1] == alvo[1]]
    lado = "ímpares (x.1)" if alvo[1] == 1 else "pares (x.2)"
    if not mesma:
        return PrevisaoPeriodo(periodo=rotulo(alvo), confianca=Confianca.sem_dados, motivo=f"Sem semestres {lado} na janela analisada.")
    k = sum(1 for p in mesma if por_periodo.get(p))
    prob = chance(por_periodo, mesma)
    conf = Confianca.alta if len(mesma) >= 3 else Confianca.media if len(mesma) == 2 else Confianca.baixa
    abertos = ", ".join(rotulo(p) for p in mesma if por_periodo.get(p)) or "nenhum"
    recentes = mesma[-2:]
    kr = sum(1 for p in recentes if por_periodo.get(p))
    obs = f" Nos {len(recentes)} mais recentes ({', '.join(rotulo(p) for p in recentes)}): {kr}." if len(mesma) > 2 else ""
    return PrevisaoPeriodo(
        periodo=rotulo(alvo),
        provavel=prob >= 0.5,
        probabilidade=prob,
        confianca=conf,
        motivo=f"Abriu em {k} de {len(mesma)} semestres {lado} observados ({abertos}).{obs} Chance ponderada: {round(prob * 100)}%.",
    )


def montar_historico(
    bruto: TurmasDoComponente,
    desde: Periodo | None = None,
    alvo: Periodo | None = None,
    curso: int | None = None,
    reservadas: set[int] | None = None,
    incluir_turmas: bool = True,
) -> HistoricoOferta:
    """Agrupa as turmas por período, calcula o resumo (paridade, frequência...) e a previsão. Função pura."""
    avisos: list[str] = []
    inicio = max(desde or PRIMEIRO_PERIODO, PRIMEIRO_PERIODO)
    if desde and desde < PRIMEIRO_PERIODO:
        avisos.append(f"O SIGAA da UFBA só tem turmas a partir de {rotulo(PRIMEIRO_PERIODO)}; a janela começa aí.")
    por_periodo: dict[Periodo, list[TurmaOferta]] = defaultdict(list)
    for t in bruto.turmas:
        p = _per(t)
        if p and p >= inicio:
            por_periodo[p].append(t)
    atual = ler_periodo(bruto.periodo_atual) if bruto.periodo_atual else None
    fim_candidatos = [p for p in por_periodo if p[1] in (1, 2)] + ([atual] if atual else [])
    fim = max(fim_candidatos) if fim_candidatos else None
    janela = regulares(inicio, fim) if fim else []
    resumo = resumir(por_periodo, janela)
    alvo = alvo or (proximo(atual) if atual else (proximo(fim) if fim else None))
    previsao = prever(por_periodo, janela, alvo) if alvo else None
    if curso is not None:
        avisos.append(
            f"A reserva de vagas por curso só existe no SIGAA a partir de {rotulo(PRIMEIRO_PERIODO_RESERVA)}: "
            "antes disso `reserva_para_o_curso` vem null (as turmas aparecem do mesmo jeito)."
        )
    periodos = []
    for p in sorted(por_periodo):
        ts = sorted(por_periodo[p], key=lambda t: (t.codigo_turma or ""))
        caps = [t.capacidade for t in ts if t.capacidade is not None]
        mats = [t.matriculados for t in ts if t.matriculados is not None]
        reserva = None
        if curso is not None and reservadas is not None and p >= PRIMEIRO_PERIODO_RESERVA:
            reserva = any(t.id in reservadas for t in ts)
        periodos.append(
            OfertaPeriodo(
                periodo=rotulo(p),
                ano=p[0],
                numero=p[1],
                total_turmas=len(ts),
                total_vagas=sum(caps) if caps else None,
                total_matriculados=sum(mats) if mats else None,
                docentes=list(dict.fromkeys(d.nome for t in ts for d in t.docentes if d.nome)),
                reserva_para_o_curso=reserva,
                turmas=ts if incluir_turmas else [],
            )
        )
    nome = next((t.componente_nome for t in bruto.turmas if t.componente_nome), None)
    if not bruto.turmas:
        avisos.append("Nenhuma turma deste componente no SIGAA (ATIVIDADES como TCC e estágio não têm turma; confira o código).")
    return HistoricoOferta(
        componente=bruto.componente,
        nome=nome,
        desde=rotulo(inicio),
        ate=rotulo(fim) if fim else None,
        curso=curso,
        periodos=periodos,
        resumo=resumo,
        previsao=previsao,
        avisos=avisos,
    )


async def historico(
    c: SigaaClient,
    codigo: str,
    desde: str | None = None,
    alvo: str | None = None,
    curso: int | None = None,
    incluir_turmas: bool = True,
) -> HistoricoOferta:
    """Oferta histórica de UM componente + resumo + previsão pro ``alvo`` (padrão: o próximo período)."""
    d, a = ler_periodo(desde, "desde"), ler_periodo(alvo, "alvo")
    cod = normalizar_codigo(codigo)
    if curso is None:
        return montar_historico(await turmas_do_componente(c, cod), d, a, None, None, incluir_turmas)
    # as duas buscas são independentes: uma sessão do pool pra cada
    bruto, reservadas = await c.paralelo([lambda s: turmas_do_componente(s, cod), lambda s: turmas_reservadas(s, cod, int(curso))])
    return montar_historico(bruto, d, a, curso, set(reservadas), incluir_turmas)


async def historico_tolerante(
    c: SigaaClient,
    codigo: str,
    desde: str | None = None,
    alvo: str | None = None,
    curso: int | None = None,
    incluir_turmas: bool = False,
) -> HistoricoOferta:
    """:func:`historico` pra lote: um componente que falha vira um item com o erro em ``avisos``
    (em vez de derrubar o lote inteiro). Sessão expirada sobe (o pool reloga e refaz)."""
    try:
        return await historico(c, codigo, desde, alvo, curso, incluir_turmas)
    except (SessaoExpirada, ValueError):
        raise
    except Exception as e:  # noqa: BLE001
        inicio = max(ler_periodo(desde, "desde") or PRIMEIRO_PERIODO, PRIMEIRO_PERIODO)
        return HistoricoOferta(
            componente=codigo, desde=rotulo(inicio), curso=curso, periodos=[], resumo=resumir({}, []),
            avisos=[f"Não consegui ler o histórico de {codigo}: {type(e).__name__}: {e}"],
        )
