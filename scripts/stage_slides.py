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
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
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
    svg = tag_edges(target.read_text(encoding="utf-8").strip())
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


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: stage_slides.py <input.md> <output.md>", file=sys.stderr)
        return 2

    source_path, output_path = (Path(arg) for arg in sys.argv[1:3])
    deck = source_path.read_text(encoding="utf-8")

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
