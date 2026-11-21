import json
import os
import queue
import threading
import time
from collections import OrderedDict
from pathlib import Path
import numpy as np
from pinyin import ROOT, Replay, context, matches, parse, SYLLABLES
from ranking import Scorer, personalized
from learning import database, load_head, write_sample

class Engine:
    def __init__(self,folder,scorer=None):
        self.replay=Replay(folder/"rime")
        self.folder=folder
        self.scorer=scorer
        self.jobs=queue.Queue()
        self.db=database(folder)
        self.writer=threading.Thread(target=self.persist,daemon=True)
        self.writer.start()
        self.head={}
        self.groups=OrderedDict()
        self.generation=-1
        self.reset()

    def persist(self):
        db=database(self.folder)
        while True:
            event=self.jobs.get()
            try:
                if event is None:
                    break
                write_sample(db,event)
            finally:
                self.jobs.task_done()
        db.close()

    def reset(self):
        self.history=""
        self.raw=""
        self.pool=[]
        self.visible=[]
        self.base=[]
        self.end=True

    def rpc(self,req):
        proc=self.replay.proc
        proc.stdin.write(json.dumps(req)+"\n")
        proc.stdin.flush()
        answer=proc.stdout.readline()
        if not answer:
            raise RuntimeError("Rime worker exited")
        return json.loads(answer)

    def extend(self,minimum):
        while not self.end and len(self.visible)<minimum:
            limit=0 if minimum==float("inf") else 64
            chunk=self.rpc(dict(input=self.raw,start=self.offset,limit=limit))
            self.end=not limit or len(chunk)<limit
            for i,w in enumerate(chunk,self.offset):
                if self.short:
                    if w in self.seen or len(w)!=len(self.parts) or not any(
                        matches(self.parts,r) for r in self.replay.readings(w)):
                        continue
                    self.seen.add(w)
                self.visible.append((w,i))
            self.offset+=len(chunk)

    def begin(self,raw):
        self.raw=raw
        self.parts=parse(raw)
        self.short=1<=len(self.parts)<=4
        self.end=False
        self.offset=0
        self.visible=[]
        self.seen=set()
        if self.short and 3<=len(self.parts)<=4 and raw in self.groups:
            self.rpc(dict(input=raw,limit=1))
            self.visible=self.groups[raw].copy()
            self.end=True
            self.groups.move_to_end(raw)
        else:
            self.extend(20 if len(self.parts)<=2 else float("inf") if self.short else 6)
            if self.short and 3<=len(self.parts)<=4:
                self.groups[raw]=self.visible.copy()
                if len(self.groups)>256:
                    self.groups.popitem(last=False)
        n=min(len(self.visible),20) if len(self.parts)<=2 else len(self.visible)
        self.pool=[w for w,_ in self.visible[:n]] if self.short else []
        self.base=[]
        self.fallback=False
        if self.pool and self.scorer:
            started=time.perf_counter()
            generation=self.db.execute("PRAGMA data_version").fetchone()[0]
            if generation!=self.generation:
                self.head=load_head(self.db,self.scorer.model_id)
                self.generation=generation
            try:
                scores=self.scorer.scores(self.history,self.pool,self.scorer.window)
                self.base=scores.tolist()
                order=np.argsort(-personalized(scores,self.pool,self.head),kind="stable")
                if time.perf_counter()-started<=.020:
                    self.visible[:n]=[self.visible[i] for i in order]
                else:
                    self.fallback=True
            except (ValueError,RuntimeError):
                self.fallback=True
        self.displayed=[w for w,_ in self.visible[:n]]

    def page(self,index):
        self.extend((index+1)*5+1)
        return [w for w,_ in self.visible[index*5:index*5+5]]

    def choose(self,idx):
        if idx<0 or idx>=len(self.visible):
            return ""
        selected,original=self.visible[idx]
        text=self.rpc({"select":original})
        if text and self.short and selected==text and self.scorer:
            kind="full" if all(s in SYLLABLES for s in self.parts) else "initial" if all(
                len(s)==1 or s in ("ch","zh","sh") for s in self.parts) else "mixed"
            self.jobs.put(dict(context=self.history,input=self.raw,kind=kind,pool=self.pool,
                display=self.displayed,scores=self.base,chosen=text,display_rank=idx+1,weight=1 if idx==0 else 3,
                model=self.scorer.model_id,coverage="in_pool" if text in self.pool else "tail"))
        if text:
            self.history=context(self.history+text)
            self.groups.clear()
        self.raw=""
        return text

    def close(self):
        self.jobs.put(None)
        self.writer.join()
        self.replay.close()
        self.db.close()

