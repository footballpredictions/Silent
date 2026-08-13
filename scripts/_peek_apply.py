from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run

q = connect()
print(run(q, "docker exec backend-api-1 sed -n '106,165p' /app/app/services/olcrtc2_cell_units.py"))
print("--- cell agent apply snippet ---")
# also ask cell via curl what it would do - add debug by reading remote main
print(run(q, "docker exec backend-api-1 python -c \"from pathlib import Path; p=Path('/app/app/services/olcrtc2_cell_units.py'); t=p.read_text(); print('has_auth_token', 'auth_token' in t); print('wbstream_guard', 'no account JWT' in t)\""))
q.close()
