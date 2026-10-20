"""SEG·SEGREDOS (LGPD, retenção) — quando o token do aluno EXPIRA (TTL ou ociosidade), o cache dele
(L1/L2: dados pessoais e de terceiros) é apagado junto, como no logout. Antes ficava até o TTL+stale de
cada entrada (até dias), sem ninguém mais poder usar nem pedir pra apagar.

Sem rede: sessões falsas, cache em memória."""

from __future__ import annotations

import asyncio
import time

from api.config import config
from api.sessions import Gerenciador, Sessao
from sigaa.cache import Entrada, cache


def _sessao(uh: str, *, expira_em: float) -> Sessao:
    agora = time.time()
    return Sessao(cliente=None, pool=None, usuario_hash=uh, criada_em=agora - 10, expira_em=expira_em, lembrar=False)  # type: ignore[arg-type]


async def _cenario(monkeypatch, apagar: bool):
    monkeypatch.setattr(config, "CACHE_APAGAR_AO_EXPIRAR", apagar, raising=False)
    ger = Gerenciador()
    agora = time.time()
    ger._sessoes = {  # noqa: SLF001
        "t-expirado": _sessao("uh-expirado", expira_em=agora - 1),
        "t-vivo": _sessao("uh-vivo", expira_em=agora + 3600),
        # o mesmo aluno com OUTRO token ainda válido: o cache dele é compartilhado e fica
        "t-duplo-a": _sessao("uh-duplo", expira_em=agora - 1),
        "t-duplo-b": _sessao("uh-duplo", expira_em=agora + 3600),
    }
    chaves = {uh: f"u:{cache.aluno(uh)}:/v1/me" for uh in ("uh-expirado", "uh-vivo", "uh-duplo")}
    for k in chaves.values():
        await cache.backend.gravar(k, Entrada(corpo=b'{"nome": "ficticio"}', criado=time.time(), ttl=3600, sensivel=True))
    ger._expurgar()  # noqa: SLF001
    await asyncio.gather(*list(ger._fechando), return_exceptions=True)  # noqa: SLF001
    resto = {uh: (await cache.backend.obter(k)) is not None for uh, k in chaves.items()}
    for k in chaves.values():
        await cache.backend.apagar_prefixo(k)
    return resto


def test_token_expirado_apaga_o_cache_do_aluno(monkeypatch):
    resto = asyncio.run(_cenario(monkeypatch, apagar=True))
    assert resto == {"uh-expirado": False, "uh-vivo": True, "uh-duplo": True}


def test_variavel_desliga(monkeypatch):
    resto = asyncio.run(_cenario(monkeypatch, apagar=False))
    assert resto == {"uh-expirado": True, "uh-vivo": True, "uh-duplo": True}


def test_padrao_ligado():
    from api.config import Config

    assert Config.CACHE_APAGAR_AO_EXPIRAR is True
