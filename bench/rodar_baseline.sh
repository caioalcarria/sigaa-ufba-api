#!/usr/bin/env bash
# Rodada PADRÃO da bancada (a mesma do baseline) — pra cada frente ter o "depois" comparável.
#   bench/rodar_baseline.sh <worktree> <rotulo> [porta_mock] [porta_api] [-- opções extras do bench.py]
#   ex.: bench/rodar_baseline.sh ~/PROJECTS/UFBA/sigaa-api-perf-cache cache 8131 8132
# Sobe um mock (fator 1; MOCK_FATOR=0 → sem latência, mede só a CPU da API) e a API do worktree, roda o bench completo e grava
# bench/resultados/<rotulo>.md e .json NESTA pasta da bancada (copie pro seu worktree se quiser versionar).
set -euo pipefail
BANC="$(cd "$(dirname "$0")/.." && pwd)"
WT="$(cd "${1:?worktree}" && pwd)"; ROT="${2:?rotulo}"; PM="${3:-8117}"; PA="${4:-8118}"
shift $(( $# >= 4 ? 4 : $# )); [ "${1:-}" = "--" ] && shift
PY="$BANC/.venv/bin/python"
mkdir -p "$BANC/bench/.pids" "$BANC/bench/resultados"
"$PY" "$BANC/bench/mock_sigaa.py" --porta "$PM" --seed 1 --fator "${MOCK_FATOR:-1}" > "$BANC/bench/.pids/mock_$PM.log" 2>&1 &
echo $! > "$BANC/bench/.pids/mock_$PM.pid"
trap 'kill $(cat "$BANC/bench/.pids/mock_$PM.pid") 2>/dev/null; rm -f "$BANC/bench/.pids/mock_$PM.pid"; "$BANC/bench/api_instancia.sh" parar "$PA" >/dev/null 2>&1 || true' EXIT
for i in $(seq 50); do curl -sf "127.0.0.1:$PM/__mock/config" >/dev/null && break; sleep 0.2; done
"$BANC/bench/api_instancia.sh" "$WT" "$PA" "http://127.0.0.1:$PM"
"$PY" "$BANC/bench/bench.py" --api "http://127.0.0.1:$PA" --mock "http://127.0.0.1:$PM" --worktree "$WT" --rotulo "$ROT" \
  --amostras-frias 3 --quentes 5 --conexoes 1,10,50,200 --alunos auto,1 --requisicoes 0 --duracao 30 --calibrar-cliente \
  --saida-md "$BANC/bench/resultados/$ROT.md" --saida-json "$BANC/bench/resultados/$ROT.json" "$@"
"$PY" "$BANC/bench/_enxugar_json.py" "$BANC/bench/resultados/$ROT.json"
