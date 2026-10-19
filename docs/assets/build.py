#!/usr/bin/env python3
"""Generate the front page's assets (README.md and docs/index.md) from the synthetic fixture experiment.

Runs the real CLI (`ingest -> check run -> stats compare -> report`) on `scripts/fixture_export.py`'s experiment in a
temporary directory and writes, next to this script:

- `demo.cast`: the session as an asciicast v2 recording (typed commands, real output), and `demo.svg`: the same
  session as an animated terminal (CSS keyframes, loops; no player needed on GitHub or the docs site);
- `stats-compare.svg`: the `stats compare` output as a still terminal;
- `report.md` and `report-comment[-full]-{dark,light}.html`: the report, and the report rendered as a GitHub
  pull-request comment in GitHub's dark and light palettes, on a 760 px page so it reads inside a docs column: the top
  (the verdict and the Outcome table, for the README and the docs home) and the whole comment (for Reports), then
  the `.png` screenshots of them;
- `suite.svg`: where flightdeck sits in the suite, drawn with agent-factory's diagram conventions (Airframe tokens,
  theme-aware when inlined), then `suite-dark.png` and `suite-light.png`.

The terminals follow Airframe's Terminal component and the diagram's fallbacks are Airframe's Night values, both read
from the vendored `docs/stylesheets/airframe-tokens.json` (`scripts/sync-airframe.sh`), since an SVG shown as an image
cannot load the site's stylesheet. The comment pages use GitHub's own palettes: that is where the report is read.

Everything but the PNGs is byte-reproducible, so CI re-runs this and fails on a diff (`.github/workflows/assets.yml`).
PNGs differ between font stacks, so `sources.sha256` records the hash of the page each PNG was shot from: an input
change without a re-render shows up as a diff there.

    uv run --group assets python docs/assets/build.py [--no-png]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TOKENS = ROOT / "docs/stylesheets/airframe-tokens.json"  # vendored by scripts/sync-airframe.sh
NIGHT: dict[str, str] = json.loads(TOKENS.read_text(encoding="utf-8"))["themes"]["dark"]
EXP, DAY = "job-expdemo", "2025-10-16"
COMMANDS = [
    "flightdeck ingest export export --out plane",
    f"flightdeck check run --data plane --date {DAY} --specs specs",
    f"flightdeck stats compare {EXP} --data plane",
    f"flightdeck report experiment {EXP} --data plane --decision export/decision.yaml --out report.md",
]
COLS, ROWS = 104, 36  # terminal size; output lines wrap at COLS
FONTS = ("https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900"
         "&family=DM+Mono:wght@400;500&family=Red+Hat+Text:wght@400..700&display=swap")


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ---------------------------------------------------------------------------------------------------- the session
def session(tmp: Path) -> list[tuple[str, str]]:
    """Run each command in `tmp` on the fixture experiment; (command, output) pairs."""
    spec = importlib.util.spec_from_file_location("fixture_export", ROOT / "scripts" / "fixture_export.py")
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.build(tmp / "export")
    (tmp / "specs").mkdir()
    shutil.copy(ROOT / "specs" / "examples" / "team-default.yaml", tmp / "specs")
    exe = str(Path(sys.executable).with_name("flightdeck"))
    env = {**os.environ, "COLUMNS": str(COLS), "NO_COLOR": "1", "TERM": "dumb"}
    env.pop("FLIGHTDECK_DATA_URI", None)
    out = []
    for cmd in COMMANDS:
        argv = cmd.split()
        argv[0] = exe if argv[0] == "flightdeck" else argv[0]
        res = subprocess.run(argv, cwd=tmp, env=env, capture_output=True, text=True)
        if res.returncode:
            sys.exit(f"build: `{cmd}` failed ({res.returncode}):\n{res.stdout}{res.stderr}")
        out.append((cmd, (res.stdout + res.stderr).expandtabs(4).rstrip("\n")))
    return out


def wrap(text: str) -> list[str]:
    lines = []
    for line in text.splitlines() or [""]:
        while len(line) > COLS:
            cut = line.rfind(" ", 0, COLS)
            cut = cut if cut > COLS // 2 else COLS
            lines.append(line[:cut])
            line = "  " + line[cut:].lstrip()
        lines.append(line)
    return lines


def timeline(steps: list[tuple[str, str]]) -> tuple[list[tuple[float, str, str]], float]:
    """Screen lines as (time shown, kind, text): kind `cmd` (typed from that time) or `out`. And the total length."""
    t, lines = 0.6, []
    for cmd, output in steps:
        lines.append((t, "cmd", cmd))
        t += len(cmd) * 0.035 + 0.5
        for line in wrap(output):
            lines.append((t, "out", line))
            t += 0.06
        t += 1.6
    lines.append((t, "cmd", ""))
    return lines, t + 4.0


def cast(steps: list[tuple[str, str]]) -> str:
    """asciicast v2 (https://docs.asciinema.org/manual/asciicast/v2/), with fixed timings and no timestamp."""
    head = {"version": 2, "width": COLS, "height": ROWS, "title": "flightdeck: ingest, check, compare, report",
            "env": {"SHELL": "/bin/sh", "TERM": "xterm-256color"}}
    events, t = [], 0.6
    for cmd, output in steps:
        events.append([round(t, 3), "o", "$ "])
        for ch in cmd:
            t += 0.035
            events.append([round(t, 3), "o", ch])
        t += 0.5
        events.append([round(t, 3), "o", "\r\n" + output.replace("\n", "\r\n") + "\r\n"])
        t += 1.6
    events.append([round(t, 3), "o", "$ "])
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in [head, *events]) + "\n"


