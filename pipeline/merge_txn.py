"""
pipeline.merge_txn
==================
A merge that is all-or-nothing and can be recovered after a crash.

A merge rewrites several files: vintage histories, published tables and seed snapshots. Each new
file is first written next to its target as `<name>.new`. A journal, `.merge_journal.json` in the
merge's target folder, lists every file with the SHA-256 of its old version (or `absent`) and of
its new version. The files are then swapped in, histories first, then tables, then snapshots:
the target is renamed to `<name>.old` and `<name>.new` is renamed to the target. Finally the
`.old` files and the journal are deleted.

    staging     the journal lists the targets; `.new` files are being written
    committing  every `.new` file is written and hashed; targets are being swapped

An ordinary error rolls the merge back before it is raised. After a crash the journal remains, a
new merge refuses to start, and `recover()` (run_parsers.py --recover) finishes the merge
(committing, every new version present) or undoes it (staging, or a new version missing). It
never guesses: a file matching neither its old nor its new hash, or an unreadable journal, stops
it with RecoveryError, and the maintainer restores from backup.

The new bytes come from `DataFrame.to_parquet(path, index=False)`, the writer used before this
module, so a successful merge writes exactly the files it wrote before.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, List, Optional, Tuple

JOURNAL = ".merge_journal.json"
ORDER = ("history", "table", "snapshot")  # histories before tables
ABSENT = "absent"


class MergeInterrupted(RuntimeError):
    """A journal from an interrupted merge exists; run_parsers.py --recover must run first."""


class RecoveryError(RuntimeError):
    """The interrupted merge cannot be finished or undone safely."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ABSENT


def _new(path: Path) -> Path:
    return path.with_name(path.name + ".new")


def _old(path: Path) -> Path:
    return path.with_name(path.name + ".old")


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class Transaction:
    """
    Collect the new files of one merge with add(), then commit() them.
    `_hook(step)` is called after every step (tests inject crashes and errors there).
    """

    def __init__(self, journal_dir: Path, vintage: str, _hook: Optional[Callable[[str], None]] = None):
        self.journal_dir = Path(journal_dir)
        self.journal = self.journal_dir / JOURNAL
        self.vintage = vintage
        self.files: List[Tuple[str, Path, object]] = []
        self._hook = _hook or (lambda step: None)

    def add(self, kind: str, target: Path, df) -> None:
        if kind not in ORDER:
            raise ValueError(f"Unknown file kind {kind!r}; expected one of {ORDER}")
        self.files.append((kind, Path(target), df))

    def _label(self, kind: str, target: Path) -> str:
        return f"{kind}:{target.name}"

    def _rel(self, path: Path) -> str:
        return Path(os.path.relpath(path, self.journal_dir)).as_posix()

    def commit(self) -> int:
        """Write every file, histories first. Returns the number of files written."""
        if self.journal.exists():
            raise MergeInterrupted(
                f"An interrupted merge left {self.journal}; run `python pipeline/run_parsers.py --recover` first.")
        if not self.files:
            return 0
        files = sorted(self.files, key=lambda f: ORDER.index(f[0]))  # stable within a kind
        entries = [{"kind": kind, "target": self._rel(target), "old_sha256": _sha256(target)}
                   for kind, target, _ in files]
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        record = {"vintage": self.vintage, "state": "staging", "files": entries}
        _write_json(self.journal, record)
        try:
            for (kind, target, df), entry in zip(files, entries):
                target.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(_new(target), index=False)
                entry["new_sha256"] = _sha256(_new(target))
                self._hook(f"stage {self._label(kind, target)}")
            record["state"] = "committing"
            _write_json(self.journal, record)
            self._hook("journal")
            for (kind, target, _), entry in zip(files, entries):
                if target.exists():
                    os.replace(target, _old(target))
                    self._hook(f"commit old {self._label(kind, target)}")
                os.replace(_new(target), target)
                self._hook(f"commit new {self._label(kind, target)}")
        except Exception:
            _undo(self.journal_dir, self._read_or(record))
            raise
        _finish(self.journal_dir, record, self._hook)
        return len(files)

    def _read_or(self, record: dict) -> dict:
        try:
            return json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return record


def _finish(journal_dir: Path, record: dict, hook: Callable[[str], None] = lambda step: None) -> None:
    """Delete the `.old` and leftover `.new` files, then the journal."""
    for entry in record["files"]:
        target = journal_dir / entry["target"]
        for leftover in (_old(target), _new(target)):
            if leftover.exists():
                leftover.unlink()
        hook(f"finish {entry['kind']}:{target.name}")
    (journal_dir / JOURNAL).unlink()


def _state(journal_dir: Path, entry: dict) -> dict:
    target = journal_dir / entry["target"]
    return {"target": target, "now": _sha256(target), "new": _sha256(_new(target)), "old": _sha256(_old(target)),
            "want_old": entry["old_sha256"], "want_new": entry.get("new_sha256")}


def _can_forward(s: dict) -> bool:
    return s["want_new"] is not None and s["want_new"] in (s["now"], s["new"])


def _can_back(s: dict) -> bool:
    if s["want_old"] == ABSENT:
        return s["now"] in (ABSENT, s["want_new"]) or s["want_new"] is None
    return s["want_old"] in (s["now"], s["old"])


def _undo(journal_dir: Path, record: dict) -> None:
    """Put every old version back and delete the new ones and the journal."""
    states = [_state(journal_dir, e) for e in record["files"]]
    _check(states, _can_back, "undo")
    for s in states:
        target = s["target"]
        if s["want_old"] == ABSENT:
            if target.exists():
                target.unlink()
        elif s["now"] != s["want_old"]:
            os.replace(_old(target), target)
    _finish(journal_dir, record)


def _check(states, possible, action: str) -> None:
    unknown = [s for s in states if s["now"] not in (ABSENT, s["want_old"], s["want_new"])]
    blocked = unknown or [s for s in states if not possible(s)]
    if blocked:
        names = ", ".join(str(s["target"]) for s in blocked)
        raise RecoveryError(
            f"Cannot {action} the interrupted merge safely: {names} match neither their published nor their "
            "new version. Nothing was changed; restore from backup (these files, then delete the journal).")


def recover(journal_dir: Path) -> str:
    """
    Finish or undo an interrupted merge whose journal is in `journal_dir`. Returns
    "rolled forward", "rolled back" or "nothing to recover"; raises RecoveryError when neither
    is safe.
    """
    journal = Path(journal_dir) / JOURNAL
    if not journal.exists():
        return "nothing to recover"
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
        entries = record["files"]
        for e in entries:
            e["target"], e["old_sha256"]  # noqa: B018 (required fields)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryError(f"The merge journal {journal} cannot be read ({exc}). Nothing was changed; "
                            "restore from backup (the data folders, then delete the journal).") from exc
    states = [_state(Path(journal_dir), e) for e in entries]
    if record.get("state") == "committing" and all(_can_forward(s) for s in states):
        _check(states, _can_forward, "finish")
        for s in states:
            if s["now"] != s["want_new"]:
                os.replace(_new(s["target"]), s["target"])
        _finish(Path(journal_dir), record)
        return "rolled forward"
    _undo(Path(journal_dir), record)
    return "rolled back"
