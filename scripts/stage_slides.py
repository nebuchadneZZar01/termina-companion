#!/usr/bin/env python3
"""Stage the Markdown deck before Marp renders it.

The deck stays plain Markdown, but two constructs need a build step:

* Marp has no Mermaid engine, so every ```mermaid fence is rendered to SVG
  with @mermaid-js/mermaid-cli and replaced by an inline SVG inside a
  ``div.diagram``. Inlining (rather than using an <img>) keeps the page's
  Inter webfont available to the SVG labels.
* A fenced code block can name its file with ``title="..."``. Marp has no
  title bar or line numbers, so those fences become the ``div.code`` panel the
  theme draws, with one numbered span per source line.

The output is a staged copy; the source deck itself is never rewritten.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MERMAID_CLI = "@mermaid-js/mermaid-cli@11"
DIAGRAM_WIDTH = 1584
FONT_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets" / "fonts"
MERMAID_FENCE = re.compile(r"^```mermaid\n(.*?)^```$", re.MULTILINE | re.DOTALL)
CODE_FENCE = re.compile(
    r'^```(?P<lang>[\w+-]+)[ \t]+title="(?P<title>[^"]+)"[ \t]*\n(?P<code>.*?)^```$',
    re.MULTILINE | re.DOTALL,
)


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


def render(code: str, workdir: Path, index: int) -> str:
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
        ],
        check=True,
    )
    svg = target.read_text(encoding="utf-8").strip()
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

        def replace(match: re.Match[str]) -> str:
            nonlocal counter
            counter += 1
            return render(match.group(1), workdir, counter)

        staged = MERMAID_FENCE.sub(replace, deck)

    staged = CODE_FENCE.sub(code_panel, staged)
    output_path.write_text(staged, encoding="utf-8")
    print(f"{source_path} => {output_path} ({counter} Mermaid diagram(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
