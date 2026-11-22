"""HTTP client of the Apps Script web app in ``apps_script.gs``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

SECRET_PLACEHOLDER = "__CAREERVAULT_SECRET__"
MAX_LOOKBACK_DAYS = 30
"""Same cap as ``MAX_LOOKBACK_DAYS`` in ``apps_script.gs``."""
LABEL_PATTERN = r"^[\w .\/-]{1,128}$"
"""Label names the script accepts (``LABEL_PATTERN`` in ``apps_script.gs``)."""
DEFAULT_TIMEOUT = 60.0
SCRIPT_URL_PATTERN = r"^https://script\.google\.com/(?:a/macros/[A-Za-z0-9.-]+|macros)/s/[A-Za-z0-9_-]+/exec$"
"""Deployed Apps Script web apps only (consumer and Workspace accounts). The secret is sent
to this URL, so nothing else is accepted."""
REDIRECT_HOSTS = frozenset({"script.google.com", "script.googleusercontent.com"})
"""Hosts the web app may redirect to (its output is served from googleusercontent)."""
MAX_REDIRECTS = 5


def is_script_url(url: str) -> bool:
    return re.fullmatch(SCRIPT_URL_PATTERN, url or "") is not None


class AppsScriptError(Exception):
    """The web app could not be reached or answered with an error."""


def script_source(secret: str) -> str:
    """``apps_script.gs`` with ``secret`` filled in, ready to paste into script.google.com."""
    template = files("app.integrations.gmail").joinpath("apps_script.gs").read_text("utf-8")
    return template.replace(SECRET_PLACEHOLDER, secret)


@dataclass(frozen=True, slots=True)
class GmailMessage:
    id: str
    thread_id: str | None
    sender: str
    subject: str
    received_at: datetime | None
    body: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> GmailMessage:
        received_at = None
        if data.get("date"):
            try:
                received_at = datetime.fromisoformat(str(data["date"]).replace("Z", "+00:00"))
            except ValueError:
                received_at = None
        return cls(
            id=str(data["id"]),
            thread_id=str(data["thread_id"]) if data.get("thread_id") else None,
            sender=str(data.get("from") or ""),
            subject=str(data.get("subject") or ""),
            received_at=received_at,
            body=str(data.get("body") or ""),
        )


class AppsScriptClient:
    """Calls the deployed web app. Apps Script answers a POST with a redirect to
    ``script.googleusercontent.com`` holding the output, hence ``follow_redirects``."""

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not url:
            raise AppsScriptError("the Apps Script web app URL is not configured")
        if not is_script_url(url):
            raise AppsScriptError("the web app URL must look like https://script.google.com/macros/s/<id>/exec")
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self._transport = transport

    def ping(self) -> str:
        """Address of the Google account the script runs as."""
        return str(self._call("ping").get("email") or "")

    def list_messages(self, lookback_days: int, label: str, max_messages: int = 30) -> list[GmailMessage]:
        """Unread, job-related inbox messages of the last ``lookback_days`` days whose thread
        does not carry ``label``. The script builds the search itself (capped at
        ``MAX_LOOKBACK_DAYS``), so callers cannot query the rest of the mailbox."""
        data = self._call("list", lookback_days=lookback_days, label=label, max=max_messages)
        messages = data.get("messages")
        if not isinstance(messages, list):
            raise AppsScriptError("the web app answered without a messages list")
        return [GmailMessage.from_json(m) for m in messages if isinstance(m, dict) and m.get("id")]

    def mark(self, message_id: str, label: str) -> None:
        """Mark the message read and add ``label`` to its thread (created when missing)."""
        self._call("mark", id=message_id, label=label)

    def label(self, message_id: str, label: str) -> None:
        """Add ``label`` to the message's thread (created when missing) without changing
        whether it is read. Needs a script deployed with the ``label`` action."""
        self._call("label", id=message_id, label=label)

    @staticmethod
    def _follow(client: httpx.Client, response: httpx.Response) -> httpx.Response:
        """Follow the web app's redirects (as GETs, without the request body) to Google
        hosts only."""
        for _ in range(MAX_REDIRECTS):
            if not response.is_redirect:
                return response
            location = urljoin(str(response.request.url), response.headers.get("location", ""))
            parts = urlsplit(location)
            if parts.scheme != "https" or parts.hostname not in REDIRECT_HOSTS:
                raise AppsScriptError(f"the web app redirected to an unexpected host: {parts.hostname}")
            response = client.get(location)
        raise AppsScriptError("too many redirects from the Apps Script web app")

    def _call(self, action: str, **params: Any) -> dict[str, Any]:
        body = {"token": self.secret, "action": action, **params}
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.post(self.url, json=body)
                response = self._follow(client, response)
        except httpx.HTTPError as exc:
            raise AppsScriptError(f"cannot reach the Apps Script web app: {exc}") from exc
        if response.status_code >= 400:
            raise AppsScriptError(f"the Apps Script web app answered HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise AppsScriptError(
                "the Apps Script web app did not answer JSON; check that it is deployed as a "
                "web app with access 'Anyone' and that the URL ends with /exec"
            ) from exc
        if not isinstance(data, dict):
            raise AppsScriptError("unexpected answer from the Apps Script web app")
        if data.get("error"):
            error = str(data["error"])
            if error == "unauthorized":
                error = "unauthorized: the secret in the script does not match; copy it again"
            raise AppsScriptError(error)
        return data
