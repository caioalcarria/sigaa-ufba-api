"""Cliente SIGAA falso pros testes de SEG·HTTP: registra o que a rota pediu ao SIGAA e devolve o que o teste mandar.

Sem rede: entra no lugar de ``api.deps._cliente`` por ``app.dependency_overrides``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

from api import deps
from api.main import app
from sigaa.client import Page


class ClienteFalso:
    base_url = "https://sigaa.ufba.br"

    def __init__(self, resposta: Any = None, *, conteudo: bytes = b"\xff\xd8\xff", tipo: str = "image/jpeg", erro: BaseException | None = None):
        self.pedidos: list[str] = []
        self.resposta, self.conteudo, self.tipo, self.erro = resposta, conteudo, tipo, erro

    async def get(self, caminho: str, **_):
        self.pedidos.append(caminho)
        return Page(url=self.base_url + caminho, status=200, content=self.conteudo, content_type=self.tipo)

    async def executar(self, fluxo):
        if self.erro is not None:
            raise self.erro
        if self.resposta is not None:
            return self.resposta
        return await fluxo(self)


@contextmanager
def com_cliente(falso: ClienteFalso):
    app.dependency_overrides[deps._cliente] = lambda: falso
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(deps._cliente, None)


AUTH = {"Authorization": "Bearer teste"}
