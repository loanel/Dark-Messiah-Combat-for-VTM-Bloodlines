// HUD: the adrenaline bar, left of Bloodlines' blood bar, drawn with the game's own HUD sprites.
//
// client.dll (UP build): CBloodBar (vftable 0x10227f14) slot 98 (+0x188, 0x1004c9f0) = per-frame paint. It builds
// CHUDSprite objects (ctor 0x10059250 thiscall(tex, x, y, w, h, texW, texH), 0x20 bytes) and draws them with
// CHUDSprite::Draw 0x10059b70 thiscall(x, y, w, h, alpha) and DrawPart 0x1005c430 thiscall(x, y, w, h, int src[4], alpha).
// Measured at 1920x1080 (MODLOG): icon bg Draw (bar+0x1ac) 1740,904 180x179; fill DrawPart (bar+0x1bc,
// hud/new_ui/bloodbar/bloodbar) 1865,533 35x395 src {46,21,43,323} for blood 10/15 (src[3] = 43 + 421*blood/max);
// bottom cap DrawPart (bar+0x1c0) 1865,899 35x28 src {46,21,22,42}; frame Draw (bar+0x1a4) 1740,47 180x1061.
// The paint's draw calls are redirected to wrappers that remember their arguments; after the paint we draw the same
// frame, a gold fill (hud/new_ui/dm_adrenaline) cut to the adrenaline level and a gold cap, shifted left.
#include <windows.h>
#include <math.h>
#include <string.h>
#include "dm_log.h"
#include "dm_hook.h"
#include "dm_shared.h"

static const DWORD PREF_BASE = 0x10000000;
static const DWORD VT_BLOODBAR = 0x10227f14;
static const int SLOT_BLOODPAINT = 98;
static const DWORD FN_SPRITE_CTOR = 0x10059250, FN_SPRITE_DRAW = 0x10059b70, FN_SPRITE_DRAWPART = 0x1005c430;
static const DWORD FN_SCREEN_W = 0x100cd100, FN_SCREEN_H = 0x100cd0f0;
static const DWORD DRAW_CALLS[] = {0x1004ce19, 0x1004ced3, 0x1004d21f, 0x1004d2d9};
static const DWORD DRAWPART_CALLS[] = {0x1004d07b, 0x1004d18d};
static const int BAR_FRAME = 0x1a4, BAR_FILL = 0x1bc, BAR_BOTTOM = 0x1c0;  // CBloodBar sprite fields
static const int FILL_SRC_TOP = 43, FILL_SRC_SPAN = 421;                     // 0x2b, 0x1a5 in the paint

typedef void(__thiscall *Paint_t)(void *panel);
typedef void(__thiscall *Ctor_t)(void *sprite, const char *tex, int x, int y, int w, int h, int texW, int texH);
typedef void(__thiscall *Draw_t)(void *sprite, int x, int y, int w, int h, int alpha);
typedef void(__thiscall *DrawPart_t)(void *sprite, int x, int y, int w, int h, int *src, int alpha);

static DWORD g_base;
static Paint_t g_origPaint;
static Draw_t g_draw;
static DrawPart_t g_drawPart;
static BYTE *g_bloodBar;
static void *g_goldFill, *g_goldBottom, *g_goldFrame, *g_goldGlow;
int g_dmHud = 1;              // dmcombat.ini hud
float g_dmHudOffset = 0.28f;  // dmcombat.ini hud_offset: shift left, in blood-frame widths
float g_dmHudScale = 0.65f;   // dmcombat.ini hud_scale: size relative to the blood bar
int g_dmReadyReticle = 1;     // dmcombat.ini adrenaline_reticle: red pulsing ring on the crosshair when adrenaline is full
int g_dmReadyEdges = 1;       // dmcombat.ini adrenaline_edges: red pulse on the screen sides (Dark Messiah style)
float g_dmReticleSize = 40;   // dmcombat.ini adrenaline_reticle_size, in 768-line units
static void *g_fxReticle, *g_fxEdgeL, *g_fxEdgeR;
void DMAdrenalineSync();

