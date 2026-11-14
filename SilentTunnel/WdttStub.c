#include <string.h>

static const char *kStubError = "Native engine is not linked";

int wdtt_engine_linked(void) { return 0; }

char *wdtt_last_error(void) { return strdup(kStubError); }
long long wdtt_start_epoch(void) { return 0; }
void wdtt_interrupt_start(void) {}

int wdtt_start(
    const char *serverIP,
    int serverPort,
    const char *hashesCSV,
    const char *password,
    const char *deviceID,
    int workers,
    int mtu,
    const char *workDir,
    long long epoch
) {
    (void)serverIP; (void)serverPort; (void)hashesCSV; (void)password;
    (void)deviceID; (void)workers; (void)mtu; (void)workDir; (void)epoch;
    return 1;
}

char *wdtt_assigned_address(void) { return 0; }
void wdtt_probe(void) {}
void wdtt_reset_direct(void) {}
long long wdtt_handshake_stamp(void) { return 0; }
long long wdtt_received_bytes(void) { return 0; }
void wdtt_expand_workers(void) {}

void wdtt_stop(void) {}

void wdtt_set_output(void (*cb)(const unsigned char *data, int len)) { (void)cb; }

void wdtt_set_journal(void (*cb)(const char *message, int level)) { (void)cb; }

void wdtt_input(const unsigned char *data, int len) { (void)data; (void)len; }

int wdtt_set_russian_policy(const char *json) { (void)json; return 1; }
