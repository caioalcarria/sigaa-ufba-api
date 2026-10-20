"""SEG·AUTH — token, sessão, logout, Basic e credencial guardada (sem rede: o login no SIGAA é falso)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import runpy
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from api import cache as C
from api import sessions as S
from api.config import config
from api.deps import SessaoAtual
from api.main import app
from sigaa import cache as SC
from sigaa.client import SigaaClient
from sigaa.errors import CredenciaisInvalidas

RAIZ = Path(__file__).resolve().parents[2]
_PREAQUECER_REAL = C.CacheHTTP._preaquecer


@pytest.fixture(autouse=True)
def sigaa_falso(monkeypatch):
    """Login/logout do SigaaClient sem rede: senha ``errada`` = credenciais inválidas."""
    chamadas = {"login": [], "logout": 0}

    async def login(self, usuario, senha):
        chamadas["login"].append(usuario)
        if senha == "errada":
            raise CredenciaisInvalidas("Usuário e/ou senha inválidos.")
        self.logado = True

    async def logout(self):
        chamadas["logout"] += 1
        self.logado = False

    monkeypatch.setattr(SigaaClient, "login", login)
    monkeypatch.setattr(SigaaClient, "logout", logout)
    monkeypatch.setattr(config, "POOL_AQUECER", 1)
    # nada sai pra rede: cliente apontado pra um buraco negro local e sem pré-aquecimento do cache
    monkeypatch.setattr(config, "SIGAA_URL", "http://127.0.0.1:9")

    async def sem_preaquecer(self, base, token):
        return None

    monkeypatch.setattr(C.CacheHTTP, "_preaquecer", sem_preaquecer)
    S.gerenciador._sessoes.clear()
    S.gerenciador.limite_login._eventos.clear()
    yield chamadas
    S.gerenciador._sessoes.clear()
    S.gerenciador.limite_login._eventos.clear()


def _cli(a=app, ip="127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=a, client=(ip, 5000)), base_url="http://t")


def _basic(u: str, s: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{s}".encode()).decode()}


# --------------------------------------------------------------------- token
@pytest.mark.asyncio
async def test_token_tem_256_bits_e_servidor_guarda_so_o_hash():
    g = S.Gerenciador()
    token, sess = await g.criar("fulano", "x")
    assert len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) == 32
    assert token not in g._sessoes and S._hash(token) in g._sessoes
    assert all(token not in k for k in g._sessoes)
    await g.parar()


@pytest.mark.asyncio
async def test_logout_mata_o_token_e_ele_nao_volta():
    async with _cli() as c:
        r = await c.post("/v1/auth/login", json={"usuario": "fulano", "senha": "x"})
        tok = r.json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        assert (await c.get("/v1/auth/sessao", headers=h)).status_code == 200
        assert (await c.delete("/v1/auth/sessao", headers=h)).status_code == 204
        for _ in range(2):
            r = await c.get("/v1/auth/sessao", headers=h)
            assert r.status_code == 401 and r.json()["erro"]["codigo"] == "token_invalido"
    assert S.gerenciador.total == 0


@pytest.mark.asyncio
async def test_token_de_um_nao_acessa_outro():
    async with _cli() as c:
        ta = (await c.post("/v1/auth/login", json={"usuario": "aluno.a", "senha": "x"})).json()["token"]
        tb = (await c.post("/v1/auth/login", json={"usuario": "aluno.b", "senha": "x"})).json()["token"]
    sa, sb = await S.gerenciador.obter(ta), await S.gerenciador.obter(tb)
    assert sa is not sb and sa.cliente is not sb.cliente and sa.pool is not sb.pool
    assert sa.usuario_hash != sb.usuario_hash


# ------------------------------------------------------- credencial guardada
@pytest.mark.asyncio
async def test_repr_da_sessao_nao_mostra_credencial():
    g = S.Gerenciador()
    _, sess = await g.criar("fulano", "senha-secreta", lembrar=True)
    assert sess._cred  # lembrar guarda a senha cifrada...
    r = repr(sess)
    assert "_cred" not in r and sess._cred.decode() not in r and "senha-secreta" not in r  # ...mas nunca no repr
    await g.parar()


@pytest.mark.asyncio
async def test_logout_esquece_a_credencial_do_cliente_e_do_pool():
    g = S.Gerenciador()
    token, sess = await g.criar("fulano", "senha-secreta", lembrar=True)
    cli, pool = sess.cliente, sess.pool
    assert cli._credenciais is not None and pool._credenciais is not None
    assert await g.encerrar(token)
    assert cli._credenciais is None and pool._credenciais is None and sess._cred is None
    assert all(s._credenciais is None for s in pool.sessoes)


@pytest.mark.asyncio
async def test_sessao_derrubada_pelo_teto_por_usuario_tambem_esquece(monkeypatch):
    monkeypatch.setattr(config, "MAX_SESSOES_POR_USUARIO", 2)
    g = S.Gerenciador()
    t1, s1 = await g.criar("fulano", "x", lembrar=True)
    await g.criar("fulano", "x", lembrar=True)
    await g.criar("fulano", "x", lembrar=True)  # derruba a mais antiga
    assert await g.obter(t1) is None
    assert s1.cliente._credenciais is None and s1.pool._credenciais is None and s1._cred is None
    await g.parar()


@pytest.mark.asyncio
async def test_expurgo_por_ociosidade_e_absoluto(monkeypatch):
    g = S.Gerenciador()
    t1, s1 = await g.criar("a", "x", lembrar=True)
    t2, s2 = await g.criar("b", "x", lembrar=True)
    s1.ultimo_uso -= config.TOKEN_OCIOSO_MIN * 60 + 1
    s2.expira_em = time.time() - 1
    assert await g.obter(t1) is None and await g.obter(t2) is None
    assert g.total == 0 and s1.cliente._credenciais is None and s2.cliente._credenciais is None


@pytest.mark.asyncio
async def test_identificar_sem_tocar_respeita_ociosidade():
    """O cache (L1) e o pré-aquecimento olham a sessão sem 'tocar' — token ocioso não pode identificar."""
    g = S.gerenciador
    token, sess = await g.criar("fulano", "x")
    sess.ultimo_uso -= config.TOKEN_OCIOSO_MIN * 60 + 1
    assert await C.identificar({"authorization": f"Bearer {token}"}, tocar=False) is None


# --------------------------------------------------------------------- Basic
def test_basic_desligado_por_padrao(monkeypatch):
    monkeypatch.delenv("SIGAA_API_PERMITIR_BASIC", raising=False)
    assert runpy.run_path(str(RAIZ / "api" / "config.py"))["Config"].PERMITIR_BASIC is False
    monkeypatch.setenv("SIGAA_API_PERMITIR_BASIC", "true")
    assert runpy.run_path(str(RAIZ / "api" / "config.py"))["Config"].PERMITIR_BASIC is True


@pytest.mark.asyncio
async def test_basic_desligado_responde_401(monkeypatch):
    monkeypatch.setattr(config, "PERMITIR_BASIC", False)
    async with _cli() as c:
        r = await c.get("/v1/auth/sessao", headers=_basic("fulano", "x"))
    assert r.status_code == 401 and r.json()["erro"]["codigo"] == "nao_autenticado"


@pytest.mark.asyncio
async def test_chave_basic_nao_e_sha256_cru_da_senha(monkeypatch):
    monkeypatch.setattr(config, "PERMITIR_BASIC", True)
    await S.gerenciador.obter_basic("fulano", "senha-secreta")
    cru = "basic:" + hashlib.sha256(b"fulano\x00senha-secreta").hexdigest()
    assert cru not in S.gerenciador._sessoes
    assert len([k for k in S.gerenciador._sessoes if k.startswith("basic:")]) == 1


@pytest.mark.asyncio
async def test_logout_basic_encerra_a_sessao_de_verdade(monkeypatch, sigaa_falso):
    monkeypatch.setattr(config, "PERMITIR_BASIC", True)
    async with _cli() as c:
        assert (await c.get("/v1/auth/sessao", headers=_basic("fulano", "x"))).status_code == 200
        sess = next(iter(S.gerenciador._sessoes.values()))
        assert (await c.delete("/v1/auth/sessao", headers=_basic("fulano", "x"))).status_code == 204
    assert S.gerenciador.total == 0  # antes: só o logout no SIGAA, a sessão (com a senha cifrada) ficava
    assert sess._cred is None and sess.cliente._credenciais is None


@pytest.mark.asyncio
async def test_basic_reaproveitado_nao_gasta_o_limite_de_login(monkeypatch, sigaa_falso):
    monkeypatch.setattr(config, "PERMITIR_BASIC", True)
    monkeypatch.setattr(S.gerenciador.limite_login, "maximo", 3)
    async with _cli() as c:
        for _ in range(10):
            r = await c.get("/v1/auth/sessao", headers=_basic("fulano", "x"))
            assert r.status_code == 200, r.text
    assert len(sigaa_falso["login"]) == 1


@pytest.mark.asyncio
async def test_basic_senha_errada_nao_cria_sessao(monkeypatch):
    monkeypatch.setattr(config, "PERMITIR_BASIC", True)
    async with _cli() as c:
        await c.get("/v1/auth/sessao", headers=_basic("fulano", "x"))
        r = await c.get("/v1/auth/sessao", headers=_basic("fulano", "errada"))
    assert r.status_code == 401 and r.json()["erro"]["codigo"] == "credenciais_invalidas"
    assert S.gerenciador.total == 1  # a sessão da senha certa não é entregue pra senha errada


# ------------------------------------------------------------ erros de login
@pytest.mark.asyncio
async def test_422_do_login_nao_ecoa_a_senha():
    async with _cli() as c:
        r = await c.post("/v1/auth/login", json={"senha": "Segredo-Xyz-123"})
        assert r.status_code == 422 and r.json()["erro"]["codigo"] == "requisicao_invalida"
        assert "Segredo-Xyz-123" not in r.text
        r = await c.post("/v1/auth/login", json={"usuario": "fulano", "senha": "Segredo-Xyz-123", "lembrar": "talvez"})
        assert r.status_code == 422 and "Segredo-Xyz-123" not in r.text


@pytest.mark.asyncio
async def test_login_errado_nao_ecoa_usuario_nem_senha():
    async with _cli() as c:
        r = await c.post("/v1/auth/login", json={"usuario": "usuario.unico.9", "senha": "errada"})
    assert r.status_code == 401 and r.json()["erro"]["codigo"] == "credenciais_invalidas"
    assert "usuario.unico.9" not in r.text and "errada" not in r.text


@pytest.mark.asyncio
async def test_mensagem_de_login_recusado_e_unica(monkeypatch):
    """Qualquer recusa do SIGAA (usuário inexistente, bloqueado...) vira a MESMA mensagem: sem enumeração."""
    monkeypatch.undo()  # usa o login de verdade, com transporte falso
    pag_login = '<form action="/sigaa/logar.do"><input name="user.senha"></form>'

    def resp(msg: str):
        def h(req: httpx.Request) -> httpx.Response:
            if "logar.do" in str(req.url):
                return httpx.Response(200, html=f'<div class="erros">{msg} fulano.tal</div>{pag_login}')
            return httpx.Response(200, html=pag_login)
        return h

    textos = set()
    for msg in ("Usuário não encontrado", "Usuário bloqueado", "Senha expirada"):
        cli = SigaaClient("http://sigaa.teste", transport=httpx.MockTransport(resp(msg)), min_interval=0, folga=0)
        with pytest.raises(CredenciaisInvalidas) as e:
            await cli.login("fulano.tal", "x")
        await cli.close()
        textos.add(str(e.value))
    assert textos == {"Usuário e/ou senha inválidos."}


# ---------------------------------------------------------- pré-aquecimento
@pytest.mark.asyncio
async def test_logout_cancela_o_preaquecimento_em_curso(monkeypatch):
    """Logout no meio do pré-aquecimento: o passo em curso é cancelado e nada do aluno fica no cache."""
    monkeypatch.setattr(C.CacheHTTP, "_preaquecer", _PREAQUECER_REAL)  # app de teste, sem SIGAA
    SC.cache.usar(SC.Memoria())
    SC.cache.ligado = True
    ch: dict[str, int] = {}
    a = FastAPI()

    @a.get("/v1/lenta")
    async def lenta(sess: SessaoAtual):
        await asyncio.sleep(0.5)
        ch["lenta"] = ch.get("lenta", 0) + 1
        return {"ok": 1}

    @a.post("/v1/auth/login")
    async def login(corpo: dict):
        agora = time.time()
        S.gerenciador._sessoes[S._hash("tokA")] = S.Sessao(
            cliente=None, pool=None, usuario_hash="aluno-a", criada_em=agora, expira_em=agora + 3600, lembrar=False
        )
        return {"token": "tokA"}

    @a.delete("/v1/auth/sessao", status_code=204)
    async def logout(sess: SessaoAtual):
        S.gerenciador._sessoes.pop(S._hash("tokA"), None)

    a.add_middleware(C.CacheHTTP)
    async with _cli(a) as c:
        await c.get("/v1/publico/x")  # monta a pilha
        inst = a.middleware_stack
        while not isinstance(inst, C.CacheHTTP):
            inst = inst.app
        inst.rotas_preaquecer, inst.espera_preaquecer, inst.silencio_preaquecer = ["/v1/lenta"], 0, 0
        await c.post("/v1/auth/login", json={})
        await asyncio.sleep(0.15)  # o passo já está rodando
        assert (await c.delete("/v1/auth/sessao", headers={"Authorization": "Bearer tokA"})).status_code == 204
        await asyncio.sleep(0.7)
    assert "lenta" not in ch
    assert await SC.cache.limpar_aluno("aluno-a") == 0
    assert not inst._passo and not inst.ultimo_fim


# ------------------------------------------------------------------ processo
def test_endurecer_processo_desliga_core_dump():
    codigo = (
        "import ctypes, resource; from api.sessions import endurecer_processo; endurecer_processo();"
        "libc = ctypes.CDLL(None); print(resource.getrlimit(resource.RLIMIT_CORE), libc.prctl(3, 0, 0, 0, 0))"
    )
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "(0, 0) 0"
