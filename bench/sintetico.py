"""Documentos SINTÉTICOS (nenhum dado real) que o SIGAA simulado entrega como PDF.

* ``historico_pdf()`` — Histórico Escolar no formato do SIGAA UFBA (o mesmo que
  ``sigaa/parsers/historico_pdf.py`` entende), com ~10 semestres e ~50 componentes, em várias
  páginas — o tamanho de um histórico de verdade, pra o custo do parse (pdfplumber) ser realista.
* ``declaracao_pdf()`` — Declaração de vínculo.

O PDF é escrito "à mão" (Helvetica + WinAnsiEncoding, texto de verdade), sem dependência nova.
"""

from __future__ import annotations

import random
import zlib

CAB = [
    "UFBA - Universidade Federal da Bahia",
    "Rua Augusto Viana, s/n - Canela - Salvador/BA - CEP 40110-909",
    "Documento Oficial",
    "Histórico Escolar - Emitido em: 05/03/2026 às 10:15",
]

DADOS = [
    "Dados Pessoais",
    "Nome: FULANO DE TAL DA SILVA Matrícula: 200000000",
    "Data de Nascimento: 01/01/2000 Local de Nascimento: SALVADOR/BA",
    "Nacionalidade: BRASILEIRA",
    "Nº do documento com órgão expedidor: 0000000, (SSP/BA)",
    "Nº do CPF: 000.000.000-00",
    "Dados do Vínculo do Discente",
    "Curso: SISTEMAS DE INFORMAÇÃO/IC/UFBA - SALVADOR - BACHARELADO - PRESENCIAL - N",
    "Status: ATIVO Índices Acadêmicos",
    "Ênfase: - IAP: 0.8000 CR: 7.5000 MC: 7.9000",
    "Currículo: G20251X - 2025.1",
    "Reconhecimento do Curso: 1, 01/01/2010. D.O.U.: 02/01/2010",
    "Ingresso: 2021.1 - 01/03/2021 Perfil Inicial:1",
    "Forma de Ingresso: SISU",
    "Período Letivo Atual: 11 Prazo para Conclusão (Padrão / Máximo):2025.2 / 2028.2",
    "Suspensões: -",
    "Prorrogações: -",
    "Conclusão: -",
    "Tipo Saída: -",
    "Data da Conclusão: - Data da Colação de Grau:-",
    "Trabalho de Conclusão de",
    "-",
    "Curso:",
    "Data da Expedição do Diploma: -",
]

