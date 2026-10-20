#!/usr/bin/env python3
"""Junta JSONs do bench.py (bancada) numa tabela antes × depois, em markdown.

    python bench/cache_comparar.py base.json cache.json [outro.json ...]
"""

from __future__ import annotations

import json
import sys


def _ms(v):
    if v is None:
        return "—"
    return f"{v / 1000:.2f} s" if v >= 1000 else f"{v:.1f} ms"


def main(caminhos: list[str]) -> None:
    rels = [json.load(open(c)) for c in caminhos]
    nomes = [r["meta"].get("rotulo") or c for r, c in zip(rels, caminhos)]
    print("### Fria × quente (p50 por rota)\n")
    print("| rota | " + " | ".join(f"{n} fria | {n} quente" for n in nomes) + " |")
    print("|---|" + "--:|--:|" * len(nomes))
    rotas = [r["rota"] for r in rels[0].get("fria_quente", [])]
    for rota in rotas:
        cel = []
        for r in rels:
            x = next((y for y in r.get("fria_quente", []) if y["rota"] == rota), None)
            if not x or "fria" not in x:
                cel += ["—", "—"]
                continue
            cel += [_ms(x["fria"].get("p50")), _ms(x["quente"].get("p50"))]
        print(f"| `{rota}` | " + " | ".join(cel) + " |")
    print("\n### Carga (req/s · p50 · p95)\n")
    print("| rota | C | N | " + " | ".join(nomes) + " |")
    print("|---|--:|--:|" + "---|" * len(nomes))
    for x0 in rels[0].get("carga", []):
        cel = []
        for r in rels:
            x = next((y for y in r.get("carga", []) if y["rota"] == x0["rota"] and y["conexoes"] == x0["conexoes"] and y["alunos"] == x0["alunos"]), None)
            if not x or "rps" not in x:
                cel.append("—")
                continue
            lat = x.get("latencia_ok") or {}
            err = sum(v for k, v in x.get("status", {}).items() if k != "200")
            cel.append(f"{x['rps']:.1f} req/s · {_ms(lat.get('p50'))} · {_ms(lat.get('p95'))}" + (f" · {err} erros" if err else ""))
        print(f"| `{x0['rota']}` | {x0['conexoes']} | {x0['alunos']} | " + " | ".join(cel) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
