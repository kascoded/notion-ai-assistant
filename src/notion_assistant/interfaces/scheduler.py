"""
Proactive check-in scheduler for Telegram bot.

Sends scheduled messages (morning brief, evening habit nudge, weekly review)
that flow through the existing NL pipeline when the user replies.
"""
import datetime
import logging
import os
import zoneinfo

logger = logging.getLogger(__name__)

MORNING_HOUR = int(os.getenv("MORNING_CHECKIN_HOUR", "8"))
EVENING_HOUR = int(os.getenv("EVENING_CHECKIN_HOUR", "21"))
TZ_NAME = os.getenv("TZ", "America/New_York")

MORNING_MSG = (
    "Good morning! What are you working on today?\n\n"
    "Reply with anything to log — habits from yesterday, tasks, expenses, "
    "or just what's on your mind."
)

EVENING_MSG = (
    "End of day check-in.\n\n"
    "<b>Habits today:</b> Did you sleep, eat well, run, workout, stretch, "
    "read, draw, or journal?\n\n"
    "Reply to log any you want to capture. "
    "Example: <code>workout done, read done</code>"
)

WEEKLY_MSG = (
    "Weekly check-in.\n\n"
    "Reply <code>weekly summary</code> for your full report, or log anything "
    "you want to wrap up the week."
)


class ProactiveScheduler:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id

    def register(self, job_queue) -> None:
        tz = zoneinfo.ZoneInfo(TZ_NAME)
        job_queue.run_daily(
            self._morning,
            time=datetime.time(hour=MORNING_HOUR, tzinfo=tz),
            name="morning_checkin",
        )
        job_queue.run_daily(
            self._evening,
            time=datetime.time(hour=EVENING_HOUR, tzinfo=tz),
            name="evening_checkin",
        )
        job_queue.run_daily(
            self._weekly,
            time=datetime.time(hour=17, tzinfo=tz),
            days=(4,),  # Friday
            name="weekly_review",
        )
        logger.info(
            "Scheduled jobs registered: morning=%dh, evening=%dh, weekly=Fri 17h (tz=%s)",
            MORNING_HOUR,
            EVENING_HOUR,
            TZ_NAME,
        )

    async def _morning(self, context) -> None:
        await context.bot.send_message(
            chat_id=self.chat_id, text=MORNING_MSG, parse_mode="HTML"
        )

    async def _evening(self, context) -> None:
        await context.bot.send_message(
            chat_id=self.chat_id, text=EVENING_MSG, parse_mode="HTML"
        )

    async def _weekly(self, context) -> None:
        await context.bot.send_message(
            chat_id=self.chat_id, text=WEEKLY_MSG, parse_mode="HTML"
        )
