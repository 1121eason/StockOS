#!/usr/bin/env python3
"""NVDA UI: loopback by default, or a private authenticated-proxy backend."""

from __future__ import annotations

import argparse
import json
import mimetypes
import signal
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
    "/research": "research.html",
    "/research.js": "research.js",
    "/app.js": "app.js",
    "/domain.mjs": "domain.mjs",
    "/styles.css": "styles.css",
    "/favicon.svg": "favicon.svg",
    "/nvda": "nvda.html",
    "/nvda.js": "nvda.js",
    "/nvda.css": "nvda.css",
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
            "served_at": datetime.now(UTC).isoformat(), "backend_baseline": "0c9d858da7eb92e2387cb918bbbe5968ad2a1a54"}


class ResearchHTTPServer(ThreadingHTTPServer):
    research_store: Path | None = None
    workbench: Any = None
    public_origin: str | None = None


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
            asset = "nvda.html" if url.path == "/" and getattr(self.server, "workbench", None) else ASSETS[url.path]
            path = ROOT / "ui" / asset
            mime = mimetypes.guess_type(path)[0] or "text/javascript"
            if path.suffix == ".mjs":
                mime = "text/javascript"
            self.send(200, path.read_bytes(), mime + "; charset=utf-8")
        elif url.path == "/api/nvda":
            workbench = getattr(self.server, "workbench", None)
            if workbench is None:
                self.json(200, {"configured": False, "research": None,
                                "message": "尚未設定 NVDA 研究來源；不會替代為示範資料。"})
            else:
                try:
                    self.json(200, {"configured": True, **workbench.load()})
                except (ValueError, OSError, KeyError):
                    self.json(200, {"configured": True, "research": None,
                                    "last_attempt": workbench.last_attempt,
                                    "message": "尚無可讀取的研究快照，請按更新研究與股價。"})
        elif url.path in ("/api/research/runs", "/api/research/run"):
            from valuation_engine.research.workspace import list_runs, load_run

            store = getattr(self.server, "research_store", None)
            try:
                if url.path == "/api/research/runs":
                    self.json(200, {"configured": store is not None,
                                    "runs": list_runs(store) if store else []})
                elif store is None:
                    self.json(404, {"error": "未設定獨立研究儲存區"})
                else:
                    self.json(200, load_run(store, parse_qs(url.query).get("id", [""])[0]))
            except (ValueError, OSError):
                self.json(422, {"error": "研究儲存區無法讀取或結果不存在"})
        elif url.path == "/api/health":
            configured = getattr(self.server, "workbench", None) is not None
            self.json(200, {"status": "ok", "mode": "nvda" if configured else "demo", "database_connected": configured,
                            "provider_calls": configured, "ai_model_calls": False,
                            "background_collection": hasattr(getattr(self.server, "workbench", None), "health"),
                            "backend_baseline": "0c9d858da7eb92e2387cb918bbbe5968ad2a1a54"})
        elif url.path.startswith("/api/operations"):
            product = getattr(self.server, "workbench", None)
            if product is None or not hasattr(product, "health"):
                self.json(404, {"error": "尚未啟用背景更新"})
                return
            try:
                if url.path == "/api/operations/health":
                    self.json(200, product.health())
                elif url.path == "/api/operations/history":
                    self.json(200, {"research": product.store.history("research"),
                                    "sources": product.store.history("source_document")})
                elif url.path == "/api/operations/artifact":
                    row = product.store.artifact(parse_qs(url.query).get("id", [""])[0])
                    self.json(200 if row else 404, row or {"error": "找不到紀錄"})
                else:
                    self.json(404, {"error": "找不到操作紀錄"})
            except (ValueError, OSError):
                self.json(422, {"error": "操作紀錄無法核對"})
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
        allowed_origins = (f"http://127.0.0.1:{self.port()}",
                           f"http://localhost:{self.port()}", getattr(self.server, "public_origin", None))
        if (origin and origin not in allowed_origins) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.json(403, {"error": "不接受其他來源的請求"})
            return
        if self.path == "/api/nvda/update":
            workbench = getattr(self.server, "workbench", None)
            if workbench is None:
                self.json(409, {"error": "未設定 NVDA 研究來源"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get_content_type() != "application/json" or not 0 < length <= 128:
                    raise ValueError("請使用有效的 JSON 更新請求。")
                if json.loads(self.rfile.read(length)) != {}:
                    raise ValueError("更新請求不接受資料庫路徑、股票或模型參數。")
                self.json(200, {"configured": True, **workbench.update()})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.json(422, {"error": str(exc) if isinstance(exc, ValueError) else "研究更新失敗，保留上一份正常結果。"})
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


def validate_proxy_origin(origin: str) -> str:
    """An exact HTTPS origin; authentication is provided by the private ingress."""
    parts = urlsplit(origin)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.path or parts.query or parts.fragment or parts.port not in (None, 443)
            or any(c.isspace() for c in origin) or "," in origin):
        raise ValueError("public-origin 必須是完整 HTTPS 網域，不含路徑或帳密")
    return origin


def stop_service(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description="StockOS 本機 UI（合成示範與獨立唯讀研究）")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--research-store", type=Path, help="Explicit isolated research SQLite file; read-only UI")
    parser.add_argument("--source-db", type=Path, help="Explicit NVDA formal source; read only, never migrated")
    parser.add_argument("--raw-dir", type=Path, help="Explicit content-hashed source directory")
    parser.add_argument("--workbench-store", type=Path, default=ROOT / "data/nvda-workbench",
                        help="Separate local immutable research snapshots")
    parser.add_argument("--open-browser", action="store_true", help="Open the local page after startup")
    parser.add_argument("--automation", action="store_true", help="Run durable NVDA quote/source/research background jobs in local shadow mode")
    parser.add_argument("--product-store", type=Path, default=ROOT / "data/nvda-product")
    parser.add_argument("--bind", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--behind-auth-proxy", action="store_true",
                        help="Container private network only; never publish its port")
    parser.add_argument("--public-origin", help="Exact HTTPS origin served by the authenticated proxy")
    parser.add_argument("--deployment", choices=("local", "cloud"), default="local")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 須介於 1024 與 65535")
    if args.automation and (not args.source_db or not args.raw_dir):
        parser.error("背景更新需要 --source-db 與 --raw-dir")
    if args.public_origin:
        try:
            validate_proxy_origin(args.public_origin)
        except ValueError as exc:
            parser.error(str(exc))
    if args.bind != "127.0.0.1" and not (args.behind_auth_proxy and args.public_origin):
        parser.error("容器網路綁定需要 --behind-auth-proxy 與 --public-origin；後端連接埠不可公開")
    if args.deployment == "cloud" and not (args.automation and args.behind_auth_proxy and args.public_origin):
        parser.error("雲端模式需要持久背景更新與已驗證身分的 HTTPS 入口")
    try:
        server = ResearchHTTPServer((args.bind, args.port), Handler)
    except OSError as exc:
        parser.exit(1, f"無法啟動：{exc}\n請改用 --port 8502，或在原終端機按 Ctrl+C。\n")
    server.research_store = args.research_store
    server.public_origin = args.public_origin
    if args.source_db or args.raw_dir:
        if not args.source_db or not args.raw_dir:
            parser.error("--source-db 與 --raw-dir 必須一起指定")
        if args.automation:
            from valuation_engine.research.product import Product

            server.workbench = Product(args.source_db, args.raw_dir, args.product_store,
                                       deployment=args.deployment)
            server.workbench.start()
        else:
            from valuation_engine.research.workbench import Workbench

            server.workbench = Workbench(args.source_db, args.raw_dir, args.workbench_store)
    mode = "NVDA 研究工作台" if server.workbench else "示範工作區"
    print(f"StockOS {mode}：http://127.0.0.1:{args.port}\nCtrl+C 停止；正式來源僅唯讀，更新只保存獨立工作台快照。不呼叫 AI 模型。", flush=True)
    if args.open_browser:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{args.port}/nvda" if server.workbench else f"http://127.0.0.1:{args.port}")
    signal.signal(signal.SIGTERM, stop_service)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStockOS 已停止。")
    finally:
        if args.automation and server.workbench:
            server.workbench.close()
        server.server_close()


if __name__ == "__main__":
    main()
