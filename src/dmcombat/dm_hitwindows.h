// Hit windows per move: when a swing can hit, and what a hit does. The timings of Dark Messiah's own windows come from
// its animation events in dmcombat_dm.bin (DMHitWindowsResolve); everything else here is DMCombat's gameplay tuning.
#pragma once

// open/close: cycles (0..1) of the sequence; FROM_DATA = Dark Messiah's window number <index> for that move.
// hitPow multiplies Bloodlines' own hit damage: fast 0.75 (user's choice), power 2.5 (raised so a power cycle reaches
// ~75-80% of the fast chain's DPS). Adrenaline moves (user): 7.5x; the huge combo strikes twice; the impale has the
// longest reach (class 3, reach_impale).
// knockDir/knockPower fill Bloodlines' melee attack descriptor: dir 0..3 rotates the push (0 straight away,
// 1 = +270 deg, 2 = +180, 3 = +90 relative to attacker->victim); power 2 = always knock back, 0 = flinch unless worn down.
// reach: 0 = fast attack, 1 = power slash, 2 = power stab (thrusts B/T), 3 = impale; each class gets its own extra reach
// past the visible blade tip (dmcombat.ini reach_fast / reach_power / reach_stab / reach_impale).
// adrenaline: gained per landed hit. fatal: 1 = a guaranteed blow on the locked target when the window opens, then the
// normal sweep. A move may have several windows (huge combo: two strikes); each can hit the same enemy again.
static const float FROM_DATA = -1.0f;

struct DMHitWindow {
	const char *move;
	int index;           // which of the move's windows in the data (FROM_DATA entries)
	float open, close;   // cycles; filled from the data for FROM_DATA entries (-2 = disabled: not in the data)
	float hitPow;
	char knockDir, knockPower, reach;
	float adrenaline;
	char fatal;
};

extern DMHitWindow g_dmHitWindows[];
extern const int g_numDMHitWindows;

// Fills the FROM_DATA timings from dmcombat_dm.bin (after DMDataLoad). Returns how many windows are usable.
int DMHitWindowsResolve();
