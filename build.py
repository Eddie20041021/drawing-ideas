#!/usr/bin/env python3
"""作圖想法筆記 — 建置腳本。

每則筆記＝三個具體元素（背景、服裝、事件，只能用詞庫的詞）＋一個抽象概念（自由的一句話）。

讀 notes/*.md（只收公開筆記）＋ vocab.json，檢查規則後輸出靜態網站到 docs/。
只用 Python 標準函式庫，任何裝了 Python 3 的電腦都能直接跑：

    python3 build.py

檢查不通過會列出原因並以非零碼結束，docs/ 不會被更新。
docs/ 是產出物，不要手動修改；要改內容就改 notes/ 或 vocab.json，再重跑。
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTES_DIR = ROOT / "notes"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"

DIMS = ["背景", "服裝", "事件"]          # 具體元素：只能用 vocab.json 的詞
CONCEPT = "概念"                         # 抽象概念：自由的一句話，不進詞庫
CONCEPT_MAX = 30
STATUS = {"想法": "💡", "試畫中": "🎨", "完成": "✅", "放下": "🗄"}
STATUS_ORDER = list(STATUS)
REQUIRED_FIELDS = ["title", "slug", "status", "visibility", "created", "updated", "summary"] + DIMS + [CONCEPT]
REQUIRED_SECTIONS = ["原話", "畫面", "Prompt 草稿", "試畫紀錄", "下一步", "AI 補充"]
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SIMILAR_MIN = 0.2      # 相似度達這個值才列在「相似的想法」
DUPLICATE_WARN = 0.6   # 達這個值就在建置時提醒「可能重複」


# ───────────────────────── 讀檔與解析 ─────────────────────────

def parse_front_matter(text: str, name: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError(f"{name}：檔案開頭必須是 --- 區塊")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError(f"{name}：找不到 front matter 結尾的 ---")
    meta: dict = {}
    for i, line in enumerate(text[4:end].splitlines(), 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"{name} 第 {i} 行：格式應為「欄位: 值」")
        key, val = line.split(":", 1)
        key, val = key.strip(), val.split(" #")[0].strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [x.strip() for x in val[1:-1].split(",") if x.strip()]
        else:
            meta[key] = val
    body = text[end + 4:].lstrip("\n")
    return meta, body


def load_vocab() -> dict[str, list[str]]:
    vocab = json.loads((ROOT / "vocab.json").read_text(encoding="utf-8"))
    missing = [d for d in DIMS if d not in vocab]
    if missing:
        raise ValueError(f"vocab.json 缺少維度：{missing}")
    return vocab


# ───────────────────────── 規則檢查 ─────────────────────────

def check_note(meta: dict, body: str, path: Path, vocab: dict) -> list[str]:
    e: list[str] = []
    name = path.name
    for f in REQUIRED_FIELDS:
        if f not in meta:
            e.append(f"{name}：缺少欄位 {f}")
    if e:
        return e

    if meta["visibility"] != "公開":
        e.append(f"{name}：notes/ 只能放公開筆記（visibility: 公開）。私人筆記請放 private/")
    if not SLUG_RE.match(meta["slug"]):
        e.append(f"{name}：slug 只能用小寫英文、數字與連字號")
    if path.stem != meta["slug"]:
        e.append(f"{name}：檔名必須等於 slug（應為 {meta['slug']}.md）")
    if meta["status"] not in STATUS:
        e.append(f"{name}：status 必須是 {STATUS_ORDER} 之一")
    for f in ("created", "updated"):
        if not DATE_RE.match(meta[f]):
            e.append(f"{name}：{f} 格式要是 YYYY-MM-DD")
    if not e and meta["updated"] < meta["created"]:
        e.append(f"{name}：updated 不能早於 created")
    if len(meta["summary"]) > 60:
        e.append(f"{name}：summary 請控制在 60 字內（目前 {len(meta['summary'])} 字）")

    for d in DIMS:
        if not isinstance(meta[d], list):
            e.append(f"{name}：{d} 要寫成清單，例如 {d}: [詞1, 詞2]，沒有就寫 {d}: []")
            continue
        for term in meta[d]:
            if term not in vocab[d]:
                e.append(f"{name}：「{term}」不在 vocab.json 的「{d}」裡。先把它加進詞庫，或改用既有的詞")

    concept = meta[CONCEPT]
    if isinstance(concept, list):
        e.append(f"{name}：{CONCEPT} 是一句話，不是清單，不要加 [ ]")
    elif not concept:
        e.append(f"{name}：{CONCEPT} 不能空白，模糊也沒關係，例如「等待」")
    elif len(concept) > CONCEPT_MAX:
        e.append(f"{name}：{CONCEPT} 請控制在 {CONCEPT_MAX} 字內（目前 {len(concept)} 字）")

    found = re.findall(r"^## (.+)$", body, flags=re.M)
    found = [s.strip() for s in found]
    missing = [s for s in REQUIRED_SECTIONS if s not in found]
    if missing:
        e.append(f"{name}：缺少段落 {missing}")
    else:
        order = [s for s in found if s in REQUIRED_SECTIONS]
        if order != REQUIRED_SECTIONS:
            e.append(f"{name}：段落順序應為 {REQUIRED_SECTIONS}")
    return e


# ───────────────────────── Markdown（只支援本專案用到的語法）─────────────────────────

def inline(text: str) -> str:
    codes: list[str] = []

    def keep_code(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = html.escape(text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img src="\2" alt="\1" loading="lazy">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def md_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(buf))}</code></pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,4}) (.+)$", line)
        if m:
            lvl = len(m.group(1))
            text = m.group(2).strip()
            anchor = re.sub(r"\s+", "-", text)
            out.append(f'<h{lvl} id="{html.escape(anchor)}">{inline(text)}</h{lvl}>')
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if len(rows) >= 2 and all(set(c) <= set("-: ") for c in rows[1]):
                head, body_rows = rows[0], rows[2:]
            else:
                head, body_rows = None, rows
            t = ["<div class=\"table-wrap\"><table>"]
            if head:
                t.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead>")
            t.append("<tbody>" + "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body_rows) + "</tbody>")
            t.append("</table></div>")
            out.append("".join(t))
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip())
                i += 1
            out.append(f"<blockquote>{'<br>'.join(inline(b) for b in buf)}</blockquote>")
            continue
        if re.match(r"^\s*[-*] ", line):
            buf = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                buf.append(re.sub(r"^\s*[-*] ", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(b)}</li>" for b in buf) + "</ul>")
            continue
        if re.match(r"^\d+\. ", line):
            buf = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                buf.append(re.sub(r"^\d+\. ", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(b)}</li>" for b in buf) + "</ol>")
            continue
        if not line.strip():
            i += 1
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4} |```|>|\||\s*[-*] |\d+\. )", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(buf)) if all(ord(c) < 128 for c in ''.join(buf)) else inline(''.join(buf))}</p>")
    return "\n".join(out)


# ───────────────────────── 相似度 ─────────────────────────

def features(meta: dict) -> set[tuple[str, str]]:
    return {(d, t) for d in DIMS for t in meta[d]}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


# ───────────────────────── 頁面 ─────────────────────────

def page(title: str, body: str, rel: str, active: str) -> str:
    nav = [("index.html", "全部想法", "index"), ("elements.html", "元素索引", "elements"), ("rules.html", "規則", "rules")]
    links = "".join(
        f'<a href="{rel}{href}"{" aria-current=\"page\"" if key == active else ""}>{label}</a>'
        for href, label, key in nav)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}｜作圖想法筆記</title>
<link rel="stylesheet" href="{rel}assets/style.css">
</head>
<body>
<header class="site">
  <a class="brand" href="{rel}index.html">作圖想法筆記</a>
  <nav>{links}</nav>
</header>
<main>
{body}
</main>
<footer class="site">依 <a href="{rel}rules.html">CLAUDE.md</a> 的規則建置 · {datetime.now().strftime('%Y-%m-%d')}</footer>
<script src="{rel}assets/app.js"></script>
</body>
</html>
"""


