"""Tira as amostras cruas (``ms_todas``) do JSON do bench → <rotulo>.json fica pequeno pra versionar;
as amostras vão pra <rotulo>.amostras.json.gz (pra quem quiser histograma)."""
import gzip, json, sys
arq = sys.argv[1]
d = json.load(open(arq))
amostras = {}
for i, c in enumerate(d.get("carga", [])):
    if "ms_todas" in c:
        amostras[f"{i}:{c.get('rota')}:C{c.get('conexoes', c.get('C'))}:N{c.get('alunos', c.get('N'))}"] = [round(x, 1) for x in c.pop("ms_todas")]
json.dump(d, open(arq, "w"), ensure_ascii=False, indent=1)
with gzip.open(arq.replace(".json", ".amostras.json.gz"), "wt") as f:
    json.dump(amostras, f)
