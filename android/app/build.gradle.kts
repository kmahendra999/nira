// The apk has to say which release it is, or the in-app update check has
// nothing to compare against. Both were hard-coded, so every release shipped
// an apk claiming to be 0.1.0 -- including the one attached to v0.1.1.
//
// CI passes -PniraVersion=<tag>; a local build gets a version that is
// obviously not a release and that always compares as older than one.
val niraVersionName: String =
    (project.findProperty("niraVersion") as String?)
        ?.removePrefix("v")
        ?.trim()
        ?.takeIf { it.isNotEmpty() }
        ?: "0.0.0-dev"

/**
 * A monotonic integer for Android, derived from the same string.
 *
 * Android compares versionCode and nothing else when deciding whether an
 * install is an upgrade, so it has to rise with the version name. Two decimal
 * digits per component caps a component at 99, which is a long way off and
 * keeps the number readable: 0.1.1 is 10001.
 */
fun niraVersionCode(name: String): Int {
    val parts = name.substringBefore('-').split('.')
    fun part(i: Int) = parts.getOrNull(i)?.toIntOrNull()?.coerceIn(0, 99) ?: 0
    val code = part(0) * 10_000 + part(1) * 100 + part(2)
    // Android rejects 0, and a dev build should sort below every release.
    return if (code <= 0) 1 else code
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.nira.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.nira.android"
        // 26 is where notification channels and foreground services land, both
        // of which a background voice assistant needs.
        minSdk = 26
        targetSdk = 36
        versionCode = niraVersionCode(niraVersionName)
        versionName = niraVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions { jvmTarget = "17" }

    // buildConfig, so the app can read the version it was built as and
    // compare it against the newest release.
    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    }

    testOptions {
        unitTests {
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons)
    implementation(libs.androidx.navigation.compose)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.security.crypto)

    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)

    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)
    implementation(libs.mlkit.barcode)

    testImplementation(libs.junit)
    testImplementation(libs.truth)
    testImplementation(libs.turbine)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.kotlinx.coroutines.test)
}
