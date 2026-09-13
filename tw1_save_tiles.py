"""Zellbloecke in Two-Worlds-1-Spielstaenden: Markertabellen tauschen.

Gemessen 13.09.2026: JEDER Stand traegt fuer alle 161 Zellen einen Block,
und der Block enthaelt die Markertabelle der Zelle. Ein alter Stand spielt
deshalb mit den Markern von damals - Teleportmarker aus Retail funktionieren,
neue Marker einer Mod (MARKER_QUEST_CREATE_OBJECT 1 in H06, MARKER_CHEST
200-202) gibt es fuer ihn nicht. Genau so scheiterten Traenke und Kisten in
Oswaroh nach der Questmigration.

Blockaufbau (Pfadsuche, Kopf 20 B davor):

    u32 col | u32 row | i32 worldY | i32 worldX | u32 pathLen
    Pfad (ASCII, z.B. "Levels\\Map_H06.lnd")
    u32 a0 | u32 a1               (0/1 - Besuchs-/Ladeflags, bleiben)
    "LN\\0\\0" | str16 Name         (Name aus der .lnd, z.B. "Map_H06")
    u32 128 | u32 128
    20 B                          (0xff + 19 Nullen)
    6x dstring Nachbarzellen
    u32 Markerzaehler | u32 Pad | Marker (dstring + 25 B)   <- wie in der .lnd
    Rest                          (Raster, Objektzustand bei besuchten Zellen)

Nur die Markerliste wird ersetzt, alles andere bleibt byteweise. Die
Blockgroesse aendert sich dabei - das Spiel schreibt selbst Bloecke
verschiedener Groesse fuer dieselbe Zelle (2018: 6562 B, Mod-Stand: 8791 B),
ein Laengenfeld gibt es im Kopf nicht.
"""

import os
import struct
import sys
import zlib

import tw1_lnd
import tw1_save

HEAD = 20
PATH_PREFIX = b'Levels\\Map_'


class TileError(Exception):
    pass


def find_blocks(payload):
    """[(start, end, cell)] aller Zellbloecke, in Dateireihenfolge."""
    hits = []
    pos = 0
    while True:
        i = payload.find(PATH_PREFIX, pos)
        if i < 0:
            break
        j = payload.find(b'.lnd', i)
        cell = payload[i + len(PATH_PREFIX):j].decode('latin-1')
        pos = j
        # Nur echte Bloecke: Pfadlaenge im Kopf muss stimmen und hinter den
        # zwei Flag-Woertern das LN-Magic stehen. Der Pfadtext kommt auch in
        # der Zeichenkettentabelle des Kampagnenskripts vor.
        start = i - HEAD
        if start < 0:
            continue
        plen = struct.unpack_from('<I', payload, start + 16)[0]
        if plen != j + 4 - i or payload[j + 4 + 8:j + 4 + 12] != b'LN' + bytes(2):
            continue
        hits.append((start, cell))
    out = []
    for k, (start, cell) in enumerate(hits):
        end = hits[k + 1][0] if k + 1 < len(hits) else None
        out.append((start, end, cell))
    return out


def parse_block(payload, start, end=None):
    """Offsets der Markerliste eines Blocks: (count_off, list_end, count).

    Hinter Kopf, Pfad und den zwei Flag-Woertern steht der Datenteil der
    .lnd woertlich ("LN"-Magic, Name, Masse, Nachbarn, Marker) - gelesen mit
    demselben Code wie die Kartendateien (tw1_lnd._marker_section).
    """
    plen = struct.unpack_from('<I', payload, start + 16)[0]
    if plen > 64:
        raise TileError(f'Pfadlaenge {plen} @{start:#x}')
    pos = start + HEAD + plen + 8              # a0, a1
    if payload[pos:pos + 4] != b'LN\x00\x00':
        raise TileError(f'kein LN-Kopf @{pos:#x}')
    limit = end if end is not None else min(len(payload), pos + 4_000_000)
    data = payload[pos:limit]
    s, e = tw1_lnd._marker_section(data)
    count = struct.unpack_from('<I', data, s)[0]
    q = s + 8
    for k in range(count):
        ln = struct.unpack_from('<I', data, q)[0]
        name = data[q + 4:q + 4 + ln]
        if not name.startswith(b'MARKER_'):
            raise TileError(f'Marker {k} @{pos + q:#x} heisst {name[:20]!r}')
        q += 4 + ln + tw1_lnd.ENTRY_TAIL
    if q != e:
        raise TileError(f'Markerliste @{pos + s:#x}: Ende {q} != {e}')
    return pos + s, pos + e, count


