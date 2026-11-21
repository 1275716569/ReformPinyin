import json
import re
import sqlite3
import subprocess
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(os.environ.get("REFORM_ROOT",Path(__file__).resolve().parents[1]))
INITIALS = set("bcdfghjklmnpqrstvwxyz") | {"zh","ch","sh"}
SYLLABLES = set(json.loads((ROOT/"artifacts/syllables.json").read_text()))
VALID = INITIALS | SYLLABLES

@lru_cache(32768)
def segment(piece):
    if not piece:
        return ()
    if piece in VALID:
        return (piece,)
    choices = []
    for size in range(1, min(6,len(piece))+1):
        first = piece[:size]
        if first in VALID:
            rest = segment(piece[size:])
            if rest is not None:
                choices.append((first,) + rest)
    return min(choices, key=lambda p: (len(p), -sum(s in SYLLABLES for s in p),
                                       tuple(-len(s) for s in p)), default=None)

@lru_cache(32768)
def parse(raw):
    if not re.fullmatch("[a-z]+(?:'[a-z]+)*",raw) or len(raw)>96:
        return ()
    groups = [segment(p) for p in raw.split("'")]
    return tuple(s for group in groups for s in group) if all(groups) else ()

def matches(parts, reading):
    full = reading.split()
    return len(parts)==len(full) and all(s==r or ((len(s)==1 or s in INITIALS) and r.startswith(s))
                                          for s,r in zip(parts,full))

def spellings(reading):
    tokens = reading.split()
    initials = [s[0] for s in tokens]
    proposals = [("full","".join(tokens)),("initial","".join(initials))]
    if len(tokens)>1:
        proposals.append(("full","'".join(tokens)))
        for i in range(len(tokens)):
            proposals.append(("mixed","".join(t if j==i else initials[j] for j,t in enumerate(tokens))))
    extended = [t[:2] if t[:2] in ("zh","ch","sh") else t[0] for t in tokens]
    if extended != initials:
        proposals.extend([("initial","".join(extended)),("initial","'".join(extended))])
    seen = set()
    for kind,raw in proposals:
        if raw not in seen:
            yield kind,raw
            seen.add(raw)

def context(text, limit=128):
    pieces = re.findall(r"[^。！？!?\n]+[。！？!?\n]*",text)
    return "".join(pieces[-2:])[-limit:]

class Replay:
    def __init__(self,user=None):
        self.db = sqlite3.connect(ROOT/"artifacts/readings.sqlite")
        self.proc = subprocess.Popen([str(ROOT/"vendor/python32/python.exe"),str(ROOT/"src/rime_worker.py"),
            str(ROOT/"vendor/stock/rime.dll"),str(ROOT/"artifacts/shared"),str(user or ROOT/"artifacts/replay")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="ascii",
            creationflags=subprocess.CREATE_NO_WINDOW)
        if self.proc.stdout.readline().strip() != '{"ready":true}':
            raise RuntimeError("Rime failed to start")

    @lru_cache(100000)
    def readings(self,word):
        return tuple(v[0] for v in self.db.execute("SELECT code FROM readings WHERE word=?",(word,)))

    @lru_cache(8192)
    def candidates(self,raw):
        parts = parse(raw)
        self.proc.stdin.write(json.dumps({"input":raw})+"\n")
        self.proc.stdin.flush()
        words = json.loads(self.proc.stdout.readline())
        if not 1<=len(parts)<=4:
            return words
        return list(dict.fromkeys(w for w in words if len(w)==len(parts)
                    and any(matches(parts,r) for r in self.readings(w))))

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=20)
        self.db.close()
