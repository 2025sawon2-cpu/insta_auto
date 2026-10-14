"""One new action-specific search; explicitly select one download at a time."""
import argparse
import json
import sys
from pathlib import Path
from tools import rework_tiktok_batch as batch

CODE = 'DeRFXHpEwck'
ROOT = Path('data/a7-receipt-review-20261011-v6').resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['search', 'download'])
    parser.add_argument('--url')
    args = parser.parse_args()
    batch.ROOT = ROOT
    batch.QUERIES = {CODE: ['영수증 미니 파일 홀더']}
    if args.phase == 'download':
        if not args.url:
            parser.error('One observed candidate URL is required.')
        path = ROOT / CODE / 'discovery.json'
        data = json.loads(path.read_text('utf-8'))
        matches = [r for r in data['candidates'] if r['url'] == args.url]
        if len(matches) != 1:
            raise RuntimeError('URL must come from this actual search result.')
        for row in data['candidates']:
            row['selected'] = row['url'] == args.url
        batch.save(path, data)
    sys.argv = ['a7_receipt_sources', args.phase, '--code', CODE]
    batch.main()


if __name__ == '__main__':
    main()
