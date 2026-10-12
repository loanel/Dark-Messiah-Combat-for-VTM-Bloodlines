// First-person rigid sword.
//
// client.dll (UP build 0x41afaf63): CViewRender::CalcViewModelView @ 0x10190ba0 (thiscall, 7 stack args, ret 0x1c)
// fills a CViewModelInfo { bool active; int index; Vector origin @+8; QAngle angles @+0x14; QAngle angles2 @+0x20 }
// that CopyViewModelInfoToEntities (0x10191940) copies onto viewmodel entity <index>. Its only call site is
// 0x1019146e (inside CViewRender::CalcView, loop over 2 viewmodels). We redirect that call, run the original, and
// when the active weapon is the katana we replace origin/angles with: eye * DM sword path * katana alignment.
//
// Spike input: the mouse/keys are read directly (GetAsyncKeyState) while the game window has focus. The game's own
// melee attack still runs underneath; syncing to it (and replacing it) comes with the vampire.dll work.
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "dm_log.h"
#include "dm_math.h"
#include "dm_viewmodel.h"
#include "dm_data.h"
#include "dm_shared.h"
#include "dm_hitwindows.h"
#include "dm_hook.h"
#include "dm_armvariants.h"
#include "dm_weapons.h"

extern int g_dmServerHits;
void DMServerFallbackTick();
extern int g_dmHud;
extern float g_dmHudOffset;
extern float g_dmHudScale;
extern float g_dmAdrenalineVolume;
extern int g_dmReadyReticle, g_dmReadyEdges;
extern float g_dmReticleSize;
extern float g_dmDamageScale;
extern int g_dmSideKnock, g_dmSideKnockFlip;
extern int g_dmExitWatchdog;
extern int g_dmRecoilHits;
extern int g_dmHitStun;

static const DWORD PREF_BASE = 0x10000000;
static const DWORD CALCVMVIEW = 0x10190ba0;      // CViewRender::CalcViewModelView
static const DWORD CALCVMVIEW_CALL = 0x1019146e;  // call site in CViewRender::CalcView
static const DWORD LOCAL_PLAYER_PTR = 0x104a0d50; // C_BasePlayer *local player (global)
static const int PLAYER_GETACTIVEWEAPON = 0x250;  // vtable byte offset, used the same way by CalcViewModelView
static const DWORD VT_KATANA = 0x101e9b94;        // C_WeaponMelee_Katana primary vftable (RTTI)

typedef BYTE *(__thiscall *CalcVMView_t)(void *self, int, int, int, int, int, int, int);
typedef void *(__thiscall *GetActiveWeapon_t)(void *player);

static DWORD g_base;
static CalcVMView_t g_origCalc;

// ---------------------------------------------------------------- settings (dmcombat.ini, live reload)
struct Settings {
	int enabled, debug;
	float grip, flip, roll;          // katana alignment: grip = katana-space z of the hand, flip = 1 tip at -z
	float offset[3];                 // extra eye-space offset (x fwd, y left, z up)
	float pitch;                     // tilt the whole DM motion down (+) about the eye, degrees
	float speed, chargeTime, blend;  // playback speed, hold time for a power attack, crossfade seconds
	float vmFov;                     // viewmodel_fov while the katana is drawn (0 = leave it alone)
};
static Settings S = {1, 1, -13.0f, 0, 0, {16, -2, -20}, 0, 1.0f, 0.36f, 0.12f, 54};
static FILETIME g_iniTime;
static DWORD g_iniCheck;

static float g_impaleHold = 0.6f;  // dmcombat.ini impale_hold: seconds the blade stays in before the pull-out
static int g_trail = 1;            // dmcombat.ini trail: red streak on the adrenaline moves
static float g_trailLife = 0.2f;   // dmcombat.ini trail_life (seconds)
static int g_trailAlpha = 170;     // dmcombat.ini trail_alpha (0-255)
static float g_torchFlame = 4;     // dmcombat.ini torch_flame: flame this many units below the torch's head end

static const char *IniPath()  // <game>\dmcombat.ini (absolute: the working directory may be anything)
{
	static char path[MAX_PATH];
	if (!path[0]) DMGamePath("dmcombat.ini", path, sizeof(path));
	return path;
}

static float IniF(const char *key, float def)
{
	char buf[64], d[32];
	sprintf(d, "%g", def);
	GetPrivateProfileStringA("viewmodel", key, d, buf, sizeof(buf), IniPath());
	return (float)atof(buf);
}

