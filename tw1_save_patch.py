"""Alten Spielstand auf das Migrations-Skript umstellen.

Was der Patcher am PQuests-Datensatz aendert (sonst nichts):
  1. GUID  -> die des Migrations-Skripts (muss zur installierten Mod passen)
  2. Code  -> Body des Migrations-Skripts (600er Grenze + state Migrate)
  3. die 22 [eQuestsNum]-Arrays von 400 auf 600 verlaengert; Fuellwerte sind
     die InitQuests-Vorgaben, gemessen an Save 090000 (Index 400-599) und
     an den freien Retail-Indizes 381-399 - identisch
  4. Zustandsindex bleibt 3 (Nothing). Ein im Save umgestellter Zustand
     wird beim Laden nicht angestossen (gemessen 13.09.).
  5. nCurrentStartingQuest -> -1 als Wartemarke. Das Skript prueft sie in
     Timer1 und OnLoadLevel (MigrateIfPending), liest dann die qtx nach
     und setzt den Wert auf eQuestsNum - 100 zurueck.

Fortschritt (Queststaende, Dialogzustaende, Einheiten, Kisten, Orte, die
eingelesene qtx) bleibt byteweise erhalten. Geschrieben wird immer ein NEUER
Spielstand-Slot, das Original wird nicht angefasst.

CLI:
    py tw1_save_patch.py patch <save> <eco> <guid-hex> [--title TEXT]
    py tw1_save_patch.py check <save>
"""

import os
import struct
import sys

import tw1_save
import tw1_save_scripts as X

STATE_NOTHING = 3          # Initialize, Initialize1, StartingQuests, Nothing
MIGRATE_PENDING = -1       # Wartemarke in nCurrentStartingQuest
QUESTS_NEW = 600

# Fuellwerte je Array (siehe Kopf). Alles andere: 0 bzw. leer.
FILL = {
    'anQuestMission': -1,
    'anQuestFlags': 4,             # eAutoCloseOnSolve
    'anQuestLevel': -1,            # eQuestInitialLevel
    'anQuestGiverMapping': -1,     # eNoMapping
    'anQuestReputationGuild': 200, # eNoGuild
    'anQuestReputationLevel': -1,
}


class PatchError(Exception):
    pass


def _fill(name, typ):
    if typ == 'string':
        return b''
    return FILL.get(name, 0)


def patch_payload(payload, new_code, new_guid):
    rec = X.load_pquests(payload)
    if rec.quests_num == QUESTS_NEW and rec.guid == new_guid:
        raise PatchError('Spielstand hat dieses Skript schon')
    if rec.state_index != 3:
        raise PatchError(f'Zustandsindex {rec.state_index}, erwartet 3 (Nothing) - '
                         f'Stand wurde mitten im Start gespeichert?')
    if new_code[:4] != b'ECO\x00':
        raise PatchError('Bytecode beginnt nicht mit ECO')

    alt = rec.quests_num
    for name, typ, size in X.PQUESTS_VARS:
        if size != 'Q':
            continue
        arr = rec.vars[name]
        if len(arr) != alt:
            raise PatchError(f'{name}: {len(arr)} Eintraege statt {alt}')
        if alt < QUESTS_NEW:
            arr.extend(_fill(name, typ) for _ in range(QUESTS_NEW - alt))

    rec.guid = new_guid
    rec.code = new_code
    rec.quests_num = QUESTS_NEW
    # Nachspann: i32 nCurrentStartingQuest + Pfad + 25 u32 - nur das erste Wort
    tr = bytearray(rec.trailer)
    struct.pack_into('<i', tr, 0, MIGRATE_PENDING)
    rec.trailer = bytes(tr)

    out = X.replace_record(payload, rec)
    # Gegenprobe: neu einlesen, alles muss passen
    chk = X.find_record(out, new_guid, len(new_code), X.PQUESTS_VARS, X.PQUESTS_PATH)
    if chk.quests_num != QUESTS_NEW or chk.state_index != STATE_NOTHING:
        raise PatchError('Gegenprobe fehlgeschlagen')
    for name, typ, size in X.PQUESTS_VARS:
        if size == 'Q':
            continue
        if chk.vars[name] != rec.vars[name]:
            raise PatchError(f'Gegenprobe: {name} weicht ab')
    return out, rec, alt


def _cmd_patch(save_path, eco_path, guid_hex, title=None):
    sv = tw1_save.read(save_path)
    code = X._eco_body(open(eco_path, 'rb').read())
    guid = bytes.fromhex(guid_hex.replace('-', ''))
    if len(guid) != 16:
        raise PatchError('GUID muss 16 Byte sein')
    payload, rec, alt = patch_payload(sv.payload, code, guid)
    raw = tw1_save.Save(sv.repack(payload=payload))
    neu_titel = title or ('MIGRIERT ' + sv.title)
    raw = raw.with_title(neu_titel)
    pruef = tw1_save.Save(raw)
    if pruef.title != neu_titel or code not in pruef.payload:
        raise PatchError('Neupacken fehlgeschlagen')
    folder = os.path.dirname(save_path)
    slot = tw1_save.next_slot(folder)
    out = os.path.join(folder, slot)
    if os.path.exists(out):
        raise PatchError(f'{out} existiert schon')
    with open(out, 'wb') as f:
        f.write(raw)
    st = rec.vars['anQuestState']
    print(f'Quelle : {os.path.basename(save_path)}  {sv.title!r}  eQuestsNum {alt}')
    print(f'Skript : {os.path.basename(eco_path)} ({len(code)} B), GUID {guid.hex()}')
    print(f'Ziel   : {out}  {neu_titel!r}')
    print(f'         eQuestsNum {QUESTS_NEW}, Wartemarke gesetzt, '
          f'{sum(1 for s in st if s)} Quests mit Zustand > 0 uebernommen')
    return out


def _cmd_check(save_path):
    sv = tw1_save.read(save_path)
    rec = X.load_pquests(sv.payload)
    print(f'{os.path.basename(save_path)}  {sv.title!r}: GUID {rec.guid.hex()}, '
          f'eQuestsNum {rec.quests_num}, Zustand {rec.state_index}, '
          f'Code {len(rec.code)} B, qtx-Zeilen {len(rec.vars["astrLines"])}, '
          f'Aktivierungen {rec.vars["nActivationsNumber"]}')


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd = argv[1]
    try:
        if cmd == 'patch':
            if len(argv) < 5:
                print('patch <save> <eco> <guid-hex> [--title TEXT]')
                return 1
            title = None
            if '--title' in argv:
                title = argv[argv.index('--title') + 1]
            _cmd_patch(argv[2], argv[3], argv[4], title)
        elif cmd == 'check':
            _cmd_check(argv[2])
        else:
            print(f'unbekannt: {cmd}')
            return 1
    except (PatchError, X.ScriptError, tw1_save.SaveError) as e:
        print(f'FEHLER: {e}')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
