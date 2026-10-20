"""Roda os cenários de carga da frente cpu contra uma API JÁ de pé e mede a CPU do processo dela.

    .venv/bin/python scripts/cpu/cenarios.py --api http://127.0.0.1:8160 --pid <pid(s) da API> --rotulo antes

A CPU é lida de /proc/<pid>/stat (utime+stime, somando os filhos vivos = workers do uvicorn
e processos do pool de parse) antes e depois de cada cenário → ms de CPU por requisição.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
HZ = os.sysconf("SC_CLK_TCK")


def _arvore(pid: int) -> list[int]:
    out = [pid]
    try:
        tarefas = os.listdir(f"/proc/{pid}/task")  # filhos de QUALQUER thread (o pool nasce numa)
    except OSError:
        return out
    for t in tarefas:
        try:
            filhos = open(f"/proc/{pid}/task/{t}/children").read().split()
        except OSError:
            continue
        for f in filhos:
            out += _arvore(int(f))
    return out


def cpu_s(pids: list[int]) -> float:
    tot = 0
    for raiz in pids:
        for p in _arvore(raiz):
            try:
                campos = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
                # utime+stime + cutime+cstime (filhos JÁ mortos e colhidos: processo do pool reciclado)
                tot += int(campos[11]) + int(campos[12]) + int(campos[13]) + int(campos[14])
            except OSError:
                pass
    return tot / HZ


CENARIOS = {
    "raiz": ["--rota", "/", "--conc", "100", "--dur", "10", "--procs", "4"],
    "portal": ["--rota", "/v1/portal", "--usuarios", "300", "--conc", "300", "--dur", "20", "--procs", "4", "--sonda", "/"],
    "historico": ["--rota", "/v1/historico", "--usuarios", "120", "--conc", "120", "--uma-vez", "--procs", "4", "--sonda", "/"],
    "portal1000": ["--rota", "/v1/portal", "--usuarios", "1000", "--conc", "1000", "--dur", "20", "--procs", "6", "--sonda", "/"],
    "historico400": ["--rota", "/v1/historico", "--usuarios", "400", "--conc", "400", "--uma-vez", "--procs", "4", "--sonda", "/"],
    "turmas": ["--rota", "/v1/turmas", "--usuarios", "200", "--conc", "200", "--dur", "25", "--procs", "4", "--sonda", "/"],
    "notas": ["--rota", "/v1/notas", "--usuarios", "100", "--conc", "100", "--dur", "40", "--procs", "4", "--sonda", "/"],
    "publico": ["--rota", "/v1/publico/cursos/1876885", "--conc", "100", "--dur", "20", "--procs", "4", "--sonda", "/"],
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8160")
    p.add_argument("--pid", type=int, nargs="+", required=True)
    p.add_argument("--rotulo", default="")
    p.add_argument("--so", nargs="*", default=["raiz", "portal", "historico", "turmas", "notas", "publico"])
    p.add_argument("--extra", default="", help="args extras pro carga.py (ex.: --gzip)")
    a = p.parse_args()
    for nome in a.so:
        antes = cpu_s(a.pid)
        out = subprocess.run(
            [sys.executable, os.path.join(AQUI, "carga.py"), "--api", a.api, "--rotulo", f"{a.rotulo}:{nome}", *CENARIOS[nome], *a.extra.split()],
            capture_output=True, text=True,
        )
        gasto = cpu_s(a.pid) - antes
        try:
            r = json.loads(out.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            print(nome, "FALHOU", out.stdout[-500:], out.stderr[-1500:])
            continue
        n = r["ok"] + sum(r["erros"].values()) + r["usuarios"]  # logins também gastam CPU
        r["cpu_s"] = round(gasto, 2)
        r["cpu_ms_por_req"] = round(gasto * 1000 / max(1, n), 2)
        print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
