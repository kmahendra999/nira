package com.nira.android.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Mirrors the web app's tokens so the two surfaces read as one product.
// Orange-400 on dark, orange-600 on light: the lighter value fails contrast
// against white, which is why the two differ rather than sharing one accent.
private val AccentDark = Color(0xFFFB923C)
private val AccentLight = Color(0xFFC2410C)

private val DarkColors = darkColorScheme(
    primary = AccentDark,
    onPrimary = Color(0xFF1A0E05),
    background = Color(0xFF0A0A0B),
    onBackground = Color(0xFFEDEDEF),
    surface = Color(0xFF121214),
    onSurface = Color(0xFFEDEDEF),
    surfaceVariant = Color(0xFF18181B),
    onSurfaceVariant = Color(0xFF8D8D93),
    error = Color(0xFFF87171),
)

private val LightColors = lightColorScheme(
    primary = AccentLight,
    onPrimary = Color.White,
    background = Color(0xFFF9F9F9),
    onBackground = Color(0xFF09090B),
    surface = Color.White,
    onSurface = Color(0xFF09090B),
    surfaceVariant = Color(0xFFE4E4E7),
    onSurfaceVariant = Color(0xFF71717A),
    error = Color(0xFFB91C1C),
)

@Composable
fun NiraTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
