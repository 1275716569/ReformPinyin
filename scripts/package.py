"""Build the offline Windows x64 setup from the tested Rime and ONNX assets."""
import hashlib
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
A=ROOT/"artifacts"
release=ROOT/"release"
release.mkdir(exist_ok=True)
stage=A/"bundle/ReformHost"
if not (stage/"ReformHost.exe").is_file():
    raise RuntimeError("freeze the service first")
def copy(path,dest):
    dest=stage/dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,dest)
copy(A/"ReformTIP.dll","ReformTIP.dll")
copy(ROOT/"data/samples.jsonl","data/samples.jsonl")
(stage/"Install.ps1").write_text((ROOT/"scripts/Install.ps1").read_text(encoding="utf8"),encoding="utf-8-sig")
copy(ROOT/"src/rime_worker.py","src/rime_worker.py")
copy(ROOT/"vendor/stock/rime.dll","vendor/stock/rime.dll")
shutil.copytree(ROOT/"vendor/python32",stage/"vendor/python32",dirs_exist_ok=True)
for file in ("syllables.json","readings.sqlite"):
    copy(A/file,"artifacts/"+file)
for file in ("manifest.json","vocab.json","ranker.onnx"):
    copy(ROOT/"model"/file,"model/"+file)
shared=A/"shared"
for file in shared.iterdir():
    if file.is_file() and (file.suffix in (".yaml",".txt") or file.name=="LICENSE"):
        copy(file,"artifacts/shared/"+file.name)
for name in ("cn_dicts","en_dicts","opencc","lua"):
    shutil.copytree(shared/name,stage/"artifacts/shared"/name,dirs_exist_ok=True)
shutil.copytree(A/"replay/build",stage/"artifacts/shared/build",dirs_exist_ok=True)
copy(ROOT/"vendor/stock/LICENSE.txt","licenses/Weasel.txt")
copy(shared/"LICENSE","licenses/Rime-Ice.txt")
for d in ("onnxruntime","numpy"):
    for file in (ROOT/".venv/Lib/site-packages"/d).rglob("*LICENSE*"):
        if file.is_file():
            copy(file,"licenses/"+d+"/"+str(file.relative_to(ROOT/".venv/Lib/site-packages"/d)))
if (ROOT/"README.md").exists():
    copy(ROOT/"README.md","README.md")
manifest=A/"setup.manifest"
manifest.write_text("""<?xml version="1.0" encoding="utf-8"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
<assemblyIdentity name="ReformPinyin.Setup" version="0.2.4.0" type="win32" processorArchitecture="amd64"/>
<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
<requestedExecutionLevel level="asInvoker" uiAccess="false"/>
</requestedPrivileges></security></trustInfo></assembly>""",encoding="utf8")
csc=Path(os.environ["WINDIR"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
loader=A/"setup-loader.exe"
subprocess.run([str(csc),"/nologo","/target:winexe","/platform:x64","/win32manifest:"+str(manifest),
    "/out:"+str(loader),"/r:System.Windows.Forms.dll","/r:System.IO.Compression.dll",
    "/r:System.IO.Compression.FileSystem.dll",str(ROOT/"native/Setup.cs")],check=True)
archive=A/"offline.zip"
with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            z.write(path,path.relative_to(stage).as_posix())
installer=release/"ReformPinyin-0.2.4-x64.exe"
with installer.open("wb") as out:
    out.write(loader.read_bytes())
    with archive.open("rb") as f:
        shutil.copyfileobj(f,out)
    out.write(struct.pack("<q",archive.stat().st_size))
print(installer.name,installer.stat().st_size,hashlib.sha256(installer.read_bytes()).hexdigest())

