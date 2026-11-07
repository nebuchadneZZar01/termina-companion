#!/usr/bin/env sh
# Build the Marp deck into docs/slides.pdf.
#
# Requires Node.js (for npx) and a local Chrome/Chromium. The first run
# downloads @marp-team/marp-cli and @mermaid-js/mermaid-cli; nothing is added to
# the repository. Mermaid fences are rendered to inline SVG in a staged copy of
# the deck, because Marp has no Mermaid engine.
set -eu

cd "$(dirname "$0")/.."

if [ -z "${CHROME_PATH:-}" ]; then
  for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      CHROME_PATH="$(command -v "$candidate")"
      break
    fi
  done
fi
export CHROME_PATH
export PUPPETEER_EXECUTABLE_PATH="${PUPPETEER_EXECUTABLE_PATH:-$CHROME_PATH}"
export PUPPETEER_SKIP_DOWNLOAD="${PUPPETEER_SKIP_DOWNLOAD:-1}"

staged=docs/.slides.build.md
trap 'rm -f "$staged"' EXIT

python3 scripts/render_mermaid.py docs/slides.md "$staged"

npx --yes @marp-team/marp-cli@latest "$staged" \
  --theme-set docs/marp-theme.css \
  --allow-local-files \
  --html \
  --wait 2000 \
  --pdf \
  --output docs/slides.pdf
