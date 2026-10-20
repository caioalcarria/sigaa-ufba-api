"""Gera docs/ENDPOINTS.md a partir do OpenAPI da aplicação (rode depois de mexer nas rotas)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from api.main import app  # noqa: E402

spec = app.openapi()
por_tag: dict[str, list[tuple[str, str, str, bool]]] = {}
for caminho, ops in spec["paths"].items():
    for metodo, op in ops.items():
        tag = (op.get("tags") or ["Outros"])[0]
        publica = not op.get("security")
        por_tag.setdefault(tag, []).append((metodo.upper(), caminho, op.get("summary", ""), publica))
linhas = ["# Endpoints", "", f"Gerado de `api.main:app` — {sum(len(v) for v in por_tag.values())} rotas. Detalhes de cada campo em `/docs` (Swagger).", ""]
linhas += ["🔓 = não precisa de login · 🔒 = `Authorization: Bearer <token>`", ""]
for tag, rotas in por_tag.items():
    linhas += [f"## {tag}", "", "| | método | rota | o que faz |", "|---|---|---|---|"]
    for m, c, s, pub in rotas:
        linhas.append(f"| {'🔓' if pub else '🔒'} | `{m}` | `{c}` | {s} |")
    linhas.append("")
pathlib.Path("docs/ENDPOINTS.md").write_text("\n".join(linhas), encoding="utf-8")
print("docs/ENDPOINTS.md:", sum(len(v) for v in por_tag.values()), "rotas")
