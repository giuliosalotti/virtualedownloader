# Virtuale UniBO — Downloader

App desktop per scaricare automaticamente i materiali di qualsiasi corso su [virtuale.unibo.it](https://virtuale.unibo.it), organizzati in cartelle per sezione.

---

## Funzionalità

- Analizza la pagina di qualsiasi corso su Virtuale in tempo reale
- Scarica tutti i file (PDF, PPTX, XLSX, DOCX, MP3, ZIP…)
- Entra nelle **Cartelle** Moodle e ne scarica il contenuto
- Salva i **link URL** come file `.url` apribili con un doppio click
- Organizza tutto in **cartelle numerate** per sezione
- Salta i file già scaricati (riprendibile in caso di interruzione)
- Interfaccia grafica con barra di progresso e log in tempo reale

---

## Requisiti

- Python **3.10** o superiore
- Le librerie elencate in `requirements.txt` (tkinter è già incluso in Python)

---

## Installazione

```bash
# 1. Clona o scarica il progetto nella tua cartella
cd virtuale-downloader

# 2. Crea un ambiente virtuale
python -m venv venv

# 3. Attivalo
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

# 4. Installa le dipendenze
pip install -r requirements.txt
```

---

## Avvio

```bash
python virtuale_gui.py
```

---

## Come si usa

### 1 — Recupera il cookie di sessione

1. Fai login su [virtuale.unibo.it](https://virtuale.unibo.it) nel browser
2. Apri i DevTools con `F12`
3. Vai su **Application → Cookies → virtuale.unibo.it** (Chrome/Edge) oppure **Storage → Cookies** (Firefox)
4. Copia il valore del cookie **`MoodleSession`**

> ⚠️ Il cookie scade dopo qualche ora di inattività. Se il download si interrompe con un errore di sessione, ripeti questo passaggio.

### 2 — Compila i campi nell'app

| Campo | Esempio |
|---|---|
| Cookie MoodleSession | `d4f8a1b2c3e9f012...` |
| URL del corso | `https://virtuale.unibo.it/course/view.php?id=69060` |
| Cartella di destinazione | `/Users/giulio/Desktop/BPA_Course` |

### 3 — Analizza e scarica

1. Clicca **Analizza corso** → l'app mostra le sezioni trovate e verifica il cookie
2. Clicca **Avvia download** → parte il download con log e barra di progresso
3. Al termine clicca **Apri cartella** per vedere i file scaricati

---

## Struttura delle cartelle generate

```
BPA_Course/
├── 00 - Introduzione/
├── 01 - Course outline - Riccardo Silvi/
├── 02 - Study material/
│   ├── Reading 1 - Business performance analytics.pdf
│   ├── Reading 2 - Business Performance Analytics.pdf
│   └── ...
├── 03 - Quizzes, Exercises with Solutions/
├── 04 - Case studies (assignments)/
│   └── Deli case/          ← sottocartella da Cartella Moodle
│       ├── file1.pdf
│       └── file2.xlsx
└── ...
```

---

## File del progetto

| File | Descrizione |
|---|---|
| `virtuale_gui.py` | Interfaccia grafica (avvia questo) |
| `virtuale_downloader_universale.py` | Versione CLI senza interfaccia |
| `requirements.txt` | Dipendenze Python |
| `README.md` | Questo file |

---

## Note di sicurezza

- Il cookie MoodleSession è equivalente a una **password temporanea**: non condividerlo e non caricarlo su repository pubblici
- Aggiungi `.env` e file di configurazione al tuo `.gitignore` se versionii il progetto con Git
- Lo script rispetta un ritardo di 1.5 secondi tra un download e l'altro per non sovraccaricare i server UniBO

---

## Problemi comuni

**"Sessione scaduta o non valida"** → rinnova il cookie MoodleSession dal browser.

**"Nessun file trovato"** → alcune risorse potrebbero richiedere iscrizione al corso o avere accesso limitato.

**Il cookie non viene accettato** → assicurati di copiare solo il valore del cookie, non il nome (`MoodleSession=...` è sbagliato, copia solo la parte dopo `=`).

**Tkinter non trovato su Linux** → installa con `sudo apt install python3-tk`.
