// Server side: the katana stops doing Bloodlines' own swing; hits come from the DM sword instead.
//
// vampire.dll (UP build 0x41afafae, base 0x10000000), see MODLOG:
//   CWeaponMelee_Katana vftable 0x104d73e4. Slot 319 (+0x4fc) = per-frame think: attack held and timer ready ->
//   PrimaryAttack (+0x518, which starts the vanilla swing + lunge), else WeaponIdle (+0x504).
//   MeleeHit = slot 270 (+0x438), thiscall(trace_t *tr, void *attackSeq): rolls Bloodlines damage (dice, Potence,
//   MeleeDamageScalar), applies it and makes the victim flinch (attackSeq NULL) or knock back.
//   UTIL_TraceLine-like 0x101cd110: cdecl(CBaseEntity *ignore, Vector *start, Vector *end, int mask, trace_t *tr),
//   used with mask 0x202400b by the game's own direct MeleeHit caller (0x10374f40).
//   Weapon owner: 0x10252240 thiscall(weapon). trace_t: fraction +0x2c, m_pEnt +0x4c, size 84.
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <intrin.h>
#include <math.h>
#include "dm_log.h"
#include "dm_hook.h"
#include "dm_shared.h"
#include "dm_hitwindows.h"
#include "dm_weapons.h"

void DMWarnConsole(const char *msg);

DMSwordShared g_dmSword;
int g_dmServerHits = 1;  // set from dmcombat.ini ([viewmodel] hits=)

static const DWORD PREF_BASE = 0x10000000;
static const DWORD VT_KATANA = 0x104d73e4;
static const int SLOT_THINK = 319;
static const int OFS_WEAPONIDLE = 0x504;
static const int OFS_MELEEHIT = 0x438;
static const DWORD FN_TRACELINE = 0x101cd110;
static const DWORD FN_GETOWNER = 0x10252240;
static const int MASK_MELEE = 0x202400b;
static const int TR_FRACTION = 0x2c, TR_ENT = 0x4c, TR_SIZE = 84;
static const int ENT_CLASSNAME = 0x26c;   // string_t m_iClassname (used by the game's own debug output)
static const int ENT_COMBATCHAR = 0x9c;    // non-NULL for characters (MeleeHit reads the same field)

// Swing sound: CBaseCombatWeapon::WeaponSound = vtable +0x534 (0x10254450, thiscall, 6 args, ret 0x18). The vanilla melee
// swing (0x10346cd0) calls it as WeaponSound(0x15 = "swish" from the item's SoundData, 1, 0, 0, 0, 0).
static const int OFS_WEAPONSOUND = 0x534;
static const int SOUND_SWISH = 0x15;
typedef void(__thiscall *WeaponSound_t)(void *weapon, int type, int a, int b, int c, int d, int e);
static int g_soundSwing = -1;

typedef void(__thiscall *Think_t)(void *weapon);
typedef void(__thiscall *Idle_t)(void *weapon);
typedef void(__thiscall *MeleeHit_t)(void *weapon, void *tr, void *attackSeq);
typedef void *(__thiscall *GetOwner_t)(void *weapon);
typedef void(__cdecl *TraceLine_t)(void *ignore, const float *start, const float *end, int mask, void *tr);

static DWORD g_base;
static Think_t g_origThink;
static TraceLine_t TraceLine;
static GetOwner_t GetOwner;

// MeleeHit's attack descriptor normally points into the attacker's sequence data (melee attack info of the
// playing attack). We pass our own: zero except knock direction (+0xb8) and power (+0xba); zero knockback lists
// (+0x28 counts) make the victim use its default knockback for the side it was hit on.
static const int DESC_SIZE = 0x200, DESC_DIR = 0xb8, DESC_POWER = 0xba;
static BYTE g_desc[DESC_SIZE];

// Damage: MeleeHit stores the rolled damage in a static CTakeDamageInfo (0x1072cb10, damage +0x30) and then calls
// a one-line setter on it (call site 0x10257f42 -> 0x10005916, thiscall, 1 arg). We redirect that call and scale
// the damage there, only while our own MeleeHit call runs.
static const DWORD MELEEHIT_SETTER_CALL = 0x10257f42;
static const int DMGINFO_DAMAGE = 0x30;
typedef void(__thiscall *Setter_t)(void *info, int arg);
static Setter_t g_origSetter;
static float g_damageMul = 0;  // 0 = not inside our hit
float g_dmDamageScale = 1.0f;  // dmcombat.ini damage_scale
int g_dmSideKnock = 1;          // dmcombat.ini side_knock: 0 off, 1 normal, 2 big sideways knockback on L/R power attacks
int g_dmSideKnockFlip = 0;      // dmcombat.ini side_knock_flip

// Knockback animation (CBaseCombatCharacter::GetKnockbackActivity 0x103449b0): the attack descriptor lists knockback
// activities per hit side (side = victim vfunc +0x50c(direction), 0..3): count at desc+0x28+side*4, activities at
// desc+0x38+(k+side*4)*4; with none listed the victim's default for that side plays (always a stagger backwards, the
// victim being turned to face the hit). For the sideways power attacks we list the sideways knockbacks for every side.
// Activity ids (vampire.dll activity registration): ACT_KNOCKBACK_BIGHIGHLEFT 0x77, BIGHIGHRIGHT 0x78,
// NORMAL_HIGH_RIGHT 0x88, NORMAL_HIGH_LEFT 0x89.
static const int DESC_KNOCK_COUNT = 0x28, DESC_KNOCK_ACTS = 0x38;
static const int ACT_KB_BIG_LEFT = 0x77, ACT_KB_BIG_RIGHT = 0x78, ACT_KB_LEFT = 0x89, ACT_KB_RIGHT = 0x88;