# ---------------------------------------------------------------------------------------------------- terminal SVG
CW, LH, PAD, BAR = 7.8, 17.0, 18, 34  # char width (0.6em at 13px), line height, padding, title bar
MONO = "'DM Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
LIT = re.compile(r"\bis worse than\b|\b[1-9]\d* failed\b")  # lines a terminal may color: the failed role, never green
VERDICT = re.compile(r"^(\S+ is (better than|non-inferior to|worse than) \S+ on \S+:|No (decision|verdict):)")
TERM_ICON = ('<g fill="none" stroke-width="1.5" stroke-linecap="square" stroke-linejoin="miter" '
             'transform="translate({x},{y}) scale(.7)"><rect x="2.5" y="3.5" width="15" height="13"/>'
             '<path d="M6 8l2.5 2L6 12M10.5 12.5H14"/></g>')  # Airframe's `terminal` icon, 20px grid drawn at 14px


def terminal(lines: list[tuple[float, str, str]], total: float | None, title: str) -> str:
    """A terminal window on Airframe's Terminal contract: always dark, DM Mono on `terminal-bg`, a bar with the product
    and scope in mono capitals, output in `terminal-fg`, the prompt and cursor in `brand`, and color on one kind of line
    only (`terminal-err` for the failed role). The bar reads `title` as `product|scope|scope`. With `total`, lines
    appear at their times and commands type out, looping every `total` seconds; without it, a still of every line."""
    t = NIGHT
    w, h = round(COLS * CW + 2 * PAD), round(BAR + PAD + len(lines) * LH + PAD / 2)
    css = [f".t{{font:13px {MONO};fill:{t['terminal-fg']};white-space:pre}}.p{{fill:{t['brand']}}}"
           f".c{{fill:{t['code-keyword']}}}.x{{fill:{t['terminal-err']}}}"
           f".b{{font:500 10.5px {MONO};letter-spacing:.08em;fill:{t['terminal-dim']}}}.b1{{fill:{t['terminal-fg']}}}"]
    body = [f'<rect width="{w}" height="{h}" rx="4" fill="{t["terminal-bg"]}"/>',
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="4" fill="none" stroke="{t["terminal-fg"]}" '
            f'stroke-opacity=".08"/><path d="M0 {BAR + .5}H{w}" stroke="{t["terminal-fg"]}" stroke-opacity=".09"/>',
            TERM_ICON.format(x=14, y=BAR / 2 - 7).replace('<g ', f'<g stroke="{t["terminal-dim"]}" ', 1)]
    x = 14 + 14 + 14  # icon, gap
    for i, part in enumerate(title.split("|")):
        body.append(f'<text class="b{" b1" if i == 0 else ""}" x="{x}" y="{BAR / 2 + 3.75}">{esc(part.upper())}</text>')
        x += round(len(part) * (10.5 * 0.6 + 0.84)) + 14
    for i, (at, kind, text) in enumerate(lines):
        y = BAR + PAD + (i + 0.75) * LH
        if kind == "cmd":
            n = len(text)
            inner = (f'<tspan class="p">$ </tspan><tspan class="c">{esc(text)}</tspan>' if text
                     else '<tspan class="p">$ ▌</tspan>')
            attrs = f' textLength="{(n + 2) * CW:.1f}" lengthAdjust="spacingAndGlyphs"' if text else ""
            el = f'<text class="t" x="{PAD}" y="{y:.1f}"{attrs}>{inner}</text>'
            if total and text:  # a cover over the command that steps right one character at a time
                x0, d = PAD + 2 * CW, n * 0.035
                body.append(f'<style>@keyframes y{i}{{0%,{100 * at / total:.3f}%{{transform:translateX(0)}}'
                            f'{100 * (at + d) / total:.3f}%,100%{{transform:translateX({n * CW:.1f}px)}}}}'
                            f'.y{i}{{animation:y{i} {total:.2f}s steps({n},end) infinite}}</style>')
                el += (f'<rect class="y{i}" x="{x0:.1f}" y="{y - LH * 0.8:.1f}" width="{n * CW + 4:.1f}" '
                       f'height="{LH:.1f}" fill="{t["terminal-bg"]}"/>')
        else:  # the verdict is the brightest line; a regression is the only red
            cls = "t x" if LIT.search(text) else "t c" if VERDICT.match(text) else "t"
            el = f'<text class="{cls}" x="{PAD}" y="{y:.1f}">{esc(text)}</text>'
        if total:
            css.append(f"@keyframes s{i}{{0%,{100 * at / total:.3f}%{{opacity:0}}"
                       f"{100 * at / total + 0.001:.3f}%,100%{{opacity:1}}}}.s{i}{{animation:s{i} {total:.2f}s "
                       "step-end infinite}")
            el = f'<g class="s{i}">{el}</g>'
        body.append(el)
    label = title.replace("|", ", ")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{esc(label)}"><style>{"".join(css)}</style>{"".join(body)}</svg>\n')


