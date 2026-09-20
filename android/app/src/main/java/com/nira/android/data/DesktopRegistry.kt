package com.nira.android.data

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Somewhere to keep a secret, abstracted so the registry's logic can be tested
 * on the JVM. The Android implementation is backed by the Keystore; a plain map
 * stands in under test.
 */
interface SecretStore {
    fun read(key: String): String?
    fun write(key: String, value: String)
}

class InMemorySecretStore(
    private val values: MutableMap<String, String> = mutableMapOf(),
) : SecretStore {
    override fun read(key: String): String? = values[key]
    override fun write(key: String, value: String) {
        values[key] = value
    }
}

/**
 * The desktops this phone is paired with.
 *
 * Plural by design: one phone pairs with several machines, each issuing its own
 * key, and revoking one must leave the others working. A single global
 * "server URL and API key" setting cannot express that.
 */
class DesktopRegistry(
    private val store: SecretStore,
    private val json: Json = Json { ignoreUnknownKeys = true; encodeDefaults = true },
) {
    companion object {
        private const val KEY_DESKTOPS = "desktops"
        private const val KEY_SELECTED = "selected_desktop"
        private const val KEY_WATCHING = "watch_in_background"
    }

    fun all(): List<Desktop> {
        val raw = store.read(KEY_DESKTOPS) ?: return emptyList()
        return runCatching {
            json.decodeFromString(ListSerializer(Desktop.serializer()), raw)
        }.getOrDefault(emptyList())
    }

    fun get(id: String): Desktop? = all().firstOrNull { it.id == id }

    /**
     * Add or replace a pairing.
     *
     * Keyed on id, which is the server-issued device id: re-pairing the same
     * phone to the same desktop should replace the old entry rather than leave
     * a stale key behind that no longer authenticates.
     */
    fun save(desktop: Desktop) {
        val updated = all().filterNot { it.id == desktop.id } + desktop
        persist(updated)
        if (selectedId() == null) select(desktop.id)
    }

    fun remove(id: String) {
        persist(all().filterNot { it.id == id })
        if (selectedId() == id) {
            // Do not leave the app pointing at a desktop that is gone.
            store.write(KEY_SELECTED, all().firstOrNull()?.id.orEmpty())
        }
    }

    fun select(id: String) {
        store.write(KEY_SELECTED, id)
    }

    fun selectedId(): String? = store.read(KEY_SELECTED)?.ifBlank { null }

    /** The desktop commands go to, falling back to the only one if unset. */
    fun selected(): Desktop? {
        val desktops = all()
        val chosen = selectedId()?.let { id -> desktops.firstOrNull { it.id == id } }
        return chosen ?: desktops.firstOrNull()
    }

    /**
     * Whether to keep listening while the app is closed.
     *
     * Off unless asked for. It costs a persistent connection, a permanent
     * notification and battery — a reasonable trade for someone who runs long
     * agent tasks, and an imposition on someone who does not.
     */
    fun watchesInBackground(): Boolean = store.read(KEY_WATCHING) == "true"

    fun setWatchesInBackground(enabled: Boolean) {
        store.write(KEY_WATCHING, if (enabled) "true" else "false")
    }

    private fun persist(desktops: List<Desktop>) {
        store.write(
            KEY_DESKTOPS,
            json.encodeToString(ListSerializer(Desktop.serializer()), desktops),
        )
    }
}