static void __fastcall DamageSetterHook(void *info, void *, int arg)
{
	if (g_damageMul > 0) {
		float *dmg = (float *)((BYTE *)info + DMGINFO_DAMAGE);
		DMLog("hit", "  damage %.1f x %.2f = %.1f", *dmg, g_damageMul, *dmg * g_damageMul);
		*dmg *= g_damageMul;
	}
	g_origSetter(info, arg);
}

// Parry: CBaseCombatCharacter::WasMeleeBlocked (0x10345ab0, on the attacker) asks, when the victim is the player,
// FUN_10160e90 (thiscall on the player: current activity +0xff0 == 0x52 or 0x1154, the block activities). It's only
// reached through the jmp thunk 0x1000ebb5. WasMeleeBlocked has already checked that the attacker holds a melee weapon
// and that the victim faces the attacker. A block makes MeleeHit skip the damage, play the defender's block and the
// attacker's blocked (stagger) reaction.
static const DWORD PLAYERBLOCK_THUNK = 0x1000ebb5;
static const DWORD PLAYERBLOCK_FN = 0x10160e90;
typedef bool(__thiscall *PlayerBlock_t)(void *player);
static PlayerBlock_t g_origPlayerBlock;

static bool __fastcall PlayerBlockHook(void *player, void *)
{
	if (g_dmServerHits && g_dmSword.active && g_dmSword.parrying) {
		g_dmSword.parriedHits++;
		DMLog("parry", "blocked an enemy melee hit (%d)", g_dmSword.parriedHits);
		return true;
	}
	return g_origPlayerBlock(player);
}

// Dice: Bloodlines rolls a swing's dice when its own swing starts. CBaseCombatCharacter::MeleeRollAndSendNotice
// 0x10346910 (thiscall attacker, arg victim, ret 4) = CalcAndStoreMeleeDiceRolls 0x10346380 (attacker's lethality vs the
// victim's defence and soak, stored per victim) + tells the victim an attack is coming (victim +0x4f0: NPC may block or
// dodge). ForceMeleeReset 0x10346760 (thiscall attacker) clears the stored rolls. We roll on first contact per victim.
// Reaction tiers from the net result (rules.txt Melee_Reactions): <=-3 dodge+counter, <=-1 dodge, <=1 block,
// <=4 block stagger, else hit + knockback. DM power attacks break guards: we raise their net to at least POWER_NET.
static const DWORD FN_ROLLANDNOTICE = 0x10346910;
static const DWORD FN_MELEERESET = 0x10346760;
static const int POWER_NET = 5;
typedef void(__thiscall *RollNotice_t)(void *attacker, void *victim);
typedef void(__thiscall *MeleeReset_t)(void *attacker);

static int g_hitSwing = -1;
static void *g_hitVictims[8];
static int g_numHit;

// Records where a fault inside game code happened (module + offset) so the log says what MeleeHit needed.
static int CrashFilter(EXCEPTION_POINTERS *ep, const char *where)
{
	EXCEPTION_RECORD *er = ep->ExceptionRecord;
	DWORD addr = (DWORD)er->ExceptionAddress;
	HMODULE mod = NULL;
	char name[MAX_PATH] = "?";
	if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)addr, &mod))
		GetModuleFileNameA(mod, name, sizeof(name));
	const char *base = strrchr(name, '\\') ? strrchr(name, '\\') + 1 : name;
	DMLog("crash", "%s: code %08lx at %s+%lx (preferred %08lx), %s %08lx; eax %08lx ecx %08lx edx %08lx esi %08lx edi %08lx",
		where, er->ExceptionCode, base, addr - (DWORD)mod, addr - (DWORD)mod + PREF_BASE,
		er->NumberParameters > 1 ? (er->ExceptionInformation[0] ? "writing" : "reading") : "-",
		er->NumberParameters > 1 ? (DWORD)er->ExceptionInformation[1] : 0,
		ep->ContextRecord->Eax, ep->ContextRecord->Ecx, ep->ContextRecord->Edx, ep->ContextRecord->Esi, ep->ContextRecord->Edi);
	return EXCEPTION_EXECUTE_HANDLER;
}

static void *VFunc(void *obj, int ofs) { return *(void **)(*(BYTE **)obj + ofs); }

// dm_weapons.h index of a server melee weapon (by its class vtable), -1 for anything else.
static int MeleeIndex(void *weapon)
{
	DWORD vt = *(DWORD *)weapon;
	for (int i = 0; i < DM_NUM_WEAPONS; i++)
		if (vt == g_base + (g_dmWeapons[i].serverVt - PREF_BASE)) return i;
	return -1;
}

static const char *ClassName(void *ent)
{
	const char *s = *(const char **)((BYTE *)ent + ENT_CLASSNAME);
	return s && !IsBadStringPtrA(s, 64) ? s : "?";
}

// Parry outcome: a blocked hit still deals damage when the attacker's dice "went through" (FUN_10349650:
// attack successes +4 - soak +8 - defence successes +0xc > 0 -> "BLOCKED ON HIT"). The per-victim dice record comes from
// CBaseCombatCharacter::GetMeleeDiceRolls 0x10345980 (thiscall attacker, arg victim, ret 4; only via thunk 0x10009200).
// While the player parries an attacker in front, we lower the net result to -2: Bloodlines then treats it as a normal
// block (no damage, attacker's blocked reaction; SuccessesForAttackerBlocked -1 / Major -3 in rules.txt).
static const DWORD DICEROLLS_THUNK = 0x10009200;
static const DWORD DICEROLLS_FN = 0x10345980;
static const int ENT_PLAYER = 0xa8;        // non-NULL for the player (WasMeleeBlocked tests the same field)
static const int OFS_WORLDCENTER = 0x364;  // vtable: const Vector *WorldSpaceCenter()
static const int PARRY_NET = -2;
typedef int *(__thiscall *DiceRolls_t)(void *attacker, void *victim);
typedef const float *(__thiscall *WorldCenter_t)(void *ent);
static DiceRolls_t g_origDiceRolls;