static void ReloadSettings()
{
	DWORD now = GetTickCount();
	if (now - g_iniCheck < 500) return;
	g_iniCheck = now;
	WIN32_FILE_ATTRIBUTE_DATA fa;
	if (!GetFileAttributesExA(IniPath(), GetFileExInfoStandard, &fa)) return;
	if (CompareFileTime(&fa.ftLastWriteTime, &g_iniTime) == 0) return;
	g_iniTime = fa.ftLastWriteTime;
	S.enabled = (int)IniF("enabled", 1);
	S.debug = (int)IniF("debug", 1);
	S.grip = IniF("grip", -13);  // must match tools/build_katana_hand.py --grip
	S.flip = IniF("flip", 0);
	S.roll = IniF("roll", 0);
	S.offset[0] = IniF("offset_x", 16);
	S.offset[1] = IniF("offset_y", -2);
	S.offset[2] = IniF("offset_z", -20);
	S.pitch = IniF("pitch", 0);
	S.speed = IniF("speed", 1);
	S.chargeTime = IniF("charge_time", 0.36f);
	S.blend = IniF("blend", 0.12f);
	S.vmFov = IniF("viewmodel_fov", 54);  // the sword placement was tuned at 54 (Bloodlines default)
	g_dmServerHits = (int)IniF("hits", 1);
	g_dmSword.parryWindow = IniF("parry_window", 0.3f);
	g_dmSword.parryBloodCost = (int)IniF("parry_blood", 1);
	g_dmSword.reach[0] = IniF("reach_fast", 10);
	g_dmSword.reach[1] = IniF("reach_power", 20);
	g_dmSword.reach[2] = IniF("reach_stab", 30);
	g_dmSword.reach[3] = IniF("reach_impale", 50);
	g_dmSword.adrenalineBase = IniF("adrenaline_base", 20);
	g_dmSword.adrenalinePerMelee = IniF("adrenaline_per_melee", 2);
	g_dmSword.adrenalineMin = IniF("adrenaline_min", 8);
	g_dmSword.adrenalineGain = IniF("adrenaline_gain", 1);
	g_dmSword.adrenalineDecay = IniF("adrenaline_decay", 20);
	g_dmSword.finisherRange = IniF("finisher_range", 110);
	g_impaleHold = IniF("impale_hold", 0.6f);
	g_trail = (int)IniF("trail", 1);
	g_trailLife = IniF("trail_life", 0.2f);
	g_trailAlpha = (int)IniF("trail_alpha", 170);
	g_torchFlame = IniF("torch_flame", 4);
	g_dmHud = (int)IniF("hud", 1);
	g_dmHudOffset = IniF("hud_offset", 0.28f);
	g_dmHudScale = IniF("hud_scale", 0.65f);
	g_dmAdrenalineVolume = IniF("adrenaline_volume", 0.8f);
	g_dmReadyReticle = (int)IniF("adrenaline_reticle", 1);
	g_dmReadyEdges = (int)IniF("adrenaline_edges", 1);
	g_dmReticleSize = IniF("adrenaline_reticle_size", 40);
	g_dmDamageScale = IniF("damage_scale", 1);
	g_dmSideKnock = (int)IniF("side_knock", 1);
	g_dmSideKnockFlip = (int)IniF("side_knock_flip", 0);
	g_dmExitWatchdog = (int)IniF("exit_watchdog", 0);
	g_dmRecoilHits = (int)IniF("recoil_hits", 0);
	g_dmHitStun = (int)IniF("hit_stun", 0);
	DMLog("ini", "reloaded: enabled %d grip %.1f flip %.0f roll %.1f offset %.1f %.1f %.1f pitch %.1f speed %.2f charge %.2f",
		S.enabled, S.grip, S.flip, S.roll, S.offset[0], S.offset[1], S.offset[2], S.pitch, S.speed, S.chargeTime);
}

// ---------------------------------------------------------------- path playback
static const DMPath *FindPath(const char *name)
{
	for (int i = 0; i < g_numDMPaths; i++)
		if (!_stricmp(g_dmPaths[i].name, name)) return &g_dmPaths[i];
	DMLog("vm", "missing path %s", name);
	return NULL;
}

struct Pose { float pos[3]; Quat q; };

static Pose SamplePath(const DMPath *p, float t)
{
	float f = t * p->fps;
	int n = p->numFrames;
	if (f < 0) f = 0;
	if (f > n - 1) f = (float)(n - 1);
	int i = (int)f;
	int j = i + 1 < n ? i + 1 : i;
	float a = f - i;
	const DMPathKey &k0 = p->keys[i], &k1 = p->keys[j];
	Pose r;
	for (int c = 0; c < 3; c++) r.pos[c] = k0.pos[c] + (k1.pos[c] - k0.pos[c]) * a;
	Quat q0 = {k0.quat[0], k0.quat[1], k0.quat[2], k0.quat[3]};
	Quat q1 = {k1.quat[0], k1.quat[1], k1.quat[2], k1.quat[3]};
	r.q = QuatSlerp(q0, q1, a);
	return r;
}

// Animated arm: the same frame of every driven arm bone (motion relative to Dark Messiah's reference pose).
static void SampleArm(const DMPath *p, float t, Pose *out)
{
	float f = t * p->fps;
	int n = p->numFrames;
	if (f < 0) f = 0;
	if (f > n - 1) f = (float)(n - 1);
	int i = (int)f;
	int j = i + 1 < n ? i + 1 : i;
	float a = f - i;
	for (int b = 0; b < DM_ARM_BONES; b++) {
		const DMPathKey &k0 = p->arm[i * DM_ARM_BONES + b], &k1 = p->arm[j * DM_ARM_BONES + b];
		for (int c = 0; c < 3; c++) out[b].pos[c] = k0.pos[c] + (k1.pos[c] - k0.pos[c]) * a;
		Quat q0 = {k0.quat[0], k0.quat[1], k0.quat[2], k0.quat[3]};
		Quat q1 = {k1.quat[0], k1.quat[1], k1.quat[2], k1.quat[3]};
		out[b].q = QuatSlerp(q0, q1, a);
	}
}

static float Duration(const DMPath *p) { return (p->numFrames - 1) / p->fps; }

// ---------------------------------------------------------------- spike state machine
enum State { ST_DRAW, ST_IDLE, ST_FAST, ST_CHARGE_IN, ST_CHARGE_IDLE, ST_SLASH_OUT, ST_PARRY_IN, ST_PARRY_IDLE, ST_PARRY_OUT, ST_PARRY_HIT, ST_ADRENALINE, ST_ADRENALINE_HOLD };
static const char *STATE_NAMES[] = {"draw", "idle", "fast", "charge_in", "charge_idle", "slash_out", "parry_in", "parry_idle", "parry_out", "parry_hit", "adrenaline", "adrenaline_hold"};

static State g_state = ST_DRAW;
static const DMPath *g_path;
static double g_stateStart;  // seconds
static int g_fastIndex;      // 0..4 = A..E
static bool g_fastQueued;
static double g_fastEnd = -1;            // when the last fast attack finished
static const double CHAIN_WINDOW = 0.4;  // seconds after a fast attack in which a tap continues the chain
static char g_dir[2] = "";   // "", "L", "R", "B", "T"
static Pose g_blendFrom;
static double g_blendStart = -1;
static Pose g_lastPose;
static Pose g_armPose[DM_ARM_BONES], g_armFrom[DM_ARM_BONES];  // animated arm: current / blend-from bone motion
static Mat34 g_armEye;   // eye * (tilt, offset): where Dark Messiah's eye space sits in the world this frame
static bool g_armEyeValid;
static bool g_wasKatana;
static bool g_lmbPrev, g_rmbPrev;
static int g_parriedSeen;
static double g_parryStart;  // when the guard went up (parry_in)
static double g_lmbDown;

static double Now()
{
	static LARGE_INTEGER f;
	LARGE_INTEGER c;
	if (!f.QuadPart) QueryPerformanceFrequency(&f);
	QueryPerformanceCounter(&c);
	return (double)c.QuadPart / (double)f.QuadPart;
}

