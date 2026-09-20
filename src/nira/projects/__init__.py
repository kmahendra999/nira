"""Project registry — the durable answer to "work on project X".

Before this there was no notion of a project anywhere. ``workspace`` existed
only as a constructor string on individual agents, so a request naming a
project had nothing to resolve against: no path, no history, and no session to
continue. A coding agent started from scratch in whatever directory the server
happened to be running in.

A project is deliberately thin — a name, a path, and what Nira learned last
time it worked there. Anything richer belongs in the agent's own state.
"""

from nira.projects.store import Project, ProjectStore

__all__ = ["Project", "ProjectStore"]
