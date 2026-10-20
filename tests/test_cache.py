"""Cache: L1 (middleware HTTP) e L2 (serviço compartilhado). Sem rede: app de teste + sessões falsas."""

from __future__ import annotations

import asyncio
import gzip
import json
import time

import httpx
import pytest
from fastapi import FastAPI, Response
from pydantic import BaseModel

from api import cache as C
from api import sessions as S
from api.deps import SessaoAtual
from sigaa import cache as SC

pytestmark = pytest.mark.asyncio


class Modelo(BaseModel):
    n: int
    itens: list[int] = []


def _app(chamadas: dict[str, int], atraso: float = 0.0) -> FastAPI:
    app = FastAPI()

    def conta(nome):
        chamadas[nome] = chamadas.get(nome, 0) + 1
        return chamadas[nome]

    @app.get("/v1/publico/teste")
    async def pub(x: int = 0):
        await asyncio.sleep(atraso)
        return {"x": x, "vez": conta("pub")}

    @app.get("/v1/eco")
    async def eco(sess: SessaoAtual, x: int = 0):
        await asyncio.sleep(atraso)
        return {"x": x, "dono": sess.usuario_hash, "vez": conta("eco")}

    @app.get("/v1/consultas/unidades/tipos")
    async def coisa(sess: SessaoAtual):
        return {"vez": conta("coisa")}

    @app.get("/v1/grande")
    async def grande(sess: SessaoAtual):
        conta("grande")
        return {"lista": list(range(5000))}

    @app.get("/v1/falha")
    async def falha(sess: SessaoAtual):
        conta("falha")
        return Response(status_code=502, content=b'{"erro":1}', media_type="application/json")

    @app.get("/v1/turmas/1/aulas")
    async def aulas(sess: SessaoAtual):
        await asyncio.sleep(0.05)
        conta("aulas")
        return {"aulas": []}

    @app.post("/v1/auth/login")
    async def login(corpo: dict):
        return {"token": corpo["token"]}

    @app.delete("/v1/auth/sessao", status_code=204)
    async def logout(sess: SessaoAtual):
        return None

    app.add_middleware(C.CacheHTTP)
    return app


def _sessao(token: str, usuario_hash: str) -> None:
    agora = time.time()
    S.gerenciador._sessoes[S._hash(token)] = S.Sessao(
        cliente=None, pool=None, usuario_hash=usuario_hash, criada_em=agora, expira_em=agora + 3600, lembrar=False
    )


@pytest.fixture(autouse=True)
def limpo():
    SC.cache.usar(SC.Memoria())
    SC.cache.ligado = True
    for k in SC.cache.stats:
        SC.cache.stats[k] = 0
    S.gerenciador._sessoes.clear()
    _sessao("tokA", "aluno-a")
    _sessao("tokA2", "aluno-a")
    _sessao("tokB", "aluno-b")
    yield
    S.gerenciador._sessoes.clear()


