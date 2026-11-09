#!/usr/bin/env python3
"""
MMM Analytics Bot — Database Backup & Recovery Utility
Creates timestamped JSON and SQLite dumps of all operational records and customers.
"""

import os
import sys
import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import DB_PATH
from database import get_filtered_records, get_all_customers

def backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  MMM Analytics Bot — Zaxira Nusxa (Backup) Yaratish")
    print("=" * 60)

    # 1. JSON Dump
    records = get_filtered_records(limit=100000)
    customers = get_all_customers(limit=100000)

    dump_data = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(records),
        "total_customers": len(customers),
        "records": records,
        "customers": customers
    }

    json_path = backup_dir / f"mmm_backup_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, ensure_ascii=False, indent=2)

    print(f"✅ JSON zaxira yaratildi: {json_path}")
    print(f"   -> {len(records)} ta yozuv, {len(customers)} ta mijoz saqlandi.")

    # 2. SQLite File copy (if local database exists)
    if os.path.exists(DB_PATH):
        sqlite_copy_path = backup_dir / f"warehouse_backup_{timestamp}.db"
        shutil.copy2(DB_PATH, sqlite_copy_path)
        print(f"✅ SQLite fayli nusxalandi: {sqlite_copy_path}")

    print("=" * 60)

if __name__ == "__main__":
    backup()
