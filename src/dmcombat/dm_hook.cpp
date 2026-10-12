#include "dm_hook.h"
#include "dm_log.h"

static IMAGE_NT_HEADERS *NtHeaders(HMODULE mod)
{
	BYTE *b = (BYTE *)mod;
	return (IMAGE_NT_HEADERS *)(b + ((IMAGE_DOS_HEADER *)b)->e_lfanew);
}

bool DMModuleIs(HMODULE mod, DWORD timestamp, DWORD sizeOfImage)
{
	if (!mod) return false;
	IMAGE_NT_HEADERS *nt = NtHeaders(mod);
	return nt->FileHeader.TimeDateStamp == timestamp && nt->OptionalHeader.SizeOfImage == sizeOfImage;
}

void *DMHookVSlot(HMODULE mod, DWORD vtablePreferredVA, int slot, void *replacement)
{
	DWORD prefBase = NtHeaders(mod)->OptionalHeader.ImageBase;
	void **vt = (void **)((DWORD)mod + (vtablePreferredVA - prefBase));
	void **p = &vt[slot];
	DWORD old;
	if (!VirtualProtect(p, sizeof(void *), PAGE_READWRITE, &old)) {
		DMLog("hook", "VirtualProtect failed for vtable %08lx slot %d", vtablePreferredVA, slot);
		return NULL;
	}
	void *orig = *p;
	*p = replacement;
	VirtualProtect(p, sizeof(void *), old, &old);
	DMLog("hook", "vtable %08lx slot %d: %p -> %p", vtablePreferredVA, slot, orig, replacement);
	return orig;
}
