// Crash catcher: when the game dies on an unhandled exception, write <game>\dmcombat_crash.txt (exception, registers,
// stack with module+offset, the end of dmcombat.log) and <game>\dmcombat_crash.dmp (minidump via dbghelp), then hand
// the crash on to whatever handler was installed before (the game's own, or Windows).
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "dm_log.h"

typedef BOOL(WINAPI *MiniDumpWriteDump_t)(HANDLE, DWORD, HANDLE, int, void *, void *, void *);
struct MiniDumpExceptionInfo { DWORD threadId; EXCEPTION_POINTERS *ep; BOOL clientPointers; };

static LPTOP_LEVEL_EXCEPTION_FILTER g_prevFilter;
static volatile LONG g_inCrash;
static char g_dir[MAX_PATH];

static void Where(DWORD addr, char *out, size_t n)
{
	HMODULE mod = NULL;
	char name[MAX_PATH] = "?";
	if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
			(LPCSTR)addr, &mod) && mod) {
		GetModuleFileNameA(mod, name, sizeof(name));
		const char *b = strrchr(name, '\\');
		_snprintf(out, n, "%s+0x%lx", b ? b + 1 : name, addr - (DWORD)mod);
	} else {
		_snprintf(out, n, "?");
	}
	out[n - 1] = 0;
}

static void AppendLogTail(FILE *f)
{
	char path[MAX_PATH];
	_snprintf(path, sizeof(path), "%sdmcombat.log", g_dir);
	FILE *l = fopen(path, "rb");
	if (!l) return;
	fseek(l, 0, SEEK_END);
	long size = ftell(l), from = size > 6000 ? size - 6000 : 0;
	fseek(l, from, SEEK_SET);
	static char buf[6001];
	size_t n = fread(buf, 1, 6000, l);
	buf[n] = 0;
	fclose(l);
	const char *start = buf;
	if (from) {  // skip the partial first line
		const char *nl = strchr(buf, '\n');
		if (nl) start = nl + 1;
	}
	fprintf(f, "\n---- end of dmcombat.log\n%s\n", start);
}

static LONG WINAPI CrashHandler(EXCEPTION_POINTERS *ep)
{
	if (InterlockedExchange(&g_inCrash, 1) == 0) {
		char path[MAX_PATH], at[MAX_PATH];
		EXCEPTION_RECORD *er = ep->ExceptionRecord;
		CONTEXT *cx = ep->ContextRecord;
		DMLog("crash", "unhandled exception %08lx at %p - writing dmcombat_crash.txt", er->ExceptionCode, er->ExceptionAddress);
		_snprintf(path, sizeof(path), "%sdmcombat_crash.txt", g_dir);
		FILE *f = fopen(path, "w");
		if (f) {
			SYSTEMTIME t;
			GetLocalTime(&t);
			Where((DWORD)er->ExceptionAddress, at, sizeof(at));
			fprintf(f, "DMCombat crash report %04d-%02d-%02d %02d:%02d:%02d\n", t.wYear, t.wMonth, t.wDay, t.wHour,
				t.wMinute, t.wSecond);
			fprintf(f, "exception %08lx at %p (%s)\n", er->ExceptionCode, er->ExceptionAddress, at);
			if (er->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && er->NumberParameters >= 2)
				fprintf(f, "%s address %08lx\n", er->ExceptionInformation[0] == 1 ? "write to" : er->ExceptionInformation[0] == 8
					? "execute at" : "read from", (DWORD)er->ExceptionInformation[1]);
			fprintf(f, "eax %08lx ebx %08lx ecx %08lx edx %08lx esi %08lx edi %08lx\nebp %08lx esp %08lx eip %08lx\n",
				cx->Eax, cx->Ebx, cx->Ecx, cx->Edx, cx->Esi, cx->Edi, cx->Ebp, cx->Esp, cx->Eip);
			fprintf(f, "\n---- stack (code addresses)\n");
			DWORD *sp = (DWORD *)cx->Esp;
			for (int i = 0, shown = 0; i < 1024 && shown < 40; i++) {
				if (IsBadReadPtr(sp + i, 4)) break;
				DWORD v = sp[i];
				MEMORY_BASIC_INFORMATION mbi;
				if (v < 0x10000 || !VirtualQuery((void *)v, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT
					|| !(mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE)))
					continue;
				Where(v, at, sizeof(at));
				fprintf(f, "esp+%03x  %08lx  %s\n", i * 4, v, at);
				shown++;
			}
			AppendLogTail(f);
			fclose(f);
		}
		HMODULE dbg = LoadLibraryA("dbghelp.dll");
		MiniDumpWriteDump_t dump = dbg ? (MiniDumpWriteDump_t)GetProcAddress(dbg, "MiniDumpWriteDump") : NULL;
		if (dump) {
			_snprintf(path, sizeof(path), "%sdmcombat_crash.dmp", g_dir);
			HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
			if (h != INVALID_HANDLE_VALUE) {
				MiniDumpExceptionInfo mi = {GetCurrentThreadId(), ep, FALSE};
				dump(GetCurrentProcess(), GetCurrentProcessId(), h, 0x0 /* MiniDumpNormal */ | 0x40 /* WithIndirectlyReferencedMemory */,
					&mi, NULL, NULL);
				CloseHandle(h);
			}
		}
	}
	return g_prevFilter ? g_prevFilter(ep) : EXCEPTION_CONTINUE_SEARCH;
}

// Called at load and again once the game's modules are in (the engine may install its own filter in between; ours
// then chains to it).
void DMCrashInstall()
{
	if (!g_dir[0]) {
		GetModuleFileNameA(NULL, g_dir, sizeof(g_dir));
		char *b = strrchr(g_dir, '\\');
		if (b) b[1] = 0;
	}
	LPTOP_LEVEL_EXCEPTION_FILTER prev = SetUnhandledExceptionFilter(CrashHandler);
	if (prev != CrashHandler) {
		g_prevFilter = prev;
		DMLog("init", "crash catcher installed (previous handler %p)", prev);
	}
}
