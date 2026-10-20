"""GRAVADOR: grava o SIGAA real, passando a PRÓPRIA API por um proxy local, pra o mock reproduzir depois.

    .venv/bin/python bench/gravar.py tudo --rotulo ufba --reps 2
        1. sobe um proxy gravador (127.0.0.1:8114) → https://sigaa.ufba.br
        2. sobe a API deste worktree (127.0.0.1:8113) com SIGAA_URL=proxy (via bench/_lancador.py)
        3. faz login com a credencial do LastPass (recon/sess.py::_cred, nunca impressa) e chama o
           ROTEIRO de rotas em série, ``--reps`` vezes (cada repetição com um login novo)
        4. guarda tudo CRU (com dados pessoais!) em recon/bench_bruto/<rotulo>/ (gitignored) + os
           tempos e2e de cada rota (calibração) em recon/bench_bruto/<rotulo>/calibracao.json
    Depois: ``bench/anonimizar.py --rotulo ufba`` gera bench/gravacoes/ufba/ (versionável).

    .venv/bin/python bench/gravar.py proxy --porta 8114 --rotulo extra      # só o proxy (pra gravar à mão)

Cuidados com o SIGAA real (docs/PERF_BRIEF.md): 1 sessão por vez, tudo em série, ≥0,35 s entre
requisições (trava GLOBAL no proxy), só rotas GET de leitura. Nada de estresse.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import aiohttp
from aiohttp import web

RAIZ = Path(__file__).resolve().parents[1]
UPSTREAM = "https://sigaa.ufba.br"
INTERVALO_MIN = 0.35  # entre requisições ao SIGAA real (global)

_RE_VS = re.compile(
    r'(?:name|id)="javax\.faces\.ViewState"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*(?:name|id)="javax\.faces\.ViewState"'
)


def viewstates(body: bytes) -> list[str]:
    txt = body.decode("iso-8859-1", "replace")
    return sorted({(m.group(1) or m.group(2)) for m in _RE_VS.finditer(txt)})


class Gravador:
    def __init__(self, saida: Path, porta: int) -> None:
        self.saida = saida
        (saida / "corpos").mkdir(parents=True, exist_ok=True)
        self.base_local = f"http://127.0.0.1:{porta}"
        self.porta = porta
        self.seq = 0
        self._log = open(saida / "trocas.jsonl", "a", encoding="utf-8")
        self._gate = asyncio.Lock()
        self._ultimo = 0.0
        self._http: aiohttp.ClientSession | None = None
        self.marca = ""  # rótulo da etapa do roteiro em andamento (só pra leitura humana)

    async def iniciar(self) -> web.AppRunner:
        self._http = aiohttp.ClientSession(
            cookie_jar=aiohttp.DummyCookieJar(), timeout=aiohttp.ClientTimeout(total=90)
        )
        app = web.Application(client_max_size=50 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.tratar)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", self.porta).start()
        return runner

    async def fechar(self) -> None:
        if self._http:
            await self._http.close()
        self._log.close()

    async def tratar(self, req: web.Request) -> web.StreamResponse:
        corpo_req = await req.read()
        hdr = {}
        for k in ("Cookie", "Content-Type", "User-Agent", "Accept-Language", "Accept", "Referer"):
            if k in req.headers:
                v = req.headers[k]
                if k == "Referer":
                    v = v.replace(self.base_local, UPSTREAM)
                hdr[k] = v
        url = UPSTREAM + req.path_qs
        async with self._gate:  # 1 requisição por vez ao SIGAA real, com intervalo mínimo
            espera = INTERVALO_MIN - (time.monotonic() - self._ultimo)
            if espera > 0:
                await asyncio.sleep(espera)
            t0 = time.monotonic()
            try:
                async with self._http.request(req.method, url, data=corpo_req or None, headers=hdr, allow_redirects=False) as r:
                    corpo = await r.read()
                    status = r.status
                    rh = r.headers
                    set_cookies = rh.getall("Set-Cookie", [])
            finally:
                self._ultimo = time.monotonic()
            dt = time.monotonic() - t0
        self.seq += 1
        seq = self.seq
        ctype = rh.get("Content-Type", "")
        loc = rh.get("Location")
        cd = rh.get("Content-Disposition")
        sha = hashlib.sha256(corpo).hexdigest()[:20]
        ext = ".pdf" if corpo[:4] == b"%PDF" else (".html" if "html" in ctype or not ctype else ".bin")
        (self.saida / "corpos" / f"{sha}{ext}").write_bytes(corpo)
        cookie = req.headers.get("Cookie", "")
        m = re.search(r"JSESSIONID=([^;]+)", cookie)
        params = (
            parse_qsl(corpo_req.decode("latin-1"), keep_blank_values=True)
            if corpo_req and "x-www-form-urlencoded" in req.headers.get("Content-Type", "")
            else []
        )
        reg = {
            "seq": seq,
            "t": time.time(),
            "marca": self.marca,
            "jsessionid": hashlib.sha256(m.group(1).encode()).hexdigest()[:12] if m else None,
            "metodo": req.method,
            "caminho": urlsplit(req.path_qs).path,
            "query": parse_qsl(urlsplit(req.path_qs).query, keep_blank_values=True),
            "params": params,
            "vs_enviado": dict(params).get("javax.faces.ViewState"),
            "status": status,
            "content_type": ctype,
            "location": loc,
            "content_disposition": cd,
            "seta_cookie": [c.split("=", 1)[0] for c in set_cookies],
            "corpo": f"{sha}{ext}",
            "tamanho": len(corpo),
            "vs_emitidos": viewstates(corpo) if ext == ".html" else [],
            "latencia_ms": round(dt * 1000, 1),
        }
        self._log.write(json.dumps(reg, ensure_ascii=False) + "\n")
        self._log.flush()

        # resposta pro cliente local: reescreve o que aponta pro SIGAA real
        out_h = {}
        if ctype:
            out_h["Content-Type"] = ctype
        if cd:
            out_h["Content-Disposition"] = cd
        if loc:
            out_h["Location"] = loc.replace(UPSTREAM, self.base_local).replace("http://sigaa.ufba.br", self.base_local)
        resp = web.Response(status=status, headers=out_h)
        for c in set_cookies:  # sem Secure/Domain pra o cookie valer em http://127.0.0.1
            c = re.sub(r";\s*Secure", "", c, flags=re.I)
            c = re.sub(r";\s*Domain=[^;]*", "", c, flags=re.I)
            resp.headers.add("Set-Cookie", c)
        if ext == ".html":
            corpo = corpo.replace(UPSTREAM.encode(), self.base_local.encode())
        resp.body = corpo
        return resp


# ----------------------------------------------------------------------------- roteiro
CURSO_SI, ESTRUTURA_SI, MATA37, DCC = 1876885, 2421505, 44697, 1114

ROTEIRO_LOGADO = [
    "/v1/me", "/v1/portal", "/v1/turmas", "/v1/grade-horaria", "/v1/atividades", "/v1/atualizacoes",
    "/v1/me/dados-pessoais", "/v1/me/perfil", "/v1/modulos",
    "/v1/turmas-virtuais",
    "/v1/turmas/{turma}", "/v1/turmas/{turma}/notas", "/v1/turmas/{turma}/frequencia",
    "/v1/turmas/{turma}/noticias", "/v1/turmas/{turma}/aulas", "/v1/turmas/{turma}/avaliacoes",
    "/v1/turmas/{turma}/tarefas", "/v1/turmas/{turma}/plano-de-curso",
    "/v1/turmas/{turma2}", "/v1/turmas/{turma2}/notas",
    "/v1/notas", "/v1/frequencia", "/v1/tarefas", "/v1/avaliacoes",
    "/v1/historico", "/v1/historico/pdf", "/v1/indices", "/v1/integralizacao", "/v1/pendencias",
    "/v1/matricula", "/v1/matricula/processamento", "/v1/documentos/comprovante-inscricao",
    "/v1/documentos/declaracao-vinculo",
    "/v1/grade-curricular", "/v1/planejamento/matricula", "/v1/carga-horaria",
    "/v1/calendario", "/v1/calendario/lista",
    f"/v1/consultas/componentes/{MATA37}", f"/v1/consultas/estruturas?curso={CURSO_SI}",
    f"/v1/consultas/estruturas/{ESTRUTURA_SI}", "/v1/consultas/turmas?componente=MATA37",
    "/v1/consultas/turmas/filtros", "/v1/consultas/componentes?codigo=MATA37",
]
ROTEIRO_PUBLICO = [
    f"/v1/publico/cursos/{CURSO_SI}", f"/v1/publico/cursos/{CURSO_SI}/estruturas",
    f"/v1/publico/cursos/{CURSO_SI}/estruturas/{ESTRUTURA_SI}", f"/v1/publico/componentes/{MATA37}",
    "/v1/publico/componentes/codigo/MATA37", "/v1/publico/componentes?codigo=MATA37",
    f"/v1/publico/turmas?ano=2026&periodo=2&unidade={DCC}", "/v1/publico/cursos?nivel=G&nome=computa%C3%A7%C3%A3o",
    "/v1/publico/unidades", f"/v1/publico/departamentos/{DCC}/componentes",
]


async def roteiro(api: str, grav: Gravador | None, reps: int, so: str | None) -> dict:
    sys.path.insert(0, str(RAIZ / "recon"))
    from sess import _cred  # noqa: E402 — lê do LastPass, nunca imprime

    usuario, senha = _cred()
    resultado: dict = {"api": api, "reps": [], "logins_s": []}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as h:
        for rep in range(reps):
            if grav:
                grav.marca = f"rep{rep}:login"
            t0 = time.monotonic()
            async with h.post(api + "/v1/auth/login", json={"usuario": usuario, "senha": senha, "lembrar": False}) as r:
                corpo = await r.json()
                if r.status != 200:
                    raise SystemExit(f"login falhou: HTTP {r.status} {corpo.get('erro', {}).get('codigo')}")
            resultado["logins_s"].append(round(time.monotonic() - t0, 3))
            print(f"[rep {rep}] login {resultado['logins_s'][-1]:.2f}s", flush=True)
            tok = {"Authorization": "Bearer " + corpo["token"]}
            ids: dict[str, str] = {}
            tempos = []
            for caminho in ROTEIRO_LOGADO + ROTEIRO_PUBLICO:
                if so and so not in caminho:
                    continue
                try:
                    alvo = caminho.format(**ids)
                except KeyError:
                    print(f"  pulei {caminho} (sem id)")
                    continue
                if grav:
                    grav.marca = f"rep{rep}:{alvo}"
                t = time.monotonic()
                async with h.get(api + alvo, headers=tok) as r:
                    dados = await r.read()
                    st = r.status
                dt = time.monotonic() - t
                tempos.append({"rota": caminho, "url": alvo, "status": st, "s": round(dt, 3), "bytes": len(dados)})
                print(f"  {st} {dt:6.2f}s {alvo}", flush=True)
                if caminho == "/v1/turmas-virtuais" and st == 200:
                    tv = json.loads(dados)
                    atuais = [x for x in tv if x.get("atual") and x.get("turma_id")] or [x for x in tv if x.get("turma_id")]
                    if atuais:
                        ids["turma"] = str(atuais[0]["turma_id"])
                        ids["turma2"] = str(atuais[min(1, len(atuais) - 1)]["turma_id"])
            if grav:
                grav.marca = f"rep{rep}:logout"
            async with h.delete(api + "/v1/auth/sessao", headers=tok) as r:
                await r.read()
            resultado["reps"].append(tempos)
        if grav:  # como o SIGAA responde a uma sessão que não existe (1 requisição só)
            grav.marca = "sessao_invalida"
            async with h.get(grav.base_local + "/sigaa/verPortalDiscente.do", headers={"Cookie": "JSESSIONID=00000000000000000000000000000000"}, allow_redirects=True) as r:
                await r.read()
    return resultado


def subir_api(porta: int, sigaa: str) -> subprocess.Popen:
    log = open(RAIZ / "recon" / f"api_{porta}.log", "w")
    p = subprocess.Popen(
        [str(RAIZ / ".venv/bin/python"), str(RAIZ / "bench/_lancador.py"), "--worktree", str(RAIZ), "--porta", str(porta), "--sigaa", sigaa],
        stdout=log, stderr=subprocess.STDOUT,
    )
    return p


async def esperar(url: str, tentativas: int = 60) -> None:
    async with aiohttp.ClientSession() as h:
        for _ in range(tentativas):
            try:
                async with h.get(url + "/", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        return
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.5)
    raise SystemExit(f"{url} não subiu")


async def cmd_tudo(a) -> None:
    saida = RAIZ / "recon" / "bench_bruto" / a.rotulo
    grav = Gravador(saida, a.porta_proxy)
    runner = await grav.iniciar()
    api = subir_api(a.porta_api, grav.base_local)
    try:
        await esperar(f"http://127.0.0.1:{a.porta_api}")
        res = await roteiro(f"http://127.0.0.1:{a.porta_api}", grav, a.reps, a.so)
        arq = saida / "calibracao.json"
        antigos = json.loads(arq.read_text()) if arq.exists() else []
        antigos.append({"quando": time.strftime("%Y-%m-%d %H:%M:%S"), **res})
        arq.write_text(json.dumps(antigos, ensure_ascii=False, indent=1))
        print(f"gravado em {saida} ({grav.seq} trocas)")
    finally:
        api.send_signal(signal.SIGINT)
        try:
            api.wait(10)
        except subprocess.TimeoutExpired:
            api.kill()
        await runner.cleanup()
        await grav.fechar()


async def cmd_proxy(a) -> None:
    grav = Gravador(RAIZ / "recon" / "bench_bruto" / a.rotulo, a.porta)
    runner = await grav.iniciar()
    print(f"proxy gravador em {grav.base_local} → {UPSTREAM} (Ctrl+C pra parar)", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await grav.fechar()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tudo")
    t.add_argument("--rotulo", default="ufba")
    t.add_argument("--reps", type=int, default=2)
    t.add_argument("--porta-proxy", type=int, default=8114)
    t.add_argument("--porta-api", type=int, default=8113)
    t.add_argument("--so", help="só as rotas que contêm este trecho")
    p = sub.add_parser("proxy")
    p.add_argument("--rotulo", default="extra")
    p.add_argument("--porta", type=int, default=8114)
    a = ap.parse_args()
    asyncio.run(cmd_tudo(a) if a.cmd == "tudo" else cmd_proxy(a))


if __name__ == "__main__":
    main()
