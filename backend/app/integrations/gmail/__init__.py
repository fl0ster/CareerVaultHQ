"""Gmail access through a Google Apps Script web app deployed in the monitored account.

The backend never holds Google credentials. The user pastes ``apps_script.gs`` (with the
shared secret filled in by :func:`script_source`) into script.google.com, deploys it as a web
app executing as themselves, and gives the ``/exec`` URL to the app. The backend then calls
it (outbound only, so the app does not need to be reachable from the internet) to list
candidate mails and to mark the handled ones read and labelled.
"""

from app.integrations.gmail.client import (
    LABEL_PATTERN,
    MAX_LOOKBACK_DAYS,
    SCRIPT_URL_PATTERN,
    AppsScriptClient,
    AppsScriptError,
    GmailMessage,
    script_source,
)

__all__ = [
    "LABEL_PATTERN",
    "MAX_LOOKBACK_DAYS",
    "SCRIPT_URL_PATTERN",
    "AppsScriptClient",
    "AppsScriptError",
    "GmailMessage",
    "script_source",
]
