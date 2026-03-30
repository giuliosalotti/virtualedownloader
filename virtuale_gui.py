#!/usr/bin/env python3
"""
Virtuale UniBO — Downloader
Interfaccia grafica per scaricare i materiali di qualsiasi corso.

REQUISITI:
    pip install requests beautifulsoup4

AVVIO:
    python virtuale_gui.py
"""

import os
import re
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from urllib.parse import unquote
import subprocess
import platform

import requests
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────
#  PALETTE
# ─────────────────────────────────────────────────────────────

C = {
    "bg":           "#F7F6F3",
    "surface":      "#FFFFFF",
    "border":       "#E5E3DD",
    "border_focus": "#1A1A18",
    "text":         "#1A1A18",
    "text_muted":   "#888780",
    "text_hint":    "#BBBAB5",
    "accent":       "#1A1A18",
    "accent_fg":    "#FFFFFF",
    "green":        "#2D9E6B",
    "red":          "#D85A30",
    "amber":        "#BA7517",
    "blue":         "#185FA5",
    "blue_light":   "#E6F1FB",
    "log_bg":       "#FAFAF8",
    "btn_sec":      "#F0EEE9",
    "btn_sec_h":    "#E5E3DD",
    "btn_hover":    "#333330",
    "disabled_bg":  "#DDDBD6",
    "disabled_fg":  "#AAAAAA",
}


# ─────────────────────────────────────────────────────────────
#  LOGICA DI DOWNLOAD
# ─────────────────────────────────────────────────────────────

EXT_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}


def sanitize(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip(' .-')
    return name[:max_len] or "senza_nome"


def build_session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("MoodleSession", cookie, domain="virtuale.unibo.it")
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniBO-Downloader/3.0)"})
    return s


def filename_from_response(resp, fallback):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1)).strip()
    m = re.search(r'filename="?([^";\r\n]+)"?', cd)
    if m:
        return m.group(1).strip()
    return fallback


def parse_course(session, course_url):
    resp = session.get(course_url, timeout=30)
    resp.raise_for_status()
    if "login" in resp.url:
        raise ValueError("Sessione scaduta o non valida.\nRinnova il cookie MoodleSession dal browser.")
    soup = BeautifulSoup(resp.text, "html.parser")
    sections_els = soup.find_all("li", class_=lambda c: c and "section" in c.split())
    result = []
    for i, sec in enumerate(sections_els):
        title_el = sec.find("h3") or sec.find("h2") or sec.find(class_="sectionname")
        raw_title = title_el.get_text(strip=True) if title_el else f"Sezione {i}"
        title = f"{i:02d} - {raw_title}"
        items = []
        for act in sec.find_all("li", class_=lambda c: c and "activity" in c.split()):
            a = act.find("a", href=True)
            if not a:
                continue
            classes = " ".join(act.get("class", []))
            if "resource" in classes:
                kind = "file"
            elif "folder" in classes:
                kind = "folder"
            elif "url" in classes:
                kind = "url"
            elif "forum" in classes:
                kind = "forum"
            else:
                kind = "other"
            name = a.get_text(strip=True)
            for suffix in ("File", "Cartella", "URL", "Forum", "Compito", "Pagina"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)].strip()
            items.append({"name": name, "url": a["href"], "type": kind})
        result.append({"title": title, "items": items})
    return result


