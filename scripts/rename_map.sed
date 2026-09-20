# Nira rename map — OpenJarvis -> Nira
#
# This file is INFRASTRUCTURE, not a one-off. It is what keeps upstream security
# patches forward-portable after the rename (see PLAN.md §2.2):
#
#   git format-patch --stdout b03203f..upstream/main \
#     | sed -f scripts/rename_map.sed | git am -3
#
# Order matters. Rules run top to bottom, so the most specific token must come
# first or a short rule corrupts a long one (e.g. `jarvis`->`nira` applied before
# `open-jarvis` would leave `open-nira`).

# ---------------------------------------------------------------------------
# 1. URLs, handled before identifiers.
#
# Without these, the blanket rules below would mangle upstream links into
# nonsense like `github.com/nira/Nira`. `nira-ai/nira` is a PLACEHOLDER — swap it
# for the real org with:  git grep -l nira-ai | xargs sed -i 's|nira-ai|YOURORG|g'
# ---------------------------------------------------------------------------
s|api\.github\.com/repos/open-jarvis/OpenJarvis|api.github.com/repos/nira-ai/nira|g
s|github\.com/open-jarvis/OpenJarvis|github.com/nira-ai/nira|g
s|open-jarvis\.github\.io/OpenJarvis|nira-ai.github.io/nira|g
s|openjarvis\.stanford\.edu|nira-ai.github.io/nira|g
s|pool\.openjarvis\.ai|pool.nira.ai|g
s|discord\.gg/openjarvis|discord.gg/nira|g
s|discord\.gg/CMVBmDQ5Fj|discord.gg/nira|g
s|x\.com/OpenJarvisAI|x.com/NiraAI|g

# ---------------------------------------------------------------------------
# 2. Grammar, before identifiers.
#
# "OpenJarvis" ends in s and takes a bare-apostrophe possessive; "Nira" does
# not. Likewise "an OpenJarvis" -> "a Nira", since the article agrees with the
# sound of the following word. Without these, a plain substitution emits
# "Nira' home directory" and "an Nira AI system" — the latter inside LLM
# prompts, where it degrades output.
# ---------------------------------------------------------------------------
s/OpenJarvis' /Nira's /g
s/An OpenJarvis/A Nira/g
s/an OpenJarvis/a Nira/g

# ---------------------------------------------------------------------------
# 3. Identifiers, most specific first.
# ---------------------------------------------------------------------------
s/OPENJARVIS/NIRA/g
s/OpenJarvis/Nira/g
s/openjarvis/nira/g

s/OPEN-JARVIS/NIRA/g
s/Open-Jarvis/Nira/g
s/open-jarvis/nira/g

s/OPEN JARVIS/NIRA/g
s/Open Jarvis/Nira/g

s/JARVIS/NIRA/g
s/Jarvis/Nira/g
s/jarvis/nira/g
