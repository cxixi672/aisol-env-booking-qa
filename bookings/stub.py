"""Loopback-only booking HTTP fixture. No persistence or database calls."""
import argparse
import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlsplit

ROUTE = "/api/bookings"
USERS = {"alice", "bob", "carol", "admin"}


def normalize_slot(body):
    if not isinstance(body, dict) or body.get("env") not in ("env-a", "env-b"):
        return None
    slot = {"env": body["env"]}
    try:
        for key in ("start", "end"):
            value = body[key]
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value):
                return None
            utc = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
            slot[key] = utc.isoformat(timespec="seconds").replace("+00:00", "Z")
        return slot if slot["start"] < slot["end"] else None
    except (TypeError, KeyError, ValueError, OverflowError):
        return None


class BookingFixture(ThreadingHTTPServer):
    def __init__(self, port=0):
        super().__init__(("127.0.0.1", port), Handler)
        self.rows = {}
        self.replays = {}
        self.lock = Lock()

    def dispatch(self, method, url, user, key, body):
        path = urlsplit(url)
        if user not in USERS:
            return 403, "FORBIDDEN", None
        if method == "DELETE" and path.path.startswith(ROUTE + "/"):
            row = self.rows.get(path.path[len(ROUTE) + 1:])
            if row is None:
                return 404, "NOT_FOUND", None
            if row["user"] != user:
                return 403, "FORBIDDEN", None
            row["status"] = "cancelled"
            return 200, "000000", row.copy()
        if path.path != ROUTE:
            return 404, "NOT_FOUND", None
        if method == "GET":
            body = {k: v[0] for k, v in parse_qs(path.query).items()}
        body = normalize_slot(body)
        if body is None or (method == "POST" and not key):
            return 400, "INVALID_INPUT", None
        overlaps = [r.copy() for r in self.rows.values() if r["env"] == body["env"]
                    and r["status"] == "active" and r["start"] < body["end"] and body["start"] < r["end"]]
        if method == "GET":
            return 200, "000000", overlaps
        if method != "POST":
            return 404, "NOT_FOUND", None
        previous = self.replays.get((user, key))
        if previous:
            payload, row = previous
            if payload != body:
                return 409, "KEY_REUSED", None
            return 200, "000000", row
        if overlaps:
            return 409, "BOOKING_CONFLICT", None
        rid = str(len(self.rows) + 1)
        row = dict(body, id=rid, user=user, status="active")
        self.rows[rid] = row
        self.replays[user, key] = (body, row.copy())
        return 201, "000000", row


class Handler(BaseHTTPRequestHandler):
    def handle_request(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size)) if size else None
            with self.server.lock:
                status, code, data = self.server.dispatch(self.command, self.path,
                    self.headers.get("X-User"), self.headers.get("Idempotency-Key"), body)
                descriptions = {"000000": "OK", "BOOKING_CONFLICT": "时段已有预约"}
                raw = json.dumps(dict(code=code, desc=descriptions.get(code, code), data=data)).encode()
        except (ValueError, UnicodeError):
            status = 400
            raw = b'{"code":"INVALID_INPUT","desc":"Invalid JSON","data":null}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_POST = do_GET = do_DELETE = handle_request

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    with BookingFixture(parser.parse_args().port) as fixture:
        print(f"http://127.0.0.1:{fixture.server_port}", flush=True)
        fixture.serve_forever()
