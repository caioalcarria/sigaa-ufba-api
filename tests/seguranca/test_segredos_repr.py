"""SEG·SEGREDOS — ``repr()``/``str()`` de objeto que carrega credencial, cookie ou dado do aluno não
mostra o conteúdo (repr aparece em traceback, em log com %r, no depurador e em mensagem de erro).

Valores FICTÍCIOS."""

from __future__ import annotations

import asyncio

from api.cache import Capturada
from sigaa.cache import Entrada
from sigaa.client import Compartilhado, Page, SigaaClient
from sigaa.pool import PoolSigaa

JSESSION = "JSESSIONFICTICIO0123456789"
DADO = "Fulano Ficticio da Silva"  # "dado pessoal" vindo do SIGAA


def test_sigaaclient_e_pool_nao_mostram_cookie():
    async def go():
        cli = SigaaClient("http://127.0.0.1:9", cookies={"JSESSIONID": JSESSION})
        pool = PoolSigaa(cli, lambda: SigaaClient("http://127.0.0.1:9"))
        try:
            for obj in (cli, pool):
                assert JSESSION not in repr(obj) and JSESSION not in str(obj)
        finally:
            await cli.close()

    asyncio.run(go())


def test_page_nao_mostra_o_html():
    p = Page(url="https://h/sigaa/portal.jsf", status=200, content=f"<html>{DADO}</html>".encode("latin-1"),
             content_type="text/html", headers={"set-cookie": f"JSESSIONID={JSESSION}"})
    assert DADO not in repr(p) and JSESSION not in repr(p)
    assert "portal.jsf" in repr(p)  # o repr continua útil pra depurar


def test_entradas_de_cache_nao_mostram_o_corpo():
    corpo = f'{{"nome": "{DADO}"}}'.encode()
    assert DADO not in repr(Entrada(corpo=corpo, criado=0.0, ttl=60, sensivel=True))
    assert DADO not in repr(Capturada(status=200, headers=[], corpo=corpo))


def test_compartilhado_nao_mostra_dado_do_aluno():
    c = Compartilhado()
    c.memo["perfil"] = (0.0, {"nome": DADO})
    c.dados["nome"] = DADO
    assert DADO not in repr(c)
