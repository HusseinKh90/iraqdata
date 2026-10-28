"""
pipeline.verify_fetchers
========================
Runs each automatic fetcher once against its live site and records what came back. Run by hand; the test suite never does.

    python pipeline/verify_fetchers.py [--sources ID ...]

Each fetcher runs against a throwaway copy of pipeline/raw and of the raw manifest, so nothing in
the repository's raw archive changes. Every request goes through downloads.polite_get as in the
weekly check (robots.txt, pacing, User-Agent, TLS, retries, size caps, content checks).

The results go to pipeline/metadata/fetcher_verification.yaml, one entry per source: the date,
`verified` or `failed`, the reason, and each response (requested and final URL, status, content
type, size, SHA-256). Entries for sources not run this time are kept. Exit status 0 when every
source run was verified, 1 otherwise.
"""

import argparse
import datetime
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root / "pipeline" / "parsers"))
sys.path.insert(0, str(repo_root / "pipeline"))

import yaml  # noqa: E402

import downloads  # noqa: E402
import fetchers  # noqa: E402
import validate  # noqa: E402

RAW_DIR = repo_root / "pipeline" / "raw"
MANIFEST = repo_root / "pipeline" / "metadata" / "raw_manifest.yaml"
RECORD = repo_root / "pipeline" / "metadata" / "fetcher_verification.yaml"


def _recording_get(log: List[dict]):
    real = downloads.polite_get

    def get(url, **kwargs):
        resp = real(url, **kwargs)
        content = resp.content or b""
        log.append({"url": url, "final_url": getattr(resp, "url", url), "status": resp.status_code,
                    "content_type": (getattr(resp, "headers", {}) or {}).get("Content-Type", ""),
                    "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        return resp
    return get


def verify(source_ids: Sequence[str], today: datetime.date, raw_dir: Path = RAW_DIR,
           manifest: Path = MANIFEST, fetcher_table: Optional[Dict] = None) -> List[dict]:
    """Run each fetcher against a temporary copy of raw_dir; return one record per source."""
    table = fetcher_table or fetchers.FETCHERS
    records = []
    with tempfile.TemporaryDirectory(prefix="iraqdata_verify_") as tmp:
        raw_copy, manifest_copy = Path(tmp) / "raw", Path(tmp) / "raw_manifest.yaml"
        shutil.copytree(raw_dir, raw_copy)
        shutil.copyfile(manifest, manifest_copy)
        for sid in source_ids:
            log: List[dict] = []
            original = downloads.polite_get
            downloads.polite_get = _recording_get(log)
            try:
                saved = table[sid](raw_copy, today, manifest_copy)
                status, reason = "verified", ("new release" if saved else "no change since the archived file")
            except Exception as exc:  # recorded, never raised: one failing site must not stop the others
                status, reason = "failed", f"{type(exc).__name__}: {exc}"
            finally:
                downloads.polite_get = original
            records.append({"source": sid, "checked": today.isoformat(), "status": status, "reason": reason,
                            "responses": log})
            print(f"[{status.upper()}] {sid}: {reason}")
    return records


def write_record(records: List[dict], path: Path = RECORD) -> None:
    existing = {}
    if path.exists():
        existing = {r["source"]: r for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("sources", [])}
    existing.update({r["source"]: r for r in records})
    header = ("# Live verification of the update check's fetchers.\n"
              "# Written by pipeline/verify_fetchers.py; do not edit by hand.\n")
    body = yaml.safe_dump({"sources": [existing[k] for k in sorted(existing)]}, sort_keys=False, allow_unicode=True,
                          width=120)
    path.write_text(header + body, encoding="utf-8", newline="\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run every automatic fetcher against its live site once.")
    parser.add_argument("--sources", nargs="+", default=None, help="Only these source ids.")
    args = parser.parse_args(argv)
    schedule = validate.load_update_schedule()
    auto = [s["id"] for s in schedule["sources"] if s["fetch"] == "auto"]
    chosen = [s for s in auto if not args.sources or s in args.sources]
    unknown = sorted(set(args.sources or []) - set(auto))
    if unknown:
        parser.error(f"not automatic sources: {unknown}")
    records = verify(chosen, datetime.datetime.now(datetime.timezone.utc).date())
    write_record(records)
    print(f"Wrote {RECORD.relative_to(repo_root).as_posix()}")
    return 0 if all(r["status"] == "verified" for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
