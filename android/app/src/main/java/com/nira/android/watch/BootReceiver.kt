package com.nira.android.watch

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.nira.android.NiraApp

/**
 * Starts watching again after a reboot.
 *
 * Without this the switch is a lie the first time the phone restarts: it still
 * reads "on", nothing is listening, and the user finds out when an approval
 * they never saw has already timed out into a refusal. A watcher that quietly
 * stops is worse than one that was never started.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            return
        }
        val registry = NiraApp.registry(context.applicationContext)
        if (registry.watchesInBackground() && registry.all().isNotEmpty()) {
            WatchService.start(context.applicationContext)
        }
    }
}
