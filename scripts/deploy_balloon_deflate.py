"""Install virtio-balloon deflate units on the Queen VPS host (no wdtt restart)."""
from __future__ import annotations

import stat
from pathlib import Path

from _deploy_common import REMOTE, connect, run

HOST_DIR = "deploy/host"
FILES = (
    "silent-deflate-balloon.sh",
    "silent-balloon-watch.sh",
    "silent-deflate-balloon.service",
    "silent-balloon-watch.service",
    "silent-balloon-watch.timer",
)


def main() -> None:
    c = connect()
    try:
        remote_host = f"{REMOTE}/deploy/host"
        run(c, f"mkdir -p {remote_host}")
        sftp = c.open_sftp()
        local = Path(__file__).resolve().parents[1] / "deploy" / "host"
        for name in FILES:
            lp = local / name
            rp = f"{remote_host}/{name}"
            sftp.put(str(lp), rp)
            print(f"upload {name}")
            if name.endswith(".sh"):
                sftp.chmod(rp, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        for unit in (
            "silent-deflate-balloon.service",
            "silent-balloon-watch.service",
            "silent-balloon-watch.timer",
        ):
            run(c, f"cp -f {remote_host}/{unit} /etc/systemd/system/{unit}")
        sftp.close()
        run(c, "systemctl daemon-reload")
        run(c, "systemctl enable --now silent-deflate-balloon.service")
        run(c, "systemctl enable --now silent-balloon-watch.timer")
        run(c, "systemctl start silent-balloon-watch.service || true")
        run(c, "systemctl --no-pager --full status silent-deflate-balloon.service | head -20")
        run(c, "free -h; grep MemTotal /proc/meminfo")
        run(c, "systemctl is-active wdtt")
    finally:
        c.close()


if __name__ == "__main__":
    main()