static bool InFrontOfPlayer(void *attacker)
{
	const float *c = ((WorldCenter_t)VFunc(attacker, OFS_WORLDCENTER))(attacker);
	float d[3] = {c[0] - g_dmSword.eye[0], c[1] - g_dmSword.eye[1], c[2] - g_dmSword.eye[2]};
	return d[0] * g_dmSword.eyeFwd[0] + d[1] * g_dmSword.eyeFwd[1] + d[2] * g_dmSword.eyeFwd[2] > 0;
}

// Parry timing (user design): a guard raised within parry_window seconds before the hit = perfect parry: free, and the
// attacker gets the major stagger (net -4). A guard held longer still blocks but costs parry_blood blood points
// (DecBloodPool, net -2 = normal block). With no blood left the block only softens the hit (net +1: blocked on hit).
// The record is adjusted once per swing: later lookups see a net already at or below the target and are left alone.
static const int PERFECT_NET = -4, NOBLOOD_NET = 1;
static const DWORD FN_DECBLOODPOOL = 0x10338df0;  // CBaseCombatCharacter::DecBloodPool(bool), thiscall, ret 4
typedef bool(__thiscall *DecBlood_t)(void *ent, char flag);

static int *__fastcall DiceRollsHook(void *attacker, void *, void *victim)
{
	int *rec = g_origDiceRolls(attacker, victim);
	if (rec && victim && *(void **)((BYTE *)victim + ENT_PLAYER)) {  // diagnostics: enemy melee vs the player
		static int *lastRec;
		static int lastNet = 1000;
		int n = rec[1] - rec[2] - rec[3];
		if (rec != lastRec || n != lastNet)
			DMLog("taken", "%s attacks the player: net %d%s", ClassName(attacker), n, g_dmSword.parrying ? " (parrying)" : "");
		lastRec = rec;
		lastNet = n;
	}
	if (rec && victim && g_dmServerHits && g_dmSword.active && g_dmSword.parrying &&
		*(void **)((BYTE *)victim + ENT_PLAYER) && InFrontOfPlayer(attacker)) {
		int net = rec[1] - rec[2] - rec[3];
		if (net > PARRY_NET) {
			int target;
			const char *how;
			if (g_dmSword.parryAge <= g_dmSword.parryWindow) {
				target = PERFECT_NET;
				how = "perfect parry (free)";
			} else {
				int paid = 0;
				for (; paid < g_dmSword.parryBloodCost; paid++)
					if (!((DecBlood_t)(g_base + (FN_DECBLOODPOOL - PREF_BASE)))(victim, 0)) break;
				if (paid >= g_dmSword.parryBloodCost) {
					target = PARRY_NET;
					how = g_dmSword.parryBloodCost ? "late parry (blood paid)" : "late parry (free)";
				} else {
					target = NOBLOOD_NET;
					how = "late parry, no blood: hit softened";
				}
			}
			DMLog("parry", "%s: guard up %.2fs, %s's roll attack %d soak %d defence %d (net %d) -> net %d", how,
				g_dmSword.parryAge, ClassName(attacker), rec[1], rec[2], rec[3], net, target);
			rec[3] += net - target;
		}
	}
	return rec;
}

static void HookThunk(DWORD thunkVA, DWORD fnVA, void *hook, void **orig, const char *what)
{
	BYTE *thunk = (BYTE *)(g_base + (thunkVA - PREF_BASE));
	DWORD target = (DWORD)(thunk + 5) + *(DWORD *)(thunk + 1);
	if (thunk[0] != 0xE9 || target != g_base + (fnVA - PREF_BASE)) {
		DMLog("hook", "%s thunk mismatch (%02x -> %08lx) - not hooked", what, thunk[0], target);
		return;
	}
	*orig = (void *)target;
	DWORD old;
	VirtualProtect(thunk + 1, 4, PAGE_EXECUTE_READWRITE, &old);
	*(DWORD *)(thunk + 1) = (DWORD)hook - (DWORD)(thunk + 5);
	VirtualProtect(thunk + 1, 4, old, &old);
	FlushInstructionCache(GetCurrentProcess(), thunk, 5);
	DMLog("hook", "%s hooked at %p", what, thunk);
}

static const DMHitWindow *WindowFor(const char *move)
{
	if (!move) return NULL;
	for (int i = 0; i < g_numDMHitWindows; i++)
		if (!strcmp(g_dmHitWindows[i].move, move)) return &g_dmHitWindows[i];
	return NULL;
}

// Enemy defence: rolling on contact is too late for the victim's block/dodge notice, so NPCs never defended. At each new
// attack we roll for the one enemy the swing is aimed at, as Bloodlines' own swing does ("Swing found target").
// Server entity table: [0x10566458] -> entries of 12 bytes {?, CBaseEntity *ent, serial}, 0x2000 slots (handle & 0x1fff).
// Alive = vtable +0x278 (used by the melee range check CWeaponMelee slot 283 0x103ea6d0, range 150).
static const DWORD ENT_TABLE_PTR = 0x10566458;
static const int ENT_SLOTS = 0x2000, ENT_STRIDE = 12;
static const int OFS_ISALIVE = 0x278;
static const float AIM_CONE_COS = 0.82f;   // ~35 degrees around the view direction
typedef bool(__thiscall *IsAlive_t)(void *ent);

