"""Залить sync_olcrtc_wb_auth_token.py на VPS, выполнить, скопировать YAML, restart WB units."""
from __future__ import annotations

import io

from _deploy_common import CONTAINER, REMOTE, connect, run, upload_file

client = connect()
sftp = client.open_sftp()
upload_file(sftp, client, "scripts/sync_olcrtc_wb_auth_token.py")
sftp.close()

# Если в БД пусто — подмешать host storage_state в аккаунты через отдельный bootstrap ниже.
remote = f"""#!/bin/bash
set -e
cd {REMOTE}
docker cp scripts/sync_olcrtc_wb_auth_token.py {CONTAINER}:/app/scripts/sync_olcrtc_wb_auth_token.py
mkdir -p update/olcrtc/agent_states
if [ -f /opt/silent-vpn/olcrtc/agent_states/wbstream_state.json ]; then
  cp /opt/silent-vpn/olcrtc/agent_states/wbstream_state.json update/olcrtc/agent_states/wbstream_state.json
  docker exec {CONTAINER} mkdir -p /app/update/olcrtc/agent_states
  docker cp update/olcrtc/agent_states/wbstream_state.json {CONTAINER}:/app/update/olcrtc/agent_states/wbstream_state.json
fi
# bootstrap accounts из файла, если JWT ещё нет в settings
docker exec -w /app {CONTAINER} python - <<'PY'
import asyncio, json
from pathlib import Path
from app.database import AsyncSessionLocal
from app.services.olcrtc_room_accounts import (
    OlcrtcRoomAccounts,
    ProviderAccount,
    extract_wb_access_token,
    load_room_accounts,
    save_room_accounts,
    sync_wbstream_auth_token_to_settings,
)

async def boot():
    state_path = Path("/app/update/olcrtc/agent_states/wbstream_state.json")
    async with AsyncSessionLocal() as db:
        tok = await sync_wbstream_auth_token_to_settings(db)
        if tok:
            print("already_or_synced_from_db len=%d" % len(tok))
            return
        if not state_path.is_file():
            print("no_state_file")
            return
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not extract_wb_access_token(state):
            print("state_has_no_accessToken")
            return
        acc = await load_room_accounts(db)
        if not acc.wbstream:
            acc.wbstream = [ProviderAccount(label="host-wb", storage_state=state)]
        else:
            acc.wbstream[0].storage_state = state
        await save_room_accounts(db, acc)
        print("bootstrapped_from_host_state")

asyncio.run(boot())
PY
docker exec -w /app {CONTAINER} python scripts/sync_olcrtc_wb_auth_token.py
mkdir -p /opt/silent-vpn/olcrtc
mapfile -t YMLS < <(docker exec {CONTAINER} sh -c 'ls /app/update/olcrtc/server*.yaml 2>/dev/null' || true)
for y in "${{YMLS[@]}}"; do
  [ -z "$y" ] && continue
  base=$(basename "$y")
  docker cp "{CONTAINER}:$y" "/opt/silent-vpn/olcrtc/$base"
  echo "host yaml $base"
done
for s in pc-wbstream android-wbstream; do
  f="/opt/silent-vpn/olcrtc/server-$s.yaml"
  if [ -f "$f" ]; then
    if grep -q 'token:' "$f"; then
      echo "$s: auth.token present"
    else
      echo "$s: auth.token MISSING"
    fi
    systemctl restart "olcrtc@$s.service" || true
    sleep 1
    systemctl is-active "olcrtc@$s.service" || true
  else
    echo "no server-$s.yaml"
  fi
done
"""

sftp2 = client.open_sftp()
sftp2.putfo(io.BytesIO(remote.encode()), "/tmp/sync_wb_auth.sh")
sftp2.close()
out = run(client, "bash /tmp/sync_wb_auth.sh 2>&1", timeout=180)
print(out)
client.close()
print("Done")
