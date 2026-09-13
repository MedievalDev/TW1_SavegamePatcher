"""Skript-Datensaetze in Two-Worlds-1-Spielstaenden lesen und schreiben.

Gemessen am 13.09.2026 an Save 000000 (Thalmont, 14.07.2018, reines
Retail) und den 600er-Saves. Der Payload traegt fuer jedes der 21 geladenen
EarthC-Skripte einen Datensatz:

    [32 B Vorspann][GUID 16 B][.eco-Body, byteidentisch][12 B Kopf]
    [Variablen in Deklarationsreihenfolge][Nachspann: u32, Pfad, 25 u32]

Kopf nach dem Code: u32 (Zaehler, 18/9/6 - je nach Save), u32 Zustandsindex
(3 = Nothing), u32 (131072). Danach beginnen die Variablen direkt mit
nCurrentThiefUID.

Variablen-Kodierung (belegt ueber Round-Trip):
    int            i32
    unit           u32 Handle (4 B - auEscapeUnit[99] endet genau vor
                   nEscapeUnits/nEscapeUnitsCounter/50)
    string         u32 Laenge + Bytes (Delphi-ASCII)
    T[N], T[]      u32 Zaehler + Zaehler x T   (auch bei fester Groesse)

Die Deklarationsreihenfolge kommt aus dem Praeprozessorlauf ueber PQuests.ec
(117 Variablen, `pq_vars.txt`; die letzte liegt nicht im Save); hier fest eingetragen, weil sie fuer ein
gegebenes Skript nie wechselt. Wer das Skript aendert und Globale hinzufuegt,
muss die Liste nachziehen - der Parser merkt es, weil der Nachspann dann nicht
mehr an der erwarteten Stelle liegt.

Das Spiel fuehrt beim Laden den Code aus dem Save aus (Vorversuch 12.09.:
getauschtes Kampagnenskript, `ec.dbg ModCheck` -> Gold 123456).
"""

import os
import struct
import sys
import zlib

import tw1_save

PQUESTS_PATH = b'Scripts\\Campaigns\\Missions\\PQuests.eco'
PQUESTS_RETAIL_GUID = bytes.fromhex('6897529988c50c4a815cac49f126bdb6')
PQUESTS_600_GUID = bytes.fromhex('c047c090c96e4e4a82b7244cffc2c289')

