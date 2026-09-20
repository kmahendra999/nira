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
3. **`kmahendra999/nira` is a placeholder org** in every upstream URL. Replace with:
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

### Phase 3 — Voice latency ✅

**8,797 passing, 0 failing.** Measured on a 45-word reply at 30 tok/s with modelled synthesis
cost: **time to first audio 1.89 s → 0.23 s (8.3× faster)**. Adding the capture window that
precedes it, a turn's fixed overhead goes from ~3.39 s to ~0.63 s.

| § | Change | Commit |
|---|---|---|
| — | Sentence segmentation + speech-ready text prep | `6532c79` |
| 1, 2 | Stream the LLM into TTS; `synthesize_stream` on the ABC, Kokoro overrides | `1411fbe` |
| 3, 4, 7, 11 | Calibrated VAD, 1.5 s → 0.4 s window, vectorised RMS, stoppable playback | `e64b4c2` |
| 5, 6, 13 | Conversational Whisper decode, in-memory audio, warm start | `0aea08d` |
| 7 | Barge-in detector, and a `nira talk` entry point | `139880b` |

Where the time went, and what replaced it:

- **The reply is spoken while it generates.** Each engine already implemented `async stream()`;
  chat_cmd called the synchronous `generate()` and discarded it. The producer runs on its own
  thread so generation of sentence N+1 overlaps playback of sentence N — consuming the stream
  inline would re-serialise them and give back the entire win.
- **The 1.5 s silence tax is gone.** On its own it exceeded a conversational budget, before any
  model ran.
- **The gate is now relative to the room.** A fixed RMS threshold of 500 meant a noisy room
  recorded the full 30 s ceiling and a quiet microphone never triggered at all.
- **Whisper decodes for conversation, not for transcription.** beam 5 with a six-step temperature
  ladder is right for a recording and wrong for a turn someone is waiting on.
- **Silence is no longer transcribed.** The startup timeout used to hand five seconds of room tone
  to Whisper, spending a full decode to produce one of its stock hallucinations.

Two things worth carrying forward:

- **Streaming STT was not implemented** (the second half of §2). Partial transcripts would need a
  backend that streams — Deepgram's live websocket API, or chunked re-decoding with faster-whisper,
  which costs CPU for a modest gain now that the gate closes in 0.4 s and decoding is much cheaper.
  Deferred deliberately rather than half-built.
- **Barge-in ships off by default** (`[speech] barge_in`). There is no acoustic echo cancellation,
  so on open speakers the microphone hears the reply and Nira interrupts itself. With headphones it
  works well. Real AEC would make it safe to default on.

Writing the segmentation tests caught two bugs in my own first version, both premature cuts — the
one failure mode that matters, since audio cannot be taken back once it is playing. Noted in
`6532c79`.

### Phase 4 — Live task progress ✅

**8,854 passing, 0 failing.** Verified end to end against a stubbed SDK: register a project,
resolve "work on payments" to it, run an agent in that directory, and watch tool events arrive at
+0.11s, +0.19s, +0.27s and +0.35s of a 0.43s run — during the work, not after it.

| § | Change | Commit |
|---|---|---|
| 1, 2, 3, 6, 7 | Streaming sidecar, real session resumption, `workspace` through the executor, scheduler events on the socket | `e9bfdff` |
| 4 | Project registry (`nira project`) | `b109aec` |
| — | MCP stdio server (`nira mcp serve`) | `94af54f` |
| 5, 7 | `max_turns`/`permission_mode` plumbed; scheduler no longer serialises tasks | `7609a36` |

The theme repeated from Phase 2: the capability was already built and one thing in the middle
made it unreachable.

- **Live progress needed no new UI.** The sidecar got a message per SDK event, the EventBus fed an
  authenticated WebSocket, and `AgentsPage` rendered a tool timeline from it. The blocker was
  `subprocess.run(capture_output=True)`, which buffers until exit — five minutes of silence, then
  everything at once.
- **`sessionId` is not `resume`.** The former assigns an id to a *new* session. Every follow-up was
  a cold start that had forgotten the conversation it was part of, and the SDK's real id was never
  read back, so a caller could not resume a session it had not invented an id for itself.
- **MCP was half-built in the other direction too.** `MCPServer` was complete and never served —
  no transport, no entry point. `nira mcp serve` now exposes 43 tools over stdio, so Claude Desktop
  can call into Nira.
- **Making the scheduler concurrent exposed a latent bug.** `next_run` only advances when a task
  finishes, so the poll loop re-selects a still-running task. Inline that could never fire; with a
  pool it would restart the same task every 60 seconds.

Carried forward:

