"""Benchmark e2e da frente 'sessoes' (pool de sessões / paralelismo) — mede a API rodando local.

Uso:
    .venv/bin/python scripts/bench_sessoes.py http://127.0.0.1:8101 [--cenarios seq,rajada] [--rotas notas,frequencia]
          [--usuario U --senha S]   # sem isso, usa SIGAA_USUARIO/SIGAA_SENHA (bench/credencial.py), sem exibir

Cenários:
* ``login``   — POST /v1/auth/login
* ``seq``     — cada rota agregada sozinha, uma depois da outra (o que um app faz ao abrir uma tela)
* ``rajada``  — as rotas do "dashboard" disparadas AO MESMO TEMPO com o mesmo token (o que um app faz ao abrir)

Imprime uma tabela (rota, status, segundos, itens) e um JSON no fim (pra comparar antes × depois).
Contra o SIGAA REAL rode com parcimônia (1 vez por cenário). Carga pesada só contra o SIGAA simulado.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import httpx

AGREGADAS = {
    "notas": "/v1/notas",
    "frequencia": "/v1/frequencia",
    "tarefas": "/v1/tarefas",
    "avaliacoes": "/v1/avaliacoes",
    "processamento": "/v1/matricula/processamento",
    "planejamento": "/v1/planejamento/matricula",
}
RAJADA = ["/v1/me", "/v1/turmas?atuais=true", "/v1/notas", "/v1/tarefas", "/v1/avaliacoes", "/v1/frequencia"]


def _cred() -> tuple[str, str]:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bench"))
    from credencial import credencial as c  # noqa: PLC0415

    return c()


def _itens(r: httpx.Response) -> str:
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        return "-"
    if isinstance(j, list):
        return str(len(j))
    if isinstance(j, dict) and "candidatos" in j:
        return f"{len(j['candidatos'])} cand."
    return "obj"


async def chamar(http: httpx.AsyncClient, rota: str) -> dict:
    t = time.perf_counter()
    try:
        r = await http.get(rota)
        st, itens = r.status_code, _itens(r)
        if st >= 400:
            itens = r.text[:120]
    except Exception as e:  # noqa: BLE001
        st, itens = 0, f"{type(e).__name__}: {e}"
    return {"rota": rota, "status": st, "s": round(time.perf_counter() - t, 2), "itens": itens}


def tabela(titulo: str, linhas: list[dict]) -> None:
    print(f"\n## {titulo}")
    for x in linhas:
        print(f"  {x['rota']:34s} {x['status']:>3}  {x['s']:6.2f}s  {x['itens']}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--cenarios", default="seq,rajada")
    ap.add_argument("--rotas", default=",".join(AGREGADAS))
    ap.add_argument("--usuario")
    ap.add_argument("--senha")
    ap.add_argument("--rotulo", default="")
    a = ap.parse_args()
    u, s = (a.usuario, a.senha) if a.usuario else _cred()
    res: dict = {"rotulo": a.rotulo, "base": a.base}
    async with httpx.AsyncClient(base_url=a.base, timeout=300) as http:
        t = time.perf_counter()
        r = await http.post("/v1/auth/login", json={"usuario": u, "senha": s, "lembrar": True})
        r.raise_for_status()
        res["login_s"] = round(time.perf_counter() - t, 2)
        print(f"login: {res['login_s']}s")
        http.headers["Authorization"] = "Bearer " + r.json()["token"]
        try:
            cen = a.cenarios.split(",")
            if "seq" in cen:
                linhas = [await chamar(http, AGREGADAS[k]) for k in a.rotas.split(",") if k in AGREGADAS]
                tabela("seq (uma rota por vez)", linhas)
                res["seq"] = linhas
            if "rajada" in cen:
                t = time.perf_counter()
                linhas = await asyncio.gather(*(chamar(http, x) for x in RAJADA))
                total = round(time.perf_counter() - t, 2)
                tabela(f"rajada ({len(RAJADA)} rotas juntas) — parede {total}s", linhas)
                res["rajada"] = {"parede_s": total, "rotas": linhas}
        finally:
            await http.post("/v1/auth/logout")
    print("\nJSON " + json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
