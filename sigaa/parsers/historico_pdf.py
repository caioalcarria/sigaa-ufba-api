"""Histórico Escolar (PDF do SIGAA) → modelo ``Historico``.

O PDF é texto de verdade (não imagem), então o ``pdfplumber`` devolve as linhas na
ordem de leitura. O parser é uma máquina de estados por SEÇÃO (o título da seção
muda o estado) e, dentro de cada seção, reconhece as linhas por padrão — nunca por
posição fixa. Seção desconhecida ou linha estranha não derruba o parser: vai pra
``linhas_nao_reconhecidas``.

Formato observado (UFBA, SIGAA 4.13) — bloco de cada componente cursado::

    NOME DO COMPONENTE
    2024.2 OB MATA58 60 7.0 APR          ← período [natureza] código CH nota situação
    Dr. FULANO DE TAL (60h), MSc. ...    ← docentes (pode faltar ou quebrar em 2 linhas)
"""

from __future__ import annotations

import io
import re
import threading
import unicodedata
from collections import OrderedDict
from datetime import date, datetime

from ..models.academico import (
    AtividadeAutonomaResumo,
    CargaExtensionista,
    CargaHorariaCategoria,
    ComponenteCursado,
    ComponentePendente,
    ComponenteRef,
    DadosPessoaisHistorico,
    Docente,
    Equivalencia,
    EstatisticaPeriodo,
    EstatisticasHistorico,
    Historico,
    Indices,
    Legenda,
    VinculoHistorico,
)

# Legendas padrão do SIGAA (usadas quando o PDF não traz a legenda inteira).
NATUREZAS_PADRAO = {
    "OB": "Obrigatório",
    "OP": "Optativo",
    "EB": "Equivalente Obrigatório",
    "EP": "Equivalente a Optativo",
    "LV": "Livre",
    "EC": "Equivalente a Complementar",
    "CO": "Complementar",
}
SITUACOES_PADRAO = {
    "APR": "Aprovado",
    "APRN": "Aprovado por Nota",
    "CANC": "Cancelado",
    "DISP": "Dispensado",
    "MATR": "Matriculado",
    "REP": "Reprovado",
    "REPF": "Reprovado por Falta",
    "REPN": "Reprovado por Nota",
    "REPMF": "Reprovado por Média e Falta",
    "REPNF": "Reprovado por Nota e Falta",
    "TRANC": "Trancado",
    "TRANS": "Transferido",
    "INCORP": "Incorporado",
    "CUMP": "Cumpriu",
    "AE": "Aproveitamento de Estudos",
}
APROVADO = {"APR", "APRN", "DISP", "INCORP", "CUMP", "TRANS", "AE"}
REPROVADO = {"REP", "REPF", "REPN", "REPMF", "REPNF"}
TRANCADO = {"TRANC", "CANC"}

_SECOES = [
    ("dados", r"^Dados Pessoais$"),
    ("vinculo", r"^Dados do V[ií]nculo do Discente$"),
    ("componentes", r"^Componentes Curriculares Cursados(/Cursando)?$"),
    ("legenda", r"^Legenda$"),
    ("autonomas", r"^Atividades Aut[ôo]nomas do Discente$"),
    ("ch", r"^Carga Hor[áa]ria e Cr[ée]ditos Integralizados/Pendentes$"),
    ("extensao", r"^Carga Hor[áa]ria Extensionista$"),
    ("pendentes", r"^Componentes Curriculares Obrigat[óo]rios Pendentes\s*:?\s*(\d+)?$"),
    ("equivalencias", r"^Equival[êe]ncias\s*:?$"),
    ("observacoes", r"^Observa[çc][õo]es\s*:?$"),
    ("enade", r"^ENADE\s*:?$"),
]
_SECOES = [(n, re.compile(p, re.I)) for n, p in _SECOES]

