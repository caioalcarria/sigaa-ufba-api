"""Servidor sob carga: pool de parse (sigaa.cpu), teto de conexões ao SIGAA, prazo (504) e gzip — sem rede."""

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sigaa.client as C
from sigaa import cpu
from sigaa import errors as E
from sigaa.client import Page, SigaaClient, _plano_clique
from sigaa.parsers.portal import parse_portal

PORTAL = (Path(__file__).parent / "fixtures" / "portal" / "portal.html").read_text("iso-8859-1")


def _quebra(_html: str) -> None:
    raise E.NaoEncontrado("não achei")


@pytest.fixture(scope="module")
def pool():
    cpu.iniciar(2)
    yield
    cpu.parar()


def test_rodar_sem_pool_e_chamada_direta():
    assert cpu.ativo() == 0
    assert asyncio.run(cpu.rodar(parse_portal, PORTAL)) == parse_portal(PORTAL)


def test_rodar_no_pool_da_o_mesmo_resultado(pool):
    assert cpu.ativo() == 2
    assert asyncio.run(cpu.rodar(parse_portal, PORTAL)) == parse_portal(PORTAL)


def test_rodar_no_pool_propaga_o_erro_do_parser(pool):
    with pytest.raises(E.NaoEncontrado, match="não achei"):
        asyncio.run(cpu.rodar(_quebra, PORTAL))


def test_rodar_nao_manda_objeto_pesado_pro_pool(pool):
    pagina = Page(url="https://x/a.jsf", status=200, content=PORTAL.encode("iso-8859-1"), content_type="text/html")
    # uma Page (com soup) não é "simples": roda aqui mesmo, sem pickle
    assert not cpu._vale_a_pena((pagina,), {})
    assert not cpu._vale_a_pena(("curto",), {})
    assert cpu._vale_a_pena((PORTAL, {"a": "b"}), {})


def test_plano_do_clique_igual_ao_inline():
    pagina = Page(url="https://sigaa/sigaa/portais/discente/discente.jsf", status=200, content=PORTAL.encode("iso-8859-1"), content_type="text/html")
    link = pagina.links_jsf()[0]
    url, dados = _plano_clique(PORTAL, pagina.url, link.onclick, {"x": "1"})
    esperado = C._plano_link(pagina, link, {"x": "1"})
    assert (url, dados) == esperado and dados["x"] == "1"


def test_um_contexto_ssl_pra_todos_os_clientes():
    a, b = SigaaClient("https://exemplo"), SigaaClient("https://exemplo")
    assert C._ssl_ctx() is C._ssl_ctx()
    asyncio.run(a.close()), asyncio.run(b.close())


def test_teto_de_conexoes_vira_sigaa_ocupado(monkeypatch):
    monkeypatch.setattr(C, "MAX_CONEXOES", 1)
    monkeypatch.setattr(C, "ESPERA_MAX_S", 0.05)

    async def lento(_req):
        await asyncio.sleep(0.3)
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    async def cenario():
        a = SigaaClient("https://sigaa.teste", min_interval=0)
        b = SigaaClient("https://sigaa.teste", min_interval=0)
        for c in (a, b):
            c._http = httpx.AsyncClient(base_url=c.base_url, transport=httpx.MockTransport(lento))
        r = await asyncio.gather(a.get("/x"), b.get("/y"), return_exceptions=True)
        await a.close(), await b.close()
        return r

    r = asyncio.run(cenario())
    assert sum(isinstance(x, Page) for x in r) == 1
    assert sum(isinstance(x, E.SigaaOcupado) for x in r) == 1


def test_sigaa_ocupado_da_503_com_retry_after():
    from api.main import app

    @app.get("/__teste/ocupado", include_in_schema=False)
    async def ocupado():
        raise E.SigaaOcupado("cheio")

    r = TestClient(app).get("/__teste/ocupado")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert r.json()["erro"]["codigo"] == "sigaa_ocupado"


def test_prazo_estourado_da_504():
    from api.main import Prazo

    mini = FastAPI()

    @mini.get("/lento")
    async def lento():
        await asyncio.sleep(2)
        return {"ok": True}

    @mini.get("/rapido")
    async def rapido():
        return {"ok": True}

    cli = TestClient(Prazo(mini, segundos=0.1))
    r = cli.get("/lento")
    assert r.status_code == 504 and r.json()["erro"]["codigo"] == "tempo_esgotado"
    assert cli.get("/rapido").status_code == 200


def test_gzip_quando_o_cliente_aceita():
    from api.main import app

    @app.get("/__teste/grande", include_in_schema=False)
    async def grande():
        return {"itens": ["x" * 50] * 200}

    cli = TestClient(app)
    r = cli.get("/__teste/grande", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip" and len(r.json()["itens"]) == 200
    assert "content-encoding" not in cli.get("/__teste/grande", headers={"Accept-Encoding": "identity"}).headers


def test_gzip_fica_por_fora_do_cache_http():
    """Por dentro, o cache guardaria o corpo já comprimido sem o Content-Encoding (JSON ilegível no MISS→HIT)."""
    from fastapi.middleware.gzip import GZipMiddleware

    from api import cache as cache_http
    from api.main import app

    ordem = [m.cls for m in app.user_middleware]  # 0 = mais de fora
    assert ordem.index(GZipMiddleware) < ordem.index(cache_http.CacheHTTP)
