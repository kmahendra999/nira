package com.nira.android.watch

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationManagerCompat
import com.nira.android.NiraApp
import com.nira.android.net.NiraClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

private const val TAG = "NiraApproval"

/**
 * Answers an approval straight from the notification.
 *
 * Without this the notification is only a reminder to go and do something:
 * unlock, find the app, navigate, tap. An approval expires, so the number of
 * steps between seeing it and answering it decides whether the answer arrives
 * in time.
 */
class ApprovalActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val desktopId = intent.getStringExtra(EXTRA_DESKTOP) ?: return
        val approvalId = intent.getStringExtra(EXTRA_APPROVAL) ?: return
        val notificationKey = intent.getStringExtra(EXTRA_KEY) ?: return
        val approve = intent.getBooleanExtra(EXTRA_APPROVE, false)

        // Take it down first. The request may be slow or fail, and a
        // notification still sitting there after a tap invites a second one —
        // which either double-answers or fails on an id already settled.
        NotificationManagerCompat.from(context).cancel(notificationKey.hashCode())

        val desktop = NiraApp.registry(context.applicationContext).get(desktopId)
        if (desktop == null) {
            Log.w(TAG, "no desktop $desktopId; it may have been unpaired")
            return
        }

        // goAsync keeps the process alive past onReceive, which otherwise ends
        // the moment this method returns and takes the request with it.
        val finish = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                NiraClient(desktop.baseUrl, desktop.deviceKey)
                    .decideApproval(approvalId, approve)
            } catch (error: Throwable) {
                // Nothing useful to show: the notification is already gone and
                // there may be no UI at all. The run falls back to its timeout,
                // which denies — the safe direction.
                Log.w(TAG, "could not answer $approvalId", error)
            } finally {
                finish.finish()
            }
        }
    }

    companion object {
        const val EXTRA_DESKTOP = "desktop_id"
        const val EXTRA_APPROVAL = "approval_id"
        const val EXTRA_APPROVE = "approve"
        const val EXTRA_KEY = "alert_key"

        fun intent(
            context: Context,
            alert: Alert.NeedsApproval,
            approve: Boolean,
        ): Intent = Intent(context, ApprovalActionReceiver::class.java)
            .setAction(if (approve) "com.nira.android.ALLOW" else "com.nira.android.REFUSE")
            .putExtra(EXTRA_DESKTOP, alert.desktopId)
            .putExtra(EXTRA_APPROVAL, alert.approvalId)
            .putExtra(EXTRA_APPROVE, approve)
            .putExtra(EXTRA_KEY, alert.key)
    }
}
