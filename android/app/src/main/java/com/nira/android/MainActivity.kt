package com.nira.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.nira.android.data.DesktopRegistry
import com.nira.android.ui.ApprovalsViewModel
import com.nira.android.ui.AskViewModel
import com.nira.android.ui.DesktopsViewModel
import com.nira.android.ui.PairingViewModel
import com.nira.android.ui.screens.ApprovalsScreen
import com.nira.android.ui.screens.AskScreen
import com.nira.android.ui.screens.DesktopsScreen
import com.nira.android.ui.screens.PairingScreen
import com.nira.android.ui.theme.NiraTheme

private object Route {
    const val ASK = "ask"
    const val DESKTOPS = "desktops"
    const val PAIR = "pair"
    const val APPROVALS = "approvals"
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            NiraTheme {
                val registry = remember { NiraApp.registry(applicationContext) }
                NiraNav(registry)
            }
        }
    }
}

@Composable
private fun NiraNav(registry: DesktopRegistry) {
    val nav = rememberNavController()
    val factory = remember(registry) { NiraViewModelFactory(registry) }

    // Land on the picker when nothing is paired yet: an empty conversation
    // screen with a disabled input gives no hint that pairing is the missing
    // step, and the picker says so outright.
    //
    // Remembered because NavHost reads it once, and recomputing it on every
    // recomposition would re-read and re-parse the registry off disk for an
    // answer that is then thrown away.
    val start = remember(registry) {
        if (registry.all().isEmpty()) Route.DESKTOPS else Route.ASK
    }

    NavHost(navController = nav, startDestination = start) {
        composable(Route.ASK) {
            val model: AskViewModel = viewModel(factory = factory)
            AskScreen(
                viewModel = model,
                onDesktops = { nav.navigate(Route.DESKTOPS) },
                onApprovals = { nav.navigate(Route.APPROVALS) },
            )
        }
        composable(Route.DESKTOPS) {
            val model: DesktopsViewModel = viewModel(factory = factory)
            DesktopsScreen(
                viewModel = model,
                onPair = { nav.navigate(Route.PAIR) },
                onOpen = {
                    // Pop back to the conversation rather than stacking one on
                    // top of the picker, so Back leaves the app instead of
                    // walking the user through every desktop they opened.
                    nav.navigate(Route.ASK) {
                        popUpTo(Route.ASK) { inclusive = true }
                        launchSingleTop = true
                    }
                },
            )
        }
        composable(Route.APPROVALS) {
            val model: ApprovalsViewModel = viewModel(factory = factory)
            ApprovalsScreen(viewModel = model, onBack = { nav.popBackStack() })
        }
        composable(Route.PAIR) {
            val model: PairingViewModel = viewModel(factory = factory)
            PairingScreen(
                viewModel = model,
                onPaired = { nav.popBackStack(Route.DESKTOPS, inclusive = false) },
                onBack = { nav.popBackStack() },
            )
        }
    }
}

/**
 * Builds the three view models, all of which need the registry.
 *
 * Hand-written because the alternative is a dependency-injection framework for
 * a single dependency shared by three classes.
 */
private class NiraViewModelFactory(
    private val registry: DesktopRegistry,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = when {
        modelClass.isAssignableFrom(AskViewModel::class.java) -> AskViewModel(registry)
        modelClass.isAssignableFrom(ApprovalsViewModel::class.java) ->
            ApprovalsViewModel(registry)
        modelClass.isAssignableFrom(DesktopsViewModel::class.java) -> DesktopsViewModel(registry)
        modelClass.isAssignableFrom(PairingViewModel::class.java) -> PairingViewModel(registry)
        else -> throw IllegalArgumentException("Unknown view model ${modelClass.name}")
    } as T
}
