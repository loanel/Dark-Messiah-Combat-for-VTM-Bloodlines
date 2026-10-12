// Adrenaline in the save game. Bloodlines saves its Python global object __main__.G (quest flags) with every save, so
// the meter is mirrored into G.dmAdrenaline (tenths, int). A load replaces G: when G.dmAdrenaline no longer matches
// what we wrote last, the game was loaded (or a new one started) and the meter takes the saved value (0 if absent).
// Runs from the HUD paint, 5 times a second, on the game's main thread (same interpreter as the level scripts).
#include <windows.h>
#include <limits.h>
#include <stdio.h>
#include "dm_log.h"
#include "dm_shared.h"

typedef int(__cdecl *PyIsInit_t)();
typedef int(__cdecl *PyRun_t)(const char *code);
typedef void *(__cdecl *PyAddModule_t)(const char *name);
typedef void *(__cdecl *PyGetAttr_t)(void *obj, const char *name);
typedef long(__cdecl *PyAsLong_t)(void *obj);
typedef void(__cdecl *PyErrClear_t)();

static PyIsInit_t pIsInit;
static PyRun_t pRun;
static PyAddModule_t pAddModule;
static PyGetAttr_t pGetAttr;
static PyAsLong_t pAsLong;
static PyErrClear_t pErrClear;
static int g_written = INT_MIN;
static bool g_disabled;

static bool Bind()
{
	if (pRun) return true;
	HMODULE py = GetModuleHandleA("vampire_python21.dll");
	if (!py) {
		static bool logged;
		if (!logged) DMLog("save", "vampire_python21.dll not loaded yet");
		logged = true;
		return false;
	}
	pIsInit = (PyIsInit_t)GetProcAddress(py, "Py_IsInitialized");
	pRun = (PyRun_t)GetProcAddress(py, "PyRun_SimpleString");
	pAddModule = (PyAddModule_t)GetProcAddress(py, "PyImport_AddModule");
	pGetAttr = (PyGetAttr_t)GetProcAddress(py, "PyObject_GetAttrString");
	pAsLong = (PyAsLong_t)GetProcAddress(py, "PyInt_AsLong");
	pErrClear = (PyErrClear_t)GetProcAddress(py, "PyErr_Clear");
	if (!pIsInit || !pRun || !pAddModule || !pGetAttr || !pAsLong || !pErrClear) {
		pRun = NULL;
		g_disabled = true;
		DMLog("save", "python exports missing - adrenaline is not saved");
		return false;
	}
	return true;
}

// -2 = no game running (no G), -1 = G has no dmAdrenaline, else tenths of adrenaline.
static long ReadSaved()
{
	// Bloodlines' PyRun_SimpleString returns garbage instead of 0/-1 (seen: 20094, 20156...), so only the value read back
	// counts; it starts at -2 so a script that didn't run reads as "no G".
	pRun("import __main__\n"
	     "__main__.dmcSaved = -2\n"
	     "try:\n\t__main__.dmcSaved = int(__main__.G.dmAdrenaline)\n"
	     "except:\n\ttry:\n\t\t__main__.G\n\t\t__main__.dmcSaved = -1\n\texcept:\n\t\t__main__.dmcSaved = -2\n");
	void *mod = pAddModule("__main__");  // borrowed
	if (!mod) return -2;
	void *v = pGetAttr(mod, "dmcSaved");  // new reference; the module keeps its own, so it never drops to 0 here
	if (!v) {
		pErrClear();
		return -2;
	}
	long r = pAsLong(v);
	--*(int *)v;  // Py_DECREF (ob_refcnt at +0)
	return r;
}

void DMAdrenalineSync()
{
	static DWORD last;
	if (g_disabled) return;
	DWORD now = GetTickCount();
	if (now - last < 200) return;
	last = now;
	__try {
		if (!Bind()) return;
		static long lastState = -100;
		if (!pIsInit()) {
			if (lastState != -3) DMLog("save", "python not initialised");
			lastState = -3;
			return;
		}
		long saved = ReadSaved();
		if ((saved < 0 ? saved : 0) != lastState) {
			DMLog("save", "state: %s (G.dmAdrenaline %ld, last written %d)",
				saved == -2 ? "no G / python error" : saved == -1 ? "G without dmAdrenaline" : "G has dmAdrenaline", saved, g_written);
			lastState = saved < 0 ? saved : 0;
		}
		if (saved == -2) return;
		if (saved != g_written) {  // loaded a save / started a game: take its value
			float v = saved >= 0 ? saved / 10.0f : 0.0f;
			if (g_written != INT_MIN || v != g_dmSword.adrenaline)
				DMLog("save", "game loaded: adrenaline %.1f -> %.1f (from the save%s)", g_dmSword.adrenaline, v,
					saved < 0 ? ", none stored" : "");
			g_dmSword.adrenaline = v;
			g_written = saved;
		}
		int cur = (int)(g_dmSword.adrenaline * 10 + 0.5f);
		if (cur != g_written) {
			char code[96];
			sprintf(code, "import __main__\ntry:\n\t__main__.G.dmAdrenaline = %d\nexcept:\n\tpass\n", cur);
			pRun(code);
			static int logged;
			if (logged++ < 3) DMLog("save", "wrote G.dmAdrenaline = %d", cur);
			g_written = cur;
		}
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		g_disabled = true;
		DMLog("save", "exception syncing adrenaline with the save - disabled");
	}
}
