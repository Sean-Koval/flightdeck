#!/usr/bin/env python3
"""Generate the front pages' assets (README.md, docs/index.md, docs/getting-started.md) from the fixture experiment.

Runs the real CLI (`ingest -> check run -> stats compare -> report`) on `scripts/fixture_export.py`'s experiment in a
temporary directory, under the quickstart's paths (`demo/export`, `demo/plane`), and writes, next to this script:

- `demo.cast`: the session as an asciicast v2 recording (typed commands, real output), and `demo.svg`: the same
  session as an animated terminal (CSS keyframes; no player needed on GitHub or the docs site). The recording shows
  `ingest -> stats compare -> report` (`check run` feeds the report's Behavior specs section but is not shown), opens
  on the finished session with the verdict, holds it for `HOLD` seconds, then replays the typing; the loop is under
  20 s and 80 columns wide, so it reads at the hero's width; `demo-still.svg`: its finished frame, for the README;
  `demo-phone.svg`: the key lines (the paired difference, the power line, the verdict) as a still 44 columns wide,
  which the README and the docs home show on screens under 600 px so the text stays 13 px;
- `stats-compare.svg`: the `stats compare` output as a still terminal;
- `report.md` and `report-comment[-full]-{dark,light}.html`: the report, and the report rendered as a GitHub
  pull-request comment in GitHub's dark and light palettes, on a 760 px page so it reads inside a docs column: the top
  (the verdict and the Outcome table, for the README and the docs home) and the whole comment (for Reports), then
  the `.png` screenshots of them, shown at their native 816 px; `report-comment-phone-{dark,light}`: the comment's top
  (verdict, experiment, rule) in GitHub's narrow layout, 358 px wide, for screens under 600 px;
- `clip.mp4`, `clip-light.mp4` and their `-poster.png`: the demo clip, Night and Day, from `clip-{dark,light}.html`:
  `stats compare` in a terminal, then `report` and its verdict, then the same report as the pull-request comment,
  about 18 s at 680 px and 2x (needs ffmpeg);
- `suite.svg`: where flightdeck sits in the suite, and `flow-data-plane.svg`, `flow-experiment.svg`,
  `flow-holdout.svg` and `paired-by-task.svg` for the guides, drawn with agent-factory's diagram conventions
  (Airframe tokens with Night fallbacks, so they follow the theme when inlined with `--8<--`), with theme-v12's
  sentence-case sans labels and radii (`radius-card` boxes, `radius-control` steps).

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
COMMANDS = [  # (command, shown in the recording); the paths are the quickstart's (README, docs/getting-started.md)
    ("flightdeck ingest export demo/export --out demo/plane", True),
    (f"flightdeck check run --data demo/plane --date {DAY} --specs specs/examples/team-default.yaml", False),
    (f"flightdeck stats compare {EXP} --data demo/plane", True),
    (f"flightdeck report experiment {EXP} --data demo/plane \\\n"
     "    --decision demo/export/decision.yaml --out demo/report.md", True),  # two lines, as the quickstart shows it
]
COLS, ROWS = 80, 30  # terminal size; output lines wrap at COLS
PHONE_COLS = 44  # the phone still's width: 44 columns read at 13 px in a 360 px column
HOLD = 5.0  # seconds the finished session (with the verdict) shows before the typing replays
FONTS = ("https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900"
         "&family=DM+Mono:wght@400;500&family=Red+Hat+Text:wght@400..700&display=swap")


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ---------------------------------------------------------------------------------------------------- the session
def session(tmp: Path) -> list[tuple[str, str]]:
    """Run each command in `tmp` on the fixture experiment; the shown ones as (command, output) pairs."""
    spec = importlib.util.spec_from_file_location("fixture_export", ROOT / "scripts" / "fixture_export.py")
    assert spec and spec.loader
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.build(tmp / "demo" / "export")
    shutil.copytree(ROOT / "specs" / "examples", tmp / "specs" / "examples")
    exe = str(Path(sys.executable).with_name("flightdeck"))
    env = {**os.environ, "COLUMNS": str(COLS), "NO_COLOR": "1", "TERM": "dumb"}
    env.pop("FLIGHTDECK_DATA_URI", None)
    out = []
    for cmd, shown in COMMANDS:
        argv = cmd.replace("\\\n", " ").split()
        argv[0] = exe if argv[0] == "flightdeck" else argv[0]
        res = subprocess.run(argv, cwd=tmp, env=env, capture_output=True, text=True)
        if res.returncode:
            sys.exit(f"build: `{cmd}` failed ({res.returncode}):\n{res.stdout}{res.stderr}")
        out += [(cmd, (res.stdout + res.stderr).expandtabs(4).rstrip("\n"))] if shown else []
    return out


def wrap(text: str, cols: int = COLS) -> list[str]:
    lines = []
    for line in text.splitlines() or [""]:
        while len(line) > cols:
            cut = line.rfind(" ", 0, cols)
            cut = cut if cut > cols // 2 else cols
            lines.append(line[:cut])
            line = "  " + line[cut:].lstrip()
        lines.append(line)
    return lines


def timeline(steps: list[tuple[str, str]]) -> tuple[list[tuple[float, str, str]], float]:
    """Screen lines as (time shown in the replay, kind, text): kind `cmd` (typed from that time) or `out`. And the
    replay's length; the loop is `HOLD` seconds of the finished frame, then the replay."""
    t, lines = 0.3, []
    for cmd, output in steps:
        for j, part in enumerate(cmd.split("\n")):  # a continuation line is typed after a `> ` prompt
            lines.append((t, "cmd" if j == 0 else "cmd2", part))
            t += len(part) * 0.03
        t += 0.4
        for line in wrap(output):
            lines.append((t, "out", line))
            t += 0.05
        t += 1.2
    lines.append((t, "cmd", ""))
    return lines, t + 0.5


