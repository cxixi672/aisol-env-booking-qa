"""DIWU-63 HTTP acceptance regression. See README for isolated dataset requirements."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier, Thread
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from contract_stub import server


def expect(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


class Client:
    def __init__(self, url):
        self.url = url.rstrip('/') + '/api/'
        self.prefix = uuid4().hex

    def call(self, method, route, user, payload, status, code='000000', key=None):
        url = self.url + route
        if method == 'GET':
            url += '?' + urlencode(payload)
        headers = {'Content-Type': 'application/json'}
        if user is not None:
            headers['X-User'] = user
        if key:
            headers['Idempotency-Key'] = self.prefix + '-' + key
        body = json.dumps(payload).encode() if method == 'POST' else None
        req = Request(url, data=body, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read().decode()
            print(json.dumps(dict(method=method, url=url, headers=headers, payload=payload,
                                  status=response.status, response=raw), ensure_ascii=False), flush=True)
            expect(response.status, status)
            envelope = json.loads(raw)
            expect(envelope['code'], code)
            if status >= 400:
                expect(envelope['data'], None)
                expect(isinstance(envelope['desc'], str) and bool(envelope['desc']), True)
            else:
                expect(envelope['desc'], 'OK')
            return envelope['data']

    def add(self, resource, user, slot, key):
        row = self.call('POST', resource, user, slot, 201, key=key)
        expected = 'waiting' if resource == 'waitlist' else 'active'
        for field, value in dict(slot, user=user, status=expected).items():
            expect(row[field], value)
        expect(isinstance(row['id'], str) and bool(row['id']), True)
        return row

    def rows(self, resource, user, slot):
        rows = self.call('GET', resource, user, slot, 200)
        expect(isinstance(rows, list), True)
        return rows

    def cancel(self, resource, row):
        result = self.call('DELETE', resource + '/' + row['id'], row['user'], None, 200)
        expect(result, dict(row, status='cancelled'))


def slots(day):
    def stamp(hour):
        return day.isoformat() + 'T' + hour + ':00Z'
    full = dict(env='env-a', start=stamp('10:00'), end=stamp('11:00'))
    return full, dict(full, end=stamp('10:30')), dict(full, start=stamp('10:30'))


def main_case(c, day):
    full, first, second = slots(day)
    for resource in ('bookings', 'maintenance', 'waitlist'):
        for user in (('alice', 'bob', 'carol', 'admin') if resource == 'waitlist' else ('admin',)):
            expect(c.rows(resource, user, full), [])
    for user in (None, 'unknown'):
        c.call('GET', 'waitlist', user, full, 403, 'FORBIDDEN')
    c.call('POST', 'waitlist', 'bob', full, 400, 'INVALID_INPUT')
    c.call('POST', 'waitlist', 'bob', full, 409, 'SLOT_AVAILABLE', 'available')
    booking = c.add('bookings', 'alice', first, 'alice')
    maint = c.add('maintenance', 'admin', second, 'half')
    bob = c.add('waitlist', 'bob', full, 'bob')
    expect(c.call('POST', 'waitlist', 'bob', full, 200, key='bob'), bob)
    c.call('POST', 'waitlist', 'bob', first, 409, 'KEY_REUSED', 'bob')
    c.call('POST', 'waitlist', 'bob', full, 409, 'ALREADY_WAITING', 'again')
    carol = c.add('waitlist', 'carol', full, 'carol')
    expect(bob['id'] != carol['id'], True)

    def states(b, k):
        for r, status in ((bob, b), (carol, k)):
            records = c.rows('waitlist', r['user'], full)
            expect(len(records), 1)
            actual = records[0]
            for field, value in dict(r, status=status).items():
                expect(actual[field], value)
            if status == 'promoted':
                expect(isinstance(actual['bookingId'], str) and bool(actual['bookingId']), True)

    def winner(r):
        queue = c.rows('waitlist', r['user'], full)[0]
        active = c.rows('bookings', 'admin', full)
        expect(len(active), 1)
        for field, value in dict(full, user=r['user'], id=queue['bookingId'], status='active').items():
            expect(active[0][field], value)
        return active[0]

    states('waiting', 'waiting')
    expect(c.rows('waitlist', 'bob', dict(full, env='env-b')), [])
    expect(c.rows('waitlist', 'bob', dict(full, start=full['end'], end=full['end'].replace('11:', '12:'))), [])
    c.call('DELETE', 'bookings/' + booking['id'], 'bob', None, 403, 'FORBIDDEN')
    c.call('DELETE', 'maintenance/' + maint['id'], 'carol', None, 403, 'FORBIDDEN')
    expect(c.rows('bookings', 'admin', full), [booking])
    expect(c.rows('maintenance', 'admin', full), [maint])
    c.cancel('bookings', booking)
    states('waiting', 'waiting')
    expect(c.rows('bookings', 'admin', full), [])
    c.cancel('maintenance', maint)
    states('promoted', 'waiting')
    b = winner(bob)
    c.cancel('maintenance', maint)
    expect(winner(bob), b)
    states('promoted', 'waiting')
    c.cancel('bookings', b)
    states('promoted', 'promoted')
    k = winner(carol)
    expect(k['id'] != b['id'], True)
    c.cancel('bookings', b)
    expect(winner(carol), k)
    c.cancel('bookings', k)
    expect(c.rows('bookings', 'admin', full), [])
    expect(c.rows('maintenance', 'admin', full), [])


def skip_case(c, day):
    full, left, right = slots(day)
    for resource, user in [('bookings', 'admin'), ('maintenance', 'admin'), ('waitlist', 'bob')]:
        expect(c.rows(resource, user, full), [])
    a = c.add('bookings', 'alice', left, 'skip-a')
    m = c.add('maintenance', 'admin', right, 'skip-m')
    head = c.add('waitlist', 'bob', full, 'skip-head')
    follower = c.add('waitlist', 'bob', left, 'skip-follower')
    expect(c.rows('waitlist', 'bob', full), [head, follower])
    barrier = Barrier(2)

    def release(_):
        barrier.wait(timeout=5)
        c.cancel('bookings', a)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(release, range(2)))
    waiting, promoted = c.rows('waitlist', 'bob', full)
    expect(waiting, head)
    active, = c.rows('bookings', 'admin', full)
    expect(active, dict(left, status='active', user='bob', id=active['id']))
    expect(promoted, dict(follower, status='promoted', bookingId=active['id']))
    c.cancel('maintenance', m)
    expect(c.rows('waitlist', 'bob', full)[0], head)
    c.cancel('bookings', active)
    last, = c.rows('bookings', 'admin', full)
    expect(c.rows('waitlist', 'bob', full)[0], dict(head, status='promoted', bookingId=last['id']))
    c.cancel('bookings', last)
    expect(c.rows('bookings', 'admin', full), [])


def run(url, day):
    c = Client(url)
    main_case(c, day)
    skip_case(c, day + timedelta(days=1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--stub', action='store_true')
    mode.add_argument('--url', help='loopback API origin with an isolated dataset')
    parser.add_argument('--day', type=date.fromisoformat, default=date(2030, 1, 2))
    args = parser.parse_args()
    if args.stub:
        with server(0) as httpd:
            thread = Thread(target=httpd.serve_forever)
            thread.start()
            try:
                run('http://127.0.0.1:' + str(httpd.server_port), args.day)
            finally:
                httpd.shutdown()
                thread.join()
    else:
        if urlsplit(args.url).hostname not in ('127.0.0.1', 'localhost', '::1'):
            parser.error('--url must use loopback')
        run(args.url, args.day)
    print('PASS ' + ('contract fixture' if args.stub else args.url))