static void *FindSwingTarget(void *owner, float maxDist)
{
	BYTE *table = *(BYTE **)(g_base + (ENT_TABLE_PTR - PREF_BASE));
	if (!table) return NULL;
	void *best = NULL;
	float bestCos = AIM_CONE_COS;
	for (int i = 1; i < ENT_SLOTS; i++) {
		void *ent = *(void **)(table + i * ENT_STRIDE + 4);
		if (!ent || ent == owner || IsBadReadPtr(ent, 0xa0) || !*(void **)((BYTE *)ent + ENT_COMBATCHAR)) continue;
		if (*(void **)((BYTE *)ent + ENT_PLAYER)) continue;
		if (!((IsAlive_t)VFunc(ent, OFS_ISALIVE))(ent)) continue;
		const float *c = ((WorldCenter_t)VFunc(ent, OFS_WORLDCENTER))(ent);
		float d[3] = {c[0] - g_dmSword.eye[0], c[1] - g_dmSword.eye[1], c[2] - g_dmSword.eye[2]};
		float dist = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
		if (dist < 1 || dist > maxDist) continue;
		float cs = (d[0] * g_dmSword.eyeFwd[0] + d[1] * g_dmSword.eyeFwd[1] + d[2] * g_dmSword.eyeFwd[2]) / dist;
		if (cs > bestCos) {
			bestCos = cs;
			best = ent;
		}
	}
	return best;
}

// Adrenaline (DM): gained per landed hit; the requirement drops with the player's Melee skill (user design).
// Melee = character int at +0x125c (m_iVAbilitiesCurrent[v_ability_melee], Python datadesc 0x1031d049; base +0x1228).
static const int ENT_MELEE_CURRENT = 0x125c;

// (The "adrenaline full" sound is played by the client HUD as a 2D sound: weapon sound slots are only precached for the
// slots the game expects, so a "detonation" entry in the katana's SoundData never played.)
static void AddAdrenaline(void *weapon, float amount, const char *why)
{
	if (amount <= 0) return;
	float before = g_dmSword.adrenaline;
	g_dmSword.adrenaline += amount * g_dmSword.adrenalineGain;
	if (g_dmSword.adrenaline > g_dmSword.adrenalineNeeded) g_dmSword.adrenaline = g_dmSword.adrenalineNeeded;
	DMLog("adren", "%s: %.1f -> %.1f / %.0f", why, before, g_dmSword.adrenaline, g_dmSword.adrenalineNeeded);
	if (before < g_dmSword.adrenalineNeeded && g_dmSword.adrenaline >= g_dmSword.adrenalineNeeded)
	{
		DMLog("adren", "ADRENALINE FULL - next released power attack is an adrenaline move");
	}
}

// One hit on <ent> with a ready trace: dice (rolled now if the swing didn't), guard break for power moves, DM damage.
static void DoHit(void *weapon, void *owner, const DMHitWindow *w, BYTE *tr, void *ent)
{
	DMLog("hit", "%s cycle %.2f -> %s (%p) fraction %.2f knock dir %d power %d", g_dmSword.move, g_dmSword.cycle,
		ClassName(ent), ent, *(float *)(tr + TR_FRACTION), w->knockDir, w->knockPower);
	int *rec = g_origDiceRolls ? g_origDiceRolls(owner, ent) : NULL;
	if (!rec && g_origDiceRolls) {
		((RollNotice_t)(g_base + (FN_ROLLANDNOTICE - PREF_BASE)))(owner, ent);
		rec = g_origDiceRolls(owner, ent);
	}
	if (rec) {
		int net = rec[1] - rec[2] - rec[3];
		DMLog("hit", "  dice: attack %d soak %d defence %d (net %d)%s", rec[1], rec[2], rec[3], net,
			w->knockPower == 2 && net < POWER_NET ? " -> power attack breaks the guard" : "");
		if (w->knockPower == 2 && net < POWER_NET) rec[1] += POWER_NET - net;
	}
	// Impact effects: the client re-traces startpos -> endpos (x1.1) against the victim's hitboxes for the blood/dust
	// colour (client 0x1002d8f0 GetColorForSurface). Our trace ends on the bounding box, which is larger than the
	// hitboxes, so that re-trace hit nothing ("GetColorForSurface() ERROR: trace did not hit anything" in the console).
	// Ending the trace at the victim's centre makes the re-trace pass through the body.
	__try {
		const float *c = ((WorldCenter_t)VFunc(ent, OFS_WORLDCENTER))(ent);
		memcpy(tr + 12, c, 12);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
	}
	memset(g_desc, 0, sizeof(g_desc));
	g_desc[DESC_DIR] = w->knockDir;
	g_desc[DESC_POWER] = w->knockPower;
	if (g_dmSideKnock && w->knockPower == 2 && (w->knockDir == 1 || w->knockDir == 3)) {
		bool left = (w->knockDir == 1) != (g_dmSideKnockFlip != 0);  // left power attack: victim staggers to its left
		int act = g_dmSideKnock >= 2 ? (left ? ACT_KB_BIG_LEFT : ACT_KB_BIG_RIGHT) : (left ? ACT_KB_LEFT : ACT_KB_RIGHT);
		for (int side = 0; side < 4; side++) {
			*(int *)(g_desc + DESC_KNOCK_COUNT + side * 4) = 1;
			*(int *)(g_desc + DESC_KNOCK_ACTS + side * 16) = act;
		}
		DMLog("hit", "  sideways knockback act 0x%x", act);
	}
	g_damageMul = w->hitPow * g_dmDamageScale;  // x Bloodlines' own hit damage
	__try {
		((MeleeHit_t)VFunc(weapon, OFS_MELEEHIT))(weapon, tr, g_desc);
	} __finally {
		g_damageMul = 0;
	}
	AddAdrenaline(weapon, w->adrenaline, w->move);
}