_RE_LINHA_COMP = re.compile(
    r"^(?P<periodo>\d{4}\.\d)\s+"
    r"(?:(?P<natureza>[A-Z]{2})\s+)?"
    r"(?P<codigo>[A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*)\s+"
    r"(?P<ch>\d{1,4})\s+"
    r"(?:(?P<freq>\d{1,3}(?:[.,]\d+)?)\s*%\s+)?"
    r"(?P<nota>\d{1,2}(?:[.,]\d+)?|--|-)?\s*"
    r"(?P<situacao>[A-Z]{2,6})"
    r"(?P<marc>(?:\s*[*@&#e§])*)\s*$"
)
_RE_DOCENTE = re.compile(r"\s*(?:(?P<titulo>Dr\.|Dra\.|MSc\.|Me\.|Ma\.|Esp\.|Prof\.|Profa\.)\s+)?(?P<nome>[^,(]+?)\s*\((?P<ch>\d+)\s*h\)")
_RE_EMITIDO = re.compile(r"Emitido em:\s*(\d{2}/\d{2}/\d{4})\s*(?:às|as)?\s*(\d{2}:\d{2})?")
_RE_VERIF = re.compile(r"verifica[çc][ãa]o:\s*([0-9a-fA-F]{6,})")
_RE_CH_VAL = re.compile(r"(\d+(?:[.,]\d+)?)\s*h\b")

_ROTULOS_DADOS = [
    ("nome", r"Nome"),
    ("matricula", r"Matr[íi]cula"),
    ("data_nascimento", r"Data de Nascimento"),
    ("local_nascimento", r"Local de Nascimento"),
    ("nacionalidade", r"Nacionalidade"),
    ("documento", r"N[ºo°]\s*do documento com [óo]rg[ãa]o expedidor"),
    ("cpf", r"N[ºo°]\s*do CPF"),
]
_ROTULOS_VINCULO = [
    ("curso", r"Curso"),
    ("status", r"Status"),
    ("enfase", r"[ÊE]nfase"),
    ("curriculo", r"Curr[íi]culo"),
    ("reconhecimento_curso", r"Reconhecimento do Curso"),
    ("ingresso", r"Ingresso"),
    ("perfil_inicial", r"Perfil Inicial"),
    ("forma_ingresso", r"Forma de Ingresso"),
    ("periodo_letivo_atual", r"Per[íi]odo Letivo Atual"),
    ("prazo_conclusao", r"Prazo para Conclus[ãa]o\s*\(Padr[ãa]o\s*/\s*M[áa]ximo\)"),
    ("suspensoes", r"Suspens[õo]es"),
    ("prorrogacoes", r"Prorroga[çc][õo]es"),
    ("data_conclusao", r"Data da Conclus[ãa]o"),
    ("data_colacao_grau", r"Data da Cola[çc][ãa]o de Grau"),
    ("conclusao", r"Conclus[ãa]o"),
    ("tipo_saida", r"Tipo Sa[íi]da"),
    ("trabalho_conclusao_curso", r"Trabalho de Conclus[ãa]o de\s+Curso"),
    ("data_expedicao_diploma", r"Data da Expedi[çc][ãa]o do Diploma"),
]


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", ".")
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(s: str | None) -> int | None:
    v = _num(s)
    return int(v) if v is not None else None


