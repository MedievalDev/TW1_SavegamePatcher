"""TW1 Savegame Patcher - Fenster.

    py save_patcher.py            Fenster
    py save_patcher.py --liste    Liste + Plan auf der Konsole (Selbsttest)

Aufbau nach PY_TOOL_DESIGN.md: Dark Theme (theme.py), dunkle Menueleiste,
Guide beim ersten Start, Links im Hilfe-Menue, Sprache DE/EN, Konfig neben
dem Skript (als Exe unter %LOCALAPPDATA%\\TW1SavePatcher).
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tkinter as tk                     # noqa: E402
from tkinter import ttk, messagebox, filedialog   # noqa: E402

import theme                              # noqa: E402
import patcher_core as C                  # noqa: E402
import tw1_save                           # noqa: E402

APP_NAME = 'TW1 SAVEGAME PATCHER'
VERSION = '1.0'
GITHUB_URL = 'https://github.com/MedievalDev/TW1_SavegamePatcher'
SITE_URL = 'https://alchemy-fox.de/'
GUIDE_URL = 'https://alchemy-fox.de/game/TW1_SavegamePatcher/'
COMMUNITY_URL = 'https://twmp.alchemy-fox.de/'
LINKS = (('GitHub-Repo', GITHUB_URL), ('Alchemy Fox', SITE_URL),
         ('Guide-Seite', GUIDE_URL), ('Community', COMMUNITY_URL))

STATUS_COLOR = {'aktuell': theme.OK, 'umstellbar': theme.GOLD,
                'teilweise': '#e0a050', 'unbekannt': theme.DIM, 'Fehler': theme.ERR}


# ---------------------------------------------------------------- Sprache --

_LANG = 'de'


def system_is_german():
    try:
        import ctypes
        return (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x07
    except Exception:
        return False


def tr(text):
    if _LANG == 'en':
        return EN.get(text, text)
    return text


# ------------------------------------------------------------------ Guide --

GUIDE_STEPS = [
    {'title': 'Willkommen', 'widget': None, 'text':
     'Dieses Werkzeug hebt vorhandene Spielstaende auf die Mods, die gerade '
     'aktiv sind - so, als haettest du mit den Mods neu angefangen, nur mit '
     'deinem alten Fortschritt.'},
    {'title': 'Aktive Mods', 'widget': 'mods_box', 'text':
     'Hier stehen alle Mods aus dem Mods-Ordner. Aktiv ist, was im Spiel '
     'eingeschaltet ist. Dahinter, was eine Mod mitbringt: Skripte und Karten. '
     'Nur diese beiden Dinge stecken in einem Spielstand fest.'},
    {'title': 'Spielstaende', 'widget': 'tree', 'text':
     'Alle Staende des Spiels mit Datum und Stand. "umstellbar" heisst: eine '
     'aktive Mod aendert etwas, das im Stand noch fehlt. "aktuell" heisst: '
     'nichts zu tun. "teilweise": ein Skript aendert seine Variablen, das '
     'kann nur die Mod selbst - der Rest wird trotzdem umgestellt.'},
    {'title': 'Was passiert', 'widget': 'plan_box', 'text':
     'Fuer den markierten Stand siehst du jeden einzelnen Schritt: welches '
     'Skript getauscht wird, welche Karte welche Marker bekommt. Nichts '
     'davon passiert, bevor du den Knopf drueckst.'},
    {'title': 'Umstellen', 'widget': 'btn_apply', 'text':
     'Markiere einen oder mehrere Staende und druecke hier. Das Original '
     'wandert vorher in den Ordner _vor_Mods neben den Staenden, der Stand '
     'wird an Ort und Stelle ersetzt - die Ladeliste im Spiel bleibt gleich.'},
    {'title': 'Danach', 'widget': 'btn_game', 'text':
     'Two Worlds liest die Ladeliste nur beim Start. Also erst umstellen, '
     'dann das Spiel starten. Laeuft es schon, verweigert der Knopf mit '
     'einem Hinweis.'},
]


class Guide:
    def __init__(self, app):
        self.app, self.i, self.frames, self.win = app, 0, [], None

    def start(self):
        self.i = 0
        if self.win:
            self.win.destroy()
        self.win = tk.Toplevel(self.app.root)
        self.win.title(tr('Guide'))
        self.win.configure(background=theme.PANEL)
        self.win.transient(self.app.root)
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', lambda: self.finish(False))
        theme.dark_titlebar(self.win)
        f = ttk.Frame(self.win, style='Panel.TFrame', padding=14)
        f.pack(fill='both', expand=True)
        self.head = ttk.Label(f, style='PanelTitle.TLabel')
        self.head.pack(anchor='w')
        self.title = ttk.Label(f, style='Panel.TLabel', font=theme.FONT_H2, foreground=theme.GOLD)
        self.title.pack(anchor='w', pady=(4, 6))
        self.text = ttk.Label(f, style='Panel.TLabel', wraplength=360, justify='left')
        self.text.pack(anchor='w')
        self.dont = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=tr('Beim Start nicht mehr anzeigen'), variable=self.dont,
                        style='Panel.TCheckbutton').pack(anchor='w', pady=(14, 8))
        b = ttk.Frame(f, style='Panel.TFrame')
        b.pack(fill='x')
        self.back = ttk.Button(b, text=tr('Zurueck'), command=self.prev)
        self.back.pack(side='left')
        self.next = ttk.Button(b, text=tr('Weiter'), style='Accent.TButton', command=self.nxt)
        self.next.pack(side='left', padx=8)
        ttk.Button(b, text=tr('Beenden'), command=lambda: self.finish(self.dont.get())).pack(side='right')
        self.show()
        r = self.app.root
        self.win.geometry(f'+{r.winfo_rootx() + 40}+{r.winfo_rooty() + 90}')

    def show(self):
        s = GUIDE_STEPS[self.i]
        self.head.configure(text=tr('Schritt {n} von {m}').format(n=self.i + 1, m=len(GUIDE_STEPS)))
        self.title.configure(text=tr(s['title']))
        self.text.configure(text=tr(s['text']))
        self.back.state(['!disabled'] if self.i > 0 else ['disabled'])
        self.next.configure(text=tr('Weiter') if self.i < len(GUIDE_STEPS) - 1 else tr('Fertig'))
        self.highlight(getattr(self.app, s['widget'], None) if s['widget'] else None)

    def prev(self):
        if self.i > 0:
            self.i -= 1
            self.show()

    def nxt(self):
        if self.i < len(GUIDE_STEPS) - 1:
            self.i += 1
            self.show()
        else:
            self.finish(True)

    def highlight(self, widget):
        for f in self.frames:
            f.destroy()
        self.frames = []
        if widget is None:
            return
        root = self.app.root
        root.update_idletasks()
        x = widget.winfo_rootx() - root.winfo_rootx()
        y = widget.winfo_rooty() - root.winfo_rooty()
        w, h, t = widget.winfo_width(), widget.winfo_height(), 3
        for fx, fy, fw, fh in ((x, y, w, t), (x, y + h - t, w, t), (x, y, t, h), (x + w - t, y, t, h)):
            f = tk.Frame(root, background=theme.GOLD)
            f.place(x=fx, y=fy, width=fw, height=fh)
            self.frames.append(f)

    def finish(self, dont_show):
        self.highlight(None)
        if dont_show or self.i == len(GUIDE_STEPS) - 1:
            self.app.cfg['guide_seen'] = True
            self.app.cfg.save()
        if self.win:
            self.win.destroy()
            self.win = None


# -------------------------------------------------------------------- App --

class App:
    def __init__(self):
        self.cfg = C.Config()
        global _LANG
        _LANG = self.cfg.get('lang') or ('de' if system_is_german() else 'en')
        self.root = tk.Tk()
        self.root.withdraw()
        theme.apply_dark_theme(self.root)
        self.root.title('TW1 Savegame Patcher')
        self.game = C.find_game_dir(self.cfg.get('game_dir'))
        self.folder = self.cfg.get('save_dir') or tw1_save.find_save_dir()
        self.mods, self.catalog, self.scripts, self.maps, self.retail = [], {}, {}, {}, {}
        self.rows = {}
        self.plans = {}
        self.bild = None
        self.guide = Guide(self)
        self.restart = False
        self.build()
        self.place_window()
        self.root.deiconify()
        self.root.after(100, self.reload_all)
        if not self.cfg.get('guide_seen'):
            self.root.after(1200, self.guide.start)

    # ---- Aufbau ----
    def place_window(self):
        w, h = 1180, 720
        self.root.update_idletasks()
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 2 - 30)
        self.root.geometry(f'{w}x{h}+{x}+{y}')
        self.root.minsize(960, 600)

    def build(self):
        self.build_menubar()
        body = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        body.pack(fill='both', expand=True)
        head = ttk.Frame(body)
        head.pack(fill='x')
        ttk.Label(head, text=tr('Spielstaende auf die aktiven Mods umstellen'), style='Brand.TLabel').pack(side='left')
        self.head_info = ttk.Label(head, text='', style='Muted.TLabel')
        self.head_info.pack(side='right')

        paned = ttk.Panedwindow(body, orient='horizontal')
        paned.pack(fill='both', expand=True, pady=(10, 8))

        # links: Liste + Log
        left = ttk.Frame(paned)
        paned.add(left, weight=3)
        cols = ('name', 'datum', 'status')
        self.tree = ttk.Treeview(left, columns=cols, show='headings', selectmode='extended')
        self.tree.heading('name', text=tr('Spielstand'))
        self.tree.heading('datum', text=tr('gespeichert'))
        self.tree.heading('status', text=tr('Stand'))
        self.tree.column('name', width=320, anchor='w')
        self.tree.column('datum', width=130, anchor='center')
        self.tree.column('status', width=110, anchor='center')
        sb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        for st, col in STATUS_COLOR.items():
            self.tree.tag_configure(st, foreground=col)
        self.tree.bind('<<TreeviewSelect>>', self.show_plan)

        # rechts: Mods, Vorschau, Plan, Knoepfe (von unten gepackt)
        right = ttk.Frame(paned, style='Panel.TFrame', padding=(10, 8))
        paned.add(right, weight=2)
        btns = ttk.Frame(right, style='Panel.TFrame')
        btns.pack(side='bottom', fill='x', pady=(8, 0))
        self.btn_apply = ttk.Button(btns, text=tr('Auf die Mods umstellen'), style='Accent.TButton', command=self.apply_clicked)
        self.btn_apply.pack(side='left')
        self.btn_game = ttk.Button(btns, text=tr('Two Worlds starten'), command=self.start_game)
        self.btn_game.pack(side='right')

        ttk.Label(right, text=tr('Aktive Mods'), style='PanelTitle.TLabel').pack(anchor='w')
        self.mods_box = tk.Text(right, height=5, font=theme.FONT, state='disabled', wrap='none',
                                background=theme.FIELD, foreground=theme.INK, relief='flat')
        self.mods_box.pack(fill='x')
        self.mods_box.tag_configure('on', foreground=theme.OK)
        self.mods_box.tag_configure('off', foreground=theme.DIM)
        self.mods_box.tag_configure('mut', foreground=theme.MUT)

        mid = ttk.Frame(right, style='Panel.TFrame')
        mid.pack(fill='x', pady=(10, 0))
        self.bild_label = ttk.Label(mid, style='Panel.TLabel')
        self.bild_label.pack(anchor='w')
        self.title_label = ttk.Label(mid, text='', style='PanelTitle.TLabel', wraplength=380)
        self.title_label.configure(padding=(0, 4, 0, 0))
        self.title_label.pack(anchor='w')
        self.info_label = ttk.Label(mid, text='', style='PanelMuted.TLabel', wraplength=380, justify='left')
        self.info_label.pack(anchor='w')

        ttk.Label(right, text=tr('Was passiert'), style='PanelTitle.TLabel').pack(anchor='w', pady=(10, 0))
        self.plan_box = tk.Text(right, font=theme.FONT_SMALL, state='disabled', wrap='word',
                                background=theme.FIELD, foreground=theme.INK, relief='flat')
        self.plan_box.pack(fill='both', expand=True)
        self.plan_box.tag_configure('ok', foreground=theme.INK)
        self.plan_box.tag_configure('skip', foreground=theme.ERR)
        self.plan_box.tag_configure('mut', foreground=theme.MUT)
        self.plan_box.tag_configure('gold', foreground=theme.GOLD)

        # Log unter der Liste
        self.log_box = tk.Text(body, height=6, font=theme.FONT_MONO, state='disabled')
        self.log_box.pack(fill='x')
        self.log_box.tag_configure('ok', foreground=theme.OK)
        self.log_box.tag_configure('err', foreground=theme.ERR)

        status = ttk.Frame(self.root, style='Status.TFrame')
        status.pack(fill='x', side='bottom')
        self.status_label = ttk.Label(status, text='', style='Status.TLabel')
        self.status_label.pack(side='left')
        self.count_label = ttk.Label(status, text='', style='Status.TLabel')
        self.count_label.pack(side='right')

    def build_menubar(self):
        bar = ttk.Frame(self.root, style='Menubar.TFrame')
        bar.pack(fill='x')
        self.menubar = bar
        for key, filler in ((tr('Datei'), self._fill_file), (tr('Bearbeiten'), self._fill_edit),
                            (tr('Ansicht'), self._fill_view), (tr('Hilfe'), self._fill_help)):
            item = ttk.Label(bar, text=key, style='Menubar.TLabel')
            item.pack(side='left')
            item.bind('<Button-1>', lambda ev, f=filler, w=item: self._popup(f, w))
            item.bind('<Enter>', lambda ev, w=item: w.state(['active']))
            item.bind('<Leave>', lambda ev, w=item: w.state(['!active']))
        ttk.Label(bar, text=APP_NAME, style='Menubar.TLabel').pack(side='right', padx=(0, 6))
        self.lang_toggle = self.build_lang_toggle(bar)
        self.lang_toggle.pack(side='right', padx=(0, 10))

    def build_lang_toggle(self, bar):
        """DE · EN oben rechts: aktive Sprache in Gold, Klick wirkt sofort."""
        box = ttk.Frame(bar, style='Menubar.TFrame')
        self.lang_labels = {}
        for i, code in enumerate(('de', 'en')):
            if i:
                ttk.Label(box, text='·', style='Menubar.TLabel', padding=(2, 5)).pack(side='left')
            lbl = ttk.Label(box, text=code.upper(), style='Menubar.TLabel', padding=(4, 5), cursor='hand2')
            lbl.pack(side='left')
            lbl.bind('<Button-1>', lambda ev, c=code: self.set_lang(c))
            self.lang_labels[code] = lbl
        self.paint_lang_toggle()
        return box

    def paint_lang_toggle(self):
        for code, lbl in self.lang_labels.items():
            lbl.configure(foreground=theme.GOLD if code == _LANG else theme.MUT)

    def _popup(self, filler, widget):
        menu = theme.Menu(self.root)
        filler(menu)
        try:
            menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def _fill_file(self, m):
        m.add_command(label=tr('Liste neu lesen'), accelerator='F5', command=self.reload_all)
        m.add_command(label=tr('Spielstand-Ordner waehlen'), command=self.choose_save_dir)
        m.add_command(label=tr('Spielordner waehlen'), command=self.choose_game_dir)
        m.add_separator()
        m.add_command(label=tr('Sicherungen oeffnen'), command=self.open_backup)
        m.add_separator()
        m.add_command(label=tr('Beenden'), accelerator='Alt+F4', command=self.root.destroy)

    def _fill_edit(self, m):
        m.add_command(label=tr('Alles auswaehlen'), accelerator='Strg+A', command=lambda: self.tree.selection_set(self.tree.get_children()))
        m.add_command(label=tr('Umstellbare auswaehlen'), command=self.select_pending)

    def _fill_view(self, m):
        sub = theme.Menu(m)
        for code, name in (('de', 'Deutsch'), ('en', 'English')):
            sub.add_radiobutton(label=name, value=code, variable=tk.StringVar(value=_LANG),
                                command=lambda c=code: self.set_lang(c))
        m.add_cascade(label=tr('Sprache'), menu=sub)

    def _fill_help(self, m):
        m.add_command(label=tr('Guide starten'), command=self.guide.start)
        m.add_command(label=tr('Dokumentation'), command=lambda: webbrowser.open(GUIDE_URL))
        m.add_separator()
        for name, url in LINKS:
            m.add_command(label=f'{name}  ({url})', command=lambda u=url: webbrowser.open(u))
        m.add_separator()
        m.add_command(label=tr('Ueber'), command=self.show_about)

    # ---- Aktionen ----
    def log(self, text, tag=None):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', text + '\n', tag or ())
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def set_status(self, text, ok=None):
        self.status_label.configure(text=text, style='StatusOk.TLabel' if ok else ('StatusErr.TLabel' if ok is False else 'Status.TLabel'))

    def set_lang(self, code):
        global _LANG
        if code == _LANG:
            return
        self.cfg['lang'] = code
        self.cfg.save()
        _LANG = code
        self.restart = True                  # main() baut das Fenster neu auf
        self.root.destroy()

    def choose_save_dir(self):
        d = filedialog.askdirectory(title=tr('Spielstand-Ordner waehlen'), initialdir=self.folder or '/')
        if d:
            self.folder = d
            self.cfg['save_dir'] = d
            self.cfg.save()
            self.reload_all()

    def choose_game_dir(self):
        d = filedialog.askdirectory(title=tr('Spielordner waehlen'), initialdir=self.game or '/')
        if d:
            self.cfg['game_dir'] = d
            self.cfg.save()
            self.game = C.find_game_dir(d)
            self.reload_all()

    def open_backup(self):
        if self.folder:
            p = os.path.join(self.folder, C.BACKUP_DIR)
            os.makedirs(p, exist_ok=True)
            os.startfile(p)

    def select_pending(self):
        self.tree.selection_set([iid for iid, (path, st) in self.rows.items() if st in ('umstellbar', 'teilweise')])

    def reload_all(self):
        if not self.game:
            self.set_status(tr('Spielordner nicht gefunden - Datei > Spielordner waehlen'), ok=False)
            return
        if not self.folder or not os.path.isdir(self.folder):
            self.set_status(tr('Spielstand-Ordner nicht gefunden - Datei > Spielstand-Ordner waehlen'), ok=False)
            return
        self.mods = C.load_mods(self.game)
        self.catalog = C.script_catalog(self.game, self.mods)
        self.scripts, self.maps = C.active_content(self.mods)
        self.retail = C.T.retail_lnds(list(self.maps), os.path.join(self.game, 'WDFiles', 'Levels.wd')) if self.maps else {}
        self.head_info.configure(text=f'{self.game}   ·   {self.folder}')
        self.mods_box.configure(state='normal')
        self.mods_box.delete('1.0', 'end')
        for m in self.mods:
            tag = 'on' if m.active else 'off'
            self.mods_box.insert('end', ('[x] ' if m.active else '[ ] ') + m.name, tag)
            what = []
            if m.scripts:
                what.append(tr('{n} Skripte').format(n=len(m.scripts)))
            if m.maps:
                what.append(tr('{n} Karten').format(n=len(m.maps)))
            if m.error:
                what.append(tr('nicht lesbar'))
            self.mods_box.insert('end', ('   ' + ', '.join(what) if what else '   ' + tr('nichts im Stand')) + '\n', 'mut')
        self.mods_box.configure(state='disabled')
        self.fill_list()

    def fill_list(self):
        vorher = {self.rows[i][0] for i in self.tree.selection() if i in self.rows}
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.plans.clear()
        n = pending = 0
        wieder = []
        items = []
        for f in os.listdir(self.folder):
            if f.lower().endswith('.twoworldssave'):
                p = os.path.join(self.folder, f)
                items.append((os.path.getmtime(p), p))
        for mtime, p in sorted(items, reverse=True):
            try:
                sv, steps = C.plan(p, self.game, self.mods, self.catalog, self.scripts, self.maps, self.retail)
                st = C.status_of(steps)
                title = sv.title
                self.plans[p] = (sv, steps)
            except Exception as ex:
                st, title = 'Fehler', f'{f}: {ex}'
                self.plans[p] = (None, [C.Step('skip', f, str(ex), ok=False)])
            iid = self.tree.insert('', 'end', values=(title, time.strftime('%d.%m.%Y %H:%M', time.localtime(mtime)), tr(st)), tags=(st,))
            self.rows[iid] = (p, st)
            if p in vorher:
                wieder.append(iid)
            n += 1
            pending += st in ('umstellbar', 'teilweise')
        self.count_label.configure(text=tr('{n} Staende, {m} umstellbar').format(n=n, m=pending))
        kids = self.tree.get_children()
        if wieder or kids:
            self.tree.selection_set(wieder or kids[0])
            self.show_plan()
        self.set_status(tr('bereit'))

    def show_plan(self, _ev=None):
        sel = self.tree.selection()
        if not sel:
            return
        path, st = self.rows[sel[-1]]
        sv, steps = self.plans.get(path, (None, []))
        try:
            img = tk.PhotoImage(data=sv.png)
            if img.width() * 2 <= 260:
                img = img.zoom(2, 2)
            self.bild = img
            self.bild_label.configure(image=img)
        except Exception:
            self.bild_label.configure(image='')
        self.title_label.configure(text=sv.title if sv else os.path.basename(path))
        self.info_label.configure(text=f'{os.path.basename(path)}  ·  {tr(st)}')
        self.plan_box.configure(state='normal')
        self.plan_box.delete('1.0', 'end')
        if not steps:
            self.plan_box.insert('end', tr('Nichts zu tun - der Stand kennt alles, was die aktiven Mods liefern.'), 'mut')
        for s in steps:
            tag = 'skip' if s.kind == 'skip' else ('mut' if s.kind == 'info' else 'ok')
            self.plan_box.insert('end', s.what, 'gold' if tag == 'ok' else tag)
            self.plan_box.insert('end', '  ' + s.detail + '\n', tag)
        self.plan_box.configure(state='disabled')

    def apply_clicked(self):
        sel = [self.rows[i] for i in self.tree.selection()]
        todo = [p for p, st in sel if st in ('umstellbar', 'teilweise')]
        if not sel:
            messagebox.showinfo(tr('Kein Stand gewaehlt'), tr('Bitte links einen oder mehrere Staende markieren.'))
            return
        if not todo:
            messagebox.showinfo(tr('Schon aktuell'), tr('Die gewaehlten Staende kennen bereits alles, was die aktiven Mods liefern.'))
            return
        if C.game_running():
            messagebox.showwarning(tr('Two Worlds laeuft'), tr('Bitte das Spiel erst beenden. Es liest die Ladeliste nur beim Start.'))
            return
        if not messagebox.askyesno(tr('Umstellen'), tr('{n} Stand/Staende auf die aktiven Mods umstellen?\nDie Originale werden nach _vor_Mods gesichert.').format(n=len(todo))):
            return
        self.btn_apply.state(['disabled'])
        self.set_status(tr('arbeite ...'))

        def arbeit():
            ok = 0
            for p in todo:
                name = self.plans[p][0].title if self.plans.get(p) and self.plans[p][0] else os.path.basename(p)
                self.root.after(0, self.log, f'{name} ({os.path.basename(p)})')
                try:
                    C.apply_plan(p, self.game, self.mods, self.catalog, self.scripts, self.maps,
                                 log=lambda t: self.root.after(0, self.log, t), retail=self.retail)
                    ok += 1
                    self.root.after(0, self.log, '  ' + tr('fertig'), 'ok')
                except Exception as ex:
                    self.root.after(0, self.log, '  ' + tr('FEHLER: {e}').format(e=ex), 'err')
            self.root.after(0, self.log, tr('{a} von {b} umgestellt. Two Worlds jetzt neu starten.').format(a=ok, b=len(todo)), 'ok' if ok == len(todo) else 'err')
            self.root.after(0, self.fill_list)
            self.root.after(0, lambda: self.btn_apply.state(['!disabled']))
            self.root.after(0, lambda: self.set_status(tr('{a} von {b} umgestellt').format(a=ok, b=len(todo)), ok=(ok == len(todo))))

        threading.Thread(target=arbeit, daemon=True).start()

    def start_game(self):
        if C.game_running():
            messagebox.showinfo(tr('Laeuft schon'), tr('Two Worlds laeuft bereits.'))
            return
        exe = os.path.join(self.game, C.GAME_EXE)
        if not os.path.exists(exe):
            exe = os.path.join(self.game, C.GAME_EXE_ALT)
        subprocess.Popen([exe], cwd=self.game, creationflags=0x00000008 | 0x00000200)
        self.log(tr('Two Worlds gestartet.'))

    def show_about(self):
        win = tk.Toplevel(self.root)
        win.title(tr('Ueber'))
        win.configure(background=theme.BG)
        win.transient(self.root)
        theme.dark_titlebar(win)
        f = ttk.Frame(win, padding=16)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text=f'TW1 Savegame Patcher {VERSION}', style='Brand.TLabel').pack(anchor='w')
        ttk.Label(f, text=tr('Hebt Spielstaende von Two Worlds 1 auf die aktiven Mods.\nSkripte mit gleichem Variablenblock werden getauscht, Questskripte mit\nMigrationspfad tragen ihre Quests selbst nach, Karten bekommen ihre Marker.'),
                  style='Muted.TLabel', justify='left').pack(anchor='w', pady=(6, 10))
        for name, url in LINKS:
            lnk = ttk.Label(f, text=f'{name}: {url}', style='Link.TLabel', cursor='hand2')
            lnk.pack(anchor='w', padx=(12, 0))
            lnk.bind('<Button-1>', lambda e, u=url: webbrowser.open(u))
        ttk.Button(f, text=tr('Schliessen'), command=win.destroy).pack(anchor='e', pady=(12, 0))

    def run(self):
        self.root.bind('<F5>', lambda e: self.reload_all())
        self.root.bind('<Control-a>', lambda e: self.tree.selection_set(self.tree.get_children()))
        self.root.mainloop()


# --------------------------------------------------------------- Konsole --

def liste():
    game = C.find_game_dir()
    folder = tw1_save.find_save_dir()
    mods = C.load_mods(game)
    cat = C.script_catalog(game, mods)
    scripts, maps = C.active_content(mods)
    retail = C.T.retail_lnds(list(maps), os.path.join(game, 'WDFiles', 'Levels.wd')) if maps else {}
    print('Spiel', game, '| Staende', folder)
    for m in mods:
        print(f'  {"[x]" if m.active else "[ ]"} {m.name}: {len(m.scripts)} Skripte, {len(m.maps)} Karten')
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith('.twoworldssave'):
            continue
        sv, steps = C.plan(os.path.join(folder, f), game, mods, cat, scripts, maps, retail)
        print(f'{f}  {sv.title!r}  {C.status_of(steps)}')
        for s in steps:
            print('     ', s.kind, '|', s)


# ------------------------------------------------------------ Englisch --

EN = {
    'Spielstaende auf die aktiven Mods umstellen': 'Bring save games up to the active mods',
    'Spielstand': 'Save game', 'gespeichert': 'saved', 'Stand': 'State',
    'Aktive Mods': 'Active mods', 'Was passiert': 'What will happen',
    'Auf die Mods umstellen': 'Patch to active mods', 'Two Worlds starten': 'Start Two Worlds',
    'Datei': 'File', 'Bearbeiten': 'Edit', 'Ansicht': 'View', 'Hilfe': 'Help',
    'Liste neu lesen': 'Reload list', 'Spielstand-Ordner waehlen': 'Choose save folder',
    'Spielordner waehlen': 'Choose game folder', 'Sicherungen oeffnen': 'Open backups',
    'Beenden': 'Quit', 'Alles auswaehlen': 'Select all', 'Umstellbare auswaehlen': 'Select patchable',
    'Sprache': 'Language', 'Guide starten': 'Start guide', 'Dokumentation': 'Documentation', 'Ueber': 'About',
    'Spielordner nicht gefunden - Datei > Spielordner waehlen': 'Game folder not found - File > Choose game folder',
    'Spielstand-Ordner nicht gefunden - Datei > Spielstand-Ordner waehlen': 'Save folder not found - File > Choose save folder',
    '{n} Skripte': '{n} scripts', '{n} Karten': '{n} maps', 'nicht lesbar': 'unreadable', 'nichts im Stand': 'nothing inside saves',
    '{n} Staende, {m} umstellbar': '{n} saves, {m} patchable', 'bereit': 'ready',
    'Nichts zu tun - der Stand kennt alles, was die aktiven Mods liefern.': 'Nothing to do - this save already has everything the active mods provide.',
    'Kein Stand gewaehlt': 'No save selected', 'Bitte links einen oder mehrere Staende markieren.': 'Select one or more saves on the left.',
    'Schon aktuell': 'Already current', 'Die gewaehlten Staende kennen bereits alles, was die aktiven Mods liefern.': 'The selected saves already have everything the active mods provide.',
    'Two Worlds laeuft': 'Two Worlds is running', 'Bitte das Spiel erst beenden. Es liest die Ladeliste nur beim Start.': 'Close the game first. It reads the load list only at startup.',
    'Umstellen': 'Patch', '{n} Stand/Staende auf die aktiven Mods umstellen?\nDie Originale werden nach _vor_Mods gesichert.': 'Patch {n} save(s) to the active mods?\nOriginals are backed up to _vor_Mods.',
    'arbeite ...': 'working ...', 'fertig': 'done', 'FEHLER: {e}': 'ERROR: {e}',
    '{a} von {b} umgestellt. Two Worlds jetzt neu starten.': '{a} of {b} patched. Restart Two Worlds now.',
    '{a} von {b} umgestellt': '{a} of {b} patched', 'Laeuft schon': 'Already running', 'Two Worlds laeuft bereits.': 'Two Worlds is already running.',
    'Two Worlds gestartet.': 'Two Worlds started.', 'Schliessen': 'Close',
    'Hebt Spielstaende von Two Worlds 1 auf die aktiven Mods.\nSkripte mit gleichem Variablenblock werden getauscht, Questskripte mit\nMigrationspfad tragen ihre Quests selbst nach, Karten bekommen ihre Marker.':
        'Brings Two Worlds 1 save games up to the active mods.\nScripts with an unchanged variable block are swapped, quest scripts with a\nmigration path add their quests themselves, maps receive their markers.',
    'Guide': 'Guide', 'Beim Start nicht mehr anzeigen': "Don't show at startup", 'Zurueck': 'Back', 'Weiter': 'Next', 'Fertig': 'Finish',
    'Schritt {n} von {m}': 'Step {n} of {m}',
    'aktuell': 'current', 'umstellbar': 'patchable', 'teilweise': 'partial', 'unbekannt': 'unknown', 'Fehler': 'error',
    'Willkommen': 'Welcome', 'Spielstaende': 'Save games', 'Danach': 'Afterwards',
    'Dieses Werkzeug hebt vorhandene Spielstaende auf die Mods, die gerade aktiv sind - so, als haettest du mit den Mods neu angefangen, nur mit deinem alten Fortschritt.':
        'This tool brings existing save games up to the mods that are currently active - as if you had started a new game with them, but with your old progress.',
    'Hier stehen alle Mods aus dem Mods-Ordner. Aktiv ist, was im Spiel eingeschaltet ist. Dahinter, was eine Mod mitbringt: Skripte und Karten. Nur diese beiden Dinge stecken in einem Spielstand fest.':
        'All mods from the Mods folder. Active means enabled in the game. Behind each: what it provides - scripts and maps. Only those two things are frozen inside a save.',
    'Alle Staende des Spiels mit Datum und Stand. "umstellbar" heisst: eine aktive Mod aendert etwas, das im Stand noch fehlt. "aktuell" heisst: nichts zu tun. "teilweise": ein Skript aendert seine Variablen, das kann nur die Mod selbst - der Rest wird trotzdem umgestellt.':
        'All saves with date and state. "patchable": an active mod changes something the save lacks. "current": nothing to do. "partial": a script changes its variables, which only the mod itself can handle - everything else is patched anyway.',
    'Fuer den markierten Stand siehst du jeden einzelnen Schritt: welches Skript getauscht wird, welche Karte welche Marker bekommt. Nichts davon passiert, bevor du den Knopf drueckst.':
        'For the selected save you see every step: which script is swapped, which map receives which markers. Nothing happens before you press the button.',
    'Markiere einen oder mehrere Staende und druecke hier. Das Original wandert vorher in den Ordner _vor_Mods neben den Staenden, der Stand wird an Ort und Stelle ersetzt - die Ladeliste im Spiel bleibt gleich.':
        'Select one or more saves and press here. The original is backed up to _vor_Mods next to the saves first; the save is replaced in place, so the load list in the game stays the same.',
    'Two Worlds liest die Ladeliste nur beim Start. Also erst umstellen, dann das Spiel starten. Laeuft es schon, verweigert der Knopf mit einem Hinweis.':
        'Two Worlds reads the load list only at startup. Patch first, then start the game. If it is already running, the button refuses with a hint.',
}


def _check_translations():
    import re as _re
    for k in list(EN):
        assert _re.findall(r'\{\w+\}', k) == _re.findall(r'\{\w+\}', EN[k]) or set(_re.findall(r'\{\w+\}', k)) == set(_re.findall(r'\{\w+\}', EN[k])), k
    for s in GUIDE_STEPS:
        assert s['text'] in EN and s['title'] in EN, s['title']


if __name__ == '__main__':
    _check_translations()
    if '--liste' in sys.argv:
        liste()
    else:
        while True:
            app = App()
            app.run()
            if not app.restart:
                break