def _cli(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


A = {"Authorization": "Bearer tokA"}
A2 = {"Authorization": "Bearer tokA2"}
B = {"Authorization": "Bearer tokB"}


async def test_miss_depois_hit_com_metadados():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        r1 = await c.get("/v1/eco?x=1", headers=A)
        r2 = await c.get("/v1/eco?x=1", headers=A)
    assert r1.headers["x-cache"] == "MISS" and r2.headers["x-cache"] == "HIT"
    assert r1.json() == r2.json() and ch["eco"] == 1
    assert r2.headers["etag"] == r1.headers["etag"]
    assert r2.headers["cache-control"].startswith("private, max-age=")
    assert int(r2.headers["age"]) >= 0 and "x-cache-gerado-em" in r2.headers
    assert "Authorization" in r2.headers["vary"]


async def test_query_diferente_e_ordem_da_query():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/publico/teste?x=1&y=2")
        r = await c.get("/v1/publico/teste?y=2&x=1")
        assert r.headers["x-cache"] == "HIT"
        r = await c.get("/v1/publico/teste?x=2")
        assert r.headers["x-cache"] == "MISS"
    assert ch["pub"] == 2


async def test_aluno_nao_ve_dado_de_outro_mas_divide_entre_os_proprios_tokens():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        ra = await c.get("/v1/eco", headers=A)
        rb = await c.get("/v1/eco", headers=B)
        ra2 = await c.get("/v1/eco", headers=A2)
    assert ra.json()["dono"] == "aluno-a" and rb.json()["dono"] == "aluno-b"
    assert rb.headers["x-cache"] == "MISS"
    assert ra2.headers["x-cache"] == "HIT" and ra2.json()["dono"] == "aluno-a"
    assert ch["eco"] == 2
    # a chave não carrega o hash do aluno em claro
    assert not any("aluno-a" in k for k in SC.cache.backend._d)


async def test_compartilhado_entre_alunos_mas_exige_login():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/consultas/unidades/tipos", headers=A)
        r = await c.get("/v1/consultas/unidades/tipos", headers=B)
        assert r.headers["x-cache"] == "HIT"
        sem = await c.get("/v1/consultas/unidades/tipos")
        ruim = await c.get("/v1/consultas/unidades/tipos", headers={"Authorization": "Bearer inventado"})
    assert sem.status_code == 401 and ruim.status_code == 401 and "x-cache" not in sem.headers
    assert ch["coisa"] == 1


async def test_publico_sem_login_e_cache_control_public():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/publico/teste")
        r = await c.get("/v1/publico/teste")
    assert r.headers["x-cache"] == "HIT" and r.headers["cache-control"].startswith("public")
    assert ch["pub"] == 1


async def test_forcar_fresco():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        r = await c.get("/v1/eco?fresco=true", headers=A)
        assert r.headers["x-cache"] == "BYPASS" and r.json()["vez"] == 2
        r = await c.get("/v1/eco", headers={**A, "Cache-Control": "no-cache"})
        assert r.headers["x-cache"] == "BYPASS" and r.json()["vez"] == 3
        r = await c.get("/v1/eco", headers=A)  # o fresco atualizou o cache
        assert r.headers["x-cache"] == "HIT" and r.json()["vez"] == 3
        r = await c.get("/v1/eco", headers={**A, "Cache-Control": "no-store"})
        assert r.json()["vez"] == 4
        r = await c.get("/v1/eco", headers=A)  # no-store não gravou
        assert r.json()["vez"] == 3


async def test_etag_304():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        r = await c.get("/v1/eco", headers=A)
        r304 = await c.get("/v1/eco", headers={**A, "If-None-Match": r.headers["etag"]})
        rdif = await c.get("/v1/eco", headers={**A, "If-None-Match": '"outro"'})
    assert r304.status_code == 304 and r304.content == b""
    assert rdif.status_code == 200


async def test_gzip():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        r1 = await c.get("/v1/grande", headers={**A, "Accept-Encoding": "gzip"})
        r2 = await c.get("/v1/grande", headers={**A, "Accept-Encoding": "gzip"})
        cru = await c.get("/v1/grande", headers={**A, "Accept-Encoding": "identity"})
    assert r1.headers["content-encoding"] == "gzip" and r2.headers["content-encoding"] == "gzip"
    assert r2.json() == cru.json() and "content-encoding" not in cru.headers
    assert int(r2.headers["content-length"]) < len(cru.content) * 0.6


async def test_erro_nao_entra_no_cache():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        for _ in range(3):
            r = await c.get("/v1/falha", headers=A)
            assert r.status_code == 502
    assert ch["falha"] == 3


async def test_singleflight():
    ch: dict[str, int] = {}
    async with _cli(_app(ch, atraso=0.2)) as c:
        rs = await asyncio.gather(*[c.get("/v1/eco?x=9", headers=A) for _ in range(20)])
    assert all(r.status_code == 200 for r in rs)
    assert ch["eco"] == 1
    assert len({r.json()["vez"] for r in rs}) == 1


async def test_stale_while_revalidate(monkeypatch):
    monkeypatch.setattr(C, "REGRAS", [(C.re.compile(r"^/v1/eco"), C.Politica(C.ALUNO, 0.1, 30))] + C.REGRAS)
    ch: dict[str, int] = {}
    async with _cli(_app(ch, atraso=0.05)) as c:
        await c.get("/v1/eco", headers=A)
        await asyncio.sleep(0.15)
        t0 = time.perf_counter()
        r = await c.get("/v1/eco", headers=A)
        rapido = time.perf_counter() - t0
        assert r.headers["x-cache"] == "STALE" and r.json()["vez"] == 1
        assert rapido < 0.04  # não esperou o "SIGAA"
        await asyncio.sleep(0.15)  # a revalidação em 2º plano terminou
        assert ch["eco"] == 2
        r = await c.get("/v1/eco", headers=A)
        assert r.json()["vez"] == 2
    assert SC.cache.stats["revalidou"] == 1


async def test_preaquecimento_apos_login(monkeypatch):
    ch: dict[str, int] = {}
    app = _app(ch)
    async with _cli(app) as c:
        r = await c.post("/v1/auth/login", json={"token": "tokA"})
        assert r.status_code == 200
        # acha a instância do middleware e troca as rotas aquecidas
        inst = app.middleware_stack
        while not isinstance(inst, C.CacheHTTP):
            inst = inst.app
        inst.rotas_preaquecer = ["/v1/eco", "/v1/turmas/1/aulas"]
        inst.espera_preaquecer = 0
        inst.silencio_preaquecer = 0
        r = await c.post("/v1/auth/login", json={"token": "tokA"})
        await asyncio.sleep(0.8)
        r1 = await c.get("/v1/eco", headers=A)
        r2 = await c.get("/v1/turmas/1/aulas", headers=A)
    assert r1.headers["x-cache"] == "HIT" and r2.headers["x-cache"] == "HIT"
    assert ch["eco"] == 1 and ch["aulas"] == 1
    assert SC.cache.stats["preaquecido"] == 2


async def test_preaquecimento_cede_a_vez_e_junta_no_singleflight():
    ch: dict[str, int] = {}
    app = _app(ch, atraso=0.1)
    async with _cli(app) as c:
        await c.get("/v1/publico/teste")  # monta a pilha
        inst = app.middleware_stack
        while not isinstance(inst, C.CacheHTTP):
            inst = inst.app
        inst.rotas_preaquecer = ["/v1/turmas/1/aulas", "/v1/eco"]
        inst.espera_preaquecer = 0.02
        await c.post("/v1/auth/login", json={"token": "tokA"})
        # o aluno pede /v1/eco logo depois do login: o aquecimento espera ele terminar
        r = await c.get("/v1/eco", headers=A)
        assert r.headers["x-cache"] == "MISS"
        await asyncio.sleep(0.4)
    assert ch["eco"] == 1 and ch["aulas"] == 1


async def test_preaquecimento_e_cancelado_quando_o_aluno_pede_outra_rota():
    """Simula a trava da sessão: o passo de aquecimento lento solta a sessão quando o aluno chega."""
    ch: dict[str, int] = {}
    trava = asyncio.Lock()
    app = FastAPI()

    @app.get("/v1/lenta")
    async def lenta(sess: SessaoAtual):
        async with trava:
            await asyncio.sleep(0.6)
            ch["lenta"] = ch.get("lenta", 0) + 1
            return {"ok": 1}

    @app.get("/v1/rapida")
    async def rapida(sess: SessaoAtual):
        async with trava:
            await asyncio.sleep(0.02)
            return {"ok": 2}

    @app.post("/v1/auth/login")
    async def login(corpo: dict):
        return {"token": corpo["token"]}

    app.add_middleware(C.CacheHTTP)
    async with _cli(app) as c:
        await c.get("/v1/publico/x")  # monta a pilha
        inst = app.middleware_stack
        while not isinstance(inst, C.CacheHTTP):
            inst = inst.app
        inst.rotas_preaquecer = ["/v1/lenta"]
        inst.espera_preaquecer = 0
        inst.silencio_preaquecer = 0
        await c.post("/v1/auth/login", json={"token": "tokA"})
        await asyncio.sleep(0.1)  # o aquecimento já pegou a trava
        t0 = time.perf_counter()
        r = await c.get("/v1/rapida", headers=A)
        dt = time.perf_counter() - t0
        assert r.status_code == 200 and dt < 0.3, dt  # não esperou os 0,6 s do aquecimento
        await asyncio.sleep(0.9)  # o aquecimento volta e termina a rota lenta
        r = await c.get("/v1/lenta", headers=A)
    assert r.headers["x-cache"] == "HIT" and ch["lenta"] == 1
    assert SC.cache.stats["preaquecimento_cedeu"] == 1


async def test_logout_apaga_o_cache_do_aluno():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        await c.get("/v1/eco", headers=B)
        r = await c.delete("/v1/auth/sessao", headers=A)
        assert r.status_code == 204
        r = await c.get("/v1/eco", headers=A2)
        assert r.headers["x-cache"] == "MISS"
        r = await c.get("/v1/eco", headers=B)
        assert r.headers["x-cache"] == "HIT"


async def test_desligado_passa_direto():
    SC.cache.ligado = False
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        r = await c.get("/v1/eco", headers=A)
    assert "x-cache" not in r.headers and ch["eco"] == 2


async def test_politicas():
    p = C.politica
    assert p("/v1/auth/login", {}).escopo is None
    assert p("/v1/status", {}).escopo is None
    assert p("/v1/publico/cursos/1/estruturas", {}).escopo == C.PUBLICO
    assert p("/v1/publico/turmas", {}).ttl == 10 * 60
    assert p("/v1/consultas/estruturas/9", {}).escopo == C.COMPARTILHADO
    assert p("/v1/consultas/estruturas/9/declaracao-prazo-maximo", {}).escopo == C.ALUNO
    assert p("/v1/calendario", {}).escopo == C.ALUNO
    assert p("/v1/calendario", {"ano": "2026", "periodo": "1"}).escopo == C.COMPARTILHADO
    assert p("/v1/historico", {}).escopo == C.ALUNO
    assert p("/v1/turmas/123/notas", {}).ttl == 10 * 60
    assert p("/v1/qualquer-coisa-nova", {}).escopo == C.ALUNO


# ---------------------------------------------------------------- L2 (serviço)
async def test_compartilhado_l2_entre_sessoes_e_copias_independentes():
    chamadas = []

    async def servico(c, x: int, completo: bool = False) -> Modelo:
        chamadas.append((c, x))
        await asyncio.sleep(0.05)
        return Modelo(n=x, itens=[1, 2])

    f = SC.compartilhado(60)(servico)
    v1, v2 = await asyncio.gather(f("sessaoA", 3), f("sessaoB", 3))  # singleflight
    v3 = await f("sessaoC", x=3)
    assert len(chamadas) == 1 and v1 == v2 == v3 == Modelo(n=3, itens=[1, 2])
    v1.itens.append(99)
    assert (await f("sessaoD", 3)).itens == [1, 2]  # ninguém altera o objeto do outro
    await f("sessaoA", 3, completo=True)
    assert len(chamadas) == 2


async def test_compartilhado_l2_erro_nao_cacheia():
    n = 0

    async def servico(c, x: int) -> Modelo:
        nonlocal n
        n += 1
        raise ValueError("ruim")

    f = SC.compartilhado(60)(servico)
    for _ in range(2):
        with pytest.raises(ValueError):
            await f(None, 1)
    assert n == 2


async def test_instalar_e_idempotente():
    from sigaa.services import consultas

    a = SC.instalar()
    fn = consultas.estrutura
    b = SC.instalar()
    assert "consultas.estrutura" in a and b and consultas.estrutura is fn
    assert getattr(consultas.estrutura, "__cache_compartilhado__", False)


# ---------------------------------------------------------------- backends
async def test_memoria_contabiliza_bytes_mesmo_com_gzip():
    m = SC.Memoria()
    e = SC.Entrada(corpo=json.dumps(list(range(3000))).encode(), criado=time.time(), ttl=60, headers=[("content-type", "application/json")])
    await m.gravar("a", e)
    e.gz()  # comprimir depois de gravar não pode desequilibrar a conta
    await m.apagar_prefixo("")
    assert m.bytes == 0


async def test_memoria_lru_por_bytes():
    m = SC.Memoria(max_bytes=10_000)
    for i in range(50):
        await m.gravar(f"k{i}", SC.Entrada(corpo=b"x" * 1000, criado=time.time(), ttl=60))
    assert m.bytes <= 10_000 and await m.obter("k49") is not None and await m.obter("k0") is None


async def test_entrada_serializa():
    e = SC.Entrada(corpo=b'{"a":1}', criado=123.0, ttl=5, swr=7, headers=[("content-type", "application/json")], sensivel=True)
    e2 = SC.Entrada.de_bytes(e.para_bytes())
    assert (e2.corpo, e2.ttl, e2.swr, e2.headers, e2.etag, e2.sensivel) == (e.corpo, 5, 7, e.headers, e.etag, True)


def _redis_ok(url="redis://127.0.0.1:6391/0") -> bool:
    import socket

    try:
        socket.create_connection(("127.0.0.1", 6391), timeout=0.2).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _redis_ok(), reason="sem Redis em 127.0.0.1:6391 (docker run -p 6391:6379 redis)")
