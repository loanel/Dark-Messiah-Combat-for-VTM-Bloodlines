// Tiny hook helpers: module identity check and vtable slot replacement (no disassembler needed).
#pragma once
#include <windows.h>

// True when the loaded module's PE TimeDateStamp and SizeOfImage match the build we reverse-engineered.
bool DMModuleIs(HMODULE mod, DWORD timestamp, DWORD sizeOfImage);

// Replaces vtable[slot] (vtable given as its VA in the module's preferred base, rebased to the loaded base).
// Returns the original function, or NULL on failure.
void *DMHookVSlot(HMODULE mod, DWORD vtablePreferredVA, int slot, void *replacement);
