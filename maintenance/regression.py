"""Run against the in-memory fixture (default) or an isolated live API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Thread
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from fixture import server

A = dict(env="env-a", start="2030-01-02T10:00:00Z", end="2030-01-02T11:00:00Z")
B = dict(A, env="env-b")
NEXT = dict(A, start=A["end"], end="2030-01-02T12:00:00Z")
WIDE = dict(A, end=NEXT["end"])


def run(base):
    prefix = uuid4().hex

    def request(method, path, user, payload=None, key=None):
        headers = {"Content-Type": "application/json"}
        if user:
            headers["X-User"] = user
        if key:
            headers["Idempotency-Key"] = prefix + "-" + key
        body = None
        if payload is not None:
            if method == "GET":
                path += "?" + urlencode(payload)
            else:
                body = json.dumps(payload).encode()
        req = Request(base + "/api/" + path, body, headers, method=method)
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            result = response.status, json.load(response)
        print(json.dumps(dict(method=method, path=path, user=user, key=key, input=payload,
                              http=result[0], response=result[1]), ensure_ascii=False), flush=True)
        return result

    def check(result, status, code="000000"):
        actual, obj = result
        assert (actual, obj["code"]) == (status, code), result
        assert isinstance(obj["desc"], str) and obj["desc"], result
        if code == "000000":
            assert obj["desc"] == "OK", result
        else:
            assert obj["data"] is None, result
            if code == "BOOKING_CONFLICT":
                assert obj["desc"] == "时段已有预约", result
        return obj["data"]

    def listed(resource, interval=A):
        return check(request("GET", resource, "alice", interval), 200)

    def created(result, interval, user):
        record = check(result, 201)
        assert isinstance(record["id"], str) and record["id"], record
        for field, value in dict(interval, user=user, status="active").items():
            assert record[field] == value, record
        return record

    def cancel(resource, record):
        expected = dict(record, status="cancelled")
        result = request("DELETE", resource + "/" + record["id"], record["user"])
        assert check(result, 200) == expected

    m, b = "maintenance", "bookings"
    for resource in (m, b):
        for window in (WIDE, B):
            assert listed(resource, window) == [], "use a clean test database"

    for user in (None, "unknown", "alice"):
        check(request("POST", m, user, A, "deny"), 403, "FORBIDDEN")
    check(request("GET", m, None, A), 403, "FORBIDDEN")
    check(request("GET", m, "alice", {"env": "env-a"}), 400, "INVALID_INPUT")
    check(request("POST", m, "admin", A), 400, "INVALID_INPUT")
    check(request("POST", m, "admin", dict(A, start=A["end"]), "zero"), 400, "INVALID_INPUT")
    win = created(request("POST", m, "admin", A, "window"), A, "admin")
    assert check(request("POST", m, "admin", A, "window"), 200) == win
    check(request("POST", m, "admin", B, "window"), 409, "KEY_REUSED")
    check(request("POST", m, "admin", A, "overlap"), 409, "MAINTENANCE_CONFLICT")
    check(request("POST", b, "alice", A, "blocked"), 409, "MAINTENANCE_CONFLICT")
    check(request("DELETE", m + "/" + win["id"], "bob"), 403, "FORBIDDEN")
    assert listed(m) == [win] and listed(b) == []
    assert listed(m, dict(A, start="2030-01-02T10:30:00Z")) == [win]
    assert listed(m, NEXT) == [] and listed(m, B) == []
    for interval, key in ((NEXT, "adjacent"), (B, "env-b")):
        other = created(request("POST", b, "alice", interval, key), interval, "alice")
        cancel(b, other)
    cancel(m, win)
    cancel(m, win)
    assert listed(m) == []
    booking = created(request("POST", b, "alice", A, "existing"), A, "alice")
    check(request("POST", m, "admin", A, "existing-conflict"), 409, "BOOKING_CONFLICT")
    assert listed(b) == [booking] and listed(m) == []
    cancel(b, booking)

    barrier = Barrier(2)

    def race(resource, user):
        barrier.wait(timeout=10)
        return request("POST", resource, user, A, "race-" + resource)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(race, m, "admin")
        second = pool.submit(race, b, "alice")
        maintenance, booking = first.result(), second.result()
    if maintenance[0] == 201:
        winner = created(maintenance, A, "admin")
        check(booking, 409, "MAINTENANCE_CONFLICT")
        kind, other = m, b
    else:
        winner = created(booking, A, "alice")
        check(maintenance, 409, "BOOKING_CONFLICT")
        kind, other = b, m
    assert listed(kind) == [winner] and listed(other) == []
    cancel(kind, winner)
    for interval in (WIDE, B):
        assert listed(m, interval) == [] and listed(b, interval) == []
    print("PASS maintenance HTTP regression, race winner:", kind)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="loopback origin of API backed by an isolated empty test DB")
    args = parser.parse_args()
    if not __debug__:
        parser.error("assertions must be enabled; unset PYTHONOPTIMIZE")
    if args.base_url is None:
        with server() as httpd:
            worker = Thread(target=httpd.serve_forever)
            worker.start()
            try:
                print("MODE in-memory contract fixture")
                run("http://127.0.0.1:" + str(httpd.server_port))
            finally:
                httpd.shutdown()
                worker.join()
    else:
        uri = urlsplit(args.base_url)
        if uri.scheme != "http" or uri.hostname not in ("localhost", "127.0.0.1", "::1") or uri.path.strip("/") or uri.query or uri.fragment or uri.username:
            parser.error("expected loopback HTTP origin")
        print("MODE live API")
        run(args.base_url.rstrip("/"))
