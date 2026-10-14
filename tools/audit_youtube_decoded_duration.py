"""Compare actually decoded duration against declared metadata, without access."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file


def audit(path):
    decoded = subprocess.run(['ffmpeg', '-v','error','-xerror','-i',str(path), '-map','0:v:0',
        '-progress','pipe:1','-nostats','-f','null','-'], capture_output=True, text=True, timeout=60)
    values = dict(line.split('=',1) for line in decoded.stdout.splitlines() if '=' in line)
    probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],
        capture_output=True, text=True, check=True, timeout=30)
    declared = float(json.loads(probe.stdout)['format']['duration'])
    actual = int(values.get('out_time_us',0)) / 1_000_000
    return {'path':str(path.resolve()),'sha256':sha256_file(path),'declared_duration':declared,
        'decoded_video_duration':actual,'decoded_video_frames':int(values.get('frame',0)),
        'decoder_exit':decoded.returncode,'decoder_error':decoded.stderr[:1200],
        'complete':decoded.returncode == 0 and abs(declared-actual) <= .25 and values.get('progress') == 'end'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--quarantine-incomplete', action='store_true')
    parser.add_argument('paths',nargs='+')
    args=parser.parse_args()
    bins=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH']=str(bins)+os.pathsep+os.environ['PATH']
    rows=[audit(Path(p)) for p in args.paths]
    if args.quarantine_incomplete:
        workspace_data=(Path.cwd()/'data').resolve()
        for row in rows:
            if row['complete']:
                continue
            path=Path(row['path']).resolve()
            if not path.is_relative_to(workspace_data) or path.parent.name != 'videos':
                raise RuntimeError('Only an incomplete received source inside workspace data/videos may be quarantined')
            root=path.parent.parent
            archive=root/'incomplete-reception'
            archive.mkdir(exist_ok=True)
            old_files=[path, path.with_suffix('.reception.json'), *root.glob('decoded-*.jpg')]
            for old in old_files:
                if old.exists():
                    dest=archive/old.name
                    if dest.exists():
                        raise RuntimeError('Preserved incomplete reception must not be overwritten')
                    old.replace(dest)
            row['quarantined_path']=str(archive/path.name)
            _atomic_json(root/'incomplete-reception-audit.json', row)
    _atomic_json(Path(args.output),{'audited_at':'2026-10-11','method':'actual_video_decode_endpoint','sources':rows})
    print(json.dumps(rows,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
