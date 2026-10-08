# Windows browser site routing

When site IP snapshots are applied, Windows removes matching legacy global site
routes left by old clients: only ActiveStore routes with the old metric 0/1 on
the captured physical gateway. Persistent routes and current API/peer/VK bypass
destinations are preserved. Without this migration, a stale /32 wins over the
tunnel's /1 and the native router never sees the selected site's packets.

Before the first DNS snapshot, browsers stay in the tunnel (explicit app
exclusions still take priority). An unresolved snapshot retries after 15 seconds
instead of interpreting selected-but-unresolved sites as outside the allowlist.
Policy changes reset only affected TCP flows. If Windows cannot delete a TCB,
the router supplies a reverse TCP RST using the endpoint's latest ACK, so an idle
pooled browser connection cannot remain on the previous route.

Windows main VPN uses `site-router.exe` + the bundled signed `wintun.dll`.
Bootstrap/payment temporary VPN keeps the existing WireGuard service path.
This module ports the tested Android packet/DNS/direct-stack implementation;
the Windows adapter resolves owners through GetExtendedTcpTable/GetExtendedUdpTable
and QueryFullProcessImageName, and binds direct sockets with IP_UNICAST_IF.

Site rules apply only to recognized browser processes. Embedded WebViews and
ordinary/unknown processes keep VPN routing. App exclusions take precedence and
also match descendants of selected processes. No shared destination bypass routes
are installed for either list on Windows. Transport/API routes keep their existing
behavior. Live edits change policy over private stdin, without restarting WG;
only connections whose effective route changes are cleared. Windows closes their
TCP state with SetTcpEntry so applications reconnect using the new route; direct
UDP sessions are also cleared. Other connections and the VPN remain running.
DNS answers for rules that remain selected survive list edits.
Startup passes domain/literal-IP rules without waiting for pre-VPN DNS. Once the
tunnel is up, fallback snapshots resolve at most eight domain rules at once with
a two-second total budget; stalled DNS is cancelled and valid retained cache kept.
Snapshots explicitly use the configured VPN DNS servers, including after edits;
an old pre-connect LAN resolver must not leave selected Chrome sites without IPs.
Policy ACKs/counts and native warnings are recorded under Sites in the main log.

Actual VPN UDP DNS answers teach selected domains and subdomains before delivery.
YouTube rules also include its separate googlevideo.com, ytimg.com and ggpht.com
resource domains in either mode. Electron expands these only in the browser
policy; the saved list stays as entered. Common static resource hosts seed the
DNS snapshot, while dynamic video hosts are learned from actual DNS answers.
CDN roots without A records do not keep the entire browser in pending-DNS mode.
Manual encrypted DNS is not observable; resolved IP snapshots remain a fallback.
IP-level rules can include shared CDN addresses inside the browser, as on Android.
The router is IPv4; existing Windows IPv6 leak handling is retained.

Build: `powershell -File site-router/build.ps1` (Go 1.26.3, Windows amd64).
Both Windows build scripts include it, and `resources/wireguard/**` packages it.
Run the debug app via `SilentVPN-Admin.bat`. Version and OTA stay unchanged.
Linux/macOS have not been ported to this native adapter and retain old routing.

Checks: `go test ./...`, `go vet ./...`, `npm test` from the PC root.
Native tests cover process ownership, direct TCP/UDP, DNS, app/browser precedence,
and a real encrypted WireGuard pair passing ordinary application traffic with an
empty browser allowlist. These tests use local sockets/in-memory TUNs and do not
alter system routes. GUI/main-VPN/actual-payment acceptance is performed by the user.

Windows reference: [IP_UNICAST_IF](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options)
uses an interface index in network byte order;
[TCP owner table](https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcptable_owner_pid)
is independent of the selected site destinations.
