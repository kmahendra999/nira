# Nira — Analysis & Roadmap

Rebranding and extending the OpenJarvis fork at `/home/ubuntu/nira` into **Nira**: a local-first
personal AI that runs on your own machines, talks back fast, drives real work on your projects,
and is controllable from your phone over Tailscale.

Written 2026-09-20. Every claim below was verified against the working tree or by running it.

---

## 1. What we're starting from

Better than expected. This is a mature codebase, not a prototype.

| Area | Size | State |
|---|---|---|
| Python (`src/openjarvis/`) | 948 files, 57 modules | Well-factored, registry-driven |
| Tests (`tests/`) | 715 files, **8,709 tests** | **8,641 pass, 6 fail, 68 skip** |
| Rust (`rust/crates/`) | 17 crates, 146 files | Builds clean via maturin |
| Frontend (`frontend/`) | React 19 + Vite 8 + Tauri 2 | Builds clean; ~19% dead code |
| Lint | ruff | **Clean** — 0 issues, 1,387 files formatted |

**Verified locally during this analysis:**
- `uv sync --extra dev --extra server --extra framework-comparison` → OK
- `maturin develop` (Rust extension) → OK
- `pytest tests/ -n auto` → 6 failures, all diagnosed (§5)
- `npm install && npm run build` → OK (with one workaround, §5.14)
- `jarvis serve` → `/health` OK, PWA served at `/`, `/v1/info` OK

### The fork point is pristine and current

Upstream is `github.com/open-jarvis/OpenJarvis`. Comparing the whole tree against a fresh checkout
of `origin/main` (`b03203f`): **zero differences**. Nira is a byte-identical copy of current
upstream `main`, with no local modifications to preserve.

(The stale clone at `~/OpenJarvis` is 26 commits *behind* — Nira is the current one, not that.)

That means we already have upstream's most recent security batch, which is worth knowing because
it's all code that a network-exposed Nira would be running:

