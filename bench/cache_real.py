#!/usr/bin/env python3
"""Medição LEVE do cache contra o SIGAA REAL (1 aluno, em série, no máx. 2 sessões ao mesmo tempo).

Sobe nada: aponte pra uma API local já rodando (porta 81xx) e rode:

    .venv/bin/python bench/cache_real.py --api http://127.0.0.1:8161 --rotulo cache

Cenários (cada rota uma vez fria e N vezes quente, sempre em série):
  1. login → rotas em sequência IMEDIATA (o que o app faz ao abrir) — mede fria;
  2. as mesmas rotas de novo — mede quente;
  3. sessão NOVA do mesmo aluno, ``?fresco=true`` no /planejamento/matricula — com o cache ligado, a
     oferta/pré-requisitos/estrutura vêm do cache compartilhado (L2), como seria pra um colega do curso;
  4. login → espera o pré-aquecimento → rotas (o app que abre 5 s depois do login).

A credencial vem do LastPass (recon/sess.py) e nunca é impressa. Nada de dado pessoal na saída: só tempos e cabeçalhos.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recon"))

ROTAS = ["/v1/portal", "/v1/me", "/v1/turmas", "/v1/historico", "/v1/indices", "/v1/matricula", "/v1/grade-curricular"]


def login(api: str) -> tuple[str, float]:
    from sess import _cred  # noqa: PLC0415

    u, p = _cred()
    t0 = time.perf_counter()
    r = httpx.post(api + "/v1/auth/login", json={"usuario": u, "senha": p, "lembrar": False}, timeout=90)
    r.raise_for_status()
    return r.json()["token"], (time.perf_counter() - t0) * 1000


def get(api: str, tok: str, rota: str) -> tuple[float, int, str, int]:
    t0 = time.perf_counter()
    r = httpx.get(api + rota, headers={"Authorization": f"Bearer {tok}", "Accept-Encoding": "gzip"}, timeout=120)
    ms = (time.perf_counter() - t0) * 1000
    return ms, r.status_code, r.headers.get("x-cache", "-"), int(r.headers.get("content-length") or len(r.content))


def logout(api: str, tok: str) -> None:
    try:
        httpx.delete(api + "/v1/auth/sessao", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    except httpx.HTTPError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--rotulo", default="?")
    ap.add_argument("--quentes", type=int, default=3)
    ap.add_argument("--espera-preaquecer", type=float, default=25.0)
    ap.add_argument("--saida", default=None)
    a = ap.parse_args()
    assert a.api.startswith("http://127.0.0.1:81"), "só API local de teste (porta 81xx)"
    out: dict = {"rotulo": a.rotulo, "cenarios": {}}

    # 1+2: fria e quente
    tok, ms_login = login(a.api)
    out["login_ms"] = round(ms_login)
    fria, quente = {}, {}
    for rota in ROTAS:
        ms, st, xc, n = get(a.api, tok, rota)
        fria[rota] = {"ms": round(ms), "status": st, "x_cache": xc, "bytes": n}
        print(f"[{a.rotulo}] fria   {rota:28s} {ms:8.0f} ms  {st} {xc}", file=sys.stderr)
    for rota in ROTAS:
        tempos = []
        for _ in range(a.quentes):
            ms, st, xc, n = get(a.api, tok, rota)
            tempos.append(ms)
        quente[rota] = {"ms_mediana": round(statistics.median(tempos), 2), "ms_todas": [round(t, 2) for t in tempos], "x_cache": xc}
        print(f"[{a.rotulo}] quente {rota:28s} {statistics.median(tempos):8.1f} ms  {xc}", file=sys.stderr)
    out["cenarios"]["fria"] = fria
    out["cenarios"]["quente"] = quente

    # 3: sessão nova, planejamento forçando L1 fresco (L2 compartilhado pode responder)
    tok2, _ = login(a.api)
    rota = "/v1/planejamento/matricula?fresco=true"
    ms, st, xc, n = get(a.api, tok2, rota)
    out["cenarios"]["planejamento_sessao_nova"] = {"ms": round(ms), "status": st, "x_cache": xc}
    print(f"[{a.rotulo}] planejamento (sessão nova) {ms:8.0f} ms {st} {xc}", file=sys.stderr)
    logout(a.api, tok2)
    logout(a.api, tok)

    # 4: login → espera o pré-aquecimento → abre o app
    tok3, _ = login(a.api)
    time.sleep(a.espera_preaquecer)
    pre = {}
    for rota in ROTAS[:6]:
        ms, st, xc, n = get(a.api, tok3, rota)
        pre[rota] = {"ms": round(ms, 1), "status": st, "x_cache": xc}
        print(f"[{a.rotulo}] pós-aquecimento {rota:28s} {ms:8.1f} ms  {xc}", file=sys.stderr)
    out["cenarios"]["apos_preaquecimento"] = pre
    logout(a.api, tok3)
    try:
        out["estatisticas"] = httpx.get(a.api + "/v1/cache/estatisticas", timeout=10).json()
    except Exception:  # noqa: BLE001
        pass
    s = json.dumps(out, ensure_ascii=False, indent=1)
    if a.saida:
        Path(a.saida).write_text(s)
    print(s)


if __name__ == "__main__":
    main()