def _data(s: str | None) -> date | None:
    if not s:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _vazio(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip(" :")
    return None if s in ("", "-", "--") else s


def extrair_texto(pdf: bytes) -> list[str]:
    """Texto de cada página do PDF — o mesmo do ``page.extract_text()`` do pdfplumber.

    Caminho rápido: os caracteres (texto + caixa) saem do PDFium (``pypdfium2``, que já
    vem com o pdfplumber) e passam pelo MESMO algoritmo de layout do pdfplumber — ~12x
    mais rápido que deixar o pdfminer interpretar o PDF. Se o PDFium faltar, falhar ou o
    PDF tiver algo que ele não reproduz igual (página/texto girado, glifo sem unicode),
    cai no pdfplumber puro.
    """
    try:
        paginas = _extrair_texto_pdfium(pdf)
    except Exception:
        paginas = None
    return paginas if paginas is not None else _extrair_texto_pdfplumber(pdf)


def _extrair_texto_pdfplumber(pdf: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [(p.extract_text() or "") for p in doc.pages]


# O PDFium não é thread-safe (nem com documentos diferentes) e o ctypes solta o GIL
# durante as chamadas — então uma chamada por vez no processo.
_PDFIUM_LOCK = threading.Lock()


def _extrair_texto_pdfium(pdf: bytes) -> list[str] | None:
    """Texto por página via PDFium + layout do pdfplumber; ``None`` = use o pdfplumber."""
    import ctypes

    import pypdfium2
    import pypdfium2.raw as R
    from pdfplumber.utils.text import chars_to_textmap

    paginas_chars: list[tuple[list[dict], float, float]] = []
    with _PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(pdf)
        try:
            for i in range(len(doc)):
                page = doc[i]
                try:
                    if page.get_rotation():
                        return None
                    largura, altura = page.get_size()
                    tp = page.get_textpage()
                    try:
                        chars = _chars_pdfium(tp, altura, R, ctypes)
                    finally:
                        tp.close()
                finally:
                    page.close()
                if chars is None:
                    return None
                paginas_chars.append((chars, largura, altura))
        finally:
            doc.close()
    # layout fora do lock: é Python puro
    return [
        chars_to_textmap(
            chars, layout_bbox=(0, 0, w, h), layout_width=w, layout_height=h
        ).as_string
        for chars, w, h in paginas_chars
    ]


def _chars_pdfium(tp, altura: float, R, ctypes) -> list[dict] | None:
    """Caracteres da página no formato que o pdfplumber usa (``None`` = não dá igual).

    A caixa "loose" do PDFium (avanço × ascendente/descendente da fonte) é a mesma
    geometria do ``LTChar`` do pdfminer — é ela que deixa o texto idêntico.
    """
    raw = tp.raw
    n = R.FPDFText_CountChars(raw)
    if n <= 0:
        return []
    buf = (ctypes.c_ushort * (n + 1))()
    R.FPDFText_GetText(raw, 0, n, buf)
    texto = bytes(buf)[: 2 * n].decode("utf-16-le", errors="replace")
    if len(texto) != n:  # par substituto: perde o alinhamento índice → caractere
        return None
    caixa = R.FS_RECTF()
    ref_caixa = ctypes.byref(caixa)
    loose_box = R.FPDFText_GetLooseCharBox
    angulo = R.FPDFText_GetCharAngle
    gerado = R.FPDFText_IsGenerated
    chars: list[dict] = []
    for i, c in enumerate(texto):
        if c.isspace():
            if gerado(raw, i):  # espaço/quebra que o PDFium inventou (não está no PDF)
                continue
        elif c in "�￾￿\x00" or angulo(raw, i) != 0:
            return None  # glifo sem unicode ou texto girado
        loose_box(raw, i, ref_caixa)
        top = altura - caixa.top
        chars.append(
            {
                "text": c,
                "x0": caixa.left,
                "x1": caixa.right,
                "top": top,
                "bottom": altura - caixa.bottom,
                "doctop": top,
                "upright": True,
            }
        )
    return chars


def _limpar_paginas(paginas: list[str]) -> tuple[list[str], dict]:
    """Junta as páginas tirando cabeçalho/rodapé repetidos. Devolve (linhas, metadados)."""
    meta: dict = {}
    linhas: list[str] = []
    for i, pag in enumerate(paginas):
        ls = [ln.strip() for ln in pag.split("\n")]
        # cabeçalho: tudo até "Histórico Escolar - Emitido em" (inclusive)
        corte = next((k for k, ln in enumerate(ls) if "Emitido em" in ln and "Hist" in ln), None)
        if corte is not None:
            if i == 0:
                meta["instituicao"] = ls[0] if ls else None
                m = _RE_EMITIDO.search(ls[corte])
                if m:
                    d = _data(m.group(1))
                    hh, mm = (m.group(2) or "00:00").split(":")
                    meta["emitido_em"] = datetime(d.year, d.month, d.day, int(hh), int(mm)) if d else None
            ls = ls[corte + 1 :]
            # páginas 2+ repetem "Nome: ... Matrícula: ..." logo abaixo
            if i > 0 and ls and ls[0].startswith("Nome:") and "Matr" in ls[0]:
                ls = ls[1:]
        texto_pag = "\n".join(ls)
        m = _RE_VERIF.search(texto_pag)
        if m:
            meta["codigo_verificacao"] = m.group(1)
        m = re.search(r"(https?://\S+/documentos)", texto_pag)
        if m:
            meta["url_verificacao"] = m.group(1)
        for ln in ls:
            if not ln:
                continue
            if ln.startswith("Para verificar sua autenticidade") or re.match(r"^P[áa]gina \d+ de \d+$", ln):
                continue
            if re.match(r"^verifica[çc][ãa]o:\s*\w+$", ln):
                continue
            ln = re.sub(r"\s*P[áa]gina \d+ de \d+$", "", ln)
            linhas.append(ln)
    return linhas, meta


def _kv(texto: str, rotulos: list[tuple[str, str]]) -> dict[str, str]:
    """Extrai 'Rótulo: valor' de um bloco onde vários pares podem dividir a mesma linha."""
    padrao = "|".join(f"(?P<{n}>{p})\\s*:" for n, p in rotulos)
    achados = list(re.finditer(padrao, texto))
    out: dict[str, str] = {}
    for k, m in enumerate(achados):
        nome = m.lastgroup
        fim = achados[k + 1].start() if k + 1 < len(achados) else len(texto)
        valor = texto[m.end() : fim]
        out.setdefault(nome, valor.strip())
    return out


def _parse_dados(bloco: list[str]) -> DadosPessoaisHistorico:
    kv = _kv("\n".join(bloco), _ROTULOS_DADOS)
    doc = _vazio(kv.get("documento"))
    rg, orgao = None, None
    if doc:
        m = re.match(r"([^,(]+)[,\s]*\(?([^)]*)\)?", doc)
        rg = _vazio(m.group(1)) if m else doc
        orgao = _vazio(m.group(2)) if m else None
    return DadosPessoaisHistorico(
        nome=_vazio(kv.get("nome")),
        matricula=_vazio(kv.get("matricula")),
        data_nascimento=_data(kv.get("data_nascimento")),
        local_nascimento=_vazio(kv.get("local_nascimento")),
        nacionalidade=_vazio(kv.get("nacionalidade")),
        documento_identidade=rg,
        orgao_expedidor=orgao,
        cpf=_vazio(kv.get("cpf")),
    )


def _parse_vinculo(bloco: list[str]) -> tuple[VinculoHistorico, Indices]:
    texto = "\n".join(bloco)
    # índices: "IAP: 0.5337 CR: 6.6367" (podem vir no meio de outras linhas)
    indices: dict[str, float] = {}
    for m in re.finditer(r"\b([A-Z]{2,6})\s*:\s*(\d+(?:[.,]\d+)?)\b", texto):
        indices[m.group(1)] = float(m.group(2).replace(",", "."))
    texto_sem_ind = re.sub(r"\b([A-Z]{2,6})\s*:\s*(\d+(?:[.,]\d+)?)\b", " ", texto)
    texto_sem_ind = re.sub(r"[ÍI]ndices Acad[êe]micos", " ", texto_sem_ind)
    # "Trabalho de Conclusão de\n-\nCurso:" — o valor fica entre as duas metades do rótulo
    tcc = None
    m = re.search(r"Trabalho de Conclus[ãa]o de\s*\n(.*?)\n\s*Curso:", texto_sem_ind, re.S)
    if m:
        tcc = m.group(1)
        texto_sem_ind = texto_sem_ind[: m.start()] + "Trabalho de Conclusão de Curso: " + tcc + "\n" + texto_sem_ind[m.end() :]
    kv = _kv(texto_sem_ind, _ROTULOS_VINCULO)
    ingresso = kv.get("ingresso") or ""
    mi = re.match(r"\s*(\d{4}\.\d)?\s*-?\s*(\d{2}/\d{2}/\d{4})?", ingresso)
    prazo = kv.get("prazo_conclusao") or ""
    mp = re.findall(r"\d{4}\.\d", prazo)
    susp = kv.get("suspensoes") or ""
    vinc = VinculoHistorico(
        curso=_vazio(kv.get("curso")),
        status=_vazio(kv.get("status")),
        enfase=_vazio(kv.get("enfase")),
        curriculo=_vazio(kv.get("curriculo")),
        reconhecimento_curso=_vazio(kv.get("reconhecimento_curso")),
        ingresso_periodo=mi.group(1) if mi else None,
        ingresso_data=_data(mi.group(2)) if mi and mi.group(2) else None,
        perfil_inicial=_int(kv.get("perfil_inicial")),
        forma_ingresso=_vazio(kv.get("forma_ingresso")),
        periodo_letivo_atual=_int(kv.get("periodo_letivo_atual")),
        prazo_conclusao_padrao=mp[0] if mp else None,
        prazo_conclusao_maximo=mp[1] if len(mp) > 1 else None,
        suspensoes=re.findall(r"\d{4}\.\d", susp),
        prorrogacoes=_vazio(kv.get("prorrogacoes")),
        conclusao=_vazio(kv.get("conclusao")),
        tipo_saida=_vazio(kv.get("tipo_saida")),
        data_conclusao=_vazio(kv.get("data_conclusao")),
        data_colacao_grau=_vazio(kv.get("data_colacao_grau")),
        trabalho_conclusao_curso=_vazio(tcc if tcc is not None else kv.get("trabalho_conclusao_curso")),
        data_expedicao_diploma=_vazio(kv.get("data_expedicao_diploma")),
    )
    return vinc, Indices(cr=indices.pop("CR", None), iap=indices.pop("IAP", None), outros=indices)


def _parse_docentes(linha: str) -> list[Docente]:
    out = []
    for m in _RE_DOCENTE.finditer(linha):
        nome = m.group("nome").strip(" ,")
        if not nome:
            continue
        out.append(Docente(nome=nome, titulo=(m.group("titulo") or None), carga_horaria=int(m.group("ch"))))
    return out


def _e_linha_docente(ln: str) -> bool:
    return bool(re.search(r"\(\d+\s*h\)", ln))


def _parse_componentes(bloco: list[str], legenda: Legenda, sobras: list[str]) -> list[ComponenteCursado]:
    """Cada componente = linha(s) de NOME + linha de DADOS + linha(s) de DOCENTES (opcional).
    A lista de docentes pode quebrar no meio ("Dra. FULANA" / "(45h)"): enquanto o texto
    acumulado não fecha com ')', a linha seguinte é continuação."""
    comps: list[ComponenteCursado] = []
    nome_pendente: list[str] = []
    ultimo: ComponenteCursado | None = None
    docs: str | None = None  # None = não estamos lendo docentes

    def fechar_docentes():
        nonlocal docs
        if ultimo is not None and docs:
            ultimo.docentes.extend(_parse_docentes(docs))
        docs = None

    for ln in bloco:
        if re.match(r"^Semestre\s+Componente", ln):
            continue
        m = _RE_LINHA_COMP.match(ln)
        if m:
            fechar_docentes()
            sit = m.group("situacao")
            nat = m.group("natureza")
            ultimo = ComponenteCursado(
                periodo=m.group("periodo"),
                codigo=m.group("codigo"),
                nome=" ".join(nome_pendente).strip() or m.group("codigo"),
                natureza=nat,
                natureza_descricao=(legenda.naturezas.get(nat) or NATUREZAS_PADRAO.get(nat)) if nat else None,
                carga_horaria=int(m.group("ch")),
                nota=_num(m.group("nota")),
                frequencia=_num(m.group("freq")),
                situacao=sit,
                situacao_descricao=legenda.situacoes.get(sit) or SITUACOES_PADRAO.get(sit),
                aprovado=sit in APROVADO,
                cursando=sit == "MATR",
                marcadores=re.findall(r"[*@&#e§]", m.group("marc") or ""),
            )
            comps.append(ultimo)
            nome_pendente = []
            docs = ""
            continue
        if docs is not None:
            if docs == "" and _e_linha_docente(ln):
                docs = ln
                continue
            if docs and not docs.rstrip().endswith(")"):
                docs += " " + ln
                continue
            fechar_docentes()
        if re.match(r"^[A-ZÀ-Ý0-9]", ln):
            nome_pendente.append(ln)
        else:
            sobras.append(ln)
    fechar_docentes()
    if nome_pendente:
        sobras.extend(nome_pendente)
    return comps


def _parse_legenda(bloco: list[str], legenda: Legenda) -> None:
    for ln in bloco:
        if re.match(r"^SIGLA\s+SIGNIFICADO$", ln, re.I):
            continue
        # várias "SIGLA Descrição" na mesma linha: "OP Optativo EB Equivalente Obrigatório ..."
        partes = re.findall(r"\b([A-Z]{2,6})\s+((?:(?![A-Z]{2,6}\b)\S+\s*)+)", ln)
        for sigla, desc in partes:
            desc = desc.strip()
            alvo = legenda.naturezas if len(sigla) == 2 and sigla in NATUREZAS_PADRAO or (len(sigla) == 2 and sigla not in SITUACOES_PADRAO) else legenda.situacoes
            alvo[sigla] = desc


def _parse_tabela_ch(bloco: list[str]) -> list[CargaHorariaCategoria]:
    if not bloco:
        return []
    cab = None
    linhas: dict[str, list[int | None]] = {}
    for ln in bloco:
        vals = _RE_CH_VAL.findall(ln)
        if not vals:
            if cab is None:
                cab = ln.split()
            continue
        rotulo = ln.split()[0]
        linhas[_sem_acento(rotulo).lower()] = [_int(v) for v in vals]
    cab = cab or []
    out = []
    for k, cat in enumerate(cab):
        out.append(
            CargaHorariaCategoria(
                categoria=cat,
                exigido=(linhas.get("exigido") or [None] * len(cab))[k] if k < len(linhas.get("exigido") or []) else None,
                integralizado=(linhas.get("integralizado") or [])[k] if k < len(linhas.get("integralizado") or []) else None,
                pendente=(linhas.get("pendente") or [])[k] if k < len(linhas.get("pendente") or []) else None,
            )
        )
    return out


def _parse_autonomas(bloco: list[str]) -> list[AtividadeAutonomaResumo]:
    out = []
    for ln in bloco:
        m = re.match(r"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*h?$", ln)
        if m and not re.match(r"^Categoria", ln):
            out.append(AtividadeAutonomaResumo(categoria=m.group(1).strip(), carga_horaria=float(m.group(2).replace(",", "."))))
    return out


def _parse_extensao(bloco: list[str]) -> list[CargaExtensionista]:
    out = []
    for ln in bloco:
        if re.match(r"^Descri[çc][ãa]o\s", ln):
            continue
        m = re.match(r"^(.*?)\s+((?:\d{2}/\d{2}/\d{4})(?:\s*(?:a|à|-)\s*\d{2}/\d{2}/\d{4})?|\d{4}\.\d)?\s*(\d+)\s*h$", ln)
        if m:
            out.append(CargaExtensionista(descricao=m.group(1).strip(), periodo=m.group(2), carga_horaria=int(m.group(3))))
    return out


def _parse_pendentes(bloco: list[str]) -> list[ComponentePendente]:
    out = []
    for ln in bloco:
        if re.match(r"^C[óo]digo\s+Componente", ln):
            continue
        m = re.match(r"^(\S+)\s+(.*?)\s*(Matriculado)?\s+(\d+)\s*h$", ln)
        if m:
            out.append(
                ComponentePendente(
                    codigo=m.group(1), nome=m.group(2).strip(), carga_horaria=int(m.group(4)), matriculado=bool(m.group(3))
                )
            )
    return out


_RE_REF = re.compile(r"([A-Z]{2,}[A-Z0-9]*\d[A-Z0-9]*)\s*-\s*(.*?)\s*\((\d+)\s*h\)")


def _parse_equivalencias(bloco: list[str]) -> list[Equivalencia]:
    # junta linhas de continuação (as que não começam com o verbo)
    itens: list[str] = []
    for ln in bloco:
        if re.match(r"^(Cumpriu|Equivale|Aproveit|Dispens)", ln) or not itens:
            itens.append(ln)
        else:
            itens[-1] += " " + ln
    out = []
    for it in itens:
        m = re.match(r"^(\w+)\s+(.*?)\s+atrav[ée]s de\s+(.*)$", it)
        if not m:
            continue
        refs_a = _RE_REF.findall(m.group(2))
        refs_b = _RE_REF.findall(m.group(3))
        if not refs_a:
            continue
        a = refs_a[0]
        out.append(
            Equivalencia(
                tipo=m.group(1),
                componente=ComponenteRef(codigo=a[0], nome=a[1], carga_horaria=int(a[2])),
                atraves_de=[ComponenteRef(codigo=c, nome=n, carga_horaria=int(h)) for c, n, h in refs_b],
                texto=it,
            )
        )
    return out


# Regras conferidas contra os índices oficiais de um histórico real da UFBA:
#   CR  = Σ(nota × CH) / Σ(CH) dos componentes COM nota, exceto reprovação por falta
#   IAP = CH aprovada / CH de todos os componentes já encerrados (trancados entram; matriculados não)
SEM_CR = {"REPF", "REPMF", "REPNF"}
APROVADO_IAP = {"APR", "APRN"}


def calcular_cr(comps: list[ComponenteCursado]) -> float | None:
    sel = [c for c in comps if c.nota is not None and c.carga_horaria and c.situacao not in SEM_CR | TRANCADO]
    ch = sum(c.carga_horaria for c in sel)
    return round(sum(c.nota * c.carga_horaria for c in sel) / ch, 4) if ch else None


def calcular_iap(comps: list[ComponenteCursado]) -> float | None:
    base = [c for c in comps if c.situacao != "MATR" and c.carga_horaria]
    ch = sum(c.carga_horaria for c in base)
    return round(sum(c.carga_horaria for c in base if c.situacao in APROVADO_IAP) / ch, 4) if ch else None


def _estatisticas(comps: list[ComponenteCursado], indices: Indices | None = None) -> EstatisticasHistorico:
    por: "OrderedDict[str, list[ComponenteCursado]]" = OrderedDict()
    for c in sorted(comps, key=lambda c: c.periodo):
        por.setdefault(c.periodo, []).append(c)
    periodos = []
    acumulado: list[ComponenteCursado] = []
    for p, cs in por.items():
        acumulado += cs
        periodos.append(
            EstatisticaPeriodo(
                periodo=p,
                componentes=len(cs),
                carga_horaria=sum(c.carga_horaria or 0 for c in cs),
                carga_horaria_aprovada=sum(c.carga_horaria or 0 for c in cs if c.situacao in APROVADO),
                aprovados=sum(c.situacao in APROVADO for c in cs),
                reprovados=sum(c.situacao in REPROVADO for c in cs),
                trancados=sum(c.situacao in TRANCADO for c in cs),
                cursando=sum(c.cursando for c in cs),
                cr_periodo=calcular_cr(cs),
                cr_acumulado=calcular_cr(acumulado),
                iap_acumulado=calcular_iap(acumulado),
            )
        )
    apr = sum(c.situacao in APROVADO for c in comps)
    rep = sum(c.situacao in REPROVADO for c in comps)
    cr, iap = calcular_cr(comps), calcular_iap(comps)
    confere = None
    if indices and indices.cr is not None and cr is not None:
        confere = abs(indices.cr - cr) < 0.001 and (indices.iap is None or iap is None or abs(indices.iap - iap) < 0.001)
    return EstatisticasHistorico(
        por_periodo=periodos,
        total_componentes=len(comps),
        total_aprovados=apr,
        total_reprovados=rep,
        total_trancados=sum(c.situacao in TRANCADO for c in comps),
        total_cursando=sum(c.cursando for c in comps),
        carga_horaria_aprovada=sum(c.carga_horaria or 0 for c in comps if c.situacao in APROVADO),
        cr_calculado=cr,
        iap_calculado=iap,
        calculo_confere_com_oficial=confere,
        taxa_aprovacao=round(apr / (apr + rep), 4) if (apr + rep) else None,
    )


def parse_historico_texto(paginas: list[str]) -> Historico:
    linhas, meta = _limpar_paginas(paginas)
    blocos: dict[str, list[str]] = {}
    extra_pendentes: int | None = None
    secao = "preambulo"
    for ln in linhas:
        nova = None
        for nome, rx in _SECOES:
            m = rx.match(ln)
            if m:
                nova = nome
                if nome == "pendentes" and m.groups() and m.group(1):
                    extra_pendentes = int(m.group(1))
                break
        if nova:
            secao = nova
            blocos.setdefault(secao, [])
            continue
        blocos.setdefault(secao, []).append(ln)

    sobras: list[str] = []
    legenda = Legenda()
    _parse_legenda(blocos.get("legenda", []), legenda)
    dados = _parse_dados(blocos.get("dados", []))
    vinculo, indices = _parse_vinculo(blocos.get("vinculo", []))
    comps = _parse_componentes(blocos.get("componentes", []), legenda, sobras)
    obs = []
    for ln in blocos.get("observacoes", []):
        if ln.startswith("-") or not obs:
            obs.append(ln.lstrip("- ").strip())
        else:
            obs[-1] += " " + ln
    return Historico(
        instituicao=meta.get("instituicao"),
        emitido_em=meta.get("emitido_em"),
        codigo_verificacao=meta.get("codigo_verificacao"),
        url_verificacao=meta.get("url_verificacao"),
        dados_pessoais=dados,
        vinculo=vinculo,
        indices=indices,
        componentes=comps,
        atividades_autonomas=_parse_autonomas(blocos.get("autonomas", [])),
        carga_horaria=_parse_tabela_ch(blocos.get("ch", [])),
        carga_horaria_extensionista=_parse_extensao(blocos.get("extensao", [])),
        obrigatorios_pendentes=_parse_pendentes(blocos.get("pendentes", [])),
        total_obrigatorios_pendentes=extra_pendentes,
        equivalencias=_parse_equivalencias(blocos.get("equivalencias", [])),
        observacoes=[o for o in obs if o],
        legenda=legenda,
        estatisticas=_estatisticas(comps, indices),
        linhas_nao_reconhecidas=sobras + blocos.get("preambulo", []) + blocos.get("enade", []),
    )


def parse_historico_pdf(pdf: bytes) -> Historico:
    return parse_historico_texto(extrair_texto(pdf))