| Commit | Fix |
|---|---|
| `b75eca2` | SSRF — normalize disguised IPv4, fail closed on unresolvable host (#1001) |
| `43e43a4` | `code_interpreter` — AST validation replacing a bypassable substring blocklist (#1002) |
| `980f44e` | Taint propagation across `ToolExecutor`, fencing untrusted tool output (#1003) |
| `6c1f1c2` | Workflow — replace condition `eval()` with an allowlist AST interpreter (#1004) |
| `308512e` | Server — configurable CORS origins, refuse credentialed wildcard (#1005) |

Also already present: `40cba53` "stop TTS falsy defaults overriding backend defaults" (#983), which
touches the voice work in Phase 3.

The flip side: **upstream is actively maintained and actively shipping security fixes.** That is the
strongest argument for keeping upstream patches applicable, and it shapes §2.2.

### The environment already has everything the plan needs

This matters a lot for sequencing — nothing here has to be procured.

**Your tailnet is already live** (`tailscale status`, MagicDNS enabled, tailnet `tail0ab740.ts.net`):

| Node | OS | Address |
|---|---|---|
| `diubuntu` | Linux | `100.123.66.19` — this machine |
| `gipserver` | Linux | `100.112.38.24` |
| `diwindows` | Windows | `100.106.110.124` |
| `asus` | Windows | `100.121.211.90` |
| `mahendra-kumars-a56` | **Android** | `100.104.227.67` |
| `quadzero-5` | Windows | `100.96.164.90` — **owned by `shashintatacomm@`, not you** |

That last row is the single most important security fact in this document. **The tailnet is not
exclusively yours**, so "reachable over Tailscale" can never mean "trusted". Per-device
authentication is mandatory, not optional. See §6.2.

**Toolchain present:** Android SDK (API 36, build-tools 36.0.0, platform-tools, emulator),
JDK 17, adb, Node 24, Cargo 1.96, Tailscale 1.102.4, Claude Code CLI.

---

## 2. Two decisions worth making before we touch anything

### 2.1 There is no git repository — fix this first

`/home/ubuntu/nira` is **not a git repo**. The rename in §3 rewrites ~12,000 strings across
1,743 files. Doing that without version control is not recoverable if it goes wrong.

Because the tree is byte-identical to upstream `b03203f`, we can do better than a synthetic
"initial commit" — we can adopt upstream's **full history** as our own, so every future
`git cherry-pick`, `git blame` and `git log` works against real ancestry:

```bash
cd /home/ubuntu/nira && git init && git remote add upstream https://github.com/open-jarvis/OpenJarvis.git && git fetch upstream && git reset --mixed b03203f
```

After that, `git status` should show only untracked build artifacts (`.venv/`, `node_modules/`,
`src/*/server/static/`, caches) — all already covered by the existing `.gitignore` — plus this
file. Nothing tracked should be modified. If anything else shows as changed, stop and investigate
before renaming.

Then branch, so `main` continues to track upstream cleanly:

```bash
cd /home/ubuntu/nira && git switch -c nira
```

### 2.2 How deep should the rename go?

The user-visible rebrand is cheap. Renaming the *Python package* is what costs you upstream merges.

| Option | Churn | Upstream merges | Result |
|---|---|---|---|
| **A. Brand only** — CLI `nira`, `~/.nira`, `NIRA_*`, product name, app identity; Python package stays `openjarvis` | ~2,000 strings | Stay easy | Ships as Nira, internals say openjarvis |
| **B. Full rename** — everything, including `src/nira/` and the 17 Rust crates | ~12,000 strings | Need the shim below | A genuinely separate product |

**Recommendation: B, full rename — but only because the mergeability cost is avoidable.**

The naive objection to B is that it ends upstream merges, and given that upstream just shipped five
security fixes to SSRF, taint propagation, the code interpreter and workflow `eval()`, losing that
stream would be a real cost for something we're about to expose on a network.

But the rename is a *deterministic* substitution, which means it is invertible enough to rewrite
patches as well as files. Keep the substitution table as a committed, versioned artifact
(`scripts/rename_map.sed`) rather than throwing it away after the rename, and forward-porting an
upstream fix becomes:

```bash
git -C /home/ubuntu/nira format-patch --stdout b03203f..upstream/main | sed -f scripts/rename_map.sed | git am -3
```

Paths and identifiers in the patch get rewritten the same way the tree did, so hunks land where
they belong. It won't be flawless on files we've substantially rewritten — but those are exactly
the files where we'd want to review an upstream security change by hand anyway.

That reduces the decision to "do you want Nira to be a real product or a skin," and you've
described a product: Android, a Tailscale device mesh, a voice runtime, and a project registry —
none of which upstream will ever carry. Doing the rename now, while the tree is byte-identical to
upstream, is the cheapest it will ever be.

If you'd rather not take that bet, say so and I'll do A instead — same script, smaller table.

---

## 3. The rename

### Scope, measured

| Token | Occurrences | Files |
|---|---|---|
| `jarvis` | 12,087 | 1,743 |
| `openjarvis` | 10,009 | 1,535 |
| `Jarvis` | 2,455 | 466 |
| `OpenJarvis` | 1,452 | 341 |
| `JARVIS` / `OPENJARVIS` | 1,000 | 255 |
| `open-jarvis` | 187 | 65 |

Plus 45 paths with the name embedded (`src/openjarvis/`, 17 `rust/crates/openjarvis-*`,
4 asset files, 3 service files, `configs/openjarvis/`, `examples/openjarvis/`).

### The mapping

| From | To | Notes |
|---|---|---|
| `openjarvis` (package) | `nira` | `src/openjarvis/` → `src/nira/` |
| `OpenJarvis` | `Nira` | |
| `jarvis` (CLI) | `nira` | `[project.scripts]` in `pyproject.toml:204` |
| `openjarvis-eval` | `nira-eval` | |
| `OPENJARVIS_*` (~90 vars) | `NIRA_*` | |
| `~/.openjarvis` | `~/.nira` | **needs a migration shim** |
| `openjarvis-*` (17 crates) | `nira-*` | `openjarvis_rust` → `nira_rust` |
| `com.openjarvis.desktop` | `com.nira.desktop` | Tauri identifier |
| `openjarvis://` | `nira://` | deep-link scheme (currently dead, §5.10) |
| `openjarvis.auth.v1` | `nira.auth.v1` | **WS subprotocol — server + client must change together** |
| `openjarvis-conversations` etc. | `nira-*` | **localStorage keys — needs a shim or users lose history** |
| `oj_sk_<token>` | `nira_sk_<token>` | API key prefix |

### Method

Mechanical and verifiable, not hand-edited:

1. Commit the baseline (§2.1).
2. Longest-token-first substitution (`OPENJARVIS` → `OpenJarvis` → `openjarvis` → `open-jarvis` →
   `JARVIS` → `Jarvis` → `jarvis`) so short tokens don't corrupt long ones. Skip `uv.lock`,
   `package-lock.json`, `Cargo.lock`, `node_modules/`, `.venv/`, binary assets. **Commit the
   substitution table as `scripts/rename_map.sed`** — per §2.2 it's what keeps upstream security
   patches applicable, so it's infrastructure, not a throwaway.
3. `git mv` the 45 named paths.
4. Regenerate lockfiles.
5. `ruff check && ruff format --check` → must stay clean.
6. `pytest tests/ -n auto` → must return to **6 failures, not 7**. The 8,709-test suite is our
   proof the rename didn't break anything, which is exactly why it runs before the bug fixes.
7. `maturin develop` + `npm run build` → must both still pass.

### Three things the naive rename gets wrong

- **`~/.openjarvis` already exists on this machine** with real data (config, 7 SQLite DBs:
  sessions, agents, memory, traces, telemetry, audit, optimize). `core/paths.py` centralizes this
  well (one `_DEFAULT_DIR_NAME` constant at `paths.py:35`), so add a **one-time migration**: if
  `~/.nira` is absent and `~/.openjarvis` exists, move it and leave a marker. Without this, the
  rebrand silently orphans every conversation, memory and trace.
- **localStorage keys** (`frontend/src/lib/store.ts:37-43`) hold conversations and settings. Same
  problem, browser-side. Needs a read-old-write-new shim on first load.
- **`_find_source_root()`** at `core/paths.py:58` greps `pyproject.toml` for the literal
  `name = "openjarvis"`. If the substitution misses the case-folded comparison there, the
  source-tree isolation guard silently stops working.

**Estimate: 1–2 days**, most of it verification rather than editing.

---

## 4. Where the real work is

The four subsystem analyses converged on one theme: **the infrastructure you need mostly exists and
is good; it's the last mile that's missing.** Concretely —

- Voice has every backend it needs but runs them **strictly serially** with a fixed 1.5 s silence tax.
- Claude Code integration works but **throws away the SDK's stream** at the subprocess boundary,
  even though a live-progress UI is already built and waiting for exactly those events.
- The server has ~90 endpoints, SSE, an authenticated WebSocket, and **a working PWA** — but one
  shared password and no concept of "which device" or "which machine".
- The frontend has an excellent design-token layer (1,523 `var(--color-*)` call sites — a rebrand
  is nearly a one-file edit) buried under 1,238 inline `style={{}}` objects that make interaction
  design impossible.

---

## 5. Bugs found

Ordered by severity. Items 1–3 I reproduced directly; the rest are code-read findings.

1. **`shell_exec` reports failures as successes.** `tools/shell_exec.py:150-164` — the Rust fast
   path (tried *first*) hardcodes `"returncode": 0` and `success=True` regardless of the real exit
   status, so **a failed command is reported to the model as having worked**. The same path also
   silently drops the sanitized environment and the 300 s timeout cap that the subprocess path
   below it carefully builds. Worst bug in the repo.
2. **RAPL energy sampling crashes on any hardened Linux.** `evals/backends/external/_subprocess_runner.py:278`
   — `rapl_path.exists()` passes but the file is `-r--------` root-only (a standard mitigation since
   CVE-2020-8694). The `PermissionError` escapes `_start_sampler()` and takes down the whole
   external-backend runner instead of falling through to the null sampler. **Causes 5 of our 6 test
   failures.** Fix: catch `OSError` in the sampler and make `_start_sampler`'s fallback chain
   defensive.
3. **Order-dependent test.** `tests/tools/test_weather.py::test_tool_executor_applies_external_boundary_guard`
   passes alone, in its file, and across `tests/tools/ -n 4` — but fails in the full suite. Global
   state leaking from another module. Our 6th failure.
4. **Claude SDK multi-block replies are truncated.** `agents/claude_code_runner/index.mjs:80` —
   `content = block.text` overwrites instead of appending, so only the *last* text block of a
   multi-block assistant message survives.
5. **Docs tell you to bind to the world.** `docs/deployment/api-server.md:35,460,469` documents
   `server.host` defaulting to `0.0.0.0`; the code and its test say `127.0.0.1`
   (`core/config.py:1166`, `tests/security/test_network_defaults.py:13-17`). Anyone copying the
   sample TOML exposes their agent — which has shell and file tools — on every interface.
6. **`nira gateway start --install` installs a no-op.** `daemon/service.py:13,33` generates units
   whose `ExecStart` is `python -m openjarvis.daemon.gateway`, but that package has no `__main__`
   and `gateway.py` has no `if __name__` block, so the service starts, imports, exits 0, and looks
   healthy. `GatewayDaemon.start()` itself only flips a boolean (`daemon/gateway.py:33-39`).
7. **`A2AClient` can't talk to an authenticated A2A server.** `a2a/client.py` sends no
   `Authorization` header although `a2a/server.py:49` supports tokens.
8. **A2A wire-state mismatch.** Python uses `submitted/working/canceled`
   (`a2a/protocol.py:12`); the Rust crate uses `Pending/Active/Cancelled`. Incompatible.
9. **`config.speech.language` is dead config.** Declared at `core/config.py:1620`, read nowhere, so
   Whisper runs a language-detection pass on every single utterance.
10. **Tauri deep-link is configured but not installed.** `tauri.conf.json` declares the
    `openjarvis://` scheme, but `tauri-plugin-deep-link` is in neither `Cargo.toml` nor
    `Cargo.lock`, and `frontend/src/lib/deep-link.ts` (61 lines) has zero consumers.
11. **Mic recording indicator doesn't animate.** `Chat/MicButton.tsx:50` references a `pulse`
    keyframe that `index.css` never defines.
12. **Dashboard clock is frozen.** `pages/DashboardPage.tsx:6-7` computes a timestamp at render and
    never updates it, under a "live telemetry" header.
13. **All telemetry is mislabeled.** `lib/analytics.ts:51-52` hardcodes `APP_VERSION = '0.1.0'`
    with a TODO; `package.json` says `1.0.1`.
14. **The frontend can't be installed on this machine as-configured, and the obvious workaround
    silently corrupts the lockfile.** `package.json` requires `npm >=11.19.0 <12` with
    `engine-strict=true`; installed npm here is 11.3.0. CI handles it by globally installing
    npm 11.19.0 (`.github/workflows/frontend.yml:36`).

    `npm install --engine-strict=false` does install and build — but I verified that installing
    with npm 11.3.0 **rewrites `package-lock.json` and strips the `libc: ["glibc"]` / `["musl"]`
    constraints** from optional dependency entries (80 diff lines). Committing that lockfile would
    break installs on musl/Alpine and cross-platform CI. So the engine pin is load-bearing, not
    bureaucratic. **Use the CI approach — install npm 11.19.0 — and never `--engine-strict=false`
    on a tree you intend to commit.** (I hit this during analysis and restored the file; the tree is
    clean.) Separately, `.npmrc` sets `strict-allow-scripts`, which current npm doesn't recognize
    and warns about on every invocation.
15. **The default TTS engine isn't in the extra the docs recommend.** `tts_backend` defaults to
    `kokoro` (`core/config.py:1628`), but the `speech` extra doesn't install Kokoro — and
    `_voice_chat.py:143-146` tells failing users to install exactly that extra.
16. **~4,700 lines of dead frontend code (≈19% of `src/`).** `components/Desktop/*` (3,358 lines,
    excluded from tsconfig so it isn't even type-checked), the orphaned `components/setup/*` wizard
    (1,258 lines), 5 unused shadcn primitives, and a second parallel API client. Several duplicate
    live components *by name* (`Desktop/EnergyDashboard` vs `Dashboard/EnergyDashboard`) — actively
    dangerous during a redesign, because you'll restyle the wrong file.

---

## 6. Architecture: the multi-device mesh

### 6.1 Topology

Every desktop (Windows / Ubuntu / Mac) runs the **same** `nira serve` daemon. There is no central
server and no cloud. Phones are thin clients. Each desktop owns its own data — which is what keeps
the local-first promise intact.

```
   Android phone(s)                    Tailnet (WireGuard)                  Desktops
  ┌────────────────┐                                                 ┌──────────────────────┐
  │  Nira Android  │                                                 │ nira serve           │
  │  · voice in    │◄───── wss:// device-scoped key ────────────────►│ · agents + tools     │
  │  · live steps  │                                                 │ · SQLite (local)     │
  │  · approvals   │                                                 │ · Claude Agent SDK   │
  └────────────────┘                                                 └──────────────────────┘
       paired with N desktops                              each desktop paired with N phones
```

Bind to the **Tailscale interface** (`100.x`), never `0.0.0.0`. That gives WireGuard encryption and
keeps the daemon off coffee-shop Wi-Fi even when the laptop is roaming. MagicDNS gives stable names
(`diubuntu.tail0ab740.ts.net`) so no IP bookkeeping.

Note this cuts *against* the existing `nira tunnel` command (`cli/tunnel_cmd.py`), which exposes
`localhost:8000` via a public Cloudflare URL. Tailscale is strictly better for this use case and
should become the documented default. Related: `cli/scan_cmd.py:43` currently flags `tailscaled` as
a *remote-access risk* in the security audit — that heuristic needs to learn the difference between
Tailscale-as-attack-surface and Tailscale-as-Nira-transport.

### 6.2 Authentication — the part that must not be skipped

Today: **one static bearer token per machine** (`server/auth_middleware.py:30`), no rotation, no
expiry, no scopes, no per-caller identity. One phone's leaked key is full control of that desktop —
and that desktop's agent has shell, file, and browser tools.

That is survivable on loopback. It is not survivable on a tailnet you share with another account.

**What to build:**
- A `devices` table: `device_id`, name, platform, public key, scopes, `created_at`, `last_seen`,
  `revoked_at`. Today no table anywhere has a `device_id` column.
- **Per-device keys**, issued by a QR pairing flow: desktop shows a QR containing
  `{host, port, short-lived enrollment token}`; phone scans, exchanges it for its own long-lived
  key. Never type or share the machine key.
- **Revocation** per device, and `last_seen` so you can see what's paired.
- **Scopes**, so a phone can be allowed to *ask* and *watch* but not to approve destructive tools.
- Per-device attribution in the existing audit log.
- `tailscale serve` for real `*.ts.net` TLS, so `wss://` works properly rather than plaintext-inside-WireGuard.

### 6.3 Event replay — the mobile-specific gap

`server/ws_bridge.py:59-60` drops events for slow clients and the stream is **live-only**: no
sequence numbers, no `Last-Event-ID`, no replay. On a desktop that's invisible. On a phone that
changes cell towers mid-task, **every reconnect loses progress**.

Add a monotonic event cursor plus a replay-since endpoint. This is small and it is the difference
between the phone experience feeling solid or broken.

### 6.4 What we reuse

The server analysis was emphatic here: an Android client needs **no new server API** to talk to one
desktop. Already working today —

- `POST /v1/managed-agents/{id}/run` → returns immediately, work continues in background
- `WS /v1/agents/events?agent_id=` → live step-by-step events, authenticated
- `POST /v1/speech/transcribe` → multipart audio in, text out
- `/v1/approvals/*` → human-in-the-loop approvals, a natural phone surface
- SSE turn persistence survives client disconnect (`agent_manager_routes.py:1628`) — exactly the
  property flaky mobile connections need
- `frontend/src/lib/useAgentEvents.ts` is a working reference client to port to Kotlin

And there's a reviewed cross-device design already in the tree: `examples/cross_device_travel/` is a
Rust prototype (explicitly not networked) that defines `Capability`, `Device`, `TaskRequest`,
`ErrorCode`, a `DeviceTransport` trait, and retry semantics where reads retry twice and writes never
auto-retry. **Don't redesign this — implement `DeviceTransport` over Tailscale and port the model
into Python.**

---

## 7. Phase plan

Ordering is deliberate: rename first (while the tree is closest to upstream), then correctness, then
the two changes with the biggest felt impact, then the mesh, then UI, then native mobile.

### Phase 0 — Safety net · half a day
Adopt upstream history per §2.1 (`git init` + `fetch upstream` + `reset --mixed b03203f`), branch to
`nira`. Install npm 11.19.0 the way CI does — **not** `--engine-strict=false` (§5.14). Record the
8,709-test baseline as the regression gate for Phase 1.

### Phase 1 — Rename to Nira · 1–2 days
Per §3, including the `~/.openjarvis` → `~/.nira` migration and the localStorage shim.
**Exit:** lint clean, still exactly 6 test failures, Rust + frontend both build.

### Phase 2 — Bug fixes · 2–3 days
§5 items 1–6 and 14–15 (the correctness and safety ones). Leave the cosmetic frontend bugs
(11–13) for Phase 6 where we're in those files anyway.
**Exit:** 0 test failures.

### Phase 3 — Voice that feels conversational · ~1 week
Today's loop is strictly serial with a hard 1.5 s silence tax, so sub-second response is
*structurally* impossible before any model even runs:

```
record → [1.5s silence wait] → whisper (full) → LLM (full completion) → TTS (full) → play (blocking)
```

In priority order:
1. **Pipeline LLM → TTS.** `cli/chat_cmd.py:482` calls synchronous `engine.generate()`, but *every*
   engine already implements `async stream()` (`engine/_stubs.py:77`). Stream it, cut on sentence
   boundaries, speak each clause as it lands. Biggest single win — turns "wait for the whole answer"
   into "first audio after one clause".
2. **Add streaming to the two ABCs.** `TTSBackend.synthesize()` (`speech/tts.py:33`) and
   `SpeechBackend.transcribe()` (`speech/_stubs.py:36`) are both blob-in/blob-out, so today no
   backend *can* stream. Kokoro is one line away — `speech/kokoro_tts.py:197-211` already iterates a
   generator and concatenates the chunks it could have been yielding.
3. **Cut the silence tax.** `speech/voice_io.py:12` — 1.5 s → ~400 ms, paired with real VAD.
4. **Real VAD.** `voice_io.py:11,69-78` is a fixed absolute RMS threshold of 500 with no noise-floor
   calibration: latches on in a noisy room, never triggers on a quiet mic. faster-whisper already
   ships Silero and it's switched off.
5. **Tune Whisper for latency.** `speech/faster_whisper.py:119-123` forwards only `language`, so it
   inherits `beam_size=5`, `best_of=5`, a 6-step temperature ladder and `condition_on_previous_text=True`.
   For conversation: beam 1, temperature 0, no previous-text conditioning, `vad_filter=True`.
6. **Stop round-tripping audio through a temp file** (`faster_whisper.py:114-123`) — pass the numpy
   array directly. Also deletes the Windows file-handle workaround.
7. **Barge-in.** `voice_io.py:122-123` is `sd.play(); sd.wait()` — blocking, mic closed, no
   interrupt hook. You can't even Ctrl-C out of a long answer. Needs callback-mode `OutputStream`
   with the input stream held open.
8. **Strip markdown before speaking** (`chat_cmd.py:499` speaks raw markdown; the regexes already
   exist at `agents/morning_digest.py:193-196`), **skip empty recordings** (today 5 s of silence
   gets sent to Whisper, inviting "Thanks for watching!" hallucinations), **warm models at session
   start**, and **plumb `config.speech.language`**.

Also worth deciding here: there is no `nira talk` command at all — voice is only a `--voice` flag on
`chat`. A dedicated always-on voice mode deserves its own entry point.

### Phase 4 — Live task progress on any project · ~1 week

**This is the "watch it work" feature, and it's ~80% built already.** The EventBus → authenticated
WebSocket → live trace UI chain is real and working (`frontend/src/pages/AgentsPage.tsx:1662-1735`
renders an incremental tool timeline with latencies today). One thing blocks it:

**`subprocess.run(capture_output=True)` at `agents/claude_code.py:192`.** The Node sidecar iterates
the Agent SDK's message stream at `index.mjs:71` — then accumulates everything into locals and emits
one JSON blob at exit. During a 300-second run you see nothing, then everything.

1. **Make the sidecar stream.** Emit one JSON line per SDK message; switch Python to `Popen` with
   line-wise reads; republish each as `TOOL_CALL_START` / `TOOL_CALL_END` / `INFERENCE_END` on the
   EventBus. **The existing WebSocket and live-trace UI then light up with zero UI changes.**
2. **Pass `workspace` through.** `agents/executor.py:492-545` builds `agent_kwargs` from a fixed
   allowlist that doesn't include `workspace`, so a managed `claude_code` agent silently runs in the
   *server's* cwd. Without this, "work on project X" cannot be expressed at all.
3. **Real session resumption.** `index.mjs:62` sets `options.sessionId`, which assigns an id rather
   than resuming; the SDK's actual parameter is `resume`. The real session id is never read off the
   `result` message either, so every follow-up is a cold start.
4. **A project registry** — id, name, path, default agent, last session id. Nothing like it exists;
   `workspace` is an ad-hoc string on individual agent constructors.
5. **Decide the permission posture.** The runner sets no `permissionMode` and no `canUseTool`
   callback, so an unconstrained 30-turn agent runs on the host once `code:execute` is granted.
   Wire it to the existing `ApprovalStore` + `/v1/approvals/*` routes so **you can approve a risky
   step from your phone** — the tier model and endpoints already exist.
6. **Raise the ceilings** — `maxTurns: 30` is hardcoded (`index.mjs:51`) and the subprocess timeout
   is 300 s. Both are low for autonomous project work.
7. Add `SCHEDULER_TASK_*` to `ws_bridge.py:19-31` so scheduled runs appear in the feed, and stop the
   scheduler executing tasks inline in its poll loop (`scheduler/scheduler.py:198-200`), where one
   20-minute task blocks every other task.

**On "Claude Desktop" specifically** — worth being precise, because your note is ambiguous and the
two readings are different features:

- *Nira drives Claude on your projects.* This is the work above. It uses the **Claude Agent SDK
  headless**, not the Claude Desktop GUI. There is no GUI automation in this repo (no pyautogui, no
  xdotool, no screenshots) and I don't recommend adding any — driving a GUI is fragile where the SDK
  is a supported API. **This is the one I'd build.**
- *Claude Desktop calls into Nira.* `mcp/server.py:43` is a complete MCP server — `initialize`,
  `tools/list`, `tools/call`, auto-discovery, destructive-hint annotations — that **is never
  served**. There's no stdio loop and no `nira mcp serve` command; it's used only as an in-process
  tool registry. Adding a stdio entrypoint is roughly 50 lines (the framing already exists in
  `mcp/transport.py`) and would let Claude Desktop use Nira's tools and memory directly. Cheap, and
  genuinely useful — I'd do it as a small side quest in this phase.

### Phase 5 — Multi-device foundation · 1–2 weeks
Device registry, QR pairing, per-device keys, scopes, revocation (§6.2). Tailscale-interface binding
plus `tailscale serve` TLS. Event cursor and replay (§6.3). HTTP-layer rate limiting — today's
limiter gates *tool calls*, not requests. Mount the existing `AgentCard` at
`/.well-known/agent.json` (the code is written at `a2a/server.py:156`, just never mounted) as
capability advertisement. Port the `cross_device_travel` capability/routing/retry model into Python
with a durable task store.
**Exit:** phone paired to two desktops, routing a task to a chosen one, surviving a network drop.

### Phase 6 — Phone v1 (PWA) + UI overhaul · 2–3 weeks

**Start with the PWA, because it already works.** `frontend/vite.config.ts:19-37` configures
VitePWA; `npm run build` emits a service worker and manifest straight into
`src/nira/server/static/`; the FastAPI server serves it. I verified this end-to-end today. Over
Tailscale, `https://diubuntu.tail0ab740.ts.net/` installs to your Android home screen **with zero
new client code** — which validates the entire transport, auth, voice and progress story before you
write a line of Kotlin.

UI work, in this order (the first item is not optional — skip it and you will restyle dead files):

1. **Delete the ~4,700 lines of dead code** (§5.16).
2. **Kill the inline-style pattern.** 1,238 `style={{}}` objects is the core blocker: no
   `:hover`/`:focus-visible`/`:active` without JS, so the codebase is full of `onMouseEnter`
   handlers mutating `e.currentTarget.style` — which breaks keyboard focus and touch entirely.
   Migrate to Tailwind v4 `@theme` tokens so `bg-surface` / `text-secondary` become real utilities
   with working variants. **Everything under "more interactive" depends on this.**
3. **Resolve the two competing token systems.** `index.css` has both the Nira `--color-*` tokens and
   an inert shadcn `oklch()` set, namespaced apart to avoid collision. Keep the former, delete
   lines 608–710. Also collapse the **triplicated** dark palette (`:root`, `.dark`, and a near-verbatim
   copy inside the `prefers-color-scheme` media query) — today a recolor must be made twice or
   system-theme users keep the old brand.
4. **Rebrand visuals.** The entire identity is an Iron Man arc reactor, which is meaningless once
   the name isn't Jarvis — this is a mark redesign, not a recolor. One 1024×1024 master regenerates
   all 11 icon files via `tauri icon`. Then recolor two CSS blocks, and sync `index.html:5`,
   the PWA `theme_color`, and the hljs palette (which currently disagree with each other *and* with
   both `--color-bg` values).
5. **Actually ship a typeface.** `--font-display` (Chakra Petch) and `--font-hud` (IBM Plex Mono)
   are declared, referenced nowhere, and never loaded; `@fontsource-variable/geist` is a dependency
   with zero imports. The app renders in the plain system stack. One import is a large, free visual
   upgrade.
6. **Replace polling with the WebSocket you already have.** Five independent timers today
   (`SystemPanel` every 3 s, plus four more at 5–30 s), several fetching overlapping data, none
   using the event stream that's already built and tested. **This is the single biggest enabler of
   "live-feeling" UI.**
7. **Elevate the agent-step timeline.** Tool calls, phases, latencies and research traces are all
   already streaming in — and render as small collapsed monospace rows. This is the most
   differentiating content in the product and deserves the most design attention.
8. **Split `AgentsPage.tsx` (4,007 lines) and `DataSourcesPage.tsx` (2,385 lines)** into per-tab modules.
9. **Accessibility pass** — focus-visible tokens, ARIA live regions for streaming, real tablist
   semantics on all three tabbed screens, non-color status encoding, and a contrast fix for
   `--color-text-tertiary` (~3.6:1 on `--color-bg`, below AA).
10. Sweep `types/connectors.ts` — 17 setup strings tell users to name their Gmail app password,
    Slack app and Azure registration "OpenJarvis".

### Phase 7 — Native Android app · 3–4 weeks

Kotlin + Jetpack Compose (SDK 36 is installed and ready). OkHttp handles both transports — and
Android is actually *simpler* than the browser here, since it can send the auth header directly
rather than smuggling the key through a WebSocket subprotocol.

What the native app buys over the PWA:
- Background voice capture and a wake word (a PWA cannot do either)
- Foreground service so a task keeps streaming with the screen off
- Push notifications when a long task finishes or needs approval (no FCM/webpush exists today)
- Assistant-button / quick-tile integration — hold the home button, talk to Nira
- Multi-desktop picker with liveness, and offline queueing

Ship it against the same API the PWA validated. Voice v1 = record on phone, transcribe on desktop
via `/v1/speech/transcribe`, which keeps audio processing on hardware you own.

---

## 8. Summary of effort

| Phase | Work | Estimate |
|---|---|---|
| 0 | Safety net | 0.5 day |
| 1 | Rename to Nira | 1–2 days |
| 2 | Bug fixes | 2–3 days |
| 3 | Voice latency | ~1 week |
| 4 | Live task progress + Claude SDK streaming | ~1 week |
| 5 | Multi-device foundation | 1–2 weeks |
| 6 | PWA phone + UI overhaul | 2–3 weeks |
| 7 | Native Android app | 3–4 weeks |

Roughly **9–13 weeks** end to end, but usable milestones land early: a fully rebranded Nira with a
green test suite in week 1, noticeably faster voice in week 2, live project progress in week 3, and
something real on your phone by week 5.

---

## 9. Decisions

1. **Rename depth** — ✅ **Full rename (B)**, confirmed 2026-09-20. `main` continues to track
   upstream so security fixes stay cherry-pickable through the patch-rewriting shim in §2.2.
2. **Claude reading** — ✅ Nira drives the **Claude Agent SDK headless** on your projects (§7
   Phase 4), with the MCP stdio server as a bonus so Claude Desktop can also call into Nira. No
   GUI automation.
3. **Brand direction** — ✅ **Orange accent theme**, confirmed 2026-09-20. Applied in Phase 6.

### 9.1 Orange theme — where it lands

The accent is a genuine one-file change (1,523 `var(--color-*)` call sites), but it must be made in
**both** the light and dark blocks of `frontend/src/index.css`, and the triplicated dark palette
(§7 Phase 6, item 3) has to be collapsed first or the `prefers-color-scheme` copy keeps the old cyan.

Current accent is cyan — `#0891b2` light (`index.css:26`) / `#22d3ee` dark (`index.css:85`).
Proposed orange, chosen for contrast parity rather than by eye:

| Token | Light | Dark |
|---|---|---|
| `--color-accent` | `#ea580c` (orange-600) | `#fb923c` (orange-400) |
| `--color-accent-hover` | `#c2410c` (orange-700) | `#fdba74` (orange-300) |
| `--color-accent-subtle` | `rgba(234, 88, 12, 0.08)` | `rgba(251, 146, 60, 0.10)` |
| `--color-accent-glow` | `rgba(234, 88, 12, 0.25)` | `rgba(251, 146, 60, 0.30)` |
| `--color-user-bubble` | `#ea580c` | `rgba(251, 146, 60, 0.14)` |

Two knock-on effects to handle in the same pass:

- **`--color-accent-amber` (`#f59e0b`) now collides with the primary accent.** Amber is currently
  the "warning/attention" accent; with an orange primary it stops reading as distinct. Either retire
  it in favour of `--color-warning`, or push it toward yellow (`#eab308`).
- **`--color-error` (`#dc2626` light / `#ff6b6b` dark) sits close to orange.** Error states must
  stay unmistakable, so error should shift red-ward (`#b91c1c` / `#f87171`) once the accent is warm.

Also sync, or the app ships three disagreeing brand colours: `index.html:5` `theme-color`, the PWA
`theme_color` in `vite.config.ts`, and the hljs syntax palette at `index.css:231-280`.

A warm accent also suits the mark redesign — the arc reactor was a cold blue glow, which is exactly
the thing that has to go.

---

## 10. Progress

- ✅ **Phase 0 — Safety net.** Repo initialized on upstream's real 1,144-commit history
  (`b03203f`), verified byte-identical, `main` tracks upstream, work branch `nira` created.
- ✅ **Phase 1 — Rename to Nira.** `29bda98` — 1,808 files, 38 paths, all four lock files.
  Package `openjarvis` → `nira`, CLI `jarvis` → `nira`, 17 Rust crates, `OPENJARVIS_*` → `NIRA_*`,
  `~/.openjarvis` → `~/.nira`, `com.openjarvis.desktop` → `com.nira.desktop`.
  Verified: lint clean, **8,650 passing** with only the pre-existing failures, Rust extension and
  frontend both build, `nira serve` boots and serves the PWA.
- ✅ **Orange accent theme.** `ed08d1d` — applied ahead of Phase 6 since the rebrand is inherently
  visual. All three token blocks, plus the amber/warning/error knock-ons and the three
  previously-disagreeing brand colours.

### Carried forward from Phase 1

Three things surfaced during execution that change later phases:

1. **The legacy home migration copies rather than moves** (`40dd011`). The original design moved
   `~/.openjarvis` wholesale. Inspecting the real install showed the root also holds a **2 GB
   virtualenv** and a 528 MB source checkout — and a `hey_jarvis.py` process had been running out
   of that virtualenv for 13 hours. A virtualenv bakes its absolute path into `pyvenv.cfg` and
   every shebang, so the move would have destroyed a working install to relocate a few hundred KB
   of state. It now copies state only, excluding `.venv`, `src`, `.scripts`, `.state`, `cache`, and
   stale `server.pid/lock/log`, leaving OpenJarvis runnable side by side.
2. **Your data has not been migrated yet** — deliberately, because that `hey_jarvis.py` process is
   still live. It happens automatically and safely on your first `nira` command.
3. **`nira-ai/nira` is a placeholder org** in every upstream URL. Replace with:
   `git grep -l nira-ai | xargs sed -i 's|nira-ai|YOURORG|g'`

### Phase 2 — Bug fixes ✅

**The suite is green for the first time: 8,701 passing, 0 failing**, across three consecutive
parallel runs. Rust workspace tests pass, frontend 77/77, lint clean.

| § | Bug | Commit |
|---|---|---|
| 1 | `shell_exec` reported failed commands as successes, leaked the parent environment, ignored its timeout | `d269636` |
| 2 | RAPL `PermissionError` aborted every external eval on hardened Linux (5 of 6 failures) | `b97d554` |
| 4 | Claude sidecar kept only the last text block of a reply | `f3f7f55` |
| 5 | Docs told users to bind an agent with shell tools to `0.0.0.0` | `38764da` |
| 6 | `nira gateway start --install` installed a unit that exited immediately | `8491be2` |
| 7, 8 | A2A client sent no bearer token; Rust/Python disagreed on every task state | `46f23cf` |
| 9 | `speech.language` was declared and read nowhere | `dc11534` |
| 10 | `nira://` links were registered with the OS and then dropped | `adf565c` |
| 12, 13 | Frozen "live" dashboard clock; telemetry tagged `0.1.0` since forever | `4537235` |
| 14, 15 | npm toolchain trap documented; `Nira[voice]` now installs a loop that can hear *and* speak | `35fdf78`, `6d9d702` |

Three findings worth carrying forward:

- **§3 (the order-dependent test) no longer reproduces.** It failed in roughly two of three
  parallel runs before Phase 2 and has now passed 17 consecutive parallel runs plus a full serial
  run. I could not pin the mechanism, so I am not claiming a specific fix — note that the two tests
  originally implicated were both network-boundary tests (SSRF/DNS), which points at environmental
  sensitivity rather than code. Worth re-checking rather than assuming it is gone for good.
- **§11 was not a real bug.** `MicButton`'s `pulse` animation was reported as referencing an
  undefined keyframe; Tailwind v4 supplies `@keyframes pulse` and it is present in the built CSS.
  Verified rather than "fixed".
- **§16 (≈4,700 lines of dead frontend code) stays in Phase 6.** It is a restructuring task, and
  Phase 6 item 1 already sequences it before any visual work.

Two gaps were deliberately left open rather than faked, both noted in the code:

- A `nira://research/<id>` link now reaches the app but cannot render the report, because
  `/api/research` is a streaming POST with no endpoint to fetch a stored session. Delivery is
  wired; the retrieval endpoint is a later phase.
- `GatewayDaemon` now stays up and shuts down cleanly under a service manager, but still composes
  little. It is honest infrastructure, not a finished gateway.

### Next

**Phase 3 — Voice latency.** The pipelining work in §7: stream the LLM into TTS sentence by
sentence, add streaming to the two ABCs, cut the 1.5 s silence tax, and replace the fixed-threshold
RMS gate with real VAD.
