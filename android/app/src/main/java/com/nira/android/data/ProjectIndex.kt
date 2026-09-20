package com.nira.android.data

/**
 * A project, and the machine it lives on.
 *
 * Projects are directories, and a directory exists on exactly one computer.
 * Asking the desktop you happen to have selected to work on a project that
 * lives on a different one cannot succeed — at best it fails, at worst the
 * agent finds a same-named directory and edits the wrong tree.
 */
data class LocatedProject(
    val project: Project,
    val desktop: Desktop,
) {
    /** Stable across desktops, which a bare project id is not. */
    val key: String get() = "${desktop.id}/${project.id}"
}

/**
 * Everything the phone can reach, gathered from every paired desktop.
 *
 * The whole reason for pairing more than one machine is that work lives in
 * different places. Showing only the selected desktop's projects turns that
 * into a hunt: switch desktop, look, switch back, look again. Here they are
 * one list, and choosing one also chooses where the work runs.
 */
data class ProjectIndex(
    val located: List<LocatedProject> = emptyList(),
    /** Desktops that could not be reached, so an absence can be explained. */
    val unreachable: List<Desktop> = emptyList(),
) {
    val isEmpty: Boolean get() = located.isEmpty()

    /** True when projects came from more than one machine. */
    val spansDesktops: Boolean
        get() = located.map { it.desktop.id }.distinct().size > 1

    fun find(key: String): LocatedProject? = located.firstOrNull { it.key == key }

    companion object {
        /**
         * Order for display: the selected desktop first, then by name.
         *
         * Whichever machine the user is already pointed at is the one they
         * most likely mean, and a list that reshuffles as desktops come and go
         * is one you cannot build muscle memory for.
         */
        fun of(
            found: Map<Desktop, List<Project>>,
            unreachable: List<Desktop> = emptyList(),
            selectedId: String? = null,
        ): ProjectIndex {
            val located = found.entries
                .flatMap { (desktop, projects) ->
                    projects.map { LocatedProject(it, desktop) }
                }
                .sortedWith(
                    compareBy(
                        { it.desktop.id != selectedId },
                        { it.desktop.name.lowercase() },
                        { it.project.name.lowercase() },
                    )
                )
            return ProjectIndex(located = located, unreachable = unreachable)
        }
    }
}
