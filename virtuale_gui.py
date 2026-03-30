#!/usr/bin/env python3
"""
Virtuale UniBO — Downloader con interfaccia grafica
Funziona con qualsiasi corso su virtuale.unibo.it

REQUISITI:
    pip install requests beautifulsoup4
    (tkinter è già incluso in Python)

UTILIZZO:
    python virtuale_gui.py
"""

import os
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────
#  LOGICA DI DOWNLOAD  (identica allo script CLI)
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
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniBO-Downloader/2.0)"})
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
        raise ValueError("Sessione scaduta o non valida. Rinnova il cookie MoodleSession.")
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


def download_folder(session, folder_url, dest, folder_name, log_fn, stop_event):
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
        log_fn(f"  🔗  Link salvato: {name}", "ok")
    except Exception as e:
        log_fn(f"  ✗  Errore link: {e}", "err")


# ─────────────────────────────────────────────────────────────
#  INTERFACCIA GRAFICA
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Virtuale UniBO — Downloader")
        self.resizable(True, True)
        self.minsize(620, 700)

        self._stop_event   = threading.Event()
        self._thread       = None
        self._sections     = []
        self._total_files  = 0
        self._done_files   = 0
        self._err_files    = 0

        self._build_ui()
        self._set_state("idle")

    # ── costruzione UI ──────────────────────────────────────

    def _build_ui(self):
        PAD = {"padx": 16, "pady": 6}
        self.configure(bg="#f5f5f3")

        # ── Titolo ──────────────────────────────────────────
        header = tk.Frame(self, bg="#f5f5f3")
        header.pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(header, text="Virtuale UniBO — Downloader",
                 font=("Helvetica", 15, "bold"),
                 bg="#f5f5f3", fg="#1a1a18").pack(anchor="w")
        tk.Label(header, text="Scarica i materiali di qualsiasi corso organizzati per sezione",
                 font=("Helvetica", 11), bg="#f5f5f3", fg="#6b6b67").pack(anchor="w")

        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x", padx=16, pady=8)

        # ── Campi input ─────────────────────────────────────
        form = tk.Frame(self, bg="#f5f5f3")
        form.pack(fill="x", **PAD)

        # Cookie
        self._make_label(form, "Cookie MoodleSession")
        self._cookie_var = tk.StringVar()
        cookie_frame = tk.Frame(form, bg="#f5f5f3")
        cookie_frame.pack(fill="x", pady=(0, 10))
        self._cookie_entry = tk.Entry(cookie_frame, textvariable=self._cookie_var,
                                      show="•", font=("Courier", 11),
                                      relief="solid", bd=1, bg="white", fg="#1a1a18")
        self._cookie_entry.pack(side="left", fill="x", expand=True)
        self._eye_btn = tk.Button(cookie_frame, text="👁", relief="flat", bg="#f5f5f3",
                                  cursor="hand2", command=self._toggle_cookie_visibility)
        self._eye_btn.pack(side="left", padx=(6, 0))
        self._cookie_status = tk.Label(cookie_frame, text="", font=("Helvetica", 10),
                                       bg="#f5f5f3")
        self._cookie_status.pack(side="left", padx=(6, 0))

        # URL
        self._make_label(form, "URL del corso  (es. https://virtuale.unibo.it/course/view.php?id=12345)")
        self._url_var = tk.StringVar()
        tk.Entry(form, textvariable=self._url_var, font=("Courier", 11),
                 relief="solid", bd=1, bg="white", fg="#1a1a18").pack(fill="x", pady=(0, 10))

        # Destinazione
        self._make_label(form, "Cartella di destinazione")
        dest_frame = tk.Frame(form, bg="#f5f5f3")
        dest_frame.pack(fill="x", pady=(0, 10))
        self._dest_var = tk.StringVar(value=str(Path.home() / "Desktop" / "Virtuale_Download"))
        tk.Entry(dest_frame, textvariable=self._dest_var, font=("Courier", 11),
                 relief="solid", bd=1, bg="white", fg="#1a1a18").pack(side="left", fill="x", expand=True)
        tk.Button(dest_frame, text="Sfoglia…", relief="solid", bd=1, bg="white",
                  font=("Helvetica", 11), cursor="hand2",
                  command=self._browse_folder).pack(side="left", padx=(6, 0))

        # ── Pulsante Analizza ────────────────────────────────
        self._analyze_btn = tk.Button(self, text="🔍  Analizza corso",
                                      font=("Helvetica", 12, "bold"),
                                      bg="#378ADD", fg="white", activebackground="#185FA5",
                                      relief="flat", padx=16, pady=8, cursor="hand2",
                                      command=self._analyze)
        self._analyze_btn.pack(fill="x", padx=16, pady=(4, 2))

        # ── Anteprima sezioni ────────────────────────────────
        self._sections_frame = tk.LabelFrame(self, text="Sezioni trovate",
                                             font=("Helvetica", 11),
                                             bg="#f5f5f3", fg="#444441",
                                             relief="solid", bd=1)
        self._sections_frame.pack(fill="x", padx=16, pady=6)

        self._sections_text = tk.Text(self._sections_frame, height=5,
                                      font=("Courier", 10), state="disabled",
                                      bg="#fafaf8", relief="flat", bd=0,
                                      fg="#444441", wrap="word")
        self._sections_text.pack(fill="x", padx=6, pady=4)

        # ── Statistiche ──────────────────────────────────────
        stats_row = tk.Frame(self, bg="#f5f5f3")
        stats_row.pack(fill="x", padx=16, pady=4)
        for col in range(3):
            stats_row.columnconfigure(col, weight=1)

        self._stat_ok  = self._make_stat_card(stats_row, "0", "Scaricati",  "#1D9E75", 0)
        self._stat_err = self._make_stat_card(stats_row, "0", "Errori",     "#D85A30", 1)
        self._stat_rem = self._make_stat_card(stats_row, "0", "Rimasti",    "#888780", 2)

        # ── Barra progresso ──────────────────────────────────
        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ttk.Progressbar(self, variable=self._progress_var,
                                             maximum=100, mode="determinate")
        self._progress_bar.pack(fill="x", padx=16, pady=4)
        self._progress_label = tk.Label(self, text="", font=("Helvetica", 10),
                                        bg="#f5f5f3", fg="#6b6b67")
        self._progress_label.pack(anchor="w", padx=16)

        # ── Log ──────────────────────────────────────────────
        log_frame = tk.LabelFrame(self, text="Log",
                                  font=("Helvetica", 11),
                                  bg="#f5f5f3", fg="#444441",
                                  relief="solid", bd=1)
        log_frame.pack(fill="both", expand=True, padx=16, pady=4)

        self._log_text = tk.Text(log_frame, font=("Courier", 10), state="disabled",
                                 bg="#fafaf8", fg="#444441", relief="flat", bd=0,
                                 wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True, padx=6, pady=4)

        # Tag colori del log
        self._log_text.tag_config("ok",      foreground="#1D9E75")
        self._log_text.tag_config("err",     foreground="#D85A30")
        self._log_text.tag_config("warn",    foreground="#BA7517")
        self._log_text.tag_config("skip",    foreground="#888780")
        self._log_text.tag_config("info",    foreground="#444441")
        self._log_text.tag_config("section", foreground="#1a1a18", font=("Courier", 10, "bold"))

        # ── Pulsanti azione ──────────────────────────────────
        btn_row = tk.Frame(self, bg="#f5f5f3")
        btn_row.pack(fill="x", padx=16, pady=(4, 16))
        for col in range(3):
            btn_row.columnconfigure(col, weight=1)

        self._start_btn  = tk.Button(btn_row, text="▶  Avvia download",
                                     font=("Helvetica", 11, "bold"),
                                     bg="#1D9E75", fg="white", activebackground="#0F6E56",
                                     relief="flat", pady=8, cursor="hand2",
                                     command=self._start_download)
        self._start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._pause_btn  = tk.Button(btn_row, text="⏸  Ferma",
                                     font=("Helvetica", 11),
                                     bg="white", relief="solid", bd=1,
                                     pady=8, cursor="hand2",
                                     command=self._stop_download)
        self._pause_btn.grid(row=0, column=1, sticky="ew", padx=4)

        self._open_btn   = tk.Button(btn_row, text="📂  Apri cartella",
                                     font=("Helvetica", 11),
                                     bg="white", relief="solid", bd=1,
                                     pady=8, cursor="hand2",
                                     command=self._open_folder)
        self._open_btn.grid(row=0, column=2, sticky="ew", padx=(4, 0))

    def _make_label(self, parent, text):
        tk.Label(parent, text=text, font=("Helvetica", 10),
                 bg="#f5f5f3", fg="#6b6b67").pack(anchor="w", pady=(4, 2))

    def _make_stat_card(self, parent, value, label, color, col):
        card = tk.Frame(parent, bg="white", relief="solid", bd=1)
        card.grid(row=0, column=col, sticky="ew", padx=4, pady=4)
        val_lbl = tk.Label(card, text=value, font=("Helvetica", 22, "bold"),
                           bg="white", fg=color)
        val_lbl.pack(pady=(8, 0))
        tk.Label(card, text=label, font=("Helvetica", 10),
                 bg="white", fg="#888780").pack(pady=(0, 8))
        return val_lbl

    # ── Controllo visibilità cookie ──────────────────────────

    def _toggle_cookie_visibility(self):
        current = self._cookie_entry.cget("show")
        self._cookie_entry.config(show="" if current == "•" else "•")

    # ── Sfoglia cartella ─────────────────────────────────────

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Scegli la cartella di destinazione")
        if folder:
            self._dest_var.set(folder)

    # ── Analizza corso ───────────────────────────────────────

    def _analyze(self):
        cookie = self._cookie_var.get().strip()
        url    = self._url_var.get().strip()
        if not cookie or not url:
            messagebox.showwarning("Campi mancanti", "Inserisci cookie e URL del corso.")
            return
        self._set_state("analyzing")
        threading.Thread(target=self._analyze_thread, args=(cookie, url), daemon=True).start()

    def _analyze_thread(self, cookie, url):
        try:
            session = build_session(cookie)
            sections = parse_course(session, url)
            self._sections = sections
            total = sum(len(s["items"]) for s in sections)
            self._total_files = total
            self.after(0, self._on_analyze_done, sections, total)
        except Exception as e:
            self.after(0, self._on_analyze_error, str(e))

    def _on_analyze_done(self, sections, total):
        self._sections_text.config(state="normal")
        self._sections_text.delete("1.0", "end")
        for s in sections:
            count = len(s["items"])
            self._sections_text.insert("end", f"📂  {s['title']}  ({count} risorse)\n")
        self._sections_text.config(state="disabled")
        self._cookie_status.config(text="✓ Valido", fg="#1D9E75")
        self._update_stats(0, 0, total)
        self._set_state("ready")
        self._log(f"Trovate {len(sections)} sezioni, {total} risorse totali.", "ok")

    def _on_analyze_error(self, err):
        self._cookie_status.config(text="✗ Errore", fg="#D85A30")
        messagebox.showerror("Errore analisi", err)
        self._set_state("idle")

    # ── Download ─────────────────────────────────────────────

    def _start_download(self):
        if not self._sections:
            messagebox.showwarning("Analisi mancante", "Prima clicca 'Analizza corso'.")
            return
        dest = self._dest_var.get().strip()
        if not dest:
            messagebox.showwarning("Cartella mancante", "Scegli una cartella di destinazione.")
            return
        cookie = self._cookie_var.get().strip()
        self._stop_event.clear()
        self._done_files = 0
        self._err_files  = 0
        self._set_state("downloading")
        self._thread = threading.Thread(
            target=self._download_thread,
            args=(cookie, self._sections, Path(dest)),
            daemon=True
        )
        self._thread.start()

    def _download_thread(self, cookie, sections, base_path):
        session = build_session(cookie)
        base_path.mkdir(parents=True, exist_ok=True)
        for section in sections:
            if self._stop_event.is_set():
                break
            folder_name = sanitize(section["title"])
            folder_path = base_path / folder_name
            folder_path.mkdir(parents=True, exist_ok=True)
            self.after(0, self._log, f"\n📂  {section['title']}", "section")
            for item in section["items"]:
                if self._stop_event.is_set():
                    break
                name = item["name"]
                url  = item["url"]
                kind = item["type"]
                if kind == "file":
                    self.after(0, self._log, f"  ↓  {name}", "info")
                    ok = download_file(session, url, folder_path, name,
                                       lambda m, t: self.after(0, self._log, m, t),
                                       self._stop_event)
                    if ok:
                        self._done_files += 1
                    else:
                        self._err_files += 1
                    time.sleep(1.5)
                elif kind == "folder":
                    download_folder(session, url, folder_path, name,
                                    lambda m, t: self.after(0, self._log, m, t),
                                    self._stop_event)
                    self._done_files += 1
                    time.sleep(1.5)
                elif kind == "url":
                    save_url_shortcut(session, url, folder_path, name,
                                      lambda m, t: self.after(0, self._log, m, t))
                    self._done_files += 1
                elif kind == "forum":
                    self.after(0, self._log, f"  💬  Forum ignorato: {name}", "skip")
                remaining = self._total_files - self._done_files - self._err_files
                self.after(0, self._update_stats, self._done_files, self._err_files, remaining)
                pct = (self._done_files + self._err_files) / max(self._total_files, 1) * 100
                self.after(0, self._update_progress, pct)
        self.after(0, self._on_download_done)

    def _on_download_done(self):
        self._set_state("done")
        self._log(f"\n✓  Download completato — {self._done_files} file scaricati, {self._err_files} errori.", "ok")
        messagebox.showinfo("Completato",
                            f"Download completato!\n\n"
                            f"✓  Scaricati:  {self._done_files}\n"
                            f"✗  Errori:     {self._err_files}\n\n"
                            f"Cartella: {self._dest_var.get()}")

    def _stop_download(self):
        self._stop_event.set()
        self._log("\n⏸  Download interrotto dall'utente.", "warn")
        self._set_state("ready")

    def _open_folder(self):
        dest = self._dest_var.get().strip()
        if not dest:
            return
        Path(dest).mkdir(parents=True, exist_ok=True)
        import subprocess, platform
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", dest])
        elif system == "Windows":
            os.startfile(dest)
        else:
            subprocess.run(["xdg-open", dest])

    # ── Helpers UI ───────────────────────────────────────────

    def _log(self, message, tag="info"):
        self._log_text.config(state="normal")
        self._log_text.insert("end", message + "\n", tag)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _update_stats(self, ok, err, rem):
        self._stat_ok.config(text=str(ok))
        self._stat_err.config(text=str(err))
        self._stat_rem.config(text=str(rem))

    def _update_progress(self, pct):
        self._progress_var.set(pct)
        self._progress_label.config(text=f"{pct:.0f}%  ({self._done_files + self._err_files} / {self._total_files})")

    def _set_state(self, state):
        """Aggiorna lo stato dei pulsanti in base alla fase."""
        if state == "idle":
            self._analyze_btn.config(state="normal", text="🔍  Analizza corso", bg="#378ADD")
            self._start_btn.config(state="disabled")
            self._pause_btn.config(state="disabled")
        elif state == "analyzing":
            self._analyze_btn.config(state="disabled", text="Analisi in corso…", bg="#888780")
            self._start_btn.config(state="disabled")
            self._pause_btn.config(state="disabled")
        elif state == "ready":
            self._analyze_btn.config(state="normal", text="🔍  Ri-analizza", bg="#378ADD")
            self._start_btn.config(state="normal")
            self._pause_btn.config(state="disabled")
        elif state == "downloading":
            self._analyze_btn.config(state="disabled", bg="#888780")
            self._start_btn.config(state="disabled")
            self._pause_btn.config(state="normal")
        elif state == "done":
            self._analyze_btn.config(state="normal", bg="#378ADD")
            self._start_btn.config(state="normal")
            self._pause_btn.config(state="disabled")


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
