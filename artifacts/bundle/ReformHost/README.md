# 改革拼音 0.2.4 · Windows 11 x64 试用版

运行 `release/ReformPinyin-0.2.4-x64.exe`，确认 Windows 的安装提示，再用 Win + 空格选择「改革拼音」。从旧版升级后，请重新打开正在试打的应用，让它加载新版输入法。单按左或右 Shift 切换中英文，切换时光标附近会短暂显示「中」或「英」。有待选拼音时切到英文，会按原样提交这串字母。空格选首项，数字 1～5 或鼠标选当前页，减号／等号、Page Up／Page Down 或滚轮翻页。逗号、句号、问号、分号、单双引号和括号输入对应中文标点，Esc 取消，回车直接提交拼音。

从开始菜单打开「改革拼音控制面板」。在「样本查询」选择本机选词或通用语料，输入拼音、词语或上下文后查询。选中一行可查候选顺序及最终选择。「训练与调试」里的「开始训练」使用当前模型的新增有效选词，至少两条可运行，每轮随机留出 20% 样本验证，其余有效样本全部训练。总体首选命中提高且简拼表现持平或提高时启用新权重。「启动调试」按给定上下文和拼音回放首页候选，使用当前个性化权重和独立的 Rime 用户词典。开发时可运行 `.\.venv\Scripts\pythonw.exe src/service.py --control` 打开同一窗口。

输入 `quan` 或 `xian` 时只出现单字。输入 `qy`、`quany`、`qyi` 时显示两字候选。输入 `xi'an` 或 `xa` 时可以选“西安”。一至二字取前 20 项打分，余项沿用原序。三四字取匹配的全部词条。长输入取 Rime 原有候选。试用版使用小狼毫 0.17.4 的 32 位 Rime 二进制，配合固定版本雾凇拼音及独立的 64 位 Windows 文本服务。用户范围内的后台进程负责 Rime、ONNX CPU 打分及选词记录。当前前端可用于 64 位桌面程序。

上下文记录本次焦点内自己确认上屏的文字。离开输入框时清除，首版使用 32 token。Windows 标记为密码或 PIN 的字段会跳过。学习默认开启。500 条新的有效记录及 5 分钟系统空闲后，低优先级进程基于用户选择更新每个候选词的偏置，最多每天一次。选择后排权重为 3，接受首选权重为 1。新模型通过本机留出验证后启用，旧权重保存在同一数据库中。Rime 的用户词典另外记录即时调频。样本默认保存在学习数据库中，注销输入法会保留个人数据。

## 从源代码复跑

在项目根目录使用 PowerShell。需要 64 位 Python 3.12、7-Zip、MinGW-w64 的 g++ 和 Windows 自带的 .NET Framework 4.x 编译器。获取小狼毫源码和发布包、雾凇源码及 Python 3.12.10 x86 嵌入版的方法见 scripts/fetch.py。工作区中已经准备好本次版本的依赖、样本和权重。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python scripts/fetch.py
.\.venv\Scripts\python scripts/prepare.py
.\.venv\Scripts\python src/corpus.py --tatoeba data/cmn.tsv.bz2 --limit 10000 --output data/pilot.jsonl
.\.venv\Scripts\python src/corpus.py --wiki data/wiki.xml.bz2 --tatoeba data/cmn.tsv.bz2 --limit 300000 --output data/samples.jsonl
.\.venv\Scripts\python src/train.py --epochs 3
.\.venv\Scripts\python src/evaluate.py
.\.venv\Scripts\python tests/smoke.py
g++ -std=c++17 -O2 -static -shared native/tip.cpp -o artifacts/ReformTIP.dll -luuid -lole32 -loleaut32 -lgdi32 -ladvapi32
.\.venv\Scripts\python -m PyInstaller --noconfirm --onedir --windowed --exclude-module torch --exclude-module scipy --exclude-module transformers --name ReformHost --distpath artifacts/bundle --workpath artifacts/freeze --specpath artifacts src/service.py
.\.venv\Scripts\python scripts/package.py
```

tests/package_smoke.py 用隔离的临时用户目录测试打包后的后台、候选和第 27 项上屏。为了避免影响真实输入，这个测试会在已有后台运行时退出。详细数据和未完成的验收见 reports/首版验收.md。

## 数据和上游来源

- 小狼毫及其发布包，tag 0.17.4。 [源码与许可](https://github.com/rime/weasel/tree/0.17.4)
- 雾凇拼音及词典，提交 927e1cf1d3eeb9bf4be85e3f684dba4dd485b6f6。 [源码及词典出处](https://github.com/iDvel/rime-ice/tree/927e1cf1d3eeb9bf4be85e3f684dba4dd485b6f6)
- 中文维基百科，2026-11-01 正文转储。样本记录保存文章 ID 与段落位置，可从页面历史查看作者。 [归属及许可](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) · [转储](https://dumps.wikimedia.org/zhwiki/20261101/)
- Tatoeba 普通话中文句子，保留句子 ID 和作者。 [语料与许可](https://tatoeba.org/en/downloads)