def cast(steps: list[tuple[str, str]]) -> str:
    """asciicast v2 (https://docs.asciinema.org/manual/asciicast/v2/), with fixed timings and no timestamp."""
    head = {"version": 2, "width": COLS, "height": ROWS, "title": "flightdeck: ingest, compare, report",
            "env": {"SHELL": "/bin/sh", "TERM": "xterm-256color"}}
    events, t = [], 0.3
    for cmd, output in steps:
        events.append([round(t, 3), "o", "$ "])
        for ch in cmd:
            t += 0.03
            events.append([round(t, 3), "o", "\r\n> " if ch == "\n" else ch])
        t += 0.4
        events.append([round(t, 3), "o", "\r\n" + output.replace("\n", "\r\n") + "\r\n"])
        t += 1.2
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


def terminal(lines: list[tuple[float, str, str]], total: float | None, title: str, cols: int = COLS) -> str:
    """A terminal window on Airframe's Terminal contract: always dark, DM Mono on `terminal-bg`, a bar with the product
    and scope in mono capitals, output in `terminal-fg`, the prompt and cursor in `brand`, and color on one kind of line
    only (`terminal-err` for the failed role). The bar reads `title` as `product|scope|scope`. With `total` (the
    replay's length), the finished session shows first and holds `HOLD` seconds, then lines appear at their times and
    commands type out, looping every `HOLD + total` seconds; without it, a still of every line. `cols` sets the
    width."""
    t = NIGHT
    w, h = round(cols * CW + 2 * PAD), round(BAR + PAD + len(lines) * LH + PAD / 2)
    loop = HOLD + (total or 0)
    pc = lambda sec: f"{100 * sec / loop:.3f}%"  # noqa: E731  a moment in the loop as a keyframe percentage
    css = [f".t{{font:13px {MONO};fill:{t['terminal-fg']};white-space:pre}}.p{{fill:{t['brand']}}}"
           f".c{{fill:{t['code-keyword']}}}.x{{fill:{t['terminal-err']}}}"
           f".b{{font:500 10.5px {MONO};letter-spacing:.08em;fill:{t['terminal-dim']}}}.b1{{fill:{t['terminal-fg']}}}"]
    r = t["radius-card"].removesuffix("px")  # Airframe's Terminal is a card
    body = [f'<rect width="{w}" height="{h}" rx="{r}" fill="{t["terminal-bg"]}"/>',
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{r}" fill="none" stroke="{t["terminal-fg"]}" '
            f'stroke-opacity=".08"/><path d="M0 {BAR + .5}H{w}" stroke="{t["terminal-fg"]}" stroke-opacity=".09"/>',
            TERM_ICON.format(x=14, y=BAR / 2 - 7).replace('<g ', f'<g stroke="{t["terminal-dim"]}" ', 1)]
    x = 14 + 14 + 14  # icon, gap
    for i, part in enumerate(title.split("|")):
        body.append(f'<text class="b{" b1" if i == 0 else ""}" x="{x}" y="{BAR / 2 + 3.75}">{esc(part.upper())}</text>')
        x += round(len(part) * (10.5 * 0.6 + 0.84)) + 14
    for i, (at, kind, text) in enumerate(lines):
        y = BAR + PAD + (i + 0.75) * LH
        if kind.startswith("cmd"):
            n, prompt = len(text), "$ " if kind == "cmd" else "> "
            inner = (f'<tspan class="p">{esc(prompt)}</tspan><tspan class="c">{esc(text)}</tspan>' if text
                     else '<tspan class="p">$ ▌</tspan>')
            attrs = f' textLength="{(n + 2) * CW:.1f}" lengthAdjust="spacingAndGlyphs"' if text else ""
            el = f'<text class="t" x="{PAD}" y="{y:.1f}"{attrs}>{inner}</text>'
            if total and text:  # a cover over the command: off during the hold, back at the replay's start, then it
                x0, d, full = PAD + 2 * CW, n * 0.03, f"transform:translateX({n * CW:.1f}px)"  # steps right per char
                body.append(f'<style>@keyframes y{i}{{0%,{pc(HOLD)}{{{full}}}{pc(HOLD + 0.001)},{pc(HOLD + at)}'
                            f'{{transform:translateX(0)}}{pc(HOLD + at + d)},100%{{{full}}}}}'
                            f'.y{i}{{animation:y{i} {loop:.2f}s steps({n},end) infinite}}</style>')
                el += (f'<rect class="y{i}" x="{x0:.1f}" y="{y - LH * 0.8:.1f}" width="{n * CW + 4:.1f}" '
                       f'height="{LH:.1f}" fill="{t["terminal-bg"]}"/>')
        else:  # the verdict is the brightest line; a regression is the only red
            cls = "t x" if LIT.search(text) else "t c" if VERDICT.match(text) else "t"
            el = f'<text class="{cls}" x="{PAD}" y="{y:.1f}">{esc(text)}</text>'
        if total:  # shown through the hold, hidden from the replay's start until its moment
            css.append(f"@keyframes s{i}{{0%,{pc(HOLD)}{{opacity:1}}{pc(HOLD + 0.001)},{pc(HOLD + at)}{{opacity:0}}"
                       f"{pc(HOLD + at + 0.001)},100%{{opacity:1}}}}.s{i}{{animation:s{i} {loop:.2f}s step-end "
                       "infinite}")
            el = f'<g class="s{i}">{el}</g>'
        body.append(el)
    label = title.replace("|", ", ")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{esc(label)}"><style>{"".join(css)}</style>{"".join(body)}</svg>\n')


