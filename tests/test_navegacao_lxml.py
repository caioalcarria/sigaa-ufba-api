"""O caminho rápido da navegação (lxml direto) tem que dar EXATAMENTE o que o BeautifulSoup dava:
links jsfcljs (texto, form, params, title) e os campos/action de cada formulário, em TODAS as fixtures."""

from pathlib import Path

import pytest

from sigaa.client import Page, _campos_lxml, form_fields

FIXTURES = sorted(p for p in (Path(__file__).parent / "fixtures").rglob("*.html"))


def _pagina(p: Path) -> Page:
    return Page(url="https://sigaa.ufba.br/sigaa/x/tela.jsf", status=200, content=p.read_bytes(), content_type="text/html")


def _links_bs4(page: Page):
    import re

    from sigaa.client import _RE_JSFCLJS, _RE_PARAMS

    out = []
    for el in page.soup.find_all(onclick=re.compile("jsfcljs")):
        m = _RE_JSFCLJS.search(el["onclick"])
        if m:
            out.append((el.get_text(" ", strip=True) or el.get("title") or "", m.group(1), dict(_RE_PARAMS.findall(m.group(2))), el["onclick"], el.get("title")))
    return out


@pytest.mark.parametrize("arq", FIXTURES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_links_iguais(arq):
    page = _pagina(arq)
    rapido = [(ln.texto, ln.form_id, ln.params, ln.onclick, ln.element.get("title")) for ln in page._links_jsf_lxml()]
    assert rapido == _links_bs4(_pagina(arq))


@pytest.mark.parametrize("arq", FIXTURES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_formularios_iguais(arq):
    page = _pagina(arq)
    ids = {f.get("id") or f.get("name") for f in page.soup.find_all("form")} - {None}
    for fid in ids:
        rapido = _campos_lxml(_pagina(arq), fid)
        if rapido is None:
            continue  # o caminho do BeautifulSoup assume (form aninhado / não achado)
        form = page.form(fid)
        assert rapido == (form.get("action") or "", form_fields(form)), fid
