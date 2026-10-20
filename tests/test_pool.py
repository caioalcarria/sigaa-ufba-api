"""Pool de sessões (sigaa/pool.py) e as primitivas de paralelismo do cliente — sem rede."""

import asyncio
import time

import httpx
import pytest

from sigaa.client import SigaaClient
from sigaa.errors import NaoEncontrado, SessaoExpirada
from sigaa.pool import PoolSigaa


class Falso(SigaaClient):
    """Sessão SIGAA de mentira: o login demora ``t_login`` e não toca a rede."""

    n = 0
    t_login = 0.05

    def __init__(self, **kw):
        super().__init__("http://sigaa.invalid", **kw)
        Falso.n += 1
        self.nome = f"s{Falso.n}"
        self.logins = 0

    async def login(self, usuario, senha):
        await asyncio.sleep(self.t_login)
        self.logins += 1
        self.logado = True

    async def logout(self):
        self.logado = False


async def _cred():
    return "u", "p"


def _pool(maximo=4, cred=_cred, **kw) -> PoolSigaa:
    return PoolSigaa(Falso(), Falso, maximo=maximo, credenciais=cred, **kw)


def run(coro):
    return asyncio.run(coro)


def test_sem_pool_paralelo_e_serial_na_mesma_sessao():
    async def main():
        c = Falso()
        vistos = []

        async def f(s, i):
            vistos.append(s.nome)
            return i * 10

        r = await c.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(4)]))
        assert r == [0, 10, 20, 30]
        assert set(vistos) == {c.nome}

    run(main())


def test_paralelo_espalha_pelas_sessoes_e_mantem_ordem():
    async def main():
        p = _pool(maximo=4)
        await p.aquecer(4)
        assert p.tamanho == 4
        usadas = set()

        async def f(s, i):
            usadas.add(s.nome)
            await asyncio.sleep(0.2)
            return i

        t = time.perf_counter()
        r = await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(8)]))
        dt = time.perf_counter() - t
        assert r == list(range(8))
        assert len(usadas) == 4
        assert dt < 0.2 * 8 / 4 + 0.35  # ~2 rodadas de 0,2 s, não 8
        await p.fechar()

    run(main())


def test_paralelo_abre_sessoes_sob_demanda_ate_o_maximo():
    async def main():
        p = _pool(maximo=3, tarefas_por_sessao=1)
        assert p.tamanho == 1

        async def f(s, i):
            await asyncio.sleep(0.3)
            return s.nome

        r = await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(6)]))
        assert len(r) == 6
        assert p.tamanho == 3
        assert len(set(r)) == 3
        await p.fechar()

    run(main())


def test_executar_concorrente_usa_sessoes_diferentes():
    async def main():
        p = _pool(maximo=2)
        await p.aquecer(2)
        nomes = []

        async def f(s):
            nomes.append(s.nome)
            await asyncio.sleep(0.2)

        t = time.perf_counter()
        await asyncio.gather(p.principal.executar(f), p.principal.executar(f))
        assert time.perf_counter() - t < 0.35
        assert len(set(nomes)) == 2
        await p.fechar()

    run(main())


def test_uma_sessao_nunca_navega_dois_fluxos_ao_mesmo_tempo():
    async def main():
        p = _pool(maximo=3)
        await p.aquecer(3)
        ativos: dict[str, int] = {}
        pior = 0

        async def f(s, i):
            nonlocal pior
            ativos[s.nome] = ativos.get(s.nome, 0) + 1
            pior = max(pior, ativos[s.nome])
            await asyncio.sleep(0.01 * (i % 3))
            ativos[s.nome] -= 1
            return i

        rotas = [p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(10)])) for _ in range(4)]
        rotas += [p.principal.executar(lambda s: f(s, 99)) for _ in range(5)]
        await asyncio.gather(*rotas)
        assert pior == 1
        await p.fechar()

    run(main())