def badge(status: str) -> str:
    return f'<span class="badge s-{STATUS_ORDER.index(status)}">{STATUS[status]} {status}</span>'


def chips(meta: dict, rel: str, limit: int | None = None) -> str:
    items = [(d, t) for d in DIMS for t in meta[d]]
    if limit:
        items = items[:limit]
    return "".join(
        f'<a class="chip" href="{rel}elements.html#{html.escape(d)}-{html.escape(t)}" title="{d}">{html.escape(t)}</a>'
        for d, t in items)


def render_index(notes: list[dict]) -> str:
    counts = {s: sum(n["meta"]["status"] == s for n in notes) for s in STATUS}
    filters = ['<button class="filter" data-status="all" aria-pressed="true">全部 ' + str(len(notes)) + '</button>']
    filters += [f'<button class="filter" data-status="{s}" aria-pressed="false">{STATUS[s]} {s} {counts[s]}</button>'
                for s in STATUS]
    cards = []
    for n in notes:
        m = n["meta"]
        cards.append(f"""<article class="card" data-status="{m['status']}">
  <div class="card-head">{badge(m['status'])}<time>{m['updated']}</time></div>
  <h2><a href="notes/{m['slug']}.html">{html.escape(m['title'])}</a></h2>
  <p>{html.escape(m['summary'])}</p>
  <p class="concept">概念｜{html.escape(m[CONCEPT])}</p>
  <div class="chips">{chips(m, '', 8)}</div>
</article>""")
    body = f"""<section class="intro">
  <h1>作圖想法筆記</h1>
  <p>想畫的畫面先記下來，再慢慢試。每則想法拆成背景、服裝、事件三個具體元素，再加上一個不用很具體的概念，方便看出哪些組合已經用過、哪些還沒試。</p>
</section>
<div class="filters" role="group" aria-label="依狀態篩選">{''.join(filters)}</div>
<section class="cards">
{''.join(cards) if cards else '<p class="muted">還沒有公開的想法。</p>'}
</section>"""
    return page("全部想法", body, "", "index")


