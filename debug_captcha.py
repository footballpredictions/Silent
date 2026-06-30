"""
Diagnostic script: simulates the full VK captcha auth chain (same logic as Go wdtt-client).
Shows exact API responses at each step so we can identify why captchaNotRobot.check returns error_limit.

Usage: cd pc && pip install curl_cffi && python debug_captcha.py
Docs:  backend/.cursor/MEMORY_BANK.md → «Диагностика VK Smart Captcha»
"""

import re, json, time, random, hashlib, base64, uuid, urllib.parse
from curl_cffi import requests as creqs

# ─── Config ──────────────────────────────────────────────────────────────────
VK_HASH       = "6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY"   # bootstrap hash
CLIENT_ID     = "6287487"
CLIENT_SECRET = "MuAxFaKDYDOICzGnEOhp"
API_VERSION   = "5.275"
CAPTCHA_API_VERSION = "5.131"

HEADERS_BASE = {
    "user-agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "accept-language":    "en-US,en;q=0.9",
    "sec-ch-ua":          '"Google Chrome";v="135", "Chromium";v="135", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
}

session = creqs.Session(impersonate="chrome124")

def post(url, data, extra_headers=None):
    headers = {**HEADERS_BASE,
               "content-type": "application/x-www-form-urlencoded",
               "origin": "https://vk.ru",
               "referer": "https://vk.ru/",
               "sec-fetch-site": "same-site",
               "sec-fetch-mode": "cors",
               "sec-fetch-dest": "empty"}
    if extra_headers:
        headers.update(extra_headers)
    r = session.post(url, data=data, headers=headers, timeout=20)
    try:
        return r.json()
    except Exception:
        print(f"  [!] Non-JSON response ({r.status_code}): {r.text[:300]}")
        return {}

def get(url, extra_headers=None):
    headers = {**HEADERS_BASE}
    if extra_headers:
        headers.update(extra_headers)
    r = session.get(url, headers=headers, timeout=20)
    return r

def sep(title):
    print(f"\n{'-'*60}")
    print(f"  {title}")
    print('-'*60)

# ─── Step 1: get_anonym_token ─────────────────────────────────────────────────
sep("STEP 1 — get_anonym_token")
data = f"client_id={CLIENT_ID}&token_type=messages&client_secret={CLIENT_SECRET}&version=1&app_id={CLIENT_ID}"
resp = post("https://login.vk.ru/?act=get_anonym_token", data)
print(json.dumps(resp, indent=2, ensure_ascii=False))

token1 = resp.get("data", {}).get("access_token", "")
if not token1:
    print("[FATAL] no access_token in step 1"); exit(1)
print(f"  >> token1 = {token1[:40]}...")
time.sleep(random.uniform(0.1, 0.15))

# ─── Step 2: getCallPreview ───────────────────────────────────────────────────
sep("STEP 2 — getCallPreview")
data = f"vk_join_link=https://vk.com/call/join/{VK_HASH}&fields=photo_200&access_token={token1}"
resp2 = post(f"https://api.vk.ru/method/calls.getCallPreview?v={API_VERSION}&client_id={CLIENT_ID}", data)
print(json.dumps(resp2, indent=2, ensure_ascii=False)[:500])
time.sleep(random.uniform(0.2, 0.4))

# ─── Step 3: getAnonymousToken (may trigger captcha) ─────────────────────────
sep("STEP 3 — getAnonymousToken")
name = "User" + str(random.randint(1000, 9999))
data3 = f"vk_join_link=https://vk.com/call/join/{VK_HASH}&name={urllib.parse.quote(name)}&access_token={token1}"
url3  = f"https://api.vk.ru/method/calls.getAnonymousToken?v={API_VERSION}&client_id={CLIENT_ID}"

resp3 = post(url3, data3)
print(json.dumps(resp3, indent=2, ensure_ascii=False)[:1000])

