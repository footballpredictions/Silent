#ifndef SilentTunnel_Bridging_Header_h
#define SilentTunnel_Bridging_Header_h

int wdtt_engine_linked(void);
char *wdtt_last_error(void);
long long wdtt_start_epoch(void);
void wdtt_interrupt_start(void);
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
);
char *wdtt_assigned_address(void);
void wdtt_probe(void);
void wdtt_reset_direct(void);
long long wdtt_handshake_stamp(void);
long long wdtt_received_bytes(void);
void wdtt_expand_workers(void);
int wdtt_set_russian_policy(const char *json);
void wdtt_stop(void);
void wdtt_set_output(void (*cb)(const unsigned char *data, int len));
void wdtt_set_journal(void (*cb)(const char *message, int level));
void wdtt_input(const unsigned char *data, int len);

#endif
