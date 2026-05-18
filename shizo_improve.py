#!/usr/bin/env python3
"""
ShizoImprove Advanced – نسخهٔ نهایی پایدار و عاری از باگ
"""

import os
import shutil
import hashlib
import zipfile
import logging
import re
import fnmatch
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ShizoImprove")


class ShizoImprove:
    def __init__(self, root: str,
                 project: str,
                 output_base: Optional[str] = None,
                 *,
                 exclude_patterns: Optional[List[str]] = None,
                 date_format: str = "%Y-%m-%d",
                 dry_run: bool = False,
                 workers: int = 1,
                 compression: bool = False,
                 checksum: bool = True):
        self.root = Path(root).resolve()
        self.project = project
        if output_base is None:
            output_base = str(Path.home() / "ShizoImprove")
        self.output_base = Path(output_base).resolve()
        self.exclude_patterns = exclude_patterns or []
        self.date_format = date_format
        self.dry_run = dry_run
        self.workers = workers
        self.compression = compression
        self.checksum = checksum
        self.all_files: List[Path] = []
        logger.info(f"Scanning {self.root} ...")
        self._scan(self.root)
        logger.info(f"Found {len(self.all_files)} files total.")

    def _scan(self, path: Path):
        try:
            for entry in os.scandir(path):
                if any(re.search(pat, entry.name) for pat in self.exclude_patterns):
                    continue
                if entry.is_dir():
                    self._scan(Path(entry.path))
                elif entry.is_file():
                    self.all_files.append(Path(entry.path))
        except PermissionError:
            pass

    @staticmethod
    def _file_checksum(filepath: Path, algorithm: str = 'sha256') -> str:
        h = hashlib.new(algorithm)
        with filepath.open('rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def copy_file_if_newer(src: Path,
                           dest: Path,
                           checksum: bool = True,
                           dry_run: bool = False) -> bool:
        if not src.is_file():
            return False

        do_copy = False
        if not dest.exists():
            do_copy = True
        else:
            try:
                if src.stat().st_mtime > dest.stat().st_mtime:
                    if checksum:
                        if ShizoImprove._file_checksum(src) != ShizoImprove._file_checksum(dest):
                            do_copy = True
                    else:
                        do_copy = True
            except OSError:
                return False

        if do_copy:
            if dry_run:
                logger.info(f"[DRY RUN] Would copy {src} -> {dest}")
                return True
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                logger.debug(f"Copied {src} -> {dest}")
                return True
        return False

    def _is_improved_path(self, path: Path) -> bool:
        return "Improved" in path.parts

    def _build_dest(self, src: Path) -> Path:
        try:
            mtime = datetime.fromtimestamp(src.stat().st_mtime)
            date_str = mtime.strftime(self.date_format)
            rel = src.relative_to(self.root)
            return self.output_base / self.project / date_str / rel
        except Exception:
            return self.output_base / self.project / "unknown" / src.name

    def _copy_one(self, src: Path):
        dest = self._build_dest(src)
        self.copy_file_if_newer(src, dest,
                                checksum=self.checksum,
                                dry_run=self.dry_run)

    def _archive(self, predicate: Callable[[Path], bool]):
        files = [p for p in self.all_files
                 if not self._is_improved_path(p) and predicate(p)]
        logger.info(f"Archiving {len(files)} files ...")

        # در حالت dry_run فقط پیام چاپ کن و هیچ عملیات فایل‌سیستمی انجام نده
        if self.dry_run:
            for fp in files:
                dest = self._build_dest(fp)
                logger.info(f"[DRY RUN] Would copy {fp} -> {dest}")
            return

        if self.workers > 1:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {executor.submit(self._copy_one, fp): fp for fp in files}
                for future in as_completed(futures):
                    fp = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error {fp}: {e}")
        else:
            for fp in files:
                self._copy_one(fp)

        if self.compression:
            self._compress_output()

    def archive_by_project(self):
        self._archive(lambda p: self.project in str(p))

    def archive_by_extension(self, extension: str):
        ext = extension if extension.startswith('.') else f'.{extension}'
        self._archive(lambda p: p.suffix.lower() == ext.lower())

    def archive_by_glob(self, pattern: str):
        self._archive(lambda p: fnmatch.fnmatch(p.name, pattern))

    def archive_by_regex(self, pattern: str):
        regex = re.compile(pattern)
        self._archive(lambda p: regex.search(p.name) is not None)

    def _compress_output(self):
        project_dir = self.output_base / self.project
        if not project_dir.exists():
            return
        for date_dir in project_dir.iterdir():
            if date_dir.is_dir():
                zip_path = date_dir.with_suffix('.zip')
                logger.info(f"Compressing {date_dir} -> {zip_path}")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for file in date_dir.rglob('*'):
                        if file.is_file():
                            zf.write(file, file.relative_to(date_dir))
                shutil.rmtree(date_dir)

    def clear_cache(self):
        if self.dry_run:
            logger.info(f"[DRY RUN] Would clear {self.output_base}")
            return
        for item in self.output_base.iterdir():
            if item.name == "Improved":
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except OSError as e:
                logger.warning(f"Cannot remove {item}: {e}")

    def move_to_improved(self):
        improved_base = self.output_base / "Improved" / self.project
        for fp in self.all_files:
            if self._is_improved_path(fp) or self.project not in str(fp):
                continue
            rel = fp.relative_to(self.root)
            dest = improved_base / rel
            self.copy_file_if_newer(fp, dest,
                                    checksum=self.checksum,
                                    dry_run=self.dry_run)