static void TryHit(void *weapon, void *owner, const DMHitWindow *w, const float *from, const float *to)
{
	BYTE tr[TR_SIZE + 16];
	memset(tr, 0, sizeof(tr));
	TraceLine(owner, from, to, MASK_MELEE, tr);
	void *ent = *(void **)(tr + TR_ENT);
	if (!ent || ent == owner || *(float *)(tr + TR_FRACTION) >= 1.0f) return;
	if (!*(void **)((BYTE *)ent + ENT_COMBATCHAR)) return;  // world, props: no damage roll (yet)
	for (int i = 0; i < g_numHit; i++)
		if (g_hitVictims[i] == ent) return;
	if (g_numHit < 8) g_hitVictims[g_numHit++] = ent;
	DoHit(weapon, owner, w, tr, ent);
}

// Fatality: one guaranteed blow on the target locked when the finisher started (DMHL2: a lethal hit at the impact frame).
static void *g_finisherTarget;

static void FatalBlow(void *weapon, void *owner, const DMHitWindow *w)
{
	void *ent = g_finisherTarget;
	g_finisherTarget = NULL;
	if (!ent || IsBadReadPtr(ent, 0xa0) || !((IsAlive_t)VFunc(ent, OFS_ISALIVE))(ent)) {
		DMLog("adren", "fatality: target gone");
		return;
	}
	const float *c = ((WorldCenter_t)VFunc(ent, OFS_WORLDCENTER))(ent);
	float center[3] = {c[0], c[1], c[2]};
	BYTE tr[TR_SIZE + 16];
	memset(tr, 0, sizeof(tr));
	TraceLine(owner, g_dmSword.eye, center, MASK_MELEE, tr);
	if (*(void **)(tr + TR_ENT) != ent) {  // something in between: the blow still lands (it is a fatality)
		memcpy(tr, g_dmSword.eye, 12);
		memcpy(tr + 12, center, 12);
		*(float *)(tr + TR_FRACTION) = 0.5f;
		*(void **)(tr + TR_ENT) = ent;
	}
	DMLog("adren", "FATALITY blow (%s) on %s", w->move, ClassName(ent));
	DoHit(weapon, owner, w, tr, ent);
	DMLog("adren", "  target %s", ((IsAlive_t)VFunc(ent, OFS_ISALIVE))(ent) ? "SURVIVED" : "killed");
}

// The window of the current move containing the cycle (a move can have several: the huge combo strikes twice).
static int ActiveWindow(const char *move, float cycle)
{
	if (!move) return -1;
	for (int i = 0; i < g_numDMHitWindows; i++)
		if (!strcmp(g_dmHitWindows[i].move, move) && cycle >= g_dmHitWindows[i].open && cycle <= g_dmHitWindows[i].close)
			return i;
	return -1;
}

static int g_hitWindowIdx = -1;
static DWORD g_lastDecay;

// Per tick: requirement from Melee, decay, and the finisher target the client checks when a power attack is released.
static void UpdateAdrenaline(void *owner)
{
	int melee = owner ? *(int *)((BYTE *)owner + ENT_MELEE_CURRENT) : 0;
	if (melee < 0 || melee > 10) melee = 0;
	if (melee != g_dmSword.melee) {
		DMLog("adren", "Melee skill %d", melee);
		g_dmSword.melee = melee;
	}
	float need = g_dmSword.adrenalineBase - g_dmSword.adrenalinePerMelee * melee;
	if (need < g_dmSword.adrenalineMin) need = g_dmSword.adrenalineMin;
	g_dmSword.adrenalineNeeded = need;
	if (g_dmSword.adrenaline > need) g_dmSword.adrenaline = need;
	DWORD now = GetTickCount();
	if (!g_lastDecay) g_lastDecay = now;
	if (g_dmSword.adrenalineDecay > 0 && now - g_lastDecay >= (DWORD)(g_dmSword.adrenalineDecay * 1000)) {
		g_lastDecay = now;
		if (g_dmSword.adrenaline > 0) {
			g_dmSword.adrenaline -= 1.0f;
			if (g_dmSword.adrenaline < 0) g_dmSword.adrenaline = 0;
		}
	}
	static DWORD lastScan;
	if (g_dmSword.adrenaline < need || !owner) g_dmSword.finisherReady = false;
	else if (now - lastScan >= 100) {  // entity scan 10x per second is plenty for a "who is in front" check
		lastScan = now;
		g_dmSword.finisherReady = FindSwingTarget(owner, g_dmSword.finisherRange) != NULL;
	}
}

// Hit-recoil lockout: when an enemy hits the player, Bloodlines stops calling the weapon's per-frame update for
// ~1 s (0.35 s after a parried hit) - measured with the [gap] log. The DM logic below therefore also runs from the
// client frame (DMServerFallbackTick, same process and thread) whenever the game hasn't updated the katana for 50 ms.
static DWORD g_lastThink;
static void *g_lastWeapon;
static const DWORD FALLBACK_AFTER_MS = 50;

static void KatanaLogic(void *weapon);
static void ApplyArmModel();

static void __fastcall KatanaThink(void *weapon, void *)
{
	g_lastThink = GetTickCount();
	g_lastWeapon = weapon;
	if (!g_dmServerHits) {
		g_origThink(weapon);
		return;
	}
	__try {
		// No PrimaryAttack: Bloodlines' own swing (and its forward lunge) never starts for the katana.
		((Idle_t)VFunc(weapon, OFS_WEAPONIDLE))(weapon);
	} __except (CrashFilter(GetExceptionInformation(), "katana idle")) {
	}
	KatanaLogic(weapon);
}

