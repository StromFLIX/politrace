"""Verify the built public snapshot over HTTPS; a queued build is not a deployment.

No deployment credential is needed. Coolify receives authenticated GitHub App push
webhooks. CI waits for this exact build, including OCR and progress products which
are deliberately not covered by the legacy data_sha256 field alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class SnapshotMismatch(RuntimeError):
    """Only public paths/statuses, never response bodies, appear in diagnostics."""


def fetch(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Politrace-deployment-verification/1.0', 'Cache-Control': 'no-cache',
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise SnapshotMismatch('Public response exceeds the verification size limit')
            return response.status, body
    except urllib.error.HTTPError as error:
        # An error page can contain provider diagnostics. Never print or retain it.
        return error.code, b''


def expected_snapshot(dist: Path) -> dict[str, bytes]:
    paths = {
        '/api/v1/live/index.json': 'api/v1/live/index.json',
        '/api/health.json': 'api/health.json',
        '/api/v1/live/analysis.json': 'api/v1/live/analysis.json',
        '/api/v1/live/readings.json': 'api/v1/live/readings.json',
        '/api/v1/live/reading-progress.json': 'api/v1/live/reading-progress.json',
        '/': 'index.html',
        '/fortschritt/': 'fortschritt/index.html',
    }
    # Check every programme reader, not only an API count. Page HTML also fingerprints
    # the rendered layout/assets, so unchanged political data cannot mask old code.
    readings = json.loads((dist / 'api/v1/live/readings.json').read_text())
    for reading in readings['items']:
        document_id = reading['document_id']
        if not document_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in document_id):
            raise ValueError('Invalid document ID in built reading index')
        if reading['collection'] == 'programs':
            url = f'/live/programme/{document_id}/'
            paths[url] = url.lstrip('/') + 'index.html'
    # One representative law reader, in addition to the full reading-edition digest list.
    law = next((r for r in readings['items'] if r['collection'] == 'laws'), None)
    if law:
        url = f'/live/gesetze/{law["document_id"]}/'
        paths[url] = url.lstrip('/') + 'index.html'
    return {url: (dist / path).read_bytes() for url, path in paths.items()}


def verify_once(base_url: str, expected: dict[str, bytes], *, request=fetch) -> None:
    for path, wanted in expected.items():
        status, actual = request(base_url + path)
        if status != 200:
            raise SnapshotMismatch(f'{path}: HTTP {status}, expected 200')
        if hashlib.sha256(actual).digest() != hashlib.sha256(wanted).digest():
            raise SnapshotMismatch(f'{path}: served content differs from the tested build')
    for path in ('/api/v1/live/does-not-exist.json', '/demo/', '/api/v1/demo/index.json'):
        status, _ = request(base_url + path)
        if status != 404:
            raise SnapshotMismatch(f'{path}: HTTP {status}, expected a genuine 404')
    # Detect a deployment changing mid-check rather than declaring a mixed snapshot good.
    path = '/api/v1/live/index.json'
    status, actual = request(base_url + path)
    if status != 200 or actual != expected[path]:
        raise SnapshotMismatch('The public snapshot changed during verification')


def wait_for_deployment(base_url: str, expected: dict[str, bytes], *, timeout=600,
                        interval=15, request=fetch, clock=time.monotonic,
                        sleep=time.sleep, report=print) -> None:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('An HTTPS origin without credentials/query/fragment is required')
    if parsed.path not in ('', '/'):
        raise ValueError('Provide the HTTPS origin, not a path')
    if timeout <= 0 or interval <= 0:
        raise ValueError('Timeout and interval must be positive')
    base_url = base_url.rstrip('/')
    deadline = clock() + timeout
    while True:
        try:
            verify_once(base_url, expected, request=request)
            report(f'Verified exact deployed snapshot: {len(expected)} source/API/reader paths and retired-route 404s')
            return
        except (SnapshotMismatch, urllib.error.URLError, TimeoutError) as error:
            reason = str(error) if isinstance(error, SnapshotMismatch) else type(error).__name__
            if clock() >= deadline:
                raise SnapshotMismatch(f'Deployment not verified within {timeout}s: {reason}') from None
            report(f'Waiting for deployment: {reason}')
            sleep(min(interval, max(0, deadline - clock())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--base-url', default='https://politrace.stromflix.com')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    wait_for_deployment(args.base_url, expected_snapshot(args.dist), timeout=args.timeout)


if __name__ == '__main__':
    main()
