// Dark Messiah data, loaded at startup from <game>\dmcombat_dm.bin (tools/dm_data.py format). The file is generated on
// the player's PC from their own Dark Messiah install (tools/gen_sword_paths.py); nothing from Dark Messiah is compiled
// into the plug-in. Without a valid file the plug-in installs no hooks and the game plays as vanilla Bloodlines.
#pragma once

struct DMPathKey { float pos[3]; float quat[4]; };  // eye space: x fwd, y left, z up
// arm: numFrames x DM_ARM_BONES keys = motion of each driven arm bone relative to Dark Messiah's reference pose
static const int DM_ARM_BONES = 7;
struct DMPath { const char *name; float fps; int numFrames; const DMPathKey *keys; const DMPathKey *arm; };

extern const DMPath *g_dmPaths;
extern int g_numDMPaths;

// Loads the file once (later calls return the first result).
bool DMDataLoad();
// Hit window <index> of <move> from the animation events (cycles 0..1); false when the data has none.
bool DMDataWindow(const char *move, int index, float *open, float *close, float *impact);
