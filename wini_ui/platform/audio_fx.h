/* audio_fx — small, calm audio cues (spec §Sound).
 *
 * The device is voice-first, so UI sound is minimal: a soft chime marks the two
 * moments the screen alone can't convey — the mic opening, and a correct answer.
 * Short, low-amplitude sine tones with a gentle envelope (no sharp attack, no
 * melody). Synthesised through SDL2 (already linked); if no audio device opens
 * (headless / no ALSA sink), every cue is a clean no-op. */
#ifndef WINI_PLATFORM_AUDIO_FX_H
#define WINI_PLATFORM_AUDIO_FX_H

typedef enum {
    WINI_CUE_LISTEN,      /* mic opened — a single soft note   */
    WINI_CUE_CORRECT,     /* gentle affirmative                */
    WINI_CUE_CELEBRATE,   /* a touch warmer, for stage complete */
} wini_cue_t;

/* Open the audio device (best-effort). Safe to call once at startup. */
void wini_audio_init(void);

/* Play a cue (no-op if audio is unavailable). */
void wini_audio_cue(wini_cue_t cue);

#endif /* WINI_PLATFORM_AUDIO_FX_H */
