"""TW1 Savegame Patcher - Kern ohne Fenster.

Hebt vorhandene Spielstaende von Two Worlds 1 auf die gerade aktiven Mods,
so als haette man mit diesen Mods neu angefangen, nur mit dem alten
Fortschritt. Was ein Stand einfriert und was hier passiert (alles gemessen,
siehe QuestForge/SPIELSTAND_PLAN.md):

  Skripte   Der Stand traegt den Bytecode aller 21 Skripte samt Variablen.
            Liefert eine aktive Mod ein Skript mit anderer GUID und GLEICHEM
            Variablenblock (Wort 2 im ECO-Kopf == Vorspannwort 4), werden
            nur GUID und Bytecode getauscht - der Rest des Datensatzes bleibt.
            PQuests mit Migrationspfad (Kira-Kampagne): Arrays 400->600 und
            Wartemarke, das Skript traegt beim naechsten Tick selbst nach.
            Anderer Variablenblock ohne bekanntes Layout: wird gemeldet,
            nicht angefasst.
  Karten    Markerlisten aller 160 Zellen liegen im Stand. Fuer jede Karte
            einer aktiven Mod: fehlende Marker einsortieren (Binaersuche der
            Engine), vom Modder geloeschte Retail-Marker entfernen,
            verschobene auf die Mod-Position setzen. Laufzeit-Marker des
            Spiels bleiben.
  Laenge    Die 4 Byte vor dem zlib-Strom sind dessen Laenge; tw1_save.repack
            schreibt sie. Ohne das schneidet das Spiel den Stand ab.

Nicht im Stand und darum ohne Arbeit: .par, .lan, Texturen, Modelle.
"""

import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

import tw1_save                      # noqa: E402
import tw1_save_scripts as X          # noqa: E402
import tw1_save_tiles as T            # noqa: E402
import tw1_save_patch as P            # noqa: E402
import wd_metadaten as W              # noqa: E402

GAME_EXE = 'TwoWorldsExtended.exe'
GAME_EXE_ALT = 'TwoWorlds.exe'
REG_MODS = r'SOFTWARE\Reality Pump\TwoWorlds\Mods'
BACKUP_DIR = '_vor_Mods'
GAME_FOLDER_NAME = 'Two Worlds - Epic Edition'
MIGRATE_EXT = '.migrate'               # Erklaerung neben dem .eco: quests=600 (siehe build_questmigrate.py)
SEP = chr(92)


# ------------------------------------------------------------ Spiel finden --

def _steam_libraries():
    libs = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam'),
                          (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Valve\Steam')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ('InstallPath', 'SteamPath'):
                        try:
                            v, _ = winreg.QueryValueEx(k, name)
                            libs.append(v.replace('/', SEP))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    out = []
    for root in libs:
        vdf = os.path.join(root, 'steamapps', 'libraryfolders.vdf')
        out.append(root)
        if os.path.exists(vdf):
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding='utf-8', errors='ignore').read()):
                out.append(m.group(1).replace('\\\\', SEP))
    return out


def find_game_dir(hint=None):
    """Spielordner: Hinweis aus der Konfig, sonst Steam-Bibliotheken, sonst bekannte Pfade."""
    cands = []
    if hint:
        cands.append(hint)
    for lib in _steam_libraries():
        cands.append(os.path.join(lib, 'steamapps', 'common', GAME_FOLDER_NAME))
    cands += [r'F:\SteamLibrary\steamapps\common\Two Worlds - Epic Edition',
              r'C:\Program Files (x86)\Steam\steamapps\common\Two Worlds - Epic Edition',
              r'C:\Program Files (x86)\Reality Pump\Two Worlds']
    for c in cands:
        if c and os.path.exists(os.path.join(c, GAME_EXE)) or (c and os.path.exists(os.path.join(c, GAME_EXE_ALT))):
            return c
    return None


def game_running():
    o = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True).stdout.lower()
    return GAME_EXE.lower().encode() in o or GAME_EXE_ALT.lower().encode() in o


# -------------------------------------------------------------- Mods lesen --