captcha_err = None
if "error" in resp3:
    err = resp3["error"]
    redirect_uri = err.get("redirect_uri", "")
    session_token = ""
    if redirect_uri:
        parsed = urllib.parse.urlparse(redirect_uri)
        session_token = urllib.parse.parse_qs(parsed.query).get("session_token", [""])[0]
    captcha_err = {
        "error_code":     err.get("error_code"),
        "error_msg":      err.get("error_msg"),
        "captcha_sid":    str(err.get("captcha_sid", "")),
        "redirect_uri":   redirect_uri,
        "session_token":  session_token,
        "captcha_ts":     str(err.get("captcha_ts", "")),
    }
    sep("CAPTCHA REQUIRED")
    print(json.dumps(captcha_err, indent=2, ensure_ascii=False))
else:
    print("\n  >> No captcha! token =", str(resp3.get("response", {}).get("token", ""))[:40])
    exit(0)

if not captcha_err["session_token"]:
    print("[FATAL] no session_token"); exit(1)

session_token = captcha_err["session_token"]
captcha_url   = captcha_err["redirect_uri"]

# ─── Step 4: Fetch captcha HTML ───────────────────────────────────────────────
sep("STEP 4 — Fetch captcha page HTML")
r_html = get(captcha_url, extra_headers={
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "cross-site",
})
html = r_html.text
print(f"  HTTP {r_html.status_code}, len={len(html)}")

# Extract PoW + script URL + window.init
pow_input    = (re.search(r'const\s+powInput\s*=\s*"([^"]+)"', html) or [None,None])[1]
pow_diff     = (re.search(r'const\s+difficulty\s*=\s*(\d+)', html) or [None,None])[1]
script_src   = (re.search(r'src="(https://[^"]+not_robot_captcha[^"]+)"', html) or [None,None])[1]
window_init  = (re.search(r'(?s)window\.init\s*=\s*(\{.*?})\s*;', html) or [None,None])[1]

print(f"  powInput      = {pow_input}")
print(f"  difficulty    = {pow_diff}")
print(f"  scriptSrc     = {script_src}")
print(f"  window.init   = {window_init[:200] if window_init else None}")

if not pow_input or not pow_diff:
    print("  [!] Could not parse PoW — dumping first 3000 chars of HTML:")
    print(html[:3000])
    exit(1)

diff = int(pow_diff)

# ─── Step 5: Fetch debug_info from captcha JS ────────────────────────────────
sep("STEP 5 — Fetch debug_info from captcha script")
debug_info = ""
if script_src:
    r_js = get(script_src, extra_headers={"accept": "text/javascript,*/*", "referer": "https://id.vk.com/"})
    js_body = r_js.text
    m = re.search(r'debug_info:(?:[^"]*\|\|)?"([a-fA-F0-9]{64})"', js_body)
    if m:
        debug_info = m.group(1)
        print(f"  debug_info    = {debug_info}")
    else:
        print(f"  [!] debug_info NOT found in JS (len={len(js_body)})")
        # Show some context around 'debug_info' in the script
        idx = js_body.find('debug_info')
        if idx >= 0:
            print(f"  context around debug_info: ...{js_body[max(0,idx-30):idx+120]}...")
        else:
            print("  'debug_info' string not found at all in JS!")

# ─── Step 6: Solve PoW ───────────────────────────────────────────────────────
sep("STEP 6 — Solve PoW")
target = "0" * diff
pow_hash = ""
t0 = time.time()
for nonce in range(1, 10_000_000):
    h = hashlib.sha256(f"{pow_input}{nonce}".encode()).hexdigest()
    if h.startswith(target):
        pow_hash = h
        break
print(f"  difficulty={diff}, solved in {time.time()-t0:.2f}s, nonce found, hash={pow_hash[:20]}...")
time.sleep(random.uniform(0.2, 0.6))  # v3: simulate browser render delay

# ─── Step 7: captchaNotRobot.settings ────────────────────────────────────────
sep("STEP 7 — captchaNotRobot.settings")
settings_data = [
    ("session_token", session_token),
    ("domain", "vk.com"),
    ("adFp", ""),
    ("access_token", ""),
]
encoded = "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in settings_data)
settings_resp = post(
    f"https://api.vk.ru/method/captchaNotRobot.settings?v={CAPTCHA_API_VERSION}",
    encoded,
    extra_headers={"origin": "https://id.vk.com", "referer": "https://id.vk.com/", "priority": "u=1, i"}
)
print(json.dumps(settings_resp, indent=2, ensure_ascii=False))

