# Virtuale UniBO Downloader

📚 Web app to bulk-download course materials from [virtuale.unibo.it](https://virtuale.unibo.it) — paste your MoodleSession cookie, select the resources you need, and download everything as a ZIP.

---

## Features

- **Course analysis** — parses any course page and lists all sections and resources
- **Selective download** — check/uncheck individual files or entire sections before downloading
- **Supported resource types**: files (PDF, PPTX, XLSX, DOCX, MP4, …), Moodle folders, external URL shortcuts
- **Real-time progress** — live log and progress bar via Server-Sent Events
- **One-click ZIP** — all downloaded files are packaged into a single archive, organized by section
- Skips already-downloaded files to allow resuming interrupted sessions

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

### Step 2 — Analyze the course

Paste the cookie and the course URL (e.g. `https://virtuale.unibo.it/course/view.php?id=12345`), then click **Analyze course**. The app will fetch all sections and resources.

### Step 3 — Select and download

Use the checkboxes to select the resources you want. You can select/deselect entire sections or individual files. Click **Download selected** to start. A live log and progress bar will appear.

### Step 4 — Save the ZIP

When the download is complete, click **Download ZIP** to save the archive to your machine. Files are organized in folders named after each course section.

---

## Output structure

```
virtuale_download.zip
├── 00 - Introduction/
├── 01 - Course outline/
├── 02 - Study material/
│   ├── Lecture 1.pdf
│   ├── Lecture 2.pptx
│   └── Readings/           ← Moodle folder
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
| `templates/index.html` | Frontend UI (Tailwind CSS + vanilla JS) |
| `virtuale_downloader.py` | Original CLI version |
| `requirements.txt` | Python dependencies |

---

## Security notes

- The `MoodleSession` cookie is equivalent to a **temporary password** — do not share it or commit it to a public repository.
- The server adds a short delay between requests to avoid overloading UniBO's servers.
- The app is intended for **personal, local use only**. Do not expose it to the public internet.

---

## Troubleshooting

**"Session expired or invalid"** → refresh the `MoodleSession` cookie from your browser.

**"No file found for resource"** → some resources may require course enrollment or have restricted access.

**Cookie not accepted** → make sure to copy only the cookie *value*, not the name. (`MoodleSession=abc123` is wrong — copy only `abc123`).

**Port already in use** → change the port in `app.py` (default: `5001`) if it conflicts with another service.
