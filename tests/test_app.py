"""O app sobe, todas as rotas entram no OpenAPI e a autenticação/erros respondem no formato certo (sem rede)."""

from fastapi.testclient import TestClient

from api.main import ROTAS, app

cliente = TestClient(app)


def test_todas_as_frentes_registradas():
    caminhos = app.openapi()["paths"]
    assert len(caminhos) > 100
    for prefixo in ["/v1/auth/login", "/v1/me", "/v1/historico", "/v1/planejamento/matricula", "/v1/turmas/{turma_id}/notas", "/v1/fotos"]:
        assert prefixo in caminhos, prefixo
    assert {"auth", "portal", "turma_virtual", "academico", "planejamento", "consultas", "midia"} <= set(ROTAS)


def test_sem_token_da_401_padronizado():
    r = cliente.get("/v1/historico")
    assert r.status_code == 401 and r.json()["erro"]["codigo"] == "nao_autenticado"
    r = cliente.get("/v1/historico", headers={"Authorization": "Bearer xyz"})
    assert r.status_code == 401 and r.json()["erro"]["codigo"] == "token_invalido"


def test_validacao_da_422_padronizado():
    r = cliente.post("/v1/auth/login", json={})
    assert r.status_code == 422 and r.json()["erro"]["codigo"] == "requisicao_invalida"
