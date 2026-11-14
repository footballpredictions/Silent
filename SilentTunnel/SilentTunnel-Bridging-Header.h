#ifndef SilentTunnel_Bridging_Header_h
#define SilentTunnel_Bridging_Header_h

int wdtt_engine_linked(void);
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
int wdtt_set_russian_policy(const char *json);
void wdtt_stop(void);
void wdtt_set_output(void (*cb)(const unsigned char *data, int len));
void wdtt_set_journal(void (*cb)(const char *message, int level));
void wdtt_input(const unsigned char *data, int len);

#endif