- **Permission posture is now settable but not yet wired to approvals.** `permissionMode` reaches
  the SDK; connecting `canUseTool` to the existing `ApprovalStore` and `/v1/approvals/*` — so a
  risky step can be approved from a phone — belongs with the mobile work in Phase 5.
- **A research deep link still cannot render its report** (carried from Phase 2). The project
  registry is the natural place to hang that retrieval once the endpoint exists.

### Phase 5 — Multi-device foundation ✅

**8,949 passing, 0 failing**, five consecutive parallel runs. Verified live against a running
server: no key 401, machine key 200, paired device key 200, after revoke 401, machine key still
200 — revocation is per device, which is the whole point.

| § | Change | Commit |
|---|---|---|
| 6.2 | Device registry, QR pairing, per-device keys, scopes, revocation | `1e2c128` |
| 6.3 | Event cursor and replay for reconnecting clients | `bef2681` |
| 6.1 | `nira serve --tailscale`; device store wired into the server | `7170cca` |
| 5 | Per-caller HTTP rate limiting | `780c403` |

The security posture this phase exists to establish:

- **Per-device keys, stored hashed.** A leaked database hands over nothing usable, and revoking a
  phone does not cut off everything else. Plain SHA-256 rather than a password KDF is deliberate:
  these are 256 bits of CSPRNG output, so there is no dictionary to run.
- **A revoked device authenticates as nothing**, not as itself with no scopes, so every caller
  fails closed instead of each one having to remember to check.
- **New devices get ask+watch.** Approving a tool call is opt-in — pairing a phone must not
  silently hand it the ability to say yes to anything.
- **A tailnet bind still requires a key.** Reaching the port proves nothing about who is knocking
  when the tailnet is shared with another account, so network reach is never treated as a
  credential.

**The long-standing test flake is finally diagnosed**, having twice been reported as unexplained
rather than fixed. `ToolExecutor` submits to a process-wide pool with a deliberately fixed worker
count, and a timed-out tool keeps running — the timeout frees the caller, not the thread. The
timeout tests run tools that sleep five to eight seconds after timing out at one, starving
unrelated tests that landed in the same xdist worker. Fixed by isolating that module's pool, not
by changing the runner: widening it was tried and `test_repeated_timeouts_use_bounded_workers`
correctly rejected it, because the fixed ceiling is a documented tradeoff and growing it only
moves the cliff.

Deferred to the client work, where they can actually be exercised end to end:

- **`tailscale serve` TLS** for real `wss://`. Over WireGuard the hop is already encrypted, so
  this is about certificate-validating clients rather than confidentiality.
- **Multi-desktop routing.** `examples/cross_device_travel/` already defines a reviewed
  capability/device/retry model; porting it into Python is only worth doing against a real second
  client, which is Phase 7.
- **Wiring `canUseTool` to `ApprovalStore`** so a risky step can be approved from a phone
  (carried from Phase 4 — it needs the phone).

### Phase 6 — UI foundation ✅ (overhaul partially done)

**8,957 passing, 0 failing.** Frontend: 81 tests, clean build from an empty cache.

| Item | Change | Commit |
|---|---|---|
| 1, 3, 5 | Deleted 6,401 unreachable lines; removed the second colour system; shipped the typeface | `a4565d0` |
| 6 | Replay cursor wired into the client; activity bar driven by events | `66af9ae` |
| — | Pairing prefers https, and explains why http will not install | `deb6f9f` |

A reachability analysis from `main.tsx` found **21 files, 6,401 lines — 27% of `src/`** that
nothing could reach. Deleted before any visual work, because several shadowed live components by
name (`Desktop/EnergyDashboard` against `Dashboard/EnergyDashboard`) and restyling the wrong file
was only a matter of time.

Three things that turned out to be more than cleanup:

- **The duplicated dark palette was load-bearing.** Removing the `prefers-color-scheme` copy would
  have broken system theming outright, because `system` added no class at all and leaned entirely
  on that media query. The theme is now resolved in JS for all three modes, with a `matchMedia`
  listener so `system` still follows the OS live.
- **A committed `tsconfig.tsbuildinfo` was hiding a type error.** Sharing tsc's incremental state
  between checkouts silently skips re-checking files; a real error in a test added in Phase 2
  surfaced only when these deletions invalidated the cache. Untracked and fixed.
- **`tailscale serve` is a prerequisite for the phone, not a refinement.** Phase 5 recorded it as
  being about certificate-validating clients. It is not: a plain-http MagicDNS origin is an
  insecure context, service workers cannot register there, and the PWA therefore cannot install or
  work offline however reachable the port is. Pairing now prefers the https origin and prints the
  one command that provides it. I did not enable serve here — it publishes a port to a tailnet
  shared with another account, which is a deliberate choice to make, not one to switch on quietly.

### Still open in Phase 6

The large refactors, deliberately not rushed:

