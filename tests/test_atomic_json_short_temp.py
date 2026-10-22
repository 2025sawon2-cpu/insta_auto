import json
import tempfile
from pathlib import Path
import pytest
from hotpost import editing_adapter as adapter


def test_atomic_write_short_temp_and_failed_replace_cleanup(monkeypatch):
    stage = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='a', dir=stage) as directory:
        root = Path(directory)
        # Exercise a long destination name without extending the temporary name.
        target = root / ('destination' * 5 + '.json')
        adapter._atomic_json(target, {'original': '원본'})
        before = target.read_bytes()
        actual_replace = adapter.os.replace
        seen = []
        def fail(source, destination):
            source = Path(source)
            seen.append(source)
            assert source.parent == target.parent
            assert len(source.name) < 20
            assert Path(destination) == target
            assert target.read_bytes() == before
            assert json.loads(source.read_text('utf-8')) == {'next': True}
            raise PermissionError('busy')
        monkeypatch.setattr(adapter.os, 'replace', fail)
        with pytest.raises(PermissionError, match='busy'):
            adapter._atomic_json(target, {'next': True})
        assert len(seen) == 4
        assert target.read_bytes() == before
        assert all(not path.exists() for path in seen)
        monkeypatch.setattr(adapter.os, 'replace', actual_replace)
        adapter._atomic_json(target, {'next': True})
        assert json.loads(target.read_text('utf-8')) == {'next': True}
        assert list(root.iterdir()) == [target]
