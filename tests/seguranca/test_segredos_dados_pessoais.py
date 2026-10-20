"""SEG·SEGREDOS — nenhum arquivo versionado carrega dado pessoal real ou cookie de sessão real.

As fixtures vêm de páginas reais do SIGAA e foram anonimizadas (CPF com dígito verificador inválido,
matrículas sequenciais, e-mails @exemplo.br, "FULANO DE TAL", JSESSIONID zerado). Este teste segura isso
quando alguém grava uma página nova.

O teste nunca imprime o valor achado — só o arquivo e a linha."""

from __future__ import annotations

import hashlib
import re
import subprocess
from html import unescape
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]

#: e-mails institucionais PÚBLICOS que aparecem em páginas públicas gravadas (só o SHA-256, de propósito)
EMAILS_INSTITUCIONAIS = {
    "3345c5778bd514b640dc04e79338284fcee41bd8c92c164fa5e180827b66f17a",
    "3240fa441cb0503ec6810a995507fe2bc393b55c8893172c69629e0b818c6726",
    "902f028dafce91563ae82b79b643f95a3d60b1b5cae998a6293fc66af586b75d",
}
DOMINIOS_FICTICIOS = re.compile(r"(?i)@(?:[\w-]+\.)*(?:exemplo|example)\.[a-z.]+$|@users\.noreply\.github\.com$")


def _versionados() -> list[Path]:
    try:
        saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("fora de um checkout git")
    return [RAIZ / f for f in saida.splitlines() if f.endswith((".html", ".htm", ".py", ".md", ".json", ".txt", ".csv", ".yml", ".yaml", ".toml", ".sh", ".js"))]


def _texto(p: Path) -> str:
    b = p.read_bytes()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def _cpf_valido(c: str) -> bool:
    d = [int(x) for x in re.sub(r"\D", "", c)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        if (sum(d[i] * (n + 1 - i) for i in range(n)) * 10) % 11 % 10 != d[n]:
            return False
    return True


def _achados(rx: re.Pattern[str], ok) -> list[str]:
    ruins = []
    for p in _versionados():
        for i, linha in enumerate(_texto(p).splitlines(), 1):
            for m in rx.finditer(linha):
                if not ok(m.group(0)):
                    ruins.append(f"{p.relative_to(RAIZ)}:{i}")
    return ruins


def test_nenhum_cpf_valido_versionado():
    assert _achados(re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), lambda c: not _cpf_valido(c)) == []


def test_emails_so_ficticios_ou_institucionais():
    # (?<![/:\w]): "usuario:senha@host" / "https://a@b" de URL de teste não é e-mail
    rx = re.compile(r"(?<![/:\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
    ok = lambda e: bool(DOMINIOS_FICTICIOS.search(e)) or hashlib.sha256(e.encode()).hexdigest() in EMAILS_INSTITUCIONAIS  # noqa: E731
    assert _achados(rx, ok) == []


def test_jsessionid_das_fixtures_zerado():
    rx = re.compile(r"(?i)jsessionid=([0-9a-z]{6,})")
    assert _achados(rx, lambda s: set(s.split("=", 1)[1].upper()) <= {"0"}) == []


def test_membros_do_laboratorio_sao_ficticios():
    """A página de laboratório gravada (outra instituição) vinha com nomes reais dos membros."""
    t = unescape(_texto(RAIZ / "tests/fixtures/consultas/publico/extras2/ref_pq_lab_detalhe.html"))
    nomes = re.findall(r">\s*([A-ZÀ-Ý][A-ZÀ-Ý]+(?: [A-ZÀ-Ý0-9]+){1,7})\s*<", t)
    pessoas = [n for n in nomes if not n.startswith(("COLABORADOR", "COORDENADOR"))]
    assert pessoas and all(n.startswith("PESQUISADOR FICTICIO") for n in pessoas)