- **The inline-style pattern** (item 2) — 1,238 `style={{}}` objects, and the `onMouseEnter`
  handlers they force, which break keyboard focus and touch. This is the prerequisite for any real
  interaction polish and deserves its own focused pass.
- **Splitting `AgentsPage.tsx` (4,007 lines) and `DataSourcesPage.tsx` (2,385)** (item 8).
- **The accessibility pass** (item 9) — focus-visible tokens, ARIA live regions for streaming,
  real tablist semantics, and the `--color-text-tertiary` contrast fix.
- **The logo** (item 4) — colour is settled, the arc-reactor mark still needs replacing. One
  1024×1024 master regenerates all 11 icon files.

Item 10 needed nothing: the rename already corrected all 16 connector setup strings.

### Phase 7 — Android client ✅

**Python: 9,044 passing.** **Android: 91 passing, 5 skipped without a server (all 5 pass
against one).** 27 Kotlin files building a 44 MB debug APK.

The twelve remaining Python failures are all `*Live` classes needing things this machine does
not have — gemma.cpp weights, Oura/Strava/Spotify/Google Tasks tokens — and fail identically on
a clean worktree at `0ef7ff1f`.

| Piece | What it does |
|---|---|
| `net/NiraClient.kt` | Enrol, info, streamed `ask`, `transcribe`, speech health, events socket |
| `net/Sse.kt` | Turns one SSE line into text, end-of-stream, or nothing |
| `data/` | Desktop registry, QR/manual pairing parser, Keystore-backed secrets, WAV framing, mic capture |
| `ui/` | Pairing (camera + manual), desktop picker with liveness, conversation with voice |

The conversation screen is the product: type or hold the microphone, watch what the desktop is
doing on a live bar above the transcript, and read the answer as it streams.

**"Work on this project" now goes somewhere.** `nira project add` has registered directories
since Phase 4 and `ClaudeCodeAgent` has taken a `workspace` since it existed, but nothing joined
them over HTTP — the registry was reachable only from a shell on the machine itself, so the phone
could chat and could watch agents work without ever being able to start any. `server/project_routes.py`
adds the join: list projects, start a run in one, read how it turned out. A row of chips above the
composer picks where the next prompt goes — `Chat`, or one of the desktop's projects — because
that choice changes what the prompt *does*, and sending an agent into a directory with file and
shell access is not something to bury in a menu. It is never the default.

The run is started, not awaited: agentic work takes minutes and a phone's radio does not survive
a request held open that long, so the response carries a run id and progress arrives on the event
socket the client is already watching. Two things the caller does *not* get to choose: the
permission mode, which would let a device holding only `ask` grant itself the right to skip every
approval the desktop would have raised, and the resource ceilings, which are clamped so nobody can
pin a Node subprocess open for a day.

That permission mode comes from config — and until now there was no config to come from. Phase 4
added the parameter to `ClaudeCodeAgent` precisely because "the posture for an agent with file and
shell access was whatever the SDK happened to default to rather than something Nira chose", and
then nothing ever set it. `agent.permission_mode` now exists, so the choice is finally the user's.

**Voice goes to your own machine.** Android's recogniser would ship the user's speech to Google,
which is the one thing a local-first assistant exists to avoid. The phone records 16 kHz mono PCM,
wraps it in a WAV container and posts it to the paired desktop's `/v1/speech/transcribe`, where
the local Whisper model handles it. The microphone button only appears once `/v1/speech/health`
confirms that desktop can actually transcribe — a mic that fails after you have finished speaking
is worse than one that was never offered.

Two bugs the live run found that no mock would have:

- **A device key could not open the events WebSocket.** `authenticate_websocket` only ever knew
  the machine key, so a paired phone could send a prompt and then be refused the socket reporting
  progress on it — the live progress the pairing exists to deliver was the one thing a device key
  could not reach. It now resolves device keys too, and checks the scope while it is there.
- **Scopes were issued but enforced nothing.** `DEFAULT_SCOPES = (ask, watch)` had been handed out
  since devices existed and attached to every request, with a comment saying downstream handlers
  read it. Nothing did. A phone paired to ask questions could rewrite config and revoke other
  devices. `server/device_scopes.py` now classifies every path, default-deny: anything
  unclassified needs `admin`, so a route added later locks down rather than opening up. The
  machine key is untouched — it carries no device identity and never reaches the check.

Two more in the app's own wiring, both of the same shape — state that outlives the screen showing
it. Tapping a desktop in the picker navigated to the conversation without changing the selection,
so tapping one machine opened a conversation with another; selecting and opening are now a single
action. And the picker's view model survives a trip to the pairing screen, so a desktop you had
just paired was missing from the list you were sent back to; both screens now re-read on resume.

