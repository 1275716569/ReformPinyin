import json
import time
from functools import lru_cache
from pathlib import Path
import numpy as np
import onnxruntime as ort

class Scorer:
    def __init__(self,path):
        self.vocab=json.loads((path/"vocab.json").read_text(encoding="utf8"))
        manifest=json.loads((path/"manifest.json").read_text())
        self.model_id=manifest["sha256"]
        self.window=manifest.get("window",64)
        opts=ort.SessionOptions()
        opts.intra_op_num_threads=2
        opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path/"ranker.onnx"),opts,providers=["CPUExecutionProvider"])

    @lru_cache(24000)
    def word(self,w):
        ids=[self.vocab.get(c,1) for c in w[:4]]
        return ids+[0]*(4-len(ids))

    def scores(self,history,words,window=64):
        x=np.array([[2]+[self.vocab.get(c,1) for c in history[-window:]]],dtype=np.int64)
        w=np.array([[self.word(s) for s in words]],dtype=np.int64)
        return self.session.run(None,{"context":x,"words":w})[0][0]

def personalized(scores,words,head):
    return scores+np.array([head.get(w,0.) for w in words],np.float32)