# (Name, Typ, Groesse) - Groesse: None = Skalar, 'dyn' = [], sonst Konstante.
# eQuestsNum wird beim Lesen aus dem ersten Zaehler uebernommen (400/600).
PQUESTS_VARS = [
    ('nCurrentThiefUID', 'int', None),
    ('auEscapeUnit', 'unit', 99),
    ('nEscapeUnits', 'int', None),
    ('nEscapeUnitsCounter', 'int', None),
    ('anMQGMaleNames', 'int', 50),
    ('nMQGMaleCurrentName', 'int', None),
    ('anMQGFemaleNames', 'int', 50),
    ('nMQGFemaleCurrentName', 'int', None),
    ('auTmpArray', 'unit', 1),
] + [(n, 'int', 'Q') for n in (
    'anQuestState', 'anQuestType', 'anQuestMission', 'anQuestGroup',
    'anQuestFlags', 'anQuestLevel', 'anQuestEnableLevel', 'anQuestObjectsNum',
)] + [
    ('astrQuestObject', 'string', 'Q'),
] + [(n, 'int', 'Q') for n in (
    'anQuestMarker', 'anQuestParty', 'anQuestRange', 'anQuestUnitMapping',
    'anQuestGiverType', 'anQuestGiverMapping', 'anQuestGiverMarker',
    'anQuestGiverMarkerMission', 'anQuestGiverRange', 'anQuestDialogState',
    'anQuestReputationGuild', 'anQuestReputationLevel',
)] + [
    ('anPlaceMarker', 'int', 'dyn'), ('anPlaceMission', 'int', 'dyn'),
    ('anPlaceRange', 'int', 'dyn'), ('anPlaceState', 'int', 'dyn'),
    ('anPlaceQuest', 'int', 'dyn'), ('nPlacesNumber', 'int', None),
    ('anQuestMapSign', 'int', 15),
    ('anDoActionsOnSolveAfterDialog', 'int', 8),
    ('anContainerLockpicked', 'int', 8),
    ('anShowMessageBox', 'int', 8),
    ('anQuestGateMission', 'int', 'dyn'), ('anQuestGateNumber', 'int', 'dyn'),
    ('auGates', 'unit', 'dyn'), ('nQuestGatesNumber', 'int', None),
    ('auDoors', 'unit', 'dyn'),
    ('auQuestUnits', 'unit', 'dyn'), ('astrUnitName', 'string', 'dyn'),
    ('anUnitNameTranslate', 'int', 'dyn'), ('anUnitMission', 'int', 'dyn'),
    ('anUnitNumber', 'int', 'dyn'), ('astrUnitItems', 'string', 'dyn'),
    ('astrUnitItemsAdd', 'string', 'dyn'),
    ('astrUnitItemsRemove', 'string', 'dyn'),
    ('anUnitState', 'int', 'dyn'), ('anQuestUnitIsDead', 'int', 'dyn'),
    ('astrUnitCreateString', 'string', 'dyn'), ('anUnitParty', 'int', 'dyn'),
    ('anUnitAngle', 'int', 'dyn'), ('anUnitStandardDialog', 'int', 'dyn'),
    ('astrUnitMagicCard', 'string', 'dyn'), ('nMappingsNum', 'int', None),
    ('astrContainerName', 'string', 'dyn'), ('anContainerMission', 'int', 'dyn'),
    ('anContainerNumber', 'int', 'dyn'),
    ('astrContainerItemsAdd', 'string', 'dyn'),
    ('astrContainerItemsRemove', 'string', 'dyn'),
    ('nContainersNumber', 'int', None),
    ('anActivationQuest', 'int', 'dyn'), ('anActivationType', 'int', 'dyn'),
    ('anActivationWhen', 'int', 'dyn'), ('anActivationParam', 'int', 'dyn'),
    ('nActivationsNumber', 'int', None),
    ('anActionType', 'int', 'dyn'), ('anActionQuest', 'int', 'dyn'),
    ('anActionWhen', 'int', 'dyn'), ('anActionMission', 'int', 'dyn'),
    ('anActionUnitMapping', 'int', 'dyn'), ('anActionMarker', 'int', 'dyn'),
    ('anActionParam1', 'int', 'dyn'), ('anActionParam2', 'int', 'dyn'),
    ('anActionParam3', 'int', 'dyn'), ('anActionParam4', 'int', 'dyn'),
    ('astrActionString', 'string', 'dyn'),
    ('astrActionContainer', 'string', 'dyn'),
    ('anActionDelay', 'int', 'dyn'), ('anActionTimer', 'int', 'dyn'),
    ('nCurrentAction', 'int', None),
    ('anOnLoadLevelActions', 'int', 'dyn'),
    ('nOnLoadLevelActionsNumber', 'int', None),
    ('anDelayedActions', 'int', 'dyn'), ('nDelayedActionsNumber', 'int', None),
    ('anRewardQuest', 'int', 'dyn'), ('anRewardType', 'int', 'dyn'),
    ('anRewardWhen', 'int', 'dyn'), ('anRewardQuantityType', 'int', 'dyn'),
    ('anRewardQuantity', 'int', 'dyn'), ('astrRewardObject', 'string', 'dyn'),
    ('anRewardParam1', 'int', 'dyn'), ('nCurrentReward', 'int', None),
    ('nCurrentQuest', 'int', None), ('nCurrentUnit', 'int', None),
    ('nCurrentContainer', 'int', None), ('nCurrentLine', 'int', None),
    ('nLinesNum', 'int', None),
    ('astrLines', 'string', 'dyn'), ('astrArgs', 'string', 'dyn'),
    ('astrLocationName', 'string', 'dyn'),
    ('anLocationX', 'int', 'dyn'), ('anLocationY', 'int', 'dyn'),
    ('anLocationMission', 'int', 'dyn'), ('anLocationRange', 'int', 'dyn'),
    ('anLocationVisibleByHero', 'int', 'dyn'), ('anLocationSign', 'int', 'dyn'),
    ('nLocationsNum', 'int', None),
    ('nQuestsOn', 'int', None),
    ('anQuestHeroFlag', 'int', 'Q'),
    # nCurrentStartingQuest (die 117. Globale) liegt NICHT im Save: der
    # Nachspann (u32 300, Pfad) folgt direkt auf anQuestHeroFlag. Gemessen
    # an Save 000000, alle anderen 116 treffen ihre Anker exakt.
]
assert len(PQUESTS_VARS) == 116

HEAD_LEN = 12          # u32 x3 nach dem Bytecode (Zaehler, Zustand, ?)
PREFIX_LEN = 32        # vor der GUID
TRAILER_WORDS = 25     # u32 nach dem Pfad-String


class ScriptError(Exception):
    pass


class _Reader:
    def __init__(self, data, pos):
        self.d = data
        self.pos = pos

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.pos)[0]
        self.pos += 4
        return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.pos)[0]
        self.pos += 4
        return v

    def dstr(self):
        n = self.u32()
        s = self.d[self.pos:self.pos + n]
        if len(s) != n:
            raise ScriptError(f'String laeuft ueber das Ende (@{self.pos:#x})')
        self.pos += n
        return s


