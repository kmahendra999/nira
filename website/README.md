# The Nira site

The front page, and the place the Android build is downloaded from. Static
files on nginx in a container — there is no application here, and nothing
in the image can execute a request.

The public copy is published to **https://kmahendra999.github.io/nira/** by
`.github/workflows/docs.yml`. This container is the local copy: the same
files, served from your own machine.

## Run it

```bash
docker compose -f website/docker-compose.yml up -d --build
```

Then open <http://localhost:8080>.

## Getting the app onto a phone

The container binds to `127.0.0.1` on purpose. It serves an installable
Android package, and binding every interface would publish that package to
whatever network the machine is on — a cafe, a hotel, a conference.

Your phone reaches it the same way it reaches the rest of Nira:

```bash
tailscale serve --bg 8080
```

That publishes the site to your tailnet and to nothing else. `tailscale
serve status` prints the URL to open on the phone.

If you would rather put it on the local network, that is one variable and
your decision to make:

```bash
NIRA_SITE_BIND=0.0.0.0 docker compose -f website/docker-compose.yml up -d
```

`NIRA_SITE_PORT` moves it off 8080.

## What is in `public/`

| | |
|---|---|
| `index.html` | the page |
| `assets/glass.css` | the theme, copied in, with the accent retuned to Nira's orange |
| `assets/site.css` | page layout, written against the theme's tokens |
| `assets/site.js` | theme toggle, quick-start tabs, copy button, download cards |
| `assets/fonts.css`, `assets/fonts/` | Geist, self-hosted |
| `assets/nira-mark.svg` | the mark, shared with the desktop icon |
| `downloads/` | what the page offers |

Nothing on the page loads anything off this origin — no font CDN, no
analytics, no app store. That is checkable: the Content-Security-Policy
nginx sends is `default-src 'self'` with no exceptions for a third party,
so an off-origin request would fail rather than quietly succeed.

## The installer

`/install.sh` is `scripts/install/install.sh`, copied into the image at build
time — which is why the build context is the repository root, pared back by
`.dockerignore` at the root. There is one copy of that script, not two.

It is served as `text/plain` so that opening the URL shows the script. The
page links to it next to the command, because piping a URL into bash runs
whatever that URL returns, and the reader should be able to look first.

The command shown on the page is built from `location.origin`, so it names
whichever host the page was reached on — `localhost:8080` at your desk, the
tailnet name under `tailscale serve`. Nothing hard-codes a hostname.

## Adding a download

Drop the file in `public/downloads/`, add an entry to `CATALOG` in
`assets/site.js`, and rebuild.

The page does not hard-code sizes or digests. It asks the server for the
size with a `HEAD` request and reads the digest from
`downloads/checksums.json`, which the Dockerfile generates at build time by
hashing whatever was copied in. A card for a file that is not on the server
says so instead of offering a link that 404s — so a catalogue entry can be
added before the build exists.

## The Android build is a debug build

It is signed with the Android debug key — the one in every copy of the SDK,
which authenticates nobody — and is marked `debuggable`, so anything with
adb access can read what it stores, including the key that pairs it to your
desktop. The download card says this. It should keep saying it until there
is a signing key and a release build, at which point both the file and that
paragraph need replacing.

To rebuild the apk from source:

```bash
cd android && ./gradlew :app:assembleDebug
cp app/build/outputs/apk/debug/app-debug.apk ../website/public/downloads/nira-android.apk
```

Then rebuild the image, which re-hashes it.
