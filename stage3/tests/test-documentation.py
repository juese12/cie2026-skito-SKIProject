#!/usr/bin/env python3
"""用人工文档测试检查器，不进行硬件回归。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('documentation',
    Path(__file__).resolve().parents[2] / 'scripts/check-documentation.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'manifest').mkdir()
        self.old = self.root / 'historical.md'
        self.old.write_text('# Original evidence\n')
        self.new = self.root / 'README.md'
        self.new.write_text('# Index\n\n[Evidence](historical.md)\n')
        (self.root / 'manifest/document-consolidation-20261006.json').write_text(json.dumps({
            'protected_md': {'historical.md': hashlib.sha256(self.old.read_bytes()).hexdigest()}}))

    def test_valid_links_and_original_hash(self):
        self.assertEqual(M.check(self.root), {'markdown_files': 2, 'protected_documents': 1})

    def test_missing_link_rejected(self):
        self.new.write_text('[Gone](gone.md)\n')
        with self.assertRaisesRegex(AssertionError, 'missing local link'):
            M.check(self.root)

    def test_altered_original_rejected(self):
        self.old.write_text('# Rewritten evidence\n')
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root)

    def test_external_and_fragment_links_ignored(self):
        self.new.write_text('[Local](historical.md#section) [Site](https://example.org) [Here](#title)\n')
        self.assertEqual(M.check(self.root)['markdown_files'], 2)

    def test_unclosed_code_fence_rejected(self):
        self.new.write_text('```bash\ntrue\n')
        with self.assertRaisesRegex(AssertionError, 'unclosed code fence'):
            M.check(self.root)

    def test_trailing_whitespace_rejected(self):
        self.new.write_text('# Heading \n')
        with self.assertRaisesRegex(AssertionError, 'trailing whitespace'):
            M.check(self.root)

    def review_edition(self):
        before = self.old.read_text()
        self.old.write_text('# Reviewer edition\n')
        entry = {'original_content': before, 'review_content': self.old.read_text()}
        path = self.root / 'manifest/document-review-edition-20261020.json'
        path.write_text(json.dumps({'documents': {'historical.md': entry}}))
        return path

    def test_recorded_edition_requires_explicit_option(self):
        self.review_edition()
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root)
        self.assertEqual(M.check(self.root, review_edition=True)['protected_documents'], 1)

    def test_modified_review_text_rejected(self):
        self.review_edition()
        self.old.write_text('# Unapproved changes\n')
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def test_modified_original_archive_rejected(self):
        path = self.review_edition()
        data = json.loads(path.read_text())
        data['documents']['historical.md']['original_content'] = '# Changed source\n'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def test_non_document_cannot_use_review_exception(self):
        path = self.root / 'model.bin'
        path.write_bytes(b'original')
        expected = M.digest(path)
        path.write_bytes(b'changed')
        self.assertFalse(M.matches_recorded_file(self.root, path, expected, True))

    def version_prefix(self):
        prefix = '> Current version: [index](README.md)\n\n'
        before = self.old.read_bytes()
        path = self.root / 'manifest/document-version-entry-20261026.json'
        path.write_text(json.dumps({'documents': {'historical.md': {
            'prefix': prefix, 'prior_sha256': hashlib.sha256(before).hexdigest()}}}))
        self.old.write_bytes(prefix.encode() + before)
        return path

    def test_exact_original_prefix_requires_explicit_option(self):
        self.version_prefix()
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root)
        self.assertEqual(M.check(self.root, review_edition=True)['protected_documents'], 1)

    def test_prefix_preserves_recorded_review_chain(self):
        self.review_edition()
        self.version_prefix()
        self.assertEqual(M.check(self.root, review_edition=True)['protected_documents'], 1)

    def test_body_change_beneath_prefix_rejected(self):
        self.review_edition()
        self.version_prefix()
        self.old.write_text(self.old.read_text() + 'Changed evidence\n')
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def test_changed_prefix_rejected(self):
        self.version_prefix()
        self.old.write_text(self.old.read_text().replace('Current version', 'Unrecorded version'))
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def test_wrong_prior_hash_rejected(self):
        path = self.version_prefix()
        data = json.loads(path.read_text())
        data['documents']['historical.md']['prior_sha256'] = '0' * 64
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def editorial_edition(self):
        before = self.old.read_text()
        self.old.write_text('# Clean reviewer report\n')
        data = {'documents': {'historical.md': {
            'original_content': before, 'review_content': self.old.read_text(),
            'original_sha256': hashlib.sha256(before.encode()).hexdigest()}}}
        path = self.root / 'manifest/document-review-edition-20261101.json'
        path.write_text(json.dumps(data))
        return path

    def test_editorial_edition_is_explicit_and_preserves_old_chain(self):
        self.review_edition()
        self.version_prefix()
        self.editorial_edition()
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root)
        self.assertEqual(M.check(self.root, review_edition=True)['protected_documents'], 1)

    def test_editorial_text_tamper_rejected(self):
        self.editorial_edition()
        self.old.write_text('# Unrecorded change\n')
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def test_editorial_archive_tamper_rejected(self):
        path = self.editorial_edition()
        data = json.loads(path.read_text())
        data['documents']['historical.md']['original_content'] = '# Another original\n'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(AssertionError, 'protected document changed'):
            M.check(self.root, review_edition=True)

    def test_editorial_exception_stays_document_only(self):
        original = self.root / 'raw.log'
        original.write_text('original raw data\n')
        expected = M.digest(original)
        original.write_text('rewritten raw data\n')
        data = {'documents': {'raw.log': {
            'original_content': 'original raw data\n',
            'review_content': original.read_text(), 'original_sha256': expected}}}
        (self.root / 'manifest/document-review-edition-20261101.json').write_text(json.dumps(data))
        self.assertFalse(M.matches_recorded_file(self.root, original, expected, True))


if __name__ == '__main__':
    unittest.main()