def marker_bytes(payload, start):
    c, e, n = parse_block(payload, start)
    return payload[c:e]


def mod_marker_bytes(lnd_blob):
    """Zaehler + Pad + Eintraege aus einer .lnd (auch Editor-Zweistromform)."""
    data = tw1_lnd.unwrap(lnd_blob)
    s, e = tw1_lnd._marker_section(data)
    return data[s:e]


def replace_markers(payload, start, new_bytes, end=None):
    c, e, _ = parse_block(payload, start, end)
    return payload[:c] + new_bytes + payload[e:]


def check(payload):
    """Alle Bloecke laufen; wirft bei Strukturfehlern. Liefert {Zelle: Marker}."""
    out = {}
    for start, end, cell in find_blocks(payload):
        c, e, n = parse_block(payload, start, end)
        out[cell] = n
    return out


def mod_lnds(wd_path):
    """{Zelle: rohe .lnd-Bytes} aus einem Mod-Archiv."""
    import wd_metadaten as W
    out = {}
    with open(wd_path, 'rb') as f:
        for x in W.eintraege(wd_path):
            p = x['pfad']
            low = p.lower()
            if not (low.startswith('levels\\map_') and low.endswith('.lnd')):
                continue
            f.seek(x['offset'])
            r = f.read(x['clen'])
            if x['flags'] & 1:
                d = zlib.decompressobj()
                r = d.decompress(r) + d.flush()
            out[p[len('Levels\\Map_'):-4]] = r
    return out


def entries(raw):
    """Markerliste (Zaehler+Pad+Eintraege) -> [(name, id, tail25)]."""
    n = struct.unpack_from('<I', raw, 0)[0]
    pos = 8
    out = []
    for _ in range(n):
        ln = struct.unpack_from('<I', raw, pos)[0]
        name = raw[pos + 4:pos + 4 + ln]
        tail = raw[pos + 4 + ln:pos + 4 + ln + tw1_lnd.ENTRY_TAIL]
        out.append((name, struct.unpack_from('<I', tail, 0)[0], tail))
        pos += 4 + ln + tw1_lnd.ENTRY_TAIL
    return out


def build_list(items):
    out = bytearray(struct.pack('<II', len(items), 0))
    for name, ident, tail in items:
        out += struct.pack('<I', len(name)) + name + tail
    return bytes(out)


def merge_markers(save_raw, mod_raw):
    """Markerliste des Stands mit der der Mod-Karte zusammenfuehren.

    Das Spiel haengt zur Laufzeit Marker an (MARKER_NPC, MARKER_QUEST_START
    fuer erzeugte Figuren), und der Objektzustand einer besuchten Zelle
    zeigt per Index auf die Liste. Deshalb:
      - vorhandene Eintraege bleiben an ihrem Platz
      - gleicher Name+Id in der Mod-Karte mit anderen Koordinaten: die 25 B
        werden uebernommen (verschobener Marker), Groesse bleibt
      - Marker, die nur die Mod-Karte hat, kommen ans Ende
    Marker, die nur der Stand hat (Laufzeitmarker), bleiben.
    """
    alt = entries(save_raw)
    neu = entries(mod_raw)
    by_key = {(n, i): k for k, (n, i, _) in enumerate(alt)}
    out = list(alt)
    moved = added = 0
    for name, ident, tail in neu:
        k = by_key.get((name, ident))
        if k is None:
            out.append((name, ident, tail))
            added += 1
        elif out[k][2] != tail:
            out[k] = (name, ident, tail)
            moved += 1
    return build_list(out), moved, added