def test_erro_sobe_o_do_primeiro_fluxo():
    async def main():
        p = _pool(maximo=3)
        await p.aquecer(3)

        async def f(s, i):
            await asyncio.sleep(0.01)
            if i in (2, 4):
                raise NaoEncontrado(f"turma {i}")
            return i

        with pytest.raises(NaoEncontrado, match="turma 2"):
            await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(6)]))
        # o pool continua utilizável e com todas as sessões livres
        assert p.livres == 3
        assert await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: asyncio.sleep(0, i) for i in range(3)])) == [0, 1, 2]
        await p.fechar()

    run(main())


def test_sessao_extra_que_cai_sem_credenciais_sai_do_pool_e_o_fluxo_vai_pra_outra():
    async def main():
        p = _pool(maximo=3)
        await p.aquecer(3)
        p._credenciais = None  # (lembrar=false depois do aquecimento)
        for s in p.sessoes:
            s._credenciais = None
        morta = p.sessoes[1]

        async def f(s, i):
            await asyncio.sleep(0.05)
            if s is morta:
                raise SessaoExpirada("caiu")
            return i

        r = await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(6)]))
        assert r == list(range(6))
        assert morta not in p.sessoes and p.tamanho == 2
        await p.fechar()

    run(main())


def test_sessao_que_cai_com_credenciais_reloga_so_ela():
    async def main():
        p = _pool(maximo=2)
        await p.aquecer(2)
        alvo = p.sessoes[1]
        caiu = {"ja": False}

        async def f(s, i):
            if s is alvo and not caiu["ja"]:
                caiu["ja"] = True
                raise SessaoExpirada("caiu")
            await asyncio.sleep(0.05)
            return i

        r = await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(4)]))
        assert r == [0, 1, 2, 3]
        assert alvo.logins == 2 and p.principal.logins == 0
        await p.fechar()

    run(main())


def test_memo_singleflight_entre_sessoes():
    async def main():
        p = _pool(maximo=3)
        await p.aquecer(3)
        chamadas = 0

        async def caro():
            nonlocal chamadas
            chamadas += 1
            await asyncio.sleep(0.1)
            return "pdf"

        r = await asyncio.gather(*(p.principal.executar(lambda s: s.memo("historico", 60, caro)) for _ in range(3)))
        assert r == ["pdf"] * 3 and chamadas == 1
        assert await p.sessoes[2].memo("historico", 60, caro) == "pdf" and chamadas == 1
        await p.fechar()

    run(main())


def test_memo_singleflight_propaga_erro_e_nao_guarda():
    async def main():
        c = Falso()
        n = 0

        async def falha():
            nonlocal n
            n += 1
            await asyncio.sleep(0.05)
            raise NaoEncontrado("x")

        r = await asyncio.gather(c.memo("k", 60, falha), c.memo("k", 60, falha), return_exceptions=True)
        assert all(isinstance(x, NaoEncontrado) for x in r) and n == 1
        with pytest.raises(NaoEncontrado):
            await c.memo("k", 60, falha)
        assert n == 2

    run(main())


def test_falha_ao_abrir_sessao_extra_nao_quebra_a_rota():
    async def main():
        async def sem_senha():
            raise SessaoExpirada("sem credenciais")

        p = _pool(maximo=3, cred=sem_senha, tarefas_por_sessao=1)

        async def f(s, i):
            await asyncio.sleep(0.05)
            return i

        r = await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: f(s, i) for i in range(4)]))
        assert r == [0, 1, 2, 3] and p.tamanho == 1
        await p.fechar()

    run(main())


# ------------------------------------------------------------ cliente: ViewState reaproveitado
PORTAL = (
    "<html><body><form id='menu:form_menu_discente'>"
    '<input type="hidden" name="javax.faces.ViewState" value="j_id{n}"/></form>'
    "<script>cmDraw([null, 'Atestado', 'menu_form_menu_discente_j_id_jsp_1', 'menu:form_menu_discente']);</script>"
    "</body></html>"
)


def _sigaa_falso(log: list, recusar_vs: set[str] | None = None, como_portal: bool = False):
    n = {"v": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        log.append((req.method, req.url.path))
        if req.url.path == "/sigaa/verPortalDiscente.do":
            n["v"] += 1
            return httpx.Response(200, html=PORTAL.format(n=n["v"]))
        if req.url.path == "/sigaa/portais/discente/discente.jsf":
            corpo = req.content.decode()
            if recusar_vs and any(f"ViewState={v}" in corpo for v in recusar_vs):
                if como_portal:  # o SIGAA real: view fora da janela → ignora o clique e devolve o portal
                    return httpx.Response(200, html=PORTAL.format(n=99).replace("<body>", '<body><div id="turmas-portal"></div>'))
                return httpx.Response(200, html="<p>O endereço digitado não é válido</p>")
            return httpx.Response(200, html="<html>tela do menu</html>")
        return httpx.Response(200, html="<html>outra</html>")

    return httpx.MockTransport(handler)


def test_menu_reaproveita_o_portal_enquanto_a_view_vale():
    async def main():
        log = []
        c = SigaaClient("http://sigaa.test", transport=_sigaa_falso(log), min_interval=0, folga=0, reusar_views=3)
        for _ in range(4):  # usar a view a renova (é o que o MyFaces faz): 4 menus seguidos = 1 GET do portal
            await c.menu("Atestado")
        assert [m for m, _ in log] == ["GET", "POST", "POST", "POST", "POST"]
        for _ in range(3):  # 3 navegações em outras telas: a view do portal sai da janela
            await c.get("/sigaa/outra")
        await c.menu("Atestado")
        assert [m for m, _ in log][-2:] == ["GET", "POST"]
        await c.close()

    run(main())


def test_menu_view_descartada_devolve_portal_e_o_cliente_repete():
    async def main():
        log = []
        c = SigaaClient("http://sigaa.test", transport=_sigaa_falso(log, recusar_vs={"j_id1"}, como_portal=True), min_interval=0, folga=0, reusar_views=10)
        await c.portal()  # j_id1: o servidor "esqueceu" essa view e devolve o portal no clique
        r = await c.menu("Atestado")
        assert "tela do menu" in r.html
        assert [m for m, _ in log] == ["GET", "POST", "GET", "POST"]
        await c.close()

    run(main())


def test_menu_nao_reaproveita_portal_depois_da_turma_virtual():
    """No SIGAA real, depois de navegar na turma virtual o portal guardado dispara o menu pra tela atual
    (/ava/index.jsf): entrar em /ava/ ou /mobile/ descarta o portal da sessão."""

    async def main():
        log = []
        c = SigaaClient("http://sigaa.test", transport=_sigaa_falso(log), min_interval=0, folga=0, reusar_views=8)
        await c.menu("Atestado")
        await c.get("/sigaa/ava/index.jsf")
        await c.menu("Atestado")
        await c.get("/sigaa/mobile/touch/menu.jsf")
        await c.menu("Atestado")
        assert [m for m, _ in log] == ["GET", "POST", "GET", "GET", "POST", "GET", "GET", "POST"]
        await c.close()

    run(main())


def test_menu_que_cai_na_turma_virtual_baixa_portal_e_repete():
    async def main():
        log = []
        n = {"post": 0}

        def handler(req):
            log.append((req.method, req.url.path))
            if req.url.path == "/sigaa/verPortalDiscente.do":
                return httpx.Response(200, html=PORTAL.format(n=len(log)))
            if req.method == "GET":
                return httpx.Response(200, html="<html><form id='formMenu'></form>turma virtual</html>")
            n["post"] += 1
            if n["post"] == 1:  # a 1a resposta do menu é a tela em que a sessão estava
                return httpx.Response(302, headers={"location": "/sigaa/ava/index.jsf"})
            return httpx.Response(200, html="<html>tela do menu</html>")

        c = SigaaClient("http://sigaa.test", transport=httpx.MockTransport(handler), min_interval=0, folga=0, reusar_views=8)
        await c.portal()
        r = await c.menu("Atestado")
        assert "tela do menu" in r.html and n["post"] == 2
        await c.close()

    run(main())


def test_menu_sem_reuso_baixa_portal_sempre():
    async def main():
        log = []
        c = SigaaClient("http://sigaa.test", transport=_sigaa_falso(log), min_interval=0, folga=0)
        for _ in range(3):
            await c.menu("Atestado")
        assert sum(x[0] == "GET" for x in log) == 3
        await c.close()

    run(main())


def test_menu_viewstate_recusado_baixa_portal_e_repete():
    async def main():
        log = []
        c = SigaaClient("http://sigaa.test", transport=_sigaa_falso(log, recusar_vs={"j_id1"}), min_interval=0, folga=0, reusar_views=10)
        await c.portal()  # j_id1 (o servidor vai "esquecer" essa view)
        r = await c.menu("Atestado")
        assert "tela do menu" in r.html
        assert [m for m, _ in log] == ["GET", "POST", "GET", "POST"]
        await c.close()

    run(main())


def test_transporte_compartilhado_nao_fecha_com_um_cliente():
    async def main():
        log = []
        t = _sigaa_falso(log)
        a = SigaaClient("http://sigaa.test", transport=t, min_interval=0, folga=0)
        b = SigaaClient("http://sigaa.test", transport=t, min_interval=0, folga=0)
        await a.portal()
        await a.close()
        await b.portal()  # o transporte continua de pé
        assert len(log) == 2
        await b.close()

    run(main())


def test_pool_nao_cresce_com_o_sigaa_sob_pressao():
    from sigaa.client import Carga

    async def main():
        carga = Carga(10)
        p = PoolSigaa(Falso(limite=carga), Falso, maximo=4, credenciais=_cred, tarefas_por_sessao=1, carga=carga)
        carga.em_voo = 6  # 60% do teto em voo (outros alunos)
        assert p.crescer(3) == 0
        r = await p.principal.executar(lambda s: s.paralelo([lambda s, i=i: asyncio.sleep(0.01, i) for i in range(4)]))
        assert r == [0, 1, 2, 3] and p.tamanho == 1
        carga.em_voo = 0
        await p.aquecer(3)
        assert p.tamanho == 3
        await p.fechar()

    run(main())


def test_carga_limita_requisicoes_simultaneas():
    from sigaa.client import Carga

    async def main():
        carga = Carga(2)
        dentro = pico = 0

        async def req():
            nonlocal dentro, pico
            async with carga:
                dentro += 1
                pico = max(pico, dentro)
                await asyncio.sleep(0.02)
                dentro -= 1

        await asyncio.gather(*(req() for _ in range(6)))
        assert pico == 2 and carga.em_voo == 0

    run(main())


def test_ritmo_conta_do_inicio_e_tem_folga_do_fim():
    """min_interval entre INÍCIOS + folga depois do FIM: resposta lenta não paga o intervalo inteiro de novo."""
    lento = 0.2

    async def handler_lento(req):
        await asyncio.sleep(lento)
        return httpx.Response(200, html="<html>ok</html>")

    async def main():
        c = SigaaClient("http://sigaa.test", transport=httpx.MockTransport(handler_lento), min_interval=0.3, folga=0.05)
        t = time.perf_counter()
        for _ in range(4):
            await c.get("/x")
        dt = time.perf_counter() - t
        # 4 × 0,2 s de resposta + 3 × 0,1 s (o que falta pros 0,3 s entre inícios) = 1,1 s; o ritmo antigo
        # (0,3 s depois do fim) daria 0,8 + 0,9 = 1,7 s
        assert 1.05 <= dt < 1.4
        rapido = SigaaClient("http://sigaa.test", transport=_sigaa_falso([]), min_interval=0.3, folga=0.05)
        t = time.perf_counter()
        for _ in range(4):
            await rapido.get("/x")
        assert time.perf_counter() - t >= 0.9  # resposta instantânea: quem manda é o min_interval (3 × 0,3 s)
        await c.close()
        await rapido.close()

    run(main())
