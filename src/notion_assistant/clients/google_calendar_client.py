"""
Async Google Calendar client.
Wraps the sync Google API client in a thread executor.
"""
import asyncio
import logging
import os
import zoneinfo
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TZ_NAME = os.getenv("TZ", "America/Los_Angeles")


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
        loop = asyncio.get_running_loop()
        try:
            self._service = await loop.run_in_executor(None, self._build_service)
        except Exception as exc:
            raise RuntimeError(f"Failed to connect to Google Calendar: {exc}") from exc
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
        tz = zoneinfo.ZoneInfo(TZ_NAME)
        dt = datetime.fromisoformat(iso_str).astimezone(tz)
        return dt.strftime("%I:%M %p").lstrip("0")

    def _list_calendar_ids(self) -> list[str]:
        """Return IDs of all calendars the user has access to."""
        result = self._service.calendarList().list().execute()
        return [c["id"] for c in result.get("items", [])]

    async def get_current_and_next(self) -> dict:
        """Return the event happening right now and the next upcoming event today."""
        tz = zoneinfo.ZoneInfo(TZ_NAME)
        now = datetime.now(tz=tz)
        # Look back 4 hours to catch events that started before now but are still running
        window_start = now - timedelta(hours=4)
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=tz)
        loop = asyncio.get_running_loop()

        try:
            calendar_ids = await loop.run_in_executor(None, self._list_calendar_ids)
        except Exception as exc:
            raise RuntimeError(f"Google Calendar auth failed: {exc}") from exc

        all_events = []
        for cal_id in calendar_ids:
            result = await loop.run_in_executor(
                None,
                lambda cid=cal_id: self._service.events()
                .list(
                    calendarId=cid,
                    timeMin=window_start.isoformat(),
                    timeMax=end_of_day.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=20,
                )
                .execute(),
            )
            for e in result.get("items", []):
                if "dateTime" not in e["start"]:
                    continue  # skip all-day events
                start_dt = datetime.fromisoformat(e["start"]["dateTime"]).astimezone(tz)
                end_dt = datetime.fromisoformat(e["end"]["dateTime"]).astimezone(tz)
                all_events.append({
                    "summary": e.get("summary", "Untitled"),
                    "start": self._fmt_time(e["start"]["dateTime"]),
                    "end": self._fmt_time(e["end"]["dateTime"]),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                })

        all_events.sort(key=lambda e: e["start_dt"])

        current = next((e for e in all_events if e["start_dt"] <= now <= e["end_dt"]), None)
        upcoming = next((e for e in all_events if e["start_dt"] > now), None)

        def clean(e):
            if e is None:
                return None
            return {k: v for k, v in e.items() if k not in ("start_dt", "end_dt")}

        return {"current": clean(current), "next": clean(upcoming)}

    async def get_events(self, date_iso: Optional[str] = None) -> list[dict]:
        """Get events across all calendars for a given date (defaults to today)."""
        target = date_iso or date.today().isoformat()
        tz = zoneinfo.ZoneInfo(TZ_NAME)
        target_dt = date.fromisoformat(target)
        time_min = datetime(target_dt.year, target_dt.month, target_dt.day, 0, 0, 0, tzinfo=tz).isoformat()
        time_max = datetime(target_dt.year, target_dt.month, target_dt.day, 23, 59, 59, tzinfo=tz).isoformat()
        loop = asyncio.get_running_loop()

        try:
            calendar_ids = await loop.run_in_executor(None, self._list_calendar_ids)
        except Exception as exc:
            raise RuntimeError(f"Google Calendar auth failed: {exc}") from exc

        raw_events = []
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
                is_all_day = "dateTime" not in e["start"]
                sort_key = e["start"].get("dateTime", e["start"].get("date", ""))
                raw_events.append({
                    "summary": e.get("summary", "Untitled"),
                    "start": self._fmt_time(e["start"]["dateTime"]) if not is_all_day else "All day",
                    "end": self._fmt_time(e["end"]["dateTime"]) if not is_all_day else "",
                    "is_all_day": is_all_day,
                    "sort_key": sort_key,
                })

        # All-day events first, then timed events sorted by start
        raw_events.sort(key=lambda e: (0 if e["is_all_day"] else 1, e["sort_key"]))
        return [{k: v for k, v in e.items() if k != "sort_key"} for e in raw_events]

    async def create_event(
        self, summary: str, start: str, end: str, description: str = ""
    ) -> dict:
        """Create a calendar event. start/end are ISO datetime strings (naive or offset-aware)."""
        tz_name = TZ_NAME
        # Default end to start + 1 hour if identical or missing
        if not end or end == start:
            try:
                start_dt = datetime.fromisoformat(start)
                end = (start_dt + timedelta(hours=1)).isoformat()
            except ValueError:
                end = start

        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": tz_name},
            "end": {"dateTime": end, "timeZone": tz_name},
        }
        loop = asyncio.get_running_loop()
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
