package com.nira.android.data

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The 44 bytes a WAV header must be for 1600 samples of 16 kHz mono 16-bit PCM.
 *
 * Copied from a file that an independent decoder — Python's `wave` module —
 * opened and reported back as 16000 Hz, 1 channel, 16 bit, 1600 frames. It is
 * spelled out rather than recomputed because a test that derives the expected
 * header the same way the production code does would agree with any mistake
 * they both made, and a WAV the desktop cannot parse transcribes as noise
 * rather than failing outright.
 */
private val GOLDEN_HEADER_1600_SAMPLES = byteArrayOf(
    82, 73, 70, 70, // "RIFF"
    164.toByte(), 12, 0, 0, // 36 + 3200
    87, 65, 86, 69, // "WAVE"
    102, 109, 116, 32, // "fmt "
    16, 0, 0, 0, // subchunk size
    1, 0, // PCM
    1, 0, // mono
    128.toByte(), 62, 0, 0, // 16000 Hz
    0, 125, 0, 0, // 32000 byte/s
    2, 0, // block align
    16, 0, // bits per sample
    100, 97, 116, 97, // "data"
    128.toByte(), 12, 0, 0, // 3200
)

class WavTest {
    private fun silence(samples: Int) = ByteArray(samples * 2)

    @Test
    fun `header matches a file an independent decoder accepted`() {
        val wav = Wav.wrap(silence(1600))
        assertThat(wav.copyOfRange(0, 44).toList())
            .isEqualTo(GOLDEN_HEADER_1600_SAMPLES.toList())
    }

    @Test
    fun `samples follow the header untouched`() {
        val pcm = ByteArray(64) { (it * 3).toByte() }
        val wav = Wav.wrap(pcm)
        assertThat(wav.size).isEqualTo(44 + 64)
        assertThat(wav.copyOfRange(44, wav.size).toList()).isEqualTo(pcm.toList())
    }

    @Test
    fun `declares the RIFF size excluding the first eight bytes`() {
        val wav = Wav.wrap(silence(10))
        assertThat(wav.intLeAt(4)).isEqualTo(wav.size - 8)
    }

    @Test
    fun `declares the data size as the sample count`() {
        val wav = Wav.wrap(silence(777))
        assertThat(wav.intLeAt(40)).isEqualTo(777 * 2)
    }

    @Test
    fun `byte rate follows a non-default sample rate`() {
        // Derived fields have to move with the rate. A header that says 48 kHz
        // but keeps the 16 kHz byte rate plays — and transcribes — at the
        // wrong speed.
        val wav = Wav.wrap(silence(10), sampleRate = 48_000)
        assertThat(wav.intLeAt(24)).isEqualTo(48_000)
        assertThat(wav.intLeAt(28)).isEqualTo(48_000 * 2)
    }

    @Test
    fun `handles an empty recording without producing a broken file`() {
        val wav = Wav.wrap(ByteArray(0))
        assertThat(wav.size).isEqualTo(44)
        assertThat(wav.intLeAt(40)).isEqualTo(0)
        assertThat(wav.intLeAt(4)).isEqualTo(36)
    }

    @Test
    fun `silence reads as no level`() {
        assertThat(Wav.level(silence(512))).isEqualTo(0f)
    }

    @Test
    fun `a loud signal reads near full scale`() {
        val loud = ByteArray(512 * 2)
        for (i in 0 until 512) {
            val value = if (i % 2 == 0) 32_767 else -32_768
            loud[i * 2] = (value and 0xFF).toByte()
            loud[i * 2 + 1] = ((value shr 8) and 0xFF).toByte()
        }
        assertThat(Wav.level(loud)).isGreaterThan(0.9f)
    }

    @Test
    fun `level honours the length of the filled prefix`() {
        // AudioRecord reports how much of the buffer it filled; measuring the
        // whole buffer would average in trailing zeros and under-report the
        // level on every short read.
        val buffer = ByteArray(1024)
        buffer[0] = 0xFF.toByte()
        buffer[1] = 0x7F
        assertThat(Wav.level(buffer, length = 2)).isGreaterThan(Wav.level(buffer))
    }

    @Test
    fun `level of nothing is zero rather than NaN`() {
        assertThat(Wav.level(ByteArray(0))).isEqualTo(0f)
    }

    @Test
    fun `level never exceeds one`() {
        val extreme = ByteArray(64) { 0xFF.toByte() }
        assertThat(Wav.level(extreme)).isAtMost(1f)
    }

    private fun ByteArray.intLeAt(offset: Int): Int =
        (this[offset].toInt() and 0xFF) or
            ((this[offset + 1].toInt() and 0xFF) shl 8) or
            ((this[offset + 2].toInt() and 0xFF) shl 16) or
            ((this[offset + 3].toInt() and 0xFF) shl 24)
}
