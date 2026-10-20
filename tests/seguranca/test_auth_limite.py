"""SEG·AUTH — limite de login: por usuário (falhas), por IP, memória do limitador e X-Forwarded-For."""

from __future__ import annotations

import httpx
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api import cache as C
from api import sessions as S
from api.config import config
from api.main import app
from sigaa.client import SigaaClient
from sigaa.errors import CredenciaisInvalidas



@pytest.fixture(autouse=True)
def sigaa_falso(monkeypatch):
    chamadas = {"login": []}

    async def login(self, usuario, senha):
        chamadas["login"].append(usuario)
        if senha == "errada":
            raise CredenciaisInvalidas("Usuário e/ou senha inválidos.")
        self.logado = True

    async def logout(self):
        self.logado = False

    async def sem_preaquecer(self, base, token):
        return None

    monkeypatch.setattr(SigaaClient, "login", login)
    monkeypatch.setattr(SigaaClient, "logout", logout)
    monkeypatch.setattr(config, "POOL_AQUECER", 1)
    monkeypatch.setattr(config, "SIGAA_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(C.CacheHTTP, "_preaquecer", sem_preaquecer)
    S.gerenciador._sessoes.clear()
    S.gerenciador.limite_login._eventos.clear()
    if hasattr(S.gerenciador, "limite_usuario"):
        S.gerenciador.limite_usuario._eventos.clear()
    yield chamadas
    S.gerenciador._sessoes.clear()
    S.gerenciador.limite_login._eventos.clear()
    if hasattr(S.gerenciador, "limite_usuario"):
        S.gerenciador.limite_usuario._eventos.clear()


def _cli(a=app, ip="127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=a, client=(ip, 5000)), base_url="http://t")


async def _login(c, usuario, senha, **h):
    return await c.post("/v1/auth/login", json={"usuario": usuario, "senha": senha}, headers=h)


# ----------------------------------------------------------- por usuário
@pytest.mark.asyncio
async def test_forca_bruta_por_usuario_bloqueia_mesmo_vinda_de_varios_ips(sigaa_falso):
    """Falhas contam por USUÁRIO: trocar de IP não ajuda e a conta do aluno não toma força bruta no SIGAA."""
    n = int(getattr(config, "MAX_FALHAS_POR_USUARIO", 5))
    for i in range(n):
        async with _cli(ip=f"10.0.0.{i + 1}") as c:
            assert (await _login(c, "Vitima.Tal", "errada")).status_code == 401
    async with _cli(ip="10.9.9.9") as c:
        r = await _login(c, " vitima.tal ", "errada")  # mesma conta (sem diferenciar maiúscula/espaço)
        assert r.status_code == 429 and r.json()["erro"]["codigo"] == "muitas_tentativas"
        r = await _login(c, "vitima.tal", "certa")  # bloqueada: nem a senha certa vai pro SIGAA agora
        assert r.status_code == 429
        assert (await _login(c, "outro.aluno", "certa")).status_code == 200  # outra conta segue livre
    assert len(sigaa_falso["login"]) == n + 1  # as tentativas bloqueadas não chegaram ao SIGAA


@pytest.mark.asyncio
async def test_bloqueio_por_usuario_tem_a_mesma_resposta_do_bloqueio_por_ip(monkeypatch):
    """O 429 não revela se o bloqueio foi da conta (sem enumeração de usuário)."""
    monkeypatch.setattr(config, "MAX_FALHAS_POR_USUARIO", 1, raising=False)
    monkeypatch.setattr(S.gerenciador.limite_login, "maximo", 3)
    async with _cli(ip="10.1.1.1") as c:
        await _login(c, "conta.a", "errada")
        por_usuario = (await _login(c, "conta.a", "x")).json()
    async with _cli(ip="10.1.1.2") as c:
        for i in range(3):
            await _login(c, f"conta.{i}", "x")
        por_ip = (await _login(c, "conta.z", "x")).json()
    assert por_usuario == por_ip


@pytest.mark.asyncio
async def test_acerto_zera_as_falhas_do_usuario(monkeypatch):
    monkeypatch.setattr(config, "MAX_FALHAS_POR_USUARIO", 3, raising=False)
    async with _cli() as c:
        for _ in range(2):
            assert (await _login(c, "fulano", "errada")).status_code == 401
        assert (await _login(c, "fulano", "certa")).status_code == 200
        for _ in range(2):
            assert (await _login(c, "fulano", "errada")).status_code == 401
        assert (await _login(c, "fulano", "certa")).status_code == 200


@pytest.mark.asyncio
async def test_basic_tambem_conta_falhas_por_usuario(monkeypatch):
    import base64

    monkeypatch.setattr(config, "PERMITIR_BASIC", True)
    monkeypatch.setattr(config, "MAX_FALHAS_POR_USUARIO", 2, raising=False)
    h = {"Authorization": "Basic " + base64.b64encode(b"fulano:errada").decode()}
    async with _cli() as c:
        assert (await c.get("/v1/auth/sessao", headers=h)).status_code == 401
        assert (await c.get("/v1/auth/sessao", headers=h)).status_code == 401
        assert (await c.get("/v1/auth/sessao", headers=h)).status_code == 429


# --------------------------------------------------------------- memória
def test_limitador_nao_cresce_sem_limite(monkeypatch):
    """Chaves velhas saem (antes: uma entrada por IP/usuário pra sempre = vazamento de memória/DoS)."""
    agora = [1000.0]
    monkeypatch.setattr(S.time, "time", lambda: agora[0])
    lim = S.LimiteLogin(5, janela_s=60)
    for i in range(50_000):
        lim.permitir(f"ip-{i}")
        agora[0] += 0.01  # 500 s no total: as primeiras chaves já saíram da janela
    assert len(lim._eventos) <= 2 * 60 / 0.01  # no máximo ~2 janelas de chaves (varredura periódica)


def test_limitador_tem_teto_de_chaves(monkeypatch):
    """Mesmo com tudo dentro da janela (rajada de IPs), o dicionário tem teto."""
    monkeypatch.setattr(S.time, "time", lambda: 1000.0)
    lim = S.LimiteLogin(5, janela_s=600)
    for i in range(S.LimiteLogin.MAX_CHAVES + 5000):
        lim.permitir(f"ip-{i}")
    assert len(lim._eventos) <= S.LimiteLogin.MAX_CHAVES


# ------------------------------------------------------------- por IP
def test_ipv6_conta_por_bloco_64():
    """Um cliente IPv6 tem 2^64 endereços no mesmo /64: o limite por IP agrupa o bloco."""
    assert S.chave_ip("2001:db8:1:2::1") == S.chave_ip("2001:db8:1:2:ffff:ffff:ffff:fffe")
    assert S.chave_ip("2001:db8:1:3::1") != S.chave_ip("2001:db8:1:2::1")
    assert S.chave_ip("200.128.1.2") == "200.128.1.2"
    assert S.chave_ip("?") == "?"


@pytest.mark.asyncio
async def test_xff_forjado_nao_muda_a_chave_do_limite_por_ip(monkeypatch):
    """Cliente direto (não é proxy confiável) mandando X-Forwarded-For: o uvicorn ignora e a chave é o IP real."""
    monkeypatch.setattr(S.gerenciador.limite_login, "maximo", 3)
    a = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")  # o que o uvicorn faz com --proxy-headers
    async with _cli(a, ip="198.51.100.7") as c:
        for i in range(3):
            assert (await _login(c, f"u{i}", "errada", **{"X-Forwarded-For": f"203.0.113.{i}"})).status_code == 401
        r = await _login(c, "u9", "errada", **{"X-Forwarded-For": "203.0.113.99"})
        assert r.status_code == 429


@pytest.mark.asyncio
async def test_xff_atras_de_proxy_confiavel_usa_o_cliente_real(monkeypatch):
    """Atrás do proxy confiável, a chave é o 1º IP NÃO confiável da direita: o cliente não forja prefixando XFF."""
    monkeypatch.setattr(S.gerenciador.limite_login, "maximo", 2)
    a = ProxyHeadersMiddleware(app, trusted_hosts="10.0.0.2")
    async with _cli(a, ip="10.0.0.2") as c:
        # o proxy acrescenta o IP real (198.51.100.7) no fim; o resto foi o atacante que mandou
        for forjado in ("1.1.1.1", "2.2.2.2"):
            assert (await _login(c, "u", "errada", **{"X-Forwarded-For": f"{forjado}, 198.51.100.7"})).status_code == 401
        r = await _login(c, "u2", "errada", **{"X-Forwarded-For": "3.3.3.3, 198.51.100.7"})
        assert r.status_code == 429
        # outro cliente real atrás do mesmo proxy tem a sua própria cota
        assert (await _login(c, "u3", "errada", **{"X-Forwarded-For": "198.51.100.8"})).status_code == 401


@pytest.mark.asyncio
async def test_documenta_que_forwarded_allow_ips_asterisco_deixa_forjar(monkeypatch):
    """FORWARDED_ALLOW_IPS='*' com a API exposta direto = o cliente escolhe o próprio IP. NÃO use (ver docs)."""
    monkeypatch.setattr(S.gerenciador.limite_login, "maximo", 1)
    a = ProxyHeadersMiddleware(app, trusted_hosts="*")
    async with _cli(a, ip="198.51.100.7") as c:
        for i in range(3):
            assert (await _login(c, f"u{i}", "errada", **{"X-Forwarded-For": f"203.0.113.{i}"})).status_code == 401