# ─── Step 8: captchaNotRobot.componentDone ───────────────────────────────────
sep("STEP 8 — captchaNotRobot.componentDone")
browser_fp = base64.b16encode(random.randbytes(16)).decode().lower()
device_info = '{"screenWidth":1920,"screenHeight":1080,"screenAvailWidth":1920,"screenAvailHeight":1040,"innerWidth":1920,"innerHeight":951,"devicePixelRatio":1,"language":"en-US","languages":["en-US","en"],"webdriver":false,"hardwareConcurrency":8,"notificationsPermission":"denied"}'
comp_data = [
    ("session_token", session_token),
    ("domain", "vk.com"),
    ("adFp", ""),
    ("browser_fp", browser_fp),
    ("device", device_info),
    ("access_token", ""),
]
encoded2 = "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in comp_data)
comp_resp = post(
    f"https://api.vk.ru/method/captchaNotRobot.componentDone?v={CAPTCHA_API_VERSION}",
    encoded2,
    extra_headers={"origin": "https://id.vk.com", "referer": "https://id.vk.com/", "priority": "u=1, i"}
)
print(json.dumps(comp_resp, indent=2, ensure_ascii=False))
time.sleep(random.uniform(0.3, 0.75))  # v3: cursor movement delay

# ─── Step 9: captchaNotRobot.check ───────────────────────────────────────────
sep("STEP 9 — captchaNotRobot.check (THE KEY STEP)")
answer_b64 = base64.b64encode(b"{}").decode()

# v3 behavioral data
cursor_pts = [{"x": 800+i*5+random.randint(-3,3), "y": 400+i*8+random.randint(-3,3)} for i in range(8)]
cursor_pts += [{"x": 720+random.randint(-4,4), "y": 848+random.randint(-4,4)} for _ in range(4)]
cursor = json.dumps(cursor_pts)

conn_rtt      = json.dumps([40 + random.randint(-10, 20) for _ in range(4)])
conn_downlink = json.dumps([10.0] * 4)

check_data = [
    ("session_token",    session_token),
    ("domain",           "vk.com"),
    ("adFp",             ""),
    ("accelerometer",    "[]"),
    ("gyroscope",        "[]"),
    ("motion",           "[]"),
    ("cursor",           cursor),
    ("taps",             "[]"),
    ("connectionRtt",    conn_rtt),
    ("connectionDownlink", conn_downlink),
    ("browser_fp",       browser_fp),
    ("hash",             pow_hash),
    ("answer",           answer_b64),
    ("debug_info",       debug_info),
    ("access_token",     ""),
]
encoded3 = "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in check_data)
check_resp = post(
    f"https://api.vk.ru/method/captchaNotRobot.check?v={CAPTCHA_API_VERSION}",
    encoded3,
    extra_headers={"origin": "https://id.vk.com", "referer": "https://id.vk.com/", "priority": "u=1, i"}
)
sep("RESULT — captchaNotRobot.check FULL RESPONSE")
print(json.dumps(check_resp, indent=2, ensure_ascii=False))
status = check_resp.get("response", {}).get("status", "")
print(f"\n  >> status = {status!r}")

if status == "error_limit":
    print("\n  [DIAGNOSIS] error_limit received!")
    print("  Possible causes:")
    print("  1. IP is flagged by VK for automated captcha solving")
    print("  2. session_token already used/expired")
    print("  3. Missing or wrong field in the request")
    print("  4. debug_info value is incorrect for the current script version")
elif status == "ok":
    print(f"\n  [SUCCESS] success_token = {check_resp.get('response',{}).get('success_token','')[:60]}")
elif status == "bot":
    print("\n  [DIAGNOSIS] bot — VK detected automation via behavioral signals")
else:
    print(f"\n  [DIAGNOSIS] unexpected status: {status!r}")
    print("  Full error object:", check_resp.get("error"))