static bool Key(int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; }

static void Enter(State st, const char *pathName, double now)
{
	const DMPath *p = FindPath(pathName);
	if (!p) return;
	g_blendFrom = g_lastPose;
	memcpy(g_armFrom, g_armPose, sizeof(g_armPose));
	g_blendStart = now;
	g_state = st;
	g_path = p;
	g_stateStart = now;
	g_dmSword.move = p->name;
	if (st == ST_PARRY_IN) g_parryStart = now;
	g_dmSword.swingId++;
	if (S.debug) DMLog("vm", "state %s seq %s (%.2fs)", STATE_NAMES[st], pathName, Duration(p));
}

static void PickDir()
{
	g_dir[0] = Key('A') ? 'L' : Key('D') ? 'R' : Key('W') ? 'T' : Key('S') ? 'B' : 0;
	g_dir[1] = 0;
}

static void BigSlashName(char *out, const char *part)
{
	if (g_dir[0]) sprintf(out, "bigslash_sword_noshield_%s_%s", g_dir, part);
	else sprintf(out, "bigslash_sword_noshield_%s", part);
}

// A finished move returns to idle, or straight into the parry when RMB is being held (pressed during the move).
static void EndMove(bool rmb, double now)
{
	if (rmb) Enter(ST_PARRY_IN, "parry_sword_in", now);
	else Enter(ST_IDLE, "sword_noshield_idle", now);
}

static void Think(double now, bool focused)
{
	bool lmb = focused && Key(VK_LBUTTON), rmb = focused && Key(VK_RBUTTON);
	bool lmbPressed = lmb && !g_lmbPrev, lmbReleased = !lmb && g_lmbPrev;
	if (lmbPressed) g_lmbDown = now;
	float t = (float)(now - g_stateStart) * S.speed;
	float dur = g_path ? Duration(g_path) : 0;
	char name[64];

	switch (g_state) {
	case ST_DRAW:
		if (t >= dur) EndMove(rmb, now);
		break;
	case ST_IDLE:
		if (rmb) { Enter(ST_PARRY_IN, "parry_sword_in", now); break; }  // held, not just pressed: also catches RMB held through a move
		if (lmb && now - g_lmbDown >= S.chargeTime) {
			PickDir();
			BigSlashName(name, "in");
			Enter(ST_CHARGE_IN, name, now);
		} else if (lmbReleased) {
			// a tap shortly after a fast attack continues the chain (A B C D E B C ...), otherwise it starts at A
			bool chain = now - g_fastEnd < CHAIN_WINDOW;
			g_fastIndex = !chain ? 0 : g_fastIndex >= 4 ? 1 : g_fastIndex + 1;
			g_fastQueued = false;
			sprintf(name, "fastattack_sword_noshield_%c", 'A' + g_fastIndex);
			Enter(ST_FAST, name, now);
		}
		break;
	case ST_FAST:
		if (lmbPressed && t > dur * 0.3f) g_fastQueued = true;
		if (t >= dur) {
			if (g_fastQueued) {
				g_fastIndex = g_fastIndex >= 4 ? 1 : g_fastIndex + 1;  // A B C D E B C ...
				g_fastQueued = false;
				sprintf(name, "fastattack_sword_noshield_%c", 'A' + g_fastIndex);
				Enter(ST_FAST, name, now);
			} else {
				g_fastEnd = now;
				EndMove(rmb, now);
			}
		}
		break;
	case ST_CHARGE_IN:
		if (lmbReleased) {  // released during the wind-up: fast attack (DM rule)
			g_fastIndex = 0;
			Enter(ST_FAST, "fastattack_sword_noshield_A", now);
		} else if (rmb && !g_rmbPrev) {  // RMB while holding re-aims with the movement key held now (user's DMHL2 rule)
			char old = g_dir[0];
			PickDir();
			if (g_dir[0] != old) {
				BigSlashName(name, "in");
				Enter(ST_CHARGE_IN, name, now);
			}
		} else if (t >= dur) {
			BigSlashName(name, "idle");
			Enter(ST_CHARGE_IDLE, name, now);
		}
		break;
	case ST_CHARGE_IDLE:
		if (lmbReleased && g_dmSword.adrenalineNeeded > 0 && g_dmSword.adrenaline >= g_dmSword.adrenalineNeeded) {
			// Adrenaline move (user design): the left power attack becomes the cleaving behead (guaranteed kill on the
			// enemy in front, if any, plus a sweep), the stabs (forward/back) become DM's impale (guaranteed kill,
			// blade held in, pulled out), the neutral and right attacks become the two-strike huge combo.
			g_dmSword.adrenaline -= g_dmSword.adrenalineNeeded;
			if (g_dmSword.adrenaline < 0) g_dmSword.adrenaline = 0;
			const char *seq = g_dir[0] == 'L' ? "behead_sword_noshield_out"
				: g_dir[0] == 'T' || g_dir[0] == 'B' ? "Impal_sword_noshield_in" : "combo_sword_huge_noshield";
			DMLog("adren", "adrenaline move: %s", seq);
			Enter(ST_ADRENALINE, seq, now);
		} else if (lmbReleased) {
			BigSlashName(name, "out");
			Enter(ST_SLASH_OUT, name, now);
		} else if (rmb && !g_rmbPrev) {  // RMB while holding re-aims (otherwise the direction stays as chosen)
			char old = g_dir[0];
			PickDir();
			if (g_dir[0] != old) {
				BigSlashName(name, "idle");
				Enter(ST_CHARGE_IDLE, name, now);
			}
		}
		break;
	case ST_SLASH_OUT: {
		// Recovery can be cut short once the blade has done its work (hit window closed, clamped to 45-65% of the
		// slash): a click starts the next attack, holding RMB raises the guard.
		float cancelAt = 0.65f;
		for (int i = 0; i < g_numDMHitWindows; i++)
			if (!strcmp(g_dmHitWindows[i].move, g_path->name)) cancelAt = g_dmHitWindows[i].close;
		if (cancelAt < 0.45f) cancelAt = 0.45f;
		if (cancelAt > 0.65f) cancelAt = 0.65f;
		if (t >= dur) EndMove(rmb, now);
		else if (dur > 0 && t / dur >= cancelAt && (rmb || lmbPressed)) {
			if (S.debug) DMLog("vm", "slash recovery cut at %.0f%%", 100 * t / dur);
			EndMove(rmb, now);  // idle picks up the click (tap = fast attack, hold = new power attack)
		}
		break;
	}
	case ST_PARRY_IN:
		if (t >= dur) Enter(ST_PARRY_IDLE, "parry_sword_idle", now);
		break;
	case ST_PARRY_IDLE:
		if (!rmb) Enter(ST_PARRY_OUT, "parry_sword_out", now);
		break;
	case ST_PARRY_OUT:
		if (t >= dur) EndMove(rmb, now);
		break;
	case ST_ADRENALINE:  // plays out in full (no recovery cut, no slow motion)
		if (t >= dur) {
			if (!strcmp(g_path->name, "Impal_sword_noshield_in")) Enter(ST_ADRENALINE_HOLD, "Impal_sword_noshield_idle", now);
			else EndMove(rmb, now);
		}
		break;
	case ST_ADRENALINE_HOLD:  // impale: the blade stays in, then DM's pull-out
		if (t >= g_impaleHold) Enter(ST_ADRENALINE, "Impal_sword_noshield_out", now);
		break;
	case ST_PARRY_HIT:  // DM parry impact, then back to holding the guard (or lowering it)
		if (t >= dur) {
			if (rmb) Enter(ST_PARRY_IDLE, "parry_sword_idle", now);
			else Enter(ST_PARRY_OUT, "parry_sword_out", now);
		}
		break;
	}
	if (g_dmSword.parriedHits != g_parriedSeen) {  // the server blocked a hit while we were parrying
		g_parriedSeen = g_dmSword.parriedHits;
		static const char *impacts[] = {"parry_sword_A", "parry_sword_B", "parry_sword_C"};
		Enter(ST_PARRY_HIT, impacts[g_parriedSeen % 3], now);
	}
	g_dmSword.parrying = g_state == ST_PARRY_IN || g_state == ST_PARRY_IDLE || g_state == ST_PARRY_HIT;
	g_dmSword.parryAge = g_dmSword.parrying ? (float)(now - g_parryStart) : 99.0f;
	g_lmbPrev = lmb;
	g_rmbPrev = rmb;
}

