"""Data source connectors for Deep Research."""

from nira.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from nira.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

# Auto-register built-in connectors
import nira.connectors.obsidian  # noqa: F401

try:
    import nira.connectors.gmail  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.gdrive  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import nira.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.apple_contacts  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.apple_calendar  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.imap  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import nira.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.google_tasks  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.weather  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.github_notifications  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.hackernews  # noqa: F401
except ImportError:
    pass

try:
    import nira.connectors.news_rss  # noqa: F401
except ImportError:
    pass
