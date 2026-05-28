from __future__ import annotations

import json
import mimetypes
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlparse

from .ai_service import get_active_ai_provider, is_ai_configured, maybe_generate_ai_answer
from .chat_logic import has_confident_match, should_force_local_answer
from .config import DB_PATH, HOST, PORT, ROOT_DIR
from .http_server_routes_get import handle_api_get
from .http_server_routes_post import handle_api_post
from .http_server_state import get_session
from .store import ensure_bootstrap, run_bootstrap_maintenance


class AppHandler(BaseHTTPRequestHandler):
    server_version = "SOSMedicaPython/1.0"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                handle_api_get(self, parsed)
                return
            self.serve_static(parsed.path)
        except Exception as error:
            self.send_json(500, {"error": str(error) or "Internal server error"})

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                self.send_json(404, {"error": "Not found"})
                return
            handle_api_post(self, parsed, self.read_json_body())
        except Exception as error:
            self.send_json(500, {"error": str(error) or "Internal server error"})

    def serve_static(self, raw_path: str) -> None:
        if raw_path == "/":
            self.send_response(302)
            self.send_cors_headers()
            self.send_header("Location", "/login")
            self.end_headers()
            return

        route_map = {
            "/login": ROOT_DIR / "login.html",
            "/chat": ROOT_DIR / "chat.html",
        }
        target = route_map.get(raw_path)
        if target is None:
            safe_path = (ROOT_DIR / raw_path.lstrip("/")).resolve()
            if not str(safe_path).startswith(str(ROOT_DIR)):
                self.send_text(403, "Forbidden")
                return
            target = safe_path

        if not target.exists() or target.is_dir():
            self.send_text(404, "Not found")
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Last-Modified", formatdate(target.stat().st_mtime, usegmt=True))
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Invalid JSON body") from error

    def require_session(self, allow_guest: bool = False) -> dict[str, str] | None:
        session = get_session(self, allow_guest=allow_guest)
        if not session:
            self.send_json(401, {"error": "Session дууссан байна. Дахин нэвтэрнэ үү."})
            return None
        return session

    def get_cors_origin(self) -> str | None:
        origin = str(self.headers.get("Origin", "") or "").strip()
        if not origin:
            return None

        allowed_prefixes = (
            "http://127.0.0.1:",
            "http://localhost:",
            "http://[::1]:",
            "https://127.0.0.1:",
            "https://localhost:",
            "https://[::1]:",
        )
        allowed_exact = {
            "http://chat.sosmedica.mn",
            "https://chat.sosmedica.mn",
        }
        if origin.startswith(allowed_prefixes) or origin in allowed_exact:
            return origin
        return None

    def send_cors_headers(self) -> None:
        origin = self.get_cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def generate_reply_payload(
        self,
        message_text: str,
        ranked_docs: list[dict[str, Any]],
        reply_documents: list[dict[str, Any]],
        all_documents: list[dict[str, Any]],
        history_messages: list[dict[str, Any]],
        fallback_reply: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not is_ai_configured():
            return fallback_reply, reply_documents[:3] if reply_documents else []

        if should_force_local_answer(message_text, ranked_docs, all_documents, history_messages):
            return fallback_reply, reply_documents[:3] if reply_documents else []

        context_documents = reply_documents[:3]
        if not context_documents and has_confident_match(message_text, ranked_docs):
            context_documents = ranked_docs[:3]

        try:
            reply_text = maybe_generate_ai_answer(
                message_text,
                context_documents,
                history_messages,
            ) or fallback_reply
            return reply_text, context_documents if context_documents else []
        except RuntimeError as error:
            print(f"[AI fallback] {error}")
            return fallback_reply, reply_documents[:3] if reply_documents else []
        except Exception as error:
            print(f"[AI unexpected fallback] {error}")
            return fallback_reply, reply_documents[:3] if reply_documents else []

    def send_text(self, status_code: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status_code)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    ensure_bootstrap(run_maintenance=False)
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Server listening on http://{HOST}:{PORT}")
    print(f"SQLite DB: {DB_PATH}")
    Thread(target=run_bootstrap_maintenance, daemon=True).start()
    server.serve_forever()
