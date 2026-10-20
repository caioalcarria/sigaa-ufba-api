"""Isolamento entre alunos no cache HTTP (L1, ``api/cache.py``).

Sem rede: app de teste + sessões falsas (dois alunos fictícios, ``aluno-a`` e ``aluno-b``). Cada
teste prova que o 2º aluno NUNCA recebe a resposta do 1º, ou que um dado de aluno não sobra no
cache depois de apagado."""

from __future__ import annotations

import asyncio
import base64
import time

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request, Response

from api import cache as C
from api import sessions as S
from api.config import config
from api.deps import SessaoAtual
from sigaa import cache as SC

pytestmark = pytest.mark.asyncio


def _app(ch: dict[str, int], portao: asyncio.Event | None = None) -> FastAPI:
    app = FastAPI()

    def conta(nome: str) -> int:
        ch[nome] = ch.get(nome, 0) + 1
        return ch[nome]

    @app.get("/v1/consultas/estruturas/{estrutura_id}/declaracao-prazo-maximo")
    async def declaracao(sess: SessaoAtual, estrutura_id: int):
        conta("declaracao")
        return {"estrutura": estrutura_id, "dono": sess.usuario_hash, "codigo_verificacao": f"cv-{sess.usuario_hash}"}

    @app.get("/v1/consultas/estruturas/{estrutura_id}")
    async def estrutura(sess: SessaoAtual, estrutura_id: int):
        conta("estrutura")
        return {"estrutura": estrutura_id}

    @app.get("/v1/consultas/minhas-solicitacoes")  # rota NOVA hipotética, por aluno, sob /v1/consultas
    async def novidade(sess: SessaoAtual):
        conta("novidade")
        return {"dono": sess.usuario_hash}

    @app.get("/v1/publico/eco")
    async def pub(x: int = 0):
        conta("pub")
        return {"x": x}

    @app.get("/v1/eco")
    async def eco(sess: SessaoAtual, request: Request):
        await asyncio.sleep(0.05)
        conta("eco")
        return {"dono": sess.usuario_hash}

    @app.get("/v1/negado")
    async def negado(sess: SessaoAtual, request: Request):
        await asyncio.sleep(0.05)
        conta("negado")
        if request.headers["authorization"].endswith("tokA"):
            return Response(status_code=403, content=b'{"erro":"acesso_negado"}', media_type="application/json")
        return {"dono": sess.usuario_hash}

    @app.get("/v1/lento")
    async def lento(sess: SessaoAtual):
        conta("lento")
        if portao is not None:
            await portao.wait()
        return {"dono": sess.usuario_hash, "vez": ch["lento"]}

    @app.post("/v1/auth/login")
    async def login(corpo: dict):
        return {"token": corpo["token"]}

    @app.delete("/v1/auth/sessao", status_code=204)
    async def logout(request: Request, sess: SessaoAtual):
        await S.gerenciador.encerrar_por_chave(S._hash(request.headers["authorization"].partition(" ")[2]))

    app.include_router(C.router)
    app.add_middleware(C.CacheHTTP)
    return app


class _PoolFalso:
    async def fechar(self) -> None:
        pass


def _sessao(token: str, usuario_hash: str, *, chave: str | None = None, ocioso_s: float = 0.0) -> S.Sessao:
    agora = time.time()
    sess = S.Sessao(
        cliente=None, pool=_PoolFalso(), usuario_hash=usuario_hash, criada_em=agora - ocioso_s,
        expira_em=agora + 3600, lembrar=False, ultimo_uso=agora - ocioso_s,
    )
    S.gerenciador._sessoes[chave or S._hash(token)] = sess
    return sess


@pytest.fixture(autouse=True)
def limpo(monkeypatch):
    monkeypatch.setattr(config, "SIGAA_URL", "http://127.0.0.1:9")  # nada de SIGAA real, nem por acidente

    async def criar_recusa(*a, **k):  # Basic com credencial nova = login no SIGAA: aqui sempre recusa
        raise HTTPException(401, detail={"codigo": "credenciais_invalidas", "mensagem": "teste"})

    monkeypatch.setattr(S.gerenciador, "criar", criar_recusa)
    SC.cache.usar(SC.Memoria())
    SC.cache.ligado = True
    getattr(SC.cache, "_limpo_em", {}).clear()
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


def _middleware(app) -> C.CacheHTTP:
    inst = app.middleware_stack
    while not isinstance(inst, C.CacheHTTP):
        inst = inst.app
    return inst