def render_note(n: dict, notes: list[dict]) -> str:
    m = n["meta"]
    rows = "".join(
        f'<tr><th>{d}</th><td>{"".join(f"<a class=chip href=../elements.html#{html.escape(d)}-{html.escape(t)}>{html.escape(t)}</a>" for t in m[d]) or "<span class=muted>—</span>"}</td></tr>'
        for d in DIMS) + f'<tr class="concept-row"><th>{CONCEPT}</th><td>{html.escape(m[CONCEPT])}</td></tr>'
    sims = sorted(
        ((jaccard(n["feat"], o["feat"]), o) for o in notes if o is not n), key=lambda x: -x[0])
    sims = [(s, o) for s, o in sims if s >= SIMILAR_MIN][:3]
    sim_html = ""
    if sims:
        items = "".join(
            f'<li><a href="{o["meta"]["slug"]}.html">{html.escape(o["meta"]["title"])}</a>'
            f'<span class="muted">　相同元素：{"、".join(t for _, t in sorted(n["feat"] & o["feat"]))}</span></li>'
            for s, o in sims)
        sim_html = f'<section class="similar"><h2>相似的想法</h2><ul>{items}</ul></section>'
    body = f"""<p class="back"><a href="../index.html">← 全部想法</a></p>
<article class="note">
  <div class="card-head">{badge(m['status'])}<time>建立 {m['created']} · 更新 {m['updated']}</time></div>
  <h1>{html.escape(m['title'])}</h1>
  <p class="summary">{html.escape(m['summary'])}</p>
  <table class="elements">{rows}</table>
  {md_to_html(n['body'])}
</article>
{sim_html}"""
    return page(m["title"], body, "../", "")