Verified against a real `nira serve`, not only MockWebServer: enrolment issues a working key, that
key authenticates, an unauthenticated call is refused, an answer streams back from the real model,
and an `ask`-only device is refused `/v1/config`, `/v1/devices` and the events socket while
keeping `/v1/chat/completions`. A project run was driven the whole way through with a device key:
`POST /v1/projects/demo/run` returned a run id in milliseconds, the Claude Code agent ran in that
project's directory, and sixty seconds later `/v1/projects/runs/<id>` reported `done` with the
agent's answer and two turns. That is the requirement — a command given away from the machine,
work started on it, progress and outcome visible — end to end against real software. `/v1/devices/me` needs authentication but no scope — a client
decides which controls to show from exactly that answer, so gating it would leave a
narrowly-paired phone unable to discover that it is narrowly paired.

### Still open in Phase 7

Everything the native app buys *over* a PWA is still ahead: background voice capture and a wake
word, a foreground service so a task keeps streaming with the screen off, push notifications when
a long task finishes or needs approval, assistant-button integration, and offline queueing. The
app is also unsigned and has never run on hardware — it builds and its logic is tested on the JVM,
which is not the same as installed.

A project run's *outcome* is polled rather than pushed. The events say what the agent is doing,
not what it concluded, so the phone asks `/v1/projects/runs/<id>` on a backoff until the run
settles. That is deliberate — a device without the `watch` scope has no socket at all and must
still be able to learn how the work it started turned out — but a terminal event carrying the
result would be better, and would also let the run history survive being read by a second device.

### Phase 8 — Interaction and accessibility ✅

**Python: 9,065 passing. Frontend: 102 passing.** Phase 6 item 2 (the blocker), and item 9 (the
accessibility pass) that depended on it.

**The tokens now reach the markup.** There was no `@theme` block, so `bg-surface` and
`text-text-secondary` were not classes — there was no way to write a colour in markup at all. That
is why the codebase had 975 `style={{}}` objects and 68 handlers assigning to
`e.currentTarget.style`. `@theme inline` maps all 43 tokens to utilities; `inline` is what makes it
work, emitting `background-color: var(--color-surface)` rather than today's value, so a utility
keeps following `.dark` exactly as the raw token does.

**All 68 JavaScript hover handlers are gone**, replaced by `hover:` / `focus-visible:` / `active:`.
Each one had three failure modes invisible to whoever wrote it: a keyboard user got no state at
all, a touch user got one that stuck after the tap because nothing fires `mouseleave`, and the
handler silently beat any stylesheet rule for the same property. Tailwind wraps `hover:` in
`@media (hover: hover)`, so it simply does not apply on a touchscreen.

| Was | Now |
|---|---|
| 68 `currentTarget.style` assignments | 0 |
| `:focus-visible` rules in the whole app | a global ring, plus 4 scoped rules |
| Muted text contrast | 2.43:1 light, 2.98:1 dark → **4.55:1 and 4.52:1** |
| Tab strips with `role="tablist"` | 0 → 2, with arrow keys and roving tabindex |
| Live region for streaming replies | none → one, announcing state not tokens |

**There was no focus styling anywhere** — not one `:focus-visible` rule — so tabbing through the
app moved an invisible cursor. Adding a global ring was not enough on its own: 25 form fields
carried `outline-none`, and a Tailwind utility sits in a later layer than `@layer base`, so each
one silently reinstated the problem on exactly the controls where it matters most. Twenty of them
lost the class; the five transparent fields inside styled boxes kept it and their containers gained
`focus-within`.

**Contrast needed both levels moved.** `--color-text-tertiary` carries timestamps, hints and field
descriptions and sat at 2.43:1 against the 4.5:1 WCAG AA asks for. Secondary was itself only just
over the line at 4.59:1, so a compliant tertiary would have been the same colour and the hierarchy
would have collapsed. The new values are the dimmest that clear 4.5:1 on every surface each one
lands on. The test computes the ratios rather than pinning hex values, so a later recolour cannot
quietly drop back under.

**Streaming now says something.** Marking the transcript itself as a live region would be worse
than the silence — every token interrupts and restarts the announcement, and the listener hears a
stutter rather than a sentence. The announcer reports state instead: thinking, each tool as it
runs, replying, complete. Its own test caught a real bug: when React batches the streaming flag and
the first token into one render, the original reducer never noticed the content and announced a
real answer as "finished without a reply".

**Keyboard reachability.** Twelve clickable `<div>`s took no focus, ignored Enter and were
announced as nothing. The agent card and five disclosure rows took the ARIA pattern; the audio
seek bar became a real `role="slider"` with arrow keys, because there is no keyboard equivalent of
"click 40% of the way along"; `OptInModal` and the mobile sidebar gained Escape, having been
dismissable only by mouse.