def _rd_value(r, typ):
    if typ == 'int':
        return r.i32()
    if typ == 'unit':
        return r.u32()
    if typ == 'string':
        return r.dstr()
    raise ScriptError(typ)


def _wr_value(out, typ, v):
    if typ == 'int':
        out += struct.pack('<i', v)
    elif typ == 'unit':
        out += struct.pack('<I', v)
    elif typ == 'string':
        out += struct.pack('<I', len(v)) + v
    else:
        raise ScriptError(typ)


class ScriptRecord:
    """Ein Skript-Datensatz im Payload.

    prefix   32 B vor der GUID (unveraendert durchreichen)
    guid     16 B
    code     der .eco-Body
    head     12 B (u32 ?, u32 Zustandsindex, u32 ?)
    vars     {Name: Wert | Liste}
    sizes    {Name: Zaehler} fuer Arrays (auch feste)
    trailer  Rohbytes ab dem Nachspann-u32 bis zum Ende des Datensatzes
    start/end  Grenzen im Payload (start = Beginn des Vorspanns)
    """

    __slots__ = ('prefix', 'guid', 'code', 'head', 'vars', 'sizes',
                 'trailer', 'start', 'end', 'layout', 'quests_num')

    @property
    def state_index(self):
        return struct.unpack_from('<I', self.head, 4)[0]


def _parse_vars(r, layout):
    vars_, sizes = {}, {}
    q = None
    for name, typ, size in layout:
        if size is None:
            vars_[name] = _rd_value(r, typ)
            continue
        n = r.u32()
        if size == 'Q':
            if q is None:
                q = n
            elif n != q:
                raise ScriptError(f'{name}: Zaehler {n}, erwartet eQuestsNum {q}')
        elif size != 'dyn' and n != size:
            raise ScriptError(f'{name}: Zaehler {n}, erwartet {size}')
        vars_[name] = [_rd_value(r, typ) for _ in range(n)]
        sizes[name] = n
    return vars_, sizes, q


def _emit_vars(layout, vars_):
    out = bytearray()
    for name, typ, size in layout:
        v = vars_[name]
        if size is None:
            _wr_value(out, typ, v)
        else:
            out += struct.pack('<I', len(v))
            for x in v:
                _wr_value(out, typ, x)
    return bytes(out)


def find_record(payload, guid, code_len, layout=PQUESTS_VARS, path=None):
    """Datensatz mit dieser GUID lesen und die Lage gegen den Nachspann pruefen."""
    g = payload.find(guid)
    if g < 0:
        raise ScriptError('GUID nicht im Payload')
    if payload.find(guid, g + 1) >= 0:
        raise ScriptError('GUID mehrfach im Payload')
    rec = ScriptRecord()
    rec.layout = layout
    rec.start = g - PREFIX_LEN
    rec.prefix = payload[rec.start:g]
    rec.guid = guid
    a = g + 16
    rec.code = payload[a:a + code_len]
    if rec.code[:4] != b'ECO\x00':
        raise ScriptError(f'Bytecode beginnt nicht mit ECO (@{a:#x})')
    r = _Reader(payload, a + code_len)
    rec.head = payload[r.pos:r.pos + HEAD_LEN]
    r.pos += HEAD_LEN
    rec.vars, rec.sizes, rec.quests_num = _parse_vars(r, layout)
    # Nachspann: u32, dstring Pfad, 25 u32
    t0 = r.pos
    r.u32()
    got_path = r.dstr()
    if path is not None and got_path != path:
        raise ScriptError(f'Nachspann-Pfad {got_path!r}, erwartet {path!r} - '
                          f'Variablenlayout passt nicht')
    r.pos += 4 * TRAILER_WORDS
    rec.trailer = payload[t0:r.pos]
    rec.end = r.pos
    return rec


def emit_record(rec):
    return (rec.prefix + rec.guid + rec.code + rec.head
            + _emit_vars(rec.layout, rec.vars) + rec.trailer)


def replace_record(payload, rec):
    """Payload mit neu serialisiertem Datensatz an derselben Stelle."""
    return payload[:rec.start] + emit_record(rec) + payload[rec.end:]


MODS_DIR = 'F:/SteamLibrary/steamapps/common/Two Worlds - Epic Edition/Mods'


