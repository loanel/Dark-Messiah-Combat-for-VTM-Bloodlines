// Logging to <game>\dmcombat.log (truncated per session, flushed per line).
#pragma once

void DMLogInit();
void DMLog(const char *cat, const char *fmt, ...);

// <game>\<rel>: the folder of Vampire.exe, whatever the working directory the game was started with.
const char *DMGamePath(const char *rel, char *out, int size);
