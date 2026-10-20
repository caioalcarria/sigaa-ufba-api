"""Proteções do transporte da senha no login (pedido do Caio).

* **HTTPS obrigatório fora do localhost** (``SIGAA_API_EXIGIR_HTTPS``): login (e Basic) por HTTP puro só
  de um cliente na própria máquina (127.0.0.1/::1). De qualquer outro lugar → 403 ``https_obrigatorio`` e a
  senha nem é lida. Atrás de proxy com TLS, o esquema vem do ``X-Forwarded-Proto`` — só se o uvicorn
  confiar no proxy (``--proxy-headers`` + ``FORWARDED_ALLOW_IPS=<IP do proxy>``).
* **Corpo cifrado opcional** (``SIGAA_API_LOGIN_CIFRADO``): ``GET /v1/auth/chave`` publica uma chave RSA
  (2048 bits, gerada no boot, nunca gravada); o cliente manda ``{"cifrado": base64(RSA-OAEP-SHA256(json))}``
  com ``{"usuario", "senha", "ts"}`` dentro. Protege a senha de quem vê o corpo DEPOIS do TLS (proxy que
  loga corpo, ferramenta de APM, dump de requisição) — NÃO protege do dono do servidor, que tem a chave
  privada. ``ts`` (época, s) vale ``SIGAA_API_LOGIN_CIFRADO_JANELA_S`` e cada envelope é aceito UMA vez
  (anti-replay).
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .config import config

ALG = "RSA-OAEP-256"
_OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
_MSG_INVALIDO = "Login cifrado inválido, vencido ou já usado. Pegue a chave em GET /v1/auth/chave e cifre de novo."


class CifradoInvalido(ValueError):
    """Envelope que não abre, vencido ou repetido — sempre a MESMA mensagem (sem oráculo)."""

    def __init__(self) -> None:
        super().__init__(_MSG_INVALIDO)


# ------------------------------------------------------------------ HTTPS
def _loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address((host or "").split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def https_ok(scheme: str, cliente: str | None) -> bool:
    """A senha pode chegar por esta conexão? ``auto`` (padrão): HTTPS, ou HTTP só do próprio host."""
    modo = (config.EXIGIR_HTTPS or "auto").strip().lower()
    if modo in ("0", "false", "nao", "não", "no", "off"):
        return True
    if scheme == "https":
        return True
    return modo == "auto" and _loopback(cliente)


# ------------------------------------------------------------------ chave e envelope
class Chaveiro:
    def __init__(self) -> None:
        self._privada: rsa.RSAPrivateKey | None = None
        self._trava = threading.Lock()
        self._vistos: dict[str, float] = {}  # sha256(envelope) → quando vence

    def privada(self) -> rsa.RSAPrivateKey:
        if self._privada is None:
            with self._trava:
                if self._privada is None:
                    self._privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return self._privada

    def publica(self) -> dict:
        pub = self.privada().public_key()
        der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return {
            "alg": ALG,
            "kid": hashlib.sha256(der).hexdigest()[:16],
            "chave_publica_pem": pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
            "janela_s": config.LOGIN_CIFRADO_JANELA_S,
            "formato": 'POST /v1/auth/login {"cifrado": base64(RSA-OAEP-SHA256(utf8(json{"usuario","senha","ts"}))), "lembrar": bool}',
        }

    def abrir(self, envelope: str) -> tuple[str, str]:
        """(usuario, senha) do envelope — ou :class:`CifradoInvalido`."""
        try:
            e = envelope.strip().replace("-", "+").replace("_", "/")  # aceita base64 e base64url
            bruto = base64.b64decode(e + "=" * (-len(e) % 4), validate=True)
            dados = json.loads(self.privada().decrypt(bruto, _OAEP).decode("utf-8"))
            usuario, senha, ts = dados["usuario"], dados["senha"], float(dados["ts"])
        except Exception:  # noqa: BLE001 - qualquer falha = a mesma resposta
            raise CifradoInvalido from None
        if not (isinstance(usuario, str) and isinstance(senha, str) and usuario and senha):
            raise CifradoInvalido
        agora, janela = time.time(), config.LOGIN_CIFRADO_JANELA_S
        if abs(agora - ts) > janela:
            raise CifradoInvalido
        marca = hashlib.sha256(bruto).hexdigest()
        if len(self._vistos) > 100_000 or len(self._vistos) % 512 == 0:
            self._vistos = {k: v for k, v in self._vistos.items() if v > agora}
        if self._vistos.get(marca, 0) > agora:
            raise CifradoInvalido  # replay
        self._vistos[marca] = agora + 2 * janela
        return usuario, senha


chaveiro = Chaveiro()