// What the blood bar drew this frame.
struct Rec { bool valid; int x, y, w, h, alpha; int src[4]; };
static Rec g_frame, g_fill, g_bottom;

static void __fastcall DrawHook(void *sprite, void *, int x, int y, int w, int h, int alpha)
{
	if (g_bloodBar && sprite == *(void **)(g_bloodBar + BAR_FRAME)) {
		Rec r = {true, x, y, w, h, alpha};
		g_frame = r;
	}
	g_draw(sprite, x, y, w, h, alpha);
}

static void __fastcall DrawPartHook(void *sprite, void *, int x, int y, int w, int h, int *src, int alpha)
{
	if (g_bloodBar && !IsBadReadPtr(src, 16)) {
		Rec r = {true, x, y, w, h, alpha, {src[0], src[1], src[2], src[3]}};
		if (sprite == *(void **)(g_bloodBar + BAR_FILL)) g_fill = r;
		else if (sprite == *(void **)(g_bloodBar + BAR_BOTTOM)) g_bottom = r;
	}
	g_drawPart(sprite, x, y, w, h, src, alpha);
}

static void *MakeSprite(const char *tex, int x, int y, int w, int h, int texW, int texH)
{
	void *sp = new BYTE[0x20];
	memset(sp, 0, 0x20);
	((Ctor_t)(g_base + (FN_SPRITE_CTOR - PREF_BASE)))(sp, tex, x, y, w, h, texW, texH);
	return sp;
}

// The adrenaline bar: the blood bar's column only (no ornaments), scaled by hud_scale about the top of the full blood
// tube and moved left by hud_offset frame widths: both tubes start at the same height, ours ends above the blood bar's
// golden wing ornament (user: no overlap).
static void DrawAdrenalineBar()
{
	if (!g_frame.valid || !g_fill.valid || !g_bottom.valid) return;
	if (!g_dmSword.active && g_dmSword.adrenaline <= 0) return;  // only with the katana out, or while some is left
	if (!g_goldFill) {
		g_goldFill = MakeSprite("hud/new_ui/dm_adrenaline", 0, 0, 0x40, 0x200, 0x40, 0x200);
		g_goldGlow = MakeSprite("hud/new_ui/dm_adrenalineglow", 0, 0, 0x40, 0x200, 0x40, 0x200);
		g_goldBottom = MakeSprite("hud/new_ui/dm_adrenalinebottom", 0, 0, 0x40, 0x40, 0x40, 0x40);
		g_goldFrame = MakeSprite("hud/new_ui/dm_adrenalineframe", 0, 0x4c, 0x80, 0x2ed, 0x80, 0x400);  // = blood frame cut
		DMLog("hud", "adrenaline sprites %p %p %p %p", g_goldFill, g_goldGlow, g_goldBottom, g_goldFrame);
	}
	float sc = g_dmHudScale > 0.1f ? g_dmHudScale : 0.65f;
	float ax = g_fill.x + g_fill.w * 0.5f, ay = (float)(g_fill.y + g_fill.h);  // bottom centre of the blood fill
	float shift = g_frame.w * g_dmHudOffset;
	int bloodSpan0 = g_fill.src[3] - g_fill.src[2];
	float perSrc0 = bloodSpan0 > 0 ? (float)g_fill.h / bloodSpan0
		: ((int(__cdecl *)())(g_base + (FN_SCREEN_H - PREF_BASE)))() / 768.0f;
	float top = ay - FILL_SRC_SPAN * perSrc0;  // top of the full blood tube: both tubes start at this height (user)
	#define TX(v) ((int)(ax + ((v) - ax) * sc - shift + 0.5f))
	#define TY(v) ((int)(top + ((v) - top) * sc + 0.5f))
	#define TS(v) ((int)((v) * sc + 0.5f))

	float need = g_dmSword.adrenalineNeeded > 0 ? g_dmSword.adrenalineNeeded : 20.0f;
	float frac = g_dmSword.adrenaline / need;
	if (frac > 1) frac = 1;
	if (frac < 0) frac = 0;
	int bloodSpan = g_fill.src[3] - g_fill.src[2];
	float perSrc = bloodSpan > 0 ? (float)g_fill.h / bloodSpan
		: ((int(__cdecl *)())(g_base + (FN_SCREEN_H - PREF_BASE)))() / 768.0f;
	int span = (int)(FILL_SRC_SPAN * frac);
	int alpha = g_frame.alpha;
	void *fill = g_goldFill;
	if (frac >= 1 && (GetTickCount() / 200) % 2) fill = g_goldGlow;  // full: blink bright/gold
	if (span > 0) {
		int src[4] = {g_fill.src[0], g_fill.src[1], FILL_SRC_TOP, FILL_SRC_TOP + span};
		int h = TS(span * perSrc);
		g_drawPart(fill, TX(g_fill.x), TY(ay) - h, TS(g_fill.w), h, src, alpha);
	}
	g_drawPart(g_goldBottom, TX(g_bottom.x), TY(g_bottom.y), TS(g_bottom.w), TS(g_bottom.h), g_bottom.src, alpha);
	g_draw(g_goldFrame, TX(g_frame.x), TY(g_frame.y), TS(g_frame.w), TS(g_frame.h), alpha);
	#undef TX
	#undef TY
	#undef TS
}

