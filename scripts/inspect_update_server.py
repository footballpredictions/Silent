"""Inspect OTA files and API on VPS."""
import json
import paramiko

HOST = "132.243.234.162"
USER = "root"
PASS = "3txvDbnJvVaZg"


def run(client, cmd):
    _, out, err = client.exec_command(cmd, timeout=60)
    text = out.read().decode("utf-8", errors="replace")
    e = err.read().decode("utf-8", errors="replace")
    print(f"\n$ {cmd}\n{text}")
    if e.strip():
        print("ERR:", e)


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20)
    run(client, "cat /opt/silent-vpn/backend/update/android/manifest.json 2>/dev/null || echo HOST manifest missing")
    run(client, "ls -la /opt/silent-vpn/backend/update/android/")
    run(client, "docker exec backend-api-1 cat /app/update/android/manifest.json 2>/dev/null || echo CONTAINER manifest missing")
    run(client, "docker exec backend-api-1 ls -la /app/update/android/")
    for ver in ("1.0.110", "1.0.111", "1.0.112"):
        run(client, f'curl -s "http://localhost:8000/api/updates/check?platform=android&version={ver}"')
    run(client, "docker inspect backend-api-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'")
    run(client, "md5sum /opt/silent-vpn/backend/update/android/SilentVPN-release.apk")
    run(client, "docker exec backend-api-1 md5sum /app/update/android/SilentVPN-release.apk")
    run(client, "curl -sI http://127.0.0.1:8000/update/android/SilentVPN-release.apk | head -12")
    run(client, "grep -r 'update/android' /opt/silent-vpn/ 2>/dev/null | head -20")
    run(client, "docker ps --format '{{.Names}}'")
    client.close()


if __name__ == "__main__":
    main()