# ------------------------------------------------------------- regras (escopo)
@pytest.mark.parametrize("ident", ["+5", "5.0", "%205", "5_0", "%2B5"])
async def test_declaracao_com_id_nao_canonico_nao_vaza_pra_outro_aluno(ident):
    """ISO-01: ``/consultas/estruturas/+5/declaracao-prazo-maximo`` não casava com ``\\d+`` e caía na
    regra COMPARTILHADA — o documento emitido pro aluno A (com o código de verificação dele) ia pro B."""
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        ra = await c.get(f"/v1/consultas/estruturas/{ident}/declaracao-prazo-maximo", headers=A)
        rb = await c.get(f"/v1/consultas/estruturas/{ident}/declaracao-prazo-maximo", headers=B)
    assert ra.status_code == rb.status_code == 200
    assert ra.json()["dono"] == "aluno-a"
    assert rb.json()["dono"] == "aluno-b", "o aluno B recebeu a declaração do aluno A"
    assert rb.headers["x-cache"] == "MISS" and ch["declaracao"] == 2


async def test_rota_nova_em_consultas_e_por_aluno_por_padrao():
    """ISO-01: o curinga ``^/v1/consultas/`` era COMPARTILHADO — qualquer rota nova por aluno sob
    /v1/consultas vazaria. Agora só as rotas conhecidas de dado público são compartilhadas."""
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/consultas/minhas-solicitacoes", headers=A)
        rb = await c.get("/v1/consultas/minhas-solicitacoes", headers=B)
    assert rb.json()["dono"] == "aluno-b"


async def test_rotas_publicas_de_consultas_continuam_compartilhadas():
    p = C.politica
    comp = {
        "/v1/consultas/cursos": 24 * C.H, "/v1/consultas/cursos/ids": 24 * C.H,
        "/v1/consultas/componentes": 24 * C.H, "/v1/consultas/componentes/filtros": 24 * C.H,
        "/v1/consultas/componentes/123": 24 * C.H, "/v1/consultas/estruturas": 24 * C.H,
        "/v1/consultas/estruturas/9": 24 * C.H, "/v1/consultas/turmas/filtros": 24 * C.H,
        "/v1/consultas/unidades": 24 * C.H, "/v1/consultas/unidades/tipos": 24 * C.H,
        "/v1/consultas/turmas": 10 * C.M, "/v1/consultas/turmas/77": 5 * C.M,
        "/v1/consultas/turmas/77/processamento": 5 * C.M, "/v1/calendario/lista": 24 * C.H,
    }
    for path, ttl in comp.items():
        pol = p(path, {})
        assert (pol.escopo, pol.ttl) == (C.COMPARTILHADO, ttl), path
    for ident in ("9", "+9", "9.0", " 9", "9_0", "٩"):
        assert p(f"/v1/consultas/estruturas/{ident}/declaracao-prazo-maximo", {}).escopo == C.ALUNO, ident
    assert p("/v1/calendario", {}).escopo == C.ALUNO
    assert p("/v1/calendario", {"ano": "2026"}).escopo == C.ALUNO
    assert p("/v1/calendario", {"ano": "2026", "periodo": "1"}).escopo == C.COMPARTILHADO


# ------------------------------------------------------------------ chave
async def test_query_com_parametro_repetido_nao_colide():
    """ISO-06: ``?x=1&x=2`` e ``?x=2&x=1`` davam a MESMA chave (pares ordenados), mas a rota vê o
    último valor — dava pra envenenar a cópia compartilhada/pública de outra combinação."""
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        r1 = await c.get("/v1/publico/eco?x=1&x=2")
        r2 = await c.get("/v1/publico/eco?x=2&x=1")
    assert r1.json() == {"x": 2}
    assert r2.json() == {"x": 1}, "a 2ª ordem recebeu a resposta da 1ª"


async def test_dois_authorization_nao_grava_dado_de_um_aluno_na_chave_do_outro():
    """ISO-05: o middleware identificava pelo ÚLTIMO ``Authorization`` e a rota (Starlette) usa o
    PRIMEIRO — a resposta do B era gravada na chave do A."""
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        dois = httpx.Headers([("authorization", "Bearer tokB"), ("authorization", "Bearer tokA")])
        r = await c.get("/v1/eco", headers=dois)
        assert r.json()["dono"] == "aluno-b"
        ra = await c.get("/v1/eco", headers=A)
    assert ra.json()["dono"] == "aluno-a", "o aluno A recebeu o dado do aluno B"