static Pose CurrentPose(double now)
{
	float t = (float)(now - g_stateStart) * S.speed;
	if (g_state == ST_IDLE || g_state == ST_CHARGE_IDLE || g_state == ST_PARRY_IDLE || g_state == ST_ADRENALINE_HOLD) {
		float d = Duration(g_path);
		if (d > 0) t = fmodf(t, d);
	}
	Pose p = SamplePath(g_path, t);
	SampleArm(g_path, t, g_armPose);
	float b = S.blend > 0 && g_blendStart >= 0 ? (float)(now - g_blendStart) / S.blend : 1.0f;
	if (b < 1) {
		for (int c = 0; c < 3; c++) p.pos[c] = g_blendFrom.pos[c] + (p.pos[c] - g_blendFrom.pos[c]) * b;
		p.q = QuatSlerp(g_blendFrom.q, p.q, b);
		for (int k = 0; k < DM_ARM_BONES; k++) {
			for (int c = 0; c < 3; c++)
				g_armPose[k].pos[c] = g_armFrom[k].pos[c] + (g_armPose[k].pos[c] - g_armFrom[k].pos[c]) * b;
			g_armPose[k].q = QuatSlerp(g_armFrom[k].q, g_armPose[k].q, b);
		}
	}
	g_lastPose = p;
	return p;
}

// ---------------------------------------------------------------- viewmodel FOV
// ConVar viewmodel_fov = 0x105fc718; the view code reads parent ([0x105fc71c])->m_fValue at +0x28 (CViewRender::SetUpView,
// 0x101917c4). We write that float while the katana is drawn and put the previous value back afterwards.
static const DWORD CVAR_VMFOV_PARENT = 0x105fc71c;
static const int CVAR_FVALUE = 0x28;
static float g_savedVmFov = -1;   // the player's value before we changed it (-1 = we haven't)
static float g_appliedVmFov = -1; // what we wrote, so we only undo our own change

static float *VmFovValue()
{
	BYTE *parent = *(BYTE **)(g_base + (CVAR_VMFOV_PARENT - PREF_BASE));
	return parent ? (float *)(parent + CVAR_FVALUE) : NULL;
}

static void ApplyVmFov(bool katana)
{
	float *v = VmFovValue();
	if (!v) return;
	if (katana && S.vmFov > 0) {
		if (g_savedVmFov < 0) {
			g_savedVmFov = *v;
			DMLog("vm", "viewmodel_fov %.0f -> %.0f while the katana is drawn", *v, S.vmFov);
		}
		*v = g_appliedVmFov = S.vmFov;
	} else if (g_savedVmFov >= 0) {
		if (*v == g_appliedVmFov) *v = g_savedVmFov;  // only undo our own change
		DMLog("vm", "viewmodel_fov restored to %.0f", *v);
		g_savedVmFov = -1;
	}
}

// ---------------------------------------------------------------- the hook
// The held melee weapon (dm_weapons.h index by its client class vtable), -1 for anything else.
static int g_weapon = -1;
static void *g_weaponEnt;  // the held melee weapon (client entity), NULL for anything else

static int ActiveMeleeWeapon()
{
	g_weaponEnt = NULL;
	void *player = *(void **)(g_base + (LOCAL_PLAYER_PTR - PREF_BASE));
	if (!player) return -1;
	GetActiveWeapon_t gaw = *(GetActiveWeapon_t *)(*(BYTE **)player + PLAYER_GETACTIVEWEAPON);
	void *weapon = gaw(player);
	if (!weapon) return -1;
	DWORD vt = *(DWORD *)weapon;
	for (int i = 0; i < DM_NUM_WEAPONS; i++)
		if (vt == g_base + (g_dmWeapons[i].clientVt - PREF_BASE)) {
			g_weaponEnt = weapon;
			return i;
		}
	return -1;
}

