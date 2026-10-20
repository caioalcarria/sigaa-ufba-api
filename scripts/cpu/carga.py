"""Gerador de carga da frente cpu (aiohttp, vários processos pra o cliente não ser o gargalo).

    .venv/bin/python scripts/cpu/carga.py --api http://127.0.0.1:8160 --rota /v1/portal \\
        --usuarios 200 --conc 200 --dur 20 --procs 4 [--sonda /]

* ``--usuarios N``: faz N logins (POST /v1/auth/login, usuários aluno0..alunoN-1) antes e
  distribui os tokens entre as conexões (0 = rota sem login).
* ``--conc C``: requisições simultâneas (somando os processos).
* ``--sonda P``: em paralelo, 1 requisição por 50 ms em P (ex.: ``/``, que não toca no SIGAA) —
  mede se a rota pesada TRAVA as outras (latência da sonda = o event loop está livre?).
* ``--uma-vez``: cada usuário faz a rota UMA vez só (ex.: /v1/historico sem cache) e sai.

Saída: uma linha JSON com req/s, p50/p95/p99/máx (ms), erros e a latência da sonda.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import time


def _pct(v: list[float], p: float) -> float:
    if not v:
        return 0.0
    v = sorted(v)
    return round(v[min(len(v) - 1, int(p / 100 * len(v)))] * 1000, 1)


async def _login(s, api: str, i: int) -> str:
    async with s.post(f"{api}/v1/auth/login", json={"usuario": f"aluno{i}", "senha": "x"}) as r:
        d = await r.json()
        if r.status != 200:
            raise RuntimeError(f"login {r.status}: {d}")
        return d["token"]


async def _logins(api: str, n: int, conc: int = 50) -> list[str]:
    import aiohttp

    sem = asyncio.Semaphore(conc)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as s:
        async def um(i):
            async with sem:
                return await _login(s, api, i)

        return await asyncio.gather(*(um(i) for i in range(n)))


async def _trabalhar(a, tokens: list[str], conc: int, fila: mp.Queue) -> None:
    import aiohttp

    lat: list[float] = []
    erros: dict[str, int] = {}
    sonda: list[float] = []
    fim = time.monotonic() + a.dur
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0), timeout=aiohttp.ClientTimeout(total=120)) as s:
        async def worker(k: int):
            j = k
            while True:
                if a.uma_vez:
                    if j >= len(tokens):
                        return
                    tok = tokens[j]
                    j += conc
                else:
                    if time.monotonic() > fim:
                        return
                    tok = tokens[k % len(tokens)] if tokens else None
                h = {"Authorization": f"Bearer {tok}"} if tok else {}
                if a.gzip:
                    h["Accept-Encoding"] = "gzip"
                t = time.perf_counter()
                try:
                    async with s.get(a.api + a.rota, headers=h) as r:
                        await r.read()
                        if r.status != 200:
                            erros[str(r.status)] = erros.get(str(r.status), 0) + 1
                            continue
                except Exception as e:  # noqa: BLE001
                    erros[type(e).__name__] = erros.get(type(e).__name__, 0) + 1
                    continue
                lat.append(time.perf_counter() - t)

        async def sondar():
            while (time.monotonic() < fim) and not parar.is_set():
                t = time.perf_counter()
                try:
                    async with s.get(a.api + a.sonda) as r:
                        await r.read()
                    sonda.append(time.perf_counter() - t)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(0.05)

        parar = asyncio.Event()
        t0 = time.perf_counter()
        sd = asyncio.create_task(sondar()) if a.sonda else None
        await asyncio.gather(*(worker(k) for k in range(conc)))
        dur = time.perf_counter() - t0
        parar.set()
        if sd:
            await sd
    fila.put({"lat": lat, "erros": erros, "sonda": sonda, "dur": dur})


def _proc(a, tokens, conc, fila):
    asyncio.run(_trabalhar(a, tokens, conc, fila))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8160")
    p.add_argument("--rota", default="/")
    p.add_argument("--usuarios", type=int, default=0)
    p.add_argument("--conc", type=int, default=50)
    p.add_argument("--dur", type=float, default=15)
    p.add_argument("--procs", type=int, default=2)
    p.add_argument("--sonda", default="")
    p.add_argument("--uma-vez", action="store_true")
    p.add_argument("--gzip", action="store_true")
    p.add_argument("--rotulo", default="")
    p.add_argument("--mock", default="http://127.0.0.1:8131", help="SIGAA simulado da bancada (pro --mock-fator)")
    p.add_argument("--mock-fator", type=float, default=None, help="depois dos logins, muda o fator de latência do mock")
    a = p.parse_args()

    tokens = asyncio.run(_logins(a.api, a.usuarios)) if a.usuarios else []
    if a.mock_fator is not None:  # logins rápidos; a CARGA com o SIGAA simulado lento
        import urllib.request

        req = urllib.request.Request(a.mock + "/__mock/config", data=json.dumps({"fator": a.mock_fator}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()
        urllib.request.urlopen(urllib.request.Request(a.mock + "/__mock/reset", data=b"{}")).read()
    fila: mp.Queue = mp.Queue()
    procs = []
    for i in range(a.procs):
        meus = tokens[i::a.procs] if tokens else []
        c = max(1, a.conc // a.procs)
        if a.uma_vez:
            c = min(c, len(meus)) or 1
        procs.append(mp.Process(target=_proc, args=(a, meus, c, fila)))
    for pr in procs:
        pr.start()
    res = [fila.get() for _ in procs]
    for pr in procs:
        pr.join()
    lat = [x for r in res for x in r["lat"]]
    sonda = [x for r in res for x in r["sonda"]]
    erros: dict[str, int] = {}
    for r in res:
        for k, v in r["erros"].items():
            erros[k] = erros.get(k, 0) + v
    dur = max(r["dur"] for r in res)
    print(json.dumps({
        "rotulo": a.rotulo, "rota": a.rota, "conc": a.conc, "usuarios": a.usuarios,
        "ok": len(lat), "req_s": round(len(lat) / dur, 1), "dur_s": round(dur, 2),
        "p50": _pct(lat, 50), "p95": _pct(lat, 95), "p99": _pct(lat, 99), "max": _pct(lat, 100),
        "erros": erros,
        **({"sonda_p50": _pct(sonda, 50), "sonda_p99": _pct(sonda, 99), "sonda_max": _pct(sonda, 100)} if a.sonda else {}),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