# ---------------------------------------------------------------------------------------------------- the PR comment
# GitHub's own palettes (primer, 2025): the report is read as a comment on github.com, so the picture shows that frame.
GH = {"light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "line": "#d1d9e0", "well": "#f6f8fa",
                "code": "#818b981f", "fade": "rgba(255,255,255,0)"},
      "dark": {"bg": "#0d1117", "fg": "#f0f6fc", "muted": "#9198a1", "line": "#3d444d", "well": "#151b23",
               "code": "#656c7633", "fade": "rgba(13,17,23,0)"}}
GH_CSS = """
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",
"Noto Sans",Helvetica,Arial,sans-serif}.page{width:var(--w);padding:24px 28px}.row{display:flex;gap:14px}
.avatar{width:40px;height:40px;border-radius:50%;background:var(--well);border:1px solid var(--line);
box-sizing:border-box;flex:none;color:var(--muted);text-align:center;
font:600 14px/38px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.comment{flex:1;border:1px solid var(--line);border-radius:6px;overflow:hidden}.head{background:var(--well);
border-bottom:1px solid var(--line);padding:8px 16px;color:var(--muted);font-size:14px}.head b{color:var(--fg)}
.md{padding:16px}.md h2{font-size:1.5em;border-bottom:1px solid var(--line);padding-bottom:.3em;margin:0 0 16px;
font-weight:600}.md h3{font-size:1.25em;margin:24px 0 12px;font-weight:600}.md p{margin:0 0 12px}
.md code{font:85% ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);
padding:.2em .4em;border-radius:6px}.md table{border-collapse:collapse;margin:0 0 14px;display:block;
width:max-content;max-width:100%;overflow:auto}.md th,.md td{border:1px solid var(--line);padding:6px 13px}
.md th{font-weight:600}.md tr:nth-child(2n){background:var(--well)}.fade{position:relative}
.fade:after{content:"";position:absolute;left:0;right:0;bottom:0;height:90px;
background:linear-gradient(var(--fade),var(--bg))}
"""


def comment_page(report: str, theme: str, top: bool) -> str:
    """The report as GitHub renders a PR comment (GFM tables, the hidden marker stays hidden) in that GitHub theme:
    with `top`, only the verdict and the Outcome table, fading out; otherwise the whole comment. A 760 px page (GitHub's
    is 880) so the text still reads once a 686 px docs column scales it."""
    from markdown_it import MarkdownIt

    body = MarkdownIt("commonmark", {"html": True}).enable("table").render(report.split("\n### Process")[0] if top
                                                                           else report)
    root = ";".join(f"--{k}:{v}" for k, v in GH[theme].items()) + ";--w:760px"
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>:root{{{root}}}{GH_CSS}</style></head><body>'
            '<div class="page"><div class="row"><div class="avatar">fd</div><div class="comment"><div class="head">'
            f'<b>dev-a</b> commented</div><div class="md{" fade" if top else ""}">{body}</div></div></div></div>'
            "</body></html>\n")


