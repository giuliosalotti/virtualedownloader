#!/usr/bin/env python3
"""
Virtuale Downloader — entry point per il bundle PyInstaller / macOS .app

Trova un port libero, apre il browser in automatico e avvia Flask.
"""

import socket
import sys
import threading
import time
import webbrowser

from app import app


def _find_free_port(start: int = 5001, end: int = 5020) -> int:
    """Restituisce il primo port disponibile nell'intervallo."""
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return start  # fallback


def _open_browser(port: int) -> None:
    time.sleep(1.4)
    webbrowser.open(f'http://127.0.0.1:{port}')


if __name__ == '__main__':
    port = _find_free_port()

    threading.Thread(target=_open_browser, args=(port,), daemon=True).start()

    app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
