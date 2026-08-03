/* Mode-channel IPC client — the device seam to the Python voice client
 * (wini_client) over a local TCP socket. Newline-delimited JSON, bidirectional
 * on one connection (see wini_ui/README.md for the contract):
 *
 *   UI  -> client :  {"event":"mode_selected","mode":"EXPLAIN|PRACTICE|TEST"}
 *   client -> UI  :  {"cmd":"...", ...}   (drives the FSM — parsed in app/)
 *
 * On the ESP32-P4 the UI and the client are one firmware and this socket
 * collapses to direct calls. */
#ifndef WINI_IPC_H
#define WINI_IPC_H

/* Store host/port. No connection is opened here. */
void ipc_init(const char *host, int port);

/* Start the background reader thread. It owns the connection: it connects (and
 * reconnects, ~1 s backoff) and queues every inbound client->UI line for
 * ipc_poll_line(). Safe to call once after ipc_init(). */
void ipc_start(void);

/* Send {"event":"mode_selected","mode":"<mode>"}\n on the shared connection.
 * Returns 0 on success, -1 if the channel could not be reached (the UI stays
 * usable either way). */
int ipc_send_mode(const char *mode);

/* Send {"event":"pause","on":0|1}\n — the mic-mute toggle. The voice client
 * gates its listen/turn loop on it (pause_button.c). Same return contract. */
int ipc_send_pause(int on);

/* Pop one queued inbound line (without the trailing newline) into `out`. Returns
 * 1 if a line was copied, 0 if the queue is empty. Call from the LVGL thread
 * (the reader thread never touches LVGL). */
int ipc_poll_line(char *out, int cap);

#endif /* WINI_IPC_H */
