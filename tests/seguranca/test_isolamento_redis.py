"""Isolamento entre alunos no backend Redis e no segredo do cache (``sigaa/cache.py``).

Sem servidor Redis: um Redis FALSO em memória (get/set/delete/scan_iter) entra no lugar do
``redis.asyncio`` — o que se testa é o que o backend grava e o que ele aceita de volta."""

from __future__ import annotations

import fnmatch
import logging
import sys
import time
import types

import pytest

from sigaa import cache as SC

pytestmark = pytest.mark.asyncio


class RedisFalso:
    def __init__(self) -> None:
        self.d: dict[bytes, bytes] = {}

    async def get(self, k):
        return self.d.get(k.encode() if isinstance(k, str) else k)

    async def set(self, k, v, ex=None):
        self.d[k.encode() if isinstance(k, str) else k] = v

    async def delete(self, k):
        self.d.pop(k.encode() if isinstance(k, str) else k, None)

    async def scan_iter(self, match="*", count=None):
        for k in list(self.d):
            if fnmatch.fnmatchcase(k.decode(), match):
                yield k

    async def aclose(self):
        pass


@pytest.fixture
def redis_falso(monkeypatch):
    servidor = RedisFalso()  # um "servidor" só: vários backends = vários workers
    mod = types.ModuleType("redis")
    sub = types.ModuleType("redis.asyncio")
    sub.from_url = lambda url, **kw: servidor
    mod.asyncio = sub
    monkeypatch.setitem(sys.modules, "redis", mod)
    monkeypatch.setitem(sys.modules, "redis.asyncio", sub)
    return servidor


def _entrada(corpo: bytes, sensivel: bool) -> SC.Entrada:
    return SC.Entrada(corpo=corpo, criado=time.time(), ttl=60, sensivel=sensivel, headers=[("content-type", "application/json")])


async def test_valor_cifrado_de_um_aluno_copiado_pra_chave_de_outro_e_recusado(redis_falso):
    """ISO-02: a cifra não amarrava a chave — quem escreve no Redis copiava o valor do aluno A pra
    chave do aluno B e o B recebia o histórico do A (decifrava normal)."""
    w1 = SC.Redis("redis://127.0.0.1:6379/0", segredo=b"s" * 32, prefixo="t:")
    await w1.gravar("u:AAAA:/v1/historico?", _entrada(b'{"nome":"ALUNO A FICTICIO"}', True))
    redis_falso.d[b"t:u:BBBB:/v1/historico?"] = redis_falso.d[b"t:u:AAAA:/v1/historico?"]
    w2 = SC.Redis("redis://127.0.0.1:6379/0", segredo=b"s" * 32, prefixo="t:")  # outro worker, L0 vazio
    assert await w2.obter("u:BBBB:/v1/historico?") is None, "o aluno B recebeu o dado cifrado do aluno A"
    assert (await w2.obter("u:AAAA:/v1/historico?")).corpo == b'{"nome":"ALUNO A FICTICIO"}'


async def test_texto_claro_numa_chave_de_aluno_e_recusado(redis_falso):
    """ISO-02: o backend aceitava ``P`` (texto claro) em chave de aluno — dado injetado no Redis
    aparecia como se fosse do aluno."""
    w = SC.Redis("redis://127.0.0.1:6379/0", segredo=b"s" * 32, prefixo="t:")
    redis_falso.d[b"t:u:BBBB:/v1/me?"] = b"P" + _entrada(b'{"nome":"INJETADO"}', True).para_bytes()
    assert await w.obter("u:BBBB:/v1/me?") is None
    redis_falso.d[b"t:c:/v1/consultas/cursos?"] = b"P" + _entrada(b'{"ok":1}', False).para_bytes()
    assert (await w.obter("c:/v1/consultas/cursos?")).corpo == b'{"ok":1}'  # compartilhado em claro segue valendo


async def test_sem_segredo_dado_de_aluno_nunca_vai_pro_redis(redis_falso):
    w = SC.Redis("redis://127.0.0.1:6379/0", segredo=None, prefixo="t:")
    await w.gravar("u:AAAA:/v1/historico?", _entrada(b'{"nome":"ALUNO A FICTICIO"}', True))
    await w.gravar("c:/v1/consultas/cursos?", _entrada(b'{"ok":1}', False))
    assert b"t:u:AAAA:/v1/historico?" not in redis_falso.d
    assert redis_falso.d[b"t:c:/v1/consultas/cursos?"][:1] == b"P"
    assert (await w.obter("u:AAAA:/v1/historico?")).corpo == b'{"nome":"ALUNO A FICTICIO"}'  # na memória local
    w2 = SC.Redis("redis://127.0.0.1:6379/0", segredo=None, prefixo="t:")
    assert await w2.obter("u:AAAA:/v1/historico?") is None  # outro worker não vê


