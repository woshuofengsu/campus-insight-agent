"""把比赛用的 markdown 转成适合打印的干净 HTML。"""
import re
import os

BASE = os.path.dirname(os.path.abspath(__file__))

CSS = """<style>
  :root {
    --text: #1a1a1a; --text2: #555;
    --accent: #2563eb; --border: #d0d0d0;
    --bg: #fff; --code-bg: #f5f5f5;
    --th-bg: #f0f4ff;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: "PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif;
    background: var(--bg); color: var(--text);
    padding: 40px 36px; max-width: 900px; margin: 0 auto;
    line-height: 1.9; font-size: 15px;
  }
  h1 {
    font-size: 1.7em; text-align:center; margin: 0 0 8px 0;
    letter-spacing: 0.04em; font-weight: 700;
  }
  h2 {
    font-size: 1.2em; color: var(--accent); margin: 36px 0 14px;
    padding-bottom: 8px; border-bottom: 2px solid var(--accent);
    font-weight: 700;
  }
  h3 {
    font-size: 1.05em; color: var(--text); margin: 24px 0 10px;
    font-weight: 700;
  }
  h4 { font-size: 0.95em; color: #444; margin: 18px 0 8px; font-weight: 600; }

  /* -- metadata card -- */
  .meta {
    background: #fafafa; border: 1px solid var(--border);
    border-radius: 6px; padding: 14px 20px; margin: 16px auto 24px;
    max-width: 580px; font-size: 0.9em; line-height: 1.8; color: #444;
  }
  .meta strong { color: #222; }
  .meta a { color: var(--accent); }

  /* -- tables -- */
  table {
    border-collapse:collapse; width:100%; margin: 12px 0 18px;
    font-size: 0.88em; line-height: 1.6;
  }
  th, td { padding: 8px 12px; border: 1px solid var(--border); text-align:left; vertical-align: top; }
  th { background: var(--th-bg); color: var(--accent); font-weight:700; white-space: nowrap; }
  tr:nth-child(even) td { background: #fafafa; }

  /* -- code -- */
  code {
    background: var(--code-bg); color: #d63384;
    padding: 1px 5px; border-radius: 3px; font-size: 0.9em;
  }
  pre {
    background: #f8f8f8; border: 1px solid var(--border);
    border-radius: 6px; padding: 16px 20px; overflow-x: auto;
    font-size: 0.82em; line-height: 1.55; margin: 12px 0 18px;
    font-family: "SF Mono","Cascadia Code","Consolas",monospace;
  }
  pre code { background: none; color: inherit; padding: 0; }

  /* -- lists -- */
  ul, ol { padding-left: 22px; margin: 6px 0 12px; }
  li { margin: 2px 0; line-height: 1.8; }

  /* -- blockquote -- */
  blockquote {
    background: #fafafa; border-left: 3px solid var(--accent);
    padding: 10px 16px; margin: 10px 0; color: #555;
    font-size: 0.9em;
  }
  blockquote strong { color: #333; }

  hr { border: none; border-top: 1px solid #ddd; margin: 28px 0; }

  strong { color: #111; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }

  .footer {
    margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd;
    text-align: center; color: #999; font-size: 0.82em;
  }

  @media (max-width: 640px) {
    body { padding: 20px 16px; font-size: 14px; }
    .meta { max-width: 100%; }
    table { font-size: 0.78em; }
    th, td { padding: 5px 7px; }
  }
  @media print {
    body { max-width: 100%; padding: 0; }
    .meta { background: none; border: 1px solid #ccc; }
    pre { background: none; border: 1px solid #ccc; }
  }
</style>"""

TASKS = [
    (os.path.join(BASE, "创意说明书.md"), "社区先知 · 创意说明书"),
    (os.path.join(BASE, "技术实现报告.md"), "社区先知 · 技术实现报告"),
]

# 匹配表格对齐分隔行，比如 |---|:---:|----|
_RE_SEP = re.compile(r"^:?-+?:?$")


