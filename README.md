# Virtuale UniBO Downloader

📚 Web app to bulk-download course materials from [virtuale.unibo.it](https://virtuale.unibo.it) — paste your MoodleSession cookie, select the resources you need, and download everything as a ZIP.

---

## Features

### Core
- **Course analysis** — parses any course page and lists all sections and resources
- **Selective download** — check/uncheck individual files or entire sections before downloading
- **Supported resource types**: files (PDF, PPTX, XLSX, DOCX, MP4, …), Moodle folders, external URL shortcuts
- **Real-time progress** — live log and progress bar via Server-Sent Events
- **One-click ZIP** — all downloaded files are packaged into a single archive, organised by section

### Selection & Navigation
- **File type icons** — each resource shows the Moodle activity icon (or an emoji fallback); works in both light and dark mode
- **Hover preview card** — hover a resource for ~650 ms to see a floating detail card (type, section, URL)
- **Text search** — filter resources across all sections by name in real time
- **Open in new tab** — open any resource directly in the browser without downloading

### Section Management
- **Drag & drop ordering** — reorder sections before downloading; the folder numbers update automatically to match the new order
- **Reset order** — one-click button to restore the original section order
- **Section cards** — each section is displayed as a distinct card with a tinted header for clear visual separation

### Download & History
- **Auto-download ZIP** — the ZIP is saved automatically as soon as the download completes (toggle-able)
- **Download history** — the last 8 downloads are stored in `localStorage` and shown in the UI
- **Desktop notifications** — opt-in browser notification when the download finishes (Web Notifications API)

### Folder Comparison
- **Compare with local folder** — pick a previously extracted course folder to compare it against the current Moodle content:
  - Files already present are highlighted in green with a ✓ badge
  - New resources are counted and highlighted
  - **"Select only new"** button deselects everything already downloaded so you only re-download what changed
  - Works for files, Moodle folder resources, and URL shortcuts (`.url` files)

---

## Requirements

- Python **3.10+**
- Dependencies listed in `requirements.txt` (`requests`, `beautifulsoup4`, `flask`)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/virtualeDownloader.git
cd virtualeDownloader

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

# 4. Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Start the server

```bash
python app.py
# → http://localhost:5001
```

Open your browser at `http://localhost:5001`.

---

### Step 1 — Get your MoodleSession cookie

1. Log in to [virtuale.unibo.it](https://virtuale.unibo.it) in your browser
2. Open DevTools with `F12`
3. Go to **Application → Cookies → virtuale.unibo.it** (Chrome / Edge) or **Storage → Cookies** (Firefox)
4. Copy the value of the **`MoodleSession`** cookie

> ⚠️ The cookie expires after a few hours of inactivity. If you get a "session expired" error, repeat this step.

### Step 2 — Analyse the course

Paste the cookie and the course URL (e.g. `https://virtuale.unibo.it/course/view.php?id=12345`), then click **Analyse course**. The app will fetch all sections and resources.

### Step 3 — Select and download

- Use the checkboxes to select resources (individual items or entire sections)
- **Drag** the grip handle on the left of each section header to reorder sections
- Use the **search bar** to filter resources by name
- Click **📂 Compare folder** to detect what you have already downloaded
- Click **Download selected** to start

### Step 4 — Save the ZIP

When the download is complete, click **Download ZIP** to save the archive (or let it save automatically if auto-download is enabled). Files are organised in folders named after each course section.

---

## Build a standalone macOS app

You can create a self-contained **`.app`** bundle with PyInstaller — no Python installation required on the target machine.

```bash
# Inside the virtualenv
./build_macos.sh
```

This produces `dist/VirtualeDownloader.app`. Double-click it or run:

```bash
open dist/VirtualeDownloader.app
```

The app will find a free port automatically and open your default browser.

> **First launch on macOS:** if Gatekeeper blocks the app (unsigned binary), right-click → **Open** → **Open** to bypass the warning.

### Folder comparison — browser support

The **Compare folder** feature uses the [File System Access API](https://developer.mozilla.org/en-US/docs/Web/API/File_System_Access_API) (`showDirectoryPicker`), which is currently supported only in **Chrome and Edge**. Firefox and Safari will show an unsupported notice.

---

## Output structure

```
virtuale_download.zip
├── 00 - Introduction/
├── 01 - Course outline/
├── 02 - Study material/
│   ├── Lecture 1.pdf
│   ├── Lecture 2.pptx
│   └── Readings/           ← Moodle folder resource
│       ├── paper1.pdf
│       └── paper2.pdf
└── 03 - Case studies/
    └── Case 1 dataset.xlsx
```

---

## Project structure

| File | Description |
|---|---|
| `app.py` | Flask backend — API routes and download logic |
| `templates/index.html` | Frontend UI (Tailwind-inspired CSS + vanilla JS) |
| `launcher.py` | Entry point for the PyInstaller bundle — finds a free port and opens the browser |
| `VirtualeDownloader.spec` | PyInstaller spec to build the macOS `.app` |
| `build_macos.sh` | One-command build script for the standalone app |
| `virtuale_downloader.py` | Original CLI version |
| `requirements.txt` | Python runtime dependencies |

---

## Security notes

- The `MoodleSession` cookie is equivalent to a **temporary password** — do not share it or commit it to a public repository.
- The server adds a short delay between requests to avoid overloading UniBO's servers.
- The app is intended for **personal, local use only**. Do not expose it to the public internet.

---

## Troubleshooting

**"Session expired or invalid"** → refresh the `MoodleSession` cookie from your browser.

**"No file found for resource"** → some resources may require course enrolment or have restricted access.

**Cookie not accepted** → copy only the cookie *value*, not the name (`MoodleSession=abc123` is wrong — copy only `abc123`).

**Port already in use** → change the port in `app.py` (default: `5001`) or use the `PORT` environment variable: `PORT=5050 python app.py`.

**Build fails with PyInstaller** → make sure you are running the build script from inside the activated virtual environment (`source venv/bin/activate`).

**"Select only new" deselects everything** → make sure you selected the root of the previously extracted ZIP folder (the one that contains the `00 - …`, `01 - …` section folders), not a parent directory.