class Mod:
    __slots__ = ('name', 'path', 'active', 'scripts', 'maps', 'migrate', 'error')

    def __init__(self, name, path, active):
        self.name, self.path, self.active = name, path, active
        self.scripts = {}      # 'scripts\\...\\x.eco' (klein) -> (guid, body, w2)
        self.maps = {}         # 'F01_1' -> lnd-Blob
        self.migrate = {}      # 'scripts\...\x.eco' -> {'quests': 600, ...}
        self.error = None


def _read_entry(fh, x):
    fh.seek(x['offset'])
    r = fh.read(x['clen'])
    if x['flags'] & 1:
        d = zlib.decompressobj()
        r = d.decompress(r) + d.flush()
    return r


def load_mods(game_dir):
    """Alle Mods im Mods-Ordner in Registry-Reihenfolge; aktiv laut Registry."""
    order, active = [], {}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_MODS) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                order.append(n)
                active[n.lower()] = bool(v)
                i += 1
    except (ImportError, OSError):
        pass
    mods_dir = os.path.join(game_dir, 'Mods')
    names = [n for n in order if os.path.exists(os.path.join(mods_dir, n))]
    if os.path.isdir(mods_dir):
        for f in sorted(os.listdir(mods_dir)):
            if f.lower().endswith('.wd') and f not in names:
                names.append(f)
    mods = []
    for n in names:
        m = Mod(n, os.path.join(mods_dir, n), active.get(n.lower(), False))
        try:
            with open(m.path, 'rb') as fh:
                for x in W.eintraege(m.path):
                    lp = x['pfad'].lower()
                    if lp.endswith('.eco') and x['guid']:
                        body = X._eco_body(_read_entry(fh, x))
                        m.scripts[lp] = (x['guid'], body, struct.unpack_from('<I', body, 8)[0])
                    elif lp.startswith('levels' + SEP + 'map_') and lp.endswith('.lnd'):
                        m.maps[x['pfad'].split(SEP)[-1][4:-4].upper()] = _read_entry(fh, x)
                    elif lp.endswith(MIGRATE_EXT):
                        info = {}
                        for ln in _read_entry(fh, x).decode('ascii', 'ignore').splitlines():
                            if '=' in ln:
                                k, v = ln.split('=', 1)
                                info[k.strip()] = v.strip()
                        m.migrate[lp[:-len(MIGRATE_EXT)] + '.eco'] = info
        except Exception as ex:
            m.error = str(ex)
        mods.append(m)
    return mods


def script_catalog(game_dir, mods):
    """GUID -> (Archiv, Skriptpfad klein, w2) ueber Spielarchive und alle Mods."""
    cat = {}
    wd_dir = os.path.join(game_dir, 'WDFiles')
    if os.path.isdir(wd_dir):
        for f in sorted(os.listdir(wd_dir)):
            if not f.lower().endswith('.wd'):
                continue
            p = os.path.join(wd_dir, f)
            try:
                with open(p, 'rb') as fh:
                    for x in W.eintraege(p):
                        lp = x['pfad'].lower()
                        if lp.endswith('.eco') and x['guid']:
                            body = X._eco_body(_read_entry(fh, x))
                            cat[x['guid']] = (f, lp, struct.unpack_from('<I', body, 8)[0])
            except Exception:
                pass
    for m in mods:
        for lp, (guid, body, w2) in m.scripts.items():
            cat[guid] = (m.name, lp, w2)
    return cat


def active_content(mods):
    """Was die aktiven Mods zusammen liefern; spaetere Mods ueberschreiben fruehere."""
    scripts, maps = {}, {}
    for m in mods:
        if not m.active or m.error:
            continue
        for lp, v in m.scripts.items():
            scripts[lp] = v + (m.name, m.migrate.get(lp))
        for cell, blob in m.maps.items():
            maps[cell] = (blob, m.name)
    return scripts, maps


# ------------------------------------------------------ Datensaetze im Stand --

class Rec:
    __slots__ = ('start', 'guid', 'img', 'img_len', 'w2')

    def __init__(self, start, guid, img, img_len, w2):
        self.start, self.guid, self.img, self.img_len, self.w2 = start, guid, img, img_len, w2


