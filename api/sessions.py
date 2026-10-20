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
* nada vai pro disco: reiniciar o servidor invalida todos os tokens;
* logout (ou expiração, ou o teto por usuário) ESQUECE a credencial: a cifrada da sessão e as
  closures que o cliente e o pool guardam pra relogar (ver ``Gerenciador._esquecer``);
* Basic auth: a chave da sessão é HMAC(chave aleatória do processo, usuário+senha) — nunca um hash
  rápido e sem sal da senha que um dump de memória permitiria quebrar offline;
* limite de login: por IP (todas as tentativas; IPv6 por bloco /64) e por USUÁRIO (só as falhas),
  pra força bruta distribuída em muitos IPs não chegar à conta do aluno no SIGAA.

Limite honesto: ``str``/``bytes`` do Python são imutáveis e não dá pra zerar a senha na memória — o
que se faz é soltar todas as referências o quanto antes (o GC reaproveita a memória) e, no boot,
desligar core dump (``endurecer_processo``).
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import hmac
import ipaddress
import logging
import resource
import secrets
import time
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from sigaa.client import Carga, SigaaClient, transporte
from sigaa.errors import CredenciaisInvalidas, SessaoExpirada
from sigaa.pool import PoolSigaa

from .config import config

log = logging.getLogger("sigaa_api.sessoes")


#: chave aleatória do processo (nunca sai da memória): HMAC das chaves Basic e do limite por usuário
_CHAVE_PROCESSO = secrets.token_bytes(32)


def _hash(valor: str) -> str:
    """SHA-256 — só pro token (256 bits aleatórios: hash rápido sem sal basta, não há o que adivinhar)."""
    return hashlib.sha256(valor.encode()).hexdigest()


def _hmac(valor: str) -> str:
    return hmac.new(_CHAVE_PROCESSO, valor.encode(), hashlib.sha256).hexdigest()


def chave_basic(usuario: str, senha: str) -> str:
    """Chave da sessão Basic: HMAC com a chave do processo (um dump não vira dicionário de senhas)."""
    return "basic:" + _hmac(f"{usuario}\x00{senha}")


def chave_usuario(usuario: str) -> str:
    return _hmac("usuario\x00" + usuario.strip().lower())


def chave_ip(ip: str) -> str:
    """Chave do limite por IP. IPv6 conta por bloco /64 (um cliente costuma ter o /64 inteiro)."""
    try:
        end = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if end.version == 6:
        if end.ipv4_mapped is not None:
            return str(end.ipv4_mapped)
        return str(ipaddress.ip_network(f"{end}/64", strict=False))
    return str(end)


def endurecer_processo() -> None:
    """Sem core dump (a memória tem tokens, senhas cifradas e a chave que as decifra) e sem ptrace por
    outro processo do mesmo usuário (``PR_SET_DUMPABLE=0``). Melhor-esforço: fora do Linux só o rlimit."""
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError) as e:
        log.warning("não deu pra desligar core dump: %s", e)
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE = 4
            log.warning("prctl(PR_SET_DUMPABLE, 0) falhou")
    except (OSError, AttributeError):
        pass


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
    _cred: bytes | None = field(default=None, repr=False)
    #: caixinhas ([credencial cifrada]) que as closures de relogin leem; o logout esvazia
    _cofres: tuple[list, ...] = field(default=(), repr=False)
    _aquecimento: asyncio.Task | None = field(default=None, repr=False)
    #: chave do limite de FALHAS por usuário (HMAC do login): o login e a confirmação de senha das ações
    #: de escrita ("step-up") dividem o mesmo contador
    chave_falhas: str = field(default="", repr=False)

    def valida(self, agora: float | None = None) -> bool:
        agora = time.time() if agora is None else agora
        return agora <= self.expira_em and agora - self.ultimo_uso <= config.TOKEN_OCIOSO_MIN * 60


