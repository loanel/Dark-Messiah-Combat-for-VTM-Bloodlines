// State shared between the client-side sword (dm_viewmodel.cpp) and the server-side hits (dm_server.cpp).
// Bloodlines runs client and server in one process and one thread, so plain globals are enough.
#pragma once

struct DMSwordShared {
	bool active;            // katana drawn and the DM sword is driving the viewmodel
	const char *move;       // current DM sequence name (dmcombat_dm.bin), NULL when none
	float cycle;            // 0..1 through the current sequence
	int swingId;            // increments on every new move; the server hits each victim once per swing
	float eye[3];           // world eye position used for the sword this frame
	float eyeFwd[3];        // world view direction this frame
	float hilt[3], mid[3], tip[3];  // world positions along the katana this frame
	bool parrying;          // in the DM parry (client state machine): enemy melee hits on the player are blocked
	int parriedHits;        // incremented by the server on every blocked hit; the client plays a parry impact
	float parryAge;         // seconds since the guard was raised (timing: a fresh guard = perfect parry)
	float parryWindow;      // dmcombat.ini parry_window: a block within this many seconds of raising the guard is free
	int parryBloodCost;
	float reach[4];  // fast, power slash, power stab, impale (adrenaline stab)
	// adrenaline (server updates, client reads/spends): requirement = base - perMelee * Melee skill, at least min
	float adrenaline, adrenalineNeeded;
	float adrenalineBase, adrenalinePerMelee, adrenalineMin, adrenalineGain, adrenalineDecay, finisherRange;
	int melee;
	bool finisherReady;     // adrenaline full and an enemy in front within finisherRange (server, per tick)         // dmcombat.ini reach_fast / reach_power / reach_stab: extra units past the blade tip     // dmcombat.ini parry_blood: blood points per mistimed block (0 = free)
	int weapon;             // held melee weapon (dm_weapons.h index), -1 = none
	char character[64];     // client: player model without the outfit, e.g. "toreador_male" (per-character arm model)
};

extern DMSwordShared g_dmSword;
