#!/usr/bin/env python3
"""
Virtuale UniBO — Web Downloader
Flask backend: analizza il corso, scarica le risorse selezionate, restituisce uno ZIP.
"""

import io
import json
import queue
import re
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request, send_file

app = Flask(__name__)

# ── costanti ────────────────────────────────────────────────────

DELAY_SECONDS = 1.0

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

# ── utilità di base ──────────────────────────────────────────────

def sanitize(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip(' .-')
    return name[:max_len] or "senza_nome"


def build_session(moodle_session: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("MoodleSession", moodle_session, domain="virtuale.unibo.it")
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniBO-Downloader/2.0)"})
    return s


def filename_from_response(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1)).strip()
    m = re.search(r'filename="?([^";\r\n]+)"?', cd)
    if m:
        return m.group(1).strip()
    return fallback


# ── parsing del corso ────────────────────────────────────────────

def parse_course(moodle_session: str, course_url: str) -> dict:
    sess = build_session(moodle_session)
    resp = sess.get(course_url, timeout=30)
    resp.raise_for_status()

    if "login" in resp.url:
        raise ValueError("Sessione scaduta o non valida. Rinnova il cookie MoodleSession.")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Estrae il nome del corso dall'<h1> (più diretto), con fallback sul <title>
    h1 = soup.find("h1")
    if h1:
        course_name = h1.get_text(strip=True)
    else:
        title_tag = soup.find("title")
        if title_tag:
            # Formato Moodle: "Corso: Business Models | Virtuale" → "Business Models"
            raw = title_tag.get_text(strip=True)
            if ": " in raw:
                course_name = raw.split(": ", 1)[1].split(" | ")[0].strip()
            else:
                course_name = raw.split(" | ")[0].strip()
        else:
            course_name = "Corso"

    sections = soup.find_all("li", class_=lambda c: c and "section" in c.split())

    result = []
    for i, sec in enumerate(sections):
        title_el = (
            sec.find("h3") or sec.find("h2")
            or sec.find(class_="sectionname")
            or sec.find(class_="section-title")
        )
        raw_title = title_el.get_text(strip=True) if title_el else f"Sezione {i}"
        title = f"{i:02d} - {raw_title}"

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

            name = a.get_text(strip=True)
            for suffix in ("File", "Cartella", "URL", "Forum", "Compito", "Pagina", "Risorsa"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)].strip()

            items.append({"name": name, "url": a["href"], "type": kind})

        result.append({"title": title, "items": items})

    return {"sections": result, "course_name": course_name}


# ── logica di download ───────────────────────────────────────────

def download_file_to(sess: requests.Session, url: str, dest: Path, name_hint: str) -> str | None:
    try:
        resp = sess.get(url, allow_redirects=True, timeout=30)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")

        if "text/html" in ct:
            soup = BeautifulSoup(resp.text, "html.parser")
            link = soup.find("a", href=re.compile(r"pluginfile\.php"))
            if link:
                resp = sess.get(link["href"], allow_redirects=True, timeout=60)
                resp.raise_for_status()
                ct = resp.headers.get("Content-Type", "")
            else:
                return None

        ct_base = ct.split(";")[0].strip()
        fallback_ext = EXT_MAP.get(ct_base, ".bin")
        raw_name = filename_from_response(resp, sanitize(name_hint) + fallback_ext)
        filename = sanitize(raw_name)
        if not Path(filename).suffix:
            filename += fallback_ext

        dest_path = dest / filename
        if not dest_path.exists():
            with open(dest_path, "wb") as f:
                f.write(resp.content)

        return filename
    except Exception:
        return None


def download_folder_to(sess: requests.Session, folder_url: str, dest: Path, emit) -> int:
    count = 0
    try:
        resp = sess.get(folder_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"pluginfile\.php"))

        for a in links:
            file_url = a["href"]
            file_name = a.get_text(strip=True) or Path(urlparse(file_url).path).name
            result = download_file_to(sess, file_url, dest, file_name)
            if result:
                count += 1
                emit("file_ok", f"    ✅ {result}")
            else:
                emit("file_err", f"    ❌ Errore: {file_name}")
            time.sleep(DELAY_SECONDS)
    except Exception as e:
        emit("file_err", f"Errore cartella: {e}")
    return count


