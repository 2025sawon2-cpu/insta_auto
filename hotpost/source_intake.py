"""Candidate intake is not final-edit admission. Keep review-required footage."""
import hashlib
import json
from pathlib import Path


def downloaded_candidates(manifest_path):
    path=Path(manifest_path)
    root=path.parent.resolve()
    data=json.loads(path.read_text('utf8'));files=[]
    for row in data.get('candidates',[]):
        if not isinstance(row,dict) or not row.get('selected_for_zip'):continue
        relative=row.get('downloaded_file')
        if not isinstance(relative,str) or not relative:continue
        file=(root/relative).resolve()
        if not file.is_relative_to(root):raise ValueError('Candidate leaves its source job')
        if not file.is_file():continue
        if row.get('file_sha256') and hashlib.sha256(file.read_bytes()).hexdigest()!=row['file_sha256']:
            raise ValueError('Downloaded candidate SHA changed before review')
        files.append(file)
    return files