def find_records(payload):
    """Alle eingebetteten Skriptbilder: [Rec]. Bildlaenge ueber das Kopfmuster
    (u32 <1000, u32 <16, u32 131072) hinter dem Bild - gemessen an 21/21."""
    out, p = [], -1
    while True:
        p = payload.find(b'ECO' + bytes(1), p + 1)
        if p < 0:
            break
        if struct.unpack_from('<I', payload, p + 4)[0] != 0x60000 or p < 48:
            continue
        w2 = struct.unpack_from('<I', payload, p + 8)[0]
        if p < 36:
            continue
        # Vorspann vor der GUID: [1, Variablenblock, Heapzeiger, 0x11, *].
        # Gemessen an 2058 Datensaetzen aus 98 Staenden: 2058/2058. Das ist
        # zugleich die Pruefung, ob hier wirklich ein Datensatz beginnt.
        a, pre_w2, _heap, cls = struct.unpack_from('<4I', payload, p - 36)
        if a != 1 or pre_w2 != w2 or cls != 0x11:
            continue
        k, clen = p + 64, None
        lim = min(len(payload) - 12, p + 800000)
        while k < lim:
            a, b, c = struct.unpack_from('<III', payload, k)
            if c == 131072 and b < 16 and a < 1000:
                clen = k - p
                break
            k += 1
        if clen is None:
            continue
        out.append(Rec(p - 36, payload[p - 16:p], p, clen, w2))
    return out


# --------------------------------------------------------------------- Plan --

class Step:
    __slots__ = ('kind', 'what', 'detail', 'ok')

    def __init__(self, kind, what, detail, ok=True):
        self.kind, self.what, self.detail, self.ok = kind, what, detail, ok

    def __str__(self):
        return f'{self.what}: {self.detail}'


def plan(save_path, game_dir, mods, catalog, scripts, maps, retail=None):
    """[Step] fuer einen Stand. kind: 'script' | 'pquests' | 'map' | 'skip' | 'info'."""
    sv = tw1_save.read(save_path)
    pl = sv.payload
    steps = []
    for rec in find_records(pl):
        known = catalog.get(rec.guid)
        name = known[1].split(SEP)[-1] if known else f'GUID {rec.guid.hex()[:12]}'
        if not known:
            steps.append(Step('info', name, 'unbekanntes Skript, bleibt'))
            continue
        target = scripts.get(known[1])
        if not target:
            continue
        guid, body, w2, modname, mig = target
        if guid == rec.guid:
            continue
        if mig and known[1].endswith('pquests.eco'):
            steps.append(Step('pquests', name, f'{modname}: Questskript mit Migrationspfad, {mig.get("quests", "?")} Quests ({len(body)} B)'))
        elif w2 == rec.w2:
            steps.append(Step('script', name, f'{modname}: Bytecode tauschen ({rec.img_len} -> {len(body)} B)'))
        else:
            steps.append(Step('skip', name, f'{modname} aendert die Variablen ({rec.w2} -> {w2} B) - kein bekanntes Layout, bleibt', ok=False))
    if maps:
        lnds = {c: b for c, (b, _) in maps.items()}
        if retail is None:
            retail = T.retail_lnds(list(lnds), os.path.join(game_dir, 'WDFiles', 'Levels.wd'))
        _, report = T.apply(pl, lnds, mode='sync', retail=retail)
        for cell, la, ln, was in report:
            if was != 'gleich':
                steps.append(Step('map', f'Karte {cell}', f'{maps[cell][1]}: {was}'))
    return sv, steps


def status_of(steps):
    if any(s.kind in ('script', 'pquests', 'map') for s in steps):
        return 'umstellbar'
    if any(s.kind == 'skip' for s in steps):
        return 'teilweise'
    return 'aktuell'


# ------------------------------------------------------------------ Umsetzen --

