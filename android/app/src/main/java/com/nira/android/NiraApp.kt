package com.nira.android

import android.content.Context
import com.nira.android.data.AndroidSecretStore
import com.nira.android.data.DesktopRegistry

/**
 * The app's few singletons.
 *
 * Deliberately not a DI framework: there are two of them, and a container
 * would be more machinery than the thing it manages.
 */
object NiraApp {
    @Volatile
    private var registryInstance: DesktopRegistry? = null

    fun registry(context: Context): DesktopRegistry =
        registryInstance ?: synchronized(this) {
            registryInstance ?: DesktopRegistry(
                AndroidSecretStore(context.applicationContext)
            ).also { registryInstance = it }
        }
}
