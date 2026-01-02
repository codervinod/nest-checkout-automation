"""Email notification service for thermostat events."""

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Optional

from .config import settings

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send email notifications for thermostat events."""

    def __init__(self):
        self.enabled = settings.smtp_enabled
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.from_email = settings.smtp_from_email or settings.smtp_username
        self.to_email = settings.smtp_to_email

    def is_configured(self) -> bool:
        """Check if email notifications are properly configured."""
        if not self.enabled:
            return False
        return bool(
            self.host
            and self.port
            and self.username
            and self.password
            and self.to_email
        )

    async def send_thermostat_notification(
        self,
        property_name: str,
        guest_name: str,
        reservation_id: str,
        thermostat_results: Dict[str, bool],
        event_time: Optional[datetime] = None,
    ) -> bool:
        """Send notification about thermostats being turned off.

        Args:
            property_name: Name of the property
            guest_name: Name of the guest checking out
            reservation_id: Reservation identifier
            thermostat_results: Dict mapping device name to success status
            event_time: Time of the checkout event

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.debug("Email notifications not configured, skipping")
            return False

        success_count = sum(1 for v in thermostat_results.values() if v)
        fail_count = len(thermostat_results) - success_count
        all_success = fail_count == 0

        # Build subject
        if all_success:
            subject = f"Thermostats Turned Off - {property_name}"
        else:
            subject = f"Thermostat Warning - {property_name}"

        # Build body
        event_time_str = (
            event_time.strftime("%Y-%m-%d %I:%M %p %Z")
            if event_time
            else datetime.now().strftime("%Y-%m-%d %I:%M %p")
        )

        thermostat_lines = []
        for name, success in thermostat_results.items():
            status = "OFF" if success else "FAILED"
            thermostat_lines.append(f"  - {name}: {status}")

        body_text = f"""Checkout detected at {property_name}

Guest: {guest_name}
Reservation: {reservation_id}
Time: {event_time_str}

Thermostat Status:
{chr(10).join(thermostat_lines)}

Summary: {success_count} turned off, {fail_count} failed
"""

        body_html = f"""
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px;">
    <h2 style="color: {'#28a745' if all_success else '#dc3545'};">
        {'Thermostats Turned Off' if all_success else 'Thermostat Warning'}
    </h2>

    <p><strong>Property:</strong> {property_name}</p>
    <p><strong>Guest:</strong> {guest_name}</p>
    <p><strong>Reservation:</strong> {reservation_id}</p>
    <p><strong>Time:</strong> {event_time_str}</p>

    <h3>Thermostat Status:</h3>
    <ul>
        {"".join(f'<li style="color: {"#28a745" if success else "#dc3545"};">{name}: {"OFF" if success else "FAILED"}</li>' for name, success in thermostat_results.items())}
    </ul>

    <p style="color: #666; font-size: 12px; margin-top: 30px;">
        Sent by Nest Checkout Automation
    </p>
</body>
</html>
"""

        return await self._send_email(subject, body_text, body_html)

    async def _send_email(
        self, subject: str, body_text: str, body_html: Optional[str] = None
    ) -> bool:
        """Send an email via SMTP.

        Args:
            subject: Email subject
            body_text: Plain text body
            body_html: Optional HTML body

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = self.to_email

            msg.attach(MIMEText(body_text, "plain"))
            if body_html:
                msg.attach(MIMEText(body_html, "html"))

            context = ssl.create_default_context()

            if self.port == 465:
                # SSL
                with smtplib.SMTP_SSL(
                    self.host, self.port, context=context
                ) as server:
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, self.to_email, msg.as_string())
            else:
                # TLS (port 587)
                with smtplib.SMTP(self.host, self.port) as server:
                    server.starttls(context=context)
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, self.to_email, msg.as_string())

            logger.info(f"Email notification sent to {self.to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False


# Global notifier instance
notifier = EmailNotifier()
