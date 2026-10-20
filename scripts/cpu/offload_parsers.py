"""Reescreve as chamadas de parser dos serviços pra rodarem no pool de CPU (idempotente).

    .venv/bin/python scripts/cpu/offload_parsers.py [--checar] [arquivos...]   (padrão: sigaa/services/*.py)

Dentro de ``async def``: ``P.parse_x(page.html, y)`` → ``await rodar(P.parse_x, page.html, y)``
(com parênteses quando o resultado é usado como ``.attr``/``[i]``/``()``). Não mexe em
lambda, ``def`` síncrono nem gerador (onde ``await`` não cabe). Rodar de novo não muda nada —
serve pra reaplicar depois de um merge que trouxe chamadas novas.
``--checar``: só diz quantas chamadas ainda rodariam no event loop (sai 1 se houver).
"""

from __future__ import annotations

import ast
import glob
import sys

IMPORT = "from ..cpu import rodar\n"


def _eh_parser(call: ast.Call) -> bool:
    f = call.func
    nome = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
    return nome.startswith("parse_")


def _alvos(tree: ast.AST) -> list[tuple[ast.Call, bool]]:
    out: list[tuple[ast.Call, bool]] = []

    def visitar(no: ast.AST, em_async: bool, pai: ast.AST | None, dentro_parser: bool) -> None:
        if isinstance(no, ast.AsyncFunctionDef):
            em_async = True
        elif isinstance(no, ast.GeneratorExp):
            # só o iterável do 1º "for" roda no escopo de fora (onde o await vale)
            visitar(no.generators[0].iter, em_async, no.generators[0], dentro_parser)
            resto = [no.elt, *no.generators[0].ifs, *(x for g in no.generators[1:] for x in (g.iter, *g.ifs))]
            for filho in resto:
                visitar(filho, False, no, dentro_parser)
            return
        elif isinstance(no, (ast.FunctionDef, ast.Lambda)):
            em_async = False
        eh = isinstance(no, ast.Call) and _eh_parser(no)
        if eh and em_async and not dentro_parser:
            parens = isinstance(pai, (ast.Attribute, ast.Subscript)) or (isinstance(pai, ast.Call) and pai.func is no)
            out.append((no, parens))
        for filho in ast.iter_child_nodes(no):
            visitar(filho, em_async, no, dentro_parser or (eh and em_async))

    visitar(tree, False, None, False)
    return out


def _off(linhas: list[bytes], ln: int, col: int) -> int:
    return sum(len(x) for x in linhas[: ln - 1]) + col


def reescrever(fonte: str) -> tuple[str, int]:
    tree = ast.parse(fonte)
    alvos = _alvos(tree)
    if not alvos:
        return fonte, 0
    b = fonte.encode()
    linhas = b.splitlines(keepends=True)
    trocas = []
    for call, parens in alvos:
        ini = _off(linhas, call.lineno, call.col_offset)
        fim = _off(linhas, call.end_lineno, call.end_col_offset)
        fini = _off(linhas, call.func.end_lineno, call.func.end_col_offset)
        func = b[ini:fini]
        resto = b[fini:fim].lstrip()
        assert resto.startswith(b"(") and resto.endswith(b")"), resto[:40]
        dentro = resto[1:-1]
        novo = b"await rodar(" + func + ((b", " + dentro.lstrip()) if dentro.strip() else b"") + b")"
        if parens:
            novo = b"(" + novo + b")"
        trocas.append((ini, fim, novo))
    for ini, fim, novo in sorted(trocas, reverse=True):
        b = b[:ini] + novo + b[fim:]
    s = b.decode()
    if IMPORT.strip() not in s:
        # logo depois do último import do topo do módulo
        imps = [n for n in ast.parse(s).body if isinstance(n, (ast.Import, ast.ImportFrom)) and getattr(n, "module", None) != "__future__"]
        ls = s.splitlines(keepends=True)
        ls.insert(imps[-1].end_lineno, IMPORT)
        s = "".join(ls)
    ast.parse(s)  # tem que continuar válido
    return s, len(trocas)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    checar = "--checar" in sys.argv
    arquivos = args or sorted(glob.glob("sigaa/services/*.py"))
    total = 0
    for arq in arquivos:
        fonte = open(arq, encoding="utf-8").read()
        novo, n = reescrever(fonte)
        total += n
        if n:
            print(f"{arq}: {n} chamada(s) {'no event loop' if checar else '→ rodar()'}")
            if not checar:
                open(arq, "w", encoding="utf-8").write(novo)
    print(f"total: {total}")
    return 1 if (checar and total) else 0


if __name__ == "__main__":
    sys.exit(main())