// Called every client frame (dm_viewmodel.cpp): runs the katana logic while the game's update is locked out.
void DMServerFallbackTick()
{
	static DWORD lastLog;
	if (!g_dmServerHits || !g_dmSword.active || !g_lastWeapon || !g_lastThink) return;
	DWORD now = GetTickCount();
	if (now - g_lastThink < FALLBACK_AFTER_MS) return;
	if (now - lastLog > 1000) {
		lastLog = now;
		DMLog("gap", "game paused the katana update (%lu ms) - running the DM hits from the client frame", now - g_lastThink);
	}
	if (IsBadReadPtr(g_lastWeapon, 0x10) || MeleeIndex(g_lastWeapon) < 0) return;
	KatanaLogic(g_lastWeapon);
}

static void KatanaLogic(void *weapon)
{
	__try {
		if (!g_dmSword.active) return;
		ApplyArmModel();
		UpdateAdrenaline(GetOwner(weapon));
		const DMHitWindow *w = WindowFor(g_dmSword.move);
		if (!w) return;
		if (g_dmSword.swingId != g_hitSwing) {  // new swing: forget last swing's victims and dice
			g_hitSwing = g_dmSword.swingId;
			g_numHit = 0;
			g_hitWindowIdx = -1;
			void *owner = GetOwner(weapon);
			if (owner && w->fatal) {  // lock the fatality's victim now
				// lock range: finisher_range + 30 for the slashes, longer by the extra reach of the impale
				float lockRange = g_dmSword.finisherRange + 30.0f + (w->reach == 3 ? g_dmSword.reach[3] - g_dmSword.reach[1] : 0);
				g_finisherTarget = FindSwingTarget(owner, lockRange);
				DMLog("adren", "%s: target %s", w->move, g_finisherTarget ? ClassName(g_finisherTarget) : "none");
			}
			if (owner) {
				((MeleeReset_t)(g_base + (FN_MELEERESET - PREF_BASE)))(owner);
				// Roll now for the enemy we're swinging at, so it gets Bloodlines' block/dodge notice in time.
				float reachMax = 75.0f + g_dmSword.reach[w->reach < 0 || w->reach > 3 ? 0 : w->reach] + 20.0f;
				void *target = g_origDiceRolls ? FindSwingTarget(owner, reachMax) : NULL;
				if (target && !g_origDiceRolls(owner, target)) {
					((RollNotice_t)(g_base + (FN_ROLLANDNOTICE - PREF_BASE)))(owner, target);
					int *rec = g_origDiceRolls(owner, target);
					if (rec) DMLog("hit", "%s aimed at %s: dice attack %d soak %d defence %d (net %d)", w->move,
						ClassName(target), rec[1], rec[2], rec[3], rec[1] - rec[2] - rec[3]);
				}
			}
		}
		int wi = ActiveWindow(g_dmSword.move, g_dmSword.cycle);
		if (wi < 0) return;
		if (g_soundSwing != g_dmSword.swingId * 64 + wi) {  // whoosh as each strike starts its cut
			g_soundSwing = g_dmSword.swingId * 64 + wi;
			((WeaponSound_t)VFunc(weapon, OFS_WEAPONSOUND))(weapon, SOUND_SWISH, 1, 0, 0, 0, 0);
		}
		if (wi != g_hitWindowIdx) {  // next strike of a multi-strike move: the same enemy can be hit again
			g_hitWindowIdx = wi;
			g_numHit = 0;
		}
		w = &g_dmHitWindows[wi];
		void *owner = GetOwner(weapon);
		if (!owner) return;
		if (w->fatal && g_finisherTarget) {  // the locked enemy dies first; the sweep below cleaves the rest
			void *locked = g_finisherTarget;
			FatalBlow(weapon, owner, w);
			if (g_numHit < 8) g_hitVictims[g_numHit++] = locked;
		}
		// Reach: the traces run past the visible tip along the blade by the move's extra reach.
		float dir[3] = {g_dmSword.tip[0] - g_dmSword.hilt[0], g_dmSword.tip[1] - g_dmSword.hilt[1], g_dmSword.tip[2] - g_dmSword.hilt[2]};
		float len = sqrtf(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
		float extra = g_dmSword.reach[w->reach < 0 || w->reach > 3 ? 0 : w->reach];
		float tip[3];
		for (int c = 0; c < 3; c++) tip[c] = g_dmSword.tip[c] + (len > 0.001f ? dir[c] / len * extra : 0);
		TryHit(weapon, owner, w, g_dmSword.eye, tip);
		TryHit(weapon, owner, w, g_dmSword.eye, g_dmSword.mid);
		TryHit(weapon, owner, w, g_dmSword.hilt, tip);
	} __except (CrashFilter(GetExceptionInformation(), "katana think")) {
		DMLog("hit", "exception in katana think - falling back to Bloodlines' own attack (hits=0)");
		DMWarnConsole("DMCombat: katana hit failed - using Bloodlines' own attack. See dmcombat.log\n");
		g_dmServerHits = 0;
	}
}

// Per-character arm models (models/weapons/dm_katana/v_dm_katana_arm_<character>.mdl, character = the player's model
// without "_armor_N", published by the client in g_dmSword.character).
// 1. Level load: the katana's Precache (vtable slot 104 +0x1a0 = CBaseCombatWeapon::Precache 0x10250ed0) also precaches
//    every installed arm model (engine [0x1070b22c] +0x34 = PrecacheModel(name, preload), as UTIL_PrecacheModel does);
//    the engine refuses precaches after the level has loaded (returned 0 in game).
// 2. While the katana is out: the server's viewmodel (CBaseViewModel, vtable 0x1051671c, no classname) gets SetModel(name) (vtable slot 105
//    +0x1a4) when its model index (+0x1a4) isn't the character's. The client hook draws any v_dm_katana_arm* model.
// (Attempt 1 hooked slot 348, which returns the weapon's item name "item_w_katana", not its viewmodel - removed.)
static const int SLOT_PRECACHE = 104, OFS_SETMODEL = 0x1a4, ENT_MODELINDEX = 0x1a4;
static const DWORD VT_VIEWMODEL = 0x1051671c;  // CBaseViewModel (no classname string)
static const DWORD ENGINE_SERVER_PTR = 0x1070b22c;
typedef void(__thiscall *Precache_t)(void *ent);
typedef int(__thiscall *PrecacheModel_t)(void *engine, const char *name, bool preload);
typedef void(__thiscall *SetModel_t)(void *ent, const char *name);
static Precache_t g_origPrecache[DM_NUM_WEAPONS];  // per class (the torch has its own)
static const int MAX_ARM_MODELS = 64;
static char g_armNames[MAX_ARM_MODELS][96];
static int g_armIndex[MAX_ARM_MODELS], g_numArm, g_origArmIndex, g_armSwapFailures;

// Every melee weapon precached at level load. A weapon first given mid-level (console, pickup, shop) used to be
// precached late; the engine refuses late precaches, so its sounds had no client index: the client looked the
// index up in its sound table, got a garbage name and crashed (seen with the bat) or played another
// weapon's sound (sledgehammer "katana sounds"). The player always carries the fists (CWeaponUnarmed 0x104e7dbc,
// item_w_unarmed; also CWeaponMelee_Fists 0x104d5ecc), precached on every level load: their Precache (slot 104 =
// CBaseCombatWeapon::Precache 0x10250ed0) also runs UTIL_PrecacheOther (0x101d0ec0, cdecl(classname): creates the
// entity, runs its Precache, removes it) for every melee weapon - which also precaches the arm models.
static const DWORD VT_UNARMED = 0x104e7dbc, VT_FISTS = 0x104d5ecc, FN_PRECACHEOTHER = 0x101d0ec0;
typedef void(__cdecl *PrecacheOther_t)(const char *classname);
static Precache_t g_origUnarmedPrecache, g_origFistsPrecache;

static void PrecacheAllMelee(const char *by)
{
	static bool busy;
	if (busy) return;
	busy = true;
	int n = 0;
	__try {
		for (int i = 0; i < DM_NUM_WEAPONS; i++, n++)
			((PrecacheOther_t)(g_base + (FN_PRECACHEOTHER - PREF_BASE)))(g_dmWeapons[i].item);
		DMLog("arm", "level load (%s): all %d melee weapons precached", by, n);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		DMLog("arm", "exception precaching melee weapon %d (%s)", n, n < DM_NUM_WEAPONS ? g_dmWeapons[n].item : "-");
	}
	busy = false;
}

static void __fastcall UnarmedPrecache(void *weapon, void *)
{
	if (g_origUnarmedPrecache) g_origUnarmedPrecache(weapon);
	PrecacheAllMelee("unarmed");
}

static void __fastcall FistsPrecache(void *weapon, void *)
{
	if (g_origFistsPrecache) g_origFistsPrecache(weapon);
	PrecacheAllMelee("fists");
}

static void __fastcall KatanaPrecache(void *weapon, void *)
{
	int wi = MeleeIndex(weapon);
	if (wi >= 0 && g_origPrecache[wi]) g_origPrecache[wi](weapon);
	__try {
		char dir[MAX_PATH], pattern[MAX_PATH];
		GetModuleFileNameA(NULL, dir, sizeof(dir));
		char *sl = strrchr(dir, '\\');
		if (sl) sl[1] = 0;
		_snprintf(pattern, sizeof(pattern), "%sUnofficial_Patch\\models\\weapons\\dm_katana\\v_dm_katana_arm_*.mdl", dir);
		void *engine = *(void **)(g_base + (ENGINE_SERVER_PTR - PREF_BASE));
		WIN32_FIND_DATAA fd;
		HANDLE h = FindFirstFileA(pattern, &fd);
		g_numArm = 0;
		g_origArmIndex = 0;
		g_armSwapFailures = 0;
		if (h == INVALID_HANDLE_VALUE) return;
		do {
			if (g_numArm >= MAX_ARM_MODELS) break;
			_snprintf(g_armNames[g_numArm], sizeof(g_armNames[0]), "models/weapons/dm_katana/%s", fd.cFileName);
			_strlwr(g_armNames[g_numArm]);
			g_armIndex[g_numArm] = ((PrecacheModel_t)VFunc(engine, 0x34))(engine, g_armNames[g_numArm], false);
			g_numArm++;
		} while (FindNextFileA(h, &fd));
		FindClose(h);
		static DWORD lastLog;  // every melee weapon's precache gets here (PrecacheAllMelee): log once per level load
		if (GetTickCount() - lastLog > 5000)
			DMLog("arm", "precached %d arm models (first: %s -> %d)", g_numArm, g_numArm ? g_armNames[0] : "-",
				g_numArm ? g_armIndex[0] : 0);
		lastLog = GetTickCount();
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		DMLog("arm", "exception precaching the arm models");
	}
}

// Called each server tick while the katana is out.
static void ApplyArmModel()
{
	if (!g_dmSword.character[0] || !g_numArm) return;
	char want[96];
	_snprintf(want, sizeof(want), "models/weapons/dm_katana/v_dm_katana_arm_%s.mdl", g_dmSword.character);
	_strlwr(want);
	int idx = 0;
	for (int i = 0; i < g_numArm; i++)
		if (!strcmp(g_armNames[i], want)) idx = g_armIndex[i];
	if (idx <= 0) return;  // not installed or the precache was refused
	if (!g_origArmIndex) {  // the item file's arm model (already precached by the game, so this only looks it up)
		void *engine = *(void **)(g_base + (ENGINE_SERVER_PTR - PREF_BASE));
		g_origArmIndex = ((PrecacheModel_t)VFunc(engine, 0x34))(engine, "models/weapons/dm_katana/v_dm_katana_arm.mdl", false);
		DMLog("arm", "item file arm model index %d", g_origArmIndex);
	}
	BYTE *table = *(BYTE **)(g_base + (ENT_TABLE_PTR - PREF_BASE));
	if (!table) return;
	for (int i = 1; i < ENT_SLOTS; i++) {
		void *ent = *(void **)(table + i * ENT_STRIDE + 4);
		// the viewmodel has no classname: identify it by its vtable (CBaseViewModel 0x1051671c)
		if (!ent || IsBadReadPtr(ent, 0x280) || *(DWORD *)ent != g_base + (VT_VIEWMODEL - PREF_BASE)) continue;
		int cur = *(int *)((BYTE *)ent + ENT_MODELINDEX);
		// the player has several viewmodel slots (unused ones have model 0, others other models): only the one showing
		// an arm model is swapped - the item file's v_dm_katana_arm.mdl, or another character's (a save made as
		// another character restores its model)
		if (cur == idx || cur <= 0) continue;
		bool arm = cur == g_origArmIndex;
		for (int k = 0; k < g_numArm && !arm; k++) arm = cur == g_armIndex[k];
		if (!arm) continue;
		if (g_armSwapFailures >= 3) return;  // SetModel didn't take: stop retrying every tick
		((SetModel_t)VFunc(ent, OFS_SETMODEL))(ent, want);
		int now = *(int *)((BYTE *)ent + ENT_MODELINDEX);
		if (now != idx) g_armSwapFailures++;
		DMLog("arm", "viewmodel model %d -> %s (%d), now %d", cur, want, idx, now);
	}
}

void DMServerInstall(HMODULE server)
{
	g_base = (DWORD)server;
	TraceLine = (TraceLine_t)(g_base + (FN_TRACELINE - PREF_BASE));
	GetOwner = (GetOwner_t)(g_base + (FN_GETOWNER - PREF_BASE));
	// every melee weapon class: the DM think (they all share CWeaponMelee's think, slot 319) and the arm-model precache
	int hooked = 0;
	for (int i = 0; i < DM_NUM_WEAPONS; i++) {
		Think_t t = (Think_t)DMHookVSlot(server, g_dmWeapons[i].serverVt, SLOT_THINK, (void *)&KatanaThink);
		if (t && !g_origThink) g_origThink = t;
		g_origPrecache[i] = (Precache_t)DMHookVSlot(server, g_dmWeapons[i].serverVt, SLOT_PRECACHE, (void *)&KatanaPrecache);
		if (t) hooked++;
	}
	DMLog("hit", "melee weapon classes hooked: %d/%d", hooked, DM_NUM_WEAPONS);
	DMLog("hit", "katana think %s", g_origThink ? "hooked" : "NOT hooked");

	DMLog("arm", "katana Precache %s", g_origPrecache ? "hooked" : "NOT hooked");
	g_origUnarmedPrecache = (Precache_t)DMHookVSlot(server, VT_UNARMED, SLOT_PRECACHE, (void *)&UnarmedPrecache);
	g_origFistsPrecache = (Precache_t)DMHookVSlot(server, VT_FISTS, SLOT_PRECACHE, (void *)&FistsPrecache);
	DMLog("arm", "all-melee precache on the fists: unarmed %s, fists %s", g_origUnarmedPrecache ? "hooked" : "NOT hooked",
		g_origFistsPrecache ? "hooked" : "NOT hooked");

	HookThunk(DICEROLLS_THUNK, DICEROLLS_FN, (void *)&DiceRollsHook, (void **)&g_origDiceRolls, "melee dice rolls");

	BYTE *thunk = (BYTE *)(g_base + (PLAYERBLOCK_THUNK - PREF_BASE));
	DWORD blockFn = (DWORD)(thunk + 5) + *(DWORD *)(thunk + 1);
	if (thunk[0] == 0xE9 && blockFn == g_base + (PLAYERBLOCK_FN - PREF_BASE)) {
		g_origPlayerBlock = (PlayerBlock_t)blockFn;
		DWORD oldp;
		VirtualProtect(thunk + 1, 4, PAGE_EXECUTE_READWRITE, &oldp);
		*(DWORD *)(thunk + 1) = (DWORD)&PlayerBlockHook - (DWORD)(thunk + 5);
		VirtualProtect(thunk + 1, 4, oldp, &oldp);
		FlushInstructionCache(GetCurrentProcess(), thunk, 5);
		DMLog("parry", "player block check hooked at %p", thunk);
	} else {
		DMLog("parry", "player block thunk mismatch (%02x -> %08lx) - parry disabled", thunk[0], blockFn);
	}

	BYTE *site = (BYTE *)(g_base + (MELEEHIT_SETTER_CALL - PREF_BASE));
	if (site[0] != 0xE8) {
		DMLog("hit", "damage call site mismatch (%02x) - DM damage multipliers disabled", site[0]);
		return;
	}
	g_origSetter = (Setter_t)((DWORD)(site + 5) + *(DWORD *)(site + 1));
	DWORD old;
	VirtualProtect(site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
	*(DWORD *)(site + 1) = (DWORD)&DamageSetterHook - (DWORD)(site + 5);
	VirtualProtect(site + 1, 4, old, &old);
	FlushInstructionCache(GetCurrentProcess(), site, 5);
	DMLog("hit", "damage setter call hooked at %p", site);
}