// "Adrenaline full" sound, played like Bloodlines' info-bar notifications (FUN_10056f30): a C_LocalPlayerFilter
// (ctor 0x100be160) and enginesound ([0x104a5818]) vtable +0xc EmitSound(filter, -1, 0, sample, volume, 0 (no
// attenuation = 2D), 0x2800, 100, NULL, NULL, true, 0). PrecacheSound = vtable +0 (sample, preload).
static const DWORD ENGINESOUND_PTR = 0x104a5818, FN_LOCALPLAYERFILTER = 0x100be160;
static const char *ADRENALINE_SOUND = "dmcombat/adrenaline_reached.wav";
float g_dmAdrenalineVolume = 0.8f;  // dmcombat.ini adrenaline_volume (Dark Messiah: 0.6)
typedef bool(__thiscall *Precache_t)(void *snd, const char *sample, int preload);
typedef void(__thiscall *Emit_t)(void *snd, void *filter, int ent, int chan, const char *sample, float vol, float atten,
	int flags, int pitch, const float *origin, const float *dir, int updatePos, float soundtime);

static void PlayAdrenalineSound()
{
	void *snd = *(void **)(g_base + (ENGINESOUND_PTR - PREF_BASE));
	if (!snd || g_dmAdrenalineVolume <= 0) return;
	static bool precached;
	if (!precached) {
		precached = true;
		((Precache_t)(*(void ***)snd)[0])(snd, ADRENALINE_SOUND, 0);
	}
	BYTE *filter = new BYTE[0x40];  // tiny, once per full meter; the game frees its own copy, we keep ours
	memset(filter, 0, 0x40);
	((void(__thiscall *)(void *))(g_base + (FN_LOCALPLAYERFILTER - PREF_BASE)))(filter);
	((Emit_t)(*(void ***)snd)[3])(snd, filter, -1, 0, ADRENALINE_SOUND, g_dmAdrenalineVolume, 0.0f, 0x2800, 100,
		NULL, NULL, 1, 0.0f);
	DMLog("hud", "adrenaline full sound");
}