def download_file(session, url, dest_folder, name_hint, log_fn, stop_event):
    if stop_event.is_set():
        return False
    try:
        resp = session.get(url, allow_redirects=True, timeout=30)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "text/html" in ct:
            soup = BeautifulSoup(resp.text, "html.parser")
            link = soup.find("a", href=re.compile(r"pluginfile\.php"))
            if link:
                if stop_event.is_set():
                    return False
                resp = session.get(link["href"], allow_redirects=True, timeout=60)
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "")
            else:
                log_fn(f"  ⚠  Nessun file trovato: {name_hint}", "warn")
                return False
        ct_base = ct.split(";")[0].strip()
        fallback_ext = EXT_MAP.get(ct_base, ".bin")
        raw_name = filename_from_response(resp, sanitize(name_hint) + fallback_ext)
        filename = sanitize(raw_name)
        if not Path(filename).suffix:
            filename += fallback_ext
        dest = dest_folder / filename
        if dest.exists():
            log_fn(f"  ⏭  Gia presente: {filename}", "skip")
            return True
        with open(dest, "wb") as f:
            f.write(resp.content)
        size_kb = len(resp.content) / 1024
        log_fn(f"  OK  {filename}  ({size_kb:.0f} KB)", "ok")
        return True
    except Exception as e:
        log_fn(f"  ERR  {e}", "err")
        return False


def download_folder_moodle(session, folder_url, dest, folder_name, log_fn, stop_event):
    sub = dest / sanitize(folder_name)
    sub.mkdir(parents=True, exist_ok=True)
    log_fn(f"  Cartella: {folder_name}", "info")
    try:
        resp = session.get(folder_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"pluginfile\.php"))
        if not links:
            log_fn("    ⚠  Cartella vuota o accesso negato", "warn")
            return
        for a in links:
            if stop_event.is_set():
                return
            file_url = a["href"]
            file_name = a.get_text(strip=True) or Path(file_url).name
            log_fn(f"    -> {file_name}", "info")
            download_file(session, file_url, sub, file_name, log_fn, stop_event)
            time.sleep(1.5)
    except Exception as e:
        log_fn(f"  ERR cartella: {e}", "err")


