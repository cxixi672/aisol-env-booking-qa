"""In-memory HTTP fixture for DIWU-63. Invoke with a loopback port for UI testing."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlsplit


class Fixture:
    def __init__(self):
        self.rows = {name: [] for name in ('bookings', 'maintenance', 'waitlist')}
        self.created = {}
        self.sequence = 0

    def insert(self, resource, slot, user, status):
        self.sequence += 1
        row = dict(slot, id=str(self.sequence), user=user, status=status)
        self.rows[resource].append(row)
        return row

    def overlaps(self, resource, slot):
        return [r for r in self.rows[resource] if r['env'] == slot['env']
                and r['start'] < slot['end'] and slot['start'] < r['end']
                and r['status'] != 'cancelled']

    def blocked(self, slot):
        return self.overlaps('bookings', slot) or self.overlaps('maintenance', slot)

    def release(self, env):
        for r in self.rows['waitlist']:
            if r['env'] == env and r['status'] == 'waiting' and not self.blocked(r):
                slot = {k: r[k] for k in ('env', 'start', 'end')}
                booking = self.insert('bookings', slot, r['user'], 'active')
                r.update(status='promoted', bookingId=booking['id'])

    def handle(self, method, route, user, key, slot):
        _, prefix, resource, *ids = route.split('/')
        if prefix != 'api' or resource not in self.rows:
            return 'NOT_FOUND', None
        if method == 'POST' and ids:
            if ids == ['list']:
                method = 'GET'
            elif ids == ['cancel'] and resource != 'waitlist':
                if not isinstance(slot, dict) or type(slot.get('id')) is not int or slot['id'] < 1:
                    return 'INVALID_INPUT', None
                method, ids = 'DELETE', [str(slot['id'])]
            elif ids != ['create']:
                return 'NOT_FOUND', None
        if user not in ('alice', 'bob', 'carol', 'admin'):
            return 'FORBIDDEN', None
        if method != 'GET' and resource == 'maintenance' and user != 'admin':
            return 'FORBIDDEN', None
        if method == 'DELETE' and ids and resource != 'waitlist':
            row = next((r for r in self.rows[resource] if r['id'] == ids[0]), None)
            if row is None:
                return 'NOT_FOUND', None
            if resource == 'bookings' and row['user'] != user:
                return 'FORBIDDEN', None
            if row['status'] == 'active':
                row['status'] = 'cancelled'
                self.release(row['env'])
            return '000000', row
        if (set(slot) != {'env', 'start', 'end'} or slot['env'] not in ('env-a', 'env-b')
                or slot['start'] >= slot['end'] or (method == 'POST' and not key)):
            return 'INVALID_INPUT', None
        if method == 'GET':
            return '000000', [r for r in self.overlaps(resource, slot)
                                   if resource != 'waitlist' or r['user'] == user]
        token = (user, resource, key)
        if token in self.created:
            payload, original = self.created[token]
            if payload != slot:
                return 'KEY_REUSED', None
            return '000000', original
        if resource == 'waitlist':
            if not self.blocked(slot):
                return 'SLOT_AVAILABLE', None
            for r in self.rows[resource]:
                if r['user'] == user and r['status'] == 'waiting' and all(r[k] == v for k, v in slot.items()):
                    return 'ALREADY_WAITING', None
        elif self.overlaps('bookings', slot):
            return 'BOOKING_CONFLICT', None
        elif self.overlaps('maintenance', slot):
            return 'MAINTENANCE_CONFLICT', None
        row = self.insert(resource, slot, user, 'waiting' if resource == 'waitlist' else 'active')
        self.created[token] = (slot.copy(), row.copy())
        return '000000', row


def server(port):
    fixture = Fixture()

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            url = urlsplit(self.path)
            slot = dict(parse_qsl(url.query))
            if self.command == 'POST':
                slot = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            code, data = fixture.handle(self.command, url.path, self.headers.get('X-User'),
                                                self.headers.get('Idempotency-Key'), slot)
            descriptions = {'000000': 'OK', 'BOOKING_CONFLICT': '时段已有预约',
                            'SLOT_AVAILABLE': '时段可预约', 'ALREADY_WAITING': '已在候补队列'}
            body = json.dumps(dict(code=code, desc=descriptions.get(code, code), data=data)).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_DELETE = respond

        def log_message(self, *args):
            pass

    return HTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', type=int)
    with server(parser.parse_args().port) as httpd:
        httpd.serve_forever()
