/* brightness — see brightness.h. */
#include "platform/brightness.h"

#include <stdio.h>
#include <string.h>
#include <dirent.h>
#include <unistd.h>

#define SYS_BL "/sys/class/backlight"

static char g_node[256];   /* .../brightness path, "" if none */
static int  g_max = 0;
static int  g_cur_pct = -1;

static int read_int(const char *path, int *out)
{
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int ok = (fscanf(f, "%d", out) == 1);
    fclose(f);
    return ok;
}

static int write_int(const char *path, int v)
{
    FILE *f = fopen(path, "w");
    if (!f) return 0;
    int ok = (fprintf(f, "%d", v) > 0);
    fclose(f);
    return ok;
}

/* Find the first backlight device under /sys/class/backlight and cache its
 * brightness path + max_brightness. */
static void discover(void)
{
    g_node[0] = '\0';
    g_max = 0;

    DIR *d = opendir(SYS_BL);
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        char mp[256];
        snprintf(mp, sizeof(mp), SYS_BL "/%s/max_brightness", e->d_name);
        int mx = 0;
        if (read_int(mp, &mx) && mx > 0) {
            snprintf(g_node, sizeof(g_node), SYS_BL "/%s/brightness", e->d_name);
            g_max = mx;
            break;
        }
    }
    closedir(d);
}

static int pct_to_raw(int pct)
{
    if (pct < 0) pct = 0;
    if (pct > WINI_BRIGHTNESS_CAP) pct = WINI_BRIGHTNESS_CAP;
    return (g_max * pct + 50) / 100;   /* rounded */
}

void wini_brightness_init(void)
{
    discover();
    if (!g_node[0]) {
        fprintf(stderr, "[brightness] no backlight node under %s "
                        "(brightness control disabled)\n", SYS_BL);
        return;
    }
    /* Probe writability once; if it fails, disable quietly. */
    if (!write_int(g_node, pct_to_raw(WINI_BRIGHTNESS_CAP))) {
        fprintf(stderr, "[brightness] %s not writable "
                        "(need udev rule or root; control disabled)\n", g_node);
        g_node[0] = '\0';
        return;
    }
    g_cur_pct = WINI_BRIGHTNESS_CAP;
    fprintf(stderr, "[brightness] %s max=%d, resting at %d%%\n",
            g_node, g_max, WINI_BRIGHTNESS_CAP);
}

void wini_brightness_set_percent(int percent)
{
    if (!g_node[0]) return;
    if (percent < 0) percent = 0;
    if (percent > WINI_BRIGHTNESS_CAP) percent = WINI_BRIGHTNESS_CAP;

    int from = (g_cur_pct < 0) ? percent : g_cur_pct;
    int steps = 12;
    for (int i = 1; i <= steps; i++) {
        int p = from + (percent - from) * i / steps;
        write_int(g_node, pct_to_raw(p));
        usleep(12 * 1000);   /* ~150 ms total ramp */
    }
    g_cur_pct = percent;
}
