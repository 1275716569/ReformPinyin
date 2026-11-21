"""Line-delimited JSON bridge to the exact 32-bit Rime shipped with Weasel."""
import ctypes as C
import json
import os
import shutil
import sys
from pathlib import Path

class Traits(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [(name, C.c_char_p) for name in
        ("shared", "user", "name", "code", "version", "app")] + [
        ("modules", C.c_void_p), ("log_level", C.c_int), ("log_dir", C.c_char_p),
        ("prebuilt", C.c_char_p), ("staging", C.c_char_p)]

class Candidate(C.Structure):
    _fields_ = [("text", C.c_char_p), ("comment", C.c_char_p), ("reserved", C.c_void_p)]

class Iterator(C.Structure):
    _fields_ = [("ptr", C.c_void_p), ("index", C.c_int), ("candidate", Candidate)]

class Commit(C.Structure):
    _fields_ = [("data_size", C.c_int), ("text", C.c_char_p)]

def main():
    dll, shared, user = map(Path, sys.argv[1:4])
    user.mkdir(exist_ok=True, parents=True)
    lunar = user / "lua/lunar.db"
    if not lunar.exists() and (shared/"lua/lunar.db").is_file():
        lunar.parent.mkdir(exist_ok=True)
        shutil.copyfile(shared/"lua/lunar.db",lunar)
    api = C.CDLL(str(dll.resolve()))
    traits = Traits(C.sizeof(Traits)-4, str(shared.resolve()).encode(), str(user.resolve()).encode(),
                    b"Reform", b"reform", b"0.1", b"rime.reform", None, 2, b"")
    api.RimeSetup(C.byref(traits))
    api.RimeInitialize(C.byref(traits))
    if api.RimeStartMaintenance(0):
        api.RimeJoinMaintenanceThread()
    session = api.RimeCreateSession()
    if not session or not api.RimeSelectSchema(session, b"rime_ice"):
        raise RuntimeError("cannot select deployed rime_ice schema")
    print('{"ready":true}', flush=True)
    try:
        for line in sys.stdin.buffer:
            request = json.loads(line)
            if "select" in request:
                api.RimeSelectCandidate(session, request["select"])
                item = Commit(C.sizeof(Commit)-4)
                if not api.RimeGetCommit(session,C.byref(item)):
                    api.RimeCommitComposition(session)
                if item.text or api.RimeGetCommit(session,C.byref(item)):
                    print(json.dumps(item.text.decode()),flush=True)
                    api.RimeFreeCommit(C.byref(item))
                else:
                    print('""',flush=True)
                continue
            start=request.get("start",0)
            if not start:
                api.RimeClearComposition(session)
                api.RimeSetInput(session, request["input"].encode("ascii"))
            it = Iterator()
            items = []
            if api.RimeCandidateListFromIndex(session, C.byref(it),start):
                try:
                    while api.RimeCandidateListNext(C.byref(it)):
                        items.append(it.candidate.text.decode())
                        if request.get("limit") and len(items) >= request["limit"]:
                            break
                finally:
                    api.RimeCandidateListEnd(C.byref(it))
            print(json.dumps(items, ensure_ascii=True), flush=True)
    finally:
        api.RimeDestroySession(session)
        api.RimeFinalize()

if __name__ == "__main__":
    main()