def save_url_shortcut(session, url_page, dest_folder, name, log_fn):
    try:
        resp = session.get(url_page, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        ext = soup.find("a", href=re.compile(r"^https?://(?!virtuale\.unibo\.it)"))
        external_url = ext["href"] if ext else url_page
        fname = dest_folder / (sanitize(name) + ".url")
        with open(fname, "w", encoding="utf-8") as f:
            f.write("[InternetShortcut]\n")
            f.write(f"URL={external_url}\n")
        log_fn(f"  Link: {name}", "ok")
    except Exception as e:
        log_fn(f"  ERR link: {e}", "err")


# ─────────────────────────────────────────────────────────────
#  WIDGET PERSONALIZZATI
# ─────────────────────────────────────────────────────────────

class FlatEntry(tk.Frame):
    """Campo input con bordo sottile e placeholder."""

    def __init__(self, parent, placeholder="", show="", font=None, **kwargs):
        super().__init__(parent, bg=C["surface"],
                         highlightthickness=1,
                         highlightbackground=C["border"],
                         highlightcolor=C["border_focus"])
        self._placeholder = placeholder
        self._show = show
        self._is_placeholder = True

        self.entry = tk.Entry(self, relief="flat", bd=0,
                              bg=C["surface"], fg=C["text_hint"],
                              insertbackground=C["text"],
                              font=font or ("Helvetica", 12))
        self.entry.pack(fill="x", padx=12, pady=9)

        if placeholder:
            self.entry.insert(0, placeholder)

        self.entry.bind("<FocusIn>",  self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)

    def _focus_in(self, e):
        self.config(highlightbackground=C["border_focus"])
        if self._is_placeholder:
            self.entry.delete(0, "end")
            self.entry.config(fg=C["text"], show=self._show)
            self._is_placeholder = False

    def _focus_out(self, e):
        self.config(highlightbackground=C["border"])
        if not self.entry.get():
            self.entry.config(show="", fg=C["text_hint"])
            self.entry.insert(0, self._placeholder)
            self._is_placeholder = True

    def get(self):
        return "" if self._is_placeholder else self.entry.get()

    def set(self, value):
        self.entry.config(show=self._show, fg=C["text"])
        self.entry.delete(0, "end")
        self.entry.insert(0, value)
        self._is_placeholder = False

    def toggle_show(self):
        if not self._is_placeholder:
            cur = self.entry.cget("show")
            self.entry.config(show="" if cur == self._show else self._show)


class StatCard(tk.Frame):
    def __init__(self, parent, label, value="–", color=C["text_muted"]):
        super().__init__(parent, bg=C["surface"],
                         highlightthickness=1,
                         highlightbackground=C["border"])
        self._val = tk.Label(self, text=value,
                              font=("Helvetica", 26, "bold"),
                              bg=C["surface"], fg=color)
        self._val.pack(pady=(14, 2))
        tk.Label(self, text=label,
                 font=("Helvetica", 10),
                 bg=C["surface"], fg=C["text_hint"]).pack(pady=(0, 14))

    def set(self, value):
        self._val.config(text=str(value))


# ─────────────────────────────────────────────────────────────
#  APP
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Virtuale UniBO — Downloader")
        self.configure(bg=C["bg"])
        self.geometry("700x860")
        self.minsize(640, 780)

        self._stop_event = threading.Event()
        self._sections   = []
        self._total      = 0
        self._done       = 0
        self._errors     = 0

        self._build_ui()
        self._set_state("idle")

    def _build_ui(self):
        # Layout principale: top fisso + middle espandibile + bottom fisso
        # Questo garantisce che i pulsanti siano SEMPRE visibili in fondo

        # ── TOP (fisso) ──────────────────────────────────────
        top = tk.Frame(self, bg=C["bg"])
        top.pack(side="top", fill="x")

        # Header
        hdr = tk.Frame(top, bg=C["bg"])
        hdr.pack(fill="x", padx=30, pady=(24, 0))
        tk.Label(hdr, text="Virtuale UniBO",
                 font=("Georgia", 22, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w")
        tk.Label(hdr, text="Scarica i materiali di qualsiasi corso organizzati per sezione",
                 font=("Helvetica", 11),
                 bg=C["bg"], fg=C["text_muted"]).pack(anchor="w", pady=(2, 0))

        tk.Frame(top, bg=C["border"], height=1).pack(fill="x", padx=30, pady=18)

        # Form
        form = tk.Frame(top, bg=C["bg"])
        form.pack(fill="x", padx=30)

        # Cookie
        self._mk_label(form, "COOKIE MOODLESESSION")
        cookie_row = tk.Frame(form, bg=C["bg"])
        cookie_row.pack(fill="x", pady=(4, 14))

        self._cookie_entry = FlatEntry(cookie_row,
                                        placeholder="Incolla qui il cookie MoodleSession...",
                                        show="*",
                                        font=("Courier", 12))
        self._cookie_entry.pack(side="left", fill="x", expand=True)

        tk.Label(cookie_row, text=" Mostra ",
                 font=("Helvetica", 10),
                 bg=C["btn_sec"], fg=C["text"],
                 padx=8, pady=9, cursor="hand2",
                 highlightthickness=1,
                 highlightbackground=C["border"]).pack(side="left", padx=(8, 0))
        cookie_row.winfo_children()[-1].bind(
            "<Button-1>", lambda e: self._cookie_entry.toggle_show())

        self._cookie_badge = tk.Label(cookie_row, text="",
                                       font=("Helvetica", 10, "bold"),
                                       bg=C["bg"], padx=6)
        self._cookie_badge.pack(side="left")

        # URL corso
        self._mk_label(form, "URL DEL CORSO")
        self._url_entry = FlatEntry(form,
                                     placeholder="https://virtuale.unibo.it/course/view.php?id=...",
                                     font=("Courier", 12))
        self._url_entry.pack(fill="x", pady=(4, 14))

        # Destinazione
        self._mk_label(form, "CARTELLA DI DESTINAZIONE")
        dest_row = tk.Frame(form, bg=C["bg"])
        dest_row.pack(fill="x", pady=(4, 0))

        self._dest_entry = FlatEntry(dest_row,
                                      placeholder="Scegli una cartella...",
                                      font=("Helvetica", 12))
        self._dest_entry.set(str(Path.home() / "Desktop" / "Virtuale_Download"))
        self._dest_entry.pack(side="left", fill="x", expand=True)

        sfoglia = tk.Label(dest_row, text="  Sfoglia...  ",
                            font=("Helvetica", 11),
                            bg=C["btn_sec"], fg=C["text"],
                            pady=9, cursor="hand2",
                            highlightthickness=1,
                            highlightbackground=C["border"])
        sfoglia.pack(side="left", padx=(8, 0))
        sfoglia.bind("<Enter>", lambda e: sfoglia.config(bg=C["btn_sec_h"]))
        sfoglia.bind("<Leave>", lambda e: sfoglia.config(bg=C["btn_sec"]))
        sfoglia.bind("<Button-1>", lambda e: self._browse())

        tk.Frame(top, bg=C["border"], height=1).pack(fill="x", padx=30, pady=18)

        # Pulsante Analizza
        self._analyze_btn = tk.Label(top, text="  Analizza corso  ->",
                                      font=("Helvetica", 12, "bold"),
                                      bg=C["blue_light"], fg=C["blue"],
                                      pady=13, cursor="hand2")
        self._analyze_btn.pack(fill="x", padx=30)
        self._analyze_btn.bind("<Enter>",
                                lambda e: self._analyze_btn.config(bg="#D0E5F7")
                                if self._analyze_enabled else None)
        self._analyze_btn.bind("<Leave>",
                                lambda e: self._analyze_btn.config(bg=C["blue_light"])
                                if self._analyze_enabled else None)
        self._analyze_btn.bind("<Button-1>", lambda e: self._analyze())
        self._analyze_enabled = True

        # Sezioni trovate
        sec_outer = tk.Frame(top, bg=C["bg"])
        sec_outer.pack(fill="x", padx=30, pady=(16, 0))

        tk.Label(sec_outer, text="SEZIONI TROVATE",
                 font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["text_hint"]).pack(anchor="w", pady=(0, 6))

        sec_card = tk.Frame(sec_outer, bg=C["surface"],
                             highlightthickness=1,
                             highlightbackground=C["border"])
        sec_card.pack(fill="x")

        self._sections_text = tk.Text(sec_card, height=5,
                                       font=("Helvetica", 11),
                                       bg=C["surface"], fg=C["text_muted"],
                                       relief="flat", bd=0,
                                       state="disabled",
                                       wrap="word", cursor="arrow")
        self._sections_text.pack(fill="x", padx=14, pady=10)

        # Statistiche
        stats_frame = tk.Frame(top, bg=C["bg"])
        stats_frame.pack(fill="x", padx=30, pady=(16, 0))
        for i in range(3):
            stats_frame.columnconfigure(i, weight=1)

        self._stat_ok  = StatCard(stats_frame, "Scaricati", "–", C["green"])
        self._stat_err = StatCard(stats_frame, "Errori",    "–", C["red"])
        self._stat_rem = StatCard(stats_frame, "Rimasti",   "–", C["text_muted"])
        for i, card in enumerate([self._stat_ok, self._stat_err, self._stat_rem]):
            card.grid(row=0, column=i, sticky="ew",
                      padx=(0 if i == 0 else 8, 0), pady=0)

        # Progress bar
        prog = tk.Frame(top, bg=C["bg"])
        prog.pack(fill="x", padx=30, pady=(14, 0))
        self._prog_lbl = tk.Label(prog, text="",
                                   font=("Helvetica", 10),
                                   bg=C["bg"], fg=C["text_hint"])
        self._prog_lbl.pack(anchor="e", pady=(0, 4))
        track = tk.Frame(prog, bg=C["border"], height=6)
        track.pack(fill="x")
        track.pack_propagate(False)
        self._prog_fill = tk.Frame(track, bg=C["green"], height=6)
        self._prog_fill.place(x=0, y=0, relheight=1, relwidth=0)

        # ── MIDDLE (espandibile) — Log ───────────────────────
        mid = tk.Frame(self, bg=C["bg"])
        mid.pack(side="top", fill="both", expand=True, padx=30, pady=(14, 0))

        tk.Label(mid, text="LOG",
                 font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["text_hint"]).pack(anchor="w", pady=(0, 6))

        log_card = tk.Frame(mid, bg=C["log_bg"],
                             highlightthickness=1,
                             highlightbackground=C["border"])
        log_card.pack(fill="both", expand=True)

        self._log = tk.Text(log_card, font=("Courier", 10),
                             bg=C["log_bg"], fg=C["text_muted"],
                             relief="flat", bd=0,
                             state="disabled", wrap="word", cursor="arrow")
        sb = tk.Scrollbar(log_card, command=self._log.yview,
                           relief="flat", bd=0, width=8)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=4, padx=(0, 2))
        self._log.pack(fill="both", expand=True, padx=12, pady=10)

        self._log.tag_config("ok",      foreground=C["green"])
        self._log.tag_config("err",     foreground=C["red"])
        self._log.tag_config("warn",    foreground=C["amber"])
        self._log.tag_config("skip",    foreground=C["text_hint"])
        self._log.tag_config("info",    foreground=C["text_muted"])
        self._log.tag_config("section", foreground=C["text"],
                              font=("Courier", 10, "bold"))

        # ── BOTTOM (fisso) — Pulsanti ────────────────────────
        # Separatore sopra i pulsanti
        tk.Frame(self, bg=C["border"], height=1).pack(side="top", fill="x", padx=30)

        bottom = tk.Frame(self, bg=C["bg"])
        bottom.pack(side="bottom", fill="x", padx=30, pady=20)

        # Pulsante DOWNLOAD (grande, sempre visibile)
        self._download_btn = tk.Label(bottom,
                                       text="  Scarica tutto  v",
                                       font=("Helvetica", 13, "bold"),
                                       bg=C["disabled_bg"], fg=C["disabled_fg"],
                                       pady=15, cursor="arrow")
        self._download_btn.pack(side="left", fill="x", expand=True)
        self._download_btn.bind("<Enter>", self._dl_hover_in)
        self._download_btn.bind("<Leave>", self._dl_hover_out)
        self._download_btn.bind("<Button-1>", lambda e: self._start_download())
        self._download_enabled = False

        # Pulsante Ferma
        self._stop_btn = tk.Label(bottom, text="  Ferma  ",
                                   font=("Helvetica", 11),
                                   bg=C["btn_sec"], fg=C["text"],
                                   pady=15, padx=16, cursor="hand2",
                                   highlightthickness=1,
                                   highlightbackground=C["border"])
        self._stop_btn.pack(side="left", padx=(10, 0))
        self._stop_btn.bind("<Enter>", lambda e: self._stop_btn.config(bg=C["btn_sec_h"]))
        self._stop_btn.bind("<Leave>", lambda e: self._stop_btn.config(bg=C["btn_sec"]))
        self._stop_btn.bind("<Button-1>", lambda e: self._stop())

        # Pulsante Apri cartella
        self._open_btn = tk.Label(bottom, text="  Apri cartella  ",
                                   font=("Helvetica", 11),
                                   bg=C["btn_sec"], fg=C["text"],
                                   pady=15, padx=16, cursor="hand2",
                                   highlightthickness=1,
                                   highlightbackground=C["border"])
        self._open_btn.pack(side="left", padx=(10, 0))
        self._open_btn.bind("<Enter>", lambda e: self._open_btn.config(bg=C["btn_sec_h"]))
        self._open_btn.bind("<Leave>", lambda e: self._open_btn.config(bg=C["btn_sec"]))
        self._open_btn.bind("<Button-1>", lambda e: self._open_folder())

    def _mk_label(self, parent, text):
        tk.Label(parent, text=text,
                 font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["text_muted"]).pack(anchor="w")

    def _dl_hover_in(self, e):
        if self._download_enabled:
            self._download_btn.config(bg=C["btn_hover"])

    def _dl_hover_out(self, e):
        if self._download_enabled:
            self._download_btn.config(bg=C["accent"])

    # ── Azioni ───────────────────────────────────────────────

    def _browse(self):
        folder = filedialog.askdirectory(title="Scegli cartella di destinazione")
        if folder:
            self._dest_entry.set(folder)

    def _analyze(self):
        if not self._analyze_enabled:
            return
        cookie = self._cookie_entry.get().strip()
        url    = self._url_entry.get().strip()
        if not cookie or not url:
            messagebox.showwarning("Campi mancanti",
                                   "Inserisci il cookie MoodleSession e l'URL del corso.")
            return
        self._set_state("analyzing")
        threading.Thread(target=self._th_analyze,
                         args=(cookie, url), daemon=True).start()

    def _th_analyze(self, cookie, url):
        try:
            session  = build_session(cookie)
            sections = parse_course(session, url)
            total    = sum(len(s["items"]) for s in sections)
            self.after(0, self._analyze_ok, sections, total)
        except Exception as e:
            self.after(0, self._analyze_fail, str(e))

    def _analyze_ok(self, sections, total):
        self._sections = sections
        self._total    = total
        self._done     = 0
        self._errors   = 0

        self._sections_text.config(state="normal")
        self._sections_text.delete("1.0", "end")
        for s in sections:
            n = len(s["items"])
            self._sections_text.insert("end", f"  {s['title']}   ({n} risorse)\n")
        self._sections_text.config(state="disabled")

        self._cookie_badge.config(text="Valido", fg=C["green"])
        self._stat_ok.set("0")
        self._stat_err.set("0")
        self._stat_rem.set(str(total))
        self._set_state("ready")
        self._write_log(f"Trovate {len(sections)} sezioni, {total} risorse totali.", "ok")

    def _analyze_fail(self, err):
        self._cookie_badge.config(text="Errore", fg=C["red"])
        messagebox.showerror("Errore analisi", err)
        self._set_state("idle")

    def _start_download(self):
        if not self._download_enabled:
            return
        dest = self._dest_entry.get().strip()
        if not dest:
            messagebox.showwarning("Cartella mancante",
                                   "Scegli una cartella di destinazione.")
            return
        cookie = self._cookie_entry.get().strip()
        self._stop_event.clear()
        self._done   = 0
        self._errors = 0
        self._stat_ok.set("0")
        self._stat_err.set("0")
        self._stat_rem.set(str(self._total))
        self._set_state("downloading")
        threading.Thread(target=self._th_download,
                         args=(cookie, self._sections, Path(dest)),
                         daemon=True).start()

    def _th_download(self, cookie, sections, base_path):
        session = build_session(cookie)
        base_path.mkdir(parents=True, exist_ok=True)

        for section in sections:
            if self._stop_event.is_set():
                break
            folder_path = base_path / sanitize(section["title"])
            folder_path.mkdir(parents=True, exist_ok=True)
            self.after(0, self._write_log, f"\n{section['title']}", "section")

            for item in section["items"]:
                if self._stop_event.is_set():
                    break

                name = item["name"]
                url  = item["url"]
                kind = item["type"]

                def log(m, t):
                    self.after(0, self._write_log, m, t)

                if kind == "file":
                    self.after(0, self._write_log, f"  -> {name}", "info")
                    ok = download_file(session, url, folder_path, name,
                                       log, self._stop_event)
                    if ok:
                        self._done += 1
                    else:
                        self._errors += 1
                    time.sleep(1.5)

                elif kind == "folder":
                    download_folder_moodle(session, url, folder_path, name,
                                           log, self._stop_event)
                    self._done += 1
                    time.sleep(1.5)

                elif kind == "url":
                    save_url_shortcut(session, url, folder_path, name, log)
                    self._done += 1

                elif kind == "forum":
                    self.after(0, self._write_log,
                               f"  - Forum ignorato: {name}", "skip")

                rem = max(0, self._total - self._done - self._errors)
                pct = (self._done + self._errors) / max(self._total, 1)
                self.after(0, self._update_progress,
                           self._done, self._errors, rem, pct)

        self.after(0, self._download_done)

    def _download_done(self):
        self._set_state("done")
        self._write_log(
            f"\nCompletato — {self._done} scaricati, {self._errors} errori.", "ok")
        messagebox.showinfo("Download completato",
                            f"Scaricati:  {self._done}\n"
                            f"Errori:     {self._errors}\n\n"
                            f"Cartella:\n{self._dest_entry.get()}")

    def _stop(self):
        self._stop_event.set()
        self._write_log("\nDownload interrotto.", "warn")
        self._set_state("ready")

    def _open_folder(self):
        dest = self._dest_entry.get().strip()
        if not dest:
            return
        Path(dest).mkdir(parents=True, exist_ok=True)
        sys = platform.system()
        if sys == "Darwin":
            subprocess.run(["open", dest])
        elif sys == "Windows":
            os.startfile(dest)
        else:
            subprocess.run(["xdg-open", dest])

    # ── Helpers ──────────────────────────────────────────────

    def _write_log(self, message, tag="info"):
        self._log.config(state="normal")
        self._log.insert("end", message + "\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _update_progress(self, ok, err, rem, pct):
        self._stat_ok.set(str(ok))
        self._stat_err.set(str(err))
        self._stat_rem.set(str(rem))
        self._prog_fill.place(relwidth=pct)
        self._prog_lbl.config(
            text=f"{pct*100:.0f}%  -  {ok + err} di {self._total}")

    def _set_state(self, state):
        if state == "idle":
            # Analizza: attivo
            self._analyze_btn.config(text="  Analizza corso  ->",
                                      bg=C["blue_light"], fg=C["blue"],
                                      cursor="hand2")
            self._analyze_enabled = True
            # Download: disabilitato
            self._download_btn.config(text="  Scarica tutto  v",
                                       bg=C["disabled_bg"], fg=C["disabled_fg"],
                                       cursor="arrow")
            self._download_enabled = False

        elif state == "analyzing":
            self._analyze_btn.config(text="  Analisi in corso...",
                                      bg=C["border"], fg=C["text_hint"],
                                      cursor="arrow")
            self._analyze_enabled = False
            self._download_btn.config(bg=C["disabled_bg"], fg=C["disabled_fg"],
                                       cursor="arrow")
            self._download_enabled = False

        elif state == "ready":
            # Analizza: ri-analizza
            self._analyze_btn.config(text="  Ri-analizza  ->",
                                      bg=C["blue_light"], fg=C["blue"],
                                      cursor="hand2")
            self._analyze_enabled = True
            # Download: ATTIVO e ben visibile
            self._download_btn.config(text="  Scarica tutto  v",
                                       bg=C["accent"], fg=C["accent_fg"],
                                       cursor="hand2")
            self._download_enabled = True

        elif state == "downloading":
            self._analyze_btn.config(bg=C["border"], fg=C["text_hint"],
                                      cursor="arrow")
            self._analyze_enabled = False
            self._download_btn.config(text="  Download in corso...",
                                       bg=C["disabled_bg"], fg=C["disabled_fg"],
                                       cursor="arrow")
            self._download_enabled = False

        elif state == "done":
            self._analyze_btn.config(text="  Ri-analizza  ->",
                                      bg=C["blue_light"], fg=C["blue"],
                                      cursor="hand2")
            self._analyze_enabled = True
            self._download_btn.config(text="  Scarica tutto  v",
                                       bg=C["accent"], fg=C["accent_fg"],
                                       cursor="hand2")
            self._download_enabled = True


# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()