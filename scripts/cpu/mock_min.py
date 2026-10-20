"""SIGAA simulado MÍNIMO (frente cpu) — só o suficiente pra medir o SERVIDOR da API sob carga.

Não substitui o SIGAA simulado da frente bancada; serve pra medir CPU/latência da API sem
encostar no SIGAA real. Cobre: login (verTelaLogin → logar.do → portal), o portal do discente,
o menu "Emitir Histórico" (devolve um PDF) e uma página pública de curso.

    MOCK_LATENCIA_MS=450 MOCK_PDF=recon/pages/historico.pdf \\
        .venv/bin/uvicorn scripts.cpu.mock_min:app --port 8150 --workers 4 --log-level warning

``MOCK_LATENCIA_MS`` simula a ida/volta ao SIGAA (450 ms ≈ o real); ``MOCK_LENTO_MS`` é a
latência das rotas cujo caminho contém ``MOCK_LENTO_TRECHO`` (simula "uma tela do SIGAA lenta").
O PDF vem de ``MOCK_PDF`` (fica em recon/, que é gitignored — tem dado pessoal).
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

RAIZ = Path(__file__).resolve().parents[2]
FIX = RAIZ / "tests" / "fixtures"
LAT = float(os.getenv("MOCK_LATENCIA_MS", "0")) / 1000
LENTO = float(os.getenv("MOCK_LENTO_MS", "0")) / 1000
LENTO_TRECHO = os.getenv("MOCK_LENTO_TRECHO", "/public/")

PORTAL = (FIX / "portal" / "portal.html").read_bytes()
CURSO = (FIX / "consultas" / "publico" / "curso_portal.html").read_bytes()
_pdf = Path(os.getenv("MOCK_PDF", RAIZ / "recon" / "pages" / "historico.pdf"))
PDF = _pdf.read_bytes() if _pdf.exists() else b""
LOGIN = b"<html><body><form name='loginForm'><input name='user.login'><input name='user.senha'></form></body></html>"

HTML = "text/html; charset=ISO-8859-1"


async def _esperar(path: str) -> None:
    d = LENTO if (LENTO and LENTO_TRECHO in path) else LAT
    if d:
        await asyncio.sleep(d)


async def tela_login(req: Request):
    await _esperar(req.url.path)
    r = Response(LOGIN, media_type=HTML)
    r.set_cookie("JSESSIONID", secrets.token_hex(16), path="/sigaa")
    return r


async def logar(req: Request):
    await _esperar(req.url.path)
    if req.query_params.get("dispatch") == "logOff":
        return Response(LOGIN, media_type=HTML)
    return RedirectResponse("/sigaa/portais/discente/discente.jsf", status_code=302)


async def portal(req: Request):
    await _esperar(req.url.path)
    if req.method == "POST":
        corpo = (await req.body()).decode("latin-1")
        if "historico" in corpo and PDF:
            return Response(PDF, media_type="application/pdf")
    return Response(PORTAL, media_type=HTML)


async def curso(req: Request):
    await _esperar(req.url.path)
    return Response(CURSO, media_type=HTML)


app = Starlette(
    routes=[
        Route("/sigaa/verTelaLogin.do", tela_login),
        Route("/sigaa/logar.do", logar, methods=["GET", "POST"]),
        Route("/sigaa/verPortalDiscente.do", portal),
        Route("/sigaa/portais/discente/discente.jsf", portal, methods=["GET", "POST"]),
        Route("/sigaa/public/curso/portal.jsf", curso),
    ]
)
