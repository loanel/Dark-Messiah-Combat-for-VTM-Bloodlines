// Reads <game>\dmcombat_dm.bin (layout: tools/dm_data.py) into DMPath tables. Every count and size is checked against
// the file length before use: a truncated or foreign file is rejected, never read past.
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "dm_data.h"
#include "dm_log.h"

const DMPath *g_dmPaths;
int g_numDMPaths;

struct DMWindowRec { char name[64]; unsigned index; float open, close, impact; };
static DMWindowRec *g_windows;
static int g_numWindows;
static int g_loaded;  // 0 = not tried, 1 = ok, -1 = failed

static bool Fail(const char *why)
{
	DMLog("data", "dmcombat_dm.bin %s - DMCombat stays off (build it: tools/gen_sword_paths.py, or run the installer)", why);
	g_loaded = -1;
	return false;
}

bool DMDataLoad()
{
	if (g_loaded) return g_loaded > 0;
	char path[MAX_PATH];
	GetModuleFileNameA(NULL, path, sizeof(path));
	char *sl = strrchr(path, '\\');
	if (sl) sl[1] = 0;
	strncat(path, "dmcombat_dm.bin", sizeof(path) - strlen(path) - 1);

	FILE *f = fopen(path, "rb");
	if (!f) return Fail("not found");
	fseek(f, 0, SEEK_END);
	long size = ftell(f);
	fseek(f, 0, SEEK_SET);
	if (size < 20 || size > 64 * 1024 * 1024) { fclose(f); return Fail("has a wrong size"); }
	BYTE *b = (BYTE *)malloc(size);  // kept for the whole session: the tables point into it
	if (!b || fread(b, 1, size, f) != (size_t)size) { fclose(f); return Fail("could not be read"); }
	fclose(f);

	unsigned version, nPaths, armBones, nWindows;
	if (memcmp(b, "DMCD", 4)) return Fail("is not a DMCombat data file");
	memcpy(&version, b + 4, 4);
	memcpy(&nPaths, b + 8, 4);
	memcpy(&armBones, b + 12, 4);
	memcpy(&nWindows, b + 16, 4);
	if (version != 1) return Fail("has an unknown version");
	if (armBones != DM_ARM_BONES || nPaths == 0 || nPaths > 1000 || nWindows > 1000) return Fail("has unexpected counts");

	DMPath *paths = (DMPath *)calloc(nPaths, sizeof(DMPath));
	long o = 20;
	for (unsigned i = 0; i < nPaths; i++) {
		if (o + 64 + 8 > size) return Fail("is truncated");
		char *name = (char *)(b + o);
		name[63] = 0;
		float fps;
		unsigned frames;
		memcpy(&fps, b + o + 64, 4);
		memcpy(&frames, b + o + 68, 4);
		o += 72;
		long bytes = (long)frames * 7 * 4 * (1 + DM_ARM_BONES);
		if (frames == 0 || frames > 100000 || fps <= 0 || o + bytes > size) return Fail("is truncated");
		paths[i].name = name;
		paths[i].fps = fps;
		paths[i].numFrames = (int)frames;
		paths[i].keys = (const DMPathKey *)(b + o);
		paths[i].arm = (const DMPathKey *)(b + o + (long)frames * sizeof(DMPathKey));
		o += bytes;
	}
	if (o + (long)nWindows * (long)sizeof(DMWindowRec) > size) return Fail("is truncated");
	g_windows = (DMWindowRec *)(b + o);
	g_numWindows = (int)nWindows;
	for (int i = 0; i < g_numWindows; i++) g_windows[i].name[63] = 0;
	g_dmPaths = paths;
	g_numDMPaths = (int)nPaths;
	g_loaded = 1;
	DMLog("data", "dmcombat_dm.bin: %d Dark Messiah sequences, %d hit windows", g_numDMPaths, g_numWindows);
	return true;
}

bool DMDataWindow(const char *move, int index, float *open, float *close, float *impact)
{
	for (int i = 0; i < g_numWindows; i++) {
		if (g_windows[i].index != (unsigned)index || strcmp(g_windows[i].name, move)) continue;
		*open = g_windows[i].open;
		*close = g_windows[i].close;
		*impact = g_windows[i].impact;
		return true;
	}
	return false;
}
