"""Check the management POST routes and their interoperability with legacy routes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from urllib.parse import urlsplit

from regression import Client, expect, main_case, skip_case, slots


class ManagementClient(Client):
    def call(self, method, route, user, payload, code='000000', key=None):
        if method == 'DELETE':
            resource, record_id = route.split('/')
            route = resource + '/cancel'
            payload = {'id': int(record_id)}
        else:
            route += '/list' if method == 'GET' else '/create'
        return super().call('POST', route, user, payload, code, key)


def compatibility(legacy, canonical, day):
    full, _, _ = slots(day)
    adjacent = dict(full, start=full['end'], end=day.isoformat() + 'T12:00:00Z')
    barrier = Barrier(2)

    def create(client):
        barrier.wait(timeout=10)
        return client.add('bookings', 'alice', full, 'shared')

    expect(legacy.rows('bookings', 'alice', full), [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, replay = pool.map(create, (legacy, canonical))
    expect(first, replay)
    expect(canonical.rows('bookings', 'bob', full), [first])
    canonical.call('POST', 'bookings', 'bob', full, 'BOOKING_CONFLICT', 'overlap')
    adjacent_row = canonical.add('bookings', 'bob', adjacent, 'adjacent')
    legacy.cancel('bookings', adjacent_row)
    canonical.cancel('bookings', first)
    expect(legacy.rows('bookings', 'alice', full), [])

    window = canonical.add('maintenance', 'admin', full, 'window')
    expect(legacy.add('maintenance', 'admin', full, 'window'), window)
    canonical.call('POST', 'bookings', 'alice', full, 'MAINTENANCE_CONFLICT', 'blocked')
    queue = legacy.add('waitlist', 'bob', full, 'queue')
    expect(canonical.add('waitlist', 'bob', full, 'queue'), queue)
    legacy.cancel('maintenance', window)
    active, = canonical.rows('bookings', 'alice', full)
    expect(active['user'], 'bob')
    expect(legacy.rows('waitlist', 'bob', full), [dict(queue, status='promoted', bookingId=active['id'])])
    canonical.cancel('bookings', active)
    expect(legacy.rows('bookings', 'alice', full), [])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--day', type=date.fromisoformat, default=date(2030, 2, 1))
    args = parser.parse_args()
    if urlsplit(args.url).hostname not in ('localhost', '::1', '127.0.0.1'):
        parser.error('use an isolated loopback service')
    canonical = ManagementClient(args.url)
    legacy = Client(args.url)
    legacy.prefix = canonical.prefix
    main_case(canonical, args.day)
    skip_case(canonical, args.day + timedelta(days=1))
    compatibility(legacy, canonical, args.day + timedelta(days=2))
    print('PASS management routes, FIFO and legacy interoperability')
