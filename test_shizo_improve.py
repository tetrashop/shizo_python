#!/usr/bin/env python3
"""
Unit tests for ShizoImprove Advanced
"""

import unittest
import tempfile
import os
import time
import shutil
from pathlib import Path
from shizo_improve import ShizoImprove


class TestShizoImproveAdvanced(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        proj = self.root / "Projects" / "MyApp"
        proj.mkdir(parents=True)
        self.file1 = proj / "main.py"
        self.file2 = proj / "utils.py"
        self.file3 = self.root / "Other" / "readme.txt"
        self.file4 = proj / "test_app.py"
        self.file5 = self.root / "excluded" / "tmp.tmp"

        for f in [self.file1, self.file2, self.file3, self.file4, self.file5]:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("initial content")

        now = time.time()
        os.utime(self.file1, (now - 86400*2, now - 86400*2))
        os.utime(self.file2, (now - 86400,   now - 86400))
        os.utime(self.file4, (now - 3600,    now - 3600))

        # Use a dedicated temp output base for isolation
        self.output_base = Path(tempfile.mkdtemp(prefix="shizo_test_"))
        self.manager = ShizoImprove(
            str(self.root), "MyApp",
            output_base=str(self.output_base),
            exclude_patterns=[r'\.tmp$'],
            dry_run=False,
            workers=1,
            compression=False,
            checksum=True
        )

    def tearDown(self):
        self.temp_dir.cleanup()
        if self.output_base.exists():
            shutil.rmtree(self.output_base, ignore_errors=True)

    def test_scan_excludes_pattern(self):
        self.assertIn(self.file1, self.manager.all_files)
        self.assertIn(self.file2, self.manager.all_files)
        self.assertNotIn(self.file5, self.manager.all_files)

    def test_archive_by_project(self):
        self.manager.archive_by_project()
        out = self.output_base / "MyApp"
        files = [f.name for f in out.rglob("*") if f.is_file()]
        self.assertIn("main.py", files)
        self.assertIn("utils.py", files)
        self.assertNotIn("readme.txt", files)

    def test_archive_by_extension(self):
        self.manager.archive_by_extension("py")
        out = self.output_base / "MyApp"
        files = [f.name for f in out.rglob("*") if f.is_file()]
        self.assertIn("main.py", files)
        self.assertIn("utils.py", files)
        self.assertIn("test_app.py", files)
        self.assertNotIn("readme.txt", files)

    def test_archive_by_glob(self):
        self.manager.archive_by_glob("test_*.py")
        out = self.output_base / "MyApp"
        files = [f.name for f in out.rglob("*") if f.is_file()]
        self.assertIn("test_app.py", files)
        self.assertNotIn("main.py", files)

    def test_archive_by_regex(self):
        self.manager.archive_by_regex(r'^test_.*\.py$')
        out = self.output_base / "MyApp"
        files = [f.name for f in out.rglob("*") if f.is_file()]
        self.assertIn("test_app.py", files)
        self.assertNotIn("main.py", files)

    def test_dry_run(self):
        # Use a separate manager with dry_run=True and isolated output
        dry_output = Path(tempfile.mkdtemp(prefix="shizo_dry_"))
        dry_mgr = ShizoImprove(
            str(self.root), "MyApp",
            output_base=str(dry_output),
            dry_run=True,
            workers=1
        )
        dry_mgr.archive_by_project()
        out = dry_output / "MyApp"
        # No files should have been created
        self.assertFalse(out.exists(), "Dry-run should not create output directory")
        shutil.rmtree(dry_output, ignore_errors=True)

    def test_clear_cache(self):
        self.manager.archive_by_project()
        self.manager.clear_cache()
        out = self.output_base / "MyApp"
        self.assertFalse(out.exists())

    def test_move_to_improved(self):
        self.manager.move_to_improved()
        improved = self.output_base / "Improved" / "MyApp"
        files = [f.name for f in improved.rglob("*") if f.is_file()]
        self.assertIn("main.py", files)
        self.assertIn("utils.py", files)
        self.assertNotIn("readme.txt", files)

    def test_checksum_prevents_copy(self):
        src = self.root / "src.txt"
        dest = self.root / "dest.txt"
        src.write_text("same content")
        dest.write_text("same content")
        os.utime(src, (time.time() + 100, time.time() + 100))
        result = ShizoImprove.copy_file_if_newer(src, dest, checksum=True)
        self.assertFalse(result)

    def test_checksum_allows_copy_when_different(self):
        src = self.root / "src.txt"
        dest = self.root / "dest.txt"
        src.write_text("new content")
        dest.write_text("old content")
        os.utime(src, (time.time() + 100, time.time() + 100))
        result = ShizoImprove.copy_file_if_newer(src, dest, checksum=True)
        self.assertTrue(result)
        self.assertEqual(dest.read_text(), "new content")

    def test_compression(self):
        mgr = ShizoImprove(
            str(self.root), "MyApp",
            output_base=str(self.output_base),
            compression=True,
            workers=1
        )
        mgr.archive_by_project()
        proj = self.output_base / "MyApp"
        zips = list(proj.glob("*.zip"))
        self.assertGreater(len(zips), 0)

    def test_parallel_execution(self):
        mgr = ShizoImprove(
            str(self.root), "MyApp",
            output_base=str(self.output_base),
            workers=2
        )
        mgr.archive_by_project()
        out = self.output_base / "MyApp"
        files = [f.name for f in out.rglob("*") if f.is_file()]
        self.assertIn("main.py", files)


if __name__ == "__main__":
    unittest.main()