# Markertypen, die nur die Questskripte lesen und die das Spiel nicht schon
# beim Spielstart in Zustand verwandelt. Gemessen 13.09.: Zellen, deren
# neue Marker nur aus dieser Menge stammen, laden (F01_1, F08_1, E11, D08,
# H06); F01 mit Laternen, Wachen, Laeden, Sitzbaenken, Feindmarkern stuerzt
# ab - fuer solche Marker fuehrt der Zellblock pro Marker Zustand, den der
# Patcher nicht nachbauen kann.
QUEST_TYPES = (
    b'MARKER_QUEST_', b'MARKER_CHEST', b'MARKER_GATE', b'MARKER_CHAIR',
    b'MARKER_SLEEP', b'MARKER_TAVERN', b'MARKER_TELEPORT',
)


def quest_only(raw):
    """Markerliste auf QUEST_TYPES reduziert."""
    keep = [e for e in entries(raw) if e[0].startswith(QUEST_TYPES)]
    return build_list(keep)


def _sort_key(name, ident):
    """Sortierschluessel der Engine (0x4a31e0): stricmp(Name), dann Id."""
    return ((name if isinstance(name, str) else name.decode('latin-1')).lower(), ident)


def insert_missing(save_raw, mod_raw):
    """Fehlende Marker der Mod-Karte an ihre Sortierposition einfuegen.

    Die Engine sucht Marker per Binaersuche ueber (stricmp-Name, Id)
    (gemessen 13.09.: 0 von 10226 Retail-Markern unauffindbar unter stricmp,
    268 unter strcmp). Angehaengte Marker findet sie darum nie (Test S/P2).
    Vorhandene Eintraege bleiben samt Laufzeitdaten unangetastet.
    Liefert (neue Rohliste, Anzahl eingefuegt)."""
    cur = list(entries(save_raw))
    have = {(x[0], x[1]) for x in cur}
    added = 0
    for name, ident, tail in entries(mod_raw):
        if (name, ident) in have:
            continue
        k = _sort_key(name, ident)
        lo, hi = 0, len(cur)
        while lo < hi:
            mid = (lo + hi) // 2
            if _sort_key(cur[mid][0], cur[mid][1]) < k:
                lo = mid + 1
            else:
                hi = mid
        cur.insert(lo, (name, ident, tail))
        have.add((name, ident))
        added += 1
    return build_list(cur), added


RETAIL_LEVELS = 'F:/SteamLibrary/steamapps/common/Two Worlds - Epic Edition/WDFiles/Levels.wd'


def retail_lnds(cells, wd_path=RETAIL_LEVELS):
    """{Zelle: .lnd-Blob} der Retail-Karten aus Levels.wd fuer die genannten Zellen."""
    import zlib
    import wd_metadaten as W
    want = {('levels' + chr(92) + 'map_' + c + '.lnd').lower(): c for c in cells}
    out = {}
    with open(wd_path, 'rb') as f:
        for x in W.eintraege(wd_path):
            c = want.get(x['pfad'].lower())
            if c is None:
                continue
            f.seek(x['offset'])
            r = f.read(x['clen'])
            if x['flags'] & 1:
                d = zlib.decompressobj()
                r = d.decompress(r) + d.flush()
            out[c] = r
    return out


