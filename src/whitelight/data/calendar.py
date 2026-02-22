"""Market calendar utilities wrapping the ``exchange-calendars`` library."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

logger = logging.getLogger(__name__)

# NYSE / NASDAQ regular session close is 16:00 Eastern.
_ET = ZoneInfo("America/New_York")

# The exchange-calendars identifier for the NYSE.
_CALENDAR_NAME = "XNYS"


class MarketCalendar:
    """Convenience wrapper around ``exchange_calendars`` for NYSE/NASDAQ schedules.

    All public methods accept and return plain ``datetime.date`` /
    ``datetime.datetime`` objects unless stated otherwise.
    """

    def __init__(self) -> None:
        # exchange_calendars needs explicit bounds.  We pick a wide range.
        self._cal = xcals.get_calendar(_CALENDAR_NAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_trading_day(self, d: date) -> bool:
        """Return ``True`` if *d* is a regular NYSE trading session."""
        ts = pd.Timestamp(d)
        return self._cal.is_session(ts)

    def next_trading_day(self, d: Optional[date] = None) -> date:
        """Return the next trading day strictly after *d* (defaults to today)."""
        d = d or date.today()
        ts = pd.Timestamp(d)
        # If d is itself a session, the *next* session is what we want.
        nxt = self._cal.next_session(ts)
        return nxt.date()

    def previous_trading_day(self, d: Optional[date] = None) -> date:
        """Return the most recent trading day strictly before *d* (defaults to today)."""
        d = d or date.today()
        ts = pd.Timestamp(d)
        prev = self._cal.previous_session(ts)
        return prev.date()

    def minutes_to_close(self) -> int:
        """Return the number of minutes until the next market close.

        If the market is currently closed the value will be the number of
        minutes until the close of the *next* regular session.  Always
        returns a non-negative integer.
        """
        now_et = datetime.now(tz=_ET)
        close_dt = self.next_close()
        delta = close_dt - now_et
        minutes = int(delta.total_seconds() // 60)
        return max(minutes, 0)

    def is_within_execution_window(
        self,
        start_minutes_before_close: int = 15,
        end_minutes_before_close: int = 1,
    ) -> bool:
        """Return ``True`` when the current time falls inside the execution window.

        The window spans from *start_minutes_before_close* to
        *end_minutes_before_close* before the close of the current trading
        session.  Outside of trading hours this always returns ``False``.
        """
        now_et = datetime.now(tz=_ET)
        today = now_et.date()

        if not self.is_trading_day(today):
            return False

        close_dt = self._session_close(today)
        if close_dt is None:
            return False

        window_open = close_dt - timedelta(minutes=start_minutes_before_close)
        window_close = close_dt - timedelta(minutes=end_minutes_before_close)

        return window_open <= now_et <= window_close

    def next_close(self) -> datetime:
        """Return the ``datetime`` of the next market close (Eastern time).

        If the market is currently in session and has not yet closed, this
        returns *today's* close.  Otherwise it returns the close of the next
        trading session.
        """
        now_et = datetime.now(tz=_ET)
        today = now_et.date()

        # If today is a session and we haven't passed the close yet, use it.
        if self.is_trading_day(today):
            close_dt = self._session_close(today)
            if close_dt is not None and now_et < close_dt:
                return close_dt

        # Otherwise look ahead.
        nxt = self.next_trading_day(today)
        close_dt = self._session_close(nxt)
        if close_dt is not None:
            return close_dt

        # Defensive fallback: shouldn't happen.
        logger.warning("Could not determine next close; falling back to 16:00 ET tomorrow")
        tomorrow = today + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 16, 0, tzinfo=_ET)

    def trading_days_between(self, start: date, end: date) -> list[date]:
        """Return a list of trading days in the closed interval [start, end]."""
        sessions = self._cal.sessions_in_range(
            pd.Timestamp(start),
            pd.Timestamp(end),
        )
        return [s.date() for s in sessions]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _session_close(self, d: date) -> Optional[datetime]:
        """Return the close time for *d* as an aware ``datetime`` in Eastern time.

        Returns ``None`` if *d* is not a trading session.
        """
        if not self.is_trading_day(d):
            return None
        ts = pd.Timestamp(d)
        close_ts = self._cal.session_close(ts)
        # exchange_calendars returns a UTC Timestamp.
        return close_ts.to_pydatetime().astimezone(_ET)
