/* Lesson-channel IPC client — the UI's seam to alphabet_server.py.
 *
 * Newline-delimited JSON, bidirectional on ONE connection:
 *
 *   UI    -> brain :  {"event":"begin"|"touch"|"fed"|"next"|"again"|"quit", ...}
 *   brain -> UI    :  {"cmd":"ready"|"stage"|"status"|"feedback", ...}
 *
 * Same shape as wini_ui/ipc.h, deliberately: one contract to learn, and on the
 * ESP32-P4 (where UI and brain are one firmware) both collapse to direct calls.
 */
#ifndef ALPHA_IPC_H
#define ALPHA_IPC_H

/* Store host/port. No connection is opened here. */
void ipc_init(const char *host, int port);

/* Start the background reader thread. It owns the connection: connects,
 * reconnects with ~1 s backoff, and queues every inbound line for
 * ipc_poll_line(). Call once, after ipc_init(). */
void ipc_start(void);

/* Send one event object. `json` is the complete line WITHOUT the newline.
 * Returns 0 on success, -1 if the channel is down (the UI stays usable). */
int ipc_send(const char *json);

/* Convenience wrappers for the events the screens actually raise. */
int ipc_send_begin(const char *letter, const char *lang);   /* both may be NULL */
int ipc_send_touch(const char *letter);
int ipc_send_fed(void);
int ipc_send_next(void);
int ipc_send_again(void);

/* Pop one queued inbound line (newline stripped) into `out`. Returns 1 if a
 * line was copied, 0 if the queue is empty. Call from the LVGL thread only —
 * the reader thread never touches LVGL. */
int ipc_poll_line(char *out, int cap);

/* 1 once the channel has ever connected — drives the splash's "connecting" copy. */
int ipc_connected(void);

#endif /* ALPHA_IPC_H */
