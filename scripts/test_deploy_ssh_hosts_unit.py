"""Куда стучится deploy SSH: публичный Улей, затем шлюз WG."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import ssh_hosts  # noqa: E402


def test_ssh_hosts_hive_then_tunnel():
    hosts = ssh_hosts("132.243.234.162")
    assert hosts[0] == "132.243.234.162"
    assert "10.66.66.1" in hosts
    assert hosts.index("10.66.66.1") > 0


def test_ssh_hosts_no_dup_when_already_tunnel():
    hosts = ssh_hosts("10.66.66.1")
    assert hosts == ["10.66.66.1"]


if __name__ == "__main__":
    test_ssh_hosts_hive_then_tunnel()
    test_ssh_hosts_no_dup_when_already_tunnel()
    print("ok")
