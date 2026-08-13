"""Build clean print-friendly HTML from competition markdown files."""
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

# Regex for table alignment separator row: e.g. |---|:---:|----|
_RE_SEP = re.compile(r"^:?-+?:?$")


def md2html(text):
    lines_out = []
    paragraphs = []

    # State machines
    table_rows = []
    prev_row = None        # row before a potential separator (candidate header)
    in_code = False
    list_items = []        # accumulating <li> strings
    meta_lines = []        # accumulating metadata blockquote lines

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

        # -- code blocks --
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

        # -- blank line: flush inline accumulators --
        if not stripped:
            flush_all()
            lines_out.append("")
            continue

        # -- HR --
        if stripped == "---":
            flush_all()
            lines_out.append("<hr>")
            continue

        # -- headings --
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

        # -- blockquote (consecutive -> single .meta or blockquote) --
        if line.startswith("> "):
            flush_list()
            flush_paragraphs()
            flush_table()
            meta_lines.append(_inline(line[2:]))
            continue

        # End of consecutive blockquote region
        if meta_lines:
            # Determine: if at the start of doc (lines_out is mostly empty), use meta card
            # Check if this is likely the header metadata region
            content_so_far = "".join(lines_out).strip()
            if not content_so_far or content_so_far.startswith("<h1"):
                # metadata card
                body = "<br>".join(meta_lines)
                lines_out.append(f'<div class="meta">{body}</div>')
            else:
                # regular blockquote later in doc
                body = "<br>".join(meta_lines)
                lines_out.append(f"<blockquote>{body}</blockquote>")
            meta_lines = []

        # -- table rows --
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            flush_paragraphs()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # Is this a separator row?
            if all(_RE_SEP.match(c) for c in cells):
                # Mark the previous row as header
                if prev_row is not None:
                    table_rows[-1] = prev_row.replace("<td>", "<th>").replace("</td>", "</th>")
                prev_row = None
                continue

            # Regular row
            tags = ["<td>", "</td>"]
            row_html = "".join(f"<td>{_inline(c)}</td>" for c in cells)
            table_rows.append(f"<tr>{row_html}</tr>")
            prev_row = row_html  # remember for potential header promotion
            continue

        # Non-table: flush pending table
        if table_rows:
            flush_table()

        # -- list items --
        list_match = re.match(r"^(\d+)[\.\、]\s+(.+)", stripped)
        if list_match:
            flush_paragraphs()
            list_items.append(f"<strong>{list_match.group(1)}.</strong> {_inline(list_match.group(2))}")
            continue

        if re.match(r"^[-*]\s+", stripped):
            flush_paragraphs()
            list_items.append(_inline(re.sub(r"^[-*]\s+", "", stripped)))
            continue

        # End of list region
        if list_items:
            flush_list()

        # -- regular paragraph --
        paragraphs.append(_inline(line))

    # End of file — flush everything
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
