"""
Async Google Calendar client.
Wraps the sync Google API client in a thread executor.
"""
import asyncio
import os
import zoneinfo
from datetime import date, datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


class GoogleCalendarClient:
    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        self._service = None

    @property
    def is_configured(self) -> bool:
        return all([self.client_id, self.client_secret, self.refresh_token])

    async def __aenter__(self):
        if not self.is_configured:
            raise RuntimeError("Google Calendar env vars not set")
        loop = asyncio.get_event_loop()
        self._service = await loop.run_in_executor(None, self._build_service)
        return self

    async def __aexit__(self, *args):
        self._service = None

    def _build_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _fmt_time(self, iso_str: str) -> str:
        """Format ISO datetime string to local time like '1:00 PM'."""
        tz = zoneinfo.ZoneInfo(os.getenv("TZ", "America/Los_Angeles"))
        dt = datetime.fromisoformat(iso_str).astimezone(tz)
        return dt.strftime("%I:%M %p").lstrip("0")

    def _list_calendar_ids(self) -> list[str]:
        """Return IDs of all calendars the user has access to."""
        result = self._service.calendarList().list().execute()
        return [c["id"] for c in result.get("items", [])]

    async def get_events(self, date_iso: Optional[str] = None) -> list[dict]:
        """Get events across all calendars for a given date (defaults to today)."""
        target = date_iso or date.today().isoformat()
        tz = zoneinfo.ZoneInfo(os.getenv("TZ", "America/Los_Angeles"))
        target_dt = date.fromisoformat(target)
        time_min = datetime(target_dt.year, target_dt.month, target_dt.day, 0, 0, 0, tzinfo=tz).isoformat()
        time_max = datetime(target_dt.year, target_dt.month, target_dt.day, 23, 59, 59, tzinfo=tz).isoformat()
        loop = asyncio.get_event_loop()

        calendar_ids = await loop.run_in_executor(None, self._list_calendar_ids)

        events = []
        for cal_id in calendar_ids:
            result = await loop.run_in_executor(
                None,
                lambda cid=cal_id: self._service.events()
                .list(
                    calendarId=cid,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute(),
            )
            for e in result.get("items", []):
                is_all_day = "date" in e["start"] and "dateTime" not in e["start"]
                events.append({
                    "summary": e.get("summary", "Untitled"),
                    "start": self._fmt_time(e["start"]["dateTime"]) if not is_all_day else "All day",
                    "end": self._fmt_time(e["end"]["dateTime"]) if not is_all_day else "",
                    "start_iso": e["start"].get("dateTime", e["start"].get("date", "")),
                    "is_all_day": is_all_day,
                    "id": e["id"],
                })

        # Sort all events by start time, all-day first
        events.sort(key=lambda e: (0 if e["is_all_day"] else 1, e["start_iso"]))
        # Drop the sort key field
        for e in events:
            del e["start_iso"]
        return events

    async def create_event(
        self, summary: str, start: str, end: str, description: str = ""
    ) -> dict:
        """Create a calendar event. start/end are ISO datetime strings."""
        tz = os.getenv("TZ", "America/Los_Angeles")
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz},
        }
        loop = asyncio.get_event_loop()
        event = await loop.run_in_executor(
            None,
            lambda: self._service.events()
            .insert(calendarId=self.calendar_id, body=body)
            .execute(),
        )
        return {
            "event_id": event["id"],
            "summary": event["summary"],
            "url": event.get("htmlLink", ""),
        }
