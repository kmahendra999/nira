package com.nira.android.data

/**
 * Something that can record speech.
 *
 * An interface only so the conversation logic can be tested without an
 * emulator: everything else about talking to a desktop is exercised on the
 * JVM, and a microphone should not be the reason that stops being true.
 */
interface Microphone {
    /** Current input level, 0..1, for the meter. */
    val level: Float

    /** Record until [stop]; null when the mic failed or the take was too short. */
    fun record(): ByteArray?

    fun stop()
}
