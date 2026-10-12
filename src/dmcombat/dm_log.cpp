#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
#include "dm_log.h"

static FILE *g_log;
static CRITICAL_SECTION g_cs;

void DMLogInit()
{
	InitializeCriticalSection(&g_cs);
	g_log = fopen("dmcombat.log", "w");  // cwd = game root (Vampire.exe folder)
}

void DMLog(const char *cat, const char *fmt, ...)
{
	if (!g_log) return;
	EnterCriticalSection(&g_cs);
	fprintf(g_log, "%8lu [%s] ", GetTickCount(), cat);
	va_list ap;
	va_start(ap, fmt);
	vfprintf(g_log, fmt, ap);
	va_end(ap);
	fputc('\n', g_log);
	fflush(g_log);
	LeaveCriticalSection(&g_cs);
}

// Prints to the game console through tier0's Warning() (the same export the game DLLs use).
void DMWarnConsole(const char *msg)
{
	typedef void (*Warning_t)(const char *, ...);
	static Warning_t warn = (Warning_t)GetProcAddress(GetModuleHandleA("tier0.dll"), "Warning");
	if (warn) warn("%s", msg);
}
