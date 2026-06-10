"""Google 生态集成（Gmail API + Google Calendar API）

通过 OAuth2 授权访问真实的 Gmail 邮箱和 Google Calendar。
"""

from mail_agent.gapi.auth import GoogleAuthError, get_credentials
from mail_agent.gapi.gcalendar import GoogleCalendarClient
from mail_agent.gapi.gmail import GmailClient

__all__ = [
    "GoogleAuthError",
    "get_credentials",
    "GmailClient",
    "GoogleCalendarClient",
]