def md2html(text):
    lines_out = []
    paragraphs = []

    # 各种状态累积器
    table_rows = []
    prev_row = None        # 分隔行前面那行，可能是表头
    in_code = False
    list_items = []        # 攒 <li> 字符串
    meta_lines = []        # 攒元信息引用块的行

    def flush_meta():
        nonlocal meta_lines
        if meta_lines:
            body = "<br>".join(meta_lines)
            lines_out.append(f'<div class="meta">{body}</div>')
            meta_lines = []

    def flush_list():
        nonlocal list_items
        if list_items:
            lines_out.append("<ul>")
            for li in list_items:
                lines_out.append(f"<li>{li}</li>")
            lines_out.append("</ul>")
            list_items = []

    def flush_paragraphs():
        nonlocal paragraphs
        if paragraphs:
            lines_out.append(f"<p>{'<br>'.join(paragraphs)}</p>")
            paragraphs = []

    def flush_table():
        nonlocal table_rows, prev_row
        if not table_rows:
            prev_row = None
            return
        lines_out.append("<table>")
        for tr in table_rows:
            lines_out.append(tr)
        lines_out.append("</table>")
        table_rows = []
        prev_row = None

    def flush_all():
        flush_meta()
        flush_list()
        flush_paragraphs()
        flush_table()

    for line in text.split("\n"):
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            flush_all()
            if in_code:
                lines_out.append("</pre>")
                in_code = False
            else:
                lines_out.append("<pre>")
                in_code = True
            continue
        if in_code:
            lines_out.append(
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            continue

        # 空行：把攒的内容一次性吐出来
        if not stripped:
            flush_all()
            lines_out.append("")
            continue

        # 分隔线
        if stripped == "---":
            flush_all()
            lines_out.append("<hr>")
            continue

        # 标题
        heading = False
        for level, tag in [(4, "h4"), (3, "h3"), (2, "h2"), (1, "h1")]:
            prefix = "#" * level + " "
            if line.startswith(prefix):
                flush_all()
                lines_out.append(f"<{tag}>{_inline(line[len(prefix):])}</{tag}>")
                heading = True
                break
        if heading:
            continue

        # 连续的引用块合并成一个 .meta 卡片或 blockquote
        if line.startswith("> "):
            flush_list()
            flush_paragraphs()
            flush_table()
            meta_lines.append(_inline(line[2:]))
            continue

        # 引用块区域结束
        if meta_lines:
            # 文档开头（前面基本没内容）就当元信息卡片，否则是正文里的引用
            content_so_far = "".join(lines_out).strip()
            if not content_so_far or content_so_far.startswith("<h1"):
                # 元信息卡片
                body = "<br>".join(meta_lines)
                lines_out.append(f'<div class="meta">{body}</div>')
            else:
                # 文档后面的普通引用块
                body = "<br>".join(meta_lines)
                lines_out.append(f"<blockquote>{body}</blockquote>")
            meta_lines = []

        # 表格行
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            flush_paragraphs()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # 是不是分隔行？
            if all(_RE_SEP.match(c) for c in cells):
                # 把上一行升级成表头
                if prev_row is not None:
                    table_rows[-1] = prev_row.replace("<td>", "<th>").replace("</td>", "</th>")
                prev_row = None
                continue

            # 普通数据行
            tags = ["<td>", "</td>"]
            row_html = "".join(f"<td>{_inline(c)}</td>" for c in cells)
            table_rows.append(f"<tr>{row_html}</tr>")
            prev_row = row_html  # 记住这行，下一条可能是分隔行
            continue

        # 不是表格内容了，把攒着的表格先输出
        if table_rows:
            flush_table()

        # 列表项
        list_match = re.match(r"^(\d+)[\.\、]\s+(.+)", stripped)
        if list_match:
            flush_paragraphs()
            list_items.append(f"<strong>{list_match.group(1)}.</strong> {_inline(list_match.group(2))}")
            continue

        if re.match(r"^[-*]\s+", stripped):
            flush_paragraphs()
            list_items.append(_inline(re.sub(r"^[-*]\s+", "", stripped)))
            continue

        # 列表区域结束
        if list_items:
            flush_list()

        # 普通段落
        paragraphs.append(_inline(line))

    # 文件读完，把剩下的全输出
    flush_all()

    return "\n".join(lines_out)


def _inline(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def build(md_file, title):
    with open(md_file, "r", encoding="utf-8") as f:
        body = md2html(f.read())

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — 社区先知 CommunityInsight Agent</title>
{CSS}
</head>
<body>
{body}
<div class="footer">
社区先知 CommunityInsight Agent · 2026 京彩AI·智汇全球 · 基层治理赛道<br>
作者：步承泽
</div>
</body>
</html>"""

    out = md_file.replace(".md", ".html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Created: {out}")


if __name__ == "__main__":
    for md_file, title in TASKS:
        build(md_file, title)
    print("Done!")
