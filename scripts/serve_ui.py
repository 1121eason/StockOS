#!/usr/bin/env python3
"""Local-only StockOS UI. No database, credentials, provider, or write integration."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from valuation_engine.research.dcf import DCFModel  # noqa: E402
from valuation_engine.research.numbers import MarketEquityShares, canonical  # noqa: E402

ASSETS = {
    "/": "index.html",
    "/app.js": "app.js",
    "/domain.mjs": "domain.mjs",
    "/styles.css": "styles.css",
    "/favicon.svg": "favicon.svg",
}
FIELDS = {
    "wacc": (Decimal("0.1"), Decimal(50)),
    "terminal_growth": (Decimal(-20), Decimal(20)),
    "growth": (Decimal(-50), Decimal(100)),
    "cash": (Decimal(0), Decimal("1e9")),
    "debt": (Decimal(0), Decimal("1e9")),
    "shares": (Decimal("0.000001"), Decimal("1e9")),
}


def fixture() -> dict[str, Any]:
    return json.loads((ROOT / "ui/fixtures/demo.json").read_text(encoding="utf-8"))


def numbers(values: dict[str, Any]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for field, (low, high) in FIELDS.items():
        raw = values.get(field)
        if raw is None or isinstance(raw, bool) or not str(raw).strip():
            raise ValueError(f"{field}: 必須填寫數值，缺值不會當作 0")
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field}: 請填寫有效數值") from exc
        if not value.is_finite() or not low <= value <= high:
            raise ValueError(f"{field}: 數值須介於 {low} 與 {high}")
        result[field] = value
    if result["wacc"] <= result["terminal_growth"]:
        raise ValueError("WACC 必須大於終端成長率")
    return result


def calculate(company: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    params = numbers(values)
    if not company["cashflows"]:
        return {"status": "unavailable", "reason": "缺少完整五年現金流，無法估值"}
    flows = [
        Decimal(str(flow)) * (1 + params["growth"] / 100) ** year
        for year, flow in enumerate(company["cashflows"], 1)
    ]

    def model(wacc: Decimal) -> dict[str, Any]:
        return DCFModel().value(
            flows,
            params["cash"],
            params["debt"],
            MarketEquityShares(params["shares"]),
            wacc / 100,
            params["terminal_growth"] / 100,
        )

    base = model(params["wacc"])
    # Range is a WACC sensitivity, never a probability or confidence interval.
    scenarios = [
        {"label": label, "wacc_pct": rate, **model(rate)}
        for label, rate in (
            ("較高折現率", params["wacc"] + 1),
            ("基準", params["wacc"]),
            ("較低折現率", params["wacc"] - 1),
        )
    ]
    return canonical(
        {**base, "cashflows": flows, "scenarios": scenarios, "parameters": params,
         "mode": "demo", "method": "DCFPolicyV1 · synthetic FCFF inputs"}
    )


def workspace(company_id: str) -> dict[str, Any]:
    data = fixture()
    company = next((c for c in data["companies"] if c["id"] == company_id), None)
    if company is None:
        raise ValueError("找不到公司，請重新選擇")
    result = (
        calculate(company, company) if company["cashflows"]
        else {"status": "unavailable", "reason": "尚無研究資料；現金流、現金、負債與股數皆缺值"}
    )
    return {**data, "company": company, "valuation": result,
            "served_at": datetime.now(UTC).isoformat(), "backend_baseline": "cbb78db"}


class Handler(BaseHTTPRequestHandler):
    server_version = "StockOSLocal/1"

    def send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def json(self, status: int, value: Any) -> None:
        self.send(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(),
                  "application/json; charset=utf-8")

    def local_request(self) -> bool:
        port = self.port()
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def port(self) -> int:
        address = self.server.server_address
        assert isinstance(address, tuple)
        return int(address[1])

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self.local_request():
            self.json(403, {"error": "僅接受 localhost 請求"})
            return
        url = urlsplit(self.path)
        if url.path in ASSETS:
            path = ROOT / "ui" / ASSETS[url.path]
            mime = mimetypes.guess_type(path)[0] or "text/javascript"
            if path.suffix == ".mjs":
                mime = "text/javascript"
            self.send(200, path.read_bytes(), mime + "; charset=utf-8")
        elif url.path == "/api/health":
            self.json(200, {"status": "ok", "mode": "demo", "database_connected": False,
                            "provider_calls": False, "backend_baseline": "cbb78db"})
        elif url.path == "/api/workspace":
            try:
                self.json(200, workspace(parse_qs(url.query).get("company", ["aurora"])[0]))
            except ValueError as exc:
                self.json(404, {"error": str(exc)})
        else:
            self.json(404, {"error": "找不到頁面"})

    def do_POST(self) -> None:
        if not self.local_request():
            self.json(403, {"error": "僅接受 localhost 請求"})
            return
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{self.port()}",
                                     f"http://localhost:{self.port()}"):
            self.json(403, {"error": "不接受其他來源的請求"})
            return
        if self.path != "/api/sandbox":
            self.json(404, {"error": "找不到 API"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise ValueError("請求大小不符")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("請使用 JSON")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("請求須為 JSON 物件")
            company = next((c for c in fixture()["companies"] if c["id"] == data.get("company")), None)
            if company is None:
                raise ValueError("找不到公司")
            self.json(200, calculate(company, data))
        except (ValueError, TypeError, ArithmeticError) as exc:
            self.json(422, {"error": str(exc) if isinstance(exc, ValueError) else "數值格式不正確"})


def main() -> None:
    parser = argparse.ArgumentParser(description="StockOS 本機 UI（合成示範資料）")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 須介於 1024 與 65535")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        parser.exit(1, f"無法啟動：{exc}\n請改用 --port 8502，或在原終端機按 Ctrl+C。\n")
    print(f"StockOS 示範工作區：http://127.0.0.1:{args.port}\nCtrl+C 停止；不讀取資料庫、不呼叫模型。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStockOS 已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
