// DMCombat's hit-window table (see dm_hitwindows.h). Timings marked FROM_DATA are Dark Messiah's and come from
// dmcombat_dm.bin at startup; the behead and impale windows are DMCombat's own (tuned to the blade's sweep).
#include "dm_hitwindows.h"
#include "dm_data.h"
#include "dm_log.h"

DMHitWindow g_dmHitWindows[] = {
	{"fastattack_sword_noshield_A", 0, FROM_DATA, FROM_DATA, 0.75f, 0, 0, 0, 0.5f, 0},
	{"fastattack_sword_noshield_B", 0, FROM_DATA, FROM_DATA, 0.75f, 0, 0, 0, 0.5f, 0},
	{"fastattack_sword_noshield_C", 0, FROM_DATA, FROM_DATA, 0.75f, 0, 0, 0, 0.5f, 0},
	{"fastattack_sword_noshield_D", 0, FROM_DATA, FROM_DATA, 0.75f, 0, 0, 0, 0.5f, 0},
	{"fastattack_sword_noshield_E", 0, FROM_DATA, FROM_DATA, 0.75f, 0, 0, 0, 0.5f, 0},
	{"bigslash_sword_noshield_out", 0, FROM_DATA, FROM_DATA, 2.5f, 0, 2, 1, 3.0f, 0},
	{"bigslash_sword_noshield_L_out", 0, FROM_DATA, FROM_DATA, 2.5f, 1, 2, 1, 3.0f, 0},
	{"bigslash_sword_noshield_R_out", 0, FROM_DATA, FROM_DATA, 2.5f, 3, 2, 1, 1.0f, 0},
	{"bigslash_sword_noshield_B_out", 0, FROM_DATA, FROM_DATA, 2.5f, 0, 2, 2, 3.0f, 0},
	{"bigslash_sword_noshield_T_out", 0, FROM_DATA, FROM_DATA, 2.5f, 0, 2, 2, 3.0f, 0},
	// adrenaline moves: the huge combo's two strikes
	{"combo_sword_huge_noshield", 0, FROM_DATA, FROM_DATA, 7.5f, 1, 2, 1, 0.0f, 0},
	{"combo_sword_huge_noshield", 1, FROM_DATA, FROM_DATA, 7.5f, 3, 2, 1, 0.0f, 0},
	// left adrenaline move: guaranteed blow on the locked enemy at the window start + a cleaving sweep through the swing
	{"behead_sword_noshield_out", 0, 0.320f, 0.560f, 7.5f, 1, 2, 1, 0.0f, 1},
	// stab adrenaline move: impale with stab reach; idle/out only hold and pull out
	{"Impal_sword_noshield_in", 0, 0.450f, 1.000f, 7.5f, 0, 2, 3, 0.0f, 1},
};
const int g_numDMHitWindows = sizeof(g_dmHitWindows) / sizeof(g_dmHitWindows[0]);

int DMHitWindowsResolve()
{
	int ok = 0;
	for (int i = 0; i < g_numDMHitWindows; i++) {
		DMHitWindow &w = g_dmHitWindows[i];
		if (w.open == FROM_DATA) {
			float o, c, impact;
			if (DMDataWindow(w.move, w.index, &o, &c, &impact)) {
				w.open = o;
				w.close = c;
			} else {
				w.open = w.close = -2.0f;  // never matches a cycle in 0..1
				DMLog("data", "no hit window %d for %s in dmcombat_dm.bin - that move won't hit", w.index, w.move);
				continue;
			}
		}
		ok++;
	}
	DMLog("data", "hit windows: %d of %d usable", ok, g_numDMHitWindows);
	return ok;
}