// Adrenaline ready: the reticle pulses red and the screen sides glow red in the same rhythm (1.25 pulses a second).
static void DrawAdrenalineReady()
{
	bool full = g_dmSword.adrenalineNeeded > 0 && g_dmSword.adrenaline >= g_dmSword.adrenalineNeeded;
	if (!full || !g_dmSword.active || (!g_dmReadyReticle && !g_dmReadyEdges)) return;
	if (!g_fxReticle) {
		g_fxReticle = MakeSprite("hud/new_ui/dm_adrenalinereticle", 0, 0, 64, 64, 64, 64);
		g_fxEdgeL = MakeSprite("hud/new_ui/dm_adrenalineedgel", 0, 0, 128, 512, 128, 512);
		g_fxEdgeR = MakeSprite("hud/new_ui/dm_adrenalineedger", 0, 0, 128, 512, 128, 512);
	}
	int sw = ((int(__cdecl *)())(g_base + (FN_SCREEN_W - PREF_BASE)))();
	int sh = ((int(__cdecl *)())(g_base + (FN_SCREEN_H - PREF_BASE)))();
	if (sw <= 0 || sh <= 0) return;
	float pulse = 0.5f - 0.5f * cosf((GetTickCount() % 800) / 800.0f * 6.2831853f);  // 0..1..0
	if (g_dmReadyReticle) {
		int size = (int)(g_dmReticleSize * sh / 768.0f + 0.5f);
		g_draw(g_fxReticle, sw / 2 - size / 2, sh / 2 - size / 2, size, size, (int)(90 + 165 * pulse));
	}
	if (g_dmReadyEdges) {
		int w = sw / 7;
		int a = (int)(150 * pulse);
		g_draw(g_fxEdgeL, 0, 0, w, sh, a);
		g_draw(g_fxEdgeR, sw - w, 0, w, sh, a);
	}
}

static void __fastcall BloodPaintHook(void *panel, void *)
{
	g_bloodBar = (BYTE *)panel;
	g_frame.valid = g_fill.valid = g_bottom.valid = false;
	g_origPaint(panel);
	static bool wasFull;
	bool full = g_dmSword.adrenalineNeeded > 0 && g_dmSword.adrenaline >= g_dmSword.adrenalineNeeded;
	if (full && !wasFull) {
		__try {
			PlayAdrenalineSound();
		} __except (EXCEPTION_EXECUTE_HANDLER) {
			DMLog("hud", "exception playing the adrenaline sound - sound disabled");
			g_dmAdrenalineVolume = 0;
		}
	}
	wasFull = full;
	DMAdrenalineSync();
	if (!g_dmHud) return;
	__try {
		DrawAdrenalineBar();
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		DMLog("hud", "exception drawing the adrenaline bar - HUD bar disabled");
		g_dmHud = 0;
	}
	__try {
		DrawAdrenalineReady();
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		DMLog("hud", "exception drawing the adrenaline-ready effects - disabled");
		g_dmReadyReticle = g_dmReadyEdges = 0;
	}
}

static bool RedirectCall(DWORD siteVA, DWORD expectTarget, void *hook)
{
	BYTE *site = (BYTE *)(g_base + (siteVA - PREF_BASE));
	DWORD target = (DWORD)(site + 5) + *(DWORD *)(site + 1);
	if (site[0] != 0xE8 || target != g_base + (expectTarget - PREF_BASE)) {
		DMLog("hud", "call site %08lx mismatch - adrenaline bar disabled", siteVA);
		return false;
	}
	DWORD old;
	VirtualProtect(site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
	*(DWORD *)(site + 1) = (DWORD)hook - (DWORD)(site + 5);
	VirtualProtect(site + 1, 4, old, &old);
	FlushInstructionCache(GetCurrentProcess(), site, 5);
	return true;
}

void DMHudInstall(HMODULE client)
{
	g_base = (DWORD)client;
	g_draw = (Draw_t)(g_base + (FN_SPRITE_DRAW - PREF_BASE));
	g_drawPart = (DrawPart_t)(g_base + (FN_SPRITE_DRAWPART - PREF_BASE));
	for (int i = 0; i < 4; i++)
		if (!RedirectCall(DRAW_CALLS[i], FN_SPRITE_DRAW, (void *)&DrawHook)) return;
	for (int i = 0; i < 2; i++)
		if (!RedirectCall(DRAWPART_CALLS[i], FN_SPRITE_DRAWPART, (void *)&DrawPartHook)) return;
	g_origPaint = (Paint_t)DMHookVSlot(client, VT_BLOODBAR, SLOT_BLOODPAINT, (void *)&BloodPaintHook);
	DMLog("hud", "adrenaline bar %s", g_origPaint ? "hooked" : "NOT hooked");
}