# ---------------------------------------------------------------------------------------------------- the diagram
def diagram() -> str:
    """Where flightdeck sits: hangar runs, flightdeck judges, the pull request decides (agent-factory's conventions:
    `scripts/diagrams.py` there; every color an Airframe token with its dark fallback)."""
    v = {k: f"var(--af-{t}, {NIGHT[t]})" for k, t in {
        "canvas": "canvas", "raised": "raised", "surface": "surface", "line": "line-strong", "fg": "fg",
        "muted": "fg-muted", "subtle": "fg-subtle", "brand": "brand-line", "rule": "line", "fd": "product-flightdeck",
        "hangar": "product-hangar", "ws": "product-tower"}.items()}
    font = {"name": "700 17px Archivo,'Helvetica Neue',Arial,sans-serif", "body":
            "400 12.5px 'Red Hat Text','Helvetica Neue',Arial,sans-serif", "lbl": "500 10.5px 'DM Mono',ui-monospace,"
            "Menlo,monospace", "small": "700 13px Archivo,'Helvetica Neue',Arial,sans-serif"}
    style = (f".fd-d .n{{font:{font['name']};font-stretch:125%;fill:{v['fg']}}}"
             f".fd-d .s{{font:{font['small']};font-stretch:125%;fill:{v['fg']}}}"
             f".fd-d .b{{font:{font['body']};fill:{v['muted']}}}.fd-d .e{{font:{font['body']};fill:{v['subtle']}}}"
             f".fd-d .l{{font:{font['lbl']};letter-spacing:.08em;fill:{v['subtle']}}}"
             f".fd-d .edge{{fill:none;stroke:{v['subtle']};stroke-width:1.25}}"
             f".fd-d .plan{{fill:none;stroke:{v['subtle']};stroke-width:1.25;stroke-dasharray:5 4}}")
    out: list[str] = []

    def box(x: int, y: int, w: int, h: int, eyebrow: str, name: str, lines: tuple[str, ...], hue: str | None,
            kind: str = "raised") -> None:
        stroke = {"hub": f' stroke="{v["brand"]}" stroke-width="1.5"', "plan": f' stroke="{v["line"]}" '
                  'stroke-dasharray="4 4" fill-opacity="0"'}.get(kind, f' stroke="{v["rule"]}"')
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{v["raised"]}"{stroke}/>')
        if hue:
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="2" fill="{v[hue]}"/>')
        out.append(f'<text class="l" x="{x + 18}" y="{y + 26}">{esc(eyebrow)}</text>'
                   f'<text class="n" x="{x + 18}" y="{y + 50}">{esc(name)}</text>')
        out.extend(f'<text class="b" x="{x + 18}" y="{y + 74 + 19 * i}">{esc(t)}</text>' for i, t in enumerate(lines))

    def step(x: int, y: int, name: str, sub: str) -> None:
        out.append(f'<rect x="{x}" y="{y}" width="300" height="52" rx="3" fill="{v["surface"]}" stroke="{v["line"]}"/>'
                   f'<text class="s" x="{x + 14}" y="{y + 21}">{esc(name)}</text>'
                   f'<text class="b" x="{x + 14}" y="{y + 40}">{esc(sub)}</text>')

    def edge(d: str, label: str, lx: int, ly: int, cls: str = "edge", anchor: str = "middle") -> None:
        out.append(f'<path class="{cls}" d="{d}" marker-end="url(#fd-arrow)"/>')
        out.extend(f'<text class="e" x="{lx}" y="{ly + 16 * i}" text-anchor="{anchor}">{esc(t)}</text>'
                   for i, t in enumerate(label.split("|")))

    w, h = 1200, 600
    out.append(f'<rect width="{w}" height="{h}" fill="{v["canvas"]}"/>')
    out.append('<text class="l" x="40" y="44">WHERE FLIGHTDECK SITS · RUN / JUDGE / GOVERN</text>')
    box(30, 90, 270, 300, "RUN", "hangar", ("runs coding agents in sandboxes", "records manifests, traces and",
                                              "the experiment index", "runs the trials it is asked for,",
                                              "pinned; does no analysis"), "hangar")
    box(430, 70, 360, 380, "JUDGE", "flightdeck", (), "fd", "hub")
    for i, (name, sub) in enumerate((("ingest", "hangar REST or an experiment export"),
                                     ("data plane", "flightdeck.parquet/v1 · DuckDB"),
                                     ("stats compare · check run", "paired by task · behavior specs"),
                                     ("report", "verdict from a pre-registered rule"))):
        step(460, 140 + 72 * i, name, sub)
        if i:
            out.append(f'<path class="edge" d="M610 {140 + 72 * i - 20} V{140 + 72 * i - 2}" '
                       'marker-end="url(#fd-arrow)"/>')
    box(890, 90, 270, 300, "DECIDE", "the pull request", ("one comment, updated in place",
                                                          "verdict, pins, outcome, cost,", "behavior specs",
                                                          "a reviewer decides; the", "approver is never the author"),
        None)
    edge("M300 200 H426", "manifests, traces,|experiment index", 365, 170)
    edge("M430 330 H304", "trials:|tasks × variants × n", 365, 356)
    edge("M790 381 H886", "report", 838, 371)
    box(430, 490, 730, 80, "GOVERN · PLANNED", "Tower: policy decisions, approvals, receipts", (),
        "ws", "plan")
    edge("M1025 390 V486", "promotion approval", 1035, 446, "plan", "start")
    defs = (f'<defs><marker id="fd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{v["subtle"]}"/></marker></defs>')
    return (f'<svg class="fd-d" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Where flightdeck sits: hangar runs, flightdeck judges, the pull request decides">'
            f"<style>{style}</style>{defs}{''.join(out)}</svg>\n")


