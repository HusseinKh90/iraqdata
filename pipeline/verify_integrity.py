"""
pipeline.verify_integrity
=========================
Checks that a checkout's data files are byte-exact: every line of
each release's checksums.sha256, every datapackage.json resource's bytes and hash, and every
raw-manifest entry.

    python pipeline/verify_integrity.py [--release DIR ...] [--skip-raw]

Files are read in binary mode only; nothing is newline-normalised. Exit codes: 0 everything
matches, 1 one or more mismatches, 2 usage error or an unreadable checksum, descriptor or manifest.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "pipeline"))

import yaml  # noqa: E402

import raw_audit  # noqa: E402

DATA_SUFFIXES = {".csv", ".parquet"}


class UnreadableError(Exception):
    """A checksum list, descriptor or manifest that cannot be read or parsed."""


def sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _show(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def read_checksums(release_dir: Path) -> List[Tuple[str, str]]:
    """(hex digest, relative path) per line of <release>/checksums.sha256."""
    path = release_dir / "checksums.sha256"
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UnreadableError(f"{_show(path)}: {exc}") from exc
    entries = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        digest, sep, name = line.rstrip("\r").partition("  ")
        if not sep or len(digest) != 64:
            raise UnreadableError(f"{_show(path)}:{n}: not '<sha256>  <path>': {line!r}")
        entries.append((digest.lower(), name))
    return entries


def check_release(release_dir: Path) -> Tuple[List[str], int, int]:
    """Problem lines, number of data files checked, number of descriptors checked."""
    problems: List[str] = []
    listed = read_checksums(release_dir)
    for digest, name in listed:
        path = release_dir / name
        if not path.is_file():
            problems.append(f"MISSING             {_show(path)}")
            continue
        actual = sha256_bytes(path)
        if actual != digest:
            problems.append(f"MISMATCH checksum   {_show(path)}  expected {digest[:8]}…  actual {actual[:8]}…")
    names = {name for _, name in listed}
    for path in sorted(p for p in release_dir.rglob("*") if p.is_file() and p.suffix in DATA_SUFFIXES):
        if path.relative_to(release_dir).as_posix() not in names:
            problems.append(f"UNLISTED            {_show(path)}")

    descriptors = 0
    descriptor_path = release_dir / "datapackage.json"
    if descriptor_path.exists():
        try:
            descriptor = json.loads(descriptor_path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UnreadableError(f"{_show(descriptor_path)}: {exc}") from exc
        descriptors = 1
        for resource in descriptor.get("resources", []):
            path = release_dir / resource["path"]
            if not path.is_file():
                if resource["path"] not in names:  # already reported when listed
                    problems.append(f"MISSING             {_show(path)}")
                continue
            size = path.stat().st_size
            if resource.get("bytes") != size:
                problems.append(f"MISMATCH bytes      {_show(path)}  expected {resource.get('bytes')}  actual {size}")
            expected = str(resource.get("hash", "")).removeprefix("sha256:")
            actual = sha256_bytes(path)
            if expected != actual:
                problems.append(f"MISMATCH hash       {_show(path)}  expected {expected[:8]}…  actual {actual[:8]}…")
    return problems, len(listed), descriptors


def check_raw() -> Tuple[List[str], int]:
    """Problem lines from the raw-manifest check, and the number of manifest entries."""
    try:
        manifest = raw_audit.load_manifest()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise UnreadableError(f"{_show(raw_audit.MANIFEST_PATH)}: {exc}") from exc
    problems = []
    for d in raw_audit.check_manifest(manifest):
        if d.kind == "changed":
            problems.append(f"MISMATCH manifest   {d.path}  {d.detail}")
        else:
            problems.append(f"{d.kind.upper():<20}{d.path}  {d.detail}")
    return problems, len(manifest.get("files", []))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify release checksums, descriptors and the raw manifest byte-exactly.")
    parser.add_argument("--release", action="append", type=Path, metavar="DIR",
                        help="release folder to check (repeatable; default: every release/data-*/)")
    parser.add_argument("--skip-raw", action="store_true", help="skip the raw-manifest check")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    releases = args.release or sorted(p for p in (repo_root / "release").glob("data-*") if p.is_dir())

    problems: List[str] = []
    files = descriptors = raw_files = 0
    try:
        for release_dir in releases:
            if not release_dir.is_dir():
                print(f"{release_dir}: not a release folder")
                return 2
            found, n_files, n_desc = check_release(release_dir)
            problems += found
            files += n_files
            descriptors += n_desc
        if not args.skip_raw:
            found, raw_files = check_raw()
            problems += found
    except UnreadableError as exc:
        print(f"UNREADABLE {exc}")
        return 2

    for line in problems:
        print(line)
    if problems:
        print(f"FAILED: {len(problems)} mismatch(es)")
        return 1
    raw_part = "" if args.skip_raw else f", {raw_files} raw files"
    print(f"OK: {files} release files, {descriptors} descriptors{raw_part}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
