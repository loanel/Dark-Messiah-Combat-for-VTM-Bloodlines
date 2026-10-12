# How DMCombat was built with an AI coding agent: prompting guide and retrospective

DMCombat was built by one player and Claude (Anthropic's model, running in Claude Code) over three days in October 2026,
with a short follow-up session on a second PC on the fourth day (section 6).
The player directed and tested in game. Claude did the reverse engineering, wrote the code and tools, and ran the
builds.

The player hadn't written any of the code. What they brought was a clear goal, decisions, and very good in-game
feedback. This document is about that collaboration: how the requests were phrased, what worked, what didn't, and
what the numbers looked like. It's meant for anyone who wants to understand the repository, or to try a similar
project.

Quotes are the player's own prompts, typos included, with long ones shortened.

---

## 1. Usage statistics

| | Main project (DMCombat) | Earlier project (Dark Messiah sword in Half-Life 2, "DMHL2") |
|---|---|---|
| Dates | 2026-10-09 20:03 → 2026-10-11 12:46 (UTC) | 2026-10-06 16:34 → 2026-10-07 00:35 |
| Claude Code conversations | 1 long conversation, plus a 2-minute setup session (installing the modding skills plugin) | 1 conversation |
| Work blocks | 5. Two ended on the plan's usage limit ("I hit my usage limit…", "we have 5% left"), one on the end of the day | 1 evening |
| Context compactions | 2 (the conversation was summarised and continued) | 1 |
| Prompts by the player | 182 real prompts. Plus 12 "interrupted" markers where the player stopped Claude mid-task to correct course | 68 |
| Prompts per day | 42 / 109 / 31 | — |
| Prompt length | median 16 words, mean 31. 23 prompts over 60 words. 35 were one-liners like "start the game" or "done, check the log" | — |
| Model calls | ~1,400 (Claude Opus 5.5) | ~630 |
| Tool calls | ~1,370: shell commands ~1,100, file reads ~110, edits ~70, new files ~65, web searches/fetches ~12 | — |
| Output tokens (text and code Claude wrote) | ~1.25 million | ~0.59 million |
| Context read from cache | ~667 million tokens | ~282 million |
| Context written to cache | ~5.2 million tokens | ~1.8 million |
| Uncached input tokens | ~2,800 | ~1,300 |

**How to read the token numbers:**
- Every model call re-reads the whole conversation so far. Almost all of that comes from the prompt cache, which is
  cheap and fast; that's the "read from cache" column.
- The 667 million is therefore not 667 million words of work. It's the same growing conversation read about 1,400
  times. A long conversation costs more per call than a short one, which is one reason to start fresh sessions for
  separate tasks (section 5).
- "Output tokens" is roughly the amount Claude actually wrote: code, tools, documents and replies.
- The numbers were counted from the session transcripts at the time of writing. They don't include this document's
  own creation.
- The follow-up session of 2026-10-12 is counted separately in section 6.

**What came out of it:**
- a native game plug-in of 12 C++ modules, and 26 Python tools;
- 15 animated arm models covering 14 characters, 4 outfits each and 11 weapons;
- a 450-line development journal;
- review galleries of about 490 rendered images.

The step-by-step story is in [DMCombat_REPORT.md](DMCombat_REPORT.md).

---

## 2. The working loop

Almost every feature followed the same loop:

1. **Goal and constraints** (the player): what should happen in game, what must not change.
2. **Investigation and a plan** (Claude): what is possible, what the options cost. The player picks.
3. **Build** (Claude): code and tools, then compile, install and launch the game.
4. **Test in game** (the player): play, then report what looks or feels wrong.
5. **Fix**, then back to step 4.
6. **Close the feature**: "It works great… lets move on. What is left on the list?" Then the next goal.

The player kept the steering wheel the whole time. Claude proposed, the player decided. Most of the speed came from
steps 4–5 being very short. "Start the game" was the most common prompt, and later Claude restarted the game itself
after every build.

---

## 3. Prompting techniques that worked

### State the whole goal, the constraints and your prior work first
The first real prompt set the direction for three days:

> "I want to use the skills provided in this plugin and your capabilities to try and mod Vampire The Masquerade:
> Bloodlines. My goal is to replace the system of melee combat in the game … I'd like to incorporate the combat from
> Dark Messiah into the game … (i am willing to completely abandon third person view in VTM:B if it is necessary) …
> I also did a preliminary project where i moved the sword combat from Dark Messiah into Half Life 2 and it worked,
> the files from that session are also present … First I want you to … check the possibility of this"

It contained four things:
- the goal;
- what may be sacrificed (third person);
- where the earlier work lives, which Claude then reused: decompiled animations and the rules spec;
- a request for a feasibility check before any building.

The plan that followed (`MODDING_PLAN.md`) was approved, and its structure held to the end.

### Decide explicitly when given options
Claude often ended with numbered options or a list of leftovers. Short, explicit answers kept things moving:

> "Do 4 and 1, then start the game"

> "Point 2 is unnecessary, Point 1 we will do soon, regarding point 3 - white mass fix is unnecessary, aside from that
> do the fixes for bat, sledgehammer check, toreador outfit and the occult blade file"

Cutting scope is a decision too, and it saved a lot of work:

> "Regarding jump attack, i think it is unnecesarry, you don't really jump in this game. The rush attack would be good
> if there is a sprint, but i don't think there is so id also skip it. Same with the kick…"

### Give feedback in numbers when you can
Positioning the sword on screen took a few minutes because the feedback was quantitative:

> "Move it half as much up as you lowered it just now, the stabs are below the recticle"
> "I think the tilt is still too forward, move it 15 degress back"
> "Move it lower by 3 units" → "1 more unit lower" → "Its looking great now"

The same went for balance:

> "Make the normal swings do 75% of the normal damage, the power attacks should have the same multiplier as in Dark
> Messiah"

> "Make them all 7.5, the two hit can deal double damage as it has less aoe and reach than the other two."

### Describe symptoms and how to reproduce them, not guessed causes
> "I think the issue is that after i myself get hit, my damage stops registering…"
> "I reproduced it now, its clear that even with god mode on, after i get hit and start swinging without moving at all
> the hits dont register for a period of time"

That reproduction led straight to a hidden 1–1.7 s "hit recoil" lockout in the game's code, and a workaround.

### Batch a whole test round into one message
The most productive single prompt of the project was one message reporting every character and outfit at once:

> "Gangrel male hand on armors 1-3 has an empty space in the texture … For malkavian male, models 2 and 3 have gloves
> … we have to use the older approach. For malkavian female, same applies for models 1 to 3. Nosferatu male similar
> problem to gangrel on models 1-2, model 3 has gloves … Tremere male 2 has the hand kind of inside the armor
> texture…"

Each item named exactly where the problem was (character, outfit number) and what kind it was. That allowed one
rebuild instead of a dozen round trips.

### Show it: screenshots and side-by-side comparisons
> "On the first screen you have the katana with brujah heavy leather, on the second you have the katana with brujah
> light clothing. It's clear that on light clothing the hand looks better…"

A comparison pair made the difference obvious and the investigation focused: a cuff bound to the wrist bone.

### Ask for research before building
> "is there some sword animation in the Dark Messiah animations that would fit as the adrenaline attack for stab
> power attacks?"

> "Can you do some reasearch if it would be possible to extract the LOOk itself of the right hand from those
> models … First try to do it for base look of a toreador that i'm currently playing"

Asking for research, and for a small first case ("first … a toreador"), kept experiments cheap before scaling them up
to 14 characters.

### Ask for tools that remove manual work
The biggest multiplier in the project. Instead of checking 56 outfits × 11 weapons by hand in game:

> "Can you show the meshes on some images so i don't have to check them all manually again?"
> "Can you do these kinds of renders for every melee weapon … make a folder with them"

> "Are there any console commands where i can on the fly change my clan? … i want to somehow expedite the testing
> process"

> "Can we somehow make it so that you run the compile, i don't want to copy paste the directories and click it 30 times"

> "Do the restart for me, its annoying with this amount of tries"

Each of these turned repeated manual work into a command or a contact sheet.

### Ask "why" and ask for explanations
> "Ok but why are we doing all this, can you explain again? It's pretty much working, do you want to make some
> complex logic…"

> "How does this mod work currently? What is this server/client thing you speak about?"

> "Can you make me a general overview … I want to explain how this was achieved to a non technical person"

Questioning a direction is cheap, and once it prevented over-engineering. The player then chose the more ambitious
option on purpose: "Keep the safer option in mind but lets try for a bit more".

### Check claims
> "Are you sure it is installed? It looks like the Dark Messiah arm still"
> "Are you sure its 11.9? I downloaded v12"

Both times the player was right: the install had silently not happened, and the version had been misread. Your own
observations beat the agent's confidence.

### Set principles early and restate them when they matter
> "i actually wanted to make it so that someone HAS to have both of the games to run this mod. They are cheap anyway
> and the original developers should be supported."

> "I don't like providing exes to people, it might be dangerous"

> "Fix it so that no data from Dark Messiah or VTMB is on the repository/mod location."

These shaped the whole deployment design: an installer that builds everything from the player's own copies of both
games, readable scripts instead of an `.exe`, and a repository with no game data.

---

## 4. What could have been better

### On Claude's side
- **Verify outputs, not counts.** The worst moment of the project:
  - What happened: a batch build of the arm models died silently at one character. The check only counted files,
    so six characters kept old-format models.
  - What the player saw: a black stretched bar on screen and a moved katana. The player had tested and approved that
    katana, so this looked like a regression in finished work: "it was working perfectly, it shouldn't be changed".
  - What fixed it for good: builds that fail loudly, and reading the installed files back.
  - Lesson: after changing shared code, re-test the feature that was already approved.
- **Don't trust a quick reading.** The Unofficial Patch version was taken from the first matching line of a readme
  (11.9) instead of the newest entry (12.0). Several "is it installed?" moments came from installing through a mapped
  drive path that silently did nothing. Both became standing rules: install from the real path and compare the
  files afterwards.
- **Be honest about what a test showed.** One check (searching the plug-in for a byte pattern) was invalid because
  the pattern itself was wrong. That was caught, but it's a reminder: a negative result from a broken test proves
  nothing.
- **Previews should match what the player sees.** Early flat-shaded previews used a camera unlike the game's, and
  were hard to judge. The textured contact sheets came late. Built at the start of the arm work, they would have
  saved several game restarts.
- **Fewer fragile one-off edits.** A lot of time went to shell-quoting problems in throwaway patch scripts.
  Simpler direct edits, or scripts saved as files, would have been faster.
- **Plan for distribution from day one.** Dark Messiah's animation data was compiled into the plug-in for convenience
  and had to be pulled out at the end. The "nothing from either game in the release" rule was known on day 2, and
  should have shaped the code right then.

### On the prompting side (suggestions, not criticism)
The player's prompting was effective overall. A few things would have saved round trips:
- **Name the exact case when reporting.** "Some of the armors seem … distorted (on the brujah…)" took an
  investigation to pin down. The later "Brujah male, heavy leather, katana, screenshot" form was much faster.
- **Say when a choice is final.** "I think 6 looks best" → "Sorry, i picked the wrong option, i meant option 3" is
  harmless, but it caused a rebuild. "Option 3, final" removes the ambiguity.
- **Mention environment events.** Windows update restarts, closing the game, and GeForce Now recording each looked
  like bugs for a moment. "I closed the game", or "Windows tried to restart", is a useful heads-up.
- **Interrupting is fine and was used well** (12 times), mostly to add a detail just remembered. Combining the
  follow-up into one complete message after interrupting, as the player usually did, keeps the agent from acting on
  half a request.

### On the process
- Keep a short **regression list** of approved features (katana placement, parry timing, adrenaline save) and
  re-check it after big changes.
- Start a **fresh session** for clearly separate phases (combat → arm models → weapons → packaging), handing over
  through the journal (`MODLOG.md`) and the project notes. Long conversations get slower and more expensive per call,
  and two forced summaries risk losing detail.
- Set up **test shortcuts** (quicksave with the right gear, console commands for items, characters and levels) at
  the start. They came gradually and each one sped testing up noticeably.

---

## 5. Templates to reuse

**Starting a project**
> Goal: <what should happen in game>. Constraints: <what may not change / may be sacrificed>. Prior work: <where,
> what>. First: check feasibility and give me options with trade-offs, don't build yet.

**Reporting a test round**
> Tested <build/feature>. Works: <list>. Problems: <case 1: where exactly + what you see + how to reproduce>, <case 2
> …>. Screenshot attached for <case>. Priority: <which first>.

**Tuning**
> <Thing> should be <direction> by <amount> (e.g. "lower by 3 units", "75% of normal damage").

**Steering**
> Do <items>. Skip <items> because <reason>. Explain <x> before we decide on <y>.

**Before shipping**
> Check that <principle> holds everywhere (e.g. "no files from either game in the repository"). Prove it, don't
> just tell me.

---

## 6. The follow-up session on a second PC (2026-10-12)

The project moved to another computer through the handoff zip, and a new Claude Code session picked it up from there.

| | Follow-up session |
|---|---|
| Time | 2026-10-12 08:03 → about 11:00 (UTC), with long breaks for playing |
| Conversations | 1, no compactions |
| Prompts by the player | 14 (one interrupted and rephrased) |
| Model calls | ~170 (Claude Opus 5.5), measured before this documentation step |
| Tool calls | ~165, almost all shell commands |
| Output tokens | ~0.11 million |
| Context read from cache | ~34 million tokens |

**What it produced:** the torch flame fix, the discipline key move, the first-person lock, an answer on skill
requirements, a pre-release audit with two real installer bugs fixed, and these document updates.

### How the session was prompted

1. **Resume from the handoff, not from memory.**
   > "Check these folders and md files to find a guide and orient yourself in the project."

   The handoff notes, journal and copied project memory were enough to rebuild everything on the new PC without
   re-deriving anything. The short session length is mostly thanks to the written journal of the earlier sessions.
2. **Remembered problems, described by symptom.**
   > "the flame texture was working incorrectly, it was place on the character instead of inside the torch"

   One sentence of what was seen was enough to trace the cause through the game code. The cause turned out to be
   somewhere else entirely (the flame follows an invisible model), which a guessed cause would have hidden.
3. **Small practical requests during testing.** "give me the command to teleport to the level we were testing in",
   "run the game again". The answers came from the old session's transcript, which was part of the handoff.
4. **Report crashes as you saw them.** "I pressed f9 which should quicksave and it crashed i think". Claude captured
   the frozen game's thread stacks before killing it, and could show that the mod's code wasn't involved.
5. **Challenge the proposal.** When Claude offered to switch the discipline key in the plug-in, the player asked:
   > "what if someone rebinds it themselves to something else? Will it still be R this way?"

   That question exposed a design flaw: the plug-in would have hardcoded the key. The result was a better design,
   an ordinary game keybind with a new default. Questions like this are worth asking whenever a change touches
   something players can configure.
6. **Short decisions.** "Go with Q", "Leave it as vanilla". Claude's options came with a recommendation, so a decision
   took one line.
7. **Compare with what already works.** "This is disabled while holding a gun with first person. I'd like to make it
   disabled with our melee weapons only too". Pointing at the gun behaviour gave the exact target, and it led straight
   to the game's own camera class.
8. **Ask whether the mod respects the game's rules.** "certain melee weapons have melee requirement attached to them
   but for now i can equip them all". Claude checked the game code first and found vanilla doesn't lock them either,
   so nothing needed changing.
9. **State the release principles again before shipping.**
   > "we don't want our repository to do any downloads ... I don't want any malicous connecitons to the internet, it
   > would be best if the mod worked offline"

   The audit then searched for exactly those things, and found two real installer bugs along the way.

### What could have been better
- **On Claude's side:** a first answer suggested a key without checking it was free (R is reload); the keybind lists
  should have been read first. The audit also showed that an installer bug (arm models gated on an obsolete file)
  survived the earlier sessions, because the old file was always present on the first PC. A test install into a
  clean copy of the game would have caught it.
- **On the process:** a clean test installation (planned next) is the real check that the repository works for
  someone else.

---

## 7. Glossary
- **Plug-in (`.vtm`):** a DLL that the Unofficial Patch's Game Mod Loader loads into the game. DMCombat's code lives
  here.
- **Server / client:** Bloodlines runs the game logic (hits, damage, enemies) and the presentation (screen, sounds,
  HUD) as two halves in the same process. DMCombat hooks both.
- **Viewmodel:** the first-person model of what you hold. DMCombat replaces it with an animated arm driven by Dark
  Messiah's animations.
- **Reverse engineering:** reading the game's compiled code (with Ghidra) to find the functions to hook.
- **Context compaction:** when a conversation gets too long, Claude Code summarises it and continues. Details can get
  lost, which is why the project keeps a written journal.
