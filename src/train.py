"""Listwise ranker trained exclusively on training documents."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from pinyin import ROOT

class Block(nn.Module):
    def __init__(self,d):
        super().__init__()
        self.qkv=nn.Linear(d,d*3)
        self.out=nn.Linear(d,d)
        self.n1=nn.LayerNorm(d)
        self.n2=nn.LayerNorm(d)
        self.ff=nn.Sequential(nn.Linear(d,4*d),nn.GELU(),nn.Linear(4*d,d))

    def forward(self,x,mask):
        b,t,d=x.shape
        q,k,v=self.qkv(x).reshape(b,t,3,4,d//4).permute(2,0,3,1,4).unbind(0)
        weights=(q@k.transpose(-1,-2))/math.sqrt(48)
        z=(weights.masked_fill(~mask[:,None,None,:],-10000).softmax(-1)@v)
        x=self.n1(x+self.out(z.transpose(1,2).reshape(b,t,d)))
        return self.n2(x+self.ff(x))

class Ranker(nn.Module):
    def __init__(self,vocab=8000,d=192):
        super().__init__()
        self.emb=nn.Embedding(vocab,d,padding_idx=0)
        self.pos=nn.Embedding(129,d)
        self.blocks=nn.ModuleList([Block(d) for _ in range(3)])
        self.context_map=nn.Linear(d,d)
        self.word_map=nn.Linear(d,d)
        self.prior=nn.Linear(d,1)
        self.rank_weight=nn.Parameter(torch.tensor(1.0))

    def forward(self,ctx,words):
        mask=ctx!=0
        x=self.emb(ctx)+self.pos(torch.arange(ctx.size(1),device=ctx.device))
        for block in self.blocks:
            x=block(x,mask)
        # BOS at index zero also represents empty context.
        state=x[torch.arange(x.size(0),device=x.device),mask.long().sum(1)-1]
        vec=self.emb(words).sum(-2)/(words!=0).sum(-1,keepdim=True).clamp_min(1)
        align=(self.context_map(state)[:,None,:]*self.word_map(vec)).sum(-1)/math.sqrt(192)
        rank=torch.arange(words.size(1),device=ctx.device).float().log1p()
        score=align+self.prior(vec).squeeze(-1)-self.rank_weight*rank
        return score.masked_fill(words[:,:,0]==0,-10000)

def lines(path):
    with Path(path).open(encoding="utf8") as f:
        for line in f:
            yield json.loads(line)

def encode_word(s,vocab):
    return [vocab.get(c,1) for c in s[:4]]

def batches(rows,bs,shuffle):
    order=list(range(len(rows)))
    if shuffle:
        random.shuffle(order)
    for start in range(0,len(order),bs):
        batch=[rows[i] for i in order[start:start+bs]]
        width=max(len(r[0]) for r in batch)
        count=max(len(r[1]) for r in batch)
        ctx=np.zeros((len(batch),width),np.int64)
        words=np.zeros((len(batch),count,4),np.int64)
        for i,(history,group,_,_) in enumerate(batch):
            ctx[i,:len(history)]=history
            words[i,:len(group)]=group
        yield torch.from_numpy(ctx),torch.from_numpy(words),torch.tensor([r[2] for r in batch]),batch

def run(args):
    random.seed(47)
    torch.manual_seed(47)
    torch.set_num_threads(4)
    torch.set_float32_matmul_precision("high")
    device="cuda" if torch.cuda.is_available() else "cpu"
    out=args.out
    out.mkdir(exist_ok=True,parents=True)
    chars=Counter()
    for r in lines(args.data):
        if r["split"]=="train":
            chars.update(r["context"]+r["target"])
    vocab={c:i+3 for i,(c,n) in enumerate(chars.most_common(7997))}
    (out/"vocab.json").write_text(json.dumps(vocab,ensure_ascii=False),encoding="utf8")
    sets={"train":[],"val":[]}
    pools={}
    for r in lines(args.data):
        split=r["split"]
        if split not in sets or r["status"]!="in_pool":
            continue
        key=r["input"]
        if key not in pools:
            pool=np.zeros((len(r["candidates"]),4),np.int64)
            for i,s in enumerate(r["candidates"]):
                vals=encode_word(s,vocab)
                pool[i,:len(vals)]=vals
            pools[key]=pool
        # Train with variable windows so 32/64/128 can be evaluated using one model.
        size=random.choice((32,64,128)) if split=="train" else 64
        text=r["context"][-size:]
        sets[split].append(([2]+[vocab.get(c,1) for c in text],pools[key],r["rank"]-1,r["kind"]))
    net=Ranker().to(device)
    opt=torch.optim.AdamW(net.parameters(),lr=0.00045)
    best=-1
    print("device",device,"sizes", {k:len(v) for k,v in sets.items()},flush=True)
    for epoch in range(args.epochs):
        net.train()
        # Bucket long candidate groups and long contexts to avoid dense padding blow-up.
        random.shuffle(sets["train"])
        for chunk in range(0,len(sets["train"]),2048):
            rows=sorted(sets["train"][chunk:chunk+2048],key=lambda r:(len(r[1])//16,len(r[0])//16))
            for x,w,y,_ in batches(rows,args.batch,False):
                opt.zero_grad(set_to_none=True)
                loss=F.cross_entropy(net(x.to(device),w.to(device)),y.to(device))
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(),2)
                opt.step()
        net.eval()
        good=total=0
        with torch.no_grad():
            for x,w,y,rows in batches(sets["val"],args.batch,False):
                predictions=net(x.to(device),w.to(device)).argmax(1).cpu()
                for a,b,r in zip(predictions,y,rows):
                    if r[3]=="initial":
                        total+=1
                        good+=int(a==b)
        metric=good/max(total,1)
        print("epoch",epoch+1,"validation initial",metric,flush=True)
        if metric>best:
            best=metric
            torch.save(net.state_dict(),out/"ranker.pt")
    net.load_state_dict(torch.load(out/"ranker.pt",map_location=device,weights_only=True))
    net.cpu().eval()
    x=torch.tensor([[2,4,6]],dtype=torch.int64)
    w=torch.tensor([[[3,0,0,0],[4,6,0,0]]],dtype=torch.int64)
    torch.onnx.export(net,(x,w),out/"ranker.onnx",input_names=["context","words"],output_names=["scores"],
        dynamic_axes={"context":{0:"batch",1:"tokens"},"words":{0:"batch",1:"candidates"},"scores":{0:"batch",1:"candidates"}},
        opset_version=17,dynamo=False)
    import onnxruntime as ort
    actual=ort.InferenceSession(str(out/"ranker.onnx"),providers=["CPUExecutionProvider"]).run(None,{"context":x.numpy(),"words":w.numpy()})[0]
    np.testing.assert_allclose(net(x,w).detach().numpy(),actual,rtol=1e-4,atol=1e-4)
    manifest={"parameters":sum(p.numel() for p in net.parameters()),"training_device":device,
        "train_items":len(sets["train"]),"val_items":len(sets["val"]),"best_initial_validation":best,
        "sha256":hashlib.sha256((out/"ranker.onnx").read_bytes()).hexdigest()}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf8")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data",type=Path,default=ROOT/"data/samples.jsonl")
    p.add_argument("--out",type=Path,default=ROOT/"model")
    p.add_argument("--epochs",type=int,default=4)
    p.add_argument("--batch",type=int,default=96)
    run(p.parse_args())
