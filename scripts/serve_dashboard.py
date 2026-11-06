#!/usr/bin/env python3
"""
Simple local HTTP server to host and view the StockOS Web Dashboard.
Usage:
    .venv/bin/python scripts/serve_dashboard.py
"""

import http.server
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "reports/dashboard.html"
PORT = 8501


def main():
    if not HTML_PATH.exists():
        print("Dashboard not found, building first...")
        subprocess.run([sys.executable, str(ROOT / "scripts/build_dashboard.py")], check=True)

    os.chdir(ROOT / "reports")
    handler = http.server.SimpleHTTPRequestHandler

    for p in range(PORT, PORT + 20):
        try:
            with socketserver.TCPServer(("", p), handler) as httpd:
                url = f"http://localhost:{p}/dashboard.html"
                print(f"\n==================================================")
                print(f" StockOS QVE 視覺化儀表板已啟動！")
                print(f" 本地網址: {url}")
                print(f" (按 Ctrl+C 可停止服務器)")
                print(f"==================================================\n")
                webbrowser.open(url)
                httpd.serve_forever()
                break
        except OSError:
            continue


if __name__ == "__main__":
    main()
