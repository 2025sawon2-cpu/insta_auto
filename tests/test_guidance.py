import json
from pathlib import Path
import tempfile
import unittest

from tools.check_guidance import check


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'docs').mkdir()
        (self.root / 'docs/rules.md').write_text('# Rules\n', encoding='utf-8')
        (self.root / 'docs/guidance.json').write_text(json.dumps({
            'documents': ['AGENTS.md'],
            'required_routes': ['docs/rules.md'],
            'forbidden_root_phrases': ['retired-command'],
        }), encoding='utf-8')
        self.agents = self.root / 'AGENTS.md'
        self.agents.write_text('[Rules](docs/rules.md)\n', encoding='utf-8')

    def test_valid_routes_pass(self):
        self.assertEqual(check(self.root), [])

    def test_large_documents_still_check_links(self):
        self.agents.write_text(self.agents.read_text() + '가' * 5000, encoding='utf-8')
        workflow = self.root / 'docs/WORKFLOW.md'
        workflow.write_text('[Rules](rules.md)\n' + '가' * 5000, encoding='utf-8')
        config = self.root / 'docs/guidance.json'
        settings = json.loads(config.read_text(encoding='utf-8'))
        settings['documents'].append('docs/WORKFLOW.md')
        config.write_text(json.dumps(settings), encoding='utf-8')
        self.assertEqual(check(self.root), [])
        workflow.write_text('[Missing](missing.md)\n' + '가' * 5000, encoding='utf-8')
        self.assertTrue(any('broken/local-only link' in error for error in check(self.root)))

    def test_deleted_original_is_reported(self):
        (self.root / 'docs/rules.md').unlink()
        self.assertTrue(any('broken/local-only' in error for error in check(self.root)))

    def test_missing_required_route_is_reported(self):
        self.agents.write_text('# Only a summary', encoding='utf-8')
        self.assertTrue(any('required route missing' in error for error in check(self.root)))

    def test_retired_instruction_is_reported(self):
        self.agents.write_text(self.agents.read_text() + 'retired-command', encoding='utf-8')
        self.assertTrue(any('retired instruction' in error for error in check(self.root)))


if __name__ == '__main__':
    unittest.main()
