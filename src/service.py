"""Single-user Rime/ONNX host. Each named-pipe request is one UTF-16 message."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time
if getattr(sys,"frozen",False):
    os.environ["REFORM_ROOT"]=str(Path(sys.executable).parent)
from pinyin import ROOT
from engine import Engine
from learning import database,update
from ranking import Scorer

K=C.WinDLL("kernel32",use_last_error=True)
K.CreateNamedPipeW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,C.c_void_p]
K.CreateNamedPipeW.restype=W.HANDLE
for name,args in [("ConnectNamedPipe",[W.HANDLE,C.c_void_p]),("CloseHandle",[W.HANDLE]),
        ("ReadFile",[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]),
        ("WriteFile",[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]),
        ("FlushFileBuffers",[W.HANDLE]),("DisconnectNamedPipe",[W.HANDLE])]:
    getattr(K,name).argtypes=args
K.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR]
K.CreateMutexW.restype=W.HANDLE
folder=Path(os.environ["LOCALAPPDATA"])/"ReformPinyin"/"user"

def train_loop():
    db=database(folder)
    version=json.loads((ROOT/"model/manifest.json").read_text())["sha256"]
    parent=int(sys.argv[-1])
    K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]
    K.OpenProcess.restype=W.HANDLE
    handle=K.OpenProcess(0x100000,False,parent)
    if not handle:
        return
    K.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD]
    while K.WaitForSingleObject(handle,60000)==258:
        update(db,version)
    K.CloseHandle(handle)

def serve():
    sid=W.DWORD()
    K.ProcessIdToSessionId(os.getpid(),C.byref(sid))
    mutex=K.CreateMutexW(None,False,"Local\\ReformPinyin.Host.v1")
    if not mutex or C.get_last_error()==183:
        return
    pipe_name=r"\\.\pipe\ReformPinyin.v1."+str(sid.value)
    try:
        scorer=Scorer(ROOT/"model")
        scorer.scores("",["字"],32)
    except (OSError,ValueError,RuntimeError):
        scorer=None
    engine=Engine(folder,scorer)
    if scorer:
        cmd=[sys.executable] if getattr(sys,"frozen",False) else [sys.executable,__file__]
        subprocess.Popen(cmd+["--learn",str(os.getpid())],creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    previous=""
    # First-instance flag prevents serving over a pipe created by another host.
    handle=K.CreateNamedPipeW(pipe_name,3|0x80000,4|2|8,1,65536,65536,100,None)
    if handle==C.c_void_p(-1).value:
        raise OSError(C.get_last_error(),"CreateNamedPipe")
    try:
        while True:
            if not K.ConnectNamedPipe(handle,None) and C.get_last_error()!=535:
                break
            buf=C.create_string_buffer(65536)
            count=W.DWORD()
            try:
                if not K.ReadFile(handle,buf,len(buf),C.byref(count),None):
                    continue
                client,op,arg=buf.raw[:count.value].decode("utf-16-le").split("\t",2)
                if client!=previous or op=="reset":
                    engine.reset()
                    previous=client
                response=""
                if op=="input":
                    engine.begin(arg)
                    response="\t".join(engine.page(0))
                elif op=="page":
                    response="\t".join(engine.page(int(arg)))
                elif op=="choose":
                    response=engine.choose(int(arg))
                elif op=="hello":
                    response="ready"
                elif op=="append":
                    from pinyin import context
                    engine.history=context(engine.history+arg)
                data=(response+"\0").encode("utf-16-le")
                K.WriteFile(handle,data,len(data),C.byref(count),None)
                K.FlushFileBuffers(handle)
            except (ValueError,IndexError,RuntimeError,OSError) as ex:
                engine.reset()
                K.WriteFile(handle,b"\0\0",2,C.byref(count),None)
            finally:
                K.DisconnectNamedPipe(handle)
    finally:
        K.CloseHandle(handle)
        engine.close()

if __name__=="__main__":
    if "--control" in sys.argv:
        from control import open_panel
        open_panel(folder)
    elif "--learn" in sys.argv:
        train_loop()
    else:
        serve()

