"""Per-user, versioned candidate bias head fitted with weighted listwise loss."""
import ctypes
import json
import msvcrt
from pathlib import Path
import random
import sqlite3
import time
import numpy as np
from ranking import personalized

def database(folder):
    folder.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(folder/"learning.sqlite",timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, stamp REAL NOT NULL, sample TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT)")
    return db

def write_sample(db,event,replace=None):
    with db:
        if replace:
            db.execute("DELETE FROM events WHERE id=?",(replace,))
        return db.execute("INSERT INTO events(stamp,sample) VALUES(?,?)",(time.time(),json.dumps(event,ensure_ascii=False))).lastrowid

def idle_seconds():
    class Info(ctypes.Structure):
        _fields_=[("size",ctypes.c_uint32),("tick",ctypes.c_uint32)]
    i=Info(ctypes.sizeof(Info),0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(i)):
        return 0
    return ((ctypes.windll.kernel32.GetTickCount()-i.tick)&0xffffffff)/1000

def load_head(db,model):
    row=db.execute("SELECT value FROM state WHERE key=?",("head:"+model,)).fetchone()
    return json.loads(row[0]) if row else {}

def candidate_head(events,head):
    weights=head.copy()
    for epoch in range(3):
        for e in events:
            words=e["pool"]
            scores=personalized(np.array(e["scores"]),words,weights)
            probs=np.exp(scores-scores.max())
            probs/=probs.sum()
            probs[words.index(e["chosen"])]-=1
            for word,g in zip(words,probs):
                weights[word]=max(-3.,min(3.,weights.get(word,0.)*.9999-.035*e["weight"]*float(g)))
    return weights

def quality(events,head):
    return sum(e["pool"][np.argmax(personalized(np.array(e["scores"]),e["pool"],head))]==e["chosen"] for e in events)

def split_examples(examples,rng=None):
    shuffled=list(examples)
    (rng or random.SystemRandom()).shuffle(shuffled)
    validation_count=max(1,round(len(shuffled)*.2))
    return shuffled[validation_count:],shuffled[:validation_count]

def update(db,model,idle=idle_seconds,now=time.time,*,manual=False,report=lambda message: None):
    if not manual and idle()<300:
        return False
    # The OS releases this lock if either the control panel or the idle worker exits.
    path=Path(db.execute("PRAGMA database_list").fetchone()[2]).with_suffix(".train.lock")
    with path.open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            report("已有一轮训练在运行。")
            return False
        return _fit(db,model,idle,now,manual,report)

def _fit(db,model,idle,now,manual,report):
    cursor_key="cursor:"+model
    row=db.execute("SELECT value FROM state WHERE key=?",(cursor_key,)).fetchone()
    last,stamp=json.loads(row[0]) if row else (0,0.)
    if not manual and now()-stamp<86400:
        return False
    examples=[]
    query="SELECT id,sample FROM events" if manual else "SELECT id,sample FROM events WHERE id>? ORDER BY id"
    params=() if manual else (last,)
    for i,s in db.execute(query,params):
        e=json.loads(s)
        if e["model"]==model and e["chosen"] in e["pool"] and len(e["scores"])==len(e["pool"]):
            examples.append((i,e))
    minimum=2 if manual else 500
    if len(examples)<minimum:
        report(f"当前有 {len(examples)} 条新增有效选词，至少需要 {minimum} 条才能划分训练集和验证集。")
        return False
    old=load_head(db,model)
    train,valid=split_examples(examples)
    fresh=old
    for start in range(0,len(train),64):
        if not manual and idle()<300:
            return False
        fresh=candidate_head([e for _,e in train[start:start+64]],fresh)
    valid_events=[e for _,e in valid]
    simple=[e for e in valid_events if e["kind"]=="initial"]
    before,after=quality(valid_events,old),quality(valid_events,fresh)
    accept=after>before and quality(simple,fresh)>=quality(simple,old)
    if not manual and idle()<300:
        return False
    with db:
        if accept:
            for key,value in [("previous:"+model,old),("head:"+model,fresh)]:
                db.execute("INSERT OR REPLACE INTO state VALUES(?,?)",(key,json.dumps(value)))
        if accept or not manual:
            db.execute("INSERT OR REPLACE INTO state VALUES(?,?)",
                       (cursor_key,json.dumps([max(last,max(i for i,_ in examples)),now()])))
    result="已启用新权重" if accept else "保留现有权重"
    report(f"训练 {len(train)} 条，随机留出验证 {len(valid_events)} 条。首选命中 {before} → {after} 条。{result}。")
    return accept

