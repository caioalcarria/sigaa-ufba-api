"""Confirmação de senha das ações de escrita ("step-up", frente feat/acoes) e login dividem o MESMO
limite de falhas por usuário: um token roubado não ganha tentativas extras de senha pelo SIGAA."""

from __future__ import annotations

import pytest

from api import sessions as S
from api.config import config


@pytest.fixture
def ger(monkeypatch):
    monkeypatch.setattr(config, "MAX_FALHAS_POR_USUARIO", 3)
    g = S.Gerenciador()
    return g


def _sess(login: str) -> S.Sessao:
    return S.Sessao(cliente=None, pool=None, usuario_hash="h", criada_em=0, expira_em=1e12, lembrar=False, chave_falhas=S.chave_usuario(login))


def test_falhas_de_confirmacao_bloqueiam_e_contam_com_as_do_login(ger):
    sess = _sess("fulano")
    ger.limite_usuario.registrar(S.chave_usuario("Fulano"))  # 1 falha de login (mesma conta, outra caixa)
    assert not ger.confirmacao_bloqueada(sess)
    ger.falha_confirmacao(sess)
    ger.falha_confirmacao(sess)
    assert ger.confirmacao_bloqueada(sess), "login + confirmação deveriam somar no mesmo teto"
    assert ger.limite_usuario.bloqueado(S.chave_usuario("fulano")), "o login da conta também fica bloqueado"


def test_limite_e_por_conta(ger):
    a, b = _sess("a"), _sess("b")
    for _ in range(3):
        ger.falha_confirmacao(a)
    assert ger.confirmacao_bloqueada(a) and not ger.confirmacao_bloqueada(b)


def test_chave_de_falhas_fora_do_repr():
    assert S.chave_usuario("fulano") not in repr(_sess("fulano"))