Nine guards in `tests/deployment/test_frontend_theme.py` keep all of it from coming back. They live
in pytest rather than vitest because these are facts about files: vitest stubs CSS imports to the
empty string, and reading the file with `node:fs` needs Node types this browser tsconfig lacks —
adding them means an npm install, which is what silently rewrote `package-lock.json` once already.
Writing that guard also caught a bug in itself: a naive `[^<>]*` attribute match stops at the `>`
of `=>`, so it skipped every element carrying a handler — exactly the ones it existed to find.

Verified in the running app, not only in tests: Escape closes the dialog, the ring is
`2px solid rgb(251, 146, 60)` on a Settings control that previously suppressed it, the composer's
border lights on `focus-within`, hover works on the nav rows, and two ArrowRight presses walk the
Data Sources tabs with focus following selection and the right panel showing.

### Still open

947 `style={{}}` objects remain. Most are legitimate — a computed width, a conditional colour — and
the ones that are not are concentrated in the two files that need splitting anyway. The point of
this phase was the interaction states, which is a different problem from where a static colour is
written.

- **Splitting `AgentsPage.tsx` (4,007 lines) and `DataSourcesPage.tsx` (2,385)** (Phase 6 item 8).
  The six disclosure rows given `role="button"` should become real `<button>` elements in that
  pass; restructuring JSX inside files that size is a job for the split, not for this one.
- **The logo** (Phase 6 item 4) — colour is settled, the arc-reactor mark still needs replacing.

### Phase 9 — Approve from your phone ✅

**Python: 9,105 passing. Android: 100. Frontend: 102.**

The approval queue, its REST endpoints, its permission memory and the `approve` scope on a paired
device had all existed for phases with nothing to put in them. The Claude Agent SDK was given no
`canUseTool`, so an "ask" decision was terminal: a risky step was refused outright and nobody was
ever offered the chance to say yes. This is the piece in between.

| Piece | What it does |
|---|---|
| `claude_code_runner/index.mjs` | Asks over the pipe and waits; stdin now carries a conversation |
| `agents/tool_approval.py` | Queues the question, waits for an answer, sends it back |
| `ApprovalsViewModel` / `ApprovalsScreen` | The phone's queue: what it wants to do, allow or refuse |
| `ApprovalBell` | Now driven by events rather than a ten-second poll |

**Two bugs found by building it, both severe.**

The first: `readline` holds Node's event loop open, so keeping stdin open past the initial request
meant the sidecar never exited, its stdout never reached end-of-file, and the host waited forever
for output from a process that had finished. That is a deadlock in *every* run, not only the ones
that ask a question. A test caught it by hanging.

The second is the same pattern this project keeps producing: `canUseTool` was correctly wired to
something that never fires. The SDK only prompts in `permissionMode: "default"`, and Nira's config
default is empty, so the callback sat there unreachable. The runner now selects that mode whenever
asking is enabled — a permission prompt nobody can reach is exactly the state this phase set out to
fix.

**Everything that is not a yes is a no.** A timeout denies, a missing queue denies, a store that
will not open denies, a host that stops listening denies, an answer to a question this process
never asked is ignored. The failure mode of the opposite choice is running a destructive command
because SQLite was busy. Waiting happens on its own thread, so progress events keep flowing while
the question is outstanding — a person deciding whether to allow something needs to see what the
agent did to get there.

Permission memory means a remembered decision answers instantly without interrupting anyone. The
key is deliberately coarse — tool plus the first word of a command — because keying on the exact
arguments means "always allow" never matches twice and the memory is decorative, while keying on
the tool alone lets one approval of `Bash("ls")` authorise every future shell command. Tools that
change the world are filed as `high`, which never auto-remembers: one yes to writing a file must
not silently authorise every future write.

Verified end to end against a real `nira serve`, which is the only way to know the SDK actually
routes a call through the callback. A project run asked to write outside its workspace parked at
`status: running`; `/v1/approvals/pending` showed the exact command; an HTTP approve — byte for
byte what the phone sends — let it through, and the file on disk said `approved`. The same run
denied left no file at all. A device holding `ask` and `watch` but not `approve` got 403.

`echo` inside the workspace is *not* prompted, and that is correct: the SDK prompts for dangerous
operations, and a direct probe confirmed the callback fires for a write outside the working tree
and not for a harmless command in it.

### Still open in Phase 9

- **Nothing pushes.** The phone learns about a waiting question only while the app is open and its
  socket is connected. A run that asks while the phone is asleep waits out its timeout and denies.
  Push notifications are listed under Phase 7's remaining work and this is now their strongest
  reason to exist.
- **"Always allow" cannot be chosen from a client.** The store supports it and the bridge honours
  it, but neither the phone nor the bell offers the button, so the memory can only be populated by
  the proactive agent's own path.

