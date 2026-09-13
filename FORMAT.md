# The Two Worlds 1 save format

Everything here was measured on real save files — a retail game from 2018,
a modded game from 2026, and 98 saves in between — not taken from any
documentation. Where something is inferred rather than measured, it says so.

Offsets are decimal unless prefixed with `0x`. All integers are
little-endian. `u32` is a 4-byte unsigned integer. A **dstring** is `u32
length` followed by that many raw bytes (latin-1, no terminator). A
**wstring** is `u32 character count` followed by twice as many bytes
(UTF-16LE).

---

## 1. The file container

`%USERPROFILE%\Saved Games\Two Worlds Saves\NNNNNN.TwoWorldsSave`

```
0x0000  "RGMH"                     magic
0x0004  u32   1                    format version
0x0008  u32   0x2028               offset of the payload section
0x000C  u32   4
0x0010  u32   0
0x0014  u32   0x3130c              (varies; screenshot-related)
0x0018  GUID  16 B                 profile / player GUID
0x0028  wstring "Two Worlds"       plus padding to 0x2028
...
0x2028  u32   PNG length
0x202C  PNG data                   the screenshot shown in the load list
        ~87 B  uncompressed copy of the first bytes of the payload
        u32   length of the zlib stream that follows   ← critical
        zlib stream (78 9C, level 6, no dictionary) to end of file
```

**The four bytes immediately in front of the zlib stream are the length of
that stream.** The loader reads exactly that many compressed bytes and not
one more. This is the single most important fact in this document, and the
one that cost the most time: a repacked save whose payload grew keeps the
old, smaller length unless you rewrite it, so the game silently truncates
the stream. Under roughly 2 KB of overhang the cut lands in the trailing
zero padding and the save *loads*, but the hero cannot move; above that it
cuts into real data, a count field reads as garbage (0x3ffffffd was typical)
and the game crashes inside its array-growth routine at `0x42fd6a` or
`0x41bf20` (TwoWorldsExtended.exe 1.7).

The uncompressed ~87-byte block in front of the length is a verbatim copy of
the beginning of the payload. The game reads the save title from there for
the load list without decompressing anything.

---

## 2. The payload

Decompress the zlib stream and you get one flat byte stream, 2.9 MB for an
early game, over 6 MB late.

```
"SV\x01$"                          magic
dstring "1.7"                      engine version
wstring "Thalmont 06:15"           save title (what the load list shows)
u32  timestamp
u32  0
GUID 16 B                          TwoWorlds.par, the parameter file in use
u32  0xa0
u32  1
u32  mod count
   per mod:  dstring name ("Yamalin.wd")  +  GUID 16 B
<script record>  × 21
<cell block>     × 160
... object state, hero, inventory, world ...
```

The mod list is descriptive only. The game does not use it to decide what to
load; it is a record of which archives were active when the save was
written. A retail save has count 0.

---

## 3. Script records — why mods never reached old saves

This is the heart of it. A Two Worlds save does not reference the game
scripts, it **contains** them: the complete compiled image of each script,
followed by the current value of every global variable in that script.

```
u32   1
u32   variable-block size          == word 2 of the ECO header below
u32   heap pointer                 (differs in every save, ignore)
u32   0x11                         class id
u32   *                            varies
GUID  16 B                         ← the key the engine looks the script up by
"ECO\0" ...                        the complete .eco image, byte-identical
                                   to the body inside the .wd archive
u32   counter                      (varies)
u32   state index                  which state the script is in
u32   131072                       0x20000, constant
<globals>                          every global variable, in declaration
                                   order, no names, no type tags
<trailer>                          script-specific
```

The prefix layout `[1, variable-block size, heap, 0x11, *]` held for
**2058 of 2058 records** across 98 saves. The patcher uses it both to find
records and to validate them.

Variable encoding: `int` = i32, `unit` = u32 handle, `string` = dstring,
arrays (fixed and dynamic alike) = `u32 count` followed by the values. There
are no names and no type information — the script reads its variables back
positionally, in the order they are declared in the `.ec` source.

**That is the whole problem.** Install a quest mod and the archive has a new
script, but the save still carries the old bytecode *and* the old variable
values, and the engine keeps executing what is in the save. Proven on
12.09.2026: a campaign script inside a save was patched to set the player's
gold to 123456; loading that save and triggering the function produced
exactly 123456 gold. The code in the save runs, the code in the archive does
not.

### 3.1 What the patcher does with a record

If an enabled mod ships a script under the same archive path with a
different GUID:

* **Variable block same size** (`ECO header word 2` equals the prefix word)
  → replace GUID and image in place, keep the variables untouched. The new
  code reads the old variables, and because the layout did not change, every
  value lands in the field it belongs to.