COMPONENTES = [
    ("MATA37", "INTRODUÇÃO À LÓGICA DE PROGRAMAÇÃO", 68), ("MATA42", "MATEMÁTICA DISCRETA I", 68),
    ("MATA02", "CÁLCULO A", 102), ("MATA01", "GEOMETRIA ANALÍTICA", 68), ("ADM001", "INTRODUÇÃO À ADMINISTRAÇÃO", 68),
    ("MATA40", "ESTRUTURAS DE DADOS E ALGORITMOS I", 68), ("MATA55", "PROGRAMAÇÃO ORIENTADA A OBJETOS", 68),
    ("MATA07", "ÁLGEBRA LINEAR A", 68), ("MATA48", "ARQUITETURA DE COMPUTADORES", 68), ("LETA09", "OFICINA DE LEITURA E PRODUÇÃO DE TEXTOS", 68),
    ("MATA60", "BANCO DE DADOS", 68), ("MATA62", "ENGENHARIA DE SOFTWARE I", 68), ("MATA58", "SISTEMAS OPERACIONAIS", 68),
    ("MATB19", "ESTATÍSTICA PARA COMPUTAÇÃO", 68), ("CONT01", "CONTABILIDADE GERAL", 68),
    ("MATA59", "REDES DE COMPUTADORES I", 68), ("MATA63", "ENGENHARIA DE SOFTWARE II", 68), ("MATC84", "LABORATÓRIO DE PROGRAMAÇÃO WEB", 68),
    ("MATC89", "APLICAÇÕES PARA A WEB", 68), ("ECO001", "INTRODUÇÃO À ECONOMIA", 68),
    ("MATC82", "SISTEMAS WEB", 68), ("MATA64", "INTELIGÊNCIA ARTIFICIAL", 68), ("MATC72", "INTERAÇÃO HUMANO-COMPUTADOR", 68),
    ("MATC90", "SISTEMAS DE APOIO À DECISÃO", 68), ("ADM002", "GESTÃO DE PROJETOS", 68),
    ("MATC94", "INTRODUÇÃO ÀS LINGUAGENS FORMAIS", 68), ("MATA61", "COMPILADORES", 68), ("MATC85", "SEGURANÇA DA INFORMAÇÃO", 68),
    ("MATC86", "MINERAÇÃO DE DADOS", 68), ("DIR001", "DIREITO E INFORMÁTICA", 68),
    ("MATC87", "COMPUTAÇÃO MÓVEL", 68), ("MATC88", "COMPUTAÇÃO EM NUVEM", 68), ("MATC91", "GOVERNANÇA DE TI", 68),
    ("MATC92", "EMPREENDEDORISMO EM TI", 68), ("MATC93", "TÓPICOS EM SISTEMAS DE INFORMAÇÃO", 68),
    ("MATC95", "PROCESSAMENTO DE IMAGENS", 68), ("MATC96", "SISTEMAS DISTRIBUÍDOS", 68), ("MATC97", "QUALIDADE DE SOFTWARE", 68),
    ("MATC98", "AUDITORIA DE SISTEMAS", 68), ("MATC99", "ÉTICA EM COMPUTAÇÃO", 68),
    ("MATD01", "LABORATÓRIO DE BANCO DE DADOS", 68), ("MATD02", "ANÁLISE DE ALGORITMOS", 68), ("MATD03", "PROJETO DE SISTEMAS", 68),
    ("MATD05", "METODOLOGIA CIENTÍFICA", 34), ("MATD06", "TRABALHO DE CONCLUSÃO DE CURSO I", 68),
]
DOCENTES = ["Dr. DOCENTE UM", "Dra. DOCENTE DOIS", "MSc. DOCENTE TRES", "Esp. DOCENTE QUATRO", "Dr. DOCENTE CINCO", "Dra. DOCENTE SEIS"]
PERIODOS = ["2021.1", "2021.2", "2022.1", "2022.2", "2023.1", "2023.2", "2024.1", "2024.2", "2025.1", "2025.2", "2026.1"]


