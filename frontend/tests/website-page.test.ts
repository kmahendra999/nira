/**
 * The download page, which was verified once in a browser and never again.
 *
 * `website/public/assets/site.js` is an IIFE with no exports, so the only way
 * to exercise it is to boot the real shipped files in a document and drive it
 * through the DOM -- which is also the only way to catch the thing most worth
 * catching: the download probe has to tell a 404 apart from a fetch that threw.
 * A release lives on an origin that sends no CORS headers, so the probe throws
 * before it can read a status, and treating that like a 404 rendered a working
 * download as "not built".
 *
 * These read the files from `website/public` rather than a copy, so they fail
 * if the shipped page changes underneath them.
 */

import fs from 'node:fs'
import path from 'node:path'
import { JSDOM } from 'jsdom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const PUBLIC = path.resolve(import.meta.dirname, '../../website/public')
const HTML = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8')
const SITE_JS = fs.readFileSync(path.join(PUBLIC, 'assets/site.js'), 'utf8')

type Reply = { ok: boolean; status?: number; headers?: Record<string, string>; json?: unknown }

/**
 * Boot the page with a scripted `fetch`. `routes` maps a URL substring to a
 * reply, or to the string 'throw' for the cross-origin case.
 */
async function boot(options: {
  url?: string
  userAgent?: string
  routes?: Record<string, Reply | 'throw'>
} = {}) {
  const { url = 'http://localhost:8080/', userAgent, routes = {} } = options

  const dom = new JSDOM(HTML, {
    url,
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  })
  const win = dom.window as unknown as Window & typeof globalThis & Record<string, unknown>

  // jsdom 29 ignores its own `userAgent` option, so `detectOs` would always
  // see Linux and the platform tests would pass for the wrong reason.
  if (userAgent) {
    Object.defineProperty(win.navigator, 'userAgent', {
      value: userAgent,
      configurable: true,
    })
  }

  win.fetch = vi.fn(async (input: unknown) => {
    const href = String(input)
    for (const [needle, reply] of Object.entries(routes)) {
      if (!href.includes(needle)) continue
      if (reply === 'throw') throw new TypeError('Failed to fetch')
      return {
        ok: reply.ok,
        status: reply.status ?? (reply.ok ? 200 : 404),
        headers: { get: (k: string) => reply.headers?.[k.toLowerCase()] ?? null },
        json: async () => reply.json ?? {},
      }
    }
    throw new TypeError('Failed to fetch')
  }) as unknown as typeof fetch

  // jsdom implements neither, and site.js calls both on load.
  win.matchMedia = ((q: string) => ({
    matches: false,
    media: q,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia

  // An IIFE: it runs on evaluation, with no DOMContentLoaded hook.
  win.eval(SITE_JS)
  // Let the config -> HEAD -> checksums promise chain settle.
  await new Promise((r) => setTimeout(r, 10))
  return { dom, win, doc: win.document }
}

const APK = 'downloads/nira-android.apk'

// The download card is rendered only by the Android panel, so `detectOs` has
// to land there for these tests to see it at all.
const ANDROID_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36'

describe('the download card', () => {
  it('says the build is missing, and prints the command that makes it', async () => {
    const { doc } = await boot({
      userAgent: ANDROID_UA,
      routes: {
        'config.json': { ok: true, json: {} },
        [APK]: { ok: false, status: 404 },
        'checksums.json': { ok: false, status: 404 },
      },
    })

    const text = doc.body.textContent ?? ''
    expect(text).toContain('not on the server yet')
    expect(text).toContain('gradlew :app:assembleDebug')
    expect(doc.querySelector('.dl-btn')).toBeNull()
  })

  it('offers the download when the file is there, with its size', async () => {
    const { doc } = await boot({
      userAgent: ANDROID_UA,
      routes: {
        'config.json': { ok: true, json: {} },
        [APK]: { ok: true, headers: { 'content-length': String(44110917) } },
        'checksums.json': { ok: true, json: { 'nira-android.apk': 'a'.repeat(64) } },
      },
    })

    const button = doc.querySelector('.dl-btn')
    expect(button).not.toBeNull()
    expect(doc.querySelector('.dl-size')?.textContent).toContain('42.1 MB')
    expect(doc.querySelector('.dl-sum')?.textContent).toContain('a'.repeat(64))
  })

  it('a thrown probe is an unmeasurable download, not a missing one', async () => {
    // The regression this file exists for. A release asset is cross-origin and
    // sends no CORS headers, so the HEAD throws before any status is readable.
    const { doc } = await boot({
      userAgent: ANDROID_UA,
      routes: {
        'config.json': {
          ok: true,
          json: { downloadsBase: 'https://github.com/o/r/releases/latest/download' },
        },
        'nira-android.apk': 'throw',
        'checksums.json': 'throw',
      },
    })

    const text = doc.body.textContent ?? ''
    expect(doc.querySelector('.dl-btn')).not.toBeNull()
    expect(text).not.toContain('not on the server yet')
    // No size, because nothing could measure it -- but still downloadable.
    expect(doc.querySelector('.dl-size')?.textContent).toContain('from the latest release')
  })
})

describe('the install command', () => {
  it('is built from the directory of the page, not the bare origin', async () => {
    // A project Pages site is served from a subpath. Using location.origin
    // printed kmahendra999.github.io/install.sh, which does not exist.
    const { doc } = await boot({
      url: 'https://kmahendra999.github.io/nira/',
      routes: {
        'config.json': { ok: true, json: {} },
        [APK]: { ok: false, status: 404 },
        'checksums.json': { ok: false, status: 404 },
      },
    })

    const text = doc.body.textContent ?? ''
    expect(text).toContain('https://kmahendra999.github.io/nira/install.sh')
    expect(text).not.toContain('https://kmahendra999.github.io/install.sh')
  })

  it('names whatever host the page was reached on', async () => {
    const { doc } = await boot({
      url: 'http://nira-box.tail1234.ts.net:8080/',
      routes: {
        'config.json': { ok: true, json: {} },
        [APK]: { ok: false, status: 404 },
        'checksums.json': { ok: false, status: 404 },
      },
    })

    expect(doc.body.textContent ?? '').toContain('http://nira-box.tail1234.ts.net:8080/install.sh')
  })
})

describe('the platform panel', () => {
  const routes = {
    'config.json': { ok: true, json: {} },
    [APK]: { ok: false, status: 404 },
    'checksums.json': { ok: false, status: 404 },
  } as Record<string, Reply>

  it('opens on the platform the reader is on', async () => {
    const { doc } = await boot({
      userAgent:
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36',
      routes,
    })

    const selected = doc.querySelector('[data-os].on')
    expect(selected?.getAttribute('data-os')).toBe('macos')
  })

  it('switches when another platform is chosen', async () => {
    const { win, doc } = await boot({ routes })

    const linux = doc.querySelector<HTMLElement>('[data-os="linux"]')
    expect(linux).not.toBeNull()
    linux!.dispatchEvent(new win.Event('click', { bubbles: true }))

    const selected = doc.querySelector('[data-os].on')
    expect(selected?.getAttribute('data-os')).toBe('linux')
  })
})
