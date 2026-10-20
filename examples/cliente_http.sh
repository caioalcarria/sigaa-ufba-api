#!/usr/bin/env bash
# Consumindo o SERVIDOR (uvicorn api.main:app) por HTTP.
API=${API:-http://localhost:8000}
read -rp "Usuário SIGAA: " U; read -rsp "Senha: " S; echo
TOKEN=$(curl -s "$API/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"usuario\":\"$U\",\"senha\":\"$S\",\"lembrar\":true}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
H="Authorization: Bearer $TOKEN"
curl -s -H "$H" "$API/v1/indices" | python3 -m json.tool | head -30
curl -s -H "$H" "$API/v1/pendencias" | python3 -m json.tool | head -30
curl -s -H "$H" -o historico.pdf "$API/v1/historico/pdf" && echo "historico.pdf salvo"
curl -s -X DELETE -H "$H" "$API/v1/auth/sessao"   # logout
