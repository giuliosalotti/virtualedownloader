#!/usr/bin/env python3
"""
Virtuale UniBO — Downloader Universale
Funziona con qualsiasi corso su virtuale.unibo.it

REQUISITI:
    pip install requests beautifulsoup4

UTILIZZO:
    1. Fai login su virtuale.unibo.it nel browser
    2. Apri DevTools (F12) → Application → Cookies → virtuale.unibo.it
    3. Copia il valore del cookie "MoodleSession"
    4. Imposta MOODLE_SESSION e COURSE_URL qui sotto
    5. Esegui: python virtuale_downloader_universale.py
"""

import os
import re
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote

# ─────────────────────────────────────────────
#  CONFIGURAZIONE — MODIFICA QUI
# ─────────────────────────────────────────────

MOODLE_SESSION = "INCOLLA_QUI_IL_TUO_MOODLESESSION"

# URL della pagina principale del corso (quella con tutte le sezioni)
# Esempio: https://virtuale.unibo.it/course/view.php?id=69060
COURSE_URL = "INCOLLA_QUI_L_URL_DEL_CORSO"

# Cartella di destinazione (viene creata automaticamente)
OUTPUT_DIR = "./Virtuale_Download"

# Pausa tra un download e l'altro in secondi (non abbassare troppo)
DELAY_SECONDS = 1.5

# ─────────────────────────────────────────────


def sanitize(name: str, max_len: int = 80) -> str:
    """Rimuove caratteri non validi per nomi di file e cartelle."""
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip(' .-')
    return name[:max_len] or "senza_nome"


def build_session(moodle_session: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("MoodleSession", moodle_session, domain="virtuale.unibo.it")
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniBO-Downloader/2.0)"})
    return s


def filename_from_response(resp: requests.Response, fallback: str) -> str:
    """Estrae il nome file dall'header Content-Disposition."""
    cd = resp.headers.get("Content-Disposition", "")
    # RFC 5987 (UTF-8)
    m = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1)).strip()
    # Classico filename=
    m = re.search(r'filename="?([^";\r\n]+)"?', cd)
    if m:
        return m.group(1).strip()
    return fallback


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


def download_file(session: requests.Session, url: str, dest_folder: Path, name_hint: str) -> bool:
    """
    Segue i redirect Moodle (view.php → pluginfile.php) e salva il file.
    """
    try:
        resp = session.get(url, allow_redirects=True, timeout=30)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")

        # Moodle spesso mostra una pagina HTML intermedia con il link reale
        if "text/html" in ct:
            soup = BeautifulSoup(resp.text, "html.parser")
            link = soup.find("a", href=re.compile(r"pluginfile\.php"))
            if link:
                resp = session.get(link["href"], allow_redirects=True, timeout=60)
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "")
            else:
                print(f"    ⚠️  Nessun file trovato per: {name_hint}")
                return False

        ct_base     = ct.split(";")[0].strip()
        fallback_ext = EXT_MAP.get(ct_base, ".bin")
        raw_name    = filename_from_response(resp, sanitize(name_hint) + fallback_ext)
        filename    = sanitize(raw_name)
        if not Path(filename).suffix:
            filename += fallback_ext

        dest = dest_folder / filename
        if dest.exists():
            print(f"    ⏭️  Già presente: {filename}")
            return True

        with open(dest, "wb") as f:
            f.write(resp.content)

        print(f"    ✅  {filename}  ({len(resp.content)/1024:.0f} KB)")
        return True

    except requests.RequestException as e:
        print(f"    ❌  Errore: {e}")
        return False


def download_moodle_folder(session: requests.Session, folder_url: str,
                           dest_folder: Path, folder_name: str):
    """Scarica il contenuto di una Cartella Moodle (mod/folder)."""
    sub = dest_folder / sanitize(folder_name)
    sub.mkdir(parents=True, exist_ok=True)
    print(f"  📁  Cartella: {folder_name}")

    try:
        resp = session.get(folder_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"pluginfile\.php"))

        if not links:
            print("    ⚠️  Cartella vuota o accesso negato")
            return

        for a in links:
            file_url  = a["href"]
            file_name = a.get_text(strip=True) or Path(urlparse(file_url).path).name
            print(f"    ↳  {file_name}")
            download_file(session, file_url, sub, file_name)
            time.sleep(DELAY_SECONDS)

    except requests.RequestException as e:
        print(f"    ❌  Errore cartella: {e}")


