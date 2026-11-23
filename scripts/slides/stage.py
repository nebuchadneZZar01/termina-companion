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
    # ==========================================
    # LINK'S GREEN CAP
    # ==========================================
    '<g transform="translate(-2.0 -4.1) scale(1.2) rotate(15)">'
    # Original cap with taller upper tip curved to the right
    '<path d="'
    "M-11 -2 "
    "C-10 -10 -6 -18 -2 -21 "
    "C2 -23 8 -22 12 -21 "
    "L13 -18 "
    "C16 -15 22 -13 28 -13 "
    "C33 -13 37 -17 39 -20 "
    "Q38 -14 29 -9 "
    "Q18 -3 7 -4 "
    "Q-3 1 -11 -2 Z"
    '" fill="#4caf50" stroke="#2f7d32" '
    'stroke-width="1.4" stroke-linejoin="round"/>'
    # Original curved brim
    '<path d="M-12 -2 Q-2 2 5 -2 Q10 -4 14 -7" '
    'fill="none" stroke="#256b2c" '
    'stroke-width="2.8" stroke-linecap="round"/>'
    "</g>"
    # ==========================================
    # MASTER SWORD
    # Pivot: right hand (25, 25)
    # ==========================================
    '<g transform="rotate(25 18 25)">'
    # Blade
    '<path d="'
    "M15.5 12 "
    "L14.5 4 "
    "L15.5 -8 "
    "L18 -17 "
    "L20.5 -8 "
    "L21.5 4 "
    "L20.5 12 Z"
    '" fill="#dce6f2" stroke="#8798b3" '
    'stroke-width="0.8" stroke-linejoin="round"/>'
    # Central blade ridge
    '<path d="M18 12 L18 -15 '
    'L19.5 -8 L19.5 4 Z" '
    'fill="#a9c6e8"/>'
    # Left blade highlight
    '<path d="M16 8 L16.5 -7 L18 -15" '
    'fill="none" stroke="#ffffff" '
    'stroke-width="0.9" stroke-linecap="round"/>'
    # Blue central fuller
    '<path d="M18 8 L18 -12" '
    'fill="none" stroke="#779ac8" '
    'stroke-width="0.65" stroke-linecap="round"/>'
    # Left wing
    '<path d="M17 14 Q13 10 9 7 L7 8 '
    'Q8 13 12 17 L17 16 Z" '
    'fill="#393064" stroke="#211a49" '
    'stroke-width="1" stroke-linejoin="round"/>'
    # Right wing
    '<path d="M19 14 Q23 10 27 7 L29 8 '
    'Q28 13 24 17 L19 16 Z" '
    'fill="#393064" stroke="#211a49" '
    'stroke-width="1" stroke-linejoin="round"/>'
    # Gold decorative wing edges
    '<path d="M8 8 Q12 11 16 14 '
    'M28 8 Q24 11 20 14" '
    'fill="none" stroke="#c69a42" '
    'stroke-width="0.8" stroke-linecap="round"/>'
    # Violet wing highlights
    '<path d="M10 9 Q13 12 15 14 '
    'M26 9 Q23 12 21 14" '
    'fill="none" stroke="#7165a8" '
    'stroke-width="0.9" stroke-linecap="round"/>'
    # Central guard
    '<path d="M15 12 L18 9 L21 12 '
    'L20 17 L16 17 Z" '
    'fill="#302653" stroke="#211a49" '
    'stroke-width="0.9"/>'
    # Golden central jewel
    '<path d="M18 10.5 L20 13 '
    'L18 15.5 L16 13 Z" '
    'fill="#e5ae3e" stroke="#a87524" '
    'stroke-width="0.7"/>'
    # Dark violet-blue handle
    '<path d="M18 17 L18 24" '
    'stroke="#29204f" stroke-width="3.5" '
    'stroke-linecap="round" fill="none"/>'
    # Grip texture
    '<path d="M16.7 19 L19.3 21 '
    'M16.7 22 L19.3 24" '
    'stroke="#6555a0" stroke-width="0.8" '
    'stroke-linecap="round" fill="none"/>'
    # Golden pommel
    '<circle cx="18" cy="25" r="1.8" '
    'fill="#d5a33e" stroke="#8a6429" '
    'stroke-width="0.7"/>'
    "</g>"
    # ==========================================
    # HYLIAN SHIELD
    # ==========================================
    '<g transform="translate(-19 23) scale(0.75)">'
    # Outer golden border
    '<path d="'
    "M-10 -15 "
    "L10 -15 "
    "L10 3 "
    "Q9 16 0 23 "
    "Q-9 16 -10 3 Z"
    '" fill="#d6a33e" stroke="#805d26" '
    'stroke-width="1.5" stroke-linejoin="round"/>'
    # Blue shield body
    '<path d="'
    "M-8 -13 "
    "L8 -13 "
    "L8 3 "
    "Q7 14 0 20 "
    "Q-7 14 -8 3 Z"
    '" fill="#28558c" stroke="#182f58" '
    'stroke-width="1"/>'
    # Central silver ridge
    '<path d="M0 -12 L0 18" '
    'stroke="#8ca9cf" stroke-width="0.8" '
    'opacity="0.8"/>'
    # Triforce
    '<path d="M0 -9 L-3 -4 L3 -4 Z '
    "M-3 -4 L-6 1 L0 1 Z "
    'M3 -4 L0 1 L6 1 Z" '
    'fill="#f5d45c" stroke="#b58a32" '
    'stroke-width="0.55" stroke-linejoin="round"/>'
    # Red bird crest
    '<path d="M-6 6 Q-3 3 0 7 '
    "Q3 3 6 6 Q3 11 0 12 "
    'Q-3 11 -6 6 Z" '
    'fill="#b83242" stroke="#76212e" '
    'stroke-width="0.7"/>'
    # Decorative lower detail
    '<path d="M-3 14 L0 17 L3 14" '
    'fill="none" stroke="#e4c36a" '
    'stroke-width="0.8"/>'
    "</g>"
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
