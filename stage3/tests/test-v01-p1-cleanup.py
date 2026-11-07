#!/usr/bin/env python3
"""限定清理范围，并复核保留的证据，不读取大体积 VCD。"""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('v01_p1_cleanup',ROOT/'scripts/cleanup-v01-p1-waves-20261026.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class CleanupTests(unittest.TestCase):
    def test_exact_five_old_files_only(self):
        self.assertEqual(len(M.TARGETS),5)
        self.assertTrue(all(Path(n).suffix=='.vcd' for n in M.TARGETS))
        self.assertTrue(all('operand-isolation' not in n and 'sew16' not in n and 'resumed' not in n for n in M.TARGETS))
        self.assertNotIn('stage2/waveform/isolation/before.vcd',M.TARGETS)

    def test_retained_actual_samples_and_images(self):
        proof=M.retained_evidence()
        self.assertEqual((proof['p1_comparisons'],proof['isolation_comparisons'],proof['functional_cases']),(3,3,8))

    def test_default_is_read_only(self):
        with patch('sys.argv',['cleanup']), patch.object(M,'protected_files') as protected, \
             patch.object(Path,'unlink') as unlink,contextlib.redirect_stdout(io.StringIO()):
            M.main()
            protected.assert_not_called();unlink.assert_not_called()

    def test_existing_journal_prevents_repeated_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Path(tmp)/'existing.json';journal.touch()
            with patch('sys.argv',['cleanup','--execute']),patch.object(M,'JOURNAL',journal), \
                 patch.object(Path,'unlink') as unlink,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError,'already has a journal'):M.main()
                unlink.assert_not_called()


if __name__=='__main__':unittest.main()
