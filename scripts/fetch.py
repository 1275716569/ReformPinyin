"""Fetch pinned upstream binaries, archives and corpus, validating before extraction."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[1]
def fetch(rel,url,checksum,alg="sha256"):
    path=ROOT/rel
    path.parent.mkdir(exist_ok=True,parents=True)
    def valid():
        if not path.exists():
            return False
        with path.open("rb") as f:
            return hashlib.file_digest(f,alg).hexdigest()==checksum
    if not valid():
        part=path.with_suffix(path.suffix+".download")
        subprocess.run(["curl.exe","-fL","--retry","3","-C","-","-o",str(part),url],check=True)
        with part.open("rb") as f:
            if hashlib.file_digest(f,alg).hexdigest()!=checksum:
                raise RuntimeError("checksum mismatch: "+str(part))
        part.replace(path)
    return path
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--skip-wiki",action="store_true")
    opts=p.parse_args()
    archives=[
      ("vendor/weasel.zip","https://codeload.github.com/rime/weasel/zip/refs/tags/0.17.4","becda44927a96e9662fc1aca4d5df344c300efc0aded9b48e0f6c685072e067b","vendor"),
      ("vendor/ice.zip","https://codeload.github.com/iDvel/rime-ice/zip/927e1cf1d3eeb9bf4be85e3f684dba4dd485b6f6","54a52db848aa82649403d8e74f9719d0b6089dd112d6a98ed51e52f32df593a0","vendor"),
      ("vendor/py32.zip","https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-win32.zip","084b9eb24cb848605c895d05b738fbc2572efc8b4c18c415a824065864a2b853","vendor/python32")]
    for rel,url,sha,dest in archives:
        with zipfile.ZipFile(fetch(rel,url,sha)) as z:
            z.extractall(ROOT/dest)
    setup=fetch("vendor/upstream.exe","https://github.com/rime/weasel/releases/download/0.17.4/weasel-0.17.4.0-installer.exe",
      "cf509534a8f5f8af9c98ed7cbb8f135439f145a8cbe7e50ede42bb5b5ab45c29")
    subprocess.run([str(Path(os.environ["ProgramFiles"])/"7-Zip/7z.exe"),"x",str(setup),"-o"+str(ROOT/"vendor/stock"),"-y"],check=True)
    fetch("data/cmn.tsv.bz2","https://downloads.tatoeba.org/exports/per_language/cmn/cmn_sentences_detailed.tsv.bz2",
          "d7dc7791eba00014a742fe0aff0d790affd54d49d9786fdf eabf0e8b98755a34".replace(" ",""))
    if not opts.skip_wiki:
        fetch("data/wiki.xml.bz2","https://dumps.wikimedia.org/zhwiki/20261101/zhwiki-20261101-pages-articles.xml.bz2",
        "fa3b5ff2cec3ab28046b38ee830bb6881bdf9537","sha1")
if __name__=="__main__":
    main()