def sync_markers(save_raw, mod_raw, retail_raw):
    """Fehlende Mod-Marker einsortieren UND die Marker entfernen, die der
    Modder aus der Karte geloescht hat (in der Retail-Karte, nicht in der
    Mod-Karte). Marker, die das Spiel zur Laufzeit selbst angelegt hat
    (MARKER_NPC, MARKER_ENEMY_G_*: weder Retail noch Mod), bleiben.
    Gemessen 13.09.: sonst spawnen entfernte Retail-Spawner weiter.
    Liefert (Rohliste, eingefuegt, entfernt, verschoben)."""
    mod = {(a[0], a[1]): a[2] for a in entries(mod_raw)}
    retail = {(a[0], a[1]): a[2] for a in entries(retail_raw)}
    kept = []
    removed = moved = 0
    for name, ident, tail in entries(save_raw):
        k = (name, ident)
        if k in retail and k not in mod:
            removed += 1                       # vom Modder geloescht
            continue
        # Vom Modder VERSCHOBEN (im alten Editor loescht man nicht, man schiebt
        # weg: Minen- und Yamalin-Zwergenspawner): Retail- und Mod-Position
        # weichen ab, der Stand traegt noch die Retail-Position. Dann gilt die
        # Mod-Position. Hat das Spiel den Marker zur Laufzeit selbst bewegt
        # (Stand != Retail, z.B. QUEST_START 3 in E01), bleibt der Stand.
        if k in retail and k in mod and retail[k][4:16] != mod[k][4:16] and tail[4:16] == retail[k][4:16]:
            tail = tail[:4] + mod[k][4:16] + tail[16:]
            moved += 1
        # Mod-eigene Marker (nicht in Retail) aus einer aelteren Mod-Fassung:
        # aktuelle Mod-Position uebernehmen. Ausnahme: Sorten, die das Spiel
        # zur Laufzeit selbst versetzt (QUEST_START folgt dem Geber, NPC).
        elif k not in retail and k in mod and tail[4:16] != mod[k][4:16]                 and not name.startswith((b'MARKER_QUEST_START', b'MARKER_NPC')):
            tail = tail[:4] + mod[k][4:16] + tail[16:]
            moved += 1
        kept.append((name, ident, tail))
    raw, added = insert_missing(build_list(kept), mod_raw)
    return raw, added, removed, moved


def apply(payload, lnds, mode='sync', only_quest=False, retail=None):
    """Markerlisten der Zellen aus `lnds` in den Payload uebernehmen.

    mode 'sync' (Standard seit 13.09. abends): wie 'insert', zusaetzlich die
      vom Modder geloeschten Retail-Marker entfernen (sync_markers). `retail`
      = {Zelle: Retail-.lnd}; fehlt es, wird es aus Levels.wd geladen.
    mode 'insert' (13.09. 17:30, Beleg X4): in JEDER Zelle -
      unbesucht, besucht oder geladen - die fehlenden Marker der Mod-Karte
      einsortieren (insert_missing). Alle frueheren "besuchte Zellen stuerzen
      ab"-Regeln waren ein Packerfehler (Laengenfeld vor dem zlib-Strom, siehe
      tw1_save.repack).
    mode 'auto' (Stand 13.09. vormittags, ueberholt):
      - unbesuchte Zelle (a0 = a1 = 0): Liste der Karte WOERTLICH einsetzen.
        Genau das schreibt das Spiel selbst (9 von 9 Mod-Zellen im
        Referenzstand byteidentisch mit der .lnd). Test T: Stand laedt,
        Sprung in die umgebaute Zelle E02 klappt.
      - besuchte oder geladene Zelle (a0 oder a1 gesetzt): NICHT anfassen.
        Ersetzen stuerzt ab (A, D), Anhaengen laedt, aber das Spiel findet
        angehaengte Marker nicht (Test S: kein Sprung) - es sucht in der nach
        Typ gruppierten Reihenfolge der Karte. Solche Zellen meldet der
        Bericht als 'besucht, uebersprungen'.
    mode 'replace' / 'merge': nur fuer Versuche.
    Liefert (neuer Payload, [(Zelle, alt, neu, was)])."""
    report = []
    if mode == 'sync' and retail is None:
        retail = retail_lnds(list(lnds))
    blocks = find_blocks(payload)
    for start, end, cell in reversed(blocks):          # hinten zuerst, Offsets bleiben gueltig
        if cell not in lnds:
            continue
        mod_raw = mod_marker_bytes(lnds[cell])
        if only_quest:
            mod_raw = quest_only(mod_raw)
        c0, e0, _ = parse_block(payload, start, end)
        alt = payload[c0:e0]
        plen = struct.unpack_from('<I', payload, start + 16)[0]
        a0, a1 = struct.unpack_from('<II', payload, start + 20 + plen)
        besucht = bool(a0 or a1)
        if mode == 'sync':
            r_raw = mod_marker_bytes(retail[cell]) if cell in retail else build_list([])
            neu, added, removed, moved = sync_markers(alt, mod_raw, r_raw)
            was = f'{added} einsortiert, {removed} entfernt, {moved} auf Mod-Position verschoben'
        elif mode == 'insert':
            neu, added = insert_missing(alt, mod_raw)
            was = f'{added} Marker einsortiert'
        elif mode == 'auto':
            if besucht:
                report.append((cell, len(alt), len(alt), f'besucht (a0={a0} a1={a1}), uebersprungen'))
                continue
            neu, was = mod_raw, 'unbesucht, woertlich ersetzt'
        elif mode == 'replace':
            neu, was = mod_raw, 'ersetzt'
        else:
            neu, moved, added = merge_markers(alt, mod_raw)
            was = f'zusammengefuehrt (+{added} neu, {moved} verschoben)'
        if neu == alt:
            report.append((cell, len(alt), len(neu), 'gleich'))
            continue
        payload = replace_markers(payload, start, neu, end)
        report.append((cell, len(alt), len(neu), was))
    check(payload)
    return payload, list(reversed(report))


