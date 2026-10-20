# ambiente da API apontando pro SIGAA simulado (nunca o real) — source scripts/cpu/env.sh
export SIGAA_URL=${SIGAA_URL:-http://127.0.0.1:8150}
export SIGAA_API_MAX_LOGINS_POR_IP=1000000 SIGAA_API_MAX_SESSOES=100000 SIGAA_API_KEEPALIVE=false
