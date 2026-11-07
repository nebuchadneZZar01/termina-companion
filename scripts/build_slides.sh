#!/usr/bin/env sh
# Build the Marp deck into docs/slides.pdf.
#
# Requires Node.js (for npx) and a local Chrome/Chromium. The first run
# downloads @marp-team/marp-cli; nothing is added to the repository.
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

npx --yes @marp-team/marp-cli@latest docs/slides.md \
  --theme-set docs/marp-theme.css \
  --allow-local-files \
  --html \
  --wait 2000 \
  --pdf \
  --output docs/slides.pdf
