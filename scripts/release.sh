#!/usr/bin/env bash
# Cut a release and attach the Android build.
#
# The apk is 42 MiB of build output and is gitignored, so the site points at
# a release asset rather than at a file in the repository. Release assets
# have no size or bandwidth limit and do not count against repository
# storage; committing the apk would add another 42 MiB blob to history on
# every rebuild, permanently.
#
# Usage:
#   GITHUB_TOKEN=ghp_xxx ./scripts/release.sh v0.1.0
#
# The token needs "Contents: read and write" on this repository. Nothing
# here prints it.
set -euo pipefail

TAG="${1:-}"
REPO="${NIRA_REPO:-kmahendra999/nira}"
APK="website/public/downloads/nira-android.apk"

[ -n "$TAG" ] || { echo "usage: $0 <tag>   e.g. $0 v0.1.0" >&2; exit 2; }
[ -n "${GITHUB_TOKEN:-}" ] || { echo "set GITHUB_TOKEN (Contents: read and write)" >&2; exit 2; }
[ -f "$APK" ] || {
    echo "$APK is missing. Build it first:" >&2
    echo "  cd android && ./gradlew :app:assembleDebug" >&2
    echo "  cp app/build/outputs/apk/debug/app-debug.apk ../$APK" >&2
    exit 1; }

SIZE=$(stat -c%s "$APK")
SUM=$(sha256sum "$APK" | cut -d' ' -f1)
echo "apk:    $APK  ($((SIZE / 1024 / 1024)) MiB)"
echo "sha256: $SUM"

api() { curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
                 -H "Accept: application/vnd.github+json" "$@"; }

# The digest goes in the release notes, because the page cannot read it:
# a release lives on an origin that sends no CORS headers, so the browser
# cannot fetch a checksums file from it.
NOTES=$(cat <<EOF
Nira $TAG

**Android** — \`nira-android.apk\`, $((SIZE / 1024 / 1024)) MiB, arm64-v8a / armeabi-v7a / x86 / x86_64, Android 8.0+.

\`\`\`
sha256  $SUM
\`\`\`

> **This is a debug build.** It is signed with the Android debug key — the one
> shipped in every copy of the SDK, which authenticates nobody — and is marked
> \`debuggable\`, so anything with adb access can read what it stores, including
> the key that pairs it to your desktop. Install it on a phone you control.
> Android will warn you about an unknown source; that warning is correct.

Install the server first: https://kmahendra999.github.io/nira/
EOF
)

echo "creating release $TAG..."
RESP=$(api -X POST "https://api.github.com/repos/$REPO/releases" \
    -d "$(python3 -c '
import json, os, sys
print(json.dumps({
    "tag_name": sys.argv[1],
    "name": "Nira " + sys.argv[1],
    "body": sys.argv[2],
    "draft": False,
    "prerelease": True,
}))' "$TAG" "$NOTES")")

ID=$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("id") or ""); sys.stderr.write((d.get("message") or "") + "\n")')
[ -n "$ID" ] || { echo "could not create the release" >&2; printf '%s\n' "$RESP" | head -20 >&2; exit 1; }

echo "uploading the apk ($((SIZE / 1024 / 1024)) MiB)..."
curl -sS --fail-with-body \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Content-Type: application/vnd.android.package-archive" \
    --data-binary @"$APK" \
    "https://uploads.github.com/repos/$REPO/releases/$ID/assets?name=nira-android.apk" \
    -o /dev/null

echo
echo "done:      https://github.com/$REPO/releases/tag/$TAG"
echo "the site links to: https://github.com/$REPO/releases/latest/download/nira-android.apk"
