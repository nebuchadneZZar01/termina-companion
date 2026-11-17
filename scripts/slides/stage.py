#!/usr/bin/env python3
"""Stage the Markdown deck before Marp renders it.

The deck stays plain Markdown, but two constructs need a build step:

* Marp has no Mermaid engine, so every ```mermaid fence is rendered to SVG
  with @mermaid-js/mermaid-cli and replaced by an inline SVG inside a
  ``div.diagram``. Inlining (rather than using an <img>) keeps the page's
  Inter webfont available to the SVG labels. The diagrams share one look:
  docs/mermaid.json holds the theme and docs/mermaid.css the colours, and the
  fences only declare roles (``class gs start;``, ``e_acc1@-->``). A fence that
  carries its own style is a build error, so the diagrams cannot drift apart.
* A fenced code block can name its file with ``title="..."``. Marp has no
  title bar or line numbers, so those fences become the ``div.code`` panel the
  theme draws, with one numbered span per source line. A Python fence's tokens
  are wrapped in the classes that give them the mockup's colours.

The output is a staged copy; the source deck itself is never rewritten.
"""

from __future__ import annotations

import html
import io
import json
import keyword
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

MERMAID_CLI = "@mermaid-js/mermaid-cli@11"
DIAGRAM_WIDTH = 1584
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
FONT_DIR = DOCS_DIR / "assets" / "fonts"
MERMAID_CONFIG = DOCS_DIR / "mermaid.json"
MERMAID_CSS = DOCS_DIR / "mermaid.css"
MERMAID_FENCE = re.compile(r"^```mermaid\n(.*?)^```$", re.MULTILINE | re.DOTALL)
CODE_FENCE = re.compile(
    r'^```(?P<lang>[\w+-]+)[ \t]+title="(?P<title>[^"]+)"[ \t]*\n(?P<code>.*?)^```$',
    re.MULTILINE | re.DOTALL,
)
# An edge tagged `a e_acc1@--> b` reaches the SVG as <path id="my-svg-e_acc1">.
# The trailing digits only keep the ids unique; the role is the rest.
TAGGED_EDGE = re.compile(r'(<path\b[^>]*?)\bid="([^"]*)-e_([A-Za-z][\w-]*)"')
# Style directives a diagram fence must not carry: the shared stylesheet owns
# them. `:::` is Mermaid's inline class shorthand.
DIAGRAM_STYLE = re.compile(r"%%\{|\bclassDef\b|\blinkStyle\b|\bstyle\s*=|:::")


def fontconfig(workdir: Path) -> Path | None:
    """Point fontconfig at the self-hosted Inter so mmdc measures the real font."""
    if not (FONT_DIR / "Inter.ttf").is_file():
        return None
    cache = workdir / "fontcache"
    cache.mkdir()
    conf = workdir / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        "<fontconfig>\n"
        f"  <dir>{FONT_DIR}</dir>\n"
        '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
        f"  <cachedir>{cache}</cachedir>\n"
        "</fontconfig>\n",
        encoding="utf-8",
    )
    return conf


def mermaid_config(workdir: Path) -> Path:
    """Merge the diagram theme and its stylesheet into the config mmdc takes."""
    config = json.loads(MERMAID_CONFIG.read_text(encoding="utf-8"))
    config["themeCSS"] = MERMAID_CSS.read_text(encoding="utf-8")
    merged = workdir / "mermaid.json"
    merged.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return merged


def check_diagram(code: str, index: int) -> None:
    """Refuse a fence that carries its own style instead of a role."""
    match = DIAGRAM_STYLE.search(code)
    if match is None:
        return
    line = code.count("\n", 0, match.start()) + 1
    raise SystemExit(
        f"diagram {index}, line {line}: {match.group(0)!r} is style in the deck; "
        "roles live in docs/mermaid.css and docs/mermaid.json"
    )


def tag_edges(svg: str) -> str:
    """Expose an `e_<role><n>` edge id as the data attribute the stylesheet reads."""
    return TAGGED_EDGE.sub(
        lambda match: (
            f'{match.group(1)}id="{match.group(2)}-e_{match.group(3)}" '
            f'data-edge-role="{match.group(3).rstrip("0123456789") or match.group(3)}"'
        ),
        svg,
    )


