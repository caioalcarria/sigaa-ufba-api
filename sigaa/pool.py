"""Pool de sessões SIGAA de UM aluno: várias sessões (JSESSIONIDs) independentes, em paralelo.

Por quê: o SIGAA é JSF *stateful* — numa sessão só dá pra navegar uma tela por vez (a turma
aberta, o ViewState... são da sessão). Mas o SIGAA aceita várias sessões do MESMO usuário ao mesmo
tempo (logar de novo NÃO derruba a anterior — medido na UFBA), e cada uma tem o seu estado JSF.
Então N sessões = N navegações ao mesmo tempo:

* ``executar(fluxo)`` roda o fluxo na primeira sessão LIVRE — duas rotas do mesmo aluno não
  esperam mais uma pela outra;
* ``paralelo(fluxos)`` espalha fluxos independentes (ex.: "notas da turma X" pra cada turma) por
  todas as sessões livres do aluno;
* sessões novas nascem sob demanda (login em segundo plano) até ``maximo``; quem precisa de sessão
  pega a primeira que ficar livre OU a nova, o que vier antes;
* as sessões dividem o mesmo ``Compartilhado`` (memo com singleflight + dados estáveis), então o
  histórico emitido numa serve pra todas;
* relogin por sessão: se UMA sessão cai, só ela é relogada (com credenciais) ou descartada (sem).

Sem credenciais guardadas (``lembrar=false``) o pool não consegue abrir sessões novas depois do
login: ele usa as que foram abertas no aquecimento (enquanto a senha ainda estava em memória).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Sequence, TypeVar

from .client import Carga, Compartilhado, Fluxo, LoginCallback, SigaaClient
from .errors import CredenciaisInvalidas, SessaoExpirada

log = logging.getLogger("sigaa.pool")
T = TypeVar("T")

_baixa: contextvars.ContextVar[bool] = contextvars.ContextVar("sigaa_pool_prioridade_baixa", default=False)


@contextmanager
def prioridade_baixa() -> Iterator[None]:
    """Trabalho de FUNDO (ex.: pré-aquecimento do cache logo após o login): o que rodar dentro deste
    bloco — inclusive tarefas criadas nele — só usa sessão do pool que SOBRA (deixa sempre uma livre
    pro aluno), não recruta a última sessão livre no ``paralelo`` e nunca abre sessão nova.

        with prioridade_baixa():
            await app(scope_interno, ...)   # a rota roda numa sessão própria, sem competir com o aluno
    """
    tok = _baixa.set(True)
    try:
        yield
    finally:
        _baixa.reset(tok)


def em_prioridade_baixa() -> bool:
    return _baixa.get()


class PoolSigaa:
    """As sessões SIGAA de um aluno. ``principal`` é a sessão do login (sempre existe)."""

    def __init__(
        self,
        principal: SigaaClient,
        fabrica: Callable[[], SigaaClient],
        *,
        maximo: int = 4,
        credenciais: LoginCallback | None = None,
        tarefas_por_sessao: int = 2,
        espera_falha_s: float = 60.0,
        carga: Carga | None = None,
        pressao_max: float = 0.5,
    ) -> None:
        """``fabrica``: cria um SigaaClient novo (deslogado) — o pool liga nele o mesmo ``Compartilhado``.
        ``credenciais``: devolve (usuário, senha) pra abrir sessões novas; None = pool fixo.
        ``tarefas_por_sessao``: no ``paralelo``, só abre sessão nova se houver pelo menos isso de
        fluxos esperando por sessão nova (um login custa ~3 s ≈ 6 viagens; não compensa pra 1 fluxo).
        ``carga``/``pressao_max``: não abre sessão nova se o SIGAA já está com mais que essa fração do
        teto global em voo — com muitos alunos ao mesmo tempo, login extra só rouba vaga de trabalho útil."""
        self.compartilhado: Compartilhado = principal.compartilhado
        self.principal = principal
        self._fabrica = fabrica
        self.maximo = max(1, maximo)
        self._credenciais = credenciais
        self.tarefas_por_sessao = max(1, tarefas_por_sessao)
        self._espera_falha = espera_falha_s
        self._carga = carga if carga is not None else (principal._limite if isinstance(principal._limite, Carga) else None)  # noqa: SLF001
        self.pressao_max = pressao_max
        self.sessoes: list[SigaaClient] = []
        self._criando = 0
        self._falhou_em = 0.0
        self._mudou = asyncio.Event()
        self._fechado = False
        self._tarefas: set[asyncio.Task] = set()
        self.logins_extras = 0
        self._adotar(principal)

    # ------------------------------------------------------------ sessões
    def _adotar(self, s: SigaaClient) -> None:
        s.compartilhado = self.compartilhado
        s.pool = self
        self.sessoes.append(s)

    @property
    def tamanho(self) -> int:
        return len(self.sessoes)

    @property
    def livres(self) -> int:
        return sum(not s.lock.locked() for s in self.sessoes)

    def _avisar(self) -> None:
        self._mudou.set()

    async def _esperar_mudanca(self, timeout: float = 1.0) -> None:
        self._mudou.clear()
        try:
            await asyncio.wait_for(self._mudou.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    def _pode_crescer(self) -> bool:
        return (
            not self._fechado
            and self._credenciais is not None
            and len(self.sessoes) + self._criando < self.maximo
            and time.monotonic() - self._falhou_em > self._espera_falha
            and (self._carga is None or self._carga.pressao < self.pressao_max)
        )

    def crescer(self, n: int = 1) -> int:
        """Abre até ``n`` sessões novas em segundo plano. Devolve quantas começaram a abrir."""
        abertas = 0
        for _ in range(n):
            if not self._pode_crescer():
                break
            self._criando += 1
            t = asyncio.create_task(self._nova_sessao())
            self._tarefas.add(t)
            t.add_done_callback(self._tarefas.discard)
            abertas += 1
        return abertas

    async def aquecer(self, total: int) -> None:
        """Garante ``total`` sessões (abre as que faltam em paralelo) e espera elas ficarem prontas."""
        self.crescer(max(0, total - len(self.sessoes) - self._criando))
        while self._criando and not self._fechado:
            await self._esperar_mudanca(5)

    async def _nova_sessao(self) -> None:
        s = self._fabrica()
        s.compartilhado = self.compartilhado
        try:
            usuario, senha = await self._credenciais()  # type: ignore[misc]
            await s.login(usuario, senha)
        except Exception as e:  # noqa: BLE001 - falhar ao abrir sessão extra não é erro da rota
            self._falhou_em = time.monotonic()
            log.info("pool: não abriu sessão extra (%s: %s)", type(e).__name__, e)
            await s.close()
            if isinstance(e, CredenciaisInvalidas):
                self._credenciais = None
            return
        except asyncio.CancelledError:
            # o pool fechou (logout) no meio do login: o SIGAA já pode ter aceitado a sessão — desloga,
            # senão ela fica logada e órfã até o SIGAA derrubar por inatividade
            await self._fechar_sessao(s)
            raise
        finally:
            self._criando -= 1
            self._avisar()
        if self._fechado:
            await self._fechar_sessao(s)
            return
        self.logins_extras += 1
        self._adotar(s)
        self._avisar()

    async def _livre(self) -> SigaaClient | None:
        """Uma sessão livre, já travada pra quem pediu (prefere a usada por último: conexão quente).
        ``acquire()`` de uma trava livre e sem fila não cede o loop, então não há corrida aqui.
        Em prioridade baixa só pega se sobrar outra livre (ou se o pool tem uma sessão só e nenhuma abrindo)."""
        cands = [s for s in self.sessoes if not s.lock.locked()]
        if not cands:
            return None
        if _baixa.get() and len(cands) < 2 and len(self.sessoes) + self._criando > 1:
            return None  # (pool de 1 sessão: divide, como antes — quem está no fundo já cede a vez por conta própria)
        s = max(cands, key=lambda x: x.ultimo_uso)
        await s.lock.acquire()
        return s

    async def _adquirir(self, *, crescer: bool = True) -> SigaaClient:
        while True:
            if self._fechado:
                raise SessaoExpirada("Sessão encerrada.")
            s = await self._livre()
            if s is not None:
                return s
            if crescer and self._criando == 0 and not _baixa.get():
                self.crescer(1)
            await self._esperar_mudanca()

    def _liberar(self, s: SigaaClient) -> None:
        if s.lock.locked():
            s.lock.release()
        self._avisar()

    async def _descartar(self, s: SigaaClient) -> None:
        """Tira do pool uma sessão que caiu (e não dá pra relogar). A principal nunca sai."""
        if s is self.principal or s not in self.sessoes:
            return
        self.sessoes.remove(s)
        await self._fechar_sessao(s)
        self._avisar()

    @staticmethod
    async def _fechar_sessao(s: SigaaClient) -> None:
        try:
            await s.logout()
        except Exception:  # noqa: BLE001
            pass
        await s.close()

    # ------------------------------------------------------------ execução
    async def _rodar(self, s: SigaaClient, fluxo: Fluxo[T]) -> T:
        """O fluxo na sessão ``s`` (travada). Sessão caída: reloga (com credenciais do pool) e refaz."""
        try:
            return await fluxo(s)
        except SessaoExpirada:
            if s._credenciais is None and self._credenciais is not None:  # noqa: SLF001
                s._credenciais = self._credenciais  # noqa: SLF001
            if s._credenciais is None:  # noqa: SLF001
                raise
            await s.relogar()
            return await fluxo(s)

    async def executar(self, fluxo: Fluxo[T]) -> T:
        """Roda o fluxo na primeira sessão livre (abre outra se todas estiverem ocupadas)."""
        for tentativa in range(self.maximo + 1):
            s = await self._adquirir()
            try:
                return await self._rodar(s, fluxo)
            except SessaoExpirada:
                if s is self.principal or tentativa >= self.maximo:
                    raise
            finally:
                self._liberar(s)
            await self._descartar(s)  # sessão extra caiu e não dá pra relogar: tenta em outra
        raise SessaoExpirada("Nenhuma sessão do SIGAA disponível.")

    async def paralelo(self, fluxos: Sequence[Fluxo[T]], *, atual: SigaaClient | None = None, max_sessoes: int | None = None) -> list[T]:
        """Espalha os fluxos pelas sessões do aluno. ``atual`` = a sessão que quem chama já está
        segurando (ela trabalha junto e NÃO é liberada no fim)."""
        n = len(fluxos)
        fila: deque[int] = deque(range(n))
        res: list[Any] = [None] * n
        erros: dict[int, BaseException] = {}
        limite = min(self.maximo, max_sessoes or self.maximo, n)
        trabalhando: set[asyncio.Task] = set()

        async def trabalhador(s: SigaaClient, liberar: bool) -> None:
            morreu = False
            try:
                while fila and not erros:
                    i = fila.popleft()
                    try:
                        res[i] = await self._rodar(s, fluxos[i])
                    except SessaoExpirada as e:
                        if s is atual or s is self.principal:
                            erros[i] = e
                        else:  # foi a sessão extra que morreu: devolve o fluxo pra outra sessão
                            fila.appendleft(i)
                            morreu = True
                            return
                    except Exception as e:  # noqa: BLE001
                        erros[i] = e
            finally:
                if liberar:
                    self._liberar(s)
                if morreu:
                    await self._descartar(s)
                self._avisar()

        def contratar(s: SigaaClient, liberar: bool) -> None:
            t = asyncio.create_task(trabalhador(s, liberar))
            trabalhando.add(t)
            t.add_done_callback(trabalhando.discard)

        if atual is not None:
            contratar(atual, False)
        try:
            while fila and not erros:
                while fila and not erros:
                    while fila and len(trabalhando) < limite:  # pega as sessões livres que cabem
                        s = await self._livre()
                        if s is None:
                            break
                        contratar(s, True)
                    # abre sessões novas se a fila que sobra compensa o login (~3 s)
                    faltam = limite - len(trabalhando) - self._criando
                    if faltam > 0 and len(fila) >= self.tarefas_por_sessao and not _baixa.get():
                        self.crescer(min(faltam, len(fila) // self.tarefas_por_sessao))
                    if fila:
                        await self._esperar_mudanca(0.5)
                if trabalhando:  # (um trabalhador cuja sessão morreu pode ter devolvido fluxo à fila)
                    await asyncio.gather(*list(trabalhando), return_exceptions=True)
        except BaseException:
            fila.clear()
            for t in list(trabalhando):
                t.cancel()
            if trabalhando:
                await asyncio.gather(*list(trabalhando), return_exceptions=True)
            raise
        if erros:
            raise erros[min(erros)]
        return res

    # ------------------------------------------------------------ manutenção
    async def manter_viva(self) -> int:
        """Toca as sessões LIVRES (as ocupadas estão navegando, já estão vivas). Devolve quantas estão vivas."""
        vivas = 0
        for s in list(self.sessoes):
            if s.lock.locked():
                vivas += 1
                continue
            await s.lock.acquire()  # livre: não cede o loop
            try:
                if await s.manter_viva():
                    vivas += 1
                elif s is not self.principal and not self._credenciais:
                    self._liberar(s)
                    await self._descartar(s)
                    continue
            except Exception as e:  # noqa: BLE001
                log.warning("keep-alive falhou: %s", e)
            finally:
                if s in self.sessoes:
                    self._liberar(s)
        return vivas

    async def fechar(self) -> None:
        self._fechado = True
        for t in list(self._tarefas):
            t.cancel()
        self._avisar()
        for s in list(self.sessoes):
            await self._fechar_sessao(s)
        self.sessoes.clear()

    def estatisticas(self) -> dict[str, Any]:
        return {
            "sessoes": len(self.sessoes),
            "livres": self.livres,
            "abrindo": self._criando,
            "maximo": self.maximo,
            "logins_extras": self.logins_extras,
            "requisicoes": sum(s.requisicoes for s in self.sessoes),
        }