* **Variable block different size** → the mod added, removed or retyped a
  global. The new code would read the old block shifted, putting garbage in
  every field after the change. No generic tool can repair this, because the
  bytecode carries no layout information (the images contain only string
  tables and native-call names, no variable names). The patcher reports the
  script as *partial* and leaves it alone, unless the mod declares a
  migration path (section 5).

The image length is not stored anywhere near the record. The patcher finds
it by scanning forward for the 12-byte head that follows every image
(`u32 < 1000`, `u32 < 16`, `u32 == 131072`).

---

## 4. GUIDs — the identity of everything

A `.wd` archive stores path, flags, class id and GUID **in its directory**,
not in the file body:

```
u8    path length
char  path, latin-1, backslashes
u8    flags
u32   offset, compressed length, raw length
flags & 0x08:  u8 length + resource name
flags & 0x10:  u32 class id
flags & 0x20:  GUID 16 B
```

The engine keys scripts by GUID (`CSMap<_GUID, CEarthCVM>` in the
executable), never by path. Three consequences, all of them measured:

1. **A script mod must carry a NEW GUID.** Ship your modified `PQuests.eco`
   under the original GUID and the engine keeps running the retail script.
   No error, no message, nothing in a log — the mod appears to do nothing.
   This cost three weeks on `Test5_SDK600.wd`: the 600-quest limit never
   took effect until the archive was rebuilt with a fresh `uuid4`. The
   official updates do the same thing; every newer version of a script in
   `Update16.wd` carries its own GUID (38 paths compared against Updates
   11–15).
2. **The GUID in the save is the link.** The patcher builds a catalogue of
   every GUID it can find — all `.wd` files in `WDFiles` plus all mods, 109
   GUIDs on a normal installation — and looks up each record's GUID in it.
   That tells it which script the record is, and therefore which mod file
   would replace it.
3. **Class id 0 is written by omitting flag 0x10**, not by writing a zero
   (`Unit.eco`, `UnitBase.eco` do this). Writing an explicit 0 produces
   something the game reads differently.

Packing tools get this wrong easily. If a packer sees an already-extracted
`.eco` and assigns `flags=0x01` (compressed only), the archive loads but the
engine cannot map the file to anything — again with no error. A correct
script entry has `flags=0x3b`: compressed + 0x02 + resource name + class id
+ GUID.

---

## 5. The migration path

A mod that changes the variable layout has to migrate itself, because only
the mod knows what its new variables mean. The Kira campaign does this and
the mechanism is open for anyone:

The mod places a plain-text file next to its script inside the `.wd`:

```
Scripts\Campaigns\Missions\PQuests.migrate
    quests=600
    waitmark=nCurrentStartingQuest=-1
```

The patcher then takes the `PQuests` route instead of a plain swap:

1. Grow every per-quest array from 400 to `quests` entries, filling new
   slots with the values a fresh game would have (`anQuestFlags = 4`,
   `anQuestLevel = -1`, `anQuestReputationGuild = 200`, and so on). 22 of
   the 116 `PQuests` globals scale with the quest count; the patcher knows
   which ones and verifies the result by re-parsing the record.
2. Set the wait mark — one word in the record's trailer,
   `nCurrentStartingQuest = -1`.
3. Swap GUID and bytecode as usual.

On the next tick the script sees the wait mark, re-reads the quest text file
from the archive, and adds everything the save does not know yet: new
quests, new NPC and container definitions, and the hooks that connect new
quests to old ones. Hooks whose trigger has already passed are fired once,
so a quest that should have been enabled by something you did hours ago
becomes available immediately. Then it clears the mark.

Why a declaration file rather than detection: the compiled image contains no
function names, so there is no way to see from the bytecode that a script
can migrate itself. Measured — the string table of the migrating script and
the retail one are identical.

Why a tick and not load time: `OnLoadLevel` fires *during* loading and
anything it does to the hero is overwritten by the position restore
afterwards. A state index changed inside the save is not entered on load
either. The only reliable trigger is the script's idle state, which runs
once the game is actually playing.

---

## 6. Cell blocks and markers

The save carries one block per map cell — 160 of them, the surface grid
A01–I12 plus the underworld `_1` cells:

```
u32×5  col, row, world Y, world X, path length
char   path        "Levels\Map_E01.lnd"
u32    a0          1 = this cell is the one currently loaded
u32    a1          1 = cell has been visited
<the data section of the .lnd file, verbatim>
   "LN\0\0", str16 name, 128, 128, 20 B, six neighbour dstrings,
   u32 marker count, u32 0,
   per marker: dstring name, u32 id, i32 x, i32 y, i32 z, u8 angle, 8 B spare
<rest: object state of the cell>
```

