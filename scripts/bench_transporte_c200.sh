#!/usr/bin/env bash
# Matriz C=200: transporte compartilhado × um por sessão, no perf/turbo + opção (cache desligado).
set -u
D=${D:-/tmp/bench-transporte}   # pasta de trabalho (cópia do perf/turbo em $D/turbo_x)
W=$D/turbo_x; PY=$HOME/PROJECTS/UFBA/sigaa-api-perf-sessoes/.venv/bin/python; B=$W/bench; O=$D/c200
cd $W
$PY $B/mock_sigaa.py --porta 8120 --views 10 > $O/mock8120.log 2>&1 & echo $! > $O/mock8120.pid
$PY $B/mock_sigaa.py --porta 8125 --views 10 --fator 0 > $O/mock8125.log 2>&1 & echo $! > $O/mock8125.pid
sleep 2
sobe() { env SIGAA_API_CACHE=false SIGAA_API_MAX_CONCORRENCIA_SIGAA=$3 SIGAA_API_TRANSPORTE_COMPARTILHADO=$4 $B/api_instancia.sh $W $1 http://127.0.0.1:$2 | tail -1; }
sobe 8121 8120 256 false; sobe 8122 8120 256 true; sobe 8123 8125 256 false; sobe 8124 8125 256 true
sobe 8126 8120 64 false;  sobe 8127 8120 64 true
u=100000
mede() {  # porta mock rotulo extra...
  local P=$1 M=$2 R=$3; shift 3; u=$((u+1000))
  $PY $B/bench.py --api http://127.0.0.1:$P --mock http://127.0.0.1:$M --worktree $W --rotulo $R --sem-frias \
     --rotas-carga /v1/turmas,/v1/notas --conexoes 200 --alunos auto --alunos-max 200 --requisicoes 400 --duracao 120 \
     --timeout 120 --login-paralelo 50 --usuario-inicio $u --saida-md $O/$R.md --saida-json $O/$R.json "$@" > /dev/null 2> $O/$R.err
  echo "== $R"; grep '^| `' $O/$R.md
}
for A in frio quente; do
  X=(); [ $A = quente ] && X=(--aquecer)
  mede 8121 8120 f1-$A-porSessao "${X[@]}"; mede 8122 8120 f1-$A-compart "${X[@]}"
  mede 8123 8125 f0-$A-porSessao "${X[@]}"; mede 8124 8125 f0-$A-compart "${X[@]}"
done
mede 8126 8120 f1-frio-teto64-porSessao; mede 8127 8120 f1-frio-teto64-compart
for P in 8121 8122 8123 8124 8126 8127; do $B/api_instancia.sh parar $P | tail -1; done
for M in 8120 8125; do kill $(cat $O/mock$M.pid) 2>/dev/null; done
echo FIM
