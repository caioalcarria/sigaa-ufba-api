"""Gerenciador de sessões: token da API ↔ sessão do aluno no SIGAA.

Desenho:
* o token é opaco (``secrets.token_urlsafe``) e o servidor guarda só o SHA-256 dele;
* cada token aponta pra um ``SigaaClient`` com cookies próprios e uma trava (a navegação
  JSF de uma sessão não pode ser paralela);
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

from sigaa.client import SigaaClient
from sigaa.errors import SessaoExpirada

from .config import config

log = logging.getLogger("sigaa_api.sessoes")


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


@dataclass
class Sessao:
    cliente: SigaaClient
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

        cli = SigaaClient(config.SIGAA_URL, credenciais=credenciais if lembrar else None)
        try:
            await cli.login(usuario, senha)
        except Exception:
            await cli.close()
            raise
        agora = time.time()
        token = secrets.token_urlsafe(32)
        sess = Sessao(
            cliente=cli,
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
            if sess and time.time() < sess.expira_em:
                sess.ultimo_uso = time.time()
                return sess
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
        try:
            await sess.cliente.logout()
        except Exception:  # noqa: BLE001 - logout é melhor-esforço
            pass
        await sess.cliente.close()
        return True

    def _expurgar(self) -> None:
        agora = time.time()
        mortas = [k for k, s in self._sessoes.items() if agora > s.expira_em or agora - s.ultimo_uso > config.TOKEN_OCIOSO_MIN * 60]
        for k in mortas:
            sess = self._sessoes.pop(k)
            asyncio.create_task(sess.cliente.close())

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

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(config.KEEPALIVE_MIN * 60)
            self._expurgar()
            agora = time.time()
            for sess in list(self._sessoes.values()):
                if agora - sess.ultimo_uso > config.KEEPALIVE_JANELA_MIN * 60:
                    continue
                cli = sess.cliente
                if cli.lock.locked():
                    continue
                try:
                    async with cli.lock:
                        vivo = await cli.manter_viva()
                    if not vivo:
                        log.info("sessão SIGAA caiu; será relogada sob demanda" if sess.lembrar else "sessão SIGAA caiu")
                except Exception as e:  # noqa: BLE001
                    log.warning("keep-alive falhou: %s", e)


gerenciador = Gerenciador()