def phone(steps: list[tuple[str, str]]) -> list[tuple[float, str, str]]:
    """The key lines for a phone, wrapped at `PHONE_COLS` so they keep the 13 px text at a phone's column width: the
    paired difference and the power line from `stats compare`, then `report` and its verdict."""
    stats, report = (next(s for s in steps if s[0].startswith(p)) for p in ("flightdeck stats", "flightdeck report"))
    keep = [p for p in stats[1].split("\n\n") if p.startswith(("Paired difference", "At "))]
    lines: list[tuple[float, str, str]] = []
    for cmd, output in ((stats[0], "\n\n".join(keep)), (report[0], report[1])):
        parts = [x for part in cmd.split(" \\\n") for x in wrap(part.strip(), PHONE_COLS - 4)]
        lines += [(0, "cmd" if i == 0 else "cmd2", x.strip() + (" \\" if i < len(parts) - 1 else ""))
                  for i, x in enumerate(parts)]
        lines += [(0, "out", x) for x in wrap(output, PHONE_COLS)] + [(0, "out", "")]
    return lines[:-1] + [(0, "cmd", "")]


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


def comment_page(report: str, theme: str, top: bool, phone: bool = False) -> str:
    """The report as GitHub renders a PR comment (GFM tables, the hidden marker stays hidden) in that GitHub theme:
    with `top`, only the verdict and the Outcome table, fading out; otherwise the whole comment. A 760 px page (GitHub's
    is 880), shown at its native 816 px. With `phone`, the comment as GitHub's narrow layout shows it (no avatar
    column) on a 358 px page, cut after the rule, for screens under 600 px."""
    from markdown_it import MarkdownIt

    text = report.split("\n### Outcome")[0] if phone else report.split("\n### Process")[0] if top else report
    body = MarkdownIt("commonmark", {"html": True}).enable("table").render(text)
    root = ";".join(f"--{k}:{v}" for k, v in GH[theme].items()) + (";--w:334px" if phone else ";--w:760px")
    avatar = "" if phone else '<div class="avatar">fd</div>'
    narrow = ".page{padding:12px}.md h2{font-size:1.25em}" if phone else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>:root{{{root}}}{GH_CSS}{narrow}</style></head>'
            f'<body><div class="page"><div class="row">{avatar}<div class="comment"><div class="head">'
            f'<b>dev-a</b> commented</div><div class="md{" fade" if top and not phone else ""}">{body}</div></div>'
            "</div></div>"
            "</body></html>\n")


# --------------------------------------------------------------------------------------------------- the diagrams
# Drawn with agent-factory's conventions (`scripts/diagrams.py` there): every color an Airframe token with its Night
# fallback, so a diagram inlined in a docs page follows the theme and the same file on its own renders dark. Authored
# at 720 px, the width a docs column shows them at, with 13 px body and 11 px labels, so nothing is read scaled down.
# Labels are sentence-case sans (`label-s`; mono is for codes and numbers only), boxes take `radius-card` and steps
# `radius-control`, and flightdeck's box is marked by its place and a `line-strong` edge, never by the brand yellow.
V = {k: f"var(--af-{t}, {NIGHT[t]})" for k, t in {
    "canvas": "canvas", "raised": "raised", "surface": "surface", "line": "line-strong", "fg": "fg",
    "muted": "fg-muted", "subtle": "fg-subtle", "rule": "line", "hangar": "product-hangar",
    "flightdeck": "product-flightdeck", "tower": "product-tower"}.items()}
