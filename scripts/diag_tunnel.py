from _deploy_common import connect, run

c = connect()
cmds = [
    "docker inspect -f '{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' backend-api-1 backend-nginx-1 backend-db-1 2>/dev/null",
    "ip -4 addr show | grep -E '10\\.66|wg|wdtt' || ip -4 addr | grep 10.66",
    "ip route get 10.66.66.1 2>&1",
    "curl -sf --connect-timeout 2 http://172.18.0.4:8000/health 2>&1 || echo api-ip-fail",
    "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $(docker ps -q --filter name=backend-api) 2>/dev/null",
]
for cmd in cmds:
    print("\n===", cmd[:75], "===")
    print(run(c, cmd))
