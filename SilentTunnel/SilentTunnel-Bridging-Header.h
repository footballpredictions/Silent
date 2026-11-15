#ifndef SilentTunnel_Bridging_Header_h
#define SilentTunnel_Bridging_Header_h

int wdtt_engine_linked(void);
char *wdtt_engine_revision(void);
char *wdtt_last_error(void);
int wdtt_start(
    const char *serverIP,
    int serverPort,
    const char *hashesCSV,
    const char *password,
    const char *deviceID,
    int workers,
    int mtu,
    const char *workDir
);
char *wdtt_assigned_address(void);
int wdtt_has_handshake(void);
void wdtt_set_start_timeout(int seconds);
void wdtt_cancel_start(void);
void wdtt_network_event(int interfaceChanged);
void wdtt_expand_workers(void);
int wdtt_set_russian_policy(const char *json);
void wdtt_stop(void);
void wdtt_set_output(void (*cb)(const unsigned char *data, int len));
void wdtt_set_journal(void (*cb)(const char *message, int level));
void wdtt_input(const unsigned char *data, int len);

#endif