### Phase 10 — More than one machine ✅

**Python: 9,125 passing. Android: 114. Frontend: 102.** This closes the last unfinished item from
the original brief: *"we should be able to add more than one desktop/system (windows/ubuntu/mac)
and android app in more than one mobile."*

`examples/cross_device_travel/` was listed as the thing to port. It is not: it is a deterministic,
in-memory Rust design study that says so itself — "before building real infrastructure". The parts
worth having were already here, in the wrong shape.

**Projects belong to machines, and the phone now knows it.** A project is a directory, and a
directory exists on exactly one computer. The phone asked only the *selected* desktop what it had,
so with three machines paired, finding work meant switching desktop, looking, switching back. Worse,
a run went to whichever desktop was selected — which either fails, or finds a same-named directory
and edits the wrong tree. `ProjectIndex` asks every paired desktop at once, labels each project
with the machine it lives on, and routes a run to that machine regardless of what is selected. One
shut laptop no longer empties the list: it is reported as unreachable, because "no projects there"
and "that machine is asleep" are different facts and only one means look elsewhere.

**Two bugs found by testing the platform half.**

`shutil.which("tailscale")` is not enough on macOS. The App Store and standalone builds ship the
CLI inside the .app bundle and never touch PATH, so a Mac happily on a tailnet looked exactly like
one without Tailscale installed — and the consequence was not an error but a silent fall back to a
LAN address that stops working the moment the laptop moves, which is the whole failure the tailnet
module exists to prevent. The binary is now looked for where each platform's installer puts it, and
the *found path* is invoked rather than the bare name.

The SPA catch-all matched every unclaimed GET, including `/v1/*`. A missing, misspelled or
not-yet-written endpoint returned 200 and a kilobyte of `index.html`. A browser shrugs; the phone
parses it as JSON and reports a syntax error, sending whoever is debugging to the client instead of
to the absent route. It also hides endpoints that were never written — which is exactly how the
missing device listing went unnoticed for four phases. API paths now 404.

**Devices can be seen and removed from somewhere other than the machine.** `GET /v1/devices` and
`DELETE /v1/devices/{id}`, both admin. The moment this matters most is the moment you are not at
the desktop: a phone has been lost, and the revoking has to happen from whatever device you still
have. Until now the only way was a shell on the machine itself.

Verified with two genuinely independent desktops — separate `NIRA_HOME`, separate API keys,
separate ports, a different project on each, one phone paired with both. The phone saw one list
across both machines correctly labelled; a run for the project on the second desktop was routed
there; that desktop's approval queue held the question while the first desktop's stayed empty;
approving on the owning machine let it through, and the file appeared with the right contents.
That is Phases 7, 9 and 10 working as one thing.

### Still open in Phase 10

- **The web UI cannot aggregate.** It is served by one desktop and authenticates to it, so it is
  structurally single-machine. The phone is the only client holding keys for several. A desktop
  reaching another desktop directly would need a second pairing direction, which nothing needs yet.
- **A run cannot be moved between machines.** Routing picks the owner; it does not migrate work, and
  nothing tries to pick a machine by load or capability. That was the design study's subject and it
  remains unbuilt, deliberately — there is no evidence yet that anyone needs it.

### Phase 11 — Notifications, without a cloud ✅

**Python: 9,125 passing. Android: 131. Frontend: 102.**

Phase 9 let a person approve a risky step from their phone, and then left the feature half-useless:
the phone only heard the question while the app was open. An approval blocks a run *and expires*,
so "you were not looking at your phone" quietly became "no".

**Deliberately not Firebase.** A push would mean the desktop reaching Google's servers to reach a
phone sitting on the same tailnet, and the content of every question — the commands an agent wants
to run on your machine — travelling through a third party. In an assistant whose entire premise is
that your data stays on hardware you own, that is the wrong trade. The socket is already there;
`WatchService` keeps it open in a foreground service and raises local notifications.

| Piece | What it does |
|---|---|
| `watch/Alerts.kt` | Decides what is worth interrupting someone for. Pure, so it is tested |
| `watch/WatchService.kt` | Holds the socket to *every* paired desktop while the app is away |
| `watch/ApprovalActionReceiver.kt` | Allow and Refuse straight from the notification |
| `watch/BootReceiver.kt` | Starts watching again after a restart |

**Only two things are worth interrupting for**: something is blocked on you, and something you
started has finished. Tool calls, tokens and phase changes stream past continuously while a run
works, and a notification for each would be a torrent of noise about something the user chose to
start. A notification that fires twice, or fires for something nobody can act on, teaches people to
swipe the next one away without reading it — which is worse than not notifying at all, because the
one that matters then looks the same as the rest. Reconnecting replays what was missed, so the same
approval arrives again on every network change; it is alerted once.