def _linhas_componentes(rng: random.Random) -> list[str]:
    out = []
    for i, (cod, nome, ch) in enumerate(COMPONENTES):
        per = PERIODOS[min(i // 5, len(PERIODOS) - 1)]
        nat = "OP" if cod.startswith(("ADM", "CONT", "ECO", "DIR")) or cod in ("MATC93", "MATC95") else "OB"
        if i >= len(COMPONENTES) - 4:
            nota, sit = "--", "MATR"
        else:
            n = round(rng.uniform(3.0, 10.0), 1)
            sit = "APR" if n >= 5 else ("REPF" if n < 3.5 else "REP")
            nota = f"{n:.1f}"
        out.append(nome)
        out.append(f"{per} {nat} {cod} {ch} {nota} {sit}")
        d = rng.choice(DOCENTES)
        out.append(f"{d} ({ch}h)")
    return out


RODAPE_FIM = [
    "Legenda",
    "OP Optativo OB Obrigatório",
    "SIGLA SIGNIFICADO",
    "APR Aprovado",
    "REP Reprovado",
    "REPF Reprovado por Falta",
    "MATR Matriculado",
    "Carga Horária e Créditos Integralizados/Pendentes",
    "Obrigatórias Optativos Complementares Total",
    "Exigido 2380 h 340 h 180 h 2900 h",
    "Integralizado 1904 h 272 h 120 h 2296 h",
    "Pendente 476 h 68 h 60 h 604 h",
    "Componentes Curriculares Obrigatórios Pendentes:3",
    "Código Componente Curricular CH",
    "MATD02 ANÁLISE DE ALGORITMOS Matriculado 68 h",
    "MATD03 PROJETO DE SISTEMAS Matriculado 68 h",
    "MATD06 TRABALHO DE CONCLUSÃO DE CURSO I Matriculado 68 h",
    "Equivalências:",
    "Observações:",
    "-",
]


def _paginas_historico() -> list[list[str]]:
    rng = random.Random(42)
    corpo = DADOS + ["Componentes Curriculares Cursados/Cursando", "Semestre Componente Curricular CH Nota Situação"]
    corpo += _linhas_componentes(rng) + RODAPE_FIM
    por_pag = 52
    blocos = [corpo[i : i + por_pag] for i in range(0, len(corpo), por_pag)]
    n = len(blocos)
    pags = []
    for k, b in enumerate(blocos, 1):
        rod = [
            "Para verificar sua autenticidade entre em https://sigaa.ufba.br/sigaa/documentos informando a matrícula, data de emissão e o código de",
            f"Página {k} de {n}",
            "verificação: 0000000000",
        ]
        cab = CAB + (["Nome: FULANO DE TAL DA SILVA Matrícula: 200000000"] if k > 1 else [])
        if k > 1 and b and not b[0].startswith("Componentes"):
            b = ["Componentes Curriculares Cursados/Cursando", "Semestre Componente Curricular CH Nota Situação"] + b
        pags.append(cab + b + rod)
    return pags


def _esc(s: str) -> bytes:
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _pdf(paginas: list[list[str]]) -> bytes:
    """PDF mínimo e válido: 1 fonte (Helvetica/WinAnsi), 1 stream comprimido por página."""
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    fonte = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(paginas)  # reservado depois das páginas
    kids = []
    for linhas in paginas:
        ops = [b"BT /F1 8 Tf 10 TL 36 806 Td"]
        for ln in linhas:
            ops.append(b"(" + _esc(ln) + b") Tj T*")
        ops.append(b"ET")
        # bordas de tabela como o JasperReports desenha (cada linha vira célula com retângulo + fios):
        # é o que faz o pdfplumber gastar ~300 ms num histórico real
        for i in range(len(linhas)):
            y = 806 - 10 * i - 2
            for x in (34, 77, 120, 225, 330, 365, 400, 425, 450, 475, 500, 530):
                ops.append(b"%d %d %d 10 re S" % (x, y, 43 if x < 120 else 25))
            ops.append(b"34 %d m 561 %d l S" % (y, y))
        raw = b"\n".join(ops)
        z = zlib.compress(raw)
        cont = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream")
        kids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>"
            % (pages_id, cont, fonte)
        ))
    assert len(objs) + 1 == pages_id
    add(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids))
    cat = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offs:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
    return bytes(out)


def historico_pdf() -> bytes:
    return _pdf(_paginas_historico())


DECLARACAO = [
    "UNIVERSIDADE FEDERAL DA BAHIA",
    "SISTEMA INTEGRADO DE GESTÃO DE ATIVIDADES ACADÊMICAS",
    "DECLARAÇÃO DE VÍNCULO",
    "Declaramos, para os devidos fins, que FULANO DE TAL DA SILVA, matrícula 200000000, CPF 000.000.000-00,",
    "é aluno(a) regularmente matriculado(a) no curso de SISTEMAS DE INFORMAÇÃO/IC/UFBA - SALVADOR - BACHARELADO",
    "- PRESENCIAL - N, no período letivo 2026.2.",
    "Salvador, 05 de Março de 2026",
    "Para verificar a autenticidade deste documento acesse https://sigaa.ufba.br/sigaa/documentos informando a matrícula,",
    "a data de emissão do documento e o código de verificação: 0000000000",
]


def declaracao_pdf() -> bytes:
    return _pdf([DECLARACAO])


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import time

    from sigaa.parsers.historico_pdf import parse_historico_pdf

    pdf = historico_pdf()
    t = time.perf_counter()
    h = parse_historico_pdf(pdf)
    dt = time.perf_counter() - t
    print(f"histórico sintético: {len(pdf)} bytes, parse {dt*1000:.0f} ms, {len(h.componentes)} componentes, "
          f"CR={h.indices.cr if h.indices else None}, não reconhecidas={len(h.linhas_nao_reconhecidas)}")
