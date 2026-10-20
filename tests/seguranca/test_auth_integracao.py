"""SEG·AUTH — integração com o SIGAA SIMULADO (bench/mock_sigaa.py) e a API de verdade (bench/_lancador.py).

Nunca fala com o SIGAA real: o lançador aponta a API pro mock local e bloqueia https. Portas 8180–8183
(faixa da frente de segurança/auth); se estiverem ocupadas, o teste é pulado.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

RAIZ = Path(__file__).resolve().parents[2]
MOCK, API_A, API_B = 8180, 8181, 8182


def _livre(porta: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def _esperar(url: str, prazo: float = 60) -> None:
    fim = time.time() + prazo
    while time.time() < fim:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{url} não subiu")


@pytest.fixture(scope="module")
def bancada():
    if not all(_livre(p) for p in (MOCK, API_A, API_B)):
        pytest.skip("portas 8180–8182 ocupadas")
    if not (RAIZ / "bench" / "mock_sigaa.py").exists():
        pytest.skip("sem bench/mock_sigaa.py")
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SIGAA_", "FORWARDED_"))}
    base.update(SIGAA_PARSE_PROCESSOS="0", SIGAA_API_KEEPALIVE="false")
    procs: list[subprocess.Popen] = []  # só os processos que ESTE teste subiu (e só eles são mortos)

    def subir(*args, **env):
        p = subprocess.Popen([sys.executable, *args], cwd=RAIZ, env={**base, **env},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)
        return p

    try:
        subir("bench/mock_sigaa.py", "--porta", str(MOCK), "--fator", "0")
        _esperar(f"http://127.0.0.1:{MOCK}/__mock/stats")
        lanc = ["bench/_lancador.py", "--worktree", ".", "--sigaa", f"http://127.0.0.1:{MOCK}"]
        # A: limite por usuário baixo; B: API "exposta direto" (nenhum proxy confiável) e limite por IP baixo
        subir(*lanc, "--porta", str(API_A), SIGAA_API_MAX_FALHAS_POR_USUARIO="3")
        subir(*lanc, "--porta", str(API_B), SIGAA_API_MAX_LOGINS_POR_IP="3", FORWARDED_ALLOW_IPS="")
        _esperar(f"http://127.0.0.1:{API_A}/")
        _esperar(f"http://127.0.0.1:{API_B}/")
        yield
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


def _stats() -> dict:
    return httpx.get(f"http://127.0.0.1:{MOCK}/__mock/stats").json()


def _logins_e_logouts() -> tuple[int, int]:
    st = _stats()
    return st["logins"], st["por_regra"].get("logout", 0)


def test_login_token_logout_token_morto_e_nada_logado_no_sigaa(bancada):
    api = f"http://127.0.0.1:{API_A}"
    lg0, lo0 = _logins_e_logouts()
    r = httpx.post(f"{api}/v1/auth/login", json={"usuario": "aluno.integracao", "senha": "x", "lembrar": True}, timeout=30)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert httpx.get(f"{api}/v1/auth/sessao", headers=h).status_code == 200
    time.sleep(0.3)  # logout no meio do aquecimento do pool / pré-aquecimento do cache
    assert httpx.delete(f"{api}/v1/auth/sessao", headers=h, timeout=30).status_code == 204
    for rota in ("/v1/auth/sessao", "/v1/portal", "/v1/me"):  # nem rota, nem cache L1 aceitam o token velho
        r = httpx.get(api + rota, headers=h, timeout=30)
        assert r.status_code == 401 and r.json()["erro"]["codigo"] == "token_invalido", (rota, r.text)
    time.sleep(1.5)  # tarefas canceladas terminam de fechar
    lg1, lo1 = _logins_e_logouts()
    assert lg1 > lg0
    assert lo1 - lo0 >= lg1 - lg0, f"{lg1 - lg0} logins no SIGAA e só {lo1 - lo0} logouts: sessão órfã logada"


def test_forca_bruta_por_usuario_bloqueia(bancada):
    api = f"http://127.0.0.1:{API_A}"
    for _ in range(3):
        r = httpx.post(f"{api}/v1/auth/login", json={"usuario": "vitima.integracao", "senha": "errada"}, timeout=30)
        assert r.status_code == 401 and r.json()["erro"]["codigo"] == "credenciais_invalidas"
    lg0 = _stats()["por_regra"].get("login:recusado", 0) + _stats()["logins"]
    for senha in ("errada", "x"):
        r = httpx.post(f"{api}/v1/auth/login", json={"usuario": "vitima.integracao", "senha": senha}, timeout=30)
        assert r.status_code == 429 and r.json()["erro"]["codigo"] == "muitas_tentativas"
    assert _stats()["por_regra"].get("login:recusado", 0) + _stats()["logins"] == lg0  # nem chegou ao SIGAA
    r = httpx.post(f"{api}/v1/auth/login", json={"usuario": "outro.integracao", "senha": "x"}, timeout=30)
    assert r.status_code == 200
    httpx.delete(f"{api}/v1/auth/sessao", headers={"Authorization": f"Bearer {r.json()['token']}"}, timeout=30)


def test_xff_forjado_nao_muda_a_chave_do_limite(bancada):
    api = f"http://127.0.0.1:{API_B}"
    for i in range(3):
        r = httpx.post(f"{api}/v1/auth/login", json={"usuario": f"xff.{i}", "senha": "errada"},
                       headers={"X-Forwarded-For": f"203.0.113.{i}"}, timeout=30)
        assert r.status_code == 401
    r = httpx.post(f"{api}/v1/auth/login", json={"usuario": "xff.9", "senha": "errada"},
                   headers={"X-Forwarded-For": "203.0.113.99", "X-Real-IP": "203.0.113.98"}, timeout=30)
    assert r.status_code == 429
