"""Check small, linked current instructions without loading operational history."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


def check(root):
    root = Path(root).resolve()
    config = json.loads((root / 'docs/guidance.json').read_text(encoding='utf-8'))
    errors = []
    for name, budget in config['documents'].items():
        path = root / name
        if not path.is_file():
            errors.append(f'{name}: missing document')
            continue
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        if len(raw) > budget:
            errors.append(f'{name}: {len(raw)} bytes exceeds {budget}')
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', text):
            target = target.strip().strip('<>')
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            linked = (path.parent / unquote(parsed.path)).resolve()
            if not linked.is_relative_to(root) or not linked.is_file():
                errors.append(f'{name}: broken/local-only link {target}')
    agents = (root / 'AGENTS.md').read_text(encoding='utf-8')
    for target in config['required_routes']:
        if f']({target})' not in agents:
            errors.append(f'AGENTS.md: required route missing: {target}')
    for phrase in config['forbidden_root_phrases']:
        if phrase in agents:
            errors.append(f'AGENTS.md: retired instruction: {phrase}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--peer', type=Path, help='Optional other repo for shared collaboration policy parity')
    args = parser.parse_args()
    errors = check(args.root)
    if args.peer:
        read = lambda path: path.read_text(encoding='utf-8').strip()
        if read(args.root / 'docs/COLLABORATION.md') != read(args.peer / 'docs/COLLABORATION.md'):
            errors.append('COLLABORATION.md differs between repositories')
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print('Guidance size, routes and current-document links passed.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
