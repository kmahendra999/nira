package com.nira.android.watch

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.nira.android.MainActivity
import com.nira.android.NiraApp
import com.nira.android.R
import com.nira.android.data.Desktop
import com.nira.android.net.NiraClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Keeps listening to the paired desktops while the app is not in front.
 *
 * An approval blocks a run and then expires: silence becomes a refusal. So
 * "you were not looking at your phone" must not be the same as "no". Something
 * has to hold the connection when the activity is gone, and on Android that
 * something is a foreground service.
 *
 * Deliberately not Firebase. A push would mean the desktop reaching Google's
 * servers to reach a phone sitting on the same tailnet, and the content of
 * every question travelling through a third party — in an assistant whose
 * entire premise is that your data stays on machines you own. The socket is
 * already there; this keeps it open.
 *
 * The honest cost: a persistent connection and a permanent notification. It is
 * opt-in for that reason, and Android will still doze the radio — this makes
 * an approval far more likely to reach someone, not certain to.
 */
class WatchService : Service() {
    private var scope: CoroutineScope? = null
    private val alerts = Alerts()
    private val jobs = mutableListOf<Job>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        startForeground(ONGOING_ID, ongoingNotification())

        val registry = NiraApp.registry(applicationContext)
        val desktops = registry.all()
        if (desktops.isEmpty()) {
            stopSelf()
            return START_NOT_STICKY
        }

        restart(desktops)
        // Restarted if Android kills it for memory: the point is to be
        // listening, and a watcher that quietly stops is worse than one that
        // was never started, because the user believes it is running.
        return START_STICKY
    }

    override fun onDestroy() {
        scope?.cancel()
        scope = null
        super.onDestroy()
    }

    private fun restart(desktops: List<Desktop>) {
        scope?.cancel()
        jobs.clear()
        alerts.forgetAll()
        val fresh = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        scope = fresh
        // Every paired desktop, not just the selected one. A question on the
        // machine you are not currently pointed at is exactly the one you will
        // otherwise miss.
        desktops.filter { it.can("watch") }.forEach { desktop ->
            jobs += fresh.launch { follow(desktop) }
        }
    }

    private suspend fun follow(desktop: Desktop) {
        var since: Long? = null
        var backoffMs = 2_000L
        val client = NiraClient(desktop.baseUrl, desktop.deviceKey)
        while (currentScopeActive()) {
            client.agentEvents(since = since)
                .catch { /* fall through to the retry below */ }
                .collect { event ->
                    event.seq?.let { since = it }
                    backoffMs = 2_000L

                    alerts.resolves(event, desktop.id)?.let { resolved ->
                        NotificationManagerCompat.from(this).cancel(resolved.hashCode())
                        alerts.clear(resolved)
                    }
                    alerts.consider(event, desktop.id, desktop.name)?.let(::post)
                }
            if (!currentScopeActive()) return
            delay(backoffMs)
            // Back off further than the in-app watcher: this runs for hours
            // with the screen off, and a tight retry against a desktop that is
            // switched off is a battery drain with nothing to show for it.
            backoffMs = (backoffMs * 2).coerceAtMost(120_000L)
        }
    }

    private fun currentScopeActive(): Boolean = scope?.isActive == true

    private fun post(alert: Alert) {
        val manager = NotificationManagerCompat.from(this)
        if (!manager.areNotificationsEnabled()) return
        val notification = when (alert) {
            is Alert.NeedsApproval -> approvalNotification(alert)
            is Alert.RunFinished -> finishedNotification(alert)
        }
        runCatching { manager.notify(alert.key.hashCode(), notification) }
    }

    private fun approvalNotification(alert: Alert.NeedsApproval): Notification =
        NotificationCompat.Builder(this, CHANNEL_APPROVALS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("${alert.desktopName} needs your approval")
            .setContentText(alert.summary)
            .setStyle(NotificationCompat.BigTextStyle().bigText(alert.summary))
            // High, and only here. This is the one alert where nothing
            // proceeds until it is answered and where waiting means no.
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setAutoCancel(true)
            .setContentIntent(openApp())
            // Answerable without unlocking and hunting for the app, which is
            // the difference between this being useful and being a reminder
            // to go and do something.
            .addAction(
                0,
                "Refuse",
                decisionIntent(alert, approve = false),
            )
            .addAction(
                0,
                "Allow",
                decisionIntent(alert, approve = true),
            )
            .build()

    private fun finishedNotification(alert: Alert.RunFinished): Notification =
        NotificationCompat.Builder(this, CHANNEL_RUNS)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(
                if (alert.failed) "${alert.agent} stopped with an error"
                else "${alert.agent} finished"
            )
            .setContentText("on ${alert.desktopName}")
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setAutoCancel(true)
            .setContentIntent(openApp())
            .build()

    private fun ongoingNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ONGOING)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Watching your desktops")
            .setContentText("So an approval reaches you before it expires")
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .setContentIntent(openApp())
            .addAction(0, "Stop", stopIntent())
            .build()

    private fun openApp(): PendingIntent = PendingIntent.getActivity(
        this,
        0,
        Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun stopIntent(): PendingIntent = PendingIntent.getService(
        this,
        1,
        Intent(this, WatchService::class.java).setAction(ACTION_STOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun decisionIntent(alert: Alert.NeedsApproval, approve: Boolean): PendingIntent =
        PendingIntent.getBroadcast(
            this,
            // Distinct per alert and per verdict, or Android reuses one
            // PendingIntent and every notification answers the same question.
            (alert.key + approve).hashCode(),
            ApprovalActionReceiver.intent(this, alert, approve),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    companion object {
        const val CHANNEL_APPROVALS = "nira.approvals"
        const val CHANNEL_RUNS = "nira.runs"
        const val CHANNEL_ONGOING = "nira.watching"
        const val ONGOING_ID = 1
        const val ACTION_STOP = "com.nira.android.STOP_WATCHING"

        fun start(context: Context) {
            val intent = Intent(context, WatchService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, WatchService::class.java).setAction(ACTION_STOP)
            )
        }

        /**
         * Three channels, because they are three different interruptions.
         *
         * One channel would mean turning off the notification about a finished
         * run also turns off the one that blocks a run — and people do turn
         * the chatty one off.
         */
        fun createChannels(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_APPROVALS,
                    "Approvals",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "A step is waiting for you to allow or refuse it"
                }
            )
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_RUNS,
                    "Finished work",
                    NotificationManager.IMPORTANCE_LOW,
                ).apply { description = "An agent finished, or stopped with an error" }
            )
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ONGOING,
                    "Watching",
                    NotificationManager.IMPORTANCE_MIN,
                ).apply { description = "Shown while Nira is listening to your desktops" }
            )
        }
    }
}
