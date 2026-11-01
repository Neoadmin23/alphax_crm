#!/usr/bin/env bash
# AlphaX GPU server kit - end-to-end check from any machine.
#   ./check.sh                      # reads AI_DOMAIN / AI_API_KEY from .env
#   ./check.sh https://ai.example.sa KEY
# Expects: 401 without the key, 404 for model management, the model list with the key,
# and one short chat answer.
set -u
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
BASE="${1:-https://${AI_DOMAIN:-}}"
KEY="${2:-${AI_API_KEY:-}}"
BASE="${BASE%/}"
pass=0; fail=0
ok()  { echo "  PASS  $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@"; }

[ -z "$KEY" ] && { echo "No API key (set AI_API_KEY in .env or pass it as 2nd argument)"; exit 2; }
echo "Checking $BASE"

c=$(code "$BASE/api/tags");                                   [ "$c" = 401 ] && ok "no key -> 401" || bad "no key -> expected 401, got $c"
c=$(code -H "Authorization: Bearer wrong-$KEY" "$BASE/v1/models"); [ "$c" = 401 ] && ok "wrong key -> 401" || bad "wrong key -> expected 401, got $c"
c=$(code -X POST -H "Authorization: Bearer $KEY" -d '{"model":"x"}' "$BASE/api/pull")
[ "$c" = 404 ] && ok "model management blocked (/api/pull -> 404)" || bad "/api/pull should be 404, got $c"
c=$(code -X DELETE -H "Authorization: Bearer $KEY" "$BASE/api/delete"); [ "$c" = 404 ] && ok "/api/delete blocked" || bad "/api/delete should be 404, got $c"

models=""
for path in /api/tags /v1/models; do
  body=$(curl -s --max-time 30 -H "Authorization: Bearer $KEY" "$BASE$path")
  found=$(echo "$body" | grep -o '"\(name\|id\)" *: *"[^"]*"' | sed 's/.*: *"\([^"]*\)"/\1/' | sort -u | tr '\n' ' ')
  if [ -n "$found" ]; then
    models="$found"; ok "models with key ($path): $models"; MODELS_PATH=$path; break
  fi
done
[ -z "$models" ] && bad "no model list with the key (is the model pulled? is UPSTREAM right?)"

first=$(echo "$models" | awk '{print $1}')
if [ -n "$first" ]; then
  if [ "${MODELS_PATH:-}" = /api/tags ]; then
    ans=$(curl -s --max-time 300 -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
      -d "{\"model\":\"$first\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}]}" "$BASE/api/chat")
  else
    ans=$(curl -s --max-time 300 -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
      -d "{\"model\":\"$first\",\"max_tokens\":20,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}]}" "$BASE/v1/chat/completions")
  fi
  echo "$ans" | grep -q '"content"' && ok "chat answer from $first" || bad "chat failed: ${ans:0:200}"
fi
echo "Result: $pass passed, $fail failed"
[ "$fail" = 0 ]
