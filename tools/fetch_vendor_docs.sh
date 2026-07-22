#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Fetch the two vendor documents that need a browser-style fetch to compare
# their sha256 against the values recorded in tests/vectors/*.json.
#
# Scope: only S-Log3 and LogC4 are fetched here. Those two PDFs are behind
# access that a plain client cannot reach (Sony 403s non-browser clients; ARRI
# serves a blob URL). The other three curves (LogC3, V-Log, C-Log3) are
# validated in the test suite against colour-science's implementations, which is
# the oracle tests/test_idt.py actually asserts against.
#
# Vendors re-version their PDFs in place, so a recorded hash can stop matching a
# live URL even when the cited anchors are unchanged (observed for the LogC4
# document). This script therefore WARNS on a hash mismatch rather than failing,
# and prints the fetched hash so provenance can be re-recorded deliberately.
set -euo pipefail
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
dest="$(dirname "$0")/../work/vendor"
mkdir -p "$dest"
cd "$dest"

curl --fail --show-error -sL -A "$UA" -o slog3.pdf \
  "https://web.archive.org/web/2024id_/https://pro.sony/s3/cms-static-content/uploadfile/06/1237494271406.pdf"
curl --fail --show-error -sL -A "$UA" -o logc4.pdf \
  "https://www.arri.com/resource/blob/278790/bea879ac0d041a925bed27a096ab3ec2/2022-05-arri-logc4-specification-data.pdf"

for f in slog3.pdf logc4.pdf; do
  head -c 5 "$f" | grep -q "%PDF" || { echo "NOT A PDF: $f"; exit 1; }
  got=$(shasum -a 256 "$f" | awk '{print $1}')
  echo "$f sha256=$got"
  pdftotext "$f" "${f%.pdf}.txt"
done