// ---------------------------------------------------------------- torch flame
// The torch's server code (CWeaponMelee_Torch, vampire.dll 0x103e77f0) spawns env_particle "TorchWeaponEmitter" and
// attaches it to the weapon's "particle" attachment with follow mode 0x11. Every frame the client particle
// (C_EnvParticle, vtable 0x1022ed24, slot 120 = +0x1e0, 0x100b0540) recomputes that point from the weapon's world
// model - which our first-person view never shows: it is held by the invisible player body, so the flame burned below
// the camera. After the game's update we move the emitter points (array at +0x470, count +0x47c, 100 bytes each,
// world position at +0x10, read by the mode-0x11 spawn callback 0x100b14c0) to the head of the drawn torch.
// The drawn torch uses viewmodel_fov, the particles the world view: the point is pushed away from the view axis by
// tan(fov / 2) / tan(viewmodel_fov / 2), so on screen it lands on the drawn torch head.
static const DWORD VT_ENVPARTICLE = 0x1022ed24, FN_PARTICLEFOLLOW = 0x100b0540;
static const int SLOT_PARTICLEFOLLOW = 0x1e0 / 4;
static const int PART_FOLLOW = 0x188, PART_MODE = 0x420, PART_POINTS = 0x470, PART_NPOINTS = 0x47c;
static const int PART_POINT_SIZE = 100, PART_POINT_POS = 0x10, FOLLOW_ATTACHMENT = 0x11;
static const DWORD CL_ENTLIST_PTR = 0x102b8e98;     // client entity table: entries of 12 bytes {?, entity, serial}
static const DWORD WORLD_FOV_SOURCE = 0x104a57e4;   // CViewRender::SetUpView: view.fov = ([0x104a57e4])->vfunc +0xa0()
static const int OFS_WORLDFOV = 0xa0;
static const DWORD CVAR_DEFAULTFOV_PARENT = 0x105f9994;  // ConVar default_fov 0x105f9990 (fallback)
typedef void(__thiscall *ParticleFollow_t)(BYTE *particle);
typedef float(__thiscall *GetFov_t)(void *self);
static ParticleFollow_t g_origParticleFollow;
static float g_flame[3];
static void *g_flameWeapon;  // the torch whose particle gets moved to g_flame; NULL = leave every particle alone

static float *VmFovValue();

static float WorldFov()
{
	float fov = 0;
	__try {
		void *src = *(void **)(g_base + (WORLD_FOV_SOURCE - PREF_BASE));
		if (src) fov = ((GetFov_t)(*(void ***)src)[OFS_WORLDFOV / 4])(src);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		fov = 0;
	}
	if (fov > 10 && fov < 170) return fov;
	BYTE *parent = *(BYTE **)(g_base + (CVAR_DEFAULTFOV_PARENT - PREF_BASE));
	return parent ? *(float *)(parent + 0x28) : 75.0f;
}

static void TorchFlamePoint(const Mat34 &eye, const Mat34 &world)
{
	g_flameWeapon = NULL;
	if (g_weapon < 0 || strcmp(g_dmWeapons[g_weapon].name, "torch") || !g_weaponEnt) return;
	float z = g_dmWeapons[g_weapon].zmax - g_torchFlame;  // katana space, along the torch
	float d[3];
	for (int c = 0; c < 3; c++) d[c] = world.m[c][2] * z + world.m[c][3] - eye.m[c][3];
	float *vm = VmFovValue();
	float vmFov = vm && *vm > 10 && *vm < 170 ? *vm : 54.0f, fov = WorldFov();
	float k = tanf(fov * DM_PI / 360) / tanf(vmFov * DM_PI / 360);
	float x = 0, y = 0, u = 0;  // eye space: forward, left, up
	for (int c = 0; c < 3; c++) {
		x += d[c] * eye.m[c][0];
		y += d[c] * eye.m[c][1];
		u += d[c] * eye.m[c][2];
	}
	for (int c = 0; c < 3; c++) g_flame[c] = eye.m[c][3] + eye.m[c][0] * x + (eye.m[c][1] * y + eye.m[c][2] * u) * k;
	g_flameWeapon = g_weaponEnt;
	static float loggedK;
	if (fabsf(k - loggedK) > 0.01f) {
		loggedK = k;
		DMLog("torch", "flame on the torch head: fov %.1f, viewmodel_fov %.1f -> scale %.3f", fov, vmFov, k);
	}
}

static void __fastcall HookParticleFollow(BYTE *self, void *)
{
	g_origParticleFollow(self);
	if (!g_flameWeapon) return;
	__try {
		if (*(int *)(self + PART_MODE) != FOLLOW_ATTACHMENT) return;
		DWORD h = *(DWORD *)(self + PART_FOLLOW);
		BYTE *list = *(BYTE **)(g_base + (CL_ENTLIST_PTR - PREF_BASE));
		if (h == 0xffffffff || !list) return;
		BYTE *e = list + (h & 0x1fff) * 12 + 4;
		if (*(DWORD *)(e + 4) != (h >> 13) || *(void **)e != g_flameWeapon) return;
		BYTE *pts = *(BYTE **)(self + PART_POINTS);
		int n = *(int *)(self + PART_NPOINTS);
		for (int i = 0; pts && i < n; i++) memcpy(pts + i * PART_POINT_SIZE + PART_POINT_POS, g_flame, sizeof(g_flame));
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		static int once;
		if (!once++) DMLog("torch", "exception moving the torch flame - left where the game puts it");
		g_flameWeapon = NULL;
	}
}

