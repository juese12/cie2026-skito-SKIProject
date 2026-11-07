#!/usr/bin/env python3
"""验证中文改名、注释边界与篡改拒绝，不运行处理器仿真。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('test_chinese_edition', ROOT/'scripts/chinese-edition.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class ChineseEditionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'project'
        (self.root/'manifest').mkdir(parents=True)
        self.data = {'documents': {}, 'code': {}}

    def save(self):
        (self.root/'manifest/chinese-edition-20261102.json').write_text(json.dumps(self.data))

    def entry(self, before, after, **fields):
        return dict(before_content=before, after_content=after,
                    before_sha256=hashlib.sha256(before.encode()).hexdigest(), **fields)

    def document(self):
        self.data['documents']['report.md'] = self.entry('# Original\n', '# 中文报告\n', new_path='报告.md')
        (self.root/'报告.md').write_text('# 中文报告\n')
        self.save()

    def code(self, after='# 中文说明\nvalue = "report.md"\n', **fields):
        before='# English explanation\nvalue = "report.md"\n'
        fields.setdefault('edit_kind', 'comments')
        self.data['code']['project/main.py'] = self.entry(before, after, **fields)
        (self.root/'main.py').write_text(after)
        self.save()
        return hashlib.sha256(before.encode()).hexdigest()

    def test_renamed_document_keeps_prior_identity(self):
        self.document()
        current, original, before=M.prior_view(self.root, self.root/'report.md')
        self.assertEqual(current, self.root/'报告.md')
        self.assertEqual(original, self.root/'report.md')
        self.assertEqual(before, b'# Original\n')
        self.assertFalse((self.root/'report.md').exists())

    def test_unrecorded_current_change_is_rejected(self):
        self.document()
        (self.root/'报告.md').write_text('# 改动后未登记\n')
        with self.assertRaisesRegex(ValueError, '当前文件'):
            M.prior_view(self.root, self.root/'report.md')

    def test_comment_translation_cannot_change_executable_statement(self):
        expected=self.code()
        self.assertTrue(M.matches_expected(self.root, self.root/'main.py', expected))
        self.data['code']['project/main.py']['after_content']='# 中文说明\nvalue = 99\n'
        (self.root/'main.py').write_text(self.data['code']['project/main.py']['after_content'])
        self.save()
        self.assertFalse(M.matches_expected(self.root, self.root/'main.py', expected))

    def test_document_path_replacement_is_limited_to_registered_names(self):
        self.document()
        expected=self.code('# 中文说明\nvalue = "报告.md"\n',
                           comment_edition='# 中文说明\nvalue = "report.md"\n',
                           path_replacements=[['report.md', '报告.md']],
                           edit_kind='comments_and_document_paths')
        self.assertTrue(M.matches_expected(self.root, self.root/'main.py', expected))
        self.data['code']['project/main.py']['path_replacements']=[['value', 'injected()']]
        self.save()
        self.assertFalse(M.matches_expected(self.root, self.root/'main.py', expected))

    def test_corrupted_prior_content_is_rejected(self):
        self.document()
        self.data['documents']['report.md']['before_content']='# Another original\n'
        self.save()
        with self.assertRaisesRegex(ValueError, '中文化前记录'):
            M.prior_view(self.root, self.root/'report.md')

    def test_hardware_cannot_claim_review_adapter_exception(self):
        expected=self.code('# 中文说明\nvalue = 99\n', edit_kind='review_compatibility')
        self.assertFalse(M.matches_expected(self.root, self.root/'main.py', expected))

    def test_reviewer_document_layer_preserves_prior_rename_chain(self):
        self.document()
        entry=self.entry('# 中文报告\n','# 交付结果\n')
        (self.root/'报告.md').write_text(entry['after_content'])
        (self.root/'manifest/reviewer-delivery-edition.json').write_text(json.dumps({'documents':{'报告.md':entry}}))
        self.assertEqual(M.prior_view(self.root,self.root/'report.md')[2],b'# Original\n')

    def test_reviewer_layer_rejects_unrecorded_changes(self):
        self.document()
        entry=self.entry('# 中文报告\n','# 交付结果\n')
        (self.root/'manifest/reviewer-delivery-edition.json').write_text(json.dumps({'documents':{'报告.md':entry}}))
        (self.root/'报告.md').write_text('# 未登记的变化\n')
        with self.assertRaisesRegex(ValueError,'当前交付稿'):
            M.prior_view(self.root,self.root/'report.md')


if __name__ == '__main__':
    unittest.main()
