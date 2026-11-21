"""Exercise the frozen service through the same pipe as the Windows text service."""
from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import json
import os
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
K=C.WinDLL("kernel32",use_last_error=True)
K.CallNamedPipeW.argtypes=[W.LPCWSTR,C.c_void_p,W.DWORD,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),W.DWORD]
sid=W.DWORD()
K.ProcessIdToSessionId(os.getpid(),C.byref(sid))
name=r"\\.\pipe\ReformPinyin.v1."+str(sid.value)

def call(op,arg=""):
    msg=("qa\t"+op+"\t"+arg).encode("utf-16-le")
    buf=C.create_string_buffer(65536)
    got=W.DWORD()
    if not K.CallNamedPipeW(name,msg,len(msg),buf,len(buf),C.byref(got),100):
        return None
    return buf.raw[:got.value].decode("utf-16-le").rstrip("\0")
def run():
    if call("hello") is not None:
        raise RuntimeError("A host is already running. Keep its live session intact.")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        proc=subprocess.Popen([str(ROOT/"artifacts/bundle/ReformHost/ReformHost.exe")],
            env={**os.environ,"LOCALAPPDATA":tmp},creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(240):
                if call("hello")=="ready":
                    break
                if proc.poll() is not None:
                    raise RuntimeError("frozen host exited "+str(proc.returncode))
                time.sleep(.25)
            else:
                raise TimeoutError("host startup")
            results=[]
            for raw in ("quan","xian","qy","quany","qyi","xi'an","xa","zgr","zgyd","womingtianshangban"):
                begin=time.perf_counter()
                reply=call("input",raw)
                assert reply,raw
                results.append((raw,reply.split("\t"),(time.perf_counter()-begin)*1000))
            call("input","qy")
            tail=call("page","5").split("\t")
            assert call("choose","26")==tail[1]
            call("reset")
            (ROOT/"reports/packaged-host.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
        finally:
            proc.terminate()
            proc.wait()
if __name__=="__main__":
    run()

