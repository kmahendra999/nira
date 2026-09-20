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

  /* ---------- Downloads ----------
     Described here, but the size and availability of each file come from the
     server. A page that hard-codes "44 MB" is wrong the first time the file
     is rebuilt, and one that offers a link to a file that is not there is
     worse than one that says so. */
  var CATALOG = [
    {
      id: 'android',
      name: 'Nira for Android',
      platform: 'Android 8.0+ · arm64, x86_64',
      icon: '▲',
      blurb: 'Talk to a paired desktop, watch a run in progress, and answer an approval from the lock screen. Pair it with `nira device pair`.',
      file: 'downloads/nira-android.apk',
      // Said plainly, because it is the kind of thing a download page
      // usually leaves out. This build is signed with the Android debug
      // key — the one in every copy of the SDK, which authenticates
      // nobody — and is marked debuggable, so anything with adb access
      // can read what it stores, including the key that pairs it to your
      // desktop. Use it on a phone you control. A release build replaces
      // this the moment there is a signing key to make one with.
      note: '<b>Debug build.</b> Signed with the Android debug key and marked debuggable — anything with adb access can read its data, including your pairing key. Fine on a phone you control; not a build to hand to someone else. Android will warn you about an unknown source; that warning is correct.'
    },
    {
      id: 'desktop',
      name: 'Desktop app',
      platform: 'macOS · Windows · Linux',
      icon: '▣',
      blurb: 'The Tauri desktop build. No binary is published here yet — build it from source with `npm run tauri build`, which produces a bundle for the machine you run it on.',
      href: 'https://github.com/kmahendra999/nira#desktop',
      cta: 'Build from source'
    },
    {
      id: 'server',
      name: 'The server',
      platform: 'Python 3.12 · any OS',
      icon: '⌘',
      blurb: 'The part that does the work: models, agents, tools and memory. Everything else connects to it. Clone and `uv sync`.',
      href: 'https://github.com/kmahendra999/nira',
      cta: 'Get the source'
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

  function render(entry, meta) {
    var available = !!(meta && meta.ok);
    var href = entry.file && available ? entry.file : entry.href;
    var label = entry.file && available ? 'Download' : (entry.cta || 'Open');
    var ghost = entry.file && available ? '' : ' ghost';
    var badge = entry.file
      ? (available
          ? '<span class="badge ready">Ready</span>'
          : '<span class="badge source">Not built</span>')
      : '<span class="badge source">Source</span>';

    var note = entry.file && !available
      ? 'This build is not on the server. Run <code>cd android &amp;&amp; ./gradlew :app:assembleDebug</code>, copy the apk into <code>website/public/downloads/</code>, and rebuild the image.'
      : entry.blurb.replace(/`([^`]+)`/g, '<code>$1</code>');

    // The caveat and the checksum only mean anything next to a file that
    // is actually there; on a card offering source they are noise.
    var caveat = '';
    if (entry.note && available) {
      caveat = '<div class="dl-note">' + entry.note +
        (meta.sha256
          ? '<span class="dl-sum">sha256 ' + meta.sha256 + '</span>'
          : '') +
        '</div>';
    }

    return '' +
      '<article class="dl">' +
        '<div class="dl-top">' +
          '<span class="dl-ico" aria-hidden="true">' + entry.icon + '</span>' +
          '<div><h3>' + entry.name + '</h3>' +
          '<div class="plat">' + entry.platform + '</div></div>' +
          '<div style="margin-left:auto">' + badge + '</div>' +
        '</div>' +
        '<p>' + note + '</p>' +
        caveat +
        '<div class="dl-foot">' +
          (href
            ? '<a class="dl-btn' + ghost + '" href="' + href + '"' +
              (entry.file && available ? ' download' : ' rel="noopener"') + '>' + label + '</a>'
            : '') +
          (available && meta.size
            ? '<span class="dl-size">' + humanSize(meta.size) + '</span>'
            : '') +
        '</div>' +
      '</article>';
  }

  var grid = $('#downloads');
  if (grid) {
    // checksums.json is written when the image is built, by hashing
    // whatever was copied in. Hard-coding a digest here would be a digest
    // of whichever file happened to be present the day it was written,
    // which is worse than none: it would keep matching in the reader's
    // eye long after it stopped matching the file.
    var sums = fetch('downloads/checksums.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });

    // Ask the server whether each file is actually there, with HEAD so a
    // 44 MB apk is not pulled down just to render a card.
    var heads = Promise.all(CATALOG.map(function (entry) {
      if (!entry.file) return Promise.resolve(null);
      return fetch(entry.file, { method: 'HEAD' })
        .then(function (response) {
          return {
            ok: response.ok,
            size: parseInt(response.headers.get('content-length') || '0', 10)
          };
        })
        .catch(function () { return { ok: false, size: 0 }; });
    }));

    Promise.all([heads, sums]).then(function (both) {
      var results = both[0];
      var digests = both[1] || {};
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

  /* ---------- Where this page is being served from ---------- */
  var served = $('#served');
  if (served) served.textContent = 'served from ' + location.host;
})();
