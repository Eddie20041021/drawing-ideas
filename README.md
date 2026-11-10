# 作圖想法筆記

記錄想用 AI 畫的畫面。每則想法拆成背景、服裝、事件三個具體元素，加上一個不用很具體的概念。網站會自動整理出哪些元素用過、哪些還沒試過。

- 網站：發佈在 GitHub Pages（來源是 `docs/`）
- 規則：見 [CLAUDE.md](CLAUDE.md)，AI 依照這份文件新增與修改筆記

## 怎麼新增一則想法

把想法用一句話丟給 AI（Claude Code 等），例如「浴衣背影看煙火，然後稍微回頭」，AI 會照 CLAUDE.md：

1. 拆出背景、服裝、事件並對照詞庫，再寫一句概念
2. 寫成固定格式的筆記（原話保留、AI 的建議另外放）
3. 沒說公開就放進不會上傳的 `private/`
4. 跑 `python3 build.py` 檢查並重新產生網站

## 自己建置

```
python3 build.py
```

只需要 Python 3，不用安裝任何套件。產出在 `docs/`。

## 結構

```
notes/      公開筆記（一則一個 .md）
private/    私人筆記，不上傳
vocab.json  元素詞庫
assets/     CSS 與 JS
build.py    檢查規則＋產生網站
docs/       產出的網站（不要手動改）
log.md      修改紀錄
```
