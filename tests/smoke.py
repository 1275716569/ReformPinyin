import json
import random
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from engine import Engine
from ranking import Scorer
from pinyin import ROOT,parse
from learning import database,write_sample,update,load_head,split_examples

def run():
    with tempfile.TemporaryDirectory() as tmp:
        engine=Engine(Path(tmp),Scorer(ROOT/"model"))
        measures=[]
        for raw,length in [("quan",1),("xian",1),("xi'an",2),("xa",2),("qy",2),("quany",2),("qyi",2),("ch'sh",2),("zgr",3),("zgyd",4),("womingtianshangban",5)]:
            t=time.perf_counter()
            engine.begin(raw)
            page=engine.page(0)
            measures.append((raw,page,round((time.perf_counter()-t)*1000,2)))
            assert page,(raw,page)
            if length<=4:
                assert all(len(w)==length for w in page),page
            if raw in ("xi'an","xa"):
                engine.extend(float("inf"))
                assert "西安" in [w for w,i in engine.visible]
        engine.begin("qy")
        engine.page(5)
        target=engine.visible[26][0]
        assert engine.choose(26)==target
        assert engine.history==target
        engine.jobs.join()
        event=json.loads(engine.db.execute("SELECT sample FROM events ORDER BY id DESC LIMIT 1").fetchone()[0])
        assert event["coverage"]=="tail" and event["weight"]==3
        engine.reset()
        assert engine.history==""
        engine.begin("quan")
        first=engine.choose(0)
        assert first
        engine.jobs.join()
        assert json.loads(engine.db.execute("SELECT sample FROM events ORDER BY id DESC LIMIT 1").fetchone()[0])["weight"]==1
        engine.begin("qy")
        assert engine.history.endswith(first)
        assert engine.choose(0)
        engine.jobs.join()
        recent=json.loads(engine.db.execute("SELECT sample FROM events ORDER BY id DESC LIMIT 1").fetchone()[0])
        assert recent["context"].endswith(first),recent["context"]
        engine.close()
        db=database(Path(tmp))
        train,valid=split_examples(list(range(10)),random.Random(5))
        assert len(train)==8 and len(valid)==2
        assert set(train).isdisjoint(valid) and set(train+valid)==set(range(10))
        assert 9 in train
        fake=dict(model="test",scores=[.2,0],pool=["甲","乙"],chosen="乙",kind="initial",weight=3)
        for _ in range(500):
            write_sample(db,fake)
        assert not update(db,"test",idle=lambda:1)
        assert update(db,"test",idle=lambda:301)
        assert load_head(db,"test")["乙"]>0
        assert not update(db,"test",idle=lambda:301)
        manual_db=database(Path(tmp)/"manual")
        for _ in range(10):
            write_sample(manual_db,fake)
        manual_db.execute("INSERT INTO state VALUES(?,?)",
                          ("cursor:test",json.dumps([999,0.])))
        messages=[]
        assert update(manual_db,"test",manual=True,report=messages.append)
        assert "训练 8 条，随机留出验证 2 条" in messages[-1],messages[-1]
        assert load_head(manual_db,"test")["乙"]>0
        cursor=json.loads(manual_db.execute(
            "SELECT value FROM state WHERE key='cursor:test'").fetchone()[0])[0]
        assert cursor==999
        manual_db.close()
        db.close()
        (ROOT/"reports/smoke.json").write_text(json.dumps(measures,ensure_ascii=False,indent=2),encoding="utf8")
        print("candidate, commit, tail, reset, sample weighting and idle update checks passed")
if __name__=="__main__":
    run()
