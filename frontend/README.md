# Nira frontend

React 19 + Vite + Tailwind v4, shipped two ways from one source tree:

- `npm run build` writes the SPA into `../src/nira/server/static/`, which is
  what `nira serve` serves (and what installs as a PWA on a phone).
- `npm run build:tauri` writes to `dist/`, which the Tauri desktop app bundles.

## Toolchain

**Use npm 11.19.0.** `package.json` pins it via `packageManager` and enforces it
with `engines` plus `engine-strict=true` in `.npmrc`:

```bash
npm install --global npm@11.19.0
npm ci
```

This is what CI does (`.github/workflows/frontend.yml`), and it is not
bureaucratic — two things break quietly on an older npm:

**The lockfile loses platform constraints.** Installing with npm < 11.19 rewrites
`package-lock.json` and strips the `"libc": ["glibc"]` / `["musl"]` fields from
optional dependencies. Committing that lockfile breaks installs on Alpine/musl
and on cross-platform CI. The damage is invisible in a diff unless you look for
it.

**Install-script allowlisting stops being enforced.** `.npmrc` sets
`strict-allow-scripts=true` and `package.json` carries an `allowScripts` block
denying `core-js` and `fsevents`. npm 11.19 honours that; older npm reports
`Unknown project config "strict-allow-scripts"` and installs run whatever
lifecycle scripts they like. That is a supply-chain control, so losing it
silently is the worst part of the mismatch.

So do **not** reach for `npm install --engine-strict=false`. It appears to work,
and it is how both of the above happen. If you have already run it, restore the
lockfile before committing:

```bash
git -C .. checkout -- frontend/package-lock.json
```

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server, proxying `/v1`, `/health` and `/api` (including WebSocket upgrades) to `http://localhost:8000` |
| `npm run build` | Type-check, then build into the Python package's static dir |
| `npm run build:tauri` | Same, but into `dist/` for the desktop bundle |
| `npm test` | Vitest |
| `npm run tauri` | Tauri CLI |

A Linux Tauri build additionally needs `libdbus-1-dev` (for the `keyring`
secret-service backend) and the usual webkit2gtk development packages.
