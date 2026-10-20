"""HIT do cache enquanto N alunos fazem login AO MESMO TEMPO (cada login dispara o pré-aquecimento,
que emite e parseia o histórico em PDF) — o parse no event loop atrasava até os HITs.

    .venv/bin/python scripts/cpu/preaquecer.py --api http://127.0.0.1:8142 --logins 50 --dur 40

Saída: uma linha JSON com a latência (ms) dos HITs da sonda durante a rajada de logins.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import aiohttp


def _pct(v: list[float], p: float) -> float:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(p / 100 * len(v)))] * 1000, 1) if v else 0.0


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8142")
    p.add_argument("--rota", default="/v1/historico")
    p.add_argument("--logins", type=int, default=50)
    p.add_argument("--dur", type=float, default=40)
    p.add_argument("--rotulo", default="")
    a = p.parse_args()
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0), timeout=aiohttp.ClientTimeout(total=180)) as s:
        async def login(u: str) -> str:
            async with s.post(a.api + "/v1/auth/login", json={"usuario": u, "senha": "x"}) as r:
                return (await r.json())["token"]

        tok = await login(f"vigia{int(time.time())}")
        h = {"Authorization": f"Bearer {tok}"}
        for _ in range(3):  # aquece a entrada da sonda até virar HIT
            async with s.get(a.api + a.rota, headers=h) as r:
                await r.read()
            await asyncio.sleep(0.5)

        lat: list[float] = []
        estados: dict[str, int] = {}
        fim = time.monotonic() + a.dur

        async def sonda():
            while time.monotonic() < fim:
                t = time.perf_counter()
                try:
                    async with s.get(a.api + a.rota, headers=h) as r:
                        await r.read()
                        x = r.headers.get("x-cache", "?")
                except aiohttp.ClientError as e:  # conexão derrubada com o loop travado também conta
                    x = type(e).__name__
                estados[x] = estados.get(x, 0) + 1
                if x == "HIT":
                    lat.append(time.perf_counter() - t)
                await asyncio.sleep(0.05)

        sd = asyncio.create_task(sonda())
        await asyncio.sleep(1)
        t0 = time.perf_counter()
        base = int(time.time())
        await asyncio.gather(*(login(f"rajada{base}_{i}") for i in range(a.logins)))
        t_logins = time.perf_counter() - t0
        await sd
    print(json.dumps({"rotulo": a.rotulo, "logins": a.logins, "logins_s": round(t_logins, 2), "sonda": estados,
                      "hit_p50": _pct(lat, 50), "hit_p95": _pct(lat, 95), "hit_p99": _pct(lat, 99), "hit_max": _pct(lat, 100)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
