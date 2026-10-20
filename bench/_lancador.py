"""Sobe a API (uvicorn) de um worktree QUALQUER apontada pra um SIGAA_URL, sem vazar pro SIGAA real.

    python bench/_lancador.py --worktree ~/PROJECTS/UFBA/sigaa-api-perf-x --porta 8122 --sigaa http://127.0.0.1:8121

Por que não ``uvicorn api.main:app`` direto: alguns ``SigaaClient`` são criados sem ``base_url``
(ex.: ``cliente_anonimo()`` das rotas /v1/publico) e cairiam no padrão ``https://sigaa.ufba.br``
mesmo com ``SIGAA_URL`` apontado pro mock. Aqui o padrão do construtor é trocado ANTES de importar
a API. E, se ``--bloquear-https`` (padrão), o processo ganha ``HTTPS_PROXY`` pra um buraco negro:
qualquer https que escape falha na hora em vez de mandar carga pra UFBA.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--porta", type=int, required=True)
    ap.add_argument("--sigaa", required=True, help="URL do SIGAA (o mock: http://127.0.0.1:81xx)")
    ap.add_argument("--permitir-https", action="store_true", help="NÃO bloqueia https (só pro gravador)")
    ap.add_argument("--log-level", default="warning")
    a = ap.parse_args()

    wt = os.path.abspath(os.path.expanduser(a.worktree))
    if a.porta == 8000 or not (8100 <= a.porta <= 8199):
        sys.exit("porta fora de 8100–8199 (a 8000 é a produção)")
    if os.path.realpath(wt) == os.path.realpath(os.path.expanduser("~/PROJECTS/UFBA/sigaa-api")):
        sys.exit("esse é o worktree de PRODUÇÃO — não")
    os.environ["SIGAA_URL"] = a.sigaa.rstrip("/")
    os.environ.setdefault("SIGAA_API_MAX_LOGINS_POR_IP", "1000000")
    os.environ.setdefault("SIGAA_API_MAX_SESSOES", "100000")
    os.environ.setdefault("SIGAA_API_MAX_SESSOES_POR_USUARIO", "1000")
    os.environ.setdefault("SIGAA_API_KEEPALIVE", "false")
    if not a.permitir_https:
        os.environ["HTTPS_PROXY"] = os.environ["https_proxy"] = "http://127.0.0.1:9"
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    os.chdir(wt)
    sys.path.insert(0, wt)

    import sigaa.client as C  # noqa: E402  (do worktree alvo)

    C.BASE_URL = os.environ["SIGAA_URL"]
    d = list(C.SigaaClient.__init__.__defaults__ or ())
    if d:
        d[0] = os.environ["SIGAA_URL"]
        C.SigaaClient.__init__.__defaults__ = tuple(d)

    import uvicorn  # noqa: E402

    from api.main import app  # noqa: E402

    # 1 processo só: os tokens/sessões da API vivem na memória do processo
    uvicorn.run(app, host="127.0.0.1", port=a.porta, log_level=a.log_level)


if __name__ == "__main__":
    main()
