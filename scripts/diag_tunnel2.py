from _deploy_common import connect, run

c = connect()
for cmd in [
    "curl -sf --connect-timeout 2 http://127.0.0.1:8000/health; echo ok127",
    "curl -sf --connect-timeout 2 http://172.18.0.2:8000/health; echo okapi",
    "ip -4 addr show dev wdtt0",
    "iptables -t nat -L PREROUTING -n -v | grep 10.66",
    "iptables -t nat -L OUTPUT -n | grep 10.66 || echo no-output",
]:
    print("\n===", cmd, "===")
    print(run(c, cmd))
