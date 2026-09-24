package com.nira.android.data

/**
 * Comparing one release to another.
 *
 * Deliberately not string comparison. `"0.1.10" < "0.1.9"` is true as text and
 * false as a version, which is the bug every naive update check ships with —
 * and it only appears once a project reaches its tenth patch, by which point
 * nobody is looking at the update code any more.
 */
data class AppVersion(
    val major: Int,
    val minor: Int,
    val patch: Int,
    /** `rc1`, `dev`, or empty for a final release. */
    val preRelease: String = "",
) : Comparable<AppVersion> {

    val isPreRelease: Boolean get() = preRelease.isNotEmpty()

    override fun compareTo(other: AppVersion): Int {
        if (major != other.major) return major.compareTo(other.major)
        if (minor != other.minor) return minor.compareTo(other.minor)
        if (patch != other.patch) return patch.compareTo(other.patch)
        // 1.0.0-rc1 comes before 1.0.0: having a pre-release suffix sorts
        // lower than not having one, which is what semver says and also what
        // a reader expects of "rc".
        return when {
            preRelease == other.preRelease -> 0
            preRelease.isEmpty() -> 1
            other.preRelease.isEmpty() -> -1
            else -> preRelease.compareTo(other.preRelease)
        }
    }

    override fun toString(): String =
        "$major.$minor.$patch" + if (isPreRelease) "-$preRelease" else ""

    companion object {
        // Accepts a release tag or a versionName: `v0.1.1`, `0.1.1`,
        // `1.0.0-rc1`, `0.0.0-dev`. Missing components are zero, so `v1` is
        // 1.0.0 rather than unparseable.
        private val PATTERN = Regex("""^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+](.+))?$""")

        fun parse(raw: String?): AppVersion? {
            val text = raw?.trim().orEmpty()
            if (text.isEmpty()) return null
            val match = PATTERN.matchEntire(text) ?: return null
            val groups = match.groupValues
            return AppVersion(
                major = groups[1].toIntOrNull() ?: return null,
                minor = groups[2].toIntOrNull() ?: 0,
                patch = groups[3].toIntOrNull() ?: 0,
                preRelease = groups[4],
            )
        }
    }
}

/** A published release, as far as the app needs to know about one. */
data class Release(
    val tag: String,
    val version: AppVersion,
    /** Direct link to the apk asset; empty when the release carries none. */
    val apkUrl: String,
    /** The release page, for a reader who would rather look first. */
    val pageUrl: String,
    val notes: String = "",
)

/** What an update check concluded. */
sealed interface UpdateStatus {
    /** Nothing newer, or the check has not run. */
    data object UpToDate : UpdateStatus

    /** The check could not reach the network, or could not read the answer. */
    data object Unknown : UpdateStatus

    data class Available(val release: Release) : UpdateStatus
}

/**
 * Whether *installed* should be offered *latest*.
 *
 * Pure, because this is the part worth testing: the network fetch has one
 * shape and this has all the edge cases.
 *
 * @param dismissedTag a release the reader has already said no to. Saying no
 *   once should not mean being asked again on the next launch — but it only
 *   suppresses that exact release, so the next one is still offered.
 */
fun decideUpdate(
    installedVersion: String?,
    latest: Release?,
    dismissedTag: String? = null,
): UpdateStatus {
    if (latest == null) return UpdateStatus.Unknown
    if (latest.tag == dismissedTag) return UpdateStatus.UpToDate
    // An unreadable installed version is not a reason to nag: it is far more
    // likely to be a build of ours we did not anticipate than a real upgrade.
    val installed = AppVersion.parse(installedVersion) ?: return UpdateStatus.Unknown
    return if (latest.version > installed) {
        UpdateStatus.Available(latest)
    } else {
        UpdateStatus.UpToDate
    }
}
