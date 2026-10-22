"""Source-only imports with a receipt for the bytes executed in this process."""
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys


class SourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self,fullname):
        data=self.get_data(self.path)
        self.executed_sha256=hashlib.sha256(data).hexdigest()
        return self.source_to_code(data,self.path)

    def exec_module(self,module):
        super().exec_module(module)
        module.__hotpost_source_sha256__=self.executed_sha256


class SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if not fullname.startswith('hotpost.'):return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec and isinstance(spec.loader,importlib.machinery.SourceFileLoader):
            spec.loader=SourceLoader(fullname,spec.origin)
        return spec


def install():
    restore_missing_sources(Path(__file__).parent)
    if not any(isinstance(finder,SourceFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0,SourceFinder())


def restore_missing_sources(root):
    """Recover a crash between source handoff and no-clobber installation."""
    for journal in root.rglob('.*.repair-journal.json'):
        entry=json.loads(journal.read_text('utf8'))
        names=[entry['target'],entry['preserved']]
        if any(Path(name).name!=name or '/' in name or '\\' in name for name in names):
            raise RuntimeError('Invalid source handoff journal')
        target=journal.parent/entry['target'];preserved=journal.parent/entry['preserved']
        if target.exists():continue
        if not preserved.is_file() or hashlib.sha256(preserved.read_bytes()).hexdigest()!=entry['sha256']:
            raise RuntimeError('Interrupted source handoff SHA mismatch')
        try:os.link(preserved,target)
        except FileExistsError:pass
