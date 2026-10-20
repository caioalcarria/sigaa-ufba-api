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


def _basic(u: str, s: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{s}".encode()).decode()}
