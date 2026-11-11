"""Online SQLite snapshots; imaging data needs a separate storage backup policy."""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def backup_databases(sources: dict[str, Path], destination: Path, *, keep: int = 7) -> Path:
    if keep < 1:
        raise ValueError("Keep at least one backup.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pending = destination / f".pending-{stamp}"
    pending.mkdir(mode=0o700)
    try:
        for name, source in sources.items():
            if not source.is_file():
                raise FileNotFoundError(f"The {name} database is not initialized.")
            target = pending / f"{name}.sqlite3"
            with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
                with sqlite3.connect(target) as dst:
                    src.backup(dst)
                    if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError(f"The {name} snapshot failed integrity verification.")
            target.chmod(0o600)
        completed = destination / f"snapshot-{stamp}"
        pending.rename(completed)
    except Exception:
        shutil.rmtree(pending)
        raise
    for old in sorted(destination.glob("snapshot-*"), reverse=True)[keep:]:
        if old.is_dir():
            shutil.rmtree(old)
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path("/var/lib/clinagent/backups"))
    parser.add_argument("--keep", type=int, default=7)
    parser.add_argument("--interval-hours", type=float, default=0)
    args = parser.parse_args()
    sources = {
        "auth": Path(os.environ["CLINAGENT_AUTH_DB"]),
        "state": Path(os.environ["CLINAGENT_DATABASE_PATH"]),
    }
    while True:
        snapshot = backup_databases(sources, args.destination, keep=args.keep)
        print(f"SQLite backup verified: {snapshot.name}", flush=True)
        if args.interval_hours <= 0:
            return
        time.sleep(args.interval_hours * 3600)


if __name__ == "__main__":
    main()