def main():
    parser = argparse.ArgumentParser(
        description="ShizoImprove Advanced",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s /sdcard MyApp
  %(prog)s /sdcard MyApp --by-ext py
  %(prog)s /sdcard MyApp --glob '*.py'
  %(prog)s /sdcard MyApp --regex '^test_.*\\.py$'
  %(prog)s /sdcard MyApp --improved
  %(prog)s /sdcard MyApp --clear-cache --dry-run
  %(prog)s /sdcard MyApp --workers 4 --compression --checksum
        """
    )
    parser.add_argument("root", help="root path to scan")
    parser.add_argument("project", help="project name keyword")
    parser.add_argument("-o", "--output", default=None, help="output directory (default ~/ShizoImprove)")
    parser.add_argument("--by-ext", dest="extension", help="archive by extension")
    parser.add_argument("--glob", dest="glob_pattern", help="archive by glob pattern")
    parser.add_argument("--regex", dest="regex_pattern", help="archive by regex pattern")
    parser.add_argument("--improved", action="store_true", help="move to Improved folder")
    parser.add_argument("--clear-cache", action="store_true", help="clear output cache")
    parser.add_argument("--dry-run", action="store_true", help="print actions without executing")
    parser.add_argument("--workers", type=int, default=1, help="number of parallel workers")
    parser.add_argument("--compression", action="store_true", help="compress date folders to zip")
    parser.add_argument("--checksum", action="store_true", default=True, help="use SHA256 to avoid duplicate copies")
    parser.add_argument("--exclude", nargs="*", help=r"regex patterns to exclude (e.g. '\.git' '\.tmp$')")

    args = parser.parse_args()

    manager = ShizoImprove(
        root=args.root,
        project=args.project,
        output_base=args.output,
        exclude_patterns=args.exclude,
        dry_run=args.dry_run,
        workers=args.workers,
        compression=args.compression,
        checksum=args.checksum,
    )

    if args.clear_cache:
        manager.clear_cache()
    elif args.improved:
        manager.move_to_improved()
    elif args.extension:
        manager.archive_by_extension(args.extension)
    elif args.glob_pattern:
        manager.archive_by_glob(args.glob_pattern)
    elif args.regex_pattern:
        manager.archive_by_regex(args.regex_pattern)
    else:
        manager.archive_by_project()

    logger.info("Done.")


if __name__ == "__main__":
    main()
