import argparse
from collections import defaultdict
import json
import time
import numpy as np
from pinyin import ROOT
from ranking import Scorer

def evaluate():
    model=Scorer(ROOT/"model")
    results={}
    for window in (32,64,128):
        counts=defaultdict(lambda:dict(n=0,pool=0,rime=0,model=0,empty=0,fallback=0))
        times=[]
        with (ROOT/"data/samples.jsonl").open(encoding="utf8") as f:
            for line in f:
                r=json.loads(line)
                if r["split"]!="test":
                    continue
                pool=r["candidates"]
                started=time.perf_counter()
                first=int(np.argmax(model.scores(r["context"],pool,window))) if pool else -1
                took=(time.perf_counter()-started)*1000
                times.append(took)
                if took>20 and pool:
                    first=0
                empty=int(np.argmax(model.scores("",pool,window))) if pool else -1
                groups=["all",r["kind"],r["source"],"length"+str(len(r["parts"])),
                    "with_context" if r["context"] else "no_context"]
                for group in groups:
                    c=counts[group]
                    c["n"]+=1
                    c["pool"]+=int(r["status"]=="in_pool")
                    c["rime"]+=int(r["rank"]==1)
                    c["model"]+=int(first>=0 and pool[first]==r["target"])
                    c["empty"]+=int(empty>=0 and pool[empty]==r["target"])
                    c["fallback"]+=int(took>20)
        results[window]=dict(groups=dict(counts),p50_ms=float(np.percentile(times,50)),
                            p95_ms=float(np.percentile(times,95)),p99_ms=float(np.percentile(times,99)))
        print(window,dict(counts["initial"]),results[window]["p95_ms"],flush=True)
        (ROOT/"reports/metrics.json").write_text(json.dumps(results,indent=2),encoding="utf8")

if __name__=="__main__":
    evaluate()
