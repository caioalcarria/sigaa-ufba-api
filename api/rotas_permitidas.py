"""Lista de rotas permitidas (opcional): uma instância que serve UM cliente expõe só o que ele usa.

``SIGAA_API_ROTAS_PERMITIDAS`` = caminhos separados por vírgula. ``*`` no fim = prefixo
(``/v1/auth/*``, ``/v1/indices*``); sem ``*`` = caminho exato (``/v1/status``). Vazio (padrão) = todas as
rotas, como antes. Fora da lista = 404 ``nao_encontrado``, igual a uma rota que não existe (não revela o
mapa da API). ``/`` fica sempre liberado (é o HEALTHCHECK da imagem).

Motivo: a API tem rotas com dado pessoal sensível (``/v1/me/dados-pessoais``: raça e necessidades
especiais — LGPD art. 11) e de terceiros (participantes, fotos). Quem hospeda só pra um front que não
usa essas rotas reduz o que fica exposto se um token vazar. ASGI puro.
"""

from __future__ import annotations

from starlette.responses import JSONResponse

MSG = "Rota não disponível nesta instância."


def ler_padroes(valor: str) -> tuple[tuple[str, ...], frozenset[str]]:
    """'/a/*,/b' → (prefixos, exatos)."""
    prefixos: list[str] = []
    exatos: set[str] = set()
    for item in (x.strip() for x in valor.split(",")):
        if not item:
            continue
        if not item.startswith("/"):
            raise ValueError(f"SIGAA_API_ROTAS_PERMITIDAS: '{item}' precisa começar com '/'")
        if item.endswith("*"):
            prefixos.append(item[:-1])
        else:
            exatos.add(item.rstrip("/") or "/")
    return tuple(prefixos), frozenset(exatos)


def permitido(caminho: str, prefixos: tuple[str, ...], exatos: frozenset[str]) -> bool:
    if caminho == "/":
        return True
    segmentos = caminho.split("/")[1:]
    # sem '.', '..' nem '//' (o proxy normaliza; aqui é defesa em profundidade contra prefixo + travessia)
    if any(s in ("", ".", "..") for s in segmentos[:-1]) or segmentos[-1] in (".", ".."):
        return False
    if (caminho.rstrip("/") or "/") in exatos:
        return True
    return any(caminho.startswith(p) for p in prefixos)


class RotasPermitidas:
    def __init__(self, app, padroes: str) -> None:
        self.app = app
        self.prefixos, self.exatos = ler_padroes(padroes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or permitido(scope.get("path", "/"), self.prefixos, self.exatos):
            return await self.app(scope, receive, send)
        await JSONResponse(status_code=404, content={"erro": {"codigo": "nao_encontrado", "mensagem": MSG}})(scope, receive, send)
