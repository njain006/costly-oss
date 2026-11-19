#!/usr/bin/env sh
# First-run setup: create backend/.env with fresh secrets.
# Safe to re-run: never overwrites an existing JWT_SECRET or ENCRYPTION_KEY.
set -eu
cd "$(dirname "$0")/.."
ENV=backend/.env
[ -f "$ENV" ] || cp backend/.env.example "$ENV"
chmod 600 "$ENV"

rand() { python3 -c 'import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'; }

set_if_blank() {  # key value
  if grep -qx "$1=" "$ENV" || grep -qx "$1=change-this-secret-key" "$ENV"; then
    tmp=$(mktemp); sed "s|^$1=.*|$1=$2|" "$ENV" > "$tmp" && mv "$tmp" "$ENV"; chmod 600 "$ENV"
    echo "  generated $1"
  elif ! grep -q "^$1=" "$ENV"; then
    echo "$1=$2" >> "$ENV"; echo "  generated $1"
  else
    echo "  kept existing $1"
  fi
}

echo "Setting up $ENV"
set_if_blank JWT_SECRET "$(rand)"
# A Fernet key is 32 random bytes, urlsafe base64.
set_if_blank ENCRYPTION_KEY "$(rand)"
echo "Done. Keep $ENV private: ENCRYPTION_KEY decrypts stored platform credentials,"
echo "and losing it means reconnecting every platform."
