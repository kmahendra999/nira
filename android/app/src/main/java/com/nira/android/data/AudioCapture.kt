package com.nira.android.data

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean

/** Refuse to send anything shorter than this; it is a mis-tap, not a sentence. */
private const val MIN_SPEECH_MS = 400

/** Stop regardless at this point, so a stuck recorder cannot fill memory. */
private const val MAX_SPEECH_MS = 120_000

/**
 * Microphone capture that yields WAV bytes for the desktop to transcribe.
 *
 * Push-to-talk rather than always-listening: the desktop already has a voice
 * pipeline with wake-word detection, and a phone that streams the microphone
 * continuously over a tailnet is both a battery problem and a privacy one that
 * nobody asked for.
 */
class AudioCapture : Microphone {
    private val recording = AtomicBoolean(false)

    @Volatile
    override var level: Float = 0f
        private set

    val isRecording: Boolean get() = recording.get()

    /**
     * Record until [stop] is called, then return the audio.
     *
     * Blocking, so callers must run it off the main thread. Returns null when
     * the microphone could not be opened or the take was too short to be
     * speech — both cases the caller should report rather than send.
     */
    @SuppressLint("MissingPermission") // The caller holds RECORD_AUDIO; see AskScreen.
    override fun record(): ByteArray? {
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuffer <= 0) return null

        // Ask for a buffer well above the minimum. At the minimum a single
        // scheduling hiccup drops samples, and dropped samples in the middle
        // of a word are transcribed as a different word rather than as a gap.
        val bufferBytes = minBuffer * 4
        val recorder = runCatching {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferBytes,
            )
        }.getOrNull() ?: return null

        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            return null
        }

        val pcm = ByteArrayOutputStream()
        val chunk = ByteArray(bufferBytes)
        val maxBytes = MAX_SPEECH_MS / 1000 * SAMPLE_RATE_HZ * 2

        recording.set(true)
        try {
            recorder.startRecording()
            while (recording.get() && pcm.size() < maxBytes) {
                val read = recorder.read(chunk, 0, chunk.size)
                if (read <= 0) break
                pcm.write(chunk, 0, read)
                level = Wav.level(chunk, read)
            }
        } catch (_: IllegalStateException) {
            return null
        } finally {
            recording.set(false)
            level = 0f
            runCatching { recorder.stop() }
            recorder.release()
        }

        val bytes = pcm.toByteArray()
        val durationMs = bytes.size * 1000L / (SAMPLE_RATE_HZ * 2)
        if (durationMs < MIN_SPEECH_MS) return null
        return Wav.wrap(bytes)
    }

    override fun stop() {
        recording.set(false)
    }
}
