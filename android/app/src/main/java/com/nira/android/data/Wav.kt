package com.nira.android.data

import java.io.ByteArrayOutputStream

/** Sample rate Whisper resamples everything to anyway; sending it 16 kHz avoids the round trip. */
const val SAMPLE_RATE_HZ = 16_000

/**
 * Wrap raw 16-bit mono PCM in a WAV container.
 *
 * The desktop picks the decoder from the filename extension, so the bytes
 * behind `speech.wav` have to actually be a WAV — raw PCM with a .wav name
 * transcribes as noise rather than failing outright, which is a far harder
 * bug to see.
 */
object Wav {
    fun wrap(pcm: ByteArray, sampleRate: Int = SAMPLE_RATE_HZ, channels: Int = 1): ByteArray {
        val bitsPerSample = 16
        val byteRate = sampleRate * channels * bitsPerSample / 8
        val blockAlign = channels * bitsPerSample / 8
        val out = ByteArrayOutputStream(44 + pcm.size)

        out.writeAscii("RIFF")
        out.writeIntLe(36 + pcm.size)
        out.writeAscii("WAVE")

        out.writeAscii("fmt ")
        out.writeIntLe(16) // PCM subchunk size
        out.writeShortLe(1) // format: PCM, uncompressed
        out.writeShortLe(channels)
        out.writeIntLe(sampleRate)
        out.writeIntLe(byteRate)
        out.writeShortLe(blockAlign)
        out.writeShortLe(bitsPerSample)

        out.writeAscii("data")
        out.writeIntLe(pcm.size)
        out.write(pcm)

        return out.toByteArray()
    }

    /**
     * Root-mean-square level of 16-bit PCM, for the level meter.
     *
     * Returned as 0..1 rather than raw amplitude so the UI does not have to
     * know how wide a sample is.
     */
    fun level(pcm: ByteArray, length: Int = pcm.size): Float {
        val samples = length / 2
        if (samples == 0) return 0f
        var sum = 0.0
        for (i in 0 until samples) {
            val lo = pcm[i * 2].toInt() and 0xFF
            val hi = pcm[i * 2 + 1].toInt() // signed: this is the high byte
            val sample = (hi shl 8) or lo
            sum += sample.toDouble() * sample.toDouble()
        }
        return (Math.sqrt(sum / samples) / Short.MAX_VALUE).toFloat().coerceIn(0f, 1f)
    }

    private fun ByteArrayOutputStream.writeAscii(text: String) {
        write(text.toByteArray(Charsets.US_ASCII))
    }

    private fun ByteArrayOutputStream.writeIntLe(value: Int) {
        write(value and 0xFF)
        write((value shr 8) and 0xFF)
        write((value shr 16) and 0xFF)
        write((value shr 24) and 0xFF)
    }

    private fun ByteArrayOutputStream.writeShortLe(value: Int) {
        write(value and 0xFF)
        write((value shr 8) and 0xFF)
    }
}