static void ApplySword(BYTE *info, double now)
{
	float *origin = (float *)(info + 8), *angles = (float *)(info + 0x14), *angles2 = (float *)(info + 0x20);

	Mat34 eye;
	AngleMatrix(angles, eye);
	eye.m[0][3] = origin[0]; eye.m[1][3] = origin[1]; eye.m[2][3] = origin[2];

	Pose p = CurrentPose(now);
	Mat34 dm;
	QuatMatrix(p.q, p.pos, dm);
	float tilt[3] = {S.pitch, 0, 0};  // rotate the DM motion about the eye, then offset it
	Mat34 hand;
	AngleMatrix(tilt, hand);
	ConcatTransforms(hand, dm, hand);
	for (int c = 0; c < 3; c++) hand.m[c][3] += S.offset[c];
	{  // the animated arm uses the same placement: eye * (tilt | offset) * Dark Messiah bone motion
		Mat34 h;
		AngleMatrix(tilt, h);
		for (int c = 0; c < 3; c++) h.m[c][3] = S.offset[c];
		ConcatTransforms(eye, h, g_armEye);
		g_armEyeValid = true;
	}

	// Katana model space -> DM sword space (grip at origin, blade along -y, edge along z):
	// katana +z (blade) -> -y, katana y -> z, katana x -> x; flip turns the katana end over; roll spins the blade.
	Mat34 fix = {{{1, 0, 0, 0}, {0, 0, -1, 0}, {0, 1, 0, 0}}};
	if (S.flip) { fix.m[1][2] = 1; fix.m[2][1] = -1; }  // 180 about x: tip at katana -z
	float c = cosf(S.roll * DM_PI / 180), s = sinf(S.roll * DM_PI / 180);
	Mat34 roll = {{{c, 0, s, 0}, {0, 1, 0, 0}, {-s, 0, c, 0}}};  // spin about sword-space y (the blade)
	Mat34 fixR;
	ConcatTransforms(roll, fix, fixR);
	// translation: the katana point (0, 0, grip) lands on the hand
	float g[3] = {fixR.m[0][2] * S.grip, fixR.m[1][2] * S.grip, fixR.m[2][2] * S.grip};
	fixR.m[0][3] = -g[0]; fixR.m[1][3] = -g[1]; fixR.m[2][3] = -g[2];

	Mat34 tmp, world;
	ConcatTransforms(eye, hand, tmp);
	ConcatTransforms(tmp, fixR, world);

	// publish for the server-side hits: eye, and points along the katana (grip -> tip end)
	float tipZ = g_weapon >= 0 ? g_dmWeapons[g_weapon].zmax : 23.5f;  // the held weapon's head end (katana space)
	float zs[3] = {S.grip, (S.grip + tipZ) * 0.5f, tipZ};
	float *outs[3] = {g_dmSword.hilt, g_dmSword.mid, g_dmSword.tip};
	for (int k = 0; k < 3; k++)
		for (int c = 0; c < 3; c++) outs[k][c] = world.m[c][2] * zs[k] + world.m[c][3];
	g_dmSword.eye[0] = eye.m[0][3]; g_dmSword.eye[1] = eye.m[1][3]; g_dmSword.eye[2] = eye.m[2][3];
	g_dmSword.eyeFwd[0] = eye.m[0][0]; g_dmSword.eyeFwd[1] = eye.m[1][0]; g_dmSword.eyeFwd[2] = eye.m[2][0];
	float d = Duration(g_path);
	g_dmSword.cycle = d > 0 ? (float)(now - g_stateStart) * S.speed / d : 1.0f;
	g_dmSword.active = true;

	TorchFlamePoint(eye, world);

	origin[0] = world.m[0][3]; origin[1] = world.m[1][3]; origin[2] = world.m[2][3];
	MatrixAngles(world, angles);
	angles2[0] = angles[0]; angles2[1] = angles[1]; angles2[2] = angles[2];
}


// ---------------------------------------------------------------- adrenaline streak
// Dark Messiah drew a red streak behind critical strikes. Ours: a fading red ribbon swept by the blade during the
// adrenaline moves, from the blade's middle to the tip plus the move's extra reach - i.e. where the hit traces really
// go, so it shows the true range (the drawn katana uses viewmodel_fov, the ribbon the world view). Drawn with the
// engine's debug overlay (engine.dll "VDebugOverlay002", slot 4 = AddTriangleOverlay(p1, p2, p3, r, g, b, a,
// noDepthTest, duration)), redrawn every frame for one frame with alpha by age.
typedef void(__thiscall *AddTri_t)(void *ov, const float *p1, const float *p2, const float *p3, int r, int g, int b,
	int a, bool noDepthTest, float duration);
typedef void *(__cdecl *CreateInterface_t)(const char *name, int *ret);
struct TrailSample { double t; float a[3], b[3]; };
static TrailSample g_trailBuf[64];
static int g_trailN;

static void *DebugOverlay()
{
	static void *ov;
	static bool tried;
	if (tried) return ov;
	tried = true;
	HMODULE eng = GetModuleHandleA("engine.dll");
	CreateInterface_t ci = eng ? (CreateInterface_t)GetProcAddress(eng, "CreateInterface") : NULL;
	ov = ci ? ci("VDebugOverlay002", NULL) : NULL;
	DMLog("vm", "debug overlay %p (adrenaline streak)", ov);
	return ov;
}

static void UpdateTrail(double now)
{
	// Only while a strike is cutting (its hit window, opened a little early so the streak leads into it): each swing of
	// the huge combo gets its own streak and the recovery back to neutral leaves none.
	bool on = false;
	int cls = 1;
	if (g_trail && g_state == ST_ADRENALINE && g_path)
		for (int i = 0; i < g_numDMHitWindows; i++)
			if (!strcmp(g_dmHitWindows[i].move, g_path->name) && g_dmSword.cycle >= g_dmHitWindows[i].open - 0.05f
				&& g_dmSword.cycle <= g_dmHitWindows[i].close) {
				on = true;
				cls = g_dmHitWindows[i].reach;
			}
	if (on) {
		float extra = g_dmSword.reach[cls < 0 || cls > 3 ? 1 : cls];
		float d[3], len = 0;
		for (int c = 0; c < 3; c++) { d[c] = g_dmSword.tip[c] - g_dmSword.hilt[c]; len += d[c] * d[c]; }
		len = sqrtf(len);
		if (g_trailN == 64) { memmove(g_trailBuf, g_trailBuf + 1, 63 * sizeof(TrailSample)); g_trailN--; }
		TrailSample &t = g_trailBuf[g_trailN++];
		t.t = now;
		for (int c = 0; c < 3; c++) {
			t.a[c] = g_dmSword.mid[c];
			t.b[c] = g_dmSword.tip[c] + (len > 0.001f ? d[c] / len * extra : 0);
		}
	}
	while (g_trailN && now - g_trailBuf[0].t > g_trailLife) {  // drop expired samples
		memmove(g_trailBuf, g_trailBuf + 1, (g_trailN - 1) * sizeof(TrailSample));
		g_trailN--;
	}
	if (g_trailN < 2) return;
	void *ov = DebugOverlay();
	if (!ov) return;
	AddTri_t tri = (AddTri_t)(*(void ***)ov)[4];
	for (int i = 1; i < g_trailN; i++) {
		TrailSample &p = g_trailBuf[i - 1], &q = g_trailBuf[i];
		if (q.t - p.t > 0.06) continue;  // a gap between two strikes: no bridge across it
		float k = 1.0f - (float)(now - p.t) / g_trailLife;
		if (k <= 0) continue;
		int a = (int)(g_trailAlpha * k);
		// both windings: the overlay triangles are one-sided
		tri(ov, p.a, p.b, q.b, 120, 4, 4, a, false, 0.0f);  // blood-bar crimson
		tri(ov, p.a, q.b, q.a, 120, 4, 4, a, false, 0.0f);  // blood-bar crimson
		tri(ov, q.b, p.b, p.a, 120, 4, 4, a, false, 0.0f);  // blood-bar crimson
		tri(ov, q.a, q.b, p.a, 120, 4, 4, a, false, 0.0f);  // blood-bar crimson
	}
}

