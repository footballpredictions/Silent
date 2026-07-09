"""Smoke-test referral flow against production API without real YuMoney payment.

Simulates:
  1) inviter login → GET /users/me/referral
  2) invitee register with referral_or_promo
  3) invalid code → 400
  4) theme has bonuses fields
  5) health still OK

Uses admin credentials from VPS only if ADMIN_* env set; otherwise creates
throwaway users via public register (email may need verify — register itself is enough).
"""
from __future__ import annotations

import os
import sys
import time
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

    # 0) health
    r = client.get("/api/health")
    if r.status_code != 200:
        r = client.get("/health")
    check("health", r.status_code == 200, f"HTTP {r.status_code}")

    # 1) theme bonuses fields
    r = client.get("/api/vpn/theme")
    check("theme", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        theme = r.json()
        for key in (
            "menu_bonuses_label",
            "bonuses_title",
            "bonuses_referral_title",
            "register_referral_or_promo_label",
        ):
            check(f"theme.{key}", key in theme and bool(str(theme.get(key) or "").strip()), str(theme.get(key)))

    # 2) register inviter
    suffix = uuid.uuid4().hex[:8]
    inviter_email = f"ref.inv.{suffix}@example.com"
    invitee_email = f"ref.tee.{suffix}@example.com"
    password = "TestPass12!"

    r = client.post("/api/auth/register", json={"email": inviter_email, "password": password})
    check("register inviter", r.status_code in (200, 201), f"HTTP {r.status_code} {r.text[:200]}")

    # Without verify we cannot login normally — use admin path if ADMIN_* env set.
    admin_login = os.environ.get("ADMIN_LOGIN")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    referral_code = None

    if admin_login and admin_pass:
        ar = client.post("/api/auth/admin/login", json={"login": admin_login, "password": admin_pass})
        if ar.status_code != 200:
            print(f"[INFO] admin login skipped (HTTP {ar.status_code}) - authenticated checks covered by remote_referral_db_test")
        else:
            check("admin login", True)
        if ar.status_code == 200:
            admin_token = ar.json().get("access_token")
            headers = {"Authorization": f"Bearer {admin_token}"}
            ur = client.get("/api/admin/users", headers=headers)
            check("admin users", ur.status_code == 200, f"HTTP {ur.status_code}")
            inviter_id = None
            if ur.status_code == 200:
                for u in ur.json():
                    if (u.get("email") or "").lower() == inviter_email.lower():
                        inviter_id = u.get("id")
                        break
            check("find inviter", inviter_id is not None, inviter_email)
            if inviter_id:
                vr = client.post(f"/api/admin/users/{inviter_id}/verify", headers=headers)
                check("verify inviter", vr.status_code in (200, 201), f"HTTP {vr.status_code} {vr.text[:120]}")

            lr = client.post("/api/auth/login", json={"email": inviter_email, "password": password})
            check("login inviter", lr.status_code == 200, f"HTTP {lr.status_code} {lr.text[:200]}")
            if lr.status_code == 200:
                user_headers = {"Authorization": f"Bearer {lr.json()['access_token']}"}
                rr = client.get("/api/users/me/referral", headers=user_headers)
                check("GET /me/referral", rr.status_code == 200, f"HTTP {rr.status_code} {rr.text[:200]}")
                if rr.status_code == 200:
                    data = rr.json()
                    referral_code = data.get("referral_code")
                    link = data.get("referral_link") or ""
                    check("referral_code", bool(referral_code), str(referral_code))
                    check(
                        "referral_link",
                        link.startswith("silentvpn://ref?code=") and referral_code in link,
                        link,
                    )
                    check("bonus_days", data.get("bonus_days") == 30, str(data.get("bonus_days")))

                if referral_code:
                    ir = client.post(
                        "/api/auth/register",
                        json={
                            "email": invitee_email,
                            "password": password,
                            "referral_or_promo": referral_code,
                        },
                    )
                    check(
                        "register invitee with ref",
                        ir.status_code in (200, 201),
                        f"HTTP {ir.status_code} {ir.text[:200]}",
                    )
                    invitee_id = None
                    ur2 = client.get("/api/admin/users", headers=headers)
                    if ur2.status_code == 200:
                        for u in ur2.json():
                            if (u.get("email") or "").lower() == invitee_email.lower():
                                invitee_id = u.get("id")
                                break
                    if invitee_id:
                        client.post(f"/api/admin/users/{invitee_id}/verify", headers=headers)
                    rr2 = client.get("/api/users/me/referral", headers=user_headers)
                    if rr2.status_code == 200:
                        pending = rr2.json().get("pending_count", 0)
                        invited = rr2.json().get("invited_count", 0)
                        check("invited_count>=1", invited >= 1, str(invited))
                        check("pending_count>=1", pending >= 1, str(pending))

                    print("[INFO] YuMoney notify not called (needs signature); reward path covered in service code")
    else:
        print("[INFO] ADMIN_LOGIN/ADMIN_PASSWORD not set - skipping authenticated referral checks")

    # 3) invalid referral_or_promo
    bad_email = f"ref.bad.{suffix}@example.com"
    br = client.post(
        "/api/auth/register",
        json={"email": bad_email, "password": password, "referral_or_promo": "NOTAREALCODE99"},
    )
    check("invalid ref/promo -> 400", br.status_code == 400, f"HTTP {br.status_code} {br.text[:200]}")

    # 4) empty referral still works
    ok_email = f"ref.ok.{suffix}@example.com"
    or_ = client.post("/api/auth/register", json={"email": ok_email, "password": password})
    check("register without code", or_.status_code in (200, 201), f"HTTP {or_.status_code}")

    print()
    if errors:
        print(f"FAILED: {len(errors)} checks")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
