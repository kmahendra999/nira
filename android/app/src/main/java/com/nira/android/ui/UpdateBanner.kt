package com.nira.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.nira.android.data.Release

/**
 * "A newer version exists", with somewhere to go about it.
 *
 * A bar rather than a dialog. The reader opened the app to do something, and
 * a modal on launch interrupts that to deliver news they did not ask for —
 * for a sideloaded build whose update is a manual download anyway.
 */
@Composable
fun UpdateBanner(
    release: Release,
    installedVersion: String,
    onUpdate: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
    ) {
        Column(modifier = Modifier.padding(start = 16.dp, end = 8.dp, top = 12.dp)) {
            Text(
                text = "Nira ${release.version} is available",
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                // Naming the installed version too, because "an update is
                // available" is not something a reader can sanity-check.
                text = "You have $installedVersion. The download is an apk — " +
                    "Android will ask you to confirm the install.",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(top = 2.dp),
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onDismiss) { Text("Not now") }
                TextButton(onClick = onUpdate) { Text("Download") }
            }
        }
    }
}
