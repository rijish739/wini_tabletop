/* audio_fx — see audio_fx.h. */
#include "platform/audio_fx.h"

#include <SDL2/SDL.h>
#include <math.h>
#include <stdio.h>

#define SR       44100
#define AMP      0.12f      /* low — a cue, not an alert */

static SDL_AudioDeviceID g_dev = 0;

void wini_audio_init(void)
{
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) {
        fprintf(stderr, "[audio] no audio subsystem (%s) — cues disabled\n",
                SDL_GetError());
        return;
    }
    SDL_AudioSpec want, have;
    SDL_zero(want);
    want.freq = SR;
    want.format = AUDIO_S16SYS;
    want.channels = 1;
    want.samples = 1024;
    g_dev = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (g_dev == 0) {
        fprintf(stderr, "[audio] no output device (%s) — cues disabled\n",
                SDL_GetError());
        return;
    }
    SDL_PauseAudioDevice(g_dev, 0);
    fprintf(stderr, "[audio] ready\n");
}

/* Queue one sine burst with a raised-cosine envelope (soft in and out). */
static void tone(float freq, int ms)
{
    if (!g_dev) return;
    int n = SR * ms / 1000;
    Sint16 *buf = SDL_malloc((size_t)n * sizeof(Sint16));
    if (!buf) return;
    for (int i = 0; i < n; i++) {
        float t = (float)i / SR;
        float env = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * i / (n - 1))); /* 0..1..0 */
        float s = sinf(2.0f * (float)M_PI * freq * t) * env * AMP;
        buf[i] = (Sint16)(s * 32767.0f);
    }
    SDL_QueueAudio(g_dev, buf, (Uint32)n * sizeof(Sint16));
    SDL_free(buf);
}

void wini_audio_cue(wini_cue_t cue)
{
    if (!g_dev) return;
    switch (cue) {
    case WINI_CUE_LISTEN:                       /* one soft mid note */
        tone(523.25f, 140);                     /* C5 */
        break;
    case WINI_CUE_CORRECT:                       /* gentle rising third */
        tone(523.25f, 120);                     /* C5 */
        tone(659.25f, 160);                     /* E5 */
        break;
    case WINI_CUE_CELEBRATE:                      /* warm major triad */
        tone(523.25f, 120);                     /* C5 */
        tone(659.25f, 120);                     /* E5 */
        tone(783.99f, 200);                     /* G5 */
        break;
    }
}
