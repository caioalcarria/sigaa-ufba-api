"""Gerenciador de sessões: token da API ↔ sessão do aluno no SIGAA.

Desenho:
* o token é opaco (``secrets.token_urlsafe``) e o servidor guarda só o SHA-256 dele;
* cada token aponta pra um POOL de sessões SIGAA do aluno (``sigaa.pool.PoolSigaa``): a sessão
  do login + até ``POOL_MAX - 1`` sessões extras (JSESSIONIDs independentes, cada uma com a sua
  trava, porque a navegação JSF de UMA sessão não pode ser paralela). Rotas diferentes do mesmo
  aluno rodam ao mesmo tempo e as rotas agregadas espalham o trabalho (``c.paralelo``);
* cada sessão tem as suas conexões HTTP keep-alive (uma piscina compartilhada degrada com muita
  concorrência), todas dividem o contexto SSL e um teto global de requisições simultâneas ao SIGAA
  (``MAX_CONCORRENCIA_SIGAA``);
* ``lembrar=True`` guarda a senha CIFRADA em memória (Fernet, chave gerada no boot e
  nunca gravada) — com isso, quando o SIGAA derruba a sessão por inatividade, a API
  reloga sozinha e refaz a consulta. Sem ``lembrar``, a API devolve 401
  ``sessao_expirada`` e o cliente faz login de novo;
* keep-alive opcional: sessões usadas recentemente recebem um "toque" periódico pra
  não expirarem no meio do uso;
* nada vai pro disco: reiniciar o servidor invalida todos os tokens.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from sigaa.client import Carga, SigaaClient, transporte
from sigaa.errors import SessaoExpirada
from sigaa.pool import PoolSigaa

from .config import config

log = logging.getLogger("sigaa_api.sessoes")


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


@dataclass
class Sessao:
    cliente: SigaaClient  # a sessão do login (``cliente.executar`` já usa o pool inteiro)
    pool: PoolSigaa
    usuario_hash: str
    criada_em: float
    expira_em: float
    lembrar: bool
    origem: str = "token"  # "token" | "basic"
    ultimo_uso: float = field(default_factory=time.time)
    _cred: bytes | None = None


class LimiteLogin:
    """Janela deslizante simples por chave (IP)."""

    def __init__(self, maximo: int, janela_s: float = 600) -> None:
        self.maximo, self.janela = maximo, janela_s
        self._eventos: dict[str, list[float]] = {}

    def permitir(self, chave: str) -> bool:
        agora = time.time()
        ev = [t for t in self._eventos.get(chave, []) if agora - t < self.janela]
        if len(ev) >= self.maximo:
            self._eventos[chave] = ev
            return False
        ev.append(agora)
        self._eventos[chave] = ev
        return True


class Gerenciador:
    def __init__(self) -> None:
        self._sessoes: dict[str, Sessao] = {}
        self._fernet = Fernet(Fernet.generate_key())
        self._basic_lock = asyncio.Lock()
        self.limite_login = LimiteLogin(config.MAX_LOGINS_POR_IP)
        self._tarefa: asyncio.Task | None = None
        self._limite: Carga | None = None
        self._aquecendo: set[asyncio.Task] = set()
        self._transporte_unico = None  # só com TRANSPORTE_COMPARTILHADO (pra comparação; ver config)

    def _novo_cliente(self, credenciais=None) -> SigaaClient:
        if self._limite is None:
            self._limite = Carga(config.MAX_CONCORRENCIA_SIGAA)
        if config.TRANSPORTE_COMPARTILHADO and self._transporte_unico is None:
            n = max(config.MAX_CONCORRENCIA_SIGAA * 2, 64)
            self._transporte_unico = transporte(http2=config.HTTP2, max_conexoes=n, keepalive=n)
        return SigaaClient(
            config.SIGAA_URL,
            transport=self._transporte_unico,
            credenciais=credenciais,
            min_interval=config.MIN_INTERVALO,
            folga=config.MIN_FOLGA,
            http2=config.HTTP2,
            conexoes=config.CONEXOES_POR_SESSAO,
            limite=self._limite,
            reusar_views=config.REUSAR_VIEWS,
        )

    # ------------------------------------------------------------------ criar
    async def criar(self, usuario: str, senha: str, *, lembrar: bool = False, origem: str = "token") -> tuple[str, Sessao]:
        self._expurgar()
        uh = _hash(usuario.strip().lower())
        do_usuario = [k for k, s in self._sessoes.items() if s.usuario_hash == uh]
        if len(do_usuario) >= config.MAX_SESSOES_POR_USUARIO:  # derruba a mais antiga
            mais_antiga = min(do_usuario, key=lambda k: self._sessoes[k].criada_em)
            await self.encerrar_por_chave(mais_antiga)
        if len(self._sessoes) >= config.MAX_SESSOES:
            mais_ociosa = min(self._sessoes, key=lambda k: self._sessoes[k].ultimo_uso)
            await self.encerrar_por_chave(mais_ociosa)

        lembrar = lembrar and config.PERMITIR_LEMBRAR
        cred = self._fernet.encrypt(f"{usuario}\x00{senha}".encode()) if lembrar else None

        async def credenciais():
            if not cred:
                raise SessaoExpirada("Sessão expirada e as credenciais não foram guardadas (lembrar=false).")
            u, s = self._fernet.decrypt(cred).decode().split("\x00", 1)
            return u, s

        cli = self._novo_cliente(credenciais if lembrar else None)
        try:
            await cli.login(usuario, senha)
        except Exception:
            await cli.close()
            raise
        # o pool abre sessões extras com a mesma credencial. Sem ``lembrar``, a senha (cifrada) só
        # vive até o aquecimento terminar; depois o pool fica com as sessões que já abriu.
        aquecer = max(1, min(config.POOL_AQUECER, config.POOL_MAX))
        cred_tmp = cred or (self._fernet.encrypt(f"{usuario}\x00{senha}".encode()) if aquecer > 1 else None)

        async def cred_pool():
            if not pool_cred[0]:
                raise SessaoExpirada("Credenciais não guardadas (lembrar=false).")
            return tuple(self._fernet.decrypt(pool_cred[0]).decode().split("\x00", 1))

        pool_cred = [cred_tmp]
        pool = PoolSigaa(
            cli,
            lambda: self._novo_cliente(credenciais if lembrar else None),
            maximo=config.POOL_MAX,
            credenciais=cred_pool if cred_tmp else None,
            tarefas_por_sessao=config.POOL_TAREFAS_POR_SESSAO,
            pressao_max=config.POOL_PRESSAO_MAX,
        )
        if aquecer > 1:
            async def aquecimento():
                try:
                    await pool.aquecer(aquecer)
                finally:
                    if not lembrar:  # esquece a senha: o pool não abre mais sessões
                        pool_cred[0] = None
                        pool._credenciais = None  # noqa: SLF001

            t = asyncio.create_task(aquecimento())
            self._aquecendo.add(t)
            t.add_done_callback(self._aquecendo.discard)
        agora = time.time()
        token = secrets.token_urlsafe(32)
        sess = Sessao(
            cliente=cli,
            pool=pool,
            usuario_hash=uh,
            criada_em=agora,
            expira_em=agora + config.TOKEN_TTL_HORAS * 3600,
            lembrar=lembrar,
            origem=origem,
            _cred=cred,
        )
        self._sessoes[_hash(token)] = sess
        return token, sess

    # ------------------------------------------------------------------ obter
    async def obter(self, token: str) -> Sessao | None:
        sess = self._sessoes.get(_hash(token))
        if sess is None:
            return None
        agora = time.time()
        if agora > sess.expira_em or agora - sess.ultimo_uso > config.TOKEN_OCIOSO_MIN * 60:
            await self.encerrar(token)
            return None
        sess.ultimo_uso = agora
        return sess

    async def obter_basic(self, usuario: str, senha: str) -> Sessao:
        """Basic auth: reaproveita a sessão da mesma credencial (chave = hash de usuário+senha)."""
        chave = "basic:" + _hash(f"{usuario}\x00{senha}")
        async with self._basic_lock:
            sess = self._sessoes.get(chave)
            agora = time.time()
            if sess and agora < sess.expira_em and agora - sess.ultimo_uso <= config.TOKEN_OCIOSO_MIN * 60:
                sess.ultimo_uso = agora
                return sess
            if sess:  # vencida ou ociosa: vale como o Bearer (fecha e valida a senha de novo)
                await self.encerrar_por_chave(chave)
            _, sess = await self.criar(usuario, senha, lembrar=True, origem="basic")
            # move pra chave determinística
            for k, v in list(self._sessoes.items()):
                if v is sess:
                    del self._sessoes[k]
            self._sessoes[chave] = sess
            return sess

    # ---------------------------------------------------------------- encerrar
    async def encerrar(self, token: str) -> bool:
        return await self.encerrar_por_chave(_hash(token))

    async def encerrar_por_chave(self, chave: str) -> bool:
        sess = self._sessoes.pop(chave, None)
        if not sess:
            return False
        await sess.pool.fechar()  # logout (melhor-esforço) + close de todas as sessões do aluno
        return True

    def _expurgar(self) -> None:
        agora = time.time()
        mortas = [k for k, s in self._sessoes.items() if agora > s.expira_em or agora - s.ultimo_uso > config.TOKEN_OCIOSO_MIN * 60]
        for k in mortas:
            sess = self._sessoes.pop(k)
            asyncio.create_task(sess.pool.fechar())

    @property
    def total(self) -> int:
        return len(self._sessoes)

    # --------------------------------------------------------------- keep-alive
    def iniciar(self) -> None:
        if config.KEEPALIVE and self._tarefa is None:
            self._tarefa = asyncio.create_task(self._keepalive())

    async def parar(self) -> None:
        if self._tarefa:
            self._tarefa.cancel()
            self._tarefa = None
        for k in list(self._sessoes):
            await self.encerrar_por_chave(k)
        if self._transporte_unico is not None:
            await self._transporte_unico.aclose()
            self._transporte_unico = None

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(config.KEEPALIVE_MIN * 60)
            self._expurgar()
            agora = time.time()
            for sess in list(self._sessoes.values()):
                if agora - sess.ultimo_uso > config.KEEPALIVE_JANELA_MIN * 60:
                    continue
                try:
                    vivo = await sess.pool.manter_viva() > 0 and sess.cliente.logado
                    if not vivo:
                        log.info("sessão SIGAA caiu; será relogada sob demanda" if sess.lembrar else "sessão SIGAA caiu")
                except Exception as e:  # noqa: BLE001
                    log.warning("keep-alive falhou: %s", e)


gerenciador = Gerenciador()
