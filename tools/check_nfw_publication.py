"""Verify deployed NFW content and exact downloadable bytes, not just HTTP 200."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, urlopen


def parse_build_id(value):
    """Accept exactly 7 hex characters or a full 40-character Git SHA; use its first 7."""
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{7}|[0-9a-fA-F]{40})', value):
        raise ValueError('Expected build ID: exactly 7 hex characters or a full 40-character Git SHA')
    return value[:7]


def verify_resources(fetch_bytes, resources, expected_build_id):
    expected_build_id = parse_build_id(expected_build_id)
    checked = []
    for record in resources:
        path = record['path']
        payload = fetch_bytes(path)
        if record.get('sha256') and hashlib.sha256(payload).hexdigest() != record['sha256']:
            raise ValueError('Download hash mismatch at '+path)
        site_html = not record.get('sha256') and (path.endswith('/') or path.endswith('.html'))
        if record.get('required_text') or site_html:
            text = html.unescape(payload.decode('utf-8'))
            for marker in record.get('required_text', []):
                if marker not in text:
                    raise ValueError('Missing content at '+path+': '+marker)
            if site_html:
                for marker in (f'href="/theme/css/site.css?v={expected_build_id}"',
                               f'src="/theme/js/site.js?v={expected_build_id}"'):
                    if marker not in text:
                        raise ValueError('Build ID mismatch at '+path+': expected '+marker)
        checked.append(path)
    return {'status':'PASS','checked_resources':len(checked),'paths':checked}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',default='https://explosion-awas.github.io')
    parser.add_argument('--directory',type=Path,help='Read a local build directory instead of making HTTP requests')
    parser.add_argument('--expected-build-id',required=True,type=parse_build_id,
                        help='7 hex characters or a full 40-character Git SHA (uses its first 7)')
    parser.add_argument('--attempts',type=int,default=24)
    parser.add_argument('--delay',type=float,default=10)
    args = parser.parse_args(argv)
    if args.attempts < 1 or args.delay < 0:
        parser.error('Require positive attempts and nonnegative delay')
    manifest = Path(__file__).resolve().parents[1]/'content/assets/papers/nfw-wave-optics/publication.json'
    resources = json.loads(manifest.read_text(encoding='utf-8'))['resources']
    def fetch(path):
        if args.directory is not None:
            target = args.directory/path.lstrip('/')
            if path.endswith('/'):
                target = target/'index.html'
            return target.read_bytes()
        request = Request(args.base.rstrip('/')+path,headers={'User-Agent':'NFW-publication-smoke/0.1'})
        with urlopen(request,timeout=20) as response:
            if response.status != 200:
                raise ValueError('Unexpected HTTP status at '+path)
            return response.read()
    for attempt in range(args.attempts):
        try:
            result = verify_resources(fetch,resources,args.expected_build_id)
            print(json.dumps(result,indent=2))
            return 0
        except (ValueError,OSError) as error:
            print('Attempt '+str(attempt+1)+': '+str(error),file=sys.stderr)
            if attempt+1 < args.attempts:
                time.sleep(args.delay)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
