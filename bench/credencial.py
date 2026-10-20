"""Credencial do SIGAA pros scripts de medição contra o SIGAA REAL.

Ordem: variáveis de ambiente ``SIGAA_USUARIO`` / ``SIGAA_SENHA``; senão, um helper local opcional
``recon/sess.py`` com ``_cred()`` (fora do git, cada um tem o seu); senão, pede no terminal.
A senha nunca é impressa.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path


def credencial() -> tuple[str, str]:
    u, s = os.getenv("SIGAA_USUARIO"), os.getenv("SIGAA_SENHA")
    if u and s:
        return u, s
    recon = Path(__file__).resolve().parents[1] / "recon"
    if (recon / "sess.py").exists():
        sys.path.insert(0, str(recon))
        from sess import _cred  # noqa: PLC0415 — helper local, fora do git

        return _cred()
    return input("Usuário SIGAA: "), getpass.getpass("Senha: ")
