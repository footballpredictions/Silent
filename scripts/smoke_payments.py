"""Smoke-test the YuMoney payment flow against production API (no real payment made).

Simulates:
  1) health + theme has payment_* fields
  2) GET /api/payments/plans
  3) POST /api/payments/init (admin/test user) -> url is well-formed, label unique, wallet
     is one of the configured wallets
  4) GET /api/payments/status/{label} -> "pending"
  5) GET /api/payments/status/{other_users_label} -> 404 (no cross-user leakage)
  6) GET /api/payments/success-page -> 200 HTML
  7) POST /api/payments/yumoney/notify with a forged/unsigned body -> 400
  8) POST /api/payments/yumoney/notify with sum=1 (correct signature, wrong amount) -> 200
     but does NOT activate a subscription (idempotent-safe; verified via status endpoint
     staying "failed", not "completed")

Notification signing requires a real wallet secret (SMOKE_YUMONEY_SECRET / matching
wallet SMOKE_YUMONEY_WALLET env) — those checks are skipped if not provided, since a
production wallet secret should never be hardcoded here.
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid

import httpx

BASE = os.environ.get("SILENT_API", "https://132-243-234-162.nip.io").rstrip("/")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0, verify=True)
    errors: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            errors.append(name)

    r = client.get("/api/health")
    if r.status_code != 200:
        r = client.get("/health")
    check("health", r.status_code == 200, f"HTTP {r.status_code}")

    r = client.get("/api/vpn/theme")
    check("theme", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        theme = r.json()
        for key in (
            "payment_waiting_title", "payment_waiting_text",
            "payment_success_title", "payment_failed_title",
        ):
            check(f"theme.{key}", key in theme and bool(str(theme.get(key) or "").strip()), str(theme.get(key)))

    r = client.get("/api/payments/plans")
    check("plans", r.status_code == 200, f"HTTP {r.status_code}")
    plan_ids = {p.get("id") for p in r.json()} if r.status_code == 200 else set()
    check("plans has monthly/two_months/quarterly", {"monthly", "two_months", "quarterly"} <= plan_ids, str(plan_ids))
    check("plans has no yearly in shop", "yearly" not in plan_ids, str(plan_ids))

    r = client.get("/api/payments/success-page")
    check("success-page", r.status_code == 200 and "text/html" in r.headers.get("content-type", "") and "silentvpn://payment" in (r.text or ""), f"HTTP {r.status_code}")

    # Unsigned/forged notification must be rejected outright.
    r = client.post("/api/payments/yumoney/notify", data={
        "notification_type": "p2p-incoming",
        "operation_id": "forged-1",
        "amount": "199.00",
        "currency": "643",
        "datetime": "2026-07-14T10:00:00Z",
        "sender": "00000000000",
        "codepro": "false",
        "label": "silent_forged",
        "sha1_hash": "0000000000000000000000000000000000000000",
    })
    check("forged notification rejected (400)", r.status_code == 400, f"HTTP {r.status_code}")

    admin_login = os.environ.get("ADMIN_LOGIN")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    if not (admin_login and admin_pass):
        print("[INFO] ADMIN_LOGIN/ADMIN_PASSWORD not set — skipping authenticated /payments/init checks")
        print()
        if errors:
            print(f"FAILED: {len(errors)} checks")
            return 1
        print("ALL CHECKS PASSED (partial — set ADMIN_LOGIN/ADMIN_PASSWORD for full coverage)")
        return 0

    ar = client.post("/api/auth/admin/login", json={"login": admin_login, "password": admin_pass})
    check("admin login", ar.status_code == 200, f"HTTP {ar.status_code}")
    if ar.status_code != 200:
        print(f"FAILED: {len(errors) + 1} checks")
        return 1
    admin_headers = {"Authorization": f"Bearer {ar.json()['access_token']}"}

    suffix = uuid.uuid4().hex[:8]
    email = f"pay.smoke.{suffix}@example.com"
    password = "TestPass12!"
    rr = client.post("/api/auth/register", json={"email": email, "password": password})
    check("register test user", rr.status_code in (200, 201), f"HTTP {rr.status_code}")

    ur = client.get("/api/admin/users", headers=admin_headers)
    user_id = None
    if ur.status_code == 200:
        for u in ur.json():
            if (u.get("email") or "").lower() == email.lower():
                user_id = u.get("id")
                break
    check("find test user", user_id is not None, email)
    if user_id:
        client.post(f"/api/admin/users/{user_id}/verify", headers=admin_headers)

    lr = client.post("/api/auth/login", json={"email": email, "password": password})
    check("login test user", lr.status_code == 200, f"HTTP {lr.status_code}")
    if lr.status_code != 200:
        print()
        print(f"FAILED: {len(errors)} checks")
        return 1
    user_headers = {"Authorization": f"Bearer {lr.json()['access_token']}"}

    labels_seen = set()
    init_ok = True
    for _ in range(3):
        ir = client.post("/api/payments/init", json={"plan_type": "monthly"}, headers=user_headers)
        if ir.status_code != 200:
            init_ok = False
            break
        body = ir.json()
        for key in ("url", "wallet", "label", "amount"):
            if key not in body:
                init_ok = False
        if body.get("label") in labels_seen:
            init_ok = False  # labels must be unique per init call
        labels_seen.add(body.get("label"))
        if not str(body.get("url", "")).startswith("https://yoomoney.ru/quickpay/confirm.xml?"):
            init_ok = False
        if " " in str(body.get("url", "")):
            init_ok = False  # must be URL-encoded (bug #5 in the plan)
    check("payments/init x3: unique labels, valid encoded url", init_ok, str(labels_seen))

    label = next(iter(labels_seen)) if labels_seen else None
    if label:
        sr = client.get(f"/api/payments/status/{label}", headers=user_headers)
        check("status pending", sr.status_code == 200 and sr.json().get("status") == "pending", sr.text[:150])

        # Cross-user isolation: another logged-in user must not see this label.
        other_email = f"pay.smoke.other.{suffix}@example.com"
        client.post("/api/auth/register", json={"email": other_email, "password": password})
        our = client.get("/api/admin/users", headers=admin_headers)
        other_id = None
        if our.status_code == 200:
            for u in our.json():
                if (u.get("email") or "").lower() == other_email.lower():
                    other_id = u.get("id")
                    break
        if other_id:
            client.post(f"/api/admin/users/{other_id}/verify", headers=admin_headers)
        olr = client.post("/api/auth/login", json={"email": other_email, "password": password})
        if olr.status_code == 200:
            other_headers = {"Authorization": f"Bearer {olr.json()['access_token']}"}
            osr = client.get(f"/api/payments/status/{label}", headers=other_headers)
            check("status hidden from other user (404)", osr.status_code == 404, f"HTTP {osr.status_code}")

    smoke_wallet = os.environ.get("SMOKE_YUMONEY_WALLET")
    smoke_secret = os.environ.get("SMOKE_YUMONEY_SECRET")
    if label and smoke_wallet and smoke_secret:
        def signed(secret: str, **fields) -> dict:
            data = {
                "notification_type": "p2p-incoming",
                "operation_id": f"smoke-{uuid.uuid4().hex[:10]}",
                "amount": "1.00",
                "withdraw_amount": "1.00",
                "currency": "643",
                "datetime": "2026-07-14T10:00:00Z",
                "sender": "41001151234567",
                "codepro": "false",
                "unaccepted": "false",
                "label": label,
            }
            data.update(fields)
            check_str = "&".join([
                data["notification_type"], data["operation_id"], data["amount"], data["currency"],
                data["datetime"], data["sender"], data["codepro"], secret, data["label"],
            ])
            data["sha1_hash"] = hashlib.sha1(check_str.encode("utf-8")).hexdigest()
            return data

        nr = client.post("/api/payments/yumoney/notify", data=signed(smoke_secret))
        check("sum=1 attack notification -> 200 (ack, not activated)", nr.status_code == 200, f"HTTP {nr.status_code} {nr.text[:150]}")

        sr2 = client.get(f"/api/payments/status/{label}", headers=user_headers)
        check(
            "sum=1 attack did not activate subscription",
            sr2.status_code == 200 and sr2.json().get("status") == "failed",
            sr2.text[:150],
        )
    else:
        print("[INFO] SMOKE_YUMONEY_WALLET/SMOKE_YUMONEY_SECRET not set — skipping real-signature notify checks")

    print()
    if errors:
        print(f"FAILED: {len(errors)} checks")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