async def test_cifrado_nao_tem_o_dado_em_claro_e_limpar_aluno_apaga_tudo(redis_falso):
    w = SC.Redis("redis://127.0.0.1:6379/0", segredo=b"s" * 32, prefixo="t:")
    await w.gravar("u:AAAA:/v1/historico?", _entrada(b'{"nome":"ALUNO A FICTICIO"}', True))
    await w.gravar("u:BBBB:/v1/historico?", _entrada(b'{"nome":"ALUNO B FICTICIO"}', True))
    assert all(b"FICTICIO" not in v for v in redis_falso.d.values())
    await w.apagar_prefixo("u:AAAA:")
    assert await w.obter("u:AAAA:/v1/historico?") is None
    assert b"t:u:AAAA:/v1/historico?" not in redis_falso.d
    assert (await w.obter("u:BBBB:/v1/historico?")).corpo == b'{"nome":"ALUNO B FICTICIO"}'


# --------------------------------------------------------------------- segredo
async def test_segredo_curto_e_recusado(monkeypatch, caplog):
    """ISO-03: segredo de 8 caracteres virava a chave do HMAC e da cifra — com uma cópia do Redis dá
    pra testar segredos fracos offline e, achado, identificar e decifrar o dado de cada aluno."""
    monkeypatch.setenv("SIGAA_API_CACHE_SEGREDO", "curto123")
    monkeypatch.delenv("SIGAA_API_CACHE_SEGREDO_MIN", raising=False)
    with caplog.at_level(logging.WARNING, "sigaa_api.cache"):
        c = SC.Cache()
    assert c.segredo_configurado is False
    assert "IGNORADO" in caplog.text


async def test_segredo_medio_avisa_e_passa_por_kdf(monkeypatch, caplog):
    seg = "segredo-de-vinte-chars"
    monkeypatch.setenv("SIGAA_API_CACHE_SEGREDO", seg)
    with caplog.at_level(logging.WARNING, "sigaa_api.cache"):
        c1, c2 = SC.Cache(), SC.Cache()
    assert c1.segredo_configurado and "curto" in caplog.text
    assert c1.segredo != seg.encode() and seg.encode() not in c1.segredo  # nunca o segredo cru como chave
    assert c1.aluno("aluno-a") == c2.aluno("aluno-a")  # determinístico: todos os workers concordam
    assert c1.aluno("aluno-a") != c1.aluno("aluno-b")


async def test_sem_segredo_hmac_aleatorio_por_processo(monkeypatch):
    monkeypatch.delenv("SIGAA_API_CACHE_SEGREDO", raising=False)
    assert SC.Cache().aluno("aluno-a") != SC.Cache().aluno("aluno-a")


async def test_avisos_de_redis_sem_tls_sem_senha_sem_segredo(monkeypatch, caplog, redis_falso):
    monkeypatch.delenv("SIGAA_API_CACHE_SEGREDO", raising=False)
    monkeypatch.setenv("SIGAA_API_CACHE_URL", "redis://10.0.0.5:6379/0")
    with caplog.at_level(logging.WARNING, "sigaa_api.cache"):
        c = SC.Cache()
    assert c.backend.nome == "redis"
    assert "rediss://" in caplog.text and "sem senha" in caplog.text and "memória deste processo" in caplog.text
    caplog.clear()
    monkeypatch.setenv("SIGAA_API_CACHE_SEGREDO", "x" * 40)
    monkeypatch.setenv("SIGAA_API_CACHE_URL", "rediss://:senha-ficticia@redis.exemplo:6380/0")
    with caplog.at_level(logging.WARNING, "sigaa_api.cache"):
        SC.Cache()
    assert caplog.text == ""


async def test_pode_gravar_respeita_a_limpeza_do_aluno():
    c = SC.cache
    uh = "aluno-fict-" + str(time.time())
    chave = f"u:{c.aluno(uh)}:/v1/me?"
    antes = time.time()
    await c.limpar_aluno(uh)
    assert c.pode_gravar(chave, antes) is False  # começou antes da limpeza
    assert c.pode_gravar(chave, time.time() + 0.001) is True
    assert c.pode_gravar("c:/v1/consultas/cursos?", antes) is True
