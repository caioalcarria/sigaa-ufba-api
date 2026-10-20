"""Compara as respostas JSON de DUAS APIs (ex.: base × frente) rota a rota, contra o MESMO SIGAA simulado.

    .venv/bin/python scripts/cpu/igualdade.py http://127.0.0.1:8132 http://127.0.0.1:8133 [--param k=v ...]

Ignora campos que mudam a cada emissão (código de verificação / emitido_em). Sai 1 se alguma rota diferir.
"""
from __future__ import annotations

import json
import sys

import httpx

ROTAS = [
    "/v1/historico", "/v1/indices", "/v1/integralizacao", "/v1/matricula", "/v1/turmas", "/v1/portal", "/v1/me",
    "/v1/grade-curricular", "/v1/planejamento/matricula", "/v1/notas", "/v1/frequencia",
    "/v1/turmas/{turma_id}/notas", "/v1/turmas/{turma_id}", "/v1/documentos/comprovante-inscricao",
    "/v1/publico/turmas?ano={ano}&periodo={periodo}&unidade={unidade}", "/v1/publico/componentes/{componente_id}",
    "/v1/publico/cursos/{curso_id}", "/v1/publico/cursos/{curso_id}/estruturas/{estrutura_id}",
    "/v1/publico/cursos/{curso_id}/calendario",
]
VOLATEIS = {"codigo_verificacao", "emitido_em", "token", "expira_em", "criada_em"}


def limpar(x):
    if isinstance(x, dict):
        return {k: limpar(v) for k, v in x.items() if k not in VOLATEIS}
    if isinstance(x, list):
        return [limpar(v) for v in x]
    return x


def main() -> int:
    a, b, *resto = sys.argv[1:]
    params = dict(p.split("=", 1) for p in resto if "=" in p)
    mock = params.pop("mock", "http://127.0.0.1:8131")
    try:
        params = {**{k: str(v) for k, v in httpx.get(mock + "/__mock/config").json().get("placeholders", {}).items()}, **params}
    except Exception:  # noqa: BLE001
        pass
    toks = {}
    for api in (a, b):
        toks[api] = httpx.post(api + "/v1/auth/login", json={"usuario": "igualdade", "senha": "x"}, timeout=60).json()["token"]
    if "turma_id" not in params:
        tv = httpx.get(a + "/v1/turmas", headers={"Authorization": f"Bearer {toks[a]}"}, timeout=120).json()
        ids = [t.get("turma_id") for t in (tv.get("turmas") or tv.get("itens") or []) if t.get("turma_id")]
        if ids:
            params["turma_id"] = str(ids[0])
    ruins = 0
    for r in ROTAS:
        try:
            rota = r.format(**params)
        except KeyError as e:
            print(f"--  {r}: sem valor pra {e}")
            continue
        res = []
        for api in (a, b):
            h = {} if "/publico/" in rota else {"Authorization": f"Bearer {toks[api]}"}
            x = httpx.get(api + rota, headers=h, timeout=180)
            try:
                corpo = limpar(x.json())
            except ValueError:
                corpo = x.text
            res.append((x.status_code, corpo))
        ok = res[0] == res[1]
        ruins += not ok
        print(f"{'OK' if ok else 'DIFERE'}  {res[0][0]}/{res[1][0]}  {rota}  ({len(json.dumps(res[0][1]))} B)")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