# A sequence-diagram actor is Mermaid's stick figure. The deck's player is the
# same figure, wearing a green cap and holding a sword in its right hand: the
# mark is drawn on top of the actor, anchored at the centre of its head. A fence
# may not carry style, and this is not a role but one specific actor.
_PLAYER_MARK = (
    # The cap: a band across the crown and a point above it.
    '<path d="M-16 -4 Q-15 -13 -4 -16 Q6 -11 14 -4 Z" fill="#4caf50" '
    'stroke="#2f7d32" stroke-width="1.4" stroke-linejoin="round"/>'
    '<path d="M-17 -4 Q-2 2 15 -6" fill="none" stroke="#2f7d32" '
    'stroke-width="2.2" stroke-linecap="round"/>'
    # The sword, raised from the hand at the right arm (x +18, y +23).
    '<path d="M18 14 L18 -2" stroke="#dfe6f2" stroke-width="3.2" '
    'stroke-linecap="round" fill="none"/>'
    '<path d="M11 16 L25 16" stroke="#f0b24a" stroke-width="2.8" '
    'stroke-linecap="round" fill="none"/>'
    '<path d="M18 25 L18 17" stroke="#8a5a2b" stroke-width="3" '
    'stroke-linecap="round" fill="none"/>'
)
_ACTOR = re.compile(r'<g class="actor-man[^"]*"[^>]*>.*?</g>', re.DOTALL)
_ACTOR_HEAD = re.compile(r'<circle cx="([-\d.]+)" cy="([-\d.]+)"')


def player_mark(svg: str) -> str:
    """Dress Mermaid's stick-figure actor as the player, keeping its label.

    args:
        svg (str): a rendered Mermaid SVG.

    returns:
        str: the SVG with every actor wearing the cap and holding the sword.
    """

    def swap(match: re.Match[str]) -> str:
        group = match.group(0)
        head = _ACTOR_HEAD.search(group)
        if head is None:
            return group
        x = float(head.group(1))
        y = float(head.group(2))
        icon = f'<g class="player-mark" transform="translate({x:g} {y:g})">{_PLAYER_MARK}</g>'
        return group.replace("</g>", f"{icon}</g>")

    return _ACTOR.sub(swap, svg)


def render(code: str, workdir: Path, index: int, config: Path) -> str:
    source = workdir / f"diagram-{index}.mmd"
    target = workdir / f"diagram-{index}.svg"
    source.write_text(code, encoding="utf-8")
    subprocess.run(
        [
            "npx",
            "--yes",
            MERMAID_CLI,
            "-i",
            str(source),
            "-o",
            str(target),
            "-b",
            "transparent",
            "-w",
            str(DIAGRAM_WIDTH),
            "-c",
            str(config),
        ],
        check=True,
    )
    svg = player_mark(tag_edges(target.read_text(encoding="utf-8").strip()))
    return f'<div class="diagram">{svg}</div>'


# The mockup's code panel colours a handful of token kinds and leaves the rest
# in the default text colour. The spans carry these classes; docs/marp-theme.css
# owns the actual colours, so the deck never names one.
_IGNORED_TOKENS = {
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.NEWLINE,
    tokenize.NL,
}
# Brackets, separators and the arrow are structure, not operators: the mockup
# leaves them in the default colour.
_NEUTRAL_OPERATORS = {
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    ",",
    ":",
    ";",
    ".",
    "...",
    "->",
    "@",
}
_STRING_TOKENS = {
    tokenize.STRING,
    tokenize.FSTRING_START,
    tokenize.FSTRING_MIDDLE,
    tokenize.FSTRING_END,
}


def _token_class(current: tokenize.TokenInfo, following: tokenize.TokenInfo | None) -> str | None:
    """Pick the stylesheet class for one token, mirroring the mockup's palette."""
    if current.type in _STRING_TOKENS:
        return "tok-string"
    if current.type == tokenize.COMMENT:
        return "tok-comment"
    if current.type == tokenize.NUMBER:
        return "tok-number"
    if current.type == tokenize.OP:
        return None if current.string in _NEUTRAL_OPERATORS else "tok-op"
    if current.type == tokenize.NAME:
        # Only a name that is actually called gets a colour: the mockup leaves
        # a class passed as an argument in the default text colour.
        if following is not None and following.string == "(":
            return "tok-class" if current.string[:1].isupper() else "tok-call"
        if keyword.iskeyword(current.string):
            return "tok-keyword"
    return None


