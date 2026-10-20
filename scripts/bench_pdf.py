"""Benchmark do parse do Histórico em PDF: motor velho (pdfplumber puro) × novo (PDFium + layout do pdfplumber).

    .venv/bin/python scripts/bench_pdf.py caminho/do/historico.pdf [--n 21] [--paralelo 8]

Imprime só tempos e se a saída bate (texto e modelo) — nunca o conteúdo do PDF.
``--paralelo K`` mede também o throughput (PDFs/s) com K PDFs de uma vez em
``asyncio.to_thread`` e em ``ProcessPoolExecutor`` (K workers, pool já aquecido).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigaa.parsers import historico_pdf as H  # noqa: E402


def parse_velho(pdf: bytes):
    return H.parse_historico_texto(H._extrair_texto_pdfplumber(pdf))


def parse_novo(pdf: bytes):
    return H.parse_historico_pdf(pdf)


MOTORES = {"velho (pdfplumber)": parse_velho, "novo (pdfium)": parse_novo}


def mediana_ms(f, arg, n: int) -> float:
    f(arg)  # aquece (imports, caches)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        f(arg)
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def vazao_threads(f, pdf: bytes, k: int, rodadas: int) -> float:
    async def lote():
        await asyncio.gather(*(asyncio.to_thread(f, pdf) for _ in range(k)))

    async def main():
        await lote()  # aquece o pool de threads
        t = time.perf_counter()
        for _ in range(rodadas):
            await lote()
        return time.perf_counter() - t

    return k * rodadas / asyncio.run(main())


def vazao_processos(f, pdf: bytes, k: int, rodadas: int) -> float:
    with ProcessPoolExecutor(max_workers=k) as pool:
        list(pool.map(f, [pdf] * k))  # sobe e aquece os workers (fora da medida)
        t = time.perf_counter()
        for _ in range(rodadas):
            list(pool.map(f, [pdf] * k))
        return k * rodadas / (time.perf_counter() - t)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--n", type=int, default=21, help="execuções por medida (mediana)")
    ap.add_argument("--paralelo", type=int, default=0, metavar="K", help="mede throughput com K PDFs simultâneos")
    ap.add_argument("--rodadas", type=int, default=5, help="lotes de K por medida de throughput")
    a = ap.parse_args()
    pdf = a.pdf.read_bytes()

    texto_velho = H._extrair_texto_pdfplumber(pdf)
    texto_novo = H.extrair_texto(pdf)
    rapido = H._extrair_texto_pdfium(pdf) is not None
    modelo_igual = parse_velho(pdf).model_dump(mode="json") == parse_novo(pdf).model_dump(mode="json")
    print(f"PDF: {len(pdf) / 1024:.0f} KB, {len(texto_velho)} página(s); caminho PDFium ativo: {'sim' if rapido else 'NÃO (fallback)'}")
    print(f"texto idêntico: {'sim' if texto_velho == texto_novo else 'NÃO'} | modelo idêntico: {'sim' if modelo_igual else 'NÃO'}")

    ex_velho = mediana_ms(H._extrair_texto_pdfplumber, pdf, a.n)
    ex_novo = mediana_ms(H.extrair_texto, pdf, a.n)
    pa_velho = mediana_ms(parse_velho, pdf, a.n)
    pa_novo = mediana_ms(parse_novo, pdf, a.n)
    print(f"\nmediana de {a.n} execuções (ms)   antes     depois   ganho")
    print(f"extrair_texto                  {ex_velho:8.1f} {ex_novo:8.1f}  {ex_velho / ex_novo:5.1f}x")
    print(f"parse_historico_pdf            {pa_velho:8.1f} {pa_novo:8.1f}  {pa_velho / pa_novo:5.1f}x")

    if a.paralelo:
        k = a.paralelo
        print(f"\nthroughput com {k} PDFs simultâneos (PDFs/s; {os.cpu_count()} CPUs)")
        print(f"{'motor':20} {'sequencial':>11} {'to_thread':>10} {'processpool':>12}")
        for nome, f in MOTORES.items():
            seq = 1000 / mediana_ms(f, pdf, max(5, a.n // 2))
            thr = vazao_threads(f, pdf, k, a.rodadas)
            prc = vazao_processos(f, pdf, k, a.rodadas)
            print(f"{nome:20} {seq:11.1f} {thr:10.1f} {prc:12.1f}")


if __name__ == "__main__":
    main()
