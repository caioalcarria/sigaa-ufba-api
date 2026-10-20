#!/usr/bin/env bash
# Sobe/para uma instância da API (uvicorn) de um worktree QUALQUER apontada pro SIGAA SIMULADO.
#
#   bench/api_instancia.sh <worktree> <porta> <sigaa_url>   # sobe em background e espera /v1/status
#   bench/api_instancia.sh parar <porta>                     # mata SÓ o PID que este script gravou
#   bench/api_instancia.sh status <porta>
#
# Ex.: bench/api_instancia.sh ~/PROJECTS/UFBA/sigaa-api-perf-cache 8112 http://127.0.0.1:8111
#
# Usa a .venv DO WORKTREE ALVO e o lançador bench/_lancador.py (ao lado deste script), que troca o
# BASE_URL padrão do SigaaClient antes de importar a API, bloqueia https (buraco negro) e recusa a
# porta 8000 / a pasta de produção. PID e log ficam em bench/.pids/api_<porta>.{pid,log} (gitignored).
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS="$AQUI/.pids"
LANCADOR="$AQUI/_lancador.py"
mkdir -p "$PIDS"

uso() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
porta_ok() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( $1 != 8000 && $1 >= 8100 && $1 <= 8199 )) || { echo "porta '$1' recusada: use 8100–8199 (a 8000 é a produção)" >&2; exit 2; }
}
vivo() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }
# confere que o PID ainda é o NOSSO uvicorn daquela porta (contra reuso de PID)
eh_nosso() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -q -- "_lancador.py.*--porta $2"; }

parar() {
  local porta=$1 arq="$PIDS/api_$1.pid" pid
  porta_ok "$porta"
  [[ -f "$arq" ]] || { echo "sem PID gravado pra porta $porta (nada a parar)"; return 0; }
  pid=$(cat "$arq")
  if vivo "$pid" && eh_nosso "$pid" "$porta"; then
    kill -TERM "$pid"
    for _ in $(seq 50); do vivo "$pid" || break; sleep 0.2; done
    vivo "$pid" && { echo "PID $pid não saiu com TERM — mandando KILL"; kill -KILL "$pid"; }
    echo "API da porta $porta parada (PID $pid)"
  else
    echo "PID $pid não está vivo (ou não é o nosso uvicorn da porta $porta) — só limpando o arquivo"
  fi
  rm -f "$arq"
}

status() {
  local porta=$1 arq="$PIDS/api_$1.pid"
  porta_ok "$porta"
  if [[ -f "$arq" ]] && vivo "$(cat "$arq")"; then echo "rodando: PID $(cat "$arq")"; else echo "parada"; fi
  curl -s --noproxy '*' -m 15 "http://127.0.0.1:$porta/v1/status" && echo || true
}

subir() {
  local wt porta=$2 sigaa=${3%/} arq log pid
  wt="$(cd "$1" 2>/dev/null && pwd)" || { echo "worktree '$1' não existe" >&2; exit 2; }
  porta_ok "$porta"
  [[ "$(realpath "$wt")" == "$(realpath "$HOME/PROJECTS/UFBA/sigaa-api" 2>/dev/null || echo -)" ]] && { echo "esse é o worktree de PRODUÇÃO — não" >&2; exit 2; }
  [[ "$sigaa" =~ ^http://(127\.0\.0\.1|localhost):[0-9]+$ ]] || { echo "sigaa_url '$sigaa' recusada: só o SIGAA simulado local (http://127.0.0.1:81xx)" >&2; exit 2; }
  [[ -x "$wt/.venv/bin/python" ]] || { echo "$wt/.venv/bin/python não existe — crie a .venv do worktree" >&2; exit 2; }
  [[ -f "$LANCADOR" ]] || { echo "lançador $LANCADOR não encontrado" >&2; exit 2; }
  arq="$PIDS/api_$porta.pid"; log="$PIDS/api_$porta.log"
  if [[ -f "$arq" ]] && vivo "$(cat "$arq")"; then echo "já tem uma API nossa na porta $porta (PID $(cat "$arq")) — rode 'parar $porta' antes" >&2; exit 1; fi
  if ss -ltnH "sport = :$porta" 2>/dev/null | grep -q .; then echo "porta $porta já está ocupada por outro processo" >&2; exit 1; fi

  # setsid: a API não morre junto com o shell que a subiu; $! é o PID do próprio python
  setsid "$wt/.venv/bin/python" "$LANCADOR" --worktree "$wt" --porta "$porta" --sigaa "$sigaa" ${API_LOG_LEVEL:+--log-level "$API_LOG_LEVEL"} \
    > "$log" 2>&1 < /dev/null &
  pid=$!
  sleep 0.3
  if ! vivo "$pid"; then  # setsid fez fork (shell com controle de jobs): acha o filho pelo comando
    pid=$(pgrep -f -- "_lancador.py --worktree $wt --porta $porta --sigaa" | head -n1 || true)
  fi
  echo "$pid" > "$arq"
  for _ in $(seq 150); do
    if curl -sf --noproxy '*' -m 15 "http://127.0.0.1:$porta/v1/status" > /dev/null; then
      # se o setsid fez fork (shell com controle de jobs), o PID certo é o de quem escuta a porta
      local real
      real=$(ss -ltnpH "sport = :$porta" 2>/dev/null | grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2)
      if [[ -n "$real" && "$real" != "$pid" ]] && eh_nosso "$real" "$porta"; then pid=$real; echo "$pid" > "$arq"; fi
      echo "API no ar: http://127.0.0.1:$porta (PID $pid, worktree $wt, SIGAA $sigaa, log $log)"
      return 0
    fi
    if ! vivo "$pid" && ! ss -ltnH "sport = :$porta" 2>/dev/null | grep -q .; then
      echo "a API morreu ao subir — log ($log):" >&2; tail -n 30 "$log" >&2; rm -f "$arq"; exit 1
    fi
    sleep 0.2
  done
  echo "a API não respondeu /v1/status em 30 s — parando (log: $log)" >&2
  parar "$porta"; exit 1
}

case "${1:-}" in
  parar)  [[ $# -eq 2 ]] || uso; parar "$2" ;;
  status) [[ $# -eq 2 ]] || uso; status "$2" ;;
  -h|--help|"") uso ;;
  *)      [[ $# -eq 3 ]] || uso; subir "$1" "$2" "$3" ;;
esac
