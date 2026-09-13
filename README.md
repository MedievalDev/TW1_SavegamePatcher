# TW1 Savegame Patcher

Bring existing **Two Worlds 1** (2007) save games up to the mods that are
currently enabled — as if you had started a new game with those mods, but
with your old progress.

A Two Worlds save does not only store your hero and the world state. It
stores **the compiled bytecode of all 21 game scripts together with every
one of their global variables**, and **the marker list of all 160 map
cells**. Everything a quest or map mod changes lives in exactly those two
places. That is why installing a quest mod never showed any effect in an
existing save: the game keeps running the code and the definitions frozen
inside the save file, not the ones in the archive.

This tool edits the save itself. It swaps the script bytecode, grows the
quest tables where a mod declares it, and merges the mod's map markers into
the cells. The original is backed up first.

Not tied to one mod — it reads whichever mods are enabled in the registry
and works out what each of them changes.

## What it does

| Inside the save | What the patcher does | Condition |
|---|---|---|
| Bytecode + variables of all 21 scripts | Replace GUID and bytecode with the mod's script, keep the variables | Variable block unchanged in size (ECO header word 2 == record prefix word 4) |
| `PQuests`, the quest script | Grow every per-quest array to the mod's quest count, set a wait mark; the script migrates its own quests on the next tick | Mod ships `Scripts\Campaigns\Missions\PQuests.migrate` with `quests=<n>` |
| A script that changes its variable layout, undeclared | Reported as *partial*, left untouched | — |
| Marker lists of 160 map cells | Per mod map: insert missing markers in the engine's sort order, drop markers the modder deleted, move relocated ones | Map ships in an enabled mod |
| Length field in front of the zlib stream | Rewritten | always |

Not stored in a save and therefore nothing to do: `.par` parameters, `.lan`
texts, textures, meshes, minimaps. Those reach an old save on their own.

## Limits

* Quests you already finished stay finished. Migration only adds what is new.
* Creatures already spawned in a cell you have visited stay there once.
  They stop respawning, because the spawn marker is gone or moved.
* A mod that adds or changes the global variables of a script cannot be
  patched generically — the bytecode carries no layout information. The mod
  has to declare it (see `.migrate` above).

## Run

* **Exe:** download `TW1_Savegame_Patcher.exe` from the
  [releases page](https://github.com/MedievalDev/TW1_SavegamePatcher/releases),
  no install. Windows SmartScreen may warn once because the file is
  unsigned (*More info → Run anyway*). Settings live in
  `%LOCALAPPDATA%\TW1SavegamePatcher\`.
* **Script:** Python 3.10 or newer, no third-party packages, then
  `python save_patcher.py`. Settings live next to the script.
* **Console self-test:** `python save_patcher.py --liste` prints the mod
  inventory and the full plan for every save without changing anything.

Close Two Worlds before patching. The game reads its load list only at
startup and holds the files open while running.

## How to use it

1. Install or update your mods and enable them in the game's mod list.
2. Start the patcher. It finds the game through the Steam library folders
   and the saves under `%USERPROFILE%\Saved Games\Two Worlds Saves`. Both
   can be set by hand under *File*.
3. Pick a save. The right-hand panel lists every single step that would be
   taken — which script is swapped, which cell receives which markers.
4. Press **Patch to active mods**. The original is copied to
   `_vor_Mods\<timestamp>_<file>` next to the saves; the save itself is
   replaced in place, so the load list in the game stays the same.
5. Start Two Worlds and load the save.

## Files

| File | Purpose |
|---|---|
| `save_patcher.py` | Window: list, plan, guided tour, menu bar, DE/EN switch |
| `patcher_core.py` | Engine: find game, read mods, locate records, build plan, apply |
| `theme.py` | Dark theme colours and ttk styles |
| `tw1_save.py` | Save container: header, preview, zlib payload, title, repack |
| `tw1_save_scripts.py` | Script records inside the payload, `PQuests` variable layout |
| `tw1_save_patch.py` | Quest array growth 400 → n, wait mark |
| `tw1_save_tiles.py` | Cell blocks and marker lists, sorted insert and sync |
| `tw1_lnd.py` | `.lnd` map files, marker section |
| `wd_metadaten.py` | `.wd` archive directory: paths, flags, GUIDs |

**[FORMAT.md](FORMAT.md)** documents the save format, the GUID mechanics and
every edit this tool makes, measured byte by byte — including the two
mistakes that cost days.

## Build the exe

`build_patcher_exe.bat` (PyInstaller, one file, no console). Result in
`dist\`.

## For mod authors

If your mod only changes quest text, markers, items or map content, nothing
is needed: the patcher handles it. If your script adds global variables,
ship a declaration next to the `.eco` inside your `.wd`:

```
Scripts\Campaigns\Missions\PQuests.migrate
    quests=600
    waitmark=nCurrentStartingQuest=-1
```

and let your script migrate itself when it sees the wait mark. See
FORMAT.md, section *Migration path*.

## Credits

Format work and tool by [MedievalDev](https://github.com/MedievalDev),
released under CC0, see `LICENSE`.

Links: [Alchemy Fox](https://alchemy-fox.de/) ·
[Guide](https://alchemy-fox.de/game/TW1_SavegamePatcher/) ·
[TW1 community server](https://twmp.alchemy-fox.de/)