**Answerable from the lock screen.** Allow and Refuse are notification actions, because an approval
expires and the number of steps between seeing it and answering it decides whether the answer
arrives in time. A decision made anywhere — the desktop, another phone — takes the notification
down, which needed a server fix: `APPROVAL_DECIDED` carried the sidecar's request id but not the
queue row's, so no client could match a decision to the question it was showing. Verified on a live
socket: the requested and decided events now carry the same `id`.

**Three notification channels**, because they are three different interruptions. One channel would
mean turning off the chatty "your agent finished" notification also turns off the one that blocks a
run — and people do turn the chatty one off.

Opt-in, and the switch says why: it costs a persistent connection, a permanent notification and
battery. That is a reasonable trade for someone running long agent tasks and an imposition on
someone who is not.

### Still open in Phase 11

- **Doze is still doze.** A foreground service makes an approval far more likely to reach someone;
  it does not make it certain. Android may defer the radio, and an aggressive OEM battery manager
  may kill the service outright. The timeout still denies, which is the safe direction, but "the
  phone was asleep" has been made much less likely rather than impossible.
- **Never run on hardware.** The service, the notification actions and the boot receiver are
  verified as far as a JVM and the built APK's manifest allow — the decisions are tested, and
  `aapt2` confirms the service, both receivers and all four permissions are registered. None of it
  has been exercised on a real phone.

### Phase 12 — The link that led nowhere ✅

**Python: 9,171 passing. Frontend: 102. Android: 131.**

`channel_agent` has been answering long queries over Telegram, Slack and iMessage with a preview
and `nira://research/<id>` since it existed. The scheme is registered with the OS, the desktop app
parses the URL and knows what to do with it — and the report was never written down. The full text
went out of scope in the same breath as the preview was cut from it, and the id was a fresh uuid
that referred to nothing.

So it was not merely a feature that had not been finished. The link **promised a reader something
that had already been thrown away**, which is a different and worse thing: a missing feature is a
disappointment, a broken promise is a bug report.

`nira/research/store.py` keeps the report under the id the reply is about to quote — before
sending it, because writing it afterwards under a different id would recreate the same dangling
link. `GET /api/research/{id}` reads it back, and `ResearchPage` renders it. When there is nowhere
to store it, no link is promised: the whole answer is sent instead, which is worse than a preview
and far better than a promise that will not open.

**Two more broken things found on the way.**

`/v1/sessions` imported `nira.sessions.store`, which does not exist — `SessionStore` lives in
`nira.sessions.session` — and then called `recent()` and `get()`, which it does not have. A blanket
`except Exception` turned all of that into `{"sessions": [], "error": ...}`, so the endpoint
reported *no sessions* rather than reporting that it was broken, and did so for as long as nobody
read the error field. Live, it returned `{"sessions":[],"error":"No module named
'nira.sessions.store'"}` and its sibling 500'd. Fixed, with `SessionStore.get()` written to match.

Every Markdown list in the app rendered without markers. Tailwind's preflight resets
`list-style: none` on `ul` and `ol`, and `.prose` set padding without ever putting the markers
back. Numbered steps lost their numbers, which is worse than losing bullets — "1. 2. 3." carries
meaning that indentation alone does not. This has affected every chat reply the assistant has ever
given; the research page simply made it visible.

Previews strip Markdown rather than showing it. A report opens with a heading and is full of
emphasis, so the raw text read `# Title Running a model **trades** …` — syntax crowding out words
in exactly the place with least room for them.

Verified in the running app: a stored report opens at its own URL with headings, emphasis and
bulleted lists rendered; the listing shows prose previews; and an id that no longer exists explains
that reports are pruned and offers the list, rather than looking like a broken link.

### Still open in Phase 12

- **Only `channel_agent` writes reports.** A deep research run started from the web UI streams to
  the browser and is not kept, so it has no link and does not appear in the list. The store is
  general enough; nothing else calls it yet.
- **No search.** Two hundred reports is a scroll, not a corpus, but it will not stay that way.

### Phase 13 — Auditing for the pattern, not guessing ✅

**Python: 9,196 passing.**

Every significant find in this project has come from one shape: something built, and nothing
reaching it. Rather than guess at the next item, I swept for that shape directly.

**The swallowed-error sweep came back clean.** Every parameterless GET endpoint was probed against
a running server looking for the `/v1/sessions` pattern — a 200 whose body quietly confesses a
failure. Forty answered correctly; the two flagged were `/v1/devices` on a server started without
an API key, which is right and says so. That is a good result and worth recording as a negative.

**The config sweep found a real one.** Of 349 config fields, five in the security sections were
read by nothing. Four turned out to be harmless — always-on protections whose knobs are decorative.
One was not.

