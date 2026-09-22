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
     Instructions, not a link to a repository, and the instructions for the
     machine the reader is actually on. Everything is still reachable if the
     detection guesses wrong: the tabs are real tabs, and the table below
     lists every file regardless of platform. */

  // The directory of this document, not location.origin: a project Pages
  // site is served from a subpath, and origin alone printed a command
  // pointing at kmahendra999.github.io/install.sh, which does not exist.
  var ORIGIN = new URL('.', location.href).href.replace(/\/$/, '');

  // Where the builds live. Empty means beside this page, which is what the
  // self-hosted container serves; the hosted site points at releases,
  // because a 42 MiB apk does not belong in the repository.
  var downloadsBase = '';
  function resolveDownload(file) {
    if (!downloadsBase) return file;
    return downloadsBase.replace(/\/$/, '') + '/' + file.split('/').pop();
  }

  var APK = 'downloads/nira-android.apk';
  var REPO = 'https://github.com/kmahendra999/nira';

  function shell(cmd) {
    return { kind: 'cmd', cmd: cmd };
  }

  /* Each platform answers the same three questions: what do I need first,
     what do I run, and what happens after. */
  var PLATFORMS = {
    macos: {
      name: 'macOS',
      needs: 'macOS 12 or later, Apple Silicon or Intel. Nothing else — the installer brings its own Python and inference engine.',
      blocks: [
        { title: 'Install the server',
          body: shell('curl -fsSL ' + ORIGIN + '/install.sh | bash'),
          note: 'Run it as yourself. The installer refuses to run as root and will stop if you use <code>sudo</code>.' },
        { title: 'Start it',
          body: shell('nira init\nnira serve') },
        { title: 'Desktop app',
          body: shell('git clone ' + REPO + '.git\ncd nira/frontend && npm install\nnpm run tauri build'),
          note: 'Produces a <code>.dmg</code> in <code>frontend/src-tauri/target/release/bundle/</code>. There is no notarised build to download — Tauri bundles for the machine it is built on.' }
      ],
      steps: [
        'Models are pulled to <code>~/.nira</code> and stay there.',
        'The web UI is at <code>http://localhost:8765</code> once <code>nira serve</code> is running.',
        'To pair a phone, run <code>nira device pair my-phone</code> and scan the QR code.'
      ]
    },

    linux: {
      name: 'Linux',
      needs: 'Any modern distribution, x86_64 or arm64. <code>curl</code> and <code>git</code>; the installer will offer to fetch anything else it needs.',
      blocks: [
        { title: 'Install the server',
          body: shell('curl -fsSL ' + ORIGIN + '/install.sh | bash'),
          note: 'Run it as yourself, not with <code>sudo</code> — it installs to <code>~/.nira</code>, not <code>/usr/local</code>, and refuses to run as root.' },
        { title: 'Start it',
          body: shell('nira init\nnira serve') },
        { title: 'Desktop app',
          body: shell('git clone ' + REPO + '.git\ncd nira/frontend && npm install\nnpm run tauri build'),
          note: 'Produces an <code>.AppImage</code> and a <code>.deb</code>. Needs the <a href="https://tauri.app/start/prerequisites/" rel="noopener">Tauri prerequisites</a> — on Debian/Ubuntu that is <code>libwebkit2gtk-4.1-dev</code> and <code>build-essential</code>.' }
      ],
      steps: [
        'An NVIDIA or AMD GPU is detected and used automatically; CPU-only works too.',
        'The web UI is at <code>http://localhost:8765</code> once <code>nira serve</code> is running.',
        'To reach it from another machine, bind it to your tailnet rather than to <code>0.0.0.0</code>.'
      ]
    },

    windows: {
      name: 'Windows',
      needs: 'Windows 10 2004 or later, with WSL2. The CLI does not run on native Windows — Git Bash and MSYS2 install to paths the rest of Nira cannot reach, and the installer stops early rather than let you find that out three minutes in.',
      blocks: [
        { title: 'Set up WSL2, once',
          body: shell('wsl --install -d Ubuntu-24.04'),
          note: 'In an <b>administrator</b> PowerShell. Reboot when it asks, then open the Ubuntu shell it installed.' },
        { title: 'Install the server, inside Ubuntu',
          body: shell('curl -fsSL ' + ORIGIN + '/install.sh | bash') },
        { title: 'Start it',
          body: shell('nira init\nnira serve') }
      ],
      steps: [
        'Everything after the first step happens inside the Ubuntu shell, not PowerShell.',
        'The web UI is at <code>http://localhost:8765</code> in your Windows browser — WSL2 forwards it.',
        'A native <code>.msi</code> desktop build can be produced with <code>npm run tauri build</code> on Windows, separately from the WSL2 server.'
      ]
    },

    android: {
      name: 'Android',
      needs: 'Android 8.0 or later. The app talks to a desktop you have paired with — <b>install the server first</b>, on the machine you want it to drive.',
      blocks: [
        { title: 'Download the app', body: { kind: 'download' },
          note: '<b>Debug build.</b> Signed with the Android debug key and marked debuggable — anything with adb access can read its data, including your pairing key. Fine on a phone you control; not a build to hand to someone else. Android will warn you about an unknown source; that warning is correct.' },
        { title: 'Pair it, from the desktop',
          body: shell('nira device pair my-phone'),
          note: 'Prints a QR code. Scan it from the app and the two are linked over your tailnet.' }
      ],
      steps: [
        'Open the apk on the phone and allow installs from your browser when Android asks.',
        'Speak a command, watch a run in progress, and answer an approval from the lock screen.',
        'Your data stays on the desktop. The phone is a window onto it, not a copy of it.'
      ]
    }
  };

  /* ---------- Which platform is this? ---------- */
  function detectOs() {
    var ua = navigator.userAgent || '';
    var plat = (navigator.userAgentData && navigator.userAgentData.platform) || '';
    if (/Android/i.test(ua)) return 'android';
    if (/iPhone|iPad|iPod/i.test(ua)) return 'macos';   // nearest useful answer
    if (/Mac|Darwin/i.test(plat + ua)) return 'macos';
    if (/Win/i.test(plat + ua)) return 'windows';
    if (/Linux|X11|CrOS/i.test(plat + ua)) return 'linux';
    return 'linux';
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  var apkMeta = { ok: false, size: 0, unmeasured: false, sha256: '' };

  function humanSize(bytes) {
    if (!bytes) return '';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0, v = bytes;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return (i === 0 ? v : v.toFixed(1)) + ' ' + units[i];
  }

  function downloadBlock() {
    if (!apkMeta.ok) {
      return '<div class="dl-missing">This build is not on the server yet. ' +
             'Build it with <code>cd android &amp;&amp; ./gradlew :app:assembleDebug</code>, ' +
             'or check the <a href="' + REPO + '/releases" rel="noopener">releases page</a>.</div>';
    }
    return '<div class="dl-row">' +
      '<a class="dl-btn" href="' + resolveDownload(APK) + '" download>Download the apk</a>' +
      '<span class="dl-size">' +
        (apkMeta.size ? humanSize(apkMeta.size) : 'from the latest release') +
        ' &middot; arm64, armv7, x86, x86_64' +
      '</span></div>' +
      (apkMeta.sha256
        ? '<div class="dl-sum">sha256 ' + apkMeta.sha256 + '</div>'
        : '');
  }

  function renderPanel(os) {
    var p = PLATFORMS[os];
    var i = 0;
    var blocks = p.blocks.map(function (b) {
      i += 1;
      var body;
      if (b.body.kind === 'download') {
        body = downloadBlock();
      } else {
        var id = 'cmd-' + os + '-' + i;
        body = '<div class="cmdbox">' +
                 '<pre id="' + id + '">' + escapeHtml(b.body.cmd) + '</pre>' +
                 '<button class="gbtn mini-copy" type="button" data-copy="' + id + '">Copy</button>' +
               '</div>';
      }
      return '<div class="step">' +
               '<div class="step-n" aria-hidden="true">' + i + '</div>' +
               '<div class="step-body">' +
                 '<h4>' + b.title + '</h4>' + body +
                 (b.note ? '<p class="step-note">' + b.note + '</p>' : '') +
               '</div>' +
             '</div>';
    }).join('');

    return '<div class="plat-panel">' +
             '<p class="needs"><b>What you need:</b> ' + p.needs + '</p>' +
             blocks +
             '<ul class="after"><li>' + p.steps.join('</li><li>') + '</li></ul>' +
           '</div>';
  }

  var panels = $('#plat-panels');
  var hint = $('#plat-hint');

  function selectOs(os, fromUser) {
    $$('.plat-tab').forEach(function (t) {
      var on = t.dataset.os === os;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', String(on));
    });
    if (panels) panels.innerHTML = renderPanel(os);
    if (hint) {
      hint.textContent = fromUser ? '' : 'detected — pick another if that is wrong';
    }
    try { localStorage.setItem('nira-site-os', os); } catch (e) { /* not fatal */ }
  }

  $$('.plat-tab').forEach(function (t) {
    t.addEventListener('click', function () { selectOs(t.dataset.os, true); });
  });

  /* ---------- The table of everything ---------- */
  function renderTable() {
    var rows = [
      { file: 'install.sh', what: 'Server installer',
        plat: 'macOS &middot; Linux &middot; WSL2', arch: 'x86_64, arm64',
        size: '', href: ORIGIN + '/install.sh', cta: 'View' },
      { file: 'nira-android.apk', what: 'Android app',
        plat: 'Android 8.0+', arch: 'arm64, armv7, x86, x86_64',
        size: apkMeta.ok ? (apkMeta.size ? humanSize(apkMeta.size) : 'latest release') : 'not built',
        href: apkMeta.ok ? resolveDownload(APK) : REPO + '/releases',
        cta: apkMeta.ok ? 'Download' : 'Releases' },
      { file: 'Source', what: 'Everything, to build yourself',
        plat: 'any', arch: '—', size: '',
        href: REPO, cta: 'GitHub' }
    ];
    var body = $('#dl-table-body');
    if (!body) return;
    body.innerHTML = rows.map(function (r) {
      return '<tr>' +
        '<td><b>' + r.file + '</b><span class="td-sub">' + r.what + '</span></td>' +
        '<td>' + r.plat + '</td>' +
        '<td class="mono">' + r.arch + '</td>' +
        '<td>' + (r.size || '&mdash;') + '</td>' +
        '<td class="ta-r"><a class="tbl-link" href="' + r.href + '"' +
          (r.cta === 'Download' ? ' download' : ' rel="noopener"') + '>' + r.cta + '</a></td>' +
      '</tr>';
    }).join('');
  }

  /* ---------- Copy, delegated, because panels re-render ---------- */
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

  /* ---------- Ask the server what is actually there ---------- */
  if (panels) {
    var stored = null;
    try { stored = localStorage.getItem('nira-site-os'); } catch (e) { /* ignore */ }

    fetch('config.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (c) { downloadsBase = (c && c.downloadsBase) || ''; })
      .catch(function () { downloadsBase = ''; })
      .then(function () {
        // HEAD, so a 42 MiB apk is not pulled down just to size a button.
        return fetch(resolveDownload(APK), { method: 'HEAD' })
          .then(function (r) {
            apkMeta.ok = r.ok;
            apkMeta.size = parseInt(r.headers.get('content-length') || '0', 10);
          })
          .catch(function () {
            // A thrown fetch and a 404 mean different things. A release lives
            // on an origin with no CORS headers, so the probe throws before it
            // can read a status -- which says nothing about whether the file
            // is there. Treating the two alike made a working download render
            // as missing.
            apkMeta.ok = true;
            apkMeta.unmeasured = true;
          });
      })
      .then(function () {
        return fetch(resolveDownload('downloads/checksums.json'))
          .then(function (r) { return r.ok ? r.json() : {}; })
          .then(function (d) { apkMeta.sha256 = d['nira-android.apk'] || ''; })
          .catch(function () { /* published with the release instead */ });
      })
      .then(function () {
        selectOs(stored || detectOs(), !!stored);
        renderTable();
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
