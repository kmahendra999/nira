package com.nira.android.net

import com.google.common.truth.Truth.assertThat
import org.junit.Test

class SseTest {
    @Test
    fun `extracts content from a delta frame`() {
        val chunk = parseSseChunk(
            """data: {"choices":[{"delta":{"content":"Hello"}}]}"""
        )
        assertThat(chunk).isEqualTo(SseChunk.Text("Hello"))
    }

    @Test
    fun `recognises the end of the stream`() {
        assertThat(parseSseChunk("data: [DONE]")).isEqualTo(SseChunk.Done)
    }

    @Test
    fun `ignores keep-alive and comment lines`() {
        assertThat(parseSseChunk("")).isNull()
        assertThat(parseSseChunk(": ping")).isNull()
        assertThat(parseSseChunk("data:")).isNull()
        assertThat(parseSseChunk("event: message")).isNull()
    }

    @Test
    fun `ignores the opening role frame`() {
        // The server's first frame announces the role and carries no text.
        // Treating it as the end of the stream would truncate every answer
        // before its first token.
        val chunk = parseSseChunk(
            """data: {"choices":[{"delta":{"role":"assistant"}}]}"""
        )
        assertThat(chunk).isNull()
    }

    @Test
    fun `ignores the finish frame`() {
        val chunk = parseSseChunk(
            """data: {"choices":[{"delta":{},"finish_reason":"stop"}]}"""
        )
        assertThat(chunk).isNull()
    }

    @Test
    fun `keeps whitespace inside content`() {
        // Tokens routinely are a single space. Trimming content would run
        // every word of the answer together.
        val chunk = parseSseChunk("""data: {"choices":[{"delta":{"content":" "}}]}""")
        assertThat(chunk).isEqualTo(SseChunk.Text(" "))
    }

    @Test
    fun `keeps newlines inside content`() {
        val chunk = parseSseChunk("""data: {"choices":[{"delta":{"content":"\n\n"}}]}""")
        assertThat(chunk).isEqualTo(SseChunk.Text("\n\n"))
    }

    @Test
    fun `raises an in-band error rather than ending quietly`() {
        val failure = runCatching {
            parseSseChunk("""data: {"error":{"message":"model is not loaded"}}""")
        }.exceptionOrNull()
        assertThat(failure).isInstanceOf(NiraException::class.java)
        assertThat(failure).hasMessageThat().contains("model is not loaded")
    }

    @Test
    fun `survives a truncated frame`() {
        // A dropped connection can cut a line in half. That is a reason to
        // skip the line, not to crash the conversation.
        assertThat(parseSseChunk("""data: {"choices":[{"delta":{"cont""")).isNull()
    }

    @Test
    fun `survives an empty choices array`() {
        assertThat(parseSseChunk("""data: {"choices":[]}""")).isNull()
    }

    @Test
    fun `tolerates a missing space after the colon`() {
        val chunk = parseSseChunk("""data:{"choices":[{"delta":{"content":"hi"}}]}""")
        assertThat(chunk).isEqualTo(SseChunk.Text("hi"))
    }

    @Test
    fun `ignores fields it does not know`() {
        val chunk = parseSseChunk(
            """data: {"id":"x","object":"chunk","usage":{"total_tokens":4},""" +
                """"choices":[{"index":0,"delta":{"content":"ok"},"logprobs":null}]}"""
        )
        assertThat(chunk).isEqualTo(SseChunk.Text("ok"))
    }
}
