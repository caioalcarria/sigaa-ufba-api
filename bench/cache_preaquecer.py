#!/usr/bin/env python3
"""Cenário "o app abre X s depois do login" contra o SIGAA SIMULADO: soma do tempo das rotas da tela inicial.

    .venv/bin/python bench/cache_preaquecer.py http://127.0.0.1:8183 --espera 20 --usuario pre001
"""
import argparse, asyncio, time

import httpx

ROTAS = ["/v1/portal", "/v1/me", "/v1/turmas", "/v1/grade-horaria", "/v1/historico", "/v1/indices", "/v1/integralizacao", "/v1/matricula"]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("api")
    ap.add_argument("--espera", type=float, default=20)
    ap.add_argument("--usuario", default="pre001")
    a = ap.parse_args()
    async with httpx.AsyncClient(base_url=a.api, timeout=120) as c:
        st = (await c.get("/v1/status")).json()
        assert st["sigaa"]["url"].startswith("http://127.0.0.1"), "só contra o SIGAA simulado"
        tok = (await c.post("/v1/auth/login", json={"usuario": a.usuario, "senha": "x"})).json()["token"]
        await asyncio.sleep(a.espera)
        total, linhas = 0.0, []
        for r in ROTAS:
            t = time.perf_counter()
            resp = await c.get(r, headers={"Authorization": f"Bearer {tok}"})
            ms = (time.perf_counter() - t) * 1000
            total += ms
            linhas.append(f"{r}={ms:.0f}ms/{resp.headers.get('x-cache', '-')}")
        print(f"{a.api} espera={a.espera:.0f}s total={total / 1000:.2f}s :: " + " ".join(linhas))


asyncio.run(main())
