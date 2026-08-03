/* Wini touch UI — LVGL v9 + SDL2, portrait 600x1024.
 *
 * Stage 5 (event-driven): boots the paper theme, the persistent-screen manager,
 * and the app_state FSM. The mode picker sends the chosen mode to the brain over
 * the IPC mode channel; the brain drives the turn back (status / overlays / cards
 * / score) over the same channel, which the FSM applies each frame. Backlight is
 * capped low and audio cues are minimal (voice-first).
 *
 * Usage: wini_ui [--size W H] [--host H] [--port N]
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

#include "theme/wini_theme.h"
#include "screens/screen_mgr.h"
#include "app/app_state.h"
#include "widgets/pause_button.h"
#include "widgets/close_button.h"
#include "platform/brightness.h"
#include "platform/audio_fx.h"
#include "ipc.h"

#define WINI_W    600
#define WINI_H    1024
#define IPC_HOST  "127.0.0.1"
#define IPC_PORT  8140

static volatile sig_atomic_t g_quit = 0;
static void on_signal(int s) { (void)s; g_quit = 1; }

/* The on-screen close button's exit path (widgets/close_button.h): same flag as
 * SIGTERM, so there is exactly one way out of the loop. */
void wini_ui_request_quit(void) { g_quit = 1; }

static uint32_t millis_cb(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint32_t)(t.tv_sec * 1000u + t.tv_nsec / 1000000u);
}

int main(int argc, char **argv)
{
    int w = WINI_W, h = WINI_H, port = IPC_PORT;
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

    /* The reSpeaker Lite exposes ONE playback substream and the voice client
     * owns it exclusively (wini_client/SPEAKER_TROUBLESHOOTING.md): if SDL/
     * PipeWire claims it for the UI's beep cues, Wini's VOICE goes silent.
     * Default SDL audio to the dummy driver on every launch path; export
     * WINI_UI_AUDIO=1 (or set SDL_AUDIODRIVER yourself) to opt back in on
     * hardware with a separate audio device. */
    if (!getenv("WINI_UI_AUDIO"))
        setenv("SDL_AUDIODRIVER", "dummy", 0);

    lv_init();
    lv_tick_set_cb(millis_cb);

    lv_display_t *disp = lv_sdl_window_create(w, h);
    if (!disp) {
        fprintf(stderr, "[wini_ui] failed to create SDL window "
                        "(is DISPLAY set? is SDL2 installed?)\n");
        return 1;
    }
    lv_sdl_window_set_title(disp, "Wini");
    /* Borderless full-panel fill: covers the taskbar, no titlebar close button.
     * FULLSCREEN_DESKTOP keeps the current 600x1024 mode (no risky mode switch). */
    SDL_Renderer *sdl_rend = (SDL_Renderer *)lv_sdl_window_get_renderer(disp);
    if (sdl_rend) {
        SDL_Window *sdl_win = SDL_RenderGetWindow(sdl_rend);
        if (sdl_win) SDL_SetWindowFullscreen(sdl_win, SDL_WINDOW_FULLSCREEN_DESKTOP);
    }
    lv_sdl_mouse_create();        /* the Goodix touch panel maps to the X pointer */
    lv_sdl_mousewheel_create();
    lv_sdl_keyboard_create();

    wini_theme_init();

    /* Platform seams (best-effort — each no-ops if unavailable). */
    wini_brightness_init();
    wini_audio_init();

    /* Build every screen once (they self-register with the FSM) and open on the
     * splash; then create the global overlays. */
    wini_screen_mgr_init(lv_screen_active());
    wini_app_init();
    /* Floating mic-mute toggle + package close button, created LAST on the top
     * layer so they stay tappable above the loading/celebration overlays. */
    wini_pause_button_create(lv_layer_top());
    wini_close_button_create(lv_layer_top());

    /* Open the mode channel: outbound mode picks + inbound turn commands. */
    ipc_init(host, port);
    ipc_start();

    printf("[wini_ui] running (%dx%d) — Stage 5 FSM + IPC + brightness + audio\n",
           w, h);
    fflush(stdout);

    while (!g_quit) {
        wini_app_poll();                 /* apply queued inbound commands */
        uint32_t idle = lv_timer_handler();
        if (idle > 20) idle = 20;
        usleep(idle * 1000);
    }

    printf("[wini_ui] bye\n");
    return 0;
}
