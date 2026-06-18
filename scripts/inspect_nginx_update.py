"""Check nginx update routing on VPS."""
import paramiko

HOST = "132.243.234.162"
USER = "root"
PASS = "3txvDbnJvVaZg"


def run(client, cmd):
    _, out, err = client.exec_command(cmd, timeout=60)
    text = out.read().decode("utf-8", errors="replace")
    print(f"\n$ {cmd}\n{text}")
    e = err.read().decode("utf-8", errors="replace")
    if e.strip():
        print("ERR:", e)


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20)
    run(client, "docker exec backend-nginx-1 cat /etc/nginx/conf.d/default.conf 2>/dev/null || docker exec backend-nginx-1 cat /etc/nginx/nginx.conf")
    run(client, "docker exec backend-nginx-1 ls -la /etc/nginx/conf.d/ 2>/dev/null")
    for f in ("default.conf", "silent.conf", "backend.conf"):
        run(client, f"docker exec backend-nginx-1 cat /etc/nginx/conf.d/{f} 2>/dev/null || true")
    run(client, "curl -sI http://backend-nginx-1/update/android/SilentVPN-release.apk | head -12")
    run(client, "curl -sI https://132.243.234.162/update/android/SilentVPN-release.apk -k | head -12")
    client.close()


if __name__ == "__main__":
    main()
