#!/usr/bin/env python3
"""Bancada de performance da sigaa-api: latência FRIA × QUENTE por rota e CARGA (N alunos × C conexões).

⚠️ Só roda contra uma API LOCAL apontada pro SIGAA SIMULADO (bench/mock_sigaa.py). Antes de medir, o bench
pergunta à API (GET /v1/status) pra onde ela aponta e ABORTA se não for 127.0.0.1/localhost — nunca manda
carga ao SIGAA real.

Fases:
  0. descoberta  — 1 login, acha {turma_id} (/v1/turmas-virtuais, senão /v1/turmas) e {unidade} (/v1/publico/unidades).
  1. fria×quente — por rota e por amostra: login NOVO (aluno novo) → 1ª chamada (fria) → K repetições (quentes) → logout.
                   Rotas públicas não precisam de login; como o cache delas pode ser COMPARTILHADO, só a 1ª amostra
                   fria é garantidamente fria.
  2. carga       — por rota-alvo × C × N: N logins ANTES (não contam; até --login-paralelo por vez), depois R
                   requisições (ou --duracao s) com C em voo, distribuídas em rodízio entre os N tokens.

Uso:
  .venv/bin/python bench/bench.py --api http://127.0.0.1:8112 --rapido
  .venv/bin/python bench/bench.py --api http://127.0.0.1:8112 --worktree ~/PROJECTS/UFBA/sigaa-api-perf-cache \\
      --rotulo cache --saida-md /tmp/b.md --saida-json /tmp/b.json

Cliente HTTP: aiohttp (o httpx.AsyncClient desaba acima de ~50 conexões simultâneas e o bench mediria o
PRÓPRIO cliente). Rode com a .venv da BANCADA (ela tem o aiohttp; o bench é só cliente HTTP, mede qualquer
worktree). `--calibrar-cliente` mostra o teto do gerador batendo direto no mock com o mesmo C.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from typing import Any
from urllib.parse import urlsplit

import aiohttp

ROTAS_PADRAO = [
    "/v1/historico",
    "/v1/indices",
    "/v1/integralizacao",
    "/v1/matricula",
    "/v1/turmas",
    "/v1/portal",
    "/v1/me",
    "/v1/grade-curricular",
    "/v1/planejamento/matricula",
    "/v1/notas",
    "/v1/frequencia",
    "/v1/turmas/{turma_id}/notas",
    "/v1/turmas/{turma_id}",
    "/v1/documentos/comprovante-inscricao",
    # públicas (sem login)
    "/v1/publico/turmas?ano={ano}&periodo={periodo}&unidade={unidade}",
    "/v1/publico/componentes/{componente_id}",
    "/v1/publico/cursos/{curso_id}",
    "/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id}",
    "/v1/publico/cursos/{curso_id}/calendario",
]
ROTAS_CARGA_PADRAO = ["/v1/historico", "/v1/turmas", "/v1/notas", "/v1/publico/componentes/{componente_id}"]

#: valores dos {placeholders} — os padrões são ids que EXISTEM nas fixtures do mock (docs/bench.md).
#: Prioridade: --param > /__mock/config (chaves iguais, ou dentro de "params"/"ids") > descoberta > estes.
PARAMS_PADRAO = {
    "ano": "2026",
    "periodo": "2",
    "codigo": "MATA37",
    "componente_id": "44697",  # MATA37
    "curso_id": "1876885",  # SI
    "estrutura_id": "2421505",  # G20251X
    "unidade": "1114",  # DCC (vazio = descobre em /v1/publico/unidades)
    "turma_id": "",  # descoberto em /v1/turmas-virtuais ou /v1/turmas (o mock tem a 393420)
}
HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def log(msg: str) -> None:
    print(f"[bench {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ estatística
def pct(vals: list[float], p: float) -> float | None:
    """Percentil com interpolação linear (p em 0..100)."""
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    i, f = int(k), k - int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * f


def resumo(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    r = lambda v: round(v, 1)  # noqa: E731
    return {
        "n": len(vals),
        "p50": r(pct(vals, 50)),
        "p95": r(pct(vals, 95)),
        "p99": r(pct(vals, 99)),
        "min": r(min(vals)),
        "max": r(max(vals)),
        "media": r(sum(vals) / len(vals)),
    }


# ------------------------------------------------------------------ HTTP
@dataclass
class Resultado:
    ms: float
    status: str  # "200", "502", "timeout", "ConnectError"...
    bytes: int = 0
    erro: str | None = None  # "502 navegacao_invalida: ..." (só quando ≠200)
    corpo: Any = None  # JSON, só quando pedido

    @property
    def ok(self) -> bool:
        return self.status == "200"


async def chamar(h: aiohttp.ClientSession, metodo: str, url: str, *, token: str | None = None, json_corpo: Any = None,
                 ler_json: bool = False, timeout: float | None = None) -> Resultado:
    """Uma requisição; o tempo inclui ler o corpo inteiro. Nunca levanta: erro de rede vira status textual."""
    hdr = {"Authorization": f"Bearer {token}"} if token else None
    kw: dict[str, Any] = {"headers": hdr, "json": json_corpo}
    if timeout:
        kw["timeout"] = aiohttp.ClientTimeout(total=timeout)
    t0 = time.perf_counter()
    try:
        async with h.request(metodo, url, **kw) as r:
            conteudo = await r.read()
            codigo = r.status
        ms = (time.perf_counter() - t0) * 1000
    except (asyncio.TimeoutError, TimeoutError):
        return Resultado((time.perf_counter() - t0) * 1000, "timeout", erro="timeout")
    except aiohttp.ClientError as e:
        return Resultado((time.perf_counter() - t0) * 1000, type(e).__name__, erro=f"{type(e).__name__}: {e}"[:200])
    res = Resultado(ms, str(codigo), len(conteudo))
    if codigo != 200:
        try:
            j = json.loads(conteudo)
            e = j.get("erro") or (j.get("detail") if isinstance(j.get("detail"), dict) else {"mensagem": str(j.get("detail", ""))})
            res.erro = f"{codigo} {e.get('codigo', '?')}: {e.get('mensagem', '')}"[:200]
        except Exception:
            res.erro = f"{codigo}: {conteudo[:120]!r}"
    elif ler_json:
        try:
            res.corpo = json.loads(conteudo)
        except ValueError:
            pass
    return res


class Alunos:
    """Gera usuários únicos na execução inteira (aluno001, aluno002...) — cada sessão nova é um aluno novo,
    assim nenhum cache por aluno (nem entre sessões) contamina uma medida 'fria'."""

    def __init__(self, fmt: str, inicio: int) -> None:
        self.fmt, self._c = fmt, count(inicio)

    def novo(self) -> str:
        return self.fmt.format(next(self._c))


@dataclass
class Bancada:
    args: argparse.Namespace
    h: aiohttp.ClientSession
    alunos: Alunos
    params: dict[str, str] = field(default_factory=dict)
    mock: str | None = None
    tetos: dict[int, dict[str, Any]] = field(default_factory=dict)
    logins_frios: list[Resultado] = field(default_factory=list)
    logins_carga: list[Resultado] = field(default_factory=list)

    def url(self, rota: str) -> str:
        return self.args.api.rstrip("/") + rota

    async def login(self, destino: list[Resultado] | None = None) -> tuple[str | None, Resultado]:
        usuario = self.alunos.novo()
        r = await chamar(self.h, "POST", self.url("/v1/auth/login"), json_corpo={"usuario": usuario, "senha": self.args.senha, "lembrar": True}, ler_json=True)
        if destino is not None:
            destino.append(r)
        token = (r.corpo or {}).get("token") if r.ok else None
        if r.ok and not token:
            r.status, r.erro = "sem_token", "login 200 sem token"
        return token, r

    async def logout(self, token: str | None) -> None:
        if token:
            await chamar(self.h, "DELETE", self.url("/v1/auth/sessao"), token=token)


def publica(rota: str) -> bool:
    return rota.startswith("/v1/publico/")


def montar(rota: str, params: dict[str, str]) -> tuple[str | None, str | None]:
    """Preenche os {placeholders}. Devolve (rota, None) ou (None, motivo)."""
    try:
        r = rota.format_map(params)
    except KeyError as e:
        return None, f"parâmetro {e} desconhecido (use --param {e.args[0]}=...)"
    faltando = [k for k in params if "{" + k + "}" in rota and not params[k]]
    if faltando:
        return None, f"sem valor pra {', '.join(faltando)} (use --param {faltando[0]}=...)"
    return r, None


# ------------------------------------------------------------------ fase 0: descoberta
async def descobrir(b: Bancada) -> dict[str, Any]:
    info: dict[str, Any] = {}
    precisa_turma = not b.params.get("turma_id") and any("{turma_id}" in r for r in b.args.rotas + b.args.rotas_carga)
    precisa_unidade = not b.params.get("unidade") and any("{unidade}" in r for r in b.args.rotas + b.args.rotas_carga)
    if precisa_turma:
        token, rl = await b.login()
        info["login"] = rl.status
        if token:
            for rota in ("/v1/turmas-virtuais", "/v1/turmas"):
                r = await chamar(b.h, "GET", b.url(rota), token=token, ler_json=True)
                lista = r.corpo.get("turmas", []) if isinstance(r.corpo, dict) else (r.corpo or [])
                tid = next((t.get("turma_id") for t in lista if isinstance(t, dict) and t.get("turma_id")), None)
                info[rota] = r.status
                if tid:
                    b.params["turma_id"], info["turma_id_de"] = str(tid), rota
                    break
            await b.logout(token)
        log(f"descoberta: turma_id={b.params.get('turma_id') or '—'} ({info})")
    if precisa_unidade:
        r = await chamar(b.h, "GET", b.url("/v1/publico/unidades"), ler_json=True)
        uid = next((u.get("id") for u in (r.corpo or []) if isinstance(u, dict) and u.get("id")), None) if isinstance(r.corpo, list) else None
        info["/v1/publico/unidades"] = r.status
        if uid:
            b.params["unidade"] = str(uid)
        log(f"descoberta: unidade={b.params.get('unidade') or '—'}")
    return info


# ------------------------------------------------------------------ fase 1: fria × quente
def _agrega(rs: list[Resultado]) -> dict[str, Any]:
    oks = [r.ms for r in rs if r.ok]
    return {
        **resumo(oks),
        "status": dict(Counter(r.status for r in rs)),
        "ms_todas": [round(r.ms, 1) for r in rs],
        "bytes_medio": round(sum(r.bytes for r in rs) / len(rs)) if rs else 0,
        "erros": sorted({r.erro for r in rs if r.erro})[:5],
    }


async def fria_quente_rota(b: Bancada, rota_tpl: str) -> dict[str, Any]:
    rota, motivo = montar(rota_tpl, b.params)
    saida: dict[str, Any] = {"rota": rota_tpl, "url": rota, "publica": publica(rota_tpl)}
    if not rota:
        saida["pulada"] = motivo
        log(f"  {rota_tpl}: PULADA ({motivo})")
        return saida
    frias: list[Resultado] = []
    quentes: list[Resultado] = []
    logins: list[Resultado] = []
    for _ in range(b.args.amostras_frias):
        token = None
        if not publica(rota_tpl):
            token, rl = await b.login(logins)
            if not token:
                continue
        frias.append(await chamar(b.h, "GET", b.url(rota), token=token))
        for _ in range(b.args.quentes):
            quentes.append(await chamar(b.h, "GET", b.url(rota), token=token))
        await b.logout(token)
    b.logins_frios.extend(logins)
    saida["fria"], saida["quente"] = _agrega(frias), _agrega(quentes)
    if logins and not any(r.ok for r in logins):
        saida["pulada"] = f"login falhou: {logins[0].erro}"
    f, q = saida["fria"].get("p50"), saida["quente"].get("p50")
    log(f"  {rota_tpl}: fria p50={f} ms · quente p50={q} ms · status={saida['fria']['status']}/{saida['quente']['status']}")
    return saida


async def fase_fria_quente(b: Bancada) -> list[dict[str, Any]]:
    log(f"fase 1: fria×quente — {len(b.args.rotas)} rotas × {b.args.amostras_frias} amostras frias × {b.args.quentes} quentes (paralelo={b.args.paralelo_frias})")
    sem = asyncio.Semaphore(b.args.paralelo_frias)

    async def uma(rota: str) -> dict[str, Any]:
        async with sem:
            return await fria_quente_rota(b, rota)

    return list(await asyncio.gather(*(uma(r) for r in b.args.rotas)))


# ------------------------------------------------------------------ fase 2: carga
async def rajada(b: Bancada, url: str, c: int, tokens: list[str | None], com_ms: bool = True) -> dict[str, Any]:
    """R requisições (e/ou --duracao s) com C sempre em voo, em rodízio entre os tokens."""
    total = b.args.requisicoes
    prazo = time.perf_counter() + b.args.duracao if b.args.duracao else None
    disparadas = count()
    resultados: list[Resultado] = []

    async def trabalhador() -> None:
        while True:
            i = next(disparadas)
            if (total and i >= total) or (prazo and time.perf_counter() >= prazo):
                return
            resultados.append(await chamar(b.h, "GET", url, token=tokens[i % len(tokens)]))

    t0 = time.perf_counter()
    await asyncio.gather(*(trabalhador() for _ in range(c)))
    parede = time.perf_counter() - t0
    oks = [r.ms for r in resultados if r.ok]
    d = {
        "requisicoes": len(resultados),
        "ok": len(oks),
        "tempo_s": round(parede, 2),
        "rps": round(len(resultados) / parede, 2) if parede else None,
        "rps_ok": round(len(oks) / parede, 2) if parede else None,
        "latencia_ok": resumo(oks),
        "latencia_todas": resumo([r.ms for r in resultados]),
        "status": dict(Counter(r.status for r in resultados)),
        "erros": dict(Counter(r.erro for r in resultados if r.erro).most_common(5)),
    }
    if com_ms:
        d["ms_todas"] = [round(r.ms, 1) for r in resultados]
    return d


async def calibrar(b: Bancada, c: int) -> dict[str, Any]:
    """Teto do GERADOR: a mesma carga (C, R/duração) direto num GET do mock, sem a API no meio.
    ideal_rps = C / latência mediana; eficiência ≈ 1 = o cliente aguenta esse C."""
    url = b.mock.rstrip("/") + b.args.calibrar_url
    d = await rajada(b, url, c, [None], com_ms=False)
    p50 = d["latencia_ok"].get("p50")
    d["url"] = url
    d["ideal_rps"] = round(c / (p50 / 1000), 1) if p50 else None
    d["eficiencia"] = round(d["rps"] / d["ideal_rps"], 2) if d.get("rps") and d["ideal_rps"] else None
    log(f"  teto do cliente C={c}: {d['rps']} req/s (ideal {d['ideal_rps']}, eficiência {d['eficiencia']}) p50={p50} · {d['status']}")
    return d


async def cenario_carga(b: Bancada, rota_tpl: str, c: int, n: int) -> dict[str, Any]:
    rota, motivo = montar(rota_tpl, b.params)
    saida: dict[str, Any] = {"rota": rota_tpl, "url": rota, "conexoes": c, "alunos": n, "publica": publica(rota_tpl)}
    if not rota:
        saida["pulada"] = motivo
        return saida
    tokens: list[str | None] = [None]
    if not publica(rota_tpl):
        sem = asyncio.Semaphore(b.args.login_paralelo)
        logins: list[Resultado] = []

        async def entra() -> str | None:
            async with sem:
                return (await b.login(logins))[0]

        t0 = time.perf_counter()
        tokens = [t for t in await asyncio.gather(*(entra() for _ in range(n))) if t]
        saida["logins"] = {"pedidos": n, "ok": len(tokens), "tempo_s": round(time.perf_counter() - t0, 2), **resumo([r.ms for r in logins if r.ok])}
        b.logins_carga.extend(logins)
        if not tokens:
            saida["pulada"] = f"nenhum login deu certo ({logins[0].erro if logins else '?'})"
            return saida
        if b.args.aquecer:
            await asyncio.gather(*(chamar(b.h, "GET", b.url(rota), token=t) for t in tokens))

    await mock_reset(b)
    saida.update(await rajada(b, b.url(rota), c, tokens))
    saida["mock"] = await mock_stats(b)
    if not publica(rota_tpl):
        await asyncio.gather(*(b.logout(t) for t in tokens))
    if b.tetos.get(c):
        saida["teto_cliente"] = b.tetos[c]
    parede = saida["tempo_s"]
    log(f"  {rota_tpl} C={c} N={n}: {saida['requisicoes']} req em {parede:.1f}s · {saida['rps']} req/s · p50={saida['latencia_ok'].get('p50')} p95={saida['latencia_ok'].get('p95')} · {saida['status']}")
    return saida


async def fase_carga(b: Bancada) -> list[dict[str, Any]]:
    a = b.args
    cenarios: list[tuple[str, int, int]] = []
    for rota in a.rotas_carga:
        for c in a.conexoes:
            vistos: set[int] = set()
            for modo in a.alunos:
                n = 0 if publica(rota) else (min(c, a.alunos_max) if modo == "auto" else int(modo))
                if n not in vistos:
                    vistos.add(n)
                    cenarios.append((rota, c, n))
    lim = f"{a.requisicoes} req" + (f" ou {a.duracao}s" if a.duracao else "") if a.requisicoes else f"{a.duracao}s"
    log(f"fase 2: carga — {len(cenarios)} cenários ({lim} cada)")
    if a.calibrar_cliente and b.mock:
        for c in sorted({cn[1] for cn in cenarios}):
            b.tetos[c] = await calibrar(b, c)
    return [await cenario_carga(b, *cn) for cn in cenarios]


# ------------------------------------------------------------------ metadados
def git_info(wt: str | None) -> dict[str, Any] | None:
    if not wt:
        return None
    wt = os.path.expanduser(wt)

    def g(*cmd: str) -> str | None:
        try:
            return subprocess.run(["git", "-C", wt, *cmd], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    return {"worktree": wt, "commit": g("rev-parse", "HEAD"), "branch": g("rev-parse", "--abbrev-ref", "HEAD"), "sujo": bool(g("status", "--porcelain", "--untracked-files=no"))}


async def mock_get(h: aiohttp.ClientSession, mock: str | None, caminho: str = "/__mock/config") -> Any:
    if not mock:
        return None
    r = await chamar(h, "GET", mock.rstrip("/") + caminho, ler_json=True, timeout=5)
    return r.corpo if r.ok and r.corpo is not None else {"indisponivel": r.erro or f"HTTP {r.status}"}


async def mock_reset(b: "Bancada") -> None:
    """Zera /__mock/stats (POST /__mock/reset) pra o próximo trecho medir só o que ele mesmo gerou."""
    if b.mock and not b.args.sem_reset_mock:
        await chamar(b.h, "POST", b.mock.rstrip("/") + "/__mock/reset", timeout=5)


async def mock_stats(b: "Bancada") -> dict[str, Any] | None:
    """O que o mock viu desde o último reset: total_misses, pico_concorrencia, por_regra, misses..."""
    st = await mock_get(b.h, b.mock, "/__mock/stats")
    if not isinstance(st, dict) or "indisponivel" in st:
        return None
    return {
        "requisicoes": sum((st.get("status") or {}).values()),
        **{k: st.get(k) for k in ("logins", "total_misses", "pico_concorrencia", "viewstate_invalido", "expiradas", "sessoes", "status", "por_regra")},
        "misses": sorted({_miss(m) for m in st.get("misses") or []}),
    }


def _local(url: str) -> bool:
    return (urlsplit(url).hostname or "") in HOSTS_LOCAIS


# ------------------------------------------------------------------ saída
def _ms(v: Any) -> str:
    if v is None:
        return "—"
    return f"{v / 1000:.2f} s" if v >= 1000 else f"{v:.0f} ms"


def _st(d: dict[str, int] | None) -> str:
    return " ".join(f"{k}×{v}" for k, v in sorted((d or {}).items())) or "—"


def _miss(x: Any) -> str:
    if not isinstance(x, dict):
        return str(x)
    link = (x.get("link") or {}).get("texto")
    return f"{x.get('metodo', '')} {x.get('caminho', '')}" + (f" «{link}»" if link else "")


def markdown(rel: dict[str, Any]) -> str:
    m = rel["meta"]
    L = [f"# Bench sigaa-api — {m['rotulo'] or m['api']}", ""]
    git = m.get("git") or {}
    L.append(f"- **data:** {m['data']} · **api:** {m['api']} (v{m.get('api_versao') or '?'}) → SIGAA {m.get('sigaa_url')}")
    L.append(f"- **commit:** {git.get('commit', '—')[:12] if git.get('commit') else '—'} ({git.get('branch', '—')}{', SUJO' if git.get('sujo') else ''}) · **worktree:** {git.get('worktree', '—')}")
    L.append(f"- **host:** {m['host']['nproc']} CPUs · load {m['host']['loadavg']} · Python {m['host']['python']}")
    mc = m.get("mock_config")
    L.append(f"- **mock:** `{json.dumps(mc, ensure_ascii=False)[:300]}`" if mc else "- **mock:** (config indisponível)")
    if ms := m.get("mock_stats_fria_quente"):
        L.append(f"- **o mock viu (fase fria×quente):** {ms.get('requisicoes')} req · {ms.get('logins')} logins · pico {ms.get('pico_concorrencia')} em voo · "
                 f"MISS={ms.get('total_misses')} · ViewState inválido={ms.get('viewstate_invalido')} · sessões expiradas={ms.get('expiradas')}")
    misses = sorted({x for ms in [m.get("mock_stats_fria_quente")] + [c.get("mock") for c in rel.get("carga") or []] if ms for x in ms.get("misses") or []})
    if misses:
        L.append(f"- **MISS no mock** (tela que o mock não cobre → a API devolve 502): {', '.join(misses)[:600]}")
    p = m["parametros"]
    L.append(f"- **parâmetros:** frias={p['amostras_frias']} quentes={p['quentes']} C={p['conexoes']} alunos={p['alunos']} (máx {p['alunos_max']}) req={p['requisicoes']} duração={p['duracao']} timeout={p['timeout']}s{' · RÁPIDO' if p['rapido'] else ''}")
    L.append(f"- **placeholders:** {', '.join(f'{k}={v}' for k, v in m['params'].items() if v)}")
    L.append(f"- **tempo total:** {m['tempo_total_s']} s")
    lf, lc = rel.get("login_frio") or {}, rel.get("login_carga") or {}
    if lf.get("n") or lc.get("n"):
        L += ["", "## Login (POST /v1/auth/login)", "", "| contexto | n | p50 | p95 | min | max | status |", "|---|--:|--:|--:|--:|--:|---|"]
        for nome, d in (("sequencial (fase fria)", lf), (f"carga (até {p['login_paralelo']} em paralelo)", lc)):
            if d.get("n") or d.get("status"):
                L.append(f"| {nome} | {d.get('n', 0)} | {_ms(d.get('p50'))} | {_ms(d.get('p95'))} | {_ms(d.get('min'))} | {_ms(d.get('max'))} | {_st(d.get('status'))} |")
    if rel.get("fria_quente"):
        L += ["", "## Latência fria × quente (por rota)", "",
              "| rota | status | fria p50 | fria p95 | fria min | fria max | quente p50 | quente p95 | quente min | quente max | fria/quente |",
              "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for r in rel["fria_quente"]:
            nome = r["rota"].split("?")[0] + (" 🔓" if r["publica"] else "")
            if "pulada" in r:
                L.append(f"| `{nome}` | PULADA: {r.get('pulada')} |" + " |" * 9)
                continue
            f, q = r["fria"], r["quente"]
            st = "200" if set(f["status"]) | set(q["status"]) == {"200"} else f"fria {_st(f['status'])} · quente {_st(q['status'])}"
            razao = f"{f['p50'] / q['p50']:.1f}×" if f.get("p50") and q.get("p50") else "—"
            L.append(f"| `{nome}` | {st} | {_ms(f.get('p50'))} | {_ms(f.get('p95'))} | {_ms(f.get('min'))} | {_ms(f.get('max'))} | {_ms(q.get('p50'))} | {_ms(q.get('p95'))} | {_ms(q.get('min'))} | {_ms(q.get('max'))} | {razao} |")
        erros = [(r["rota"], e) for r in rel["fria_quente"] for k in ("fria", "quente") for e in (r.get(k) or {}).get("erros", [])]
        if erros:
            L += ["", "<details><summary>erros (fria/quente)</summary>", ""] + [f"- `{rt}`: {e}" for rt, e in dict.fromkeys(erros)] + ["", "</details>"]
    if rel.get("carga"):
        L += ["", "## Carga (N alunos × C conexões simultâneas)", "",
              "| rota | C | N | req | ok | req/s | p50 | p95 | p99 | max | tempo | mock: req · pico · MISS | status / erros |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
        tetos = {r["conexoes"]: r["teto_cliente"] for r in rel["carga"] if r.get("teto_cliente")}
        for c, t in sorted(tetos.items()):
            L.append(f"| _teto do cliente (direto no mock)_ | {c} | — | {t['requisicoes']} | {t['ok']} | {t['rps']:.1f} | {_ms(t['latencia_ok'].get('p50'))} | "
                     f"{_ms(t['latencia_ok'].get('p95'))} | {_ms(t['latencia_ok'].get('p99'))} | {_ms(t['latencia_ok'].get('max'))} | {t['tempo_s']} s | "
                     f"ideal {t['ideal_rps']} req/s · eficiência {t['eficiencia']} | {_st(t['status'])} |")
        for r in rel["carga"]:
            nome = r["rota"].split("?")[0] + (" 🔓" if r["publica"] else "")
            n = "—" if r["publica"] else r["alunos"]
            if "requisicoes" not in r:
                L.append(f"| `{nome}` | {r['conexoes']} | {n} | PULADA: {r.get('pulada')} |" + " |" * 9)
                continue
            lat = r["latencia_ok"]
            err = "; ".join(f"{e[:70]} ×{k}" for e, k in r["erros"].items())
            mo = r.get("mock") or {}
            mk = f"{mo.get('requisicoes')} · {mo.get('pico_concorrencia')} · {mo.get('total_misses')}" if mo else "—"
            L.append(f"| `{nome}` | {r['conexoes']} | {n} | {r['requisicoes']} | {r['ok']} | {r['rps']:.1f} | {_ms(lat.get('p50'))} | {_ms(lat.get('p95'))} | {_ms(lat.get('p99'))} | {_ms(lat.get('max'))} | {r['tempo_s']} s | {mk} | {_st(r['status'])}{(' — ' + err) if err else ''} |")
    L += ["", "_🔓 = rota pública (sem login; o cache dela pode ser compartilhado entre alunos, então só a 1ª amostra fria é garantidamente fria)._", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ main
def _lista(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bench da sigaa-api (latência fria×quente + carga) contra o SIGAA simulado.", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--api", default="http://127.0.0.1:8112", help="URL da API a medir (tem que ser local)")
    p.add_argument("--mock", help="URL do mock (lê /__mock/config e /__mock/stats, zera com /__mock/reset); padrão: o SIGAA_URL que a API informa em /v1/status")
    p.add_argument("--worktree", help="worktree da API medida (grava o commit git nos metadados)")
    p.add_argument("--rotulo", default="", help="nome da rodada (ex.: baseline, cache, sessoes)")
    p.add_argument("--rotas", type=_lista, default=ROTAS_PADRAO, help="rotas da fase fria×quente (vírgula; aceita {turma_id} {codigo} {curso_id} {unidade} {ano} {periodo})")
    p.add_argument("--rotas-carga", type=_lista, default=ROTAS_CARGA_PADRAO, help="rotas da fase de carga (vírgula)")
    p.add_argument("--param", action="append", default=[], metavar="CHAVE=VALOR", help="valor de um placeholder (repetível), ex.: --param turma_id=123")
    p.add_argument("--senha", default="bench", help="senha usada em todos os logins (o mock aceita qualquer uma, menos 'errada')")
    p.add_argument("--usuario-fmt", default="aluno{:03d}", help="formato dos usuários")
    p.add_argument("--usuario-inicio", type=int, default=1, help="número do 1º usuário")
    p.add_argument("--amostras-frias", type=int, default=3, help="sessões novas por rota (cada uma dá 1 amostra fria)")
    p.add_argument("--quentes", type=int, default=5, help="repetições quentes por sessão")
    p.add_argument("--paralelo-frias", type=int, default=1, help="rotas medidas ao mesmo tempo na fase fria×quente (1 = medida limpa)")
    p.add_argument("--conexoes", type=lambda s: [int(x) for x in _lista(s)], default=[1, 10, 50, 200], help="C: conexões simultâneas")
    p.add_argument("--alunos", type=_lista, default=["auto"], help="N por cenário: 'auto' = min(C, --alunos-max) ou um número (ex.: auto,1 = também o 'mesmo aluno')")
    p.add_argument("--alunos-max", type=int, default=50)
    p.add_argument("--requisicoes", type=int, default=200, help="R: requisições por cenário de carga (0 = sem limite, use --duracao)")
    p.add_argument("--duracao", type=float, default=None, help="duração máxima (s) de cada cenário de carga")
    p.add_argument("--aquecer", action="store_true", help="na carga, 1 chamada por sessão antes de medir (não conta)")
    p.add_argument("--login-paralelo", type=int, default=20, help="logins simultâneos no preparo da carga")
    p.add_argument("--timeout", type=float, default=120, help="timeout de cada requisição (s)")
    p.add_argument("--calibrar-cliente", action="store_true", help="antes da carga, mede o teto do gerador batendo direto no mock com cada C")
    p.add_argument("--calibrar-url", default="/sigaa/public/turmas/listar.jsf", help="GET do mock usado no --calibrar-cliente")
    p.add_argument("--sem-reset-mock", action="store_true", help="não zera /__mock/stats antes de cada fase/cenário (use se o mock é compartilhado com outra rodada)")
    p.add_argument("--sem-frias", action="store_true", help="pula a fase fria×quente")
    p.add_argument("--sem-carga", action="store_true", help="pula a fase de carga")
    p.add_argument("--rapido", action="store_true", help="smoke: 1 fria, 2 quentes, C=1,10, 20 req (máx 4 s) por cenário, todas as rotas frias em paralelo")
    p.add_argument("--saida-md", help="grava a tabela markdown neste arquivo")
    p.add_argument("--saida-json", help="grava o JSON completo neste arquivo")
    a = p.parse_args(argv)
    if a.rapido:
        a.amostras_frias, a.quentes, a.conexoes, a.requisicoes = 1, 2, [1, 10], 20
        a.duracao = a.duracao or 4
        if a.paralelo_frias == 1:  # cada rota tem sessão própria; o que pesa é a rota mais lenta
            a.paralelo_frias = len(a.rotas)
    if not a.requisicoes and not a.duracao:
        p.error("--requisicoes 0 exige --duracao")
    return a


async def principal(a: argparse.Namespace) -> dict[str, Any]:
    if not _local(a.api):
        raise SystemExit(f"recusado: --api {a.api} não é local (o bench só mede API local apontada pro SIGAA simulado)")
    t_ini = time.perf_counter()
    c_max = max(a.conexoes) if not a.sem_carga else 1
    # limit = C + folga: o pool nunca é o gargalo (a espera por conexão livre contaria como latência)
    conector = aiohttp.TCPConnector(limit=c_max + max(a.login_paralelo, a.paralelo_frias) + 20, limit_per_host=0)
    async with aiohttp.ClientSession(connector=conector, timeout=aiohttp.ClientTimeout(total=a.timeout, sock_connect=10), trust_env=False) as h:
        r = await chamar(h, "GET", a.api.rstrip("/") + "/v1/status", ler_json=True, timeout=20)
        if not isinstance(r.corpo, dict):
            raise SystemExit(f"API {a.api} não respondeu /v1/status: {r.erro or r.status}")
        st = r.corpo
        sigaa_url = (st.get("sigaa") or {}).get("url") or ""
        if not _local(sigaa_url):
            raise SystemExit(f"recusado: a API aponta pra {sigaa_url!r} — o bench SÓ roda contra o SIGAA simulado (127.0.0.1). Suba a API com bench/api_instancia.sh.")
        mock = a.mock or sigaa_url
        if not _local(mock):
            raise SystemExit(f"recusado: --mock {mock} não é local")
        mc = await mock_get(h, mock)
        params = dict(PARAMS_PADRAO)
        if isinstance(mc, dict):  # o mock pode sugerir ids que existem nos dados dele
            for fonte in (mc, mc.get("params") or {}, mc.get("ids") or {}):
                if isinstance(fonte, dict):
                    params.update({k: str(v) for k, v in fonte.items() if k in PARAMS_PADRAO and v not in (None, "")})
        for kv in a.param:
            k, _, v = kv.partition("=")
            params[k.strip()] = v.strip()
        b = Bancada(a, h, Alunos(a.usuario_fmt, a.usuario_inicio), params, mock=mock)
        log(f"API {a.api} v{st.get('versao')} → SIGAA {sigaa_url} · mock config: {'ok' if mc and 'indisponivel' not in mc else 'indisponível'}")
        descoberta = await descobrir(b)
        await mock_reset(b)
        fq = [] if a.sem_frias else await fase_fria_quente(b)
        mock_fria = await mock_stats(b) if fq else None
        carga = [] if a.sem_carga else await fase_carga(b)

    def _lg(rs: list[Resultado]) -> dict[str, Any]:
        return {**resumo([r.ms for r in rs if r.ok]), "status": dict(Counter(r.status for r in rs))} if rs else {}

    return {
        "meta": {
            "rotulo": a.rotulo,
            "data": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "api": a.api,
            "api_versao": st.get("versao"),
            "sigaa_url": sigaa_url,
            "mock_url": mock,
            "mock_config": mc,
            "git": git_info(a.worktree),
            "host": {
                "nproc": os.cpu_count(),
                "nproc_disponivel": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                "loadavg": [round(x, 2) for x in os.getloadavg()],
                "python": platform.python_version(),
                "aiohttp": aiohttp.__version__,
                "sistema": platform.platform(),
            },
            "parametros": {k: getattr(a, k) for k in ("amostras_frias", "quentes", "paralelo_frias", "conexoes", "alunos", "alunos_max", "requisicoes", "duracao", "aquecer", "login_paralelo", "timeout", "rapido", "rotas", "rotas_carga")},
            "params": params,
            "descoberta": descoberta,
            "mock_stats_fria_quente": mock_fria,
            "tempo_total_s": round(time.perf_counter() - t_ini, 1),
        },
        "login_frio": _lg(b.logins_frios),
        "login_carga": _lg(b.logins_carga),
        "fria_quente": fq,
        "carga": carga,
    }


def main(argv: list[str] | None = None) -> int:
    a = argumentos(argv)
    try:
        rel = asyncio.run(principal(a))
    except KeyboardInterrupt:
        log("interrompido")
        return 130
    md = markdown(rel)
    print(md)
    if a.saida_md:
        with open(os.path.expanduser(a.saida_md), "w", encoding="utf-8") as f:
            f.write(md)
        log(f"markdown → {a.saida_md}")
    if a.saida_json:
        with open(os.path.expanduser(a.saida_json), "w", encoding="utf-8") as f:
            json.dump(rel, f, ensure_ascii=False, indent=1)
        log(f"json → {a.saida_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
