// DMCombat: Dark Messiah style melee for Vampire: The Masquerade - Bloodlines.
// Game Mod Loader plug-in (.vtm): the loader LoadLibrary()s every Bin\loader\*.vtm and calls the
// exported loaded_<module>() functions right after each game module is loaded.
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "dm_log.h"
#include "dm_hook.h"
#include "dm_viewmodel.h"
#include "dm_data.h"
#include "dm_hitwindows.h"

void DMServerInstall(HMODULE server);
void DMHudInstall(HMODULE client);
void DMCrashInstall();
void DMFxInstall(HMODULE client);
void DMExitWatchdogStart();
void DMEngineSoundGuard();
void DMWarnConsole(const char *msg);

// The mod folder the game runs (-game <folder>, default Vampire). Bin\loader plug-ins load for every folder.
static const char *ModDir()
{
	static char mod[MAX_PATH];
	if (!mod[0]) {
		strcpy(mod, "Vampire");
		const char *g = strstr(GetCommandLineA(), "-game ");
		if (g) sscanf(g + 6, " %259s", mod);
	}
	return mod;
}

// Dark Messiah data (dmcombat_dm.bin, generated on the player's PC) and DMCombat's models in the running mod folder
// (install.py puts them into Unofficial_Patch): without both no hooks go in - the game plays as without DMCombat.
// (Started without -game Unofficial_Patch, the plug-in would otherwise drive weapons that have no arm model.)
static bool DataReady()
{
	static int state;  // 0 = not tried, 1 = ok, -1 = missing
	if (!state) {
		char arm[MAX_PATH];
		_snprintf(arm, sizeof(arm), "%s\\models\\weapons\\dm_katana\\v_dm_katana_arm.mdl", ModDir());
		arm[sizeof(arm) - 1] = 0;
		if (GetFileAttributesA(arm) == INVALID_FILE_ATTRIBUTES) {
			DMLog("init", "%s not found - DMCombat is installed for another mod folder (start with -game Unofficial_Patch); "
				"plug-in off", arm);
			state = -1;
		} else {
			state = DMDataLoad() && DMHitWindowsResolve() > 0 ? 1 : -1;
		}
	}
	return state > 0;
}

// The block is on the right mouse button. The installer moves "Cast Discipline Power" (vm_discipline) to Q
// (tools/make_keys.py); a player who binds it back to the right mouse casts while blocking - say so, don't fight it.
// Reads <mod>\cfg\config.cfg, mod = the -game folder (default Vampire).
static void CheckDisciplineBind()
{
	char path[MAX_PATH], line[512];
	_snprintf(path, sizeof(path), "%s\\cfg\\config.cfg", ModDir());
	path[sizeof(path) - 1] = 0;
	FILE *f = fopen(path, "r");
	if (!f) return;
	static const char BIND[] = "bind \"MOUSE2\" \"vm_discipline\"";
	while (fgets(line, sizeof(line), f))
		if (!_strnicmp(line, BIND, sizeof(BIND) - 1)) {
			DMLog("init", "Cast Discipline Power is bound to the right mouse button (%s) - it casts while blocking", path);
			DMWarnConsole("DMCombat: Cast Discipline Power is on the right mouse button, which blocks with melee weapons. "
				"Rebind it in Options > Keyboard (DMCombat's default: Q).\n");
			break;
		}
	fclose(f);
}

// Builds we reverse-engineered (Unofficial Patch install, 2026-10-09).
static const DWORD CLIENT_TIMESTAMP = 0x41afaf63, CLIENT_SIZE = 0x6e9000;
static const DWORD SERVER_TIMESTAMP = 0x41afafae, SERVER_SIZE = 0xab9000;

extern "C" void WINAPI loaded_vampire()
{
	HMODULE mod = GetModuleHandleA("vampire.dll");
	if (!DMModuleIs(mod, SERVER_TIMESTAMP, SERVER_SIZE)) {
		DMLog("init", "vampire.dll is an unknown build - server hooks disabled");
		return;
	}
	DMLog("init", "vampire.dll ok at %p", mod);
	if (!DataReady()) return;
	DMServerInstall(mod);
}

extern "C" void WINAPI loaded_client()
{
	HMODULE mod = GetModuleHandleA("client.dll");
	if (!DMModuleIs(mod, CLIENT_TIMESTAMP, CLIENT_SIZE)) {
		DMLog("init", "client.dll is an unknown build - client hooks disabled");
		return;
	}
	DMLog("init", "client.dll ok at %p", mod);
	if (!DataReady()) return;
	DMViewModelInstall(mod);
	DMHudInstall(mod);
	DMFxInstall(mod);
	DMExitWatchdogStart();
	DMEngineSoundGuard();
	DMCrashInstall();
	CheckDisciplineBind();
}

BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID)
{
	if (reason == DLL_PROCESS_ATTACH) {
		DMLogInit();
		DMLog("init", "dmcombat.vtm loaded");
		DMCrashInstall();
	}
	return TRUE;
}
