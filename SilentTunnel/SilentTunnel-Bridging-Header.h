#ifndef SilentTunnel_Bridging_Header_h
#define SilentTunnel_Bridging_Header_h

int wdtt_engine_linked(void);
const char *wdtt_last_error(void);
int wdtt_start(
    const char *serverIP,
    int serverPort,
    const char *hashesCSV,
    const char *password,
    const char *deviceID,
    int workers,
    const char *privB64,
    const char *pubB64,
    int mtu,
    const char *workDir
);
int wdtt_set_russian_policy(const char *json);
void wdtt_stop(void);
void wdtt_set_output(void (*cb)(const unsigned char *data, int len));
void wdtt_input(const unsigned char *data, int len);

#endif
