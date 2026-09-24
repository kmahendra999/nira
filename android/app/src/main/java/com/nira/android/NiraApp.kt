package com.nira.android

import android.content.Context
import com.nira.android.data.AndroidSecretStore
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.SecretStore

/**
 * The app's few singletons.
 *
 * Deliberately not a DI framework: there are two of them, and a container
 * would be more machinery than the thing it manages.
 */
object NiraApp {
    @Volatile
    private var registryInstance: DesktopRegistry? = null

    @Volatile
    private var secretsInstance: SecretStore? = null

    /**
     * The one secret store.
     *
     * Shared rather than constructed per caller: `AndroidSecretStore` opens
     * EncryptedSharedPreferences, and a second instance over the same file is
     * a second keyset to unwrap for no benefit.
     */
    fun secrets(context: Context): SecretStore =
        secretsInstance ?: synchronized(this) {
            secretsInstance
                ?: AndroidSecretStore(context.applicationContext)
                    .also { secretsInstance = it }
        }

    fun registry(context: Context): DesktopRegistry =
        registryInstance ?: synchronized(this) {
            registryInstance ?: DesktopRegistry(secrets(context))
                .also { registryInstance = it }
        }
}
