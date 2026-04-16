"""Tests for config module — timezone correctness."""
import unittest
from datetime import datetime, time as dt_time, timezone


class TestMarketTimezone(unittest.TestCase):
    """MARKET_TZ must produce correct UTC offsets, not pytz LMT."""

    def test_market_tz_is_zoneinfo(self):
        from zoneinfo import ZoneInfo
        from config import MARKET_TZ

        self.assertIsInstance(MARKET_TZ, ZoneInfo)

    def test_utc_offset_est(self):
        """During standard time (e.g. January), offset should be -5:00."""
        from config import MARKET_TZ

        winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).astimezone(MARKET_TZ)
        offset_hours = winter.utcoffset().total_seconds() / 3600
        self.assertEqual(offset_hours, -5.0)

    def test_utc_offset_edt(self):
        """During daylight saving (e.g. July), offset should be -4:00."""
        from config import MARKET_TZ

        summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc).astimezone(MARKET_TZ)
        offset_hours = summer.utcoffset().total_seconds() / 3600
        self.assertEqual(offset_hours, -4.0)

    def test_eod_time_produces_correct_utc_offset_via_combine(self):
        """datetime.combine with the scheduled time must give correct UTC offset.

        This replicates what discord.py's tasks.loop does internally.
        pytz gives LMT (-4:56:02) instead of EDT (-4:00), causing the
        task to fire at the wrong UTC time.
        """
        from config import MARKET_TZ

        eod = dt_time(hour=16, minute=5, tzinfo=MARKET_TZ)
        # March 26 2026 is EDT
        dt = datetime.combine(datetime(2026, 3, 26), eod)
        offset_hours = dt.utcoffset().total_seconds() / 3600
        self.assertEqual(offset_hours, -4.0,
                         f"Expected EDT offset -4h, got {offset_hours}h — likely pytz LMT bug")


if __name__ == "__main__":
    unittest.main()
