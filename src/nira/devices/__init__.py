"""Per-device identity for a Nira mesh.

The server authenticates with a single static bearer token shared by every
caller. That is fine on loopback and wrong the moment Nira is reachable from
anything else: one token means no way to tell a phone from a laptop, no way to
revoke one without revoking all, no per-device audit trail, and no way to let a
phone ask questions without also letting it approve a destructive tool call.

It matters more here than in a typical deployment. A tailnet is not
automatically yours alone — this one is shared with another account — so
"reachable over Tailscale" can never stand in for "trusted".
"""

from nira.devices.store import Device, DeviceStore, Enrollment

__all__ = ["Device", "DeviceStore", "Enrollment"]