The marker list is the part mods change. A marker is what quest actions
point at: `OBJECT_CREATE` reads `MARKER_QUEST_CREATE_OBJECT`,
`ENEMY_CREATE` reads `MARKER_QUEST_CREATE_ENEMY`, teleports read
`MARKER_QUEST_TELEPORT`, gates read `MARKER_GATE`. Point an action at a
marker the save does not have and nothing happens — no error, no message.

### 6.1 The engine finds markers by binary search

Function `0x4a31e0` in TwoWorldsExtended.exe does a binary search over the
cell's marker array, comparing with `stricmp` (case-insensitive) on the name
and then the numeric id. Measured against a retail save: under
case-insensitive comparison **0 of 10226 markers are unfindable**; under
case-sensitive comparison 268 are.

That single fact explains a whole class of failures: **appending markers to
the end of the list does not work.** The search never looks there. Early
attempts did exactly that, the save loaded fine, and the new teleport simply
did not exist. Markers have to be *inserted at their sort position*.

### 6.2 What the patcher does per cell

For every cell that an enabled mod ships a map for, three lists are
compared: the list in the save, the list in the mod's `.lnd`, and the list
in the retail `Levels.wd`.

| Case | Action | Why |
|---|---|---|
| in mod, not in save | insert at its sort position | the mod added it |
| in retail and in save, not in mod | remove | the modder deleted it in the editor — typically a spawn point that would otherwise keep spawning enemies |
| in retail, in mod, but at a different position, and the save still has the retail position | move to the mod's position | the old editor makes deleting hard, so modders drag markers into an unused corner instead; nine dwarf spawners in the mine were moved this way |
| in save only, neither retail nor mod | keep | the game created it at runtime (`MARKER_NPC` for spawned characters, `MARKER_ENEMY_G_*` for roaming groups) |

The distinction in the last two rows matters. Without the retail list as a
third reference you cannot tell "the modder deleted this" from "the game
created this while playing", and removing the wrong one either leaves
respawning monsters or deletes live characters.

This works in visited and even in the currently loaded cell. An earlier
theory that visited cells cannot be touched came from the truncation bug in
section 1, not from the cells.

---

## 7. What the patcher does not touch

`.par` parameters, `.lan` texts and dialogue trees, textures, meshes,
minimaps, sounds. None of them live in a save; the game reads them from the
archives on every start, so a mod that only changes those already works in
an old save without any patching.

Quest *progress* is also untouched. Migration only adds. A quest you
finished stays finished, and a creature already standing in a cell you
visited stays there once — it just stops respawning, because the spawn
marker is gone.

---

## 8. Order of operations when patching

1. Read the save, decompress the payload.
2. If a `PQuests` migration is declared: grow the arrays, set the wait mark
   (this changes the record's length, so it happens first).
3. Swap the remaining scripts, **from the back of the payload forwards**, so
   earlier offsets stay valid while later ones are being rewritten.
4. Sync the marker lists of all mod cells, again from the back forwards.
5. Recompress, **write the new stream length in front of the stream**.
6. Verify: re-parse the payload, all 160 cell blocks readable, the same
   number of script records as before, and the plan for the patched save
   must come back empty.
7. Copy the original to `_vor_Mods\<timestamp>_<file>`, then replace the
   save in place.

Step 6 is not decoration. Every rule in this document was found by a test
that failed, and the cheapest way to catch a mistake is to ask the patched
save the same question again.

---

## 8a. Reading a list of saves quickly

The title shown in the load list can be read **without decompressing
anything**: the uncompressed block in front of the zlib stream is a copy of
the payload head and carries it. `tw1_save.quick_title()` does that — 98
saves in 0.01 s, against 0.9 s for full decompression and 11 s for a full
plan of all of them. The window therefore lists every save immediately and
fills in the *what would happen* column from a background thread.

Tkinter only accepts calls from the thread that owns the interpreter, so the
worker puts its results in a `queue.Queue` which the main thread drains on a
timer. Calling `root.after` from a worker raises *main thread is not in main
loop*.

## 9. Tools used to measure this

The facts above came out of four small tools, all in the QuestForge
workspace:

* a byte-level parser with a round-trip test — read a record, write it back,
  demand the bytes be identical
* `exe_dis.py`, a capstone-based disassembler wrapper for
  TwoWorldsExtended.exe (find callers, dump a function, resolve strings)
* `minidbg.py`, a ctypes debugger that attaches to the running game and
  dumps registers, stack and the stream object on an access violation
* `bplog.py`, a breakpoint logger that traces every read of the save stream
  with its position — this is what showed that the stream simply *ends* mid
  way through a well-formed payload, which pointed straight at the length
  field

The rule that made all of it work: measure it before claiming it. This
engine has no error log. A wrong marker, a missing line, a stale length
field all produce the same symptom — nothing happens — and every assumption
that is not measured costs half a day later.