def save_url_shortcut_to(sess: requests.Session, url_page: str, dest: Path, name: str):
    try:
        resp = sess.get(url_page, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        ext = soup.find("a", href=re.compile(r"^https?://(?!virtuale\.unibo\.it)")) or soup.find(
            "a", class_=re.compile(r"btn")
        )
        external_url = ext["href"] if ext else url_page
        fname = dest / (sanitize(name) + ".url")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"[InternetShortcut]\nURL={external_url}\n")
    except Exception:
        pass


# ── sessioni di download in memoria ─────────────────────────────

_sessions: dict[str, dict] = {}


def do_download(session_id: str, moodle_session: str, items: list[dict]):
    data = _sessions[session_id]
    q: queue.Queue = data["queue"]

    def emit(type_: str, message: str, **kw):
        q.put({"type": type_, "message": message, **kw})

    try:
        sess = build_session(moodle_session)
        downloadable = [i for i in items if i["type"] in ("file", "folder", "url")]
        total = len(downloadable)
        ok = err = done_count = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            for item in downloadable:
                name = item["name"]
                url = item["url"]
                kind = item["type"]
                section = item.get("section", "Generale")

                sec_path = base / sanitize(section)
                sec_path.mkdir(parents=True, exist_ok=True)

                done_count += 1
                pct = int(done_count / total * 100) if total else 100

                if kind == "file":
                    emit("progress", f"↓  {name}", percent=pct)
                    result = download_file_to(sess, url, sec_path, name)
                    if result:
                        ok += 1
                        emit("file_ok", f"✅ {result}", percent=pct)
                    else:
                        err += 1
                        emit("file_err", f"❌ Non scaricato: {name}", percent=pct)

                elif kind == "folder":
                    emit("progress", f"📁 Cartella: {name}", percent=pct)
                    sub = sec_path / sanitize(name)
                    sub.mkdir(parents=True, exist_ok=True)
                    count = download_folder_to(sess, url, sub, emit)
                    ok += count

                elif kind == "url":
                    emit("progress", f"🔗 Link: {name}", percent=pct)
                    save_url_shortcut_to(sess, url, sec_path, name)
                    emit("file_ok", f"✅ {sanitize(name)}.url salvato", percent=pct)

                time.sleep(DELAY_SECONDS)

            emit("status", "Creazione archivio ZIP...", percent=99)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in base.rglob("*"):
                    if fp.is_file():
                        zf.write(fp, fp.relative_to(base))

            data["zip_data"] = buf.getvalue()

        emit(
            "done",
            f"Completato! {ok} file scaricati, {err} errori.",
            ok=ok,
            err=err,
            percent=100,
        )
    except Exception as e:
        emit("error", f"Errore: {e}")


# ── route Flask ──────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    body = request.get_json()
    try:
        result = parse_course(body["moodleSession"], body["courseUrl"])
        return jsonify({"ok": True, "sections": result["sections"], "courseName": result["course_name"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    body = request.get_json()
    sid = str(uuid.uuid4())
    zip_name = sanitize(body.get("courseName", "")) or "virtuale_download"
    _sessions[sid] = {"queue": queue.Queue(), "zip_data": None, "zip_name": zip_name}

    threading.Thread(
        target=do_download,
        args=(sid, body["moodleSession"], body["items"]),
        daemon=True,
    ).start()

    return jsonify({"sessionId": sid})


@app.route("/api/progress/<sid>")
def progress_stream(sid):
    def generate():
        if sid not in _sessions:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Sessione non trovata'})}\n\n"
            return
        q = _sessions[sid]["queue"]
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg["type"] in ("done", "error"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/zip/<sid>")
def get_zip(sid):
    session = _sessions.get(sid, {})
    zip_data = session.get("zip_data")
    if not zip_data:
        return "Non disponibile", 404
    zip_name = session.get("zip_name", "virtuale_download") + ".zip"
    return send_file(
        io.BytesIO(zip_data),
        as_attachment=True,
        download_name=zip_name,
        mimetype="application/zip",
    )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