def diagram_page(svg: str, theme: str) -> str:
    css = (ROOT / "docs" / "stylesheets" / "airframe.css").read_text(encoding="utf-8")
    return (f'<!doctype html><html data-theme="{theme}"><head><meta charset="utf-8"><link rel="stylesheet" '
            f'href="{FONTS}"><style>{css}html,body{{margin:0;background:var(--af-canvas)}}'
            f"svg{{display:block;width:1200px;height:auto}}</style></head><body>{svg}</body></html>\n")


# ---------------------------------------------------------------------------------------------------- main
def shoot(pages: dict[str, tuple[str, str]]) -> None:
    """PNG per page: {png name: (html, selector)}, with Playwright's Chromium."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        tab = browser.new_context(device_scale_factor=2, viewport={"width": 1200, "height": 900}).new_page()
        for name, (page, selector) in pages.items():
            tab.set_content(page, wait_until="networkidle")
            tab.evaluate("document.fonts.ready")
            el = tab.locator(selector).first
            el.screenshot(path=str(HERE / name))
            box = el.bounding_box() or {}
            print(f"build: {name} is {box.get('width', 0):.0f}×{box.get('height', 0):.0f} css px")
            print("build: wrote", name)
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-png", action="store_true", help="Skip the Playwright screenshots.")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        steps = session(Path(d))
        report = (Path(d) / "report.md").read_text(encoding="utf-8")
    lines, total = timeline(steps)
    files = {
        "demo.cast": cast(steps),
        "demo.svg": terminal(lines, total, "flightdeck|fixture experiment|12 tasks × 2 variants × 3 trials"),
        "stats-compare.svg": terminal([(0, "cmd", steps[2][0])] + [(0, "out", x) for x in wrap(steps[2][1])], None,
                                      "flightdeck|stats compare"),
        "report.md": report,
        **{f"report-comment{k}-{t}.html": comment_page(report, t, not k) for k in ("", "-full")
           for t in ("dark", "light")},
        "suite.svg": diagram(),
    }
    pages = {**{f"report-comment{k}-{t}.png": (files[f"report-comment{k}-{t}.html"], "div.page") for k in ("", "-full")
                for t in ("dark", "light")},
             **{f"suite-{t}.png": (diagram_page(files["suite.svg"], t), "svg") for t in ("dark", "light")}}
    files["sources.sha256"] = "".join(f"{hashlib.sha256(p.encode()).hexdigest()}  {n}\n"
                                      for n, (p, _) in sorted(pages.items()))
    for name, text in files.items():
        (HERE / name).write_text(text, encoding="utf-8")
        print("build: wrote", name)
    if not args.no_png:
        shoot(pages)


if __name__ == "__main__":
    main()
