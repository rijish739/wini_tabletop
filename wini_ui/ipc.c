/* Mode-channel IPC client — see ipc.h.
 *
 * One TCP connection to the wini_client mode channel (default 127.0.0.1:8140),
 * used both ways: the UI writes mode_selected lines, and a background reader
 * thread reads client->UI command lines into a small queue that the LVGL thread
 * drains via ipc_poll_line(). The reader owns the socket lifecycle (connect,
 * reconnect with backoff) so a tap never blocks and a dropped client is picked
 * back up automatically.
 *
 * Threading: the reader thread only touches the socket + the line queue (guarded
 * by a mutex); it never calls LVGL. ipc_send_mode() writes under the same mutex.
 *
 * This whole file is the seam that disappears on the ESP32-P4: there the UI and
 * the client are one firmware, so these calls become direct in-process calls. */
#include "ipc.h"

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/select.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

#define IPC_Q_SLOTS 64
#define IPC_LINE_MAX 512

static char g_host[64] = "127.0.0.1";
static int  g_port = 8140;

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static int  g_fd = -1;             /* shared connection (owned by the reader)   */
static int  g_started = 0;

/* Inbound line ring buffer (reader pushes, LVGL thread pops). */
static char g_q[IPC_Q_SLOTS][IPC_LINE_MAX];
static int  g_head = 0, g_tail = 0;   /* g_tail == g_head => empty */

void ipc_init(const char *host, int port)
{
    if (host) {
        strncpy(g_host, host, sizeof(g_host) - 1);
        g_host[sizeof(g_host) - 1] = '\0';
    }
    g_port = port;
}

/* ---- connection ----------------------------------------------------------- */

static int connect_with_timeout(int ms)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)g_port);
    if (inet_pton(AF_INET, g_host, &addr.sin_addr) != 1) { close(fd); return -1; }

    int fl = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, fl | O_NONBLOCK);

    int rc = connect(fd, (struct sockaddr *)&addr, sizeof(addr));
    if (rc != 0) {
        if (errno != EINPROGRESS) { close(fd); return -1; }
        fd_set wf;
        FD_ZERO(&wf);
        FD_SET(fd, &wf);
        struct timeval tv = { ms / 1000, (ms % 1000) * 1000 };
        if (select(fd + 1, NULL, &wf, NULL, &tv) <= 0) { close(fd); return -1; }
        int err = 0;
        socklen_t len = sizeof(err);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) < 0 || err != 0) {
            close(fd);
            return -1;
        }
    }
    fcntl(fd, F_SETFL, fl);   /* back to blocking for the reader */
    return fd;
}

static int send_all(int fd, const char *buf, size_t n)
{
    size_t off = 0;
    while (off < n) {
        ssize_t w = send(fd, buf + off, n - off, MSG_NOSIGNAL);
        if (w <= 0) {
            if (w < 0 && errno == EINTR) continue;
            return -1;
        }
        off += (size_t)w;
    }
    return 0;
}

/* ---- inbound queue -------------------------------------------------------- */

static void queue_push(const char *line)
{
    pthread_mutex_lock(&g_lock);
    int next = (g_head + 1) % IPC_Q_SLOTS;
    if (next != g_tail) {                 /* drop on overflow, never block */
        strncpy(g_q[g_head], line, IPC_LINE_MAX - 1);
        g_q[g_head][IPC_LINE_MAX - 1] = '\0';
        g_head = next;
    }
    pthread_mutex_unlock(&g_lock);
}

int ipc_poll_line(char *out, int cap)
{
    int got = 0;
    pthread_mutex_lock(&g_lock);
    if (g_tail != g_head) {
        strncpy(out, g_q[g_tail], (size_t)cap - 1);
        out[cap - 1] = '\0';
        g_tail = (g_tail + 1) % IPC_Q_SLOTS;
        got = 1;
    }
    pthread_mutex_unlock(&g_lock);
    return got;
}

/* ---- reader thread -------------------------------------------------------- */

static void *reader_main(void *arg)
{
    (void)arg;
    char acc[IPC_LINE_MAX * 2];
    size_t acc_len = 0;

    for (;;) {
        int fd;
        pthread_mutex_lock(&g_lock);
        fd = g_fd;
        pthread_mutex_unlock(&g_lock);

        if (fd < 0) {
            fd = connect_with_timeout(400);
            if (fd < 0) { usleep(1000 * 1000); continue; }   /* retry ~1 Hz */
            pthread_mutex_lock(&g_lock);
            g_fd = fd;
            pthread_mutex_unlock(&g_lock);
            acc_len = 0;
        }

        char buf[512];
        ssize_t r = recv(fd, buf, sizeof(buf), 0);
        if (r <= 0) {
            if (r < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            pthread_mutex_lock(&g_lock);
            if (g_fd == fd) { close(g_fd); g_fd = -1; }
            pthread_mutex_unlock(&g_lock);
            continue;   /* reconnect */
        }

        for (ssize_t i = 0; i < r; i++) {
            char c = buf[i];
            if (c == '\n') {
                acc[acc_len] = '\0';
                if (acc_len > 0) queue_push(acc);
                acc_len = 0;
            } else if (acc_len < sizeof(acc) - 1) {
                acc[acc_len++] = c;
            }   /* else: overlong line, keep scanning for the newline */
        }
    }
    return NULL;
}

void ipc_start(void)
{
    if (g_started) return;
    g_started = 1;
    pthread_t t;
    if (pthread_create(&t, NULL, reader_main, NULL) == 0)
        pthread_detach(t);
}

/* ---- outbound ------------------------------------------------------------- */

static int ipc_send_line(const char *line, int n);

int ipc_send_mode(const char *mode)
{
    char line[128];
    int n = snprintf(line, sizeof(line),
                     "{\"event\":\"mode_selected\",\"mode\":\"%s\"}\n", mode);
    if (n <= 0 || (size_t)n >= sizeof(line)) return -1;
    return ipc_send_line(line, n);
}

int ipc_send_pause(int on)
{
    char line[64];
    int n = snprintf(line, sizeof(line),
                     "{\"event\":\"pause\",\"on\":%d}\n", on ? 1 : 0);
    if (n <= 0 || (size_t)n >= sizeof(line)) return -1;
    return ipc_send_line(line, n);
}

static int ipc_send_line(const char *line, int n)
{
    for (int attempt = 0; attempt < 2; attempt++) {
        pthread_mutex_lock(&g_lock);
        if (g_fd < 0) g_fd = connect_with_timeout(400);
        int fd = g_fd;
        int rc = (fd >= 0) ? send_all(fd, line, (size_t)n) : -1;
        if (rc != 0 && fd >= 0) { close(g_fd); g_fd = -1; }   /* stale: retry */
        pthread_mutex_unlock(&g_lock);

        if (fd < 0) {
            fprintf(stderr, "[wini_ui] mode channel connect failed (%s:%d)\n",
                    g_host, g_port);
            return -1;
        }
        if (rc == 0) return 0;
    }
    fprintf(stderr, "[wini_ui] mode channel send failed\n");
    return -1;
}