static BYTE *__fastcall HookCalcViewModelView(void *self, void *, int index, int a2, int a3, int a4, int a5, int a6, int a7)
{
	BYTE *info = g_origCalc(self, index, a2, a3, a4, a5, a6, a7);
	if (!info || index != 0) return info;
	__try {
		ReloadSettings();
		double now = Now();
		int weapon = S.enabled ? ActiveMeleeWeapon() : -1;
		bool katana = weapon >= 0;
		if (weapon != g_weapon && katana && g_wasKatana) {  // switched straight from one melee weapon to another
			DMLog("vm", "melee weapon %s", g_dmWeapons[weapon].name);
			Enter(ST_DRAW, "sword_noshield_draw", now);
		}
		g_weapon = weapon;
		g_dmSword.weapon = weapon;
		if (katana != g_wasKatana) {
			DMLog("vm", "katana %s", katana ? "drawn" : "put away");
			g_wasKatana = katana;
			if (katana) {
				g_blendStart = -1;
				Enter(ST_DRAW, "sword_noshield_draw", now);
			}
		}
		ApplyVmFov(katana && g_path);
		if (!katana || !g_path) {
			g_dmSword.active = false;
			g_flameWeapon = NULL;
			return info;
		}
		HWND fg = GetForegroundWindow();
		DWORD pid = 0;
		GetWindowThreadProcessId(fg, &pid);
		Think(now, pid == GetCurrentProcessId());
		ApplySword(info, now);
		__try {
			UpdateTrail(now);
		} __except (EXCEPTION_EXECUTE_HANDLER) {
			DMLog("vm", "exception drawing the adrenaline streak - streak disabled");
			g_trail = 0;
			g_trailN = 0;
		}
		DMServerFallbackTick();  // keeps hits working during Bloodlines' hit-recoil weapon lockout
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		static int once;
		if (!once++) DMLog("vm", "exception in viewmodel hook - sword disabled");
		S.enabled = 0;
	}
	return info;
}

// ---------------------------------------------------------------- animated arm
// models/weapons/dm_katana/v_dm_katana_arm.mdl (tools/build_katana_arm.py) = arm variants + the katana skinned to the
// skeleton of Bloodlines' thaumaturgy viewmodel. After the game builds the viewmodel's bones
// (C_BaseViewModel vtable 0x1022c6a4 slot 123 = C_BaseAnimating::BuildTransformations 0x1008fd00, thiscall, 4 args;
// bone-to-world matrices at this+0x6e8, 0x30 each), every driven bone is overwritten with Dark Messiah's pose:
//   boneToWorld = eye * (tilt | offset) * D(frame) * inverse(poseToBone)
// GetModelPtr = 0x1008f900 thiscall(-1) -> studiohdr (name +12, numbones +0xf0, boneindex +0xf4; bone 160 bytes,
// poseToBone at +88).
static const DWORD VT_BASEVIEWMODEL = 0x1022c6a4, FN_GETMODELPTR = 0x1008f900;
static const int SLOT_BUILDTRANSFORMATIONS = 123, OFS_BONETOWORLD = 0x6e8;
typedef void(__thiscall *BuildTransformations_t)(void *self, void *a, void *b, void *c, void *d);
typedef BYTE *(__thiscall *GetModelPtr_t)(void *self, int index);
static BuildTransformations_t g_origBuild;
static int g_armBuilds;

static void InvertRigid(const float *m, Mat34 &out)  // m = 3x4 rows
{
	for (int i = 0; i < 3; i++)
		for (int j = 0; j < 3; j++) out.m[i][j] = m[j * 4 + i];
	for (int i = 0; i < 3; i++)
		out.m[i][3] = -(out.m[i][0] * m[3] + out.m[i][1] * m[7] + out.m[i][2] * m[11]);
}

// The player's outfit and character, read from the path of its third-person model, which is consistent across clans
// (the file names aren't): character/pc/<gender>/<clan>/armor<N>/... (gangrel male: armor_<N>). Publishes
// g_dmSword.character = "<clan>_<gender>" (the server swaps in v_dm_katana_arm_<character>.mdl) and returns N, or -1.
static int PlayerOutfit()
{
	static char lastName[128];
	static int lastOutfit = -1;
	void *player = *(void **)(g_base + (LOCAL_PLAYER_PTR - PREF_BASE));
	if (!player) return lastOutfit;
	const BYTE *hdr = ((GetModelPtr_t)(g_base + (FN_GETMODELPTR - PREF_BASE)))(player, -1);
	if (!hdr || !strncmp(lastName, (const char *)hdr + 12, sizeof(lastName) - 1)) return lastOutfit;
	strncpy(lastName, (const char *)hdr + 12, sizeof(lastName) - 1);
	char path[128];
	strncpy(path, (const char *)hdr + 12, sizeof(path) - 1);
	path[sizeof(path) - 1] = 0;
	_strlwr(path);
	for (char *c = path; *c; c++) if (*c == '\\') *c = '/';
	char gender[16] = "", clan[32] = "";
	int outfit = -1;
	const char *p = strstr(path, "character/pc/");
	if (p && sscanf(p, "character/pc/%15[a-z]/%31[a-z]/armor", gender, clan) == 2) {
		const char *a = strstr(p, "/armor");
		if (a) {
			a += 6;
			if (*a == '_') a++;
			if (*a >= '0' && *a <= '9') outfit = *a - '0';
		}
	}
	if (outfit >= 0 && outfit < DM_ARM_VARIANTS) {  // character model block N = outfit armor_N
		_snprintf(g_dmSword.character, sizeof(g_dmSword.character) - 1, "%s_%s", clan, gender);
		lastOutfit = outfit;
	} else {
		lastOutfit = -1;
	}
	DMLog("vm", "player model %s -> character %s, outfit %d", path, g_dmSword.character, lastOutfit);
	return lastOutfit;
}

