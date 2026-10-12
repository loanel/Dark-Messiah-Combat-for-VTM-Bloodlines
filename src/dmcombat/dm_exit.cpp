// Exit watchdog: on this system the game sometimes stays alive after quitting - no window, idle, main thread waiting
// inside the engine/NVIDIA driver shutdown (seen 2026-10-10; no DMCombat code on any thread). Once the game window has
// existed and then been gone for EXIT_GRACE_MS (saves and config are written before the window goes away), the
// process ends itself. dmcombat.ini exit_watchdog=0 turns it off.
#include <windows.h>
#include "dm_log.h"

int g_dmExitWatchdog = 1;
static const DWORD EXIT_GRACE_MS = 5000;

static BOOL CALLBACK FindOwnWindow(HWND hwnd, LPARAM found)
{
	DWORD pid = 0;
	GetWindowThreadProcessId(hwnd, &pid);
	if (pid == GetCurrentProcessId() && IsWindowVisible(hwnd) && !GetWindow(hwnd, GW_OWNER)) {
		*(bool *)found = true;
		return FALSE;
	}
	return TRUE;
}

static DWORD WINAPI Watchdog(LPVOID)
{
	bool hadWindow = false;
	DWORD goneSince = 0;
	for (;;) {
		Sleep(500);
		bool found = false;
		EnumWindows(FindOwnWindow, (LPARAM)&found);
		if (found) {
			hadWindow = true;
			goneSince = 0;
			continue;
		}
		if (!hadWindow || !g_dmExitWatchdog) continue;
		DWORD now = GetTickCount();
		if (!goneSince) goneSince = now;
		else if (now - goneSince > EXIT_GRACE_MS) {
			DMLog("exit", "game window gone for %lu ms and the process is still alive - ending it", now - goneSince);
			TerminateProcess(GetCurrentProcess(), 0);
		}
	}
}

void DMExitWatchdogStart()
{
	static bool started;
	if (started) return;
	started = true;
	HANDLE t = CreateThread(NULL, 0, Watchdog, NULL, 0, NULL);
	if (t) CloseHandle(t);
}
