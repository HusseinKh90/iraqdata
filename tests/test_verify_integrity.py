"""
pipeline/verify_integrity.py.

Fixture releases are built under tmp_path; every file is written and read as bytes.
"""

import hashlib
import json

import pytest

import verify_integrity


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def release(tmp_path):
    rel = tmp_path / "data-test"
    rel.mkdir()
    files = {
        "a.csv": b"date,value\r\n2020,1.0\r\n",
        "a.parquet": b"PAR1 not really parquet PAR1",
    }
    lines, resources = [], []
    for name, data in files.items():
        (rel / name).write_bytes(data)
        lines.append(f"{_sha(data)}  {name}")
        resources.append({"path": name, "bytes": len(data), "hash": f"sha256:{_sha(data)}"})
    (rel / "checksums.sha256").write_bytes(("\n".join(lines) + "\n").encode())
    (rel / "datapackage.json").write_bytes(json.dumps({"resources": resources}).encode())
    return rel


def _run(capsys, *args):
    code = verify_integrity.main(["--skip-raw", *args])
    return code, capsys.readouterr().out


def test_matching_release_passes(release, capsys):
    code, out = _run(capsys, "--release", str(release))
    assert code == 0
    assert out.strip().splitlines()[-1].startswith("OK: 2 release files, 1 descriptors")


def test_flipped_byte_is_a_checksum_mismatch(release, capsys):
    data = bytearray((release / "a.csv").read_bytes())
    data[0] ^= 1
    (release / "a.csv").write_bytes(bytes(data))
    code, out = _run(capsys, "--release", str(release))
    assert code == 1
    assert "MISMATCH checksum" in out and "a.csv" in out
    assert out.strip().splitlines()[-1].startswith("FAILED:")


def test_line_ending_change_is_detected(release, capsys):
    (release / "a.csv").write_bytes((release / "a.csv").read_bytes().replace(b"\r\n", b"\n"))
    code, out = _run(capsys, "--release", str(release))
    assert code == 1
    assert "MISMATCH bytes" in out


def test_wrong_descriptor_bytes(release, capsys):
    meta = json.loads((release / "datapackage.json").read_bytes())
    meta["resources"][0]["bytes"] += 1
    (release / "datapackage.json").write_bytes(json.dumps(meta).encode())
    code, out = _run(capsys, "--release", str(release))
    assert code == 1
    assert "MISMATCH bytes" in out


def test_missing_listed_file(release, capsys):
    (release / "a.parquet").unlink()
    code, out = _run(capsys, "--release", str(release))
    assert code == 1
    assert "MISSING" in out and "a.parquet" in out


def test_unlisted_data_file(release, capsys):
    (release / "extra.csv").write_bytes(b"x\r\n")
    code, out = _run(capsys, "--release", str(release))
    assert code == 1
    assert "UNLISTED" in out and "extra.csv" in out


def test_unreadable_checksum_file_exits_2(release, capsys):
    (release / "checksums.sha256").write_bytes(b"not a checksum line\n")
    code, out = _run(capsys, "--release", str(release))
    assert code == 2
    assert "UNREADABLE" in out


def test_missing_release_folder_exits_2(tmp_path, capsys):
    code, _ = _run(capsys, "--release", str(tmp_path / "nope"))
    assert code == 2


def test_committed_checkout_verifies(capsys):
    """The repository's own release(s) and raw manifest verify byte-exactly."""
    code = verify_integrity.main([])
    out = capsys.readouterr().out
    assert code == 0, out
