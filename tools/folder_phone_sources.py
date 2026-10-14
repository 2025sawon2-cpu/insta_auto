"""One phone-use search in the existing collector; one explicit download."""
import argparse
import json
import sys
from pathlib import Path
from tools import rework_tiktok_batch as batch

CODE = 'DeSoiZvyyqj'
ROOT = Path('data/folder-phone-review-20261011-v8').resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['search', 'download'])
    parser.add_argument('--url')
    args = parser.parse_args()
    batch.ROOT = ROOT
    batch.QUERIES = {CODE: ['Hagibis folder SSD phone photo backup']}
    if args.phase == 'download':
        if not args.url: parser.error('One observed search candidate URL is required.')
        path = ROOT / CODE / 'discovery.json'
        data = json.loads(path.read_text('utf-8'))
        if len([r for r in data['candidates'] if r['url'] == args.url]) != 1:
            raise RuntimeError('URL must come from this actual search result.')
        for row in data['candidates']:
            row['selected'] = row['url'] == args.url
        batch.save(path, data)
    sys.argv = ['folder_phone_sources', args.phase, '--code', CODE]
    batch.main()


if __name__ == '__main__':
    main()
