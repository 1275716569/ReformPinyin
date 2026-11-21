"""Exercise the actual panel buttons using temporary personal samples."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from control import Panel, CORPUS, ROOT, sample_page
from learning import database, write_sample, load_head


def run():
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        root = tk.Tk()
        root.withdraw()
        panel = Panel(root, folder)
        def wait(ready):
            deadline = time.monotonic() + 120
            while not ready():
                root.update()
                if time.monotonic() > deadline:
                    raise TimeoutError("panel action timed out")
                time.sleep(.02)
            root.update()
        try:
            wait(lambda: not panel.searching)
            assert not panel.rows
            panel.start.invoke()
            wait(lambda: panel.start.instate(["!disabled"]))
            assert "0 条" in panel.training.get(), panel.training.get()
            model = json.loads((ROOT / "model/manifest.json").read_text())["sha256"]
            with closing(database(folder)) as db:
                event = dict(input="qy", context="测试", model=model, scores=[.1, 0],
                             pool=["区域","权益"], display=["区域","权益"], chosen="权益",
                             display_rank=2, kind="initial", weight=3)
                for _ in range(52):
                    write_sample(db, event)
                panel.entry.insert(0, "权益")
                panel.find.invoke()
                wait(lambda: not panel.searching)
                assert len(panel.rows) == 50
                first_page = {e["id"] for e in panel.rows}
                panel.forward.invoke()
                wait(lambda: not panel.searching)
                assert len(panel.rows) == 2
                assert not first_page.intersection(e["id"] for e in panel.rows)
                panel.back.invoke()
                wait(lambda: not panel.searching)
                assert "权益" in panel.detail.get("1.0","end")
                panel.start.invoke()
                wait(lambda: panel.start.instate(["!disabled"]))
                assert "已启用" in panel.training.get(), panel.training.get()
                assert load_head(db, model)["权益"] > 0
                panel.raw.insert(0, "qy")
                panel.history.insert(0, "消费者的")
                panel.debug_button.invoke()
                wait(lambda: panel.debug_button.instate(["!disabled"]))
                assert "1  " in panel.result.get(), panel.result.get()
                assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 52
            panel.source.set(CORPUS)
            panel.entry.delete(0, "end")
            panel.entry.insert(0, "我们")
            panel.find.invoke()
            wait(lambda: not panel.searching)
            assert panel.rows and panel.next_cursor
            panel.forward.invoke()
            wait(lambda: not panel.searching)
            assert panel.rows
        finally:
            panel.work.shutdown()
            root.destroy()
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        with closing(database(folder)) as db:
            for _ in range(50):
                write_sample(db, {"input":"qy","chosen":"权益","context":"",
                                  "display":["权益"],"pool":["权益"],"display_rank":1,
                                  "weight":1,"kind":"initial"})
        rows, cursor = sample_page(folder, "本机选词", "", 0)
        assert len(rows) == 50 and cursor is None
    print("Panel search, paging, manual training and isolated replay passed")


if __name__ == "__main__":
    run()