class LimiteLogin:
    """Janela deslizante por chave (IP ou usuário), com memória limitada: chaves que saíram da janela
    são varridas de tempos em tempos e o dicionário tem teto (``MAX_CHAVES``)."""

    MAX_CHAVES = 100_000

    def __init__(self, maximo: int, janela_s: float = 600) -> None:
        self.maximo, self.janela = maximo, janela_s
        self._eventos: dict[str, list[float]] = {}
        self._varrido_em = 0.0

    def _recentes(self, chave: str, agora: float) -> list[float]:
        return [t for t in self._eventos.get(chave, ()) if agora - t < self.janela]

    def _varrer(self, agora: float) -> None:
        if len(self._eventos) < self.MAX_CHAVES and agora - self._varrido_em < min(self.janela, 60):
            return
        self._varrido_em = agora
        velhas = [k for k, ev in self._eventos.items() if not ev or agora - ev[-1] >= self.janela]
        for k in velhas:
            del self._eventos[k]
        excesso = len(self._eventos) - self.MAX_CHAVES
        if excesso >= 0:  # rajada com tudo dentro da janela: sai o mais antigo (e 10 % de folga)
            for k in sorted(self._eventos, key=lambda k: self._eventos[k][-1])[: excesso + self.MAX_CHAVES // 10]:
                del self._eventos[k]

    def bloqueado(self, chave: str) -> bool:
        return self.maximo > 0 and len(self._recentes(chave, time.time())) >= self.maximo

    def registrar(self, chave: str) -> None:
        agora = time.time()
        self._varrer(agora)
        ev = self._recentes(chave, agora)
        ev.append(agora)
        self._eventos[chave] = ev

    def zerar(self, chave: str) -> None:
        self._eventos.pop(chave, None)

    def permitir(self, chave: str) -> bool:
        """Conta a tentativa e diz se ela pode seguir."""
        if self.bloqueado(chave):
            return False
        self.registrar(chave)
        return True


class MuitasTentativas(Exception):
    """Login recusado pelo limite (por IP ou por usuário — a resposta é a mesma, de propósito)."""


class Gerenciador:
    def __init__(self) -> None:
        self._sessoes: dict[str, Sessao] = {}
        self._fernet = Fernet(Fernet.generate_key())
        self._basic_lock = asyncio.Lock()
        self.limite_login = LimiteLogin(config.MAX_LOGINS_POR_IP)
        #: falhas de login por usuário (HMAC do login) — o limite lê config.MAX_FALHAS_POR_USUARIO a cada uso
        self.limite_usuario = LimiteLogin(config.MAX_FALHAS_POR_USUARIO, config.JANELA_FALHAS_USUARIO_MIN * 60)
        self._fechando: set[asyncio.Task] = set()
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
        cofre = [cred]  # as closures leem daqui: o logout esvazia e nenhuma delas reloga mais

        async def credenciais():
            if not cofre[0]:
                raise SessaoExpirada("Sessão expirada e as credenciais não foram guardadas (lembrar=false).")
            u, s = self._fernet.decrypt(cofre[0]).decode().split("\x00", 1)
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
        t = None
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
            _cofres=(cofre, pool_cred),
            _aquecimento=t,
            chave_falhas=chave_usuario(usuario),
        )
        self._sessoes[_hash(token)] = sess
        return token, sess

    # ------------------------------------------------------------------ obter
    async def obter(self, token: str) -> Sessao | None:
        sess = self._sessoes.get(_hash(token))
        if sess is None:
            return None
        agora = time.time()
        if not sess.valida(agora):
            await self.encerrar(token)
            return None
        sess.ultimo_uso = agora
        return sess

    # ------------------------------------------------- confirmação de senha (ações de escrita)
    def confirmacao_bloqueada(self, sess: Sessao) -> bool:
        """A conta já estourou as falhas de senha (login + confirmações) na janela? Consulte DENTRO da trava
        da ação, logo antes de enviar ao SIGAA — fora dela, N pedidos em paralelo passam juntos."""
        self.limite_usuario.maximo = config.MAX_FALHAS_POR_USUARIO
        return bool(sess.chave_falhas) and self.limite_usuario.bloqueado(sess.chave_falhas)

    def falha_confirmacao(self, sess: Sessao) -> None:
        """O SIGAA recusou a senha/CPF/data da confirmação: conta no MESMO limite das falhas de login."""
        if sess.chave_falhas:
            self.limite_usuario.registrar(sess.chave_falhas)

    def espiar(self, token: str) -> Sessao | None:
        """Como ``obter``, mas sem tocar (não renova a ociosidade nem encerra): pro cache e o pré-aquecimento."""
        sess = self._sessoes.get(_hash(token))
        return sess if sess is not None and sess.valida() else None

    def espiar_basic(self, usuario: str, senha: str) -> Sessao | None:
        sess = self._sessoes.get(chave_basic(usuario, senha))
        return sess if sess is not None and sess.valida() else None

    async def autenticar(self, usuario: str, senha: str, *, ip: str = "?", lembrar: bool = False, origem: str = "token") -> tuple[str, Sessao]:
        """Login com os limites: tentativas por IP e FALHAS por usuário (``MuitasTentativas`` antes de ir ao SIGAA)."""
        if not self.limite_login.permitir(chave_ip(ip)):
            raise MuitasTentativas
        cu = chave_usuario(usuario)
        self.limite_usuario.maximo = config.MAX_FALHAS_POR_USUARIO
        if self.limite_usuario.bloqueado(cu):
            raise MuitasTentativas
        try:
            token, sess = await self.criar(usuario, senha, lembrar=lembrar, origem=origem)
        except CredenciaisInvalidas:
            self.limite_usuario.registrar(cu)
            raise
        self.limite_usuario.zerar(cu)
        return token, sess

    async def obter_basic(self, usuario: str, senha: str, *, ip: str = "?") -> Sessao:
        """Basic auth: reaproveita a sessão da mesma credencial (chave = HMAC de usuário+senha). Só um
        login NOVO passa pelos limites — reaproveitar a sessão não é tentativa de login."""
        sess = self.espiar_basic(usuario, senha)
        if sess is not None:
            sess.ultimo_uso = time.time()
            return sess
        chave = chave_basic(usuario, senha)
        async with self._basic_lock:
            sess = self.espiar_basic(usuario, senha)
            if sess is not None:
                sess.ultimo_uso = time.time()
                return sess
            if chave in self._sessoes:  # vencida: encerra antes de criar a nova
                await self.encerrar_por_chave(chave)
            token, sess = await self.autenticar(usuario, senha, ip=ip, lembrar=True, origem="basic")
            self._sessoes.pop(_hash(token), None)  # move pra chave determinística
            self._sessoes[chave] = sess
            return sess

    # ---------------------------------------------------------------- encerrar
    async def encerrar(self, token: str) -> bool:
        return await self.encerrar_por_chave(_hash(token))

    async def encerrar_sessao(self, sess: Sessao) -> bool:
        """Encerra pela própria sessão (serve pro token e pro Basic, cuja chave não é o hash do header)."""
        chave = next((k for k, v in self._sessoes.items() if v is sess), None)
        if chave is not None:
            return await self.encerrar_por_chave(chave)
        self._esquecer(sess)
        if sess.pool is not None:
            await sess.pool.fechar()
        return False

    async def encerrar_por_chave(self, chave: str) -> bool:
        sess = self._sessoes.pop(chave, None)
        if not sess:
            return False
        self._esquecer(sess)
        if sess.pool is not None:
            await sess.pool.fechar()  # logout (melhor-esforço) + close de todas as sessões do aluno
        return True

    @staticmethod
    def _esquecer(sess: Sessao) -> None:
        """Solta a credencial: a cifrada da sessão, as caixinhas que as closures leem e as próprias
        closures no cliente/pool (alguém com a ``Sessao`` na mão — uma rota em voo — não reloga mais)."""
        for cofre in sess._cofres:
            cofre[0] = None
        sess._cred = None
        if sess._aquecimento is not None and not sess._aquecimento.done():
            sess._aquecimento.cancel()
        if sess.pool is not None:
            sess.pool._credenciais = None  # noqa: SLF001
            for s in list(sess.pool.sessoes):
                s._credenciais = None  # noqa: SLF001
        if sess.cliente is not None:
            sess.cliente._credenciais = None  # noqa: SLF001

    def _expurgar(self) -> None:
        agora = time.time()
        mortas = [k for k, s in self._sessoes.items() if not s.valida(agora)]
        for k in mortas:
            sess = self._sessoes.pop(k)
            self._esquecer(sess)
            if sess.pool is not None:
                t = asyncio.create_task(sess.pool.fechar())
                self._fechando.add(t)
                t.add_done_callback(self._fechando.discard)

    @property
    def total(self) -> int:
        return len(self._sessoes)

    # --------------------------------------------------------------- keep-alive
    def iniciar(self) -> None:
        if config.SEM_CORE_DUMP:
            endurecer_processo()
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
