"""Apply the reviewed iOS lifecycle changes to the pinned shared WDTT client."""
from pathlib import Path
import re
import sys


def adapt(source):
    def replace_once(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError("Shared WDTT session changed; review the iOS lifecycle adapter: " + old.splitlines()[0])
        source = source.replace(old, new, 1)

    source, count = re.subn(r"workerSendBuf\s*=\s*2048", "workerSendBuf = 64", source)
    if count != 1:
        raise ValueError("Shared WDTT worker queue changed")

    # GETCONF and the proxy must both unblock on session cancellation.
    old = ("\tstopDTLS := context.AfterFunc(sessCtx, func() {\n"
           "\t\t_ = dtlsConn.SetDeadline(time.Now())\n"
           "\t})\n\tdefer stopDTLS()\n\n")
    replace_once(old, "")
    before_getconf = "\tif getConfig && configCh != nil {\n"
    replace_once(before_getconf,
                 "\tstopDTLS := context.AfterFunc(sessCtx, func() { _ = pipeB.Close() })\n"
                 "\tdefer stopDTLS()\n\n" + before_getconf)

    # A failed ping must cancel the reader/writer too, not leave a registered
    # worker blocked in proxyWg.Wait while the keepalive goroutine has exited.
    marker = "// DTLS Keepalive + periodic GETCONF"
    head, tail = source.split(marker, 1)
    old = "\tgo func() {\n\t\tdefer proxyWg.Done()\n"
    if tail.count(old) < 1:
        raise ValueError("Shared WDTT keepalive changed")
    tail = tail.replace(old, old + "\t\tdefer sessCancel()\n", 1)
    for payload, label in [("ping", "Keepalive"), ("getconfPayload(localPort, deviceID, password)", "Access-check")]:
        old = f"\t\t\t\tif _, err := dtlsConn.Write({payload}); err != nil {{\n\t\t\t\t\treturn\n"
        if tail.count(old) != 1:
            raise ValueError("Shared WDTT keepalive write changed")
        tail = tail.replace(old, old.replace("\t\t\t\t\treturn\n",
            "\t\t\t\t\tif sessCtx.Err() != nil { return }\n"
            f'\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] {label}: запись не прошла, канал закрывается", sessionID)\n'
            "\t\t\t\t\treturn\n"), 1)
    source = head + marker + tail
    # Closing a session closes its pipe while a dispatcher write may be in
    # flight. That cancellation is not a new transport failure (Reader already
    # makes the same distinction in the shared client).
    replace_once("\t\t\t\tif writeErr != nil {\n",
                 "\t\t\t\tif writeErr != nil {\n\t\t\t\t\tif sessCtx.Err() != nil { return }\n")

    # Pion reports failed allocation/permission renewal through its logger, not
    # ReadFrom/WriteTo. Keep that lifecycle signal instead of discarding it.
    context_setup = "\tsessCtx, sessCancel := context.WithCancel(ctx)\n\tdefer sessCancel()\n\n"
    replace_once(context_setup, "")
    marker = "\tturnConn, endpoint, err := dialUDPTURN(ctx, creds.TurnURLs, sessionID, tp)\n"
    replace_once(marker, context_setup + "\tactivity := &iosSessionActivity{}\n" + marker)
    replace_once("\tstopTransport := context.AfterFunc(ctx, func() { _ = turnConn.Close() })",
                 "\tstopTransport := context.AfterFunc(sessCtx, func() { _ = turnConn.Close() })")
    replace_once("\tdefer tc.Close()\n", "\tdefer tc.Close()\n"
                 "\tstopTransactions := context.AfterFunc(sessCtx, tc.Close)\n\tdefer stopTransactions()\n")
    replace_once("\td.Register(slot)\n\tdefer d.Unregister(slot)\n",
                 "\td.Register(slot)\n"
                 "\tactivity.markReady()\n"
                 "\tvar removeOnce sync.Once\n"
                 "\tremoveSlot := func() { removeOnce.Do(func() { d.Unregister(slot) }) }\n"
                 "\tstopSlot := context.AfterFunc(sessCtx, removeSlot)\n"
                 "\tdefer stopSlot()\n\tdefer removeSlot()\n")
    begin = source.index("\tgo func() {", source.index("// Keepalive goroutine (TURN binding request)"))
    end = source.index("\n\t// Relay ↔ Pipe proxy", begin)
    source = source[:begin] + '''\tgo func() {
\t\tdefer sessionWg.Done()
\t\trunIOSBindingChecks(sessCtx, sessionID, func() (net.Addr, error) {
\t\t\tstarted := time.Now()
\t\t\taddress, probeErr := tc.SendBindingRequest()
\t\t\tif quality != nil { quality.observe(time.Since(started), probeErr, time.Now()) }
\t\t\treturn address, probeErr
\t\t}, sessCancel, activity)
\t}()
''' + source[end:]
    replace_once("\t\tLoggerFactory:          &NullLoggerFactory{},",
                 "\t\tLoggerFactory:          &iosTURNLoggerFactory{ctx: sessCtx, cancel: sessCancel, sessionID: sessionID},")
    replace_once("\t\t\tkind, ctrlErr := ClassifyControlPayload(pkt[:n])\n",
                 "\t\t\tactivity.markReceived()\n\t\t\tkind, ctrlErr := ClassifyControlPayload(pkt[:n])\n")
    return source


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(adapt(Path(sys.argv[1]).read_text(encoding="utf-8")), encoding="utf-8")