def known_pquests_builds():
    """{GUID: Codelaenge} aller bekannten PQuests-Fassungen: Update16 und jede
    PQuests.eco in Mods/*.wd (dort steht die GUID, die auch im Save liegt)."""
    aus = {PQUESTS_RETAIL_GUID: 144343}
    try:
        import wd_metadaten as W
        for f in os.listdir(MODS_DIR):
            if not f.lower().endswith('.wd'):
                continue
            pfad = os.path.join(MODS_DIR, f)
            try:
                for e in W.eintraege(pfad):
                    if e['pfad'].lower().endswith('pquests.eco') and e['guid']:
                        aus[e['guid']] = e['rlen']
            except Exception:
                pass
    except ImportError:
        pass
    return aus


def load_pquests(payload, guid=None, code_len=None):
    """PQuests-Datensatz finden. Ohne GUID: alle bekannten Fassungen probieren."""
    builds = known_pquests_builds()
    # Die Laenge NICHT aus dem Archiv uebernehmen: ein Stand kann einen
    # aelteren Bau derselben GUID tragen (13.09.: 148.904 statt 149.212 B).
    # Deshalb immer ueber das Kopfmuster hinter dem Code bestimmen.
    if guid is not None:
        n = code_len or _pquests_code_len(payload, guid)
        return find_record(payload, guid, n, PQUESTS_VARS, PQUESTS_PATH)
    for g in builds:
        if payload.find(g) >= 0:
            return find_record(payload, g, _pquests_code_len(payload, g), PQUESTS_VARS, PQUESTS_PATH)
    raise ScriptError('kein PQuests-Datensatz mit bekannter GUID (Update16 oder Mods/*.wd)')


def _pquests_code_len(payload, guid):
    """Laenge des Bytecodes ueber die bekannten Fassungen und den Kopf danach."""
    a = payload.find(guid) + 16
    for n in _known_code_lengths():
        blk = payload[a:a + n]
        if len(blk) == n and blk[:4] == b'ECO\x00':
            h = struct.unpack_from('<III', payload, a + n)
            if h[0] < 1000 and h[1] < 16 and h[2] == 131072:
                return n
    raise ScriptError('Bytecode-Laenge nicht bestimmbar (keine bekannte Fassung)')


def _known_code_lengths():
    yield from set(known_pquests_builds().values())
    yield from (148119, 148904, 149212)      # eigene Baue vom 13.09.
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skripte')
    if os.path.isdir(d):
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith('.eco'):
                    try:
                        yield len(_eco_body(open(os.path.join(root, f), 'rb').read()))
                    except Exception:
                        pass


def _eco_body(raw):
    """Body einer .eco: nackt oder als Zwei-Strom-Datei (Kopfsatz + Body)."""
    if raw[:4] == b'ECO\x00':
        return raw
    if raw[:2] == b'\x78\x9c':
        d = zlib.decompressobj()
        d.decompress(raw)
        rest = d.unused_data
        return zlib.decompress(rest) if rest[:2] == b'\x78\x9c' else rest
    raise ScriptError('unbekanntes .eco-Format')


# ---------------------------------------------------------------- CLI

def _cmd_info(path):
    sv = tw1_save.read(path)
    rec = load_pquests(sv.payload)
    v = rec.vars
    print(f'{os.path.basename(path)}  {sv.title!r}')
    print(f'  Datensatz 0x{rec.start:X}..0x{rec.end:X}, Code {len(rec.code)} B, '
          f'GUID {rec.guid.hex()}, Zustand {rec.state_index}, '
          f'eQuestsNum {rec.quests_num}')
    st = v['anQuestState']
    from collections import Counter
    print(f'  Queststaende: {sorted(Counter(st).items())}')
    print(f'  qtx-Zeilen {len(v["astrLines"])}, NPC-Zuordnungen {v["nMappingsNum"]}, '
          f'Aktivierungen {v["nActivationsNumber"]}, Aktionen {v["nCurrentAction"]}, '
          f'Belohnungen {v["nCurrentReward"]}, Orte {v["nLocationsNum"]}')
    geladen = [i for i, f in enumerate(v['anQuestFlags']) if f & 0x10]
    print(f'  geladene Quests: {len(geladen)}, hoechste {max(geladen)}')


def _cmd_roundtrip(path):
    sv = tw1_save.read(path)
    rec = load_pquests(sv.payload)
    orig = sv.payload[rec.start:rec.end]
    neu = emit_record(rec)
    ok = neu == orig
    print(f'{os.path.basename(path)}: Datensatz {len(orig)} B, '
          f'neu {len(neu)} B, byteidentisch: {ok}')
    if not ok:
        i = next(k for k in range(min(len(orig), len(neu))) if orig[k] != neu[k])
        print(f'  erste Abweichung @+{i} (0x{rec.start + i:X})')
    return ok


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, path = argv[1], argv[2]
    if cmd == 'info':
        _cmd_info(path)
    elif cmd == 'roundtrip':
        return 0 if _cmd_roundtrip(path) else 1
    else:
        print(f'unbekannt: {cmd}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