static void __fastcall HookBuildTransformations(void *self, void *, void *a, void *b, void *c, void *d)
{
	g_origBuild(self, a, b, c, d);
	__try {
		BYTE *hdr = ((GetModelPtr_t)(g_base + (FN_GETMODELPTR - PREF_BASE)))(self, -1);
		if (!hdr || !strstr((const char *)hdr + 12, "v_dm_katana_arm")) return;
		if (!g_armEyeValid || !g_dmSword.active) {  // weapon lowered/holstered: hide every variant (no donor poses)
			float *bones = *(float **)((BYTE *)self + OFS_BONETOWORLD);
			int numBones = *(int *)(hdr + 0xf0);
			if (bones)
				for (int gb = 1; gb < numBones && gb < DM_ARM_VARIANT_BASE(DM_ARM_VARIANTS); gb++)
					memset(bones + gb * 12, 0, 12 * sizeof(float));
			return;
		}
		static const BYTE *loggedHdr;
		if (hdr != loggedHdr) {  // which arm model the game actually draws (per-character model check)
			loggedHdr = hdr;
			char file[MAX_PATH] = "";
			const BYTE *mdl = ((GetModelPtr_t)(g_base + (FN_GETMODELPTR - PREF_BASE)))(self, 0);
			DMLog("arm", "drawing arm model %s (model index %d)", (const char *)hdr + 12, *(int *)((BYTE *)self + 0x420));
			(void)file; (void)mdl;
		}
		int numBones = *(int *)(hdr + 0xf0);
		BYTE *boneTable = hdr + *(int *)(hdr + 0xf4);
		float *bones = *(float **)((BYTE *)self + OFS_BONETOWORLD);
		if (!bones) return;
		// arm block: the character model's outfit N; the base model (or an unknown player model) = block 0, DM's arm
		int outfit = PlayerOutfit();
		int sel = strstr((const char *)hdr + 12, "v_dm_katana_arm_") && outfit >= 0 ? outfit : 0;
		// weapons (bones 1..DM_NUM_WEAPON_BONES): the held one rides the hand, the others collapse
		for (int wb = 0; wb < DM_NUM_WEAPON_BONES; wb++) {
			int gb = 1 + wb;
			if (gb >= numBones) continue;
			if (wb != g_weapon) {
				memset(bones + gb * 12, 0, 12 * sizeof(float));
				continue;
			}
			Mat34 d, ed, inv, w;
			QuatMatrix(g_armPose[DM_ARM_BONES - 1].q, g_armPose[DM_ARM_BONES - 1].pos, d);  // the hand's motion
			ConcatTransforms(g_armEye, d, ed);
			InvertRigid((const float *)(boneTable + gb * 160 + 88), inv);
			ConcatTransforms(ed, inv, w);
			memcpy(bones + gb * 12, w.m, sizeof(w.m));
		}
		for (int v = 0; v < DM_ARM_VARIANTS; v++) {
			for (int k = 0; k < DM_ARM_BONES; k++) {
				int gb = DM_ARM_VARIANT_BASE(v) + k;
				if (gb >= numBones) continue;
				if (v != sel) {  // collapse: every vertex of this variant lands on one point
					memset(bones + gb * 12, 0, 12 * sizeof(float));
					continue;
				}
				Mat34 d, ed, inv, w;
				QuatMatrix(g_armPose[k].q, g_armPose[k].pos, d);
				ConcatTransforms(g_armEye, d, ed);
				InvertRigid((const float *)(boneTable + gb * 160 + 88), inv);
				ConcatTransforms(ed, inv, w);
				memcpy(bones + gb * 12, w.m, sizeof(w.m));
			}
		}
		if (!g_armBuilds++)
			DMLog("vm", "animated arm: %d variants in %s, driving variant %d", DM_ARM_VARIANTS, (const char *)hdr + 12, sel);
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		static int once;
		if (!once++) DMLog("vm", "exception driving the arm bones");
	}
}

void DMViewModelInstall(HMODULE client)
{
	g_base = (DWORD)client;
	g_origBuild = (BuildTransformations_t)DMHookVSlot(client, VT_BASEVIEWMODEL, SLOT_BUILDTRANSFORMATIONS,
		(void *)&HookBuildTransformations);
	DMLog("vm", "animated arm hook %s", g_origBuild ? "installed" : "NOT installed");
	void **vtParticle = (void **)(g_base + (VT_ENVPARTICLE - PREF_BASE));
	if (vtParticle[SLOT_PARTICLEFOLLOW] == (void *)(g_base + (FN_PARTICLEFOLLOW - PREF_BASE)))
		g_origParticleFollow = (ParticleFollow_t)DMHookVSlot(client, VT_ENVPARTICLE, SLOT_PARTICLEFOLLOW, (void *)&HookParticleFollow);
	DMLog("torch", "torch flame hook %s", g_origParticleFollow ? "installed" : "NOT installed (slot changed - another plug-in?)");
	BYTE *site = (BYTE *)(g_base + (CALCVMVIEW_CALL - PREF_BASE));
	DWORD target = (DWORD)(site + 5) + *(DWORD *)(site + 1);
	if (site[0] != 0xE8 || target != g_base + (CALCVMVIEW - PREF_BASE)) {
		DMLog("vm", "call site mismatch (%02x -> %08lx), not hooking (another plug-in?)", site[0], target);
		return;
	}
	g_origCalc = (CalcVMView_t)target;
	DWORD old;
	VirtualProtect(site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
	*(DWORD *)(site + 1) = (DWORD)&HookCalcViewModelView - (DWORD)(site + 5);
	VirtualProtect(site + 1, 4, old, &old);
	FlushInstructionCache(GetCurrentProcess(), site, 5);
	DMLog("vm", "hooked CalcViewModelView call at %p; %d DM paths", site, g_numDMPaths);
	ReloadSettings();
}