def highlight_python(code: str) -> list[str]:
    """Split Python source into HTML lines with one span per coloured token.

    Falling back to escaped plain text keeps a snippet with a syntax error
    readable instead of failing the build.
    """
    lines = code.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [html.escape(line) for line in lines]

    meaningful = [tok for tok in tokens if tok.type not in _IGNORED_TOKENS]
    marks: list[list[tuple[int, int, str]]] = [[] for _ in lines]
    for position, current in enumerate(meaningful):
        following = meaningful[position + 1] if position + 1 < len(meaningful) else None
        css = _token_class(current, following)
        if css is None:
            continue
        (start_row, start_col), (end_row, end_col) = current.start, current.end
        # A multi-line token (a docstring) is one span per line it touches.
        for row in range(start_row, end_row + 1):
            begin = start_col if row == start_row else 0
            end = end_col if row == end_row else len(lines[row - 1])
            marks[row - 1].append((begin, end, css))

    rendered = []
    for line, spans in zip(lines, marks, strict=True):
        pieces: list[str] = []
        cursor = 0
        for begin, end, css in sorted(spans):
            if begin > cursor:
                pieces.append(html.escape(line[cursor:begin]))
            pieces.append(f'<span class="{css}">{html.escape(line[begin:end])}</span>')
            cursor = end
        pieces.append(html.escape(line[cursor:]))
        rendered.append("".join(pieces))
    return rendered


def code_panel(match: re.Match[str]) -> str:
    """Turn a titled fence into the code panel with one number per line."""
    code = match.group("code")
    language = match.group("lang").lower()
    lines = code.splitlines()
    highlighted = (
        highlight_python(code)
        if language in {"python", "py"}
        else [html.escape(line) for line in lines]
    )
    numbered = "\n".join(
        f'<span class="ln">{number}</span>{line}'
        for number, line in enumerate(highlighted, start=1)
    )
    title = html.escape(match.group("title"))
    return (
        '<div class="code">\n'
        '<div class="code-title">'
        '<i class="r"></i><i class="y"></i><i class="g"></i>'
        f"<span>{title}</span></div>\n"
        f"<pre>{numbered}</pre>\n"
        "</div>"
    )


FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
SLIDE_SEPARATOR = re.compile(r"\n---\n")


def numbered_slides(deck: str) -> list[int]:
    """Return the 0-based indexes of the slides that carry a page number.

    The deck leaves the cover and the closing out of the count with a local
    ``_paginate: false`` directive, so their slide is skipped.

    args:
        deck (str): the deck source, front matter included.

    returns:
        list[int]: indexes of the numbered slides, in deck order.
    """
    match = FRONT_MATTER.match(deck)
    body = deck[match.end() :] if match else deck
    slides = SLIDE_SEPARATOR.split(body)
    return [index for index, slide in enumerate(slides) if "_paginate: false" not in slide]


def inject_page_numbers(deck: str) -> str:
    """Append the printed page number to every numbered slide.

    Marp numbers every slide and reserves ``section::after`` for its own count,
    whose ``content`` it strips from any theme or ``style`` rule. A real span
    is the one way to print a different total, and it also keeps the marker in
    the HTML export.

    args:
        deck (str): the deck source, front matter included.

    returns:
        str: the deck with one ``<span class="page-no">`` per numbered slide.
    """
    match = FRONT_MATTER.match(deck)
    head = deck[: match.end()] if match else ""
    body = deck[match.end() :] if match else deck
    slides = SLIDE_SEPARATOR.split(body)
    positions = numbered_slides(deck)
    total = len(positions)
    if not total:
        return deck
    for page, index in enumerate(positions, start=1):
        slides[index] += f'\n\n<span class="page-no">{page} / {total}</span>\n'
    separator = "\n---\n".join(slides)
    return head + separator


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: stage.py <input.md> <output.md>", file=sys.stderr)
        return 2

    source_path, output_path = (Path(arg) for arg in sys.argv[1:3])
    deck = source_path.read_text(encoding="utf-8")
    deck = inject_page_numbers(deck)

    if not shutil.which("npx"):
        print("npx not found: install Node.js to render the Mermaid diagrams", file=sys.stderr)
        return 1

    if "CHROME_PATH" in os.environ:
        os.environ.setdefault("PUPPETEER_EXECUTABLE_PATH", os.environ["CHROME_PATH"])
    os.environ.setdefault("PUPPETEER_SKIP_DOWNLOAD", "1")

    counter = 0

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        conf = fontconfig(workdir)
        if conf is not None:
            os.environ["FONTCONFIG_FILE"] = str(conf)
        config = mermaid_config(workdir)

        def replace(match: re.Match[str]) -> str:
            nonlocal counter
            counter += 1
            check_diagram(match.group(1), counter)
            return render(match.group(1), workdir, counter, config)

        staged = MERMAID_FENCE.sub(replace, deck)

    staged = CODE_FENCE.sub(code_panel, staged)
    output_path.write_text(staged, encoding="utf-8")
    print(f"{source_path} => {output_path} ({counter} Mermaid diagram(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
