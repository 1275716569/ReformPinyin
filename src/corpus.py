"""Stream source documents into reproducible, auditable real-Rime examples."""
import argparse
import bz2
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import random
import re
import unicodedata
import xml.etree.ElementTree as ET
import jieba
import mwparserfromhell
from opencc import OpenCC
from pypinyin import lazy_pinyin
from pinyin import ROOT, Replay, context, matches, parse, spellings

def wiki(path):
    for _,node in ET.iterparse(bz2.open(path), events=("end",)):
        if not node.tag.endswith("}page"):
            continue
        if node.findtext("{*}ns")=="0" and node.find("{*}redirect") is None:
            ident = node.findtext("{*}id")
            raw = node.findtext("{*}revision/{*}text") or ""
            # Retain prose paragraphs and remove templates, references and tables.
            for offset,line in enumerate(raw.splitlines()):
                if not line or line[0] in "*#:;|{!=[":
                    continue
                clean = mwparserfromhell.parse(line).strip_code(normalize=True, collapse=True)
                if clean:
                    yield "wiki",ident,offset,clean,""
        node.clear()

def tatoeba(path):
    for line in bz2.open(path,"rt",encoding="utf8"):
        ident,lang,sentence,author,*_ = line.rstrip("\n").split("\t")
        yield "tatoeba",ident,0,sentence,author

def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()

def generate(args):
    streams = []
    if args.tatoeba:
        streams.append(tatoeba(args.tatoeba))
    if args.wiki:
        streams.append(wiki(args.wiki))
    if not streams:
        raise ValueError("provide at least one source")
    engine = Replay()
    converter = OpenCC("t2s")
    seen, stats = set(), Counter()
    rng = random.Random(402)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".partial")
    numbers = Counter()
    try:
        with temp.open("w",encoding="utf8") as out:
            for pair in itertools.zip_longest(*streams):
                for doc in filter(None,pair):
                    source,ident,offset,body,author = doc
                    # Every variant of a target inherits its document's split.
                    bucket = int(digest(source+ident)[:8],16)%100
                    split = "train" if bucket<90 else "val" if bucket<95 else "test"
                    body = converter.convert(unicodedata.normalize("NFKC",body)).strip()
                    pos = 0
                    for sentence in re.findall(r"[^。！？!?\n]+[。！？!?]*",body):
                        start = body.find(sentence,pos)
                        pos = start+len(sentence)
                        key = digest(sentence)
                        if key in seen:
                            continue
                        seen.add(key)
                        offset_in_sentence = 0
                        for word in jieba.cut(sentence,HMM=False):
                            idx = offset_in_sentence
                            offset_in_sentence += len(word)
                            if not re.fullmatch("[\u3400-\u9fff]{1,4}",word):
                                continue
                            readings = engine.readings(word)
                            if not readings:
                                stats["missing_lexicon"] += 1
                                continue
                            if len(readings)==1:
                                reading = readings[0]
                            else:
                                span = lazy_pinyin(sentence,errors=lambda x:list(x))
                                reading = " ".join(span[idx:idx+len(word)]).replace("ü","v")
                                if reading not in readings:
                                    stats["unresolved_reading"] += 1
                                    continue
                            variants = list(spellings(reading))
                            rng.shuffle(variants)
                            for kind,raw in variants:
                                parts = parse(raw)
                                if not matches(parts,reading):
                                    stats["ambiguous_spelling"] += 1
                                    continue
                                words = engine.candidates(raw)
                                pool = words[:20] if len(parts)<=2 else words
                                rank = words.index(word)+1 if word in words else 0
                                status = "in_pool" if 0<rank<=len(pool) else "tail" if rank else "absent"
                                record = dict(source=source,document=ident,paragraph=offset,
                                    offset=start+idx,author=author,split=split,context=context(body[:start+idx]),
                                    input=raw,kind=kind,parts=parts,target=word,rank=rank,
                                    candidates=pool,total=len(words),status=status)
                                out.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
                                stats[status]+=1
                                numbers[split]+=int(status=="in_pool")
                    if numbers["train"]>=args.limit:
                        break
                if numbers["train"]>=args.limit:
                    break
                if sum(stats.values())//10000 > stats.get("progress",0):
                    stats["progress"]=sum(stats.values())//10000
                    print(dict(numbers),flush=True)
        temp.replace(args.output)
        args.output.with_suffix(".stats.json").write_text(json.dumps(dict(counts=numbers,statistics=stats),
            ensure_ascii=False,indent=2),encoding="utf8")
    finally:
        engine.close()

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--wiki",type=Path)
    cli.add_argument("--tatoeba",type=Path)
    cli.add_argument("--limit",type=int,default=300000)
    cli.add_argument("--output",type=Path,default=ROOT/"data/samples.jsonl")
    generate(cli.parse_args())
