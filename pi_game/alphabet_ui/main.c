/* Alphabet learning module — LVGL v9 + SDL2, portrait 600x1024.
 *
 * The renderer half of the module: alphabet_server.py owns the lesson state
 * machine and the voice, this process draws stages and reports touches. Boot
 * mirrors wini_ui/main.c because it targets the same panel and the same X11
 * stack — including the deliberate choice never to open the speaker here.
 *
 * Usage: alphabet_ui [--size W H] [--host H] [--port N]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <stdint.h>

#include "lvgl/lvgl.h"
#include <SDL2/SDL.h>

#include "theme/alpha_theme.h"
#include "screens/alpha_screens.h"
#include "ipc.h"

#define ALPHA_W   600
#define ALPHA_H  1024
#define IPC_HOST "127.0.0.1"
#define IPC_PORT 8160

static volatile sig_atomic_t g_quit = 0;
static void on_signal(int s) { (void)s; g_quit = 1; }

static uint32_t millis_cb(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint32_t)(t.tv_sec * 1000u + t.tv_nsec / 1000000u);
}

int main(int argc, char **argv)
{
    int w = ALPHA_W, h = ALPHA_H, port = IPC_PORT;
    const char *host = IPC_HOST;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--port") && i + 1 < argc) port = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--host") && i + 1 < argc) host = argv[++i];
        else if (!strcmp(argv[i], "--size") && i + 2 < argc) {
            w = atoi(argv[++i]);
            h = atoi(argv[++i]);
        }
    }
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    /* The reSpeaker Lite exposes ONE playback substream and the brain owns it
     * (it is what actually speaks). If SDL claims it for UI cues, Wini's VOICE
     * goes silent — the exact failure documented in
     * wini_client/SPEAKER_TROUBLESHOOTING.md. Default to the dummy driver. */
    if (!getenv("ALPHABET_UI_AUDIO"))
        setenv("SDL_AUDIODRIVER", "dummy", 0);

    lv_init();
    lv_tick_set_cb(millis_cb);

    lv_display_t *disp = lv_sdl_window_create(w, h);
    if (!disp) {
        fprintf(stderr, "[alphabet_ui] failed to create SDL window "
                        "(is DISPLAY set? is SDL2 installed?)\n");
        return 1;
    }
    lv_sdl_window_set_title(disp, "Wini — Letters");

    /* Borderless full-panel fill; FULLSCREEN_DESKTOP keeps the current mode
     * rather than risking a mode switch on the DSI panel. */
    SDL_Renderer *rend = (SDL_Renderer *)lv_sdl_window_get_renderer(disp);
    if (rend) {
        SDL_Window *win = SDL_RenderGetWindow(rend);
        if (win) SDL_SetWindowFullscreen(win, SDL_WINDOW_FULLSCREEN_DESKTOP);
    }
    lv_sdl_mouse_create();          /* the Goodix touch panel maps to the pointer */
    lv_sdl_mousewheel_create();
    lv_sdl_keyboard_create();

    alpha_theme_init();

    /* Open the lesson channel BEFORE building the UI: the brain sends {"cmd":
     * "ready"} the moment it accepts, and the reader thread queues it, so the
     * splash is correct on the very first frame. */
    ipc_init(host, port);
    ipc_start();

    alpha_ui_init(lv_screen_active());

    printf("[alphabet_ui] running (%dx%d), lesson channel %s:%d\n",
           w, h, host, port);
    fflush(stdout);

    while (!g_quit && !alpha_ui_should_quit()) {
        alpha_ui_poll();
        uint32_t idle = lv_timer_handler();
        if (idle > 20) idle = 20;
        usleep(idle * 1000);
    }

    /* The on-screen close control ends the whole package, not just the window:
     * left alone, the brain keeps running, keeps holding the reSpeaker, and the
     * background touch service never comes back. The launcher passes its own
     * stop script here (same contract as wini_ui's WINI_STOP_CMD). */
    const char *stop_cmd = getenv("ALPHABET_STOP_CMD");
    if (stop_cmd && stop_cmd[0]) {
        printf("[alphabet_ui] running stop command: %s\n", stop_cmd);
        fflush(stdout);
        if (system(stop_cmd) != 0)
            fprintf(stderr, "[alphabet_ui] stop command failed\n");
    }

    printf("[alphabet_ui] bye\n");
    return 0;
}