def apply_plan(save_path, game_dir, mods, catalog, scripts, maps, log=print, retail=None):
    """Stand an Ort und Stelle umstellen; Original nach _vor_Mods. Liefert Schritte."""
    sv, steps = plan(save_path, game_dir, mods, catalog, scripts, maps, retail)
    todo = [s for s in steps if s.kind in ('script', 'pquests', 'map')]
    if not todo:
        log('  nichts zu tun')
        return steps
    pl = sv.payload
    # 1) PQuests mit Migrationspfad (aendert die Laenge des Datensatzes)
    for s in steps:
        if s.kind == 'pquests':
            lp = next(lp for lp in scripts if lp.endswith('pquests.eco'))
            guid, body, w2, modname, mig = scripts[lp]
            P.QUESTS_NEW = int(mig.get('quests', P.QUESTS_NEW))
            pl, rec, alt = P.patch_payload(pl, body, guid)
            log(f'  {s.what}: Arrays {alt} -> {P.QUESTS_NEW}, Wartemarke gesetzt ({modname})')
    # 2) einfache Tausche, von hinten nach vorn (Offsets bleiben gueltig)
    recs = find_records(pl)
    for rec in sorted(recs, key=lambda r: r.start, reverse=True):
        known = catalog.get(rec.guid)
        if not known:
            continue
        target = scripts.get(known[1])
        if not target or target[0] == rec.guid or known[1].endswith('pquests.eco'):
            continue
        guid, body, w2, modname, mig = target
        if w2 != rec.w2:
            continue
        pl = pl[:rec.img - 16] + guid + body + pl[rec.img + rec.img_len:]
        log(f'  {known[1].split(SEP)[-1]}: Bytecode getauscht ({modname})')
    # 3) Karten
    if maps:
        lnds = {c: b for c, (b, _) in maps.items()}
        if retail is None:
            retail = T.retail_lnds(list(lnds), os.path.join(game_dir, 'WDFiles', 'Levels.wd'))
        pl, report = T.apply(pl, lnds, mode='sync', retail=retail)
        for cell, la, ln, was in report:
            if was != 'gleich':
                log(f'  Karte {cell}: {was}')
    # 4) packen + Gegenpruefung
    raw = sv.repack(payload=pl)
    pr = tw1_save.Save(raw)
    if struct.unpack_from('<I', raw, pr.zlib_off - 4)[0] != len(raw) - pr.zlib_off:
        raise RuntimeError('Laengenfeld vor dem zlib-Strom stimmt nicht')
    T.check(pr.payload)
    if len(find_records(pr.payload)) != len(find_records(sv.payload)):
        raise RuntimeError('Skriptdatensaetze nach dem Patch nicht mehr vollstaendig')
    _, rest = plan_from_payload(pr, game_dir, mods, catalog, scripts, maps, retail)
    if any(s.kind in ('script', 'pquests', 'map') for s in rest):
        raise RuntimeError('Gegenpruefung: nach dem Patch bleiben Schritte offen: ' + '; '.join(map(str, rest)))
    # 5) Original sichern, ersetzen
    folder = os.path.dirname(save_path)
    backup = os.path.join(folder, BACKUP_DIR)
    os.makedirs(backup, exist_ok=True)
    ziel = os.path.join(backup, time.strftime('%Y-%m-%d_%H-%M-%S_') + os.path.basename(save_path))
    shutil.copy2(save_path, ziel)
    with open(save_path, 'wb') as f:
        f.write(raw)
    log(f'  Original gesichert: {os.path.join(BACKUP_DIR, os.path.basename(ziel))}')
    return steps


def plan_from_payload(sv, game_dir, mods, catalog, scripts, maps, retail):
    tmp = tempfile.mkdtemp(prefix='tw1sp_')
    try:
        p = os.path.join(tmp, 'x.TwoWorldsSave')
        with open(p, 'wb') as f:
            f.write(sv.raw if sv.payload is not None and hasattr(sv, 'raw') else b'')
        return plan(p, game_dir, mods, catalog, scripts, maps, retail)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------- Konfig --

def config_path():
    if getattr(__import__('sys'), 'frozen', False):
        d = os.path.join(os.environ.get('LOCALAPPDATA', HERE), 'TW1SavegamePatcher')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, 'save_patcher_settings.json')
    return os.path.join(HERE, 'save_patcher_settings.json')


class Config(dict):
    def __init__(self):
        super().__init__()
        self.path = config_path()
        try:
            self.update(json.load(open(self.path, encoding='utf-8')))
        except Exception:
            pass

    def save(self):
        try:
            json.dump(self, open(self.path, 'w', encoding='utf-8'), indent=2)
        except Exception:
            pass
