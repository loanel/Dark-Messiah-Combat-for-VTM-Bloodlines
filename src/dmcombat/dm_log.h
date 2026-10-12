// Logging to <game>\dmcombat.log (truncated per session, flushed per line).
#pragma once

void DMLogInit();
void DMLog(const char *cat, const char *fmt, ...);