async def test_cabecalhos_que_nao_mudam_a_resposta_nao_separam_alunos():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers={**A, "Accept-Language": "en"})
        rb = await c.get("/v1/eco", headers={**B, "Accept-Language": "en"})
    assert rb.json()["dono"] == "aluno-b"


# ------------------------------------------------------------ identificação
async def test_token_invalido_ou_ausente_nunca_recebe_hit_compartilhado():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        assert (await c.get("/v1/consultas/estruturas/9", headers=A)).status_code == 200
        assert (await c.get("/v1/consultas/estruturas/9", headers=B)).headers["x-cache"] == "HIT"
        for h in ({}, {"Authorization": "Bearer lixo"}, {"Authorization": "Basic " + base64.b64encode(b"x:y").decode()}):
            r = await c.get("/v1/consultas/estruturas/9", headers=h)
            assert r.status_code == 401 and "x-cache" not in r.headers, h


async def test_bearer_ocioso_nao_recebe_hit():
    _sessao("tokVelho", "aluno-a", ocioso_s=config.TOKEN_OCIOSO_MIN * 60 + 5)
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        r = await c.get("/v1/eco", headers={"Authorization": "Bearer tokVelho"})
    assert r.status_code == 401 and "x-cache" not in r.headers


async def test_identificar_sem_tocar_respeita_ociosidade():
    """ISO-04: ``tocar=False`` (logout, pré-aquecimento) só olhava ``expira_em``."""
    _sessao("tokVelho", "aluno-a", ocioso_s=config.TOKEN_OCIOSO_MIN * 60 + 5)
    assert await C.identificar({"authorization": "Bearer tokVelho"}, tocar=False) is None
    assert await C.identificar({"authorization": "Bearer tokA"}, tocar=False) == "aluno-a"


def _basic(u: str, s: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{s}".encode()).decode()}


async def test_basic_ocioso_nao_recebe_hit_nem_reaproveita_a_sessao(monkeypatch):
    """ISO-04: a sessão Basic ociosa além de TOKEN_OCIOSO_MIN ainda servia HIT (e a rota a
    reaproveitava). Agora ela é tratada como expirada: a credencial é validada de novo."""
    chave = "basic:" + S._hash("fulano\x00senha-ficticia")
    _sessao("", "aluno-a", chave=chave, ocioso_s=config.TOKEN_OCIOSO_MIN * 60 + 5)
    criadas: list[str] = []

    async def criar(usuario, senha, *, lembrar=False, origem="token"):  # login NOVO (validaria a senha no SIGAA)
        criadas.append(usuario)
        return "tok-novo", _sessao("tok-novo", "aluno-a")

    monkeypatch.setattr(S.gerenciador, "criar", criar)
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)  # o cache do aluno A está quente
        r = await c.get("/v1/eco", headers=_basic("fulano", "senha-ficticia"))
    assert r.status_code == 200 and r.headers.get("x-cache") != "HIT"
    assert criadas == ["fulano"], "a sessão Basic ociosa foi reaproveitada sem validar a senha de novo"


async def test_basic_ativo_recebe_hit_e_conta_como_uso():
    chave = "basic:" + S._hash("fulano\x00senha-ficticia")
    sess = _sessao("", "aluno-a", chave=chave, ocioso_s=60)
    antes = sess.ultimo_uso
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        r = await c.get("/v1/eco", headers=_basic("fulano", "senha-ficticia"))
    assert r.headers["x-cache"] == "HIT" and r.json()["dono"] == "aluno-a"
    assert sess.ultimo_uso > antes
    r = await C.identificar({"authorization": _basic("fulano", "outra-senha")["Authorization"]})
    assert r is None  # senha errada nunca acha a sessão (a chave leva a senha)


# ------------------------------------------------------------- singleflight
async def test_singleflight_nao_mistura_alunos():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        ra, rb, ra2 = await asyncio.gather(c.get("/v1/eco", headers=A), c.get("/v1/eco", headers=B), c.get("/v1/eco", headers=A2))
    assert ra.json()["dono"] == ra2.json()["dono"] == "aluno-a"
    assert rb.json()["dono"] == "aluno-b"
    assert ch["eco"] == 2  # A e A2 dividem (mesmo aluno); B voa sozinho


async def test_lider_com_403_nao_propaga_a_resposta_pros_seguidores():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        t1 = asyncio.create_task(c.get("/v1/negado", headers=A))
        await asyncio.sleep(0.01)
        r2 = await c.get("/v1/negado", headers=A2)
        r1 = await t1
    assert r1.status_code == 403
    assert r2.status_code == 200 and r2.json()["dono"] == "aluno-a"
    assert ch["negado"] == 2


