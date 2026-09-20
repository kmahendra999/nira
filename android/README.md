# Nira for Android

Talk to your own machines from your phone. The app holds no data of its own
beyond the keys it was issued: prompts, voice and work all go to a desktop you
have paired with, over your tailnet.

## Build

```bash
./gradlew :app:assembleDebug
```

The APK lands in `app/build/outputs/apk/debug/`. `local.properties` must point
at an Android SDK; everything else the build needs it downloads.

## Test

```bash
./gradlew :app:testDebugUnitTest
```

All tests run on the JVM — no emulator, no device. That is deliberate: the
parts worth testing are the wire format, the pairing parser, the conversation
logic and the WAV framing, and none of them need Android to be real. The
microphone is behind a `Microphone` interface for exactly this reason.

### Against a real server

`LiveServerContractTest` runs against an actual `nira serve` instead of a mock.
MockWebServer proves the client does what its tests say; it cannot prove the
tests describe the server, and that gap is where a client and its backend drift
apart. It skips unless you point it at one:

```bash
NIRA_TEST_URL=http://127.0.0.1:8791 \
NIRA_TEST_DEVICE_KEY=nira_dk_... \
./gradlew :app:testDebugUnitTest --tests '*LiveServerContractTest' --rerun-tasks
```

Set `NIRA_TEST_ENROLL_TOKEN` as well to cover the pairing leg. Tokens are
single-use, so mint a fresh one per run:

```bash
nira device pair test-phone
```

Note that the desktop must have been started with an API key
(`NIRA_API_KEY`, or `[server.auth].api_key`). Without one the server runs
unauthenticated and the device registry is not mounted at all, so enrolment
returns 501 and every request succeeds without a key — which looks like a
client bug and is not one.

## Pairing

On the desktop:

```bash
nira device pair my-phone
```

Scan the QR, or type the address and code by hand — useful for a headless
machine, or when the camera will not cooperate. The phone gets its own key,
which can be revoked without disturbing any other device:

```bash
nira device list
nira device revoke <id>
```

A device is granted scopes at pairing time, defaulting to `ask` and `watch`.
Pair with `--scope` to narrow or widen that; the server enforces it on every
request and on the events socket.

## Voice

Hold the microphone button and speak. The phone records 16 kHz mono PCM, wraps
it in a WAV container and sends it to the paired desktop's
`/v1/speech/transcribe`, where the local Whisper model handles it.

Android's own recogniser would ship your voice to Google, which is the one
thing a local-first assistant exists to avoid. The button only appears once the
desktop confirms it can actually transcribe.

## Projects

Register a directory on the desktop:

```bash
nira project add nira ~/code/nira
```

It then appears as a chip above the composer. Choosing it sends the next prompt
to an agent rooted in that directory rather than to the chat model, and the
activity bar reports what the agent is doing while it works. Chat is always the
default: pointing an agent with file and shell access at a directory is not
something to do by accident.