**Skill signature verification was unreachable.** `load_skill` has known how to verify a manifest
signature since signing existed. It could not be asked to: `load_skill_directory` and
`discover_skills` — the only functions the skill manager calls — took no key, and
`security.signing_key_path` was read by nothing. A skill could carry a `signature` and nobody ever
looked at it. Skills arrive from a remote index and define the steps an agent executes, which is
exactly the case signing exists for. The key is now read from config and threaded through all three
discovery layouts.

**And the check could be switched off by its own subject.** The gate was
`if verify_signature and public_key and manifest.signature` — so deleting the signature line
skipped verification entirely. An unsigned skill is now refused when a key is configured, with a
message saying both ways out. Verification stays off without a key: there is nothing to check
against, and refusing every skill because the user never opted in would break a working install to
enforce a policy nobody chose.

**A correction to my own framing.** I began this phase expecting to find that the config lies to
users about security. It mostly does not. `enforce_tool_confirmation` is already documented in two
places as *"accepted but not currently enforced"* — the project was honest about it before I
arrived. `ssrf_protection` and `merkle_audit` were undocumented rather than misdescribed, and both
describe protections that are genuinely unconditional. What I actually found was one inert setting
and one bypass, not a pattern of false assurance.

`ssrf_protection` no longer appears in the generated config, because offering a security switch
nobody reads is worse than offering none — the first thing a reader does with one is trust it. All
three are now documented in `security.md` as accepted and not read, with what *does* enforce them.
A test pins this: it fails if a dead switch reappears in the generated config, and I verified it
fails by putting one back.

My own test also caught my own mistake: the first "tampered skill" test passed because its
`[[steps]]` block used a key the loader ignores, so both versions signed byte-for-byte identical
bytes and proved nothing.

### Still open in Phase 13

- **Signing needs the `security-signing` extra.** `cryptography` is optional, so the 13 signature
  tests skip where it is absent. They ran here because I installed it.
- **Nothing signs skills yet.** Verification works; there is no `nira skill sign` to produce a
  signature, so today the feature is for someone distributing skills with their own tooling.
- **`sandbox_dangerous` is still inert.** The dangerous-capability warning it describes does happen,
  but gated on a CLI flag rather than the setting. Documented behaviour and actual behaviour agree;
  the setting is simply not the thing controlling it.

### Phase 14 — Signing, not only verifying ✅

**Python: 9,219 passing.**

Phase 13 made skill signature verification reachable and shipped no way to produce a signature for
it to check. That left the feature usable only by someone who already had Ed25519 tooling of their
own — which is not finishing something, it is describing it.

`nira skill keygen` writes a key pair; `nira skill sign <skill>` signs a manifest in place.

**The manifest is edited surgically rather than re-serialised.** A `skill.toml` is written by hand:
it has comments, ordering and formatting its author chose, and a round-trip through a TOML writer
would discard all of that to change one line. The signature is placed inside the `[skill]` table
and replaces any already there — a signature written after the first `[[skill.steps]]` would not
be read at all, so it would look like it had worked and do nothing.

Signing covers the manifest *without* its signature, so signing twice produces the same result
rather than signing the previous signature, and editing a skill invalidates it, which is the point.

Two details that matter more than they look. The private key is written `0600` before anything else
can read it and is never printed — it signs skills an agent executes, and default permissions on a
shared machine leave it readable by every other account. And `keygen` refuses to overwrite an
existing pair without `--force`, because every skill signed with the old key stops verifying and
there is no way back to it.

Driven end to end on a real skill: keygen, sign, verify, then tamper with the step the agent would
run — the tampered skill is refused and logged, the signed one loads, and an install without a key
is unaffected.

**Two output bugs found by looking at it.** Rich read `[security]` in the "add this to your config"
snippet as markup and printed nothing, leaving a config block with no table header for the user to
copy. Fixing that with `no_wrap` then truncated a long path instead of wrapping it; `soft_wrap` is
the one that lets the terminal fold the line while emitting the string intact.

### Still open in Phase 14

- **One skill at a time.** There is no `nira skill sign --all`, which is what someone maintaining a
  skill index would actually want.
- **Signing still needs the `security-signing` extra.** Without `cryptography` both commands exit
  with instructions, and the 23 tests skip.
- **Nothing verifies at install time.** `nira skill install` does not check a signature before
  writing a skill to disk; verification happens when skills are loaded.

### Next

The two Phase 6 refactors still outstanding: splitting `AgentsPage.tsx` (4,007 lines) and
`DataSourcesPage.tsx` (2,385), which is also where the six disclosure rows given `role="button"`
should become real `<button>` elements. Then the logo mark — a redesign rather than a recolour, and
the one item here that wants a designer more than an engineer.