def visited_mod_cells(payload, lnds):
    """[(Zelle, a0, a1)] der Mod-Zellen, die der Stand schon besucht hat."""
    out = []
    for start, end, cell in find_blocks(payload):
        if cell not in lnds:
            continue
        plen = struct.unpack_from('<I', payload, start + 16)[0]
        a0, a1 = struct.unpack_from('<II', payload, start + 20 + plen)
        if a0 or a1:
            out.append((cell, a0, a1))
    return out


def _cmd_check(path):
    sv = tw1_save.read(path)
    z = check(sv.payload)
    print(f'{os.path.basename(path)}  {sv.title!r}: {len(z)} Zellbloecke, '
          f'{sum(z.values())} Marker; H06 {z.get("H06")}, E01 {z.get("E01")}, '
          f'F01_1 {z.get("F01_1")}')


def _cmd_diff(path, wd):
    sv = tw1_save.read(path)
    lnds = mod_lnds(wd)
    for start, end, cell in find_blocks(sv.payload):
        if cell not in lnds:
            continue
        a_names = _names(marker_bytes(sv.payload, start))
        n_names = _names(mod_marker_bytes(lnds[cell]))
        nur_neu = sorted(set(n_names) - set(a_names))
        nur_alt = sorted(set(a_names) - set(n_names))
        print(f'{cell:6} Stand {len(a_names):3} Marker, Mod {len(n_names):3}  '
              f'nur Mod: {nur_neu[:8]}  nur Stand: {nur_alt[:8]}')


def _names(raw):
    n = struct.unpack_from('<I', raw, 0)[0]
    pos = 8
    out = []
    for _ in range(n):
        ln = struct.unpack_from('<I', raw, pos)[0]
        name = raw[pos + 4:pos + 4 + ln].decode('latin-1')
        ident = struct.unpack_from('<I', raw, pos + 4 + ln)[0]
        out.append(f'{name}#{ident}')
        pos += 4 + ln + tw1_lnd.ENTRY_TAIL
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd = argv[1]
    try:
        if cmd == 'check':
            _cmd_check(argv[2])
        elif cmd == 'diff':
            _cmd_diff(argv[2], argv[3])
        else:
            print(f'unbekannt: {cmd}')
            return 1
    except (TileError, tw1_save.SaveError) as e:
        print(f'FEHLER: {e}')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
