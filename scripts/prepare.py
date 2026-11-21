"""Assemble the shared directory, the reading index, and the replay fixture."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import re
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
ICE = ROOT / "vendor/rime-ice-927e1cf1d3eeb9bf4be85e3f684dba4dd485b6f6"
SHARED = ROOT / "artifacts/shared"

def prepare():
    shutil.copytree(ROOT / "vendor/stock/data", SHARED, dirs_exist_ok=True)
    shutil.copytree(ICE, SHARED, dirs_exist_ok=True)
    (SHARED / "default.custom.yaml").write_text('patch:\n  schema_list:\n    - schema: rime_ice\n', encoding="utf-8")
    db_path = ROOT / "artifacts/readings.sqlite"
    temp = db_path.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    db = sqlite3.connect(temp)
    db.execute("CREATE TABLE readings(word TEXT, code TEXT, PRIMARY KEY(word,code)) WITHOUT ROWID")
    syllables = set()
    for table in ["8105", "base", "ext", "tencent", "others"]:
        with (ICE / f"cn_dicts/{table}.dict.yaml").open(encoding="utf-8-sig") as f:
            for line in f:
                if line.strip() == "...":
                    break
            batch = []
            for line in f:
                fields = line.rstrip().split("\t")
                if len(fields) < 2 or not 1 <= len(fields[0]) <= 4:
                    continue
                word, code = fields[:2]
                codes = code.split()
                if len(codes) != len(word) or not re.fullmatch("[a-z]+(?: [a-z]+)*", code):
                    continue
                batch.append((word, code))
                syllables.update(codes)
                if len(batch) >= 5000:
                    db.executemany("INSERT OR IGNORE INTO readings VALUES(?,?)", batch)
                    batch.clear()
            db.executemany("INSERT OR IGNORE INTO readings VALUES(?,?)", batch)
    db.commit()
    db.close()
    temp.replace(db_path)
    (ROOT/"artifacts/syllables.json").write_text(json.dumps(sorted(syllables)), encoding="utf-8")
    print(len(syllables), "syllables", flush=True)

if __name__ == "__main__":
    prepare()
