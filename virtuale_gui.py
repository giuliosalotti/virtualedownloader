#!/usr/bin/env python3
"""
Virtuale UniBO — Downloader
Interfaccia grafica moderna per scaricare i materiali di qualsiasi corso.

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
#  PALETTE COLORI
# ─────────────────────────────────────────────────────────────

C = {
    "bg":            "#F7F6F3",
    "surface":       "#FFFFFF",
    "border":        "#E5E3DD",
    "border_focus":  "#1A1A18",
    "text":          "#1A1A18",
    "text_muted":    "#888780",
    "text_hint":     "#BBBAB5",
    "accent":        "#1A1A18",
    "accent_fg":     "#FFFFFF",
    "green":         "#2D9E6B",
    "green_light":   "#EAF5F0",
    "red":           "#D85A30",
    "amber":         "#BA7517",
    "blue":          "#185FA5",
    "blue_light":    "#E6F1FB",
    "log_bg":        "#FAFAF8",
    "btn_secondary": "#F0EEE9",
    "btn_sec_hover": "#E5E3DD",
    "btn_hover":     "#333330",
    "disabled":      "#CCCCC8",
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
        title = f"{i:02d} – {raw_title}"
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
            log_fn(f"  ⏭  Già presente: {filename}", "skip")
            return True
        with open(dest, "wb") as f:
            f.write(resp.content)
        size_kb = len(resp.content) / 1024
        log_fn(f"  ✓  {filename}  ({size_kb:.0f} KB)", "ok")
        return True
    except Exception as e:
        log_fn(f"  ✗  Errore: {e}", "err")
        return False


def download_folder_moodle(session, folder_url, dest, folder_name, log_fn, stop_event):
    sub = dest / sanitize(folder_name)
    sub.mkdir(parents=True, exist_ok=True)
    log_fn(f"  📁  Cartella: {folder_name}", "info")
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
            log_fn(f"    ↳  {file_name}", "info")
            download_file(session, file_url, sub, file_name, log_fn, stop_event)
            time.sleep(1.5)
    except Exception as e:
        log_fn(f"  ✗  Errore cartella: {e}", "err")


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
        log_fn(f"  🔗  Link: {name}", "ok")
    except Exception as e:
        log_fn(f"  ✗  Errore link: {e}", "err")


# ─────────────────────────────────────────────────────────────
#  WIDGET PERSONALIZZATI
# ─────────────────────────────────────────────────────────────

class FlatEntry(tk.Frame):
    """Campo di testo con bordo sottile e placeholder."""

    def __init__(self, parent, placeholder="", show="", font=None, **kwargs):
        super().__init__(parent, bg=C["surface"],
                         highlightthickness=1,
                         highlightbackground=C["border"],
                         highlightcolor=C["border_focus"])
        self._placeholder = placeholder
        self._show = show
        self._font = font or ("Helvetica", 12)
        self._showing_placeholder = True

        self.entry = tk.Entry(self, relief="flat", bd=0,
                              bg=C["surface"], fg=C["text_hint"],
                              insertbackground=C["text"],
                              font=self._font, show="")
        self.entry.pack(fill="x", padx=12, pady=9)

        if placeholder:
            self.entry.insert(0, placeholder)

        self.entry.bind("<FocusIn>",  self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

    def _on_focus_in(self, e):
        self.config(highlightbackground=C["border_focus"])
        if self._showing_placeholder:
            self.entry.delete(0, "end")
            self.entry.config(fg=C["text"], show=self._show)
            self._showing_placeholder = False

    def _on_focus_out(self, e):
        self.config(highlightbackground=C["border"])
        if not self.entry.get():
            self.entry.config(show="", fg=C["text_hint"])
            self.entry.insert(0, self._placeholder)
            self._showing_placeholder = True

    def get(self):
        if self._showing_placeholder:
            return ""
        return self.entry.get()

    def set(self, value):
        self.entry.config(show=self._show, fg=C["text"])
        self.entry.delete(0, "end")
        self.entry.insert(0, value)
        self._showing_placeholder = False

    def toggle_show(self):
        if not self._showing_placeholder:
            cur = self.entry.cget("show")
            self.entry.config(show="" if cur == self._show else self._show)


class StatCard(tk.Frame):
    def __init__(self, parent, label, value="–", color=C["text_muted"]):
        super().__init__(parent, bg=C["surface"],
                         highlightthickness=1,
                         highlightbackground=C["border"])
        self._val_lbl = tk.Label(self, text=value,
                                  font=("Helvetica", 28, "bold"),
                                  bg=C["surface"], fg=color)
        self._val_lbl.pack(pady=(16, 2))
        tk.Label(self, text=label.upper(),
                 font=("Helvetica", 9),
                 bg=C["surface"], fg=C["text_hint"],
                 letter_spacing=2).pack(pady=(0, 16))

    def set(self, value):
        self._val_lbl.config(text=str(value))


def flat_btn(parent, text, command, bg, fg, hover_bg, font=None, pady=12):
    """Crea un Label che si comporta come pulsante flat."""
    lbl = tk.Label(parent, text=text,
                   font=font or ("Helvetica", 12, "bold"),
                   bg=bg, fg=fg,
                   padx=0, pady=pady,
                   cursor="hand2")
    lbl._bg = bg
    lbl._hover_bg = hover_bg
    lbl._enabled = True

    def on_enter(e):
        if lbl._enabled:
            lbl.config(bg=lbl._hover_bg)

    def on_leave(e):
        if lbl._enabled:
            lbl.config(bg=lbl._bg)

    def on_click(e):
        if lbl._enabled and command:
            command()

    lbl.bind("<Enter>", on_enter)
    lbl.bind("<Leave>", on_leave)
    lbl.bind("<ButtonRelease-1>", on_click)
    return lbl


def secondary_btn(parent, text, command):
    lbl = tk.Label(parent, text=text,
                   font=("Helvetica", 11),
                   bg=C["btn_secondary"], fg=C["text"],
                   padx=18, pady=12, cursor="hand2",
                   highlightthickness=1,
                   highlightbackground=C["border"])
    lbl.bind("<Enter>", lambda e: lbl.config(bg=C["btn_sec_hover"]))
    lbl.bind("<Leave>", lambda e: lbl.config(bg=C["btn_secondary"]))
    lbl.bind("<ButtonRelease-1>", lambda e: command())
    return lbl


# ─────────────────────────────────────────────────────────────
#  APP PRINCIPALE
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Virtuale UniBO — Downloader")
        self.configure(bg=C["bg"])
        self.minsize(680, 800)
        self.resizable(True, True)

        self._stop_event = threading.Event()
        self._sections   = []
        self._total      = 0
        self._done       = 0
        self._errors     = 0

        self._build_ui()
        self._set_state("idle")

    # ── Costruzione UI ───────────────────────────────────────

    def _build_ui(self):

        # ── Header ──────────────────────────────────────────
        header = tk.Frame(self, bg=C["bg"])
        header.pack(fill="x", padx=30, pady=(26, 0))

        tk.Label(header, text="Virtuale UniBO",
                 font=("Georgia", 24, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w")
        tk.Label(header,
                 text="Scarica i materiali di qualsiasi corso, organizzati per sezione",
                 font=("Helvetica", 12),
                 bg=C["bg"], fg=C["text_muted"]).pack(anchor="w", pady=(3, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=30, pady=20)

        # ── Form ────────────────────────────────────────────
        form = tk.Frame(self, bg=C["bg"])
        form.pack(fill="x", padx=30)

        # Cookie
        row_cookie = tk.Frame(form, bg=C["bg"])
        row_cookie.pack(fill="x", pady=(0, 4))
        tk.Label(row_cookie, text="MOODLE SESSION COOKIE",
                 font=("Helvetica", 9, "bold"), letter_spacing=2,
                 bg=C["bg"], fg=C["text_muted"]).pack(side="left", anchor="w")
        self._cookie_badge = tk.Label(row_cookie, text="",
                                       font=("Helvetica", 9, "bold"),
                                       bg=C["bg"])
        self._cookie_badge.pack(side="right", anchor="e")

        cookie_row = tk.Frame(form, bg=C["bg"])
        cookie_row.pack(fill="x", pady=(0, 16))
        self._cookie_entry = FlatEntry(cookie_row,
                                        placeholder="Incolla qui il cookie MoodleSession…",
                                        show="•",
                                        font=("Courier", 12))
        self._cookie_entry.pack(side="left", fill="x", expand=True)
        eye = tk.Label(cookie_row, text=" 👁 ",
                        font=("Helvetica", 13),
                        bg=C["bg"], cursor="hand2", padx=4)
        eye.pack(side="left")
        eye.bind("<Button-1>", lambda e: self._cookie_entry.toggle_show())

        # URL
        tk.Label(form, text="URL DEL CORSO",
                 font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["text_muted"]).pack(anchor="w", pady=(0, 4))
        self._url_entry = FlatEntry(form,
                                     placeholder="https://virtuale.unibo.it/course/view.php?id=…",
                                     font=("Courier", 12))
        self._url_entry.pack(fill="x", pady=(0, 16))

        # Destinazione
        tk.Label(form, text="CARTELLA DI DESTINAZIONE",
                 font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["text_muted"]).pack(anchor="w", pady=(0, 4))
        dest_row = tk.Frame(form, bg=C["bg"])
        dest_row.pack(fill="x", pady=(0, 4))
        self._dest_entry = FlatEntry(dest_row,
                                      placeholder="Scegli una cartella…",
                                      font=("Helvetica", 12))
        self._dest_entry.set(str(Path.home() / "Desktop" / "Virtuale_Download"))
        self._dest_entry.pack(side="left", fill="x", expand=True)
        browse = secondary_btn(dest_row, "  Sfoglia…", self._browse)
        browse.pack(side="left", padx=(8, 0))

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", padx=30, pady=20)

        # ── Pulsante Analizza ────────────────────────────────
        self._analyze_btn = flat_btn(self,
                                      text="Analizza corso  →",
                                      command=self._analyze,
                                      bg=C["blue_light"], fg=C["blue"],
                                      hover_bg="#D0E5F7",
                                      font=("Helvetica", 12, "bold"),
                                      pady=13)
        self._analyze_btn.pack(fill="x", padx=30)

        # ── Sezioni ──────────────────────────────────────────
        sec_frame = tk.Frame(self, bg=C["bg"])
        sec_frame.pack(fill="x", padx=30, pady=(16, 0))

        self._sections_lbl = tk.Label(sec_frame, text="SEZIONI TROVATE",
                                       font=("Helvetica", 9, "bold"),
                                       bg=C["bg"], fg=C["text_hint"])
        self._sections_lbl.pack(anchor="w", pady=(0, 6))

        sec_card = tk.Frame(sec_frame, bg=C["surface"],
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

        # ── Statistiche ──────────────────────────────────────
        stats = tk.Frame(self, bg=C["bg"])
        stats.pack(fill="x", padx=30, pady=(16, 0))
        for i in range(3):
            stats.columnconfigure(i, weight=1)

        self._stat_ok  = StatCard(stats, "Scaricati", "–", C["green"])
        self._stat_err = StatCard(stats, "Errori",    "–", C["red"])
        self._stat_rem = StatCard(stats, "Rimasti",   "–", C["text_muted"])

        for i, card in enumerate([self._stat_ok, self._stat_err, self._stat_rem]):
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))

        # ── Progress bar ─────────────────────────────────────
        prog_frame = tk.Frame(self, bg=C["bg"])
        prog_frame.pack(fill="x", padx=30, pady=(16, 0))

        self._prog_lbl = tk.Label(prog_frame, text="",
                                   font=("Helvetica", 10),
                                   bg=C["bg"], fg=C["text_hint"])
        self._prog_lbl.pack(anchor="e", pady=(0, 5))

        track = tk.Frame(prog_frame, bg=C["border"], height=5)
        track.pack(fill="x")
        track.pack_propagate(False)
        self._prog_fill = tk.Frame(track, bg=C["green"], height=5)
        self._prog_fill.place(x=0, y=0, relheight=1, relwidth=0)

        # ── Log ──────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=C["bg"])
        log_frame.pack(fill="both", expand=True, padx=30, pady=(16, 0))

        tk.Label(log_frame, text="LOG",
                 font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["text_hint"]).pack(anchor="w", pady=(0, 6))

        log_card = tk.Frame(log_frame, bg=C["log_bg"],
                             highlightthickness=1,
                             highlightbackground=C["border"])
        log_card.pack(fill="both", expand=True)

        self._log = tk.Text(log_card, font=("Courier", 10),
                             bg=C["log_bg"], fg=C["text_muted"],
                             relief="flat", bd=0, state="disabled",
                             wrap="word", cursor="arrow")
        sb = tk.Scrollbar(log_card, command=self._log.yview,
                           relief="flat", bd=0, width=8,
                           bg=C["bg"], troughcolor=C["border"])
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

        # ── Pulsanti azione ──────────────────────────────────
        btn_row = tk.Frame(self, bg=C["bg"])
        btn_row.pack(fill="x", padx=30, pady=(14, 26))

        self._download_btn = flat_btn(btn_row,
                                       text="  Scarica tutto  ↓",
                                       command=self._start_download,
                                       bg=C["accent"], fg=C["accent_fg"],
                                       hover_bg=C["btn_hover"],
                                       font=("Helvetica", 13, "bold"),
                                       pady=14)
        self._download_btn.pack(side="left", fill="x", expand=True)

        self._stop_btn = secondary_btn(btn_row, "  Ferma  ◼", self._stop)
        self._stop_btn.pack(side="left", padx=(10, 0))

        self._open_btn = secondary_btn(btn_row, "  Apri cartella  ↗", self._open_folder)
        self._open_btn.pack(side="left", padx=(10, 0))

    # ── Azioni ───────────────────────────────────────────────

    def _browse(self):
        folder = filedialog.askdirectory(title="Scegli cartella di destinazione")
        if folder:
            self._dest_entry.set(folder)

    def _analyze(self):
        cookie = self._cookie_entry.get().strip()
        url    = self._url_entry.get().strip()
        if not cookie or not url:
            messagebox.showwarning("Campi mancanti", "Inserisci il cookie e l'URL del corso.")
            return
        self._set_state("analyzing")
        threading.Thread(target=self._th_analyze, args=(cookie, url), daemon=True).start()

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

        self._cookie_badge.config(text="● Sessione valida", fg=C["green"])
        self._stat_ok.set("0")
        self._stat_err.set("0")
        self._stat_rem.set(str(total))
        self._set_state("ready")
        self._write_log(f"Trovate {len(sections)} sezioni · {total} risorse totali", "ok")

    def _analyze_fail(self, err):
        self._cookie_badge.config(text="● Sessione non valida", fg=C["red"])
        messagebox.showerror("Errore analisi", err)
        self._set_state("idle")

    def _start_download(self):
        if not self._sections:
            messagebox.showwarning("Prima analizza", "Clicca prima su 'Analizza corso'.")
            return
        dest = self._dest_entry.get().strip()
        if not dest:
            messagebox.showwarning("Cartella mancante", "Scegli una cartella di destinazione.")
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
                    self.after(0, self._write_log, f"  ↓  {name}", "info")
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
                    self.after(0, self._write_log, f"  –  Forum ignorato: {name}", "skip")

                rem = max(0, self._total - self._done - self._errors)
                pct = (self._done + self._errors) / max(self._total, 1)
                self.after(0, self._update_progress, self._done, self._errors, rem, pct)

        self.after(0, self._download_done)

    def _download_done(self):
        self._set_state("done")
        self._write_log(f"\nCompletato — {self._done} scaricati, {self._errors} errori.", "ok")
        messagebox.showinfo("Download completato",
                            f"Scaricati:  {self._done}\n"
                            f"Errori:     {self._errors}\n\n"
                            f"Cartella:\n{self._dest_entry.get()}")

    def _stop(self):
        self._stop_event.set()
        self._write_log("\nDownload interrotto dall'utente.", "warn")
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

    # ── Helpers UI ───────────────────────────────────────────

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
        self._prog_lbl.config(text=f"{pct*100:.0f}%  ·  {ok + err} di {self._total}")

    def _set_state(self, state):
        if state == "idle":
            self._analyze_btn.config(text="Analizza corso  →",
                                      bg=C["blue_light"], fg=C["blue"])
            self._analyze_btn._bg       = C["blue_light"]
            self._analyze_btn._hover_bg = "#D0E5F7"
            self._analyze_btn._enabled  = True
            self._analyze_btn.config(cursor="hand2")
            self._download_btn.config(bg=C["disabled"], fg=C["surface"], cursor="arrow")
            self._download_btn._enabled = False

        elif state == "analyzing":
            self._analyze_btn.config(text="Analisi in corso…",
                                      bg=C["border"], fg=C["text_hint"], cursor="arrow")
            self._analyze_btn._enabled  = False
            self._download_btn.config(bg=C["disabled"], fg=C["surface"], cursor="arrow")
            self._download_btn._enabled = False

        elif state == "ready":
            self._analyze_btn.config(text="Ri-analizza  →",
                                      bg=C["blue_light"], fg=C["blue"], cursor="hand2")
            self._analyze_btn._bg       = C["blue_light"]
            self._analyze_btn._hover_bg = "#D0E5F7"
            self._analyze_btn._enabled  = True
            self._download_btn.config(text="  Scarica tutto  ↓",
                                       bg=C["accent"], fg=C["accent_fg"], cursor="hand2")
            self._download_btn._bg      = C["accent"]
            self._download_btn._hover_bg = C["btn_hover"]
            self._download_btn._enabled = True

        elif state == "downloading":
            self._analyze_btn.config(bg=C["border"], fg=C["text_hint"], cursor="arrow")
            self._analyze_btn._enabled  = False
            self._download_btn.config(text="  Download in corso…",
                                       bg=C["disabled"], fg=C["surface"], cursor="arrow")
            self._download_btn._enabled = False

        elif state == "done":
            self._analyze_btn.config(text="Ri-analizza  →",
                                      bg=C["blue_light"], fg=C["blue"], cursor="hand2")
            self._analyze_btn._bg       = C["blue_light"]
            self._analyze_btn._enabled  = True
            self._download_btn.config(text="  Scarica tutto  ↓",
                                       bg=C["accent"], fg=C["accent_fg"], cursor="hand2")
            self._download_btn._bg      = C["accent"]
            self._download_btn._hover_bg = C["btn_hover"]
            self._download_btn._enabled = True


# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
