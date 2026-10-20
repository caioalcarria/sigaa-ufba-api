"""Isolamento entre alunos no pool de sessões SIGAA (``sigaa/pool.py``) — sem rede."""

from __future__ import annotations

import asyncio

from api import sessions as S
from api.config import config
from sigaa.client import SigaaClient
from sigaa.pool import PoolSigaa, em_prioridade_baixa, prioridade_baixa


class Falso(SigaaClient):
    def __init__(self, dono: str):
        super().__init__("http://sigaa.invalid")
        self.dono = dono

    async def login(self, usuario, senha):
        await asyncio.sleep(0.01)
        self.logado = True

    async def logout(self):
        self.logado = False


def _pool(dono: str) -> PoolSigaa:
    async def cred():
        return dono, "senha-ficticia"

    return PoolSigaa(Falso(dono), lambda: Falso(dono), maximo=3, credenciais=cred, tarefas_por_sessao=1)


def test_sessoes_e_memo_de_um_aluno_nunca_vao_pro_pool_do_outro():
    async def main():
        pa, pb = _pool("aluno-a"), _pool("aluno-b")
        await pa.aquecer(3)
        await pb.aquecer(3)
        vistos: dict[str, set[str]] = {"a": set(), "b": set()}

        async def fluxo(lado, s):
            await asyncio.sleep(0.01)
            vistos[lado].add(s.dono)
            s.compartilhado.memo[f"k-{lado}"] = (0.0, lado)
            return s

        sa = await asyncio.gather(*[pa.executar(lambda s: fluxo("a", s)) for _ in range(6)], pa.paralelo([lambda s: fluxo("a", s)] * 6))
        sb = await asyncio.gather(*[pb.executar(lambda s: fluxo("b", s)) for _ in range(6)], pb.paralelo([lambda s: fluxo("b", s)] * 6))
        assert vistos == {"a": {"aluno-a"}, "b": {"aluno-b"}}
        assert not {id(s) for s in pa.sessoes} & {id(s) for s in pb.sessoes}
        assert pa.compartilhado is not pb.compartilhado
        assert set(pa.compartilhado.memo) == {"k-a"} and set(pb.compartilhado.memo) == {"k-b"}
        assert all(s.compartilhado is pa.compartilhado for s in pa.sessoes)
        await pa.fechar()
        await pb.fechar()
        return sa, sb

    asyncio.run(main())


def test_cada_cliente_novo_do_gerenciador_tem_o_seu_estado(monkeypatch):
    monkeypatch.setattr(config, "SIGAA_URL", "http://127.0.0.1:9")

    async def main():
        g = S.Gerenciador()
        a, b = g._novo_cliente(), g._novo_cliente()
        try:
            assert a.compartilhado is not b.compartilhado
        finally:
            await a.close()
            await b.close()

    asyncio.run(main())


def test_prioridade_baixa_nao_vaza_pra_tarefa_de_outro_aluno():
    async def main():
        visto: dict[str, bool] = {}
        dentro = asyncio.Event()
        solta = asyncio.Event()

        async def aquecimento_do_a():
            with prioridade_baixa():
                filha = asyncio.create_task(asyncio.sleep(0, result=em_prioridade_baixa()))
                visto["filha_do_a"] = await filha
                dentro.set()
                await solta.wait()
            visto["a_depois"] = em_prioridade_baixa()

        async def requisicao_do_b():
            await dentro.wait()
            visto["b"] = em_prioridade_baixa()  # o A está DENTRO do bloco neste instante
            solta.set()

        await asyncio.gather(aquecimento_do_a(), requisicao_do_b())
        assert visto == {"filha_do_a": True, "b": False, "a_depois": False}

    asyncio.run(main())