R_CARD, R_CONTROL = (NIGHT[r].removesuffix("px") for r in ("radius-card", "radius-control"))
SANS, HEAD = "'Red Hat Text','Helvetica Neue',Arial,sans-serif", "Archivo,'Helvetica Neue',Arial,sans-serif"
D_STYLE = (f".fd-d .n{{font:700 15px {HEAD};font-stretch:125%;fill:{V['fg']}}}"
           f".fd-d .s{{font:700 13px {HEAD};font-stretch:125%;fill:{V['fg']}}}"
           f".fd-d .b{{font:400 13px {SANS};fill:{V['muted']}}}.fd-d .e{{font:400 11px {SANS};fill:{V['subtle']}}}"
           f".fd-d .l{{font:500 11px {SANS};fill:{V['subtle']}}}"
           f".fd-d .k{{font:500 11px {MONO};fill:{V['fg']}}}"
           f".fd-d .edge{{fill:none;stroke:{V['subtle']};stroke-width:1.25}}"
           f".fd-d .plan{{fill:none;stroke:{V['subtle']};stroke-width:1.25;stroke-dasharray:5 4}}")


class Diagram:
    """One SVG: `box` (eyebrow, name, body lines), `step` (a small named row), `edge` (an arrow with a label) and
    `text`, then `svg(label)`; `kind` is `raised` (default), `hub` (a `line-strong` edge: flightdeck) or `plan`
    (dashed); `hue` names a product whose 2px marker tops the box."""

    def __init__(self, name: str, w: int, h: int, title: str) -> None:
        self.id, self.w, self.h = name, w, h
        self.out = [f'<rect width="{w}" height="{h}" fill="{V["canvas"]}"/>',
                    f'<text class="l" x="24" y="30">{esc(title)}</text>']

    def box(self, x: int, y: int, w: int, h: int, eyebrow: str, name: str, lines: tuple[str, ...] = (),
            kind: str = "raised", hue: str = "") -> None:
        stroke = {"hub": f' stroke="{V["line"]}"', "plan": f' stroke="{V["line"]}" '
                  'stroke-dasharray="4 4" fill-opacity="0"'}.get(kind, f' stroke="{V["rule"]}"')
        self.out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{R_CARD}" fill="{V["raised"]}"{stroke}/>')
        if hue:  # the product's hue: a 2px marker inset from the corners, as agent-factory's diagrams draw it
            self.out.append(f'<rect x="{x + int(R_CARD)}" y="{y}" width="{w - 2 * int(R_CARD)}" height="2" '
                            f'fill="{V[hue]}"/>')
        if eyebrow:
            self.out.append(f'<text class="l" x="{x + 14}" y="{y + 22}">{esc(eyebrow)}</text>')
        self.out.append(f'<text class="n" x="{x + 14}" y="{y + (44 if eyebrow else 26)}">{esc(name)}</text>')
        top = y + (66 if eyebrow else 48)
        self.out += [f'<text class="b" x="{x + 14}" y="{top + 18 * i}">{esc(t)}</text>' for i, t in enumerate(lines)]

    def step(self, x: int, y: int, w: int, name: str, sub: str = "", h: int = 40) -> None:
        self.out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{R_CONTROL}" fill="{V["surface"]}" '
                        f'stroke="{V["line"]}"/><text class="s" x="{x + 12}" y="{y + (24 if not sub else 18)}">'
                        f'{esc(name)}</text>')
        if sub:
            self.out.append(f'<text class="e" x="{x + 12}" y="{y + 32}">{esc(sub)}</text>')

    def edge(self, d: str, label: str = "", lx: int = 0, ly: int = 0, cls: str = "edge", anchor: str = "middle",
             head: bool = True) -> None:
        end = f' marker-end="url(#{self.id}-arrow)"' if head else ""
        self.out.append(f'<path class="{cls}" d="{d}"{end}/>')
        self.out += [f'<text class="e" x="{lx}" y="{ly + 15 * i}" text-anchor="{anchor}">{esc(t)}</text>'
                     for i, t in enumerate(label.split("|")) if label]

    def text(self, x: int, y: int, text: str, cls: str = "b", anchor: str = "start") -> None:
        self.out.append(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{esc(text)}</text>')

    def svg(self, label: str) -> str:
        defs = (f'<defs><marker id="{self.id}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{V["subtle"]}"/>'
                "</marker></defs>")
        return (f'<svg class="fd-d" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
                f'width="{self.w}" height="{self.h}" style="max-width:100%;height:auto" role="img" '
                f'aria-label="{esc(label)}">'
                f'<style>{D_STYLE}</style>{defs}{"".join(self.out)}</svg>\n')


def suite() -> str:
    """Where flightdeck sits: hangar runs, flightdeck judges, the pull request decides; Tower governs. Three boxes in a
    row, Tower a one-line strip under them, the roles on the eyebrows and each product's hue as a 2px marker
    (theme-v14: hangar teal, Tower azure). Tower is built (policy
    decisions, approvals, signed receipts); only flightdeck's promotion approval through it is planned, so that edge
    alone is dashed and says so."""
    d = Diagram("suite", 720, 420, "Where flightdeck sits · run / judge / decide")
    y, h, bw = 56, 276, 160
    xs = (24, 280, 536)
    d.box(xs[0], y, bw, h, "Run", "hangar", ("runs coding agents", "in sandboxes;", "records manifests,",
                                             "traces and the", "experiment index.", "Runs the trials it",
                                             "is asked for, pinned;", "does no analysis."), hue="hangar")
    d.box(xs[1], y, bw, h, "Judge", "flightdeck", (), "hub", "flightdeck")
    for i, (name, sub) in enumerate((("ingest", "REST or an export"), ("data plane", "Parquet · DuckDB"),
                                     ("stats · check", "paired by task · specs"), ("report", "a pre-registered rule"))):
        d.step(xs[1] + 12, y + 60 + 50 * i, bw - 24, name, sub)
        if i:
            d.edge(f"M{xs[1] + bw // 2} {y + 60 + 50 * i - 10} V{y + 60 + 50 * i - 2}")
    pr = ("one comment, updated", "in place: verdict,", "pins, outcome, cost,", "behavior specs.",
          "A reviewer decides;", "the approver is", "never the author.")
    d.box(xs[2], y, bw, h, "Decide", "the pull request", pr)
    d.edge(f"M{xs[0] + bw} {y + 110} H{xs[1] - 4}", "runs, traces,|the index", 232, y + 88)
    d.edge(f"M{xs[1]} {y + 200} H{xs[0] + bw + 4}", "trials to run:|tasks × arms × n", 232, y + 222)
    d.edge(f"M{xs[1] + bw} {y + 110} H{xs[2] - 4}", "the report", 488, y + 100)
    d.box(24, 358, 672, 40, "", "", (), hue="tower")
    d.text(38, 383, "Govern", "l")
    d.text(96, 383, "Tower: policy decisions, approvals, signed receipts", "s")
    d.edge(f"M{xs[2] + bw // 2} {y + h} V354", "promotion approval · planned", xs[2] + bw // 2 - 8, y + h + 16, "plan",
           "end")
    return d.svg("Where flightdeck sits: hangar runs, flightdeck judges, the pull request decides; Tower governs "
                 "risky actions with policy decisions, approvals and signed receipts; promotion approval through "
                 "Tower is planned")


def flow_data_plane() -> str:
    d = Diagram("plane", 720, 236, "The data plane · two ways in, one way out")
    d.box(24, 52, 200, 64, "", "hangar's outbox", ("one hangar.run/v1 per run,", "written to GCS"))
    d.box(24, 140, 200, 64, "", "an export, or REST", ("hangar experiment export,", "or GET /api/experiments/{id}"))
    d.step(264, 64, 140, "compact", "nightly, on Cloud Run")
    d.step(264, 152, 140, "ingest", "when you need it now")
    d.box(444, 52, 252, 152, "", "the data plane", ("Parquet: one table per kind", "of record, partitioned by day",
                                                    "(flightdeck.parquet/v1).", "", "DuckDB views over it feed",
                                                    "stats, check and report."))
    for y in (84, 172):
        d.edge(f"M224 {y} H260")
        d.edge(f"M404 {y} H440")
    return d.svg("The data plane: hangar's outbox is compacted nightly and an export or REST response is ingested on "
                 "demand, both into Parquet tables that DuckDB views read for stats, check and report")


def flow_experiment() -> str:
    d = Diagram("exp", 720, 260, "An experiment · from suite to report")
    steps = (("suite.yaml", "tasks, variants, trials"), ("plan", "tasks × arms × n, pinned"),
             ("cost gate", "projected spend ≤ budget"), ("hangar runs it", "queued, isolated, pinned"),
             ("collect", "into the data plane"), ("report", "verdict on the pull request"))
    for i, (name, sub) in enumerate(steps):
        x = 24 + (i % 3) * 232
        y = 52 + (i // 3) * 136
        d.step(x, y, 200, name, sub, 48)
        if i % 3 != 2:
            d.edge(f"M{x + 200} {y + 24} H{x + 228}")
    d.edge("M588 100 V176 H124 V184")
    d.step(256, 124, 200, "cache", "unchanged inputs: the trial is reused", 40)
    d.edge("M356 124 V104", "", 0, 0, "plan")
    d.text(470, 141, "so plan submits only", "e")
    d.text(470, 156, "what is missing", "e")
    return d.svg("An experiment: a suite is planned into pinned trials, passed through the cost gate, run by hangar, "
                 "collected into the data plane and reported; the cache skips trials whose inputs are unchanged")


def flow_holdout() -> str:
    d = Diagram("hold", 720, 236, "A sealed holdout · written blind, scored once")
    steps = (("brief", "writers who are not", "the change's authors"),
             ("write blind", "tasks land in", "incoming/<writer>/"),
             ("seal", "canaries and hashes", "added; plaintext gone"),
             ("run", "decrypted, one arm,", "egress none"),
             ("score once", "approver ≠ author;", "then the set is spent"))
    for i, (name, a, b) in enumerate(steps):
        x = 24 + i * 136
        d.step(x, 52, 120, name, "", 36)
        d.text(x + 2, 112, a, "e")
        d.text(x + 2, 127, b, "e")
        if i < 4:
            d.edge(f"M{x + 120} 70 H{x + 134}")
    d.box(24, 160, 672, 52, "", "", (), "plan")
    d.text(38, 182, "Nightly", "l")
    d.text(38, 200, "canary-scan reads the last days' traces for the set's canary strings; a hit voids the set.", "b")
    return d.svg("A sealed holdout: briefed to blind writers, written, sealed with canaries and hashes, run once on "
                 "the candidate and scored once by an approver who is not the author; a nightly canary scan voids a "
                 "leaked set")


def paired_by_task() -> str:
    """Two arms, tasks as rows, resolved or not per trial; the discordant pairs are what the comparison learns from."""
    d = Diagram("pair", 720, 262, "Paired by task · the comparison resamples tasks, not trials")
    rows = (("t01", "● ● ●", "● ● ●", "saturated: no information"),
            ("t02", "○ ○ ○", "○ ○ ○", "saturated: no information"), ("t03", "○ ● ○", "● ● ○", "discordant: +1 of 3"),
            ("t04", "○ ○ ●", "● ● ●", "discordant: +2 of 3"),
            ("t05", "● ○ ●", "○ ● ●", "concordant: the same rate"), ("…", "", "", "every task runs in both arms"))
    d.text(24, 62, "Task", "l")
    d.text(120, 62, "Control", "l")
    d.text(260, 62, "Candidate", "l")
    d.text(420, 62, "What the pair says", "l")
    d.out.append(f'<path d="M24 70 H696" stroke="{V["rule"]}"/>')
    for i, (task, a, b, note) in enumerate(rows):
        y = 94 + 24 * i
        d.text(24, y, task, "k")
        d.text(120, y, a, "k")
        d.text(260, y, b, "k")
        d.text(420, y, note, "b" if "discordant" in note else "e")
    d.text(24, 236, "● resolved  ○ not resolved. The paired difference is the mean over tasks of the candidate rate "
           "minus", "e")
    d.text(24, 251, "the control rate; its interval comes from resampling tasks. A task with one arm missing is left "
           "out.", "e")
    return d.svg("Paired by task: each task runs three trials in both arms; saturated tasks carry no information, "
                 "discordant tasks drive the paired difference, and the interval comes from resampling tasks")


# ---------------------------------------------------------------------------------------------------- main
# ------------------------------------------------------------------------------------------------------- the clip
# The demo clip (KAN-75): about 20 s at 640 px and 2x, so it reads at a docs column's width and on a phone. It opens on
# `stats compare` in a terminal (the poster is that first frame), types `report` and its verdict, then shows the same
# report as the pull-request comment: its verdict, the experiment, the rule and the Outcome table.
# `clip-{dark,light}.html` is the page, which plays its own timeline; the MP4s
# are screenshots of it taken back to back, encoded at the time each was on screen. Night and Day differ in the page
# and the comment (GitHub's palette); the terminal is dark in both, as Airframe's Terminal always is.
CLIP_W, CLIP_H, CLIP_COLS = 680, 640, 71  # 71 columns of 14 px DM Mono fill the terminal at 680
CLIP_CSS = """
html,body{margin:0;height:100%;background:var(--af-canvas);overflow:hidden}
.stage{position:relative;width:100vw;height:100vh}
.scene{position:absolute;inset:0;padding:20px 20px 84px;box-sizing:border-box;transition:opacity .45s,transform .45s}
.scene.off{opacity:0;transform:translateY(12px)}
.term{background:var(--af-terminal-bg);color:var(--af-terminal-fg);border-radius:var(--af-radius-card);
border:1px solid color-mix(in srgb,var(--af-terminal-fg) 8%,transparent);font:14px/19px var(--af-font-mono);
overflow:hidden}
.term .bar{display:flex;gap:14px;align-items:center;padding:0 14px;height:34px;border-bottom:1px solid
color-mix(in srgb,var(--af-terminal-fg) 9%,transparent);font:500 10.5px var(--af-font-mono);letter-spacing:.08em;
text-transform:uppercase;color:var(--af-terminal-dim)}.term .bar b{color:var(--af-terminal-fg);font-weight:500}
.term pre{margin:0;padding:16px 18px;font:inherit;white-space:pre}
.term .p{color:var(--af-brand)}.term .c,.term .v{color:var(--af-code-keyword)}.term .hide{visibility:hidden}
.gh{height:100%;overflow:hidden;border-radius:var(--af-radius-card);border:1px solid var(--af-line)}
.gh .page{width:auto;padding:16px}.gh .avatar{display:none}
.cap{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);display:flex;gap:10px;align-items:baseline;
width:max-content;max-width:calc(100vw - 48px);box-sizing:border-box;padding:9px 14px;background:var(--af-raised);
color:var(--af-fg);border:1px solid var(--af-line-strong);border-left:3px solid var(--af-brand);
border-radius:var(--af-radius-control);box-shadow:var(--af-shadow-overlay);font:500 15px/1.35 var(--af-font-sans);
z-index:2}.cap b{font:500 12px var(--af-font-mono);color:var(--af-brand-text);letter-spacing:.08em}
"""


def clip_lines(steps: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The terminal's lines as (kind, text): `stats compare` and its table and paired difference, then `report` and
    its verdict, wrapped at CLIP_COLS."""
    stats, report = (next(s for s in steps if s[0].startswith(p)) for p in ("flightdeck stats", "flightdeck report"))
    keep = [p for p in stats[1].split("\n\n") if p.startswith(("VARIANT", "Paired difference"))]
    lines: list[tuple[str, str]] = []
    for cmd, output in ((stats[0], "\n\n".join(keep)), (report[0], report[1])):
        parts = cmd.split(" \\\n")
        lines += [("cmd" if i == 0 else "cmd2", x.strip() + (" \\" if i < len(parts) - 1 else ""))
                  for i, x in enumerate(parts)]
        lines += [("out", x) for x in wrap(output, CLIP_COLS)] + [("out", "")]
    return lines + [("cmd", "")]


def clip_page(steps: list[tuple[str, str]], report: str, theme: str) -> str:
    """The clip's page in `theme`: Airframe (the vendored stylesheet) around the terminal and GitHub's palette in the
    comment. Its script plays the timeline and sets `window.clipDone` at the end."""
    from markdown_it import MarkdownIt

    css = (ROOT / "docs/stylesheets/airframe.css").read_text(encoding="utf-8")
    rows = []
    for i, (kind, text) in enumerate(clip_lines(steps)):
        if kind.startswith("cmd"):
            prompt = "$ " if kind == "cmd" else "> "
            rows.append(f'<span class="l" data-i="{i}" data-k="cmd"><span class="p">{prompt}</span>'
                        f'<span class="c" data-t="{esc(text)}">{"▌" if not text else ""}</span></span>')
        else:
            cls = "v" if VERDICT.match(text) else ""
            rows.append(f'<span class="l {cls}" data-i="{i}" data-k="out">{esc(text)}</span>')
    body = MarkdownIt("commonmark", {"html": True}).enable("table").render(report.split("\n### Process")[0])
    gh = ";".join(f"--{k}:{v}" for k, v in GH[theme].items()) + ";--w:auto"
    script = """
const lines = [...document.querySelectorAll('.term .l')], cap = document.querySelector('.cap');
const say = (n, t) => { cap.querySelector('b').textContent = n; cap.querySelector('span').textContent = t; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
lines.forEach((l) => l.classList.add('hide'));
async function type(l, ms) { const c = l.querySelector('.c'), t = c.dataset.t; l.classList.remove('hide');
  for (let k = 0; k <= t.length; k++) { c.textContent = t.slice(0, k); if (ms) await wait(ms); } }
async function play() {
  let i = 0;
  const block = async (typing) => {  // a command (and its continuation), then its output up to the blank line
    while (i < lines.length && lines[i].dataset.k === 'cmd' && lines[i].querySelector('.c').dataset.t) {
      await type(lines[i], typing); i++;
      if (lines[i] && lines[i].dataset.k === 'cmd' && !lines[i].querySelector('.c').dataset.t) break; }
    await wait(350);
    while (i < lines.length && lines[i].dataset.k === 'out') { lines[i].classList.remove('hide'); i++; await wait(45); }
  };
  say('1', 'flightdeck compares the two arms, paired by task');
  await block(0);  // the first command is already typed in the first frame
  window.clipStarted = true;
  await wait(3800);
  say('2', 'The report ends in a verdict, by a rule fixed in advance');
  await block(28);
  lines[i].classList.remove('hide');
  await wait(3600);
  say('3', 'The same report, posted on the pull request as one comment');
  document.querySelector('.s1').classList.add('off'); document.querySelector('.s2').classList.remove('off');
  await wait(6400);
  window.clipDone = true;
}
document.fonts.ready.then(play);
"""
    return (f'<!doctype html><html data-theme="{theme}"><head><meta charset="utf-8">'
            f'<link rel="stylesheet" href="{FONTS}">'
            f"<style>{css}{GH_CSS}{CLIP_CSS}</style></head><body><div class=\"stage\">"
            f'<div class="scene s1"><div class="term"><div class="bar"><b>flightdeck</b><span>fixture experiment</span>'
            f'</div><pre>{chr(10).join(rows)}</pre></div></div>'
            f'<div class="scene s2 off"><div class="gh" style="{gh}"><div class="page"><div class="row">'
            f'<div class="comment"><div class="head"><b>flightdeck</b> commented</div><div class="md">{body}</div>'
            "</div></div></div></div></div>"
            f'</div><div class="cap"><b></b><span></span></div><script>{script}</script></body></html>\n')


def record_clip(pages: dict[str, str]) -> None:
    """clip.mp4 / clip-light.mp4 and their posters (the first frame) from the clip pages: {mp4 name: html}."""
    from playwright.sync_api import sync_playwright

    ffmpeg = shutil.which("ffmpeg") or sys.exit("build: the clip needs ffmpeg on PATH")
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as d:
        browser = pw.chromium.launch()
        for name, page in pages.items():
            tab = browser.new_context(device_scale_factor=2, viewport={"width": CLIP_W, "height": CLIP_H}).new_page()
            tab.set_content(page, wait_until="networkidle")
            tab.wait_for_function("window.clipStarted === true", timeout=30000)
            shots: list[tuple[Path, float]] = []
            while not tab.evaluate("window.clipDone === true"):
                path = Path(d) / f"{name}-{len(shots):05d}.png"
                tab.screenshot(path=str(path))
                shots.append((path, tab.evaluate("performance.now()") / 1000))
            tab.context.close()
            seconds = shots[-1][1] - shots[0][1]
            if not 15 <= seconds <= 25:
                sys.exit(f"build: {name} runs {seconds:.1f} s; a clip runs 15 to 25 s")
            listing = Path(d) / f"{name}.txt"
            rows = []
            for (path, t), (_, nxt) in zip(shots, [*shots[1:], (None, shots[-1][1] + 0.1)], strict=True):
                rows += [f"file '{path}'", f"duration {max(nxt - t, 0.01):.3f}"]
            listing.write_text("\n".join([*rows, f"file '{shots[-1][0]}'"]) + "\n", encoding="utf-8")
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                            "-vf", "fps=15,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "28",
                            "-movflags", "+faststart", str(HERE / name)], check=True)
            shutil.copyfile(shots[0][0], HERE / name.replace(".mp4", "-poster.png"))
            size = (HERE / name).stat().st_size
            if size > 3_000_000:
                sys.exit(f"build: {name} is {size} bytes; a clip stays under 3 MB")
            print(f"build: wrote {name} ({seconds:.1f} s, {len(shots)} frames, {size // 1024} KB) and its poster")
        browser.close()


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
    ap.add_argument("--no-png", action="store_true", help="Skip the Playwright screenshots and the clip.")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        steps = session(Path(d))
        report = (Path(d) / "demo" / "report.md").read_text(encoding="utf-8")
    lines, total = timeline(steps)
    print(f"build: the recording loops every {HOLD + total:.1f} s ({len(lines)} lines, {COLS} columns)")
    stats = next(s for s in steps if s[0].startswith("flightdeck stats compare"))
    files = {
        "demo.cast": cast(steps),
        "demo.svg": terminal(lines, total, "flightdeck|fixture experiment|12 tasks × 2 variants × 3 trials"),
        "demo-still.svg": terminal(lines, None, "flightdeck|fixture experiment|12 tasks × 2 variants × 3 trials"),
        "demo-phone.svg": terminal(phone(steps), None, "flightdeck|fixture experiment", PHONE_COLS),
        "stats-compare.svg": terminal([(0, "cmd", stats[0])] + [(0, "out", x) for x in wrap(stats[1])], None,
                                      "flightdeck|stats compare"),
        "report.md": report,
        **{f"report-comment{k}-{t}.html": comment_page(report, t, not k) for k in ("", "-full")
           for t in ("dark", "light")},
        **{f"report-comment-phone-{t}.html": comment_page(report, t, True, True) for t in ("dark", "light")},
        "suite.svg": suite(), "flow-data-plane.svg": flow_data_plane(), "flow-experiment.svg": flow_experiment(),
        "flow-holdout.svg": flow_holdout(), "paired-by-task.svg": paired_by_task(),
    }
    files.update({f"clip-{t}.html": clip_page(steps, report, t) for t in ("dark", "light")})
    pages = {f"report-comment{k}-{t}.png": (files[f"report-comment{k}-{t}.html"], "div.page")
             for k in ("", "-full", "-phone") for t in ("dark", "light")}
    clips = {"clip.mp4": files["clip-dark.html"], "clip-light.mp4": files["clip-light.html"]}
    files["sources.sha256"] = "".join(f"{hashlib.sha256(p.encode()).hexdigest()}  {n}\n"
                                      for n, p in sorted([*((n, p) for n, (p, _) in pages.items()), *clips.items()]))
    for name, text in files.items():
        (HERE / name).write_text(text, encoding="utf-8")
        print("build: wrote", name)
    if not args.no_png:
        shoot(pages)
        record_clip(clips)


if __name__ == "__main__":
    main()