async def test_redis_cifra_dado_de_aluno():
    import redis.asyncio as aioredis

    r = SC.Redis("redis://127.0.0.1:6391/0", segredo=b"s3gredo", prefixo="teste:")
    await r.limpar()
    await r.gravar("u:x:/v1/historico?", SC.Entrada(corpo=b'{"nome":"FULANO DE TAL"}', criado=time.time(), ttl=60, sensivel=True))
    await r.gravar("p:/v1/publico/a?", SC.Entrada(corpo=b'{"publico":1}', criado=time.time(), ttl=60))
    cru = aioredis.from_url("redis://127.0.0.1:6391/0")
    v = await cru.get("teste:u:x:/v1/historico?")
    assert v[:1] == b"F" and b"FULANO" not in v
    assert b"publico" in await cru.get("teste:p:/v1/publico/a?")
    r2 = SC.Redis("redis://127.0.0.1:6391/0", segredo=b"s3gredo", prefixo="teste:")  # "outro worker"
    assert (await r2.obter("u:x:/v1/historico?")).corpo == b'{"nome":"FULANO DE TAL"}'
    r3 = SC.Redis("redis://127.0.0.1:6391/0", segredo=None, prefixo="teste:")  # sem segredo: não lê nem grava sensível
    assert await r3.obter("u:x:/v1/historico?") is None
    await r3.gravar("u:y:/v1/me?", SC.Entrada(corpo=b"segredo", criado=time.time(), ttl=60, sensivel=True))
    assert await cru.get("teste:u:y:/v1/me?") is None
    await r.limpar()
    for x in (r, r2, r3):
        await x.fechar()
    await cru.aclose()
