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
  theme draws, with one numbered span per source line.

The output is a staged copy; the source deck itself is never rewritten.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def code_panel(match: re.Match[str]) -> str:
    """Turn a titled fence into the code panel with one number per line."""
    lines = match.group("code").splitlines()
    numbered = "\n".join(
        f'<span class="ln">{number}</span>{html.escape(line)}'
        for number, line in enumerate(lines, start=1)
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
