package com.nira.android.data

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

private const val TAG = "NiraSecretStore"
private const val FILE = "nira_secrets"

/**
 * Device keys, held under a Keystore-backed master key.
 *
 * These authenticate against a desktop that can run shell commands, so plain
 * SharedPreferences would leave them readable by anything with access to the
 * app's data directory — a rooted phone, an ADB backup, a filesystem dump.
 */
class AndroidSecretStore(context: Context) : SecretStore {
    private val prefs: SharedPreferences = create(context)

    override fun read(key: String): String? = prefs.getString(key, null)

    override fun write(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }

    private companion object {
        fun create(context: Context): SharedPreferences {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            return try {
                EncryptedSharedPreferences.create(
                    context,
                    FILE,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                )
            } catch (e: Exception) {
                // A rotated or invalidated Keystore entry makes the existing
                // file undecryptable. Start over rather than refusing to open:
                // the cost is re-pairing, and the alternative is an app that
                // cannot launch until its data is cleared.
                Log.w(TAG, "Encrypted store unreadable; recreating", e)
                context.deleteSharedPreferences(FILE)
                EncryptedSharedPreferences.create(
                    context,
                    FILE,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                )
            }
        }
    }
}