def save_url_shortcut(session: requests.Session, url_page: str,
                      dest_folder: Path, name: str):
    """
    Risolve il link esterno di un modulo URL e lo salva come file .url
    apribile su Windows, macOS e Linux.
    """
    try:
        resp = session.get(url_page, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Moodle mostra il link esterno in un <div class="urlworkaround"> o simili
        ext = (
            soup.find("a", href=re.compile(r"^https?://(?!virtuale\.unibo\.it)")) or
            soup.find("a", class_=re.compile(r"btn"))
        )
        external_url = ext["href"] if ext else url_page

        fname = dest_folder / (sanitize(name) + ".url")
        with open(fname, "w", encoding="utf-8") as f:
            f.write("[InternetShortcut]\n")
            f.write(f"URL={external_url}\n")

        print(f"    🔗  Link: {external_url}")

    except Exception as e:
        print(f"    ❌  Errore link '{name}': {e}")


# ─────────────────────────────────────────────
#  PARSING DELLA PAGINA DEL CORSO
# ─────────────────────────────────────────────

def parse_course(session: requests.Session, course_url: str) -> list[dict]:
    """
    Scarica la pagina del corso e restituisce la lista delle sezioni
    con i relativi materiali.
    """
    print(f"🌐  Scarico la pagina del corso...")
    resp = session.get(course_url, timeout=30)
    resp.raise_for_status()

    # Controlla se siamo stati reindirizzati al login
    if "login" in resp.url:
        raise ValueError("❌  Sessione scaduta o non valida. Rinnova il cookie MoodleSession.")

    soup    = BeautifulSoup(resp.text, "html.parser")
    sections = soup.find_all("li", class_=lambda c: c and "section" in c.split())

    result = []
    for i, sec in enumerate(sections):
        # Titolo sezione
        title_el = (
            sec.find("h3") or
            sec.find("h2") or
            sec.find(class_="sectionname") or
            sec.find(class_="section-title")
        )
        raw_title = title_el.get_text(strip=True) if title_el else f"Sezione {i}"
        title     = f"{i:02d} - {raw_title}"

        items = []
        for activity in sec.find_all("li", class_=lambda c: c and "activity" in c.split()):
            a = activity.find("a", href=True)
            if not a:
                continue

            classes = " ".join(activity.get("class", []))
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

            # Pulisce il nome rimuovendo suffissi Moodle visibili
            name = a.get_text(strip=True)
            for suffix in ("File", "Cartella", "URL", "Forum", "Compito", "Pagina", "Risorsa"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)].strip()

            items.append({"name": name, "url": a["href"], "type": kind})

        result.append({"title": title, "items": items})

    print(f"   → {len(result)} sezioni trovate, {sum(len(s['items']) for s in result)} risorse totali\n")
    return result


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    # Validazioni iniziali
    if MOODLE_SESSION == "INCOLLA_QUI_IL_TUO_MOODLESESSION":
        print("❗  Imposta la variabile MOODLE_SESSION nel file.")
        return
    if COURSE_URL == "INCOLLA_QUI_L_URL_DEL_CORSO":
        print("❗  Imposta la variabile COURSE_URL nel file.")
        return

    session   = build_session(MOODLE_SESSION)
    base_path = Path(OUTPUT_DIR)
    base_path.mkdir(parents=True, exist_ok=True)

    # Estrai nome corso dall'URL per la cartella
    course_id = re.search(r"id=(\d+)", COURSE_URL)
    course_id = course_id.group(1) if course_id else "corso"

    try:
        sections = parse_course(session, COURSE_URL)
    except ValueError as e:
        print(e)
        return
    except requests.RequestException as e:
        print(f"❌  Impossibile connettersi a Virtuale: {e}")
        return

    print(f"📚  Inizio download → {base_path.resolve()}")
    print("=" * 60)

    ok = err = 0

    for section in sections:
        folder_name = sanitize(section["title"])
        folder_path = base_path / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)

        print(f"\n📂  {section['title']}")

        if not section["items"]:
            print("    (sezione vuota)")
            continue

        for item in section["items"]:
            name = item["name"]
            url  = item["url"]
            kind = item["type"]

            if kind == "file":
                print(f"  ↓  {name}")
                if download_file(session, url, folder_path, name):
                    ok += 1
                else:
                    err += 1
                time.sleep(DELAY_SECONDS)

            elif kind == "folder":
                download_moodle_folder(session, url, folder_path, name)
                time.sleep(DELAY_SECONDS)

            elif kind == "url":
                print(f"  🔗  {name}")
                save_url_shortcut(session, url, folder_path, name)
                time.sleep(DELAY_SECONDS * 0.5)

            elif kind == "forum":
                print(f"  💬  Forum (ignorato): {name}")

            else:
                print(f"  ❓  Tipo sconosciuto '{kind}': {name}")

    print("\n" + "=" * 60)
    print(f"✅  Scaricati:  {ok}")
    print(f"❌  Errori:     {err}")
    print(f"📁  Cartella:   {base_path.resolve()}")
    print()


if __name__ == "__main__":
    main()