async def test_revalidacao_stale_grava_so_na_chave_de_quem_pediu(monkeypatch):
    monkeypatch.setattr(C, "REGRAS", [(C.re.compile(r"^/v1/eco"), C.Politica(C.ALUNO, 0.1, 30))] + C.REGRAS)
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        await c.get("/v1/eco", headers=B)
        await asyncio.sleep(0.15)
        r = await c.get("/v1/eco", headers=A)
        assert r.headers["x-cache"] == "STALE"
        await asyncio.sleep(0.15)
        chave_a = C.montar_chave(C.politica("/v1/eco", {}), "/v1/eco", [], "aluno-a")
        chave_b = C.montar_chave(C.politica("/v1/eco", {}), "/v1/eco", [], "aluno-b")
        assert b"aluno-a" in (await SC.cache.backend.obter(chave_a)).corpo
        assert b"aluno-b" in (await SC.cache.backend.obter(chave_b)).corpo


# --------------------------------------------------------- limpeza / logout
async def test_resposta_em_voo_durante_a_limpeza_nao_volta_pro_cache():
    """ISO-07: um MISS (ou revalidação/pré-aquecimento) que já tinha saído pro SIGAA terminava
    DEPOIS do ``DELETE /v1/cache/meu``/logout e gravava de novo o dado do aluno."""
    portao = asyncio.Event()
    ch: dict[str, int] = {}
    async with _cli(_app(ch, portao)) as c:
        voo = asyncio.create_task(c.get("/v1/lento", headers=A))
        await asyncio.sleep(0.05)
        assert (await c.delete("/v1/cache/meu", headers=A2)).status_code == 204
        portao.set()
        assert (await voo).status_code == 200
        r = await c.get("/v1/lento", headers=A)
    assert r.headers["x-cache"] == "MISS", "o dado buscado antes da limpeza voltou pro cache"


async def test_limpar_meu_apaga_so_o_meu_inclusive_stale(monkeypatch):
    monkeypatch.setattr(C, "REGRAS", [(C.re.compile(r"^/v1/eco"), C.Politica(C.ALUNO, 0.05, 30))] + C.REGRAS)
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        await c.get("/v1/eco", headers=B)
        await asyncio.sleep(0.1)  # as duas entradas estão STALE
        await c.delete("/v1/cache/meu", headers=A)
        ra = await c.get("/v1/eco", headers=A)
        rb = await c.get("/v1/eco", headers=B)
    assert ra.headers["x-cache"] == "MISS"
    assert rb.headers["x-cache"] == "STALE"


async def test_preaquecimento_para_no_logout():
    ch: dict[str, int] = {}
    app = _app(ch)
    async with _cli(app) as c:
        await c.get("/v1/eco", headers=B)
        m = _middleware(app)
        m.rotas_preaquecer, m.espera_preaquecer, m.silencio_preaquecer = ["/v1/eco"], 0.1, 0
        await c.post("/v1/auth/login", json={"token": "tokA"})
        assert (await c.delete("/v1/auth/sessao", headers=A)).status_code == 204
        await asyncio.sleep(0.3)
    assert ch["eco"] == 1  # só o do B: o aquecimento do A não rodou depois do logout
    assert await SC.cache.backend.obter(C.montar_chave(C.politica("/v1/eco", {}), "/v1/eco", [], "aluno-a")) is None


# ------------------------------------------------------- cabeçalhos / stats
async def test_cache_control_nunca_public_fora_do_publico():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        for path, h in (("/v1/eco", A), ("/v1/consultas/estruturas/9", A)):
            await c.get(path, headers=h)
            r = await c.get(path, headers=h)
            assert r.headers["cache-control"].startswith("private"), path
            assert "Authorization" in r.headers["vary"], path
        r = await c.get("/v1/publico/eco")
        assert r.headers["cache-control"].startswith("public")


async def test_estatisticas_nao_expoem_nada_por_aluno():
    ch: dict[str, int] = {}
    async with _cli(_app(ch)) as c:
        await c.get("/v1/eco", headers=A)
        r = await c.get("/v1/cache/estatisticas")
    assert r.status_code == 200
    corpo = r.text
    for proibido in ("aluno-a", SC.cache.aluno("aluno-a"), "/v1/eco", "tokA"):
        assert proibido not in corpo
