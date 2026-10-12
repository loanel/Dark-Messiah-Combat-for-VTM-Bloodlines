// "GetColorForSurface() ERROR: trace did not hit anything." console spam.
//
// client.dll 0x1002d8f0 GetColorForSurface(trace_t *tr, Vector *color), cdecl, called by the impact dust / debris fleck
// effects (call sites 0x1002de07 FX_DebrisFlecks, 0x1002ec20 FX_Dust, 0x100394df). When tr->m_pEnt (+0x4c) is NULL it
// prints the warning and then takes the colour from the lighting at the impact point - the same branch a world hit
// takes. The wrapper hands such traces over as world hits (client world entity = 0x100d0cf0(entlist [0x102b8e9c], 0),
// as in DidHitWorld 0x100ee8e0), so the colour comes out the same and the warning is gone.
#include <windows.h>
#include "dm_log.h"

static const DWORD PREF_BASE = 0x10000000;
static const DWORD FN_COLORFORSURFACE = 0x1002d8f0, FN_GETBASEENTITY = 0x100d0cf0, ENTLIST_PTR = 0x102b8e9c;
static const DWORD CALL_SITES[] = {0x1002de07, 0x1002ec20, 0x100394df};
static const int TR_ENT = 0x4c;

typedef void(__cdecl *ColorForSurface_t)(BYTE *tr, float *color);
typedef void *(__thiscall *GetBaseEntity_t)(void *list, int index);
static DWORD g_base;
static ColorForSurface_t g_orig;

static void __cdecl ColorForSurfaceHook(BYTE *tr, float *color)
{
	if (tr && !*(void **)(tr + TR_ENT)) {
		static int logged;
		if (logged < 5) {
			logged++;
			float *s = (float *)tr, *e = (float *)(tr + 12);
			DMLog("fx", "impact effect trace hit nothing (%.0f %.0f %.0f -> %.0f %.0f %.0f, fraction %.2f) - treated as world",
				s[0], s[1], s[2], e[0], e[1], e[2], *(float *)(tr + 0x2c));
		}
		__try {
			void *list = *(void **)(g_base + (ENTLIST_PTR - PREF_BASE));
			if (list) *(void **)(tr + TR_ENT) = ((GetBaseEntity_t)(g_base + (FN_GETBASEENTITY - PREF_BASE)))(list, 0);
		} __except (EXCEPTION_EXECUTE_HANDLER) {
		}
	}
	g_orig(tr, color);
}

void DMFxInstall(HMODULE client)
{
	g_base = (DWORD)client;
	g_orig = (ColorForSurface_t)(g_base + (FN_COLORFORSURFACE - PREF_BASE));
	int n = 0;
	for (int i = 0; i < 3; i++) {
		BYTE *site = (BYTE *)(g_base + (CALL_SITES[i] - PREF_BASE));
		if (site[0] != 0xE8 || (DWORD)(site + 5) + *(DWORD *)(site + 1) != (DWORD)g_orig) {
			DMLog("fx", "call site %08lx mismatch - left alone", CALL_SITES[i]);
			continue;
		}
		DWORD old;
		VirtualProtect(site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
		*(DWORD *)(site + 1) = (DWORD)&ColorForSurfaceHook - (DWORD)(site + 5);
		VirtualProtect(site + 1, 4, old, &old);
		FlushInstructionCache(GetCurrentProcess(), site, 5);
		n++;
	}
	DMLog("fx", "surface colour wrapper on %d/3 call sites", n);
}

// Sound crash guard. engine.dll 0x20028de0 = the client's "sound by precache index" lookup: on a cache miss it reads
// the name from the sound string table and passes it to 0x201191e0 (skips the leading sound chars) from 0x20028e49.
// For an index the client doesn't have (seen twice: right after hits, once with a bat just given by console - late
// precache), the table hands back a garbage pointer and the game crashes in 0x201191e0 (dmcombat_crash.txt
// engine.dll+0x119200). The call goes through a wrapper: a bad name becomes a harmless empty sound, and is logged.
typedef const char *(__cdecl *SkipSoundChars_t)(const char *name);
static SkipSoundChars_t g_origSkip;

static const char *__cdecl SkipSoundCharsGuard(const char *name)
{
	if (!name || IsBadStringPtrA(name, 260)) {
		static int logged;
		if (logged++ < 10) DMLog("fx", "sound lookup with a bad name pointer %p - played as silence (crash avoided)", name);
		return "common/null.wav";
	}
	return g_origSkip(name);
}

void DMEngineSoundGuard()
{
	HMODULE eng = GetModuleHandleA("engine.dll");
	if (!eng) return;
	BYTE *base = (BYTE *)eng;
	IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
	if (nt->FileHeader.TimeDateStamp != 0x41afaf48) {
		DMLog("fx", "engine.dll is an unknown build - sound guard not installed");
		return;
	}
	BYTE *site = base + (0x20028e49 - 0x20000000);
	DWORD target = (DWORD)(site + 5) + *(DWORD *)(site + 1);
	if (site[0] != 0xE8 || target != (DWORD)base + (0x201191e0 - 0x20000000)) {
		DMLog("fx", "engine sound call site mismatch - guard not installed");
		return;
	}
	g_origSkip = (SkipSoundChars_t)target;
	DWORD old;
	VirtualProtect(site + 1, 4, PAGE_EXECUTE_READWRITE, &old);
	*(DWORD *)(site + 1) = (DWORD)&SkipSoundCharsGuard - (DWORD)(site + 5);
	VirtualProtect(site + 1, 4, old, &old);
	FlushInstructionCache(GetCurrentProcess(), site, 5);
	DMLog("fx", "engine sound crash guard installed");
}
