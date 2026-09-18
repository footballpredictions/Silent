"""Куда стучится deploy SSH: публичный Улей, затем шлюз WG."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import ssh_hosts  # noqa: E402


def test_ssh_hosts_hive_then_tunnel():
    hosts = ssh_hosts("89.125.188.100")
    assert hosts[0] == "89.125.188.100"
    assert "10.66.66.1" in hosts
    assert hosts.index("10.66.66.1") > 0


def test_ssh_hosts_no_dup_when_already_tunnel():
    hosts = ssh_hosts("10.66.66.1")
    assert hosts == ["10.66.66.1"]


def test_jump_hosts_default_worker_cells():
    from _deploy_common import jump_hosts

    hosts = jump_hosts("")
    assert hosts[0] == "87.58.213.193"
    assert "78.17.74.27" in hosts
    assert "192.177.26.38" not in hosts


def test_jump_hosts_custom_list():
    from _deploy_common import jump_hosts

    assert jump_hosts(" 1.2.3.4 , 1.2.3.4, 5.6.7.8 ") == ["1.2.3.4", "5.6.7.8"]


if __name__ == "__main__":
    test_ssh_hosts_hive_then_tunnel()
    test_ssh_hosts_no_dup_when_already_tunnel()
    test_jump_hosts_default_worker_cells()
    test_jump_hosts_custom_list()
    print("ok")
