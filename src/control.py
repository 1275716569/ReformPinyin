"""Local sample browser, personal training and isolated candidate replay."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import ttk

from engine import Engine
from learning import database, load_head, update
from pinyin import ROOT, context
from ranking import Scorer

PAGE_SIZE = 50
PERSONAL = "本机选词"
CORPUS = "通用语料"
KINDS = {"initial": "简拼", "full": "全拼", "mixed": "混拼"}


def sample_page(folder, source, keyword, cursor):
    rows = []
    if source == PERSONAL:
        sql = """
            SELECT id, stamp, sample FROM events
            WHERE (? = 0 OR id <= ?) AND
                (instr(lower(json_extract(sample,'$.input')), ?) OR
                 instr(json_extract(sample,'$.chosen'), ?) OR
                 instr(json_extract(sample,'$.context'), ?) OR ? = '')
            ORDER BY id DESC LIMIT ?
        """
        with closing(database(folder)) as db:
            for key, stamp, sample in db.execute(sql, (cursor, cursor, keyword.lower(),
                                             keyword, keyword, keyword, PAGE_SIZE + 1)):
                if len(rows) == PAGE_SIZE:
                    return rows, key
                event = json.loads(sample)
                event["id"] = key
                event["time"] = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S")
                rows.append(event)
        return rows, None
    else:
        with (ROOT / "data/samples.jsonl").open("rb") as stream:
            stream.seek(cursor)
            next_cursor = None
            while True:
                line = stream.readline()
                if not line:
                    break
                event = json.loads(line)
                if keyword and not any(keyword.casefold() in event[field].casefold()
                                       for field in ("input", "target", "context")):
                    continue
                if len(rows) == PAGE_SIZE:
                    return rows, next_cursor
                rows.append(event)
                next_cursor = stream.tell()
    return rows, None


def train_personal(folder):
    model = json.loads((ROOT / "model/manifest.json").read_text())["sha256"]
    messages = []
    with closing(database(folder)) as db:
        update(db, model, manual=True, report=messages.append)
    return messages[-1]


def replay(folder, history, raw):
    scorer = Scorer(ROOT / "model")
    with closing(database(folder)) as db:
        head = load_head(db, scorer.model_id)
    with TemporaryDirectory() as temp:
        with closing(Engine(Path(temp), scorer)) as engine:
            with engine.db:
                engine.db.execute("INSERT INTO state VALUES (?,?)",
                                  ("head:" + scorer.model_id, json.dumps(head)))
            engine.history = context(history)
            engine.begin(raw)
            words = engine.page(0)
            return "    ".join(f"{i}  {word}" for i, word in enumerate(words, 1)) or "没有匹配的候选"


class Panel:
    def __init__(self, root, folder):
        self.root, self.folder = root, folder
        self.work = ThreadPoolExecutor(max_workers=2)
        self.cursors = [0]
        self.rows = []
        self.next_cursor = None
        self.keyword = ""
        self.page = 0
        root.title("改革拼音 · 控制面板")
        root.geometry("870x610")
        root.minsize(670, 500)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(root)
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10))
        body = ttk.Frame(root, padding=18)
        body.pack(fill="both", expand=True)
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill="both", expand=True)
        samples = ttk.Frame(self.tabs, padding=14)
        tools = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(samples, text="样本查询")
        self.tabs.add(tools, text="训练与调试")

        bar = ttk.Frame(samples)
        bar.pack(fill="x", pady=(0, 10))
        self.source = ttk.Combobox(bar, values=[PERSONAL, CORPUS], state="readonly", width=10)
        self.source.current(0)
        self.source.pack(side="left")
        self.source.bind("<<ComboboxSelected>>", lambda _: self.search())
        ttk.Label(bar, text="拼音、词语或上下文").pack(side="left", padx=(14, 6))
        self.entry = ttk.Entry(bar)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _: self.search())
        self.find = ttk.Button(bar, text="查询", command=self.search)
        self.find.pack(side="left", padx=(6, 0))

        table = ttk.Frame(samples)
        table.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table, columns=("input", "target", "kind", "context"),
                                  show="headings", selectmode="browse", height=9)
        for col, title, width in (("input","拼音",115), ("target","选词 / 目标词",105),
                                  ("kind","拼写",62), ("context","上下文",300)):
            self.table.heading(col, text=title, anchor="w")
            self.table.column(col, width=width, minwidth=42, stretch=col=="context")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", lambda _: self.details())

        nav = ttk.Frame(samples)
        nav.pack(fill="x", pady=8)
        self.status = tk.StringVar()
        ttk.Label(nav, textvariable=self.status).pack(side="left")
        self.forward = ttk.Button(nav, text="下一页", command=lambda: self.move(1))
        self.forward.pack(side="right")
        self.back = ttk.Button(nav, text="上一页", command=lambda: self.move(-1))
        self.back.pack(side="right", padx=4)
        self.detail = tk.Text(samples, height=5, wrap="word", relief="flat", padx=8, pady=5,
                              background="#f5f6f7", state="disabled")
        self.detail.pack(fill="x")

        self.heading(tools, "本机个性化训练")
        self.training = tk.StringVar(value="等待开始")
        self.start = ttk.Button(tools, text="开始训练", command=self.train)
        self.start.pack(anchor="w", pady=(8, 6))
        ttk.Label(tools, textvariable=self.training, wraplength=560).pack(anchor="w")
        ttk.Separator(tools).pack(fill="x", pady=18)
        self.heading(tools, "候选调试")
        ttk.Label(tools, text="上下文").pack(anchor="w", pady=(9, 2))
        self.history = ttk.Entry(tools)
        self.history.pack(fill="x")
        ttk.Label(tools, text="拼音").pack(anchor="w", pady=(8, 2))
        self.raw = ttk.Entry(tools)
        self.raw.pack(fill="x")
        self.raw.bind("<Return>", lambda _: self.debug())
        self.debug_button = ttk.Button(tools, text="启动调试", command=self.debug)
        self.debug_button.pack(anchor="w", pady=9)
        self.result = tk.StringVar()
        ttk.Label(tools, textvariable=self.result, wraplength=550).pack(anchor="w")
        self.searching = False
        self.search()

    def heading(self, parent, text):
        ttk.Label(parent, text=text, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")

    def run(self, func, done, error):
        future = self.work.submit(func)
        def poll():
            if not future.done():
                self.root.after(80, poll)
                return
            try:
                value = future.result()
            except Exception as exc:
                error(f"操作失败：{exc}")
            else:
                done(value)
        self.root.after(20, poll)

    def search(self):
        if self.searching:
            return
        self.keyword = self.entry.get().strip()
        self.cursors = [0]
        self.page = 0
        self.load()

    def move(self, step):
        if self.searching:
            return
        if step > 0:
            self.cursors.append(self.next_cursor)
        else:
            self.cursors.pop()
        self.page += step
        self.load()

    def load(self):
        self.searching = True
        self.status.set("查询中…")
        source, cursor = self.source.get(), self.cursors[-1]
        self.source.configure(state="disabled")
        for button in (self.back, self.forward, self.find):
            button.state(["disabled"])
        def show(result, message=None):
            self.searching = False
            self.rows, self.next_cursor = result
            self.table.delete(*self.table.get_children())
            for i, e in enumerate(self.rows):
                self.table.insert("", "end", iid=str(i), values=(e["input"], e.get("chosen", e.get("target")),
                                  KINDS.get(e["kind"], e["kind"]), e["context"]))
            self.details()
            if self.rows:
                self.table.selection_set("0")
            self.status.set(message or (f"第 {self.page+1} 页 · 本页 {len(self.rows)} 条" if self.rows
                                        else "没有匹配的样本"))
            self.source.configure(state="readonly")
            self.find.state(["!disabled"])
            if self.page:
                self.back.state(["!disabled"])
            if self.next_cursor is not None:
                self.forward.state(["!disabled"])
        self.run(lambda: sample_page(self.folder, source, self.keyword, cursor),
                 show, lambda msg: show(([], None), msg))

    def details(self):
        selected = self.table.selection()
        lines = []
        if selected:
            e = self.rows[int(selected[0])]
            if "chosen" in e:
                lines.append(f"{e.get('time', '')}    上屏「{e['chosen']}」    显示名次 {e['display_rank']}    权重 {e['weight']}")
                lines.append("显示顺序  " + "、".join(e["display"]))
                lines.append("原始顺序  " + "、".join(e["pool"]))
            else:
                lines.append(f"{e['source']} · {e['document']}    目标「{e['target']}」    原始名次 {e['rank'] or '未出现'}")
                lines.append("原始候选  " + "、".join(e["candidates"]))
            lines.append("上下文  " + (e["context"] or "（空）"))
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    def train(self):
        self.start.state(["disabled"])
        self.training.set("正在训练并验证…")
        def finish(message):
            self.training.set(message)
            self.start.state(["!disabled"])
        self.run(lambda: train_personal(self.folder), finish, finish)

    def debug(self):
        if self.debug_button.instate(["disabled"]):
            return
        raw, history = self.raw.get().strip().lower(), self.history.get()
        if not raw or len(raw)>96 or not re.fullmatch("[a-z]+(?:'[a-z]+)*", raw):
            self.result.set("请输入拼音，例如 qy 或 xi'an。")
            return
        self.debug_button.state(["disabled"])
        self.result.set("正在回放候选…")
        def finish(message):
            self.result.set(message)
            self.debug_button.state(["!disabled"])
        self.run(lambda: replay(self.folder, history, raw), finish, finish)


def open_panel(folder):
    root = tk.Tk()
    panel = Panel(root, folder)
    try:
        root.mainloop()
    finally:
        panel.work.shutdown(cancel_futures=True)
