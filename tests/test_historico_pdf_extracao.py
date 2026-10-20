"""Extração de texto do PDF: o caminho rápido (PDFium) tem de dar o MESMO texto do pdfplumber.

O PDF é montado aqui mesmo (Helvetica, sem fonte embutida) — nada de documento real.
"""

import sys

from sigaa.parsers import historico_pdf as H


def _pdf_sintetico(paginas: list[list[tuple[float, float, int, str]]], rotacao: int = 0) -> bytes:
    """PDF mínimo: cada página é uma lista de (x, y, tamanho da fonte, texto)."""
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    kids = []
    for linhas in paginas:
        stream = b"".join(
            b"BT /F1 %d Tf %g %g Td (%s) Tj ET\n"
            % (tam, x, y, t.encode("cp1252").replace(b"(", b"\\(").replace(b")", b"\\)"))
            for x, y, tam, t in linhas
        )
        conteudo, pagina = len(objs) + 2, len(objs) + 3
        objs[conteudo] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        objs[pagina] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Rotate %d "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (rotacao, conteudo)
        )
        kids.append(pagina)
    objs[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for k in sorted(objs):
        offsets[k] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (k, objs[k])
    xref, n = len(out), max(objs) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % n
    out += b"".join(b"%010d 00000 n \n" % offsets[k] for k in range(1, n))
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (n, xref)
    return bytes(out)


PAG_COMPONENTES = [
    (40, 800, 10, "Componentes Curriculares Cursados/Cursando"),
    (40, 780, 9, "CÁLCULO A"),
    (40, 768, 9, "2024.2"),
    (80, 768, 9, "OB"),
    (110, 768, 9, "MATA02"),
    (160, 768, 9, "90"),
    (190, 768, 9, "7.5"),
    (220, 768, 9, "APR"),
    (40, 756, 8, "Dr. FULANO DE TAL (90h)"),
    (300, 756, 8, "colado"),
    (330.5, 756, 8, "quase"),
    (40, 740, 9, "Média (ç ã é)"),
]
PAG_LEGENDA = [(40, 800, 12, "Legenda"), (40, 780, 9, "APR - Aprovado")]


def test_pdfium_igual_ao_pdfplumber():
    pdf = _pdf_sintetico([PAG_COMPONENTES, PAG_LEGENDA, []])
    rapido = H._extrair_texto_pdfium(pdf)
    assert rapido is not None
    assert rapido == H._extrair_texto_pdfplumber(pdf)
    assert rapido[0].split("\n")[2] == "2024.2 OB MATA02 90 7.5 APR"
    assert rapido[2] == ""
    assert H.extrair_texto(pdf) == rapido


def test_pagina_girada_cai_no_pdfplumber():
    pdf = _pdf_sintetico([PAG_COMPONENTES], rotacao=90)
    assert H._extrair_texto_pdfium(pdf) is None
    assert H.extrair_texto(pdf) == H._extrair_texto_pdfplumber(pdf)


def test_sem_pypdfium2_cai_no_pdfplumber(monkeypatch):
    pdf = _pdf_sintetico([PAG_COMPONENTES])
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import vira ImportError
    assert H.extrair_texto(pdf) == H._extrair_texto_pdfplumber(pdf)
