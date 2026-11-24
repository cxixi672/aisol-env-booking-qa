"""In-memory HTTP contract fixture for the maintenance regression."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qsl, urlsplit


def server(port=0):
    rows = {"bookings": [], "maintenance": []}
    replay = {}
    mutex = Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def dispatch(self):
            path = urlsplit(self.path)
            _, api, resource, *ids = path.path.split("/")
            user = self.headers.get("X-User")
            if api != "api" or resource not in rows:
                return 404, "NOT_FOUND", None
            if user not in ("alice", "bob", "carol", "admin"):
                return 403, "FORBIDDEN", None
            if self.command != "GET" and resource == "maintenance" and user != "admin":
                return 403, "FORBIDDEN", None
            if self.command == "DELETE":
                record = next((r for r in rows[resource] if [r["id"]] == ids), None)
                if record is None:
                    return 404, "NOT_FOUND", None
                if resource == "bookings" and record["user"] != user:
                    return 403, "FORBIDDEN", None
                record["status"] = "cancelled"
                return 200, "000000", record
            payload = dict(parse_qsl(path.query)) if self.command == "GET" else json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if (payload.get("env") not in ("env-a", "env-b") or not payload.get("start")
                    or not payload.get("end") or payload["start"] >= payload["end"]):
                return 400, "INVALID_INPUT", None

            def overlapping(kind):
                return [r for r in rows[kind] if r["status"] == "active" and r["env"] == payload["env"]
                        and r["start"] < payload["end"] and payload["start"] < r["end"]]

            if self.command == "GET":
                return 200, "000000", overlapping(resource)
            key = user, resource, self.headers.get("Idempotency-Key")
            if not key[2]:
                return 400, "INVALID_INPUT", None
            if key in replay:
                original, record = replay[key]
                if original == payload:
                    return 200, "000000", record
                return 409, "KEY_REUSED", None
            for kind, code in (("maintenance", "MAINTENANCE_CONFLICT"), ("bookings", "BOOKING_CONFLICT")):
                if overlapping(kind):
                    return 409, code, None
            record = dict(payload, id=str(len(rows[resource]) + 1), user=user, status="active")
            rows[resource].append(record)
            replay[key] = payload, record.copy()
            return 201, "000000", record

        def handle_request(self):
            with mutex:
                status, code, data = self.dispatch()
                desc = {
                    "000000": "OK", "BOOKING_CONFLICT": "时段已有预约",
                    "MAINTENANCE_CONFLICT": "时段处于维护窗口", "KEY_REUSED": "幂等键已用于不同请求",
                    "INVALID_INPUT": "请求参数无效", "NOT_FOUND": "记录不存在", "FORBIDDEN": "无权限",
                }[code]
                body = json.dumps(dict(code=code, desc=desc, data=data)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET = do_DELETE = handle_request

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    with server(parser.parse_args().port) as httpd:
        print(f"Contract fixture http://127.0.0.1:{httpd.server_port}", flush=True)
        httpd.serve_forever()
