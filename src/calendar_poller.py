"""iCal calendar polling and checkout event detection."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Set

import httpx
import pytz
from icalendar import Calendar

logger = logging.getLogger(__name__)


@dataclass
class CheckoutEvent:
    """Represents a checkout event from the calendar."""

    reservation_id: str
    event_start: datetime
    event_end: datetime
    property_name: str
    guest_name: str
    summary: str
    description: str
    has_trigger_keyword: bool

    def __hash__(self):
        return hash(self.reservation_id)

    def __eq__(self, other):
        if isinstance(other, CheckoutEvent):
            return self.reservation_id == other.reservation_id
        return False


class CalendarPoller:
    """Polls iCal feed and detects checkout events."""

    def __init__(self, ical_url: str, trigger_keyword: str = "TURN_OFF_THERMOSTATS"):
        self.ical_url = ical_url.replace("webcal://", "https://")
        self.trigger_keyword = trigger_keyword
        self._processed_events: Set[str] = set()
        self._processed_timestamps: dict = {}  # reservation_id -> timestamp

    def _parse_reservation_id(self, description: str) -> Optional[str]:
        """Extract reservation ID from event description.

        Looks for pattern like 'Reservation: HMFW5EYFCS'
        """
        match = re.search(r"Reservation:\s*([A-Z0-9]+)", description, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _parse_property_name(self, description: str) -> str:
        """Extract property name from event description."""
        match = re.search(r"Property:\s*(.+?)(?:\n|$)", description)
        if match:
            return match.group(1).strip()
        return "Unknown Property"

    def _parse_guest_name(self, description: str) -> str:
        """Extract guest name from event description."""
        match = re.search(r"Guest name:\s*(.+?)(?:\n|$)", description)
        if match:
            return match.group(1).strip()
        return "Unknown Guest"

    def _ensure_timezone_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is timezone-aware (default to UTC if naive)."""
        if dt.tzinfo is None:
            return pytz.UTC.localize(dt)
        return dt

    async def fetch_calendar(self) -> Optional[Calendar]:
        """Fetch and parse the iCal feed.

        Returns:
            Parsed Calendar object or None if fetch failed.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.ical_url)
                response.raise_for_status()
                return Calendar.from_ical(response.text)
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch calendar: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to parse calendar: {e}")
            return None

    def parse_events(
        self,
        calendar: Calendar,
        buffer_minutes: int = 30,
    ) -> List[CheckoutEvent]:
        """Parse calendar and find checkout events that need action.

        Args:
            calendar: Parsed iCal Calendar object.
            buffer_minutes: Minutes after event start to still consider it active.

        Returns:
            List of checkout events that should trigger action.
        """
        now = datetime.now(pytz.UTC)
        buffer_start = now - timedelta(minutes=buffer_minutes)
        events = []

        for component in calendar.walk():
            if component.name != "VEVENT":
                continue

            try:
                summary = str(component.get("summary", ""))
                description = str(component.get("description", ""))

                # Get event times
                dtstart = component.get("dtstart")
                dtend = component.get("dtend")

                if not dtstart:
                    continue

                event_start = self._ensure_timezone_aware(dtstart.dt)
                event_end = (
                    self._ensure_timezone_aware(dtend.dt)
                    if dtend
                    else event_start + timedelta(hours=1)
                )

                # Handle all-day events (date instead of datetime)
                if not isinstance(event_start, datetime):
                    event_start = datetime.combine(
                        event_start, datetime.min.time(), tzinfo=pytz.UTC
                    )
                if not isinstance(event_end, datetime):
                    event_end = datetime.combine(
                        event_end, datetime.min.time(), tzinfo=pytz.UTC
                    )

                # Check if this is a checkout event (within our time window)
                # Event should have started within buffer_minutes or be currently happening
                is_in_window = buffer_start <= event_start <= now
                is_happening_now = event_start <= now <= event_end

                if not (is_in_window or is_happening_now):
                    continue

                # Parse event details
                reservation_id = self._parse_reservation_id(description)
                if not reservation_id:
                    # Generate a fallback ID from summary and start time
                    reservation_id = f"{summary[:20]}_{event_start.isoformat()}"

                # Check for trigger keyword
                has_trigger = self.trigger_keyword.upper() in description.upper()

                # Check if this is a checkout event (by summary or trigger keyword)
                is_checkout = "check-out" in summary.lower() or "checkout" in summary.lower()

                if not (is_checkout or has_trigger):
                    continue

                event = CheckoutEvent(
                    reservation_id=reservation_id,
                    event_start=event_start,
                    event_end=event_end,
                    property_name=self._parse_property_name(description),
                    guest_name=self._parse_guest_name(description),
                    summary=summary,
                    description=description,
                    has_trigger_keyword=has_trigger,
                )
                events.append(event)

            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue

        return events

    def filter_unprocessed(self, events: List[CheckoutEvent]) -> List[CheckoutEvent]:
        """Filter out events that have already been processed.

        Args:
            events: List of checkout events.

        Returns:
            List of events that haven't been processed yet.
        """
        unprocessed = []
        for event in events:
            if event.reservation_id not in self._processed_events:
                unprocessed.append(event)
        return unprocessed

    def mark_processed(self, event: CheckoutEvent) -> None:
        """Mark an event as processed.

        Args:
            event: The checkout event that was processed.
        """
        self._processed_events.add(event.reservation_id)
        self._processed_timestamps[event.reservation_id] = datetime.now(pytz.UTC)
        logger.info(f"Marked event {event.reservation_id} as processed")

    def cleanup_old_processed(self, max_age_hours: int = 24) -> None:
        """Remove old entries from the processed set.

        Args:
            max_age_hours: Remove entries older than this many hours.
        """
        cutoff = datetime.now(pytz.UTC) - timedelta(hours=max_age_hours)
        to_remove = []

        for res_id, timestamp in self._processed_timestamps.items():
            if timestamp < cutoff:
                to_remove.append(res_id)

        for res_id in to_remove:
            self._processed_events.discard(res_id)
            del self._processed_timestamps[res_id]

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old processed events")

    async def get_actionable_checkouts(
        self,
        buffer_minutes: int = 30,
    ) -> List[CheckoutEvent]:
        """Fetch calendar and return checkout events needing action.

        This is the main method to call from the scheduler.

        Args:
            buffer_minutes: Minutes after event start to still consider it active.

        Returns:
            List of unprocessed checkout events with trigger keyword.
        """
        # Cleanup old processed events
        self.cleanup_old_processed()

        # Fetch calendar
        calendar = await self.fetch_calendar()
        if not calendar:
            logger.warning("Could not fetch calendar, skipping this poll")
            return []

        # Parse and filter events
        events = self.parse_events(calendar, buffer_minutes)
        logger.info(f"Found {len(events)} checkout events in time window")

        # Filter to only events with trigger keyword
        triggered_events = [e for e in events if e.has_trigger_keyword]
        logger.info(f"Found {len(triggered_events)} events with trigger keyword")

        # Filter out already processed
        unprocessed = self.filter_unprocessed(triggered_events)
        logger.info(f"Found {len(unprocessed)} unprocessed events")

        return unprocessed