def render_elements(notes: list[dict], vocab: dict) -> str:
    parts = []
    for d in DIMS:
        used: dict[str, list[dict]] = {}
        for n in notes:
            for t in n["meta"][d]:
                used.setdefault(t, []).append(n)
        rows = []
        for t in sorted(used, key=lambda t: (-len(used[t]), vocab[d].index(t))):
            links = "、".join(f'<a href="notes/{x["meta"]["slug"]}.html">{html.escape(x["meta"]["title"])}</a>' for x in used[t])
            rows.append(f'<li id="{html.escape(d)}-{html.escape(t)}"><span class="term">{html.escape(t)}</span>'
                        f'<span class="count">{len(used[t])}</span><span class="where">{links}</span></li>')
        unused = [t for t in vocab[d] if t not in used]
        unused_html = "".join(f'<span class="chip unused" id="{html.escape(d)}-{html.escape(t)}">{html.escape(t)}</span>' for t in unused)
        parts.append(f"""<section class="dim" id="{d}">
  <h2>{d}<span class="muted">　用過 {len(used)} / 詞庫 {len(vocab[d])}</span></h2>
  <ul class="used">{''.join(rows) or '<li class="muted">還沒用過任何詞</li>'}</ul>
  <div class="unused-wrap"><span class="label">還沒用過</span>{unused_html or '<span class="muted">全部用過了</span>'}</div>
</section>""")
    concepts = "".join(
        f'<li><span class="term">{html.escape(n["meta"][CONCEPT])}</span>'
        f'<a href="notes/{n["meta"]["slug"]}.html">{html.escape(n["meta"]["title"])}</a></li>'
        for n in notes)
    parts.append(f"""<section class="dim" id="{CONCEPT}">
  <h2>{CONCEPT}<span class="muted">　不進詞庫，每則一句話</span></h2>
  <ul class="concepts">{concepts or '<li class="muted">還沒有</li>'}</ul>
</section>""")
    body = f"""<section class="intro">
  <h1>元素索引</h1>
  <p>背景、服裝、事件用過幾次、出現在哪些想法裡。灰色的是詞庫裡還沒用過的，可以當成下一張圖的靈感。最下面是每則想法的概念。</p>
</section>
{''.join(parts)}"""
    return page("元素索引", body, "", "elements")


def render_rules() -> str:
    md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    body = f'<article class="note rules">{md_to_html(md)}</article>'
    return page("規則", body, "", "rules")


# ───────────────────────── 主流程 ─────────────────────────

def main() -> int:
    vocab = load_vocab()
    errors: list[str] = []
    notes: list[dict] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        try:
            meta, body = parse_front_matter(path.read_text(encoding="utf-8"), path.name)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        errs = check_note(meta, body, path, vocab)
        errors += errs
        if not errs:
            notes.append({"meta": meta, "body": body, "feat": features(meta)})

    slugs = [n["meta"]["slug"] for n in notes]
    dup = {s for s in slugs if slugs.count(s) > 1}
    if dup:
        errors.append(f"slug 重複：{sorted(dup)}")

    if errors:
        print("❌ 規則檢查沒過，docs/ 沒有更新：")
        for e in errors:
            print("  -", e)
        return 1

    for i, a in enumerate(notes):
        for b in notes[i + 1:]:
            s = jaccard(a["feat"], b["feat"])
            if s >= DUPLICATE_WARN:
                print(f"⚠ 可能重複：{a['meta']['slug']} 與 {b['meta']['slug']}（相似度 {s:.2f}）")

    notes.sort(key=lambda n: (n["meta"]["updated"], n["meta"]["created"]), reverse=True)

    if DOCS.exists():
        shutil.rmtree(DOCS)
    (DOCS / "notes").mkdir(parents=True)
    shutil.copytree(ASSETS, DOCS / "assets")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    (DOCS / "index.html").write_text(render_index(notes), encoding="utf-8")
    (DOCS / "elements.html").write_text(render_elements(notes, vocab), encoding="utf-8")
    (DOCS / "rules.html").write_text(render_rules(), encoding="utf-8")
    for n in notes:
        (DOCS / "notes" / f"{n['meta']['slug']}.html").write_text(render_note(n, notes), encoding="utf-8")

    print(f"✅ 建置完成：{len(notes)} 則公開筆記 → docs/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
