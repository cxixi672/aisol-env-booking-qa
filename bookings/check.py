"""Exercise an isolated booking API or the bundled HTTP fixture."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.client import HTTPConnection
import json
from threading import Barrier, Thread
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

from stub import BookingFixture

A = dict(env="env-a", start="2030-01-02T10:00:00Z", end="2030-01-02T11:00:00Z")
NEXT = dict(A, start=A["end"], end="2030-01-02T12:00:00Z")
B = dict(A, env="env-b")
SPAN = dict(A, end=NEXT["end"])
ROUTE = "/api/bookings"


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def run(base):
    target = urlsplit(base)
    require(target.scheme == "http" and target.hostname in {"localhost", "127.0.0.1", "::1"}
            and target.path in ("", "/"), "use an isolated HTTP loopback origin")
    prefix = uuid4().hex

    def call(method, user="alice", payload=None, key=None, rid=None):
        path = ROUTE if rid is None else ROUTE + "/" + quote(rid, safe="")
        headers = {}
        if user is not None:
            headers["X-User"] = user
        if key is not None:
            headers["Idempotency-Key"] = prefix + "-" + key
        body = None
        if method == "GET" and payload:
            path += "?" + urlencode(payload)
        elif payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        conn = HTTPConnection(target.hostname, target.port, timeout=10)
        try:
            conn.request(method, path, body, headers)
            resp = conn.getresponse()
            raw = resp.read().decode()
            print(json.dumps(dict(method=method, path=path, headers=headers, body=payload,
                                  status=resp.status, response=raw), ensure_ascii=False), flush=True)
            return resp.status, json.loads(raw)
        finally:
            conn.close()

    def expect(reply, status, code="000000"):
        actual, env = reply
        require((actual, env.get("code")) == (status, code), f"expected {status} {code}, got {reply}")
        require(isinstance(env.get("desc"), str) and "data" in env, f"invalid envelope {env}")
        if code == "000000":
            require(env["desc"] == "OK", str(env))
        else:
            require(env["data"] is None, str(env))
            if code == "BOOKING_CONFLICT":
                require(env["desc"] == "时段已有预约", str(env))
        return env["data"]

    def record(row, user, slot):
        require(isinstance(row.get("id"), str) and row["id"], str(row))
        for k, v in dict(slot, user=user, status="active").items():
            require(row.get(k) == v, str(row))
        return row

    def listing(slot, rows):
        require(expect(call("GET", "carol", slot), 200) == rows, f"unexpected listing for {slot}")

    def race(attempts):
        barrier = Barrier(2)
        def submit(args):
            barrier.wait(timeout=5)
            return call("POST", *args)
        with ThreadPoolExecutor(2) as pool:
            return list(pool.map(submit, attempts))

    with ExitStack() as cleanup:
        def track(row):
            cleanup.callback(lambda: expect(call("DELETE", row["user"], rid=row["id"]), 200))
            return row

        for slot in [SPAN, B]:
            listing(slot, [])
        for identity in (None, "guest"):
            expect(call("POST", identity, A, "unknown"), 403, "FORBIDDEN")
        expect(call("POST", "alice", A), 400, "INVALID_INPUT")
        expect(call("POST", "alice", dict(A, end=A["start"]), "bad"), 400, "INVALID_INPUT")
        expect(call("GET", payload={"env": "env-a"}), 400, "INVALID_INPUT")

        users = ["alice", "bob"]
        attempts = [(u, A, "competition") for u in users]
        replies = race(attempts)
        winners = [i for i, (status, _) in enumerate(replies) if status == 201]
        require(len(winners) == 1, "expected exactly one creator")
        i = winners[0]
        winner, other = users[i], users[1-i]
        first = track(record(expect(replies[i], 201), winner, A))
        expect(replies[1-i], 409, "BOOKING_CONFLICT")
        replay = expect(call("POST", winner, dict(reversed(list(A.items()))), "competition"), 200)
        require(first == replay, "replay changed record")
        expect(call("POST", winner, NEXT, "competition"), 409, "KEY_REUSED")
        listing(A, [first])

        twins = sorted(race([("carol", NEXT, "adjacent")] * 2), key=lambda pair: pair[0])
        adjacent = track(record(expect(twins[1], 201), "carol", NEXT))
        require(expect(twins[0], 200) == adjacent, "same-key concurrent replay differed")
        isolated = track(record(expect(call("POST", other, B, "competition"), 201), other, B))
        require(len({r["id"] for r in (first, adjacent, isolated)}) == 3, "duplicate booking IDs")
        listing(A, [first])
        listing(NEXT, [adjacent])
        listing(SPAN, [first, adjacent])
        listing(B, [isolated])
        expect(call("DELETE", other, rid=first["id"]), 403, "FORBIDDEN")
        listing(A, [first])
        for _ in range(2):
            cancelled = expect(call("DELETE", winner, rid=first["id"]), 200)
            require(cancelled == dict(first, status="cancelled"), "unexpected cancellation")
        listing(SPAN, [adjacent])
        listing(B, [isolated])
        replacement = track(record(expect(call("POST", other, A, "released"), 201), other, A))
        listing(A, [replacement])
    for slot in [SPAN, B]:
        listing(slot, [])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="isolated candidate origin (default starts a fresh HTTP stub)")
    args = parser.parse_args()
    with ExitStack() as stack:
        base = args.base_url
        if base is None:
            server = stack.enter_context(BookingFixture())
            thread = Thread(target=server.serve_forever)
            thread.start()
            stack.callback(thread.join)
            stack.callback(server.shutdown)
            base = f"http://127.0.0.1:{server.server_port}"
        print("TARGET", "external" if args.base_url else "in-memory stub", base, flush=True)
        run(base)
        print("PASS")
