/* =====================================================================
   Nira site — the small amount of behaviour a landing page needs.
   ---------------------------------------------------------------------
   The theme ships an 885-line runtime built for an app shell: navigation
   trees, charts, a palette engine. None of that belongs on one page, so
   this is written fresh against the theme's tokens.
   ===================================================================== */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };

  /* ---------- Theme ----------
     Follows the system by default and remembers an explicit choice, so the
     page matches the desktop it is being read on. localStorage is wrapped
     because it throws outright in a private window. */
  var STORE_KEY = 'nira-site-theme';

  function readStored() {
    try { return localStorage.getItem(STORE_KEY); } catch (e) { return null; }
  }
  function writeStored(value) {
    try { localStorage.setItem(STORE_KEY, value); } catch (e) { /* not fatal */ }
  }

  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)');

  function applyTheme(mode) {
    var dark = mode === 'dark' || (mode !== 'light' && prefersDark.matches);
    document.body.classList.toggle('dark', dark);
    var button = $('#theme');
    if (button) {
      button.textContent = dark ? '☾' : '☀';
      button.setAttribute('aria-label', dark ? 'Switch to light' : 'Switch to dark');
    }
  }

  applyTheme(readStored() || 'system');
  // Follow the OS while the reader has not chosen for themselves.
  prefersDark.addEventListener('change', function () {
    if (!readStored()) applyTheme('system');
  });

  var themeButton = $('#theme');
  if (themeButton) {
    themeButton.addEventListener('click', function () {
      var next = document.body.classList.contains('dark') ? 'light' : 'dark';
      writeStored(next);
      applyTheme(next);
    });
  }

  /* ---------- Quick-start tabs ---------- */
  $$('.tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      $$('.tab').forEach(function (other) {
        var on = other === tab;
        other.classList.toggle('on', on);
        other.setAttribute('aria-selected', String(on));
      });
      $$('.cmd').forEach(function (panel) {
        panel.classList.toggle('on', panel.dataset.panel === tab.dataset.tab);
      });
    });
  });

  /* ---------- Copy the visible command ---------- */
  var copyButton = $('#copy');
  if (copyButton) {
    copyButton.addEventListener('click', function () {
      var panel = $('.cmd.on');
      if (!panel) return;
      // The prompt and the comments are shown, not typed. Copying them gives
      // someone a line that fails the moment they paste it.
      var text = Array.prototype.slice.call(panel.childNodes)
        .filter(function (node) {
          return !(node.nodeType === 1 && (node.classList.contains('p') ||
                                           node.classList.contains('c')));
        })
        .map(function (node) { return node.textContent; })
        .join('')
        .split('\n')
        .map(function (line) { return line.trim(); })
        .filter(Boolean)
        .join('\n');

      var done = function () {
        copyButton.textContent = 'Copied';
        setTimeout(function () { copyButton.textContent = 'Copy'; }, 1600);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
      function fallback() {
        // http:// on a LAN address is not a secure context, and this site is
        // meant to be opened on one.
        var area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        try { document.execCommand('copy'); done(); } catch (e) { /* give up quietly */ }
        document.body.removeChild(area);
      }
    });
  }

  /* ---------- Install ----------
     Instructions, not a link to a repository. The command someone needs is
     the thing they came for, so it is on the page, copyable, and pointed at
     this host — which means it works wherever the page is reachable, over
     the tailnet as readily as over localhost, without depending on a docs
     site that may or may not have been published.

     Sizes and availability still come from the server: a page that
     hard-codes "44 MB" is wrong the first time the file is rebuilt, and one
     that offers a link to a file that is not there is worse than one that
     says so. */

  // Where this page is being served from, which is also where install.sh
  // is. Not hard-coded: localhost while the container is on your desk, the
  // tailnet name once `tailscale serve` is on, and both are correct.
  var ORIGIN = location.origin;

  // Downloads may not live beside the page. The self-hosted container serves
  // them from /downloads/; the hosted site cannot, because a 42 MiB apk
  // exceeds the 25 MiB per-file ceiling on both Pages and Workers assets, so
  // there it comes from an R2 bucket on its own origin. config.json says
  // which, so neither deployment needs a different copy of this file.
  var downloadsBase = '';
  function resolveDownload(file) {
    if (!downloadsBase) return file;
    return downloadsBase.replace(/\/$/, '') + '/' + file.split('/').pop();
  }

  var CATALOG = [
    {
      id: 'server',
      name: 'The server',
      platform: 'Linux · macOS · Windows via WSL2',
      icon: '\u2318',
      blurb: 'The part that does the work: models, agents, tools and memory. Everything else connects to it. Install this first — the phone app is not useful without it.',
      wide: true,
      badge: 'One command',
      badgeKind: 'ready',
      commands: [
        { cmd: 'curl -fsSL ' + ORIGIN + '/install.sh | bash' }
      ],
      steps: [
        'Installs to <code>~/.nira</code> and puts <code>nira</code> on your PATH.',
        'Picks an engine to suit your hardware and pulls a small model to start with.',
        'Then run <code>nira init</code>, and <code>nira serve</code> to bring it up.'
      ],
      note: '<b>Do not use sudo.</b> The installer refuses to run as root and will stop. Run it as yourself; it asks for sudo only if it has to install a missing system package. Piping a URL into bash runs whatever that URL returns, so read it first — <a href="install.sh" rel="noopener">this is the script</a>.'
    },
    {
      id: 'android',
      name: 'Nira for Android',
      platform: 'Android 8.0+ · arm64, x86_64',
      icon: '\u25b2',
      blurb: 'Talk to a paired desktop, watch a run in progress, and answer an approval from the lock screen.',
      file: 'downloads/nira-android.apk',
      steps: [
        'Download the apk on the phone, open it, and allow installs from your browser when Android asks.',
        'On the desktop, run <code>nira device pair my-phone</code> — it prints a QR code.',
        'Scan it from the app. The two are linked over your tailnet from then on.'
      ],
      // Said plainly, because it is the kind of thing a download page
      // usually leaves out. This build is signed with the Android debug
      // key — the one in every copy of the SDK, which authenticates
      // nobody — and is marked debuggable, so anything with adb access
      // can read what it stores, including the key that pairs it to your
      // desktop. A release build replaces this the moment there is a
      // signing key to make one with.
      note: '<b>Debug build.</b> Signed with the Android debug key and marked debuggable — anything with adb access can read its data, including your pairing key. Fine on a phone you control; not a build to hand to someone else. Android will warn you about an unknown source; that warning is correct.',
      missing: 'This build is not on the server. Run <code>cd android &amp;&amp; ./gradlew :app:assembleDebug</code>, copy the apk into <code>website/public/downloads/</code>, and rebuild the image.'
    },
    {
      id: 'desktop',
      name: 'Desktop app',
      platform: 'macOS · Windows · Linux',
      icon: '\u25a3',
      blurb: 'The Tauri desktop build — the same interface as the web UI, in its own window. There is no prebuilt binary to download: Tauri bundles for the machine it is built on, so you build it on yours.',
      commands: [
        { cmd: 'git clone https://github.com/kmahendra999/nira.git\ncd nira/frontend && npm install\nnpm run tauri build' }
      ],
      steps: [
        'Needs Node 20+ and a Rust toolchain; the <a href="https://tauri.app/start/prerequisites/" rel="noopener">Tauri prerequisites</a> list what else your OS needs.',
        'The bundle lands in <code>frontend/src-tauri/target/release/bundle/</code> — a <code>.dmg</code>, <code>.msi</code> or <code>.AppImage</code> depending on where you built it.'
      ]
    }
  ];

  function humanSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    var units = ['B', 'KB', 'MB', 'GB'];
    var index = 0;
    var value = bytes;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return (index === 0 ? value : value.toFixed(1)) + ' ' + units[index];
  }

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function ticks(s) {
    return s.replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  function render(entry, meta) {
    var available = !!(meta && meta.ok);
    var badge = entry.file
      ? (available
          ? '<span class="dl-badge ready">Ready</span>'
          : '<span class="dl-badge source">Not built</span>')
      : '<span class="dl-badge ' + (entry.badgeKind || 'source') + '">' +
        (entry.badge || 'Build it') + '</span>';

    var body = entry.file && !available
      ? entry.missing
      : ticks(entry.blurb);

    // A card whose file is missing should not go on giving instructions for
    // installing it, or print a caveat about a build that is not there.
    var usable = !entry.file || available;

    var commands = '';
    if (usable && entry.commands) {
      commands = entry.commands.map(function (c, i) {
        var id = entry.id + '-cmd-' + i;
        return '<div class="cmdbox">' +
                 '<pre id="' + id + '">' + escapeHtml(c.cmd) + '</pre>' +
                 '<button class="gbtn mini-copy" type="button" data-copy="' + id + '">Copy</button>' +
               '</div>';
      }).join('');
    }

    var steps = '';
    if (usable && entry.steps) {
      steps = '<ol class="dl-steps">' +
        entry.steps.map(function (s) { return '<li>' + s + '</li>'; }).join('') +
        '</ol>';
    }

    var caveat = '';
    if (usable && entry.note) {
      caveat = '<div class="dl-note">' + entry.note +
        (meta && meta.sha256
          ? '<span class="dl-sum">sha256 ' + meta.sha256 + '</span>'
          : '') +
        '</div>';
    }

    var foot = '';
    if (entry.file && available) {
      foot = '<div class="dl-foot">' +
               '<a class="dl-btn" href="' + resolveDownload(entry.file) +
                 '" download>Download</a>' +
               (meta.size ? '<span class="dl-size">' + humanSize(meta.size) + '</span>' : '') +
             '</div>';
    }

    return '' +
      '<article class="dl' + (entry.wide ? ' wide' : '') + '">' +
        '<div class="dl-top">' +
          '<span class="dl-ico" aria-hidden="true">' + entry.icon + '</span>' +
          '<div><h3>' + entry.name + '</h3>' +
          '<div class="plat">' + entry.platform + '</div></div>' +
          '<div style="margin-left:auto">' + badge + '</div>' +
        '</div>' +
        '<p>' + body + '</p>' +
        (commands || steps
          ? '<div class="dl-body">' + commands + steps + '</div>'
          : '') +
        caveat +
        foot +
      '</article>';
  }

  // Copy on the per-card command blocks. Delegated, because the cards are
  // rendered after this runs.
  function copyText(text, button) {
    var done = function () {
      var was = button.textContent;
      button.textContent = 'Copied';
      setTimeout(function () { button.textContent = was; }, 1600);
    };
    var fallback = function () {
      var area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try { document.execCommand('copy'); done(); } catch (e) { /* give up quietly */ }
      document.body.removeChild(area);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('[data-copy]');
    if (!button) return;
    var pre = document.getElementById(button.dataset.copy);
    if (pre) copyText(pre.textContent, button);
  });

  var grid = $('#downloads');
  if (grid) {
    // Resolved before the cards render, so a card never points at the wrong
    // origin for a moment and then corrects itself.
    var configured = fetch('config.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (c) { downloadsBase = (c && c.downloadsBase) || ''; })
      .catch(function () { downloadsBase = ''; });
    // checksums.json is written when the image is built, by hashing
    // whatever was copied in. Hard-coding a digest here would be a digest
    // of whichever file happened to be present the day it was written,
    // which is worse than none: it would keep matching in the reader's eye
    // long after it stopped matching the file.
    var sums = configured
      .then(function () { return fetch(resolveDownload('downloads/checksums.json')); })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });

    // Ask the server whether each file is actually there, with HEAD so a
    // 44 MB apk is not pulled down just to render a card.
    var heads = configured.then(function () {
      return Promise.all(CATALOG.map(function (entry) {
      if (!entry.file) return Promise.resolve(null);
      return fetch(resolveDownload(entry.file), { method: 'HEAD' })
        .then(function (response) {
          return {
            ok: response.ok,
            size: parseInt(response.headers.get('content-length') || '0', 10)
          };
        })
        .catch(function () { return { ok: false, size: 0 }; });
      }));
    });

    Promise.all([configured, heads, sums]).then(function (both) {
      var results = both[1];
      var digests = both[2] || {};
      grid.innerHTML = CATALOG.map(function (entry, index) {
        var meta = results[index];
        if (meta && entry.file) {
          var name = entry.file.split('/').pop();
          if (digests[name]) meta.sha256 = digests[name];
        }
        return render(entry, meta);
      }).join('');
    });
  }

  /* ---------- Where this page is being served from ----------
     The quick-start command is written with localhost:8080 in the markup so
     the page still reads correctly with scripting off, and is rewritten to
     the real origin here. Someone reading this over `tailscale serve` on
     their phone should be able to copy a command that works on their
     laptop, not one pointing at a port on whatever machine they are
     holding. */
  $$('.host').forEach(function (node) { node.textContent = location.origin; });

  var served = $('#served');
  if (served) served.textContent = 'served from ' + location.host;
})();
