"""SEG·SEGREDOS — a imagem e o compose continuam endurecidos (regressão estática, sem docker).

Prova de execução (docker real, rede própria, mock do SIGAA) está no relatório da frente."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
yaml = pytest.importorskip("yaml")


def _docker() -> str:
    return (RAIZ / "Dockerfile").read_text(encoding="utf-8")


def _final(df: str) -> str:
    """Só a última etapa (a imagem que roda)."""
    return re.split(r"(?m)^FROM ", df)[-1]


def _compose() -> dict:
    return yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["sigaa-api"]


def test_dependencias_so_do_lock_com_hash():
    df = _docker()
    assert "--require-hashes" in df and "requirements.lock" in df
    assert not re.search(r"pip install[^\n]*\s\.(\[|\s|$)", df), "pip install . resolve dependência fora do lock"


def test_imagem_final_sem_root_sem_pip_e_com_healthcheck():
    fin = _final(_docker())
    m = re.search(r"(?m)^USER\s+(\S+)", fin)
    assert m and m.group(1).split(":")[0] not in ("root", "0")
    assert "HEALTHCHECK" in fin
    assert "pip install" not in fin  # nada instalado na etapa final
    assert re.search(r"(?m)^FROM \S+@sha256:[0-9a-f]{64}|^ARG BASE=\S+@sha256:[0-9a-f]{64}", _docker())


def test_cmd_sem_server_header_e_sem_core_dump():
    cmd = _final(_docker()).split("CMD", 1)[1]
    assert "--no-server-header" in cmd and "ulimit -c 0" in cmd


def test_forwarded_allow_ips_explicito_e_nunca_loopback_ou_asterisco():
    """Dentro do contêiner o proxy reverso NUNCA é 127.0.0.1: com esse valor o XFF nunca vale e todo cliente
    vira o IP do proxy (o limite de login por IP vira um limite GLOBAL). '*' deixa o cliente forjar o IP."""
    m = re.search(r'FORWARDED_ALLOW_IPS=("?)([^"\s]*)\1', _final(_docker()))
    assert m is not None
    assert m.group(2) not in ("127.0.0.1", "127.0.0.1,::1", "*")
    c = _compose()["environment"]["FORWARDED_ALLOW_IPS"]
    padrao = re.sub(r"^\$\{FORWARDED_ALLOW_IPS:-(.*)\}$", r"\1", c)
    assert padrao and padrao not in ("127.0.0.1", "*") and "/" not in padrao  # um IP: o do proxy, não a rede toda
    # e esse IP é o reservado pro proxy na rede própria do compose (não o gateway, por onde chega a porta publicada)
    redes = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))["networks"]
    sub = next(iter(redes.values()))["ipam"]["config"][0]["subnet"]
    import ipaddress

    rede = ipaddress.ip_network(sub)
    assert ipaddress.ip_address(padrao) in rede and ipaddress.ip_address(padrao) != next(rede.hosts())


def test_compose_endurecido():
    s = _compose()
    assert s.get("read_only") is True
    assert s.get("cap_drop") == ["ALL"]
    assert "no-new-privileges:true" in s.get("security_opt", [])
    assert s.get("ulimits", {}).get("core") == 0
    assert s["environment"].get("SIGAA_API_CORS") != "*"
    assert all(str(p).startswith("127.0.0.1:") for p in s.get("ports", []))


def test_dockerignore_lista_branca():
    di = (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*" in di  # tudo fora...
    entra = {linha[1:].rstrip("/") for linha in di if linha.startswith("!")}
    assert entra <= {"requirements.lock", "sigaa", "api"}  # ...só o necessário entra (nada de tests/recon/bench/.git)
