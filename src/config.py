"""Configuration management using Pydantic Settings."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # iCal Configuration
    ical_url: str = Field(
        ...,
        description="Hospitable checkout calendar iCal URL"
    )

    # Google OAuth Configuration
    google_client_id: str = Field(
        ...,
        description="Google OAuth Client ID"
    )
    google_client_secret: str = Field(
        ...,
        description="Google OAuth Client Secret"
    )
    google_refresh_token: str = Field(
        ...,
        description="Google OAuth Refresh Token"
    )

    # Nest/SDM Configuration
    nest_project_id: str = Field(
        ...,
        description="Google Device Access Project ID"
    )
    nest_device_ids: str = Field(
        default="",
        description="Comma-separated list of Nest thermostat device IDs to control"
    )

    # Polling Configuration
    poll_interval_minutes: int = Field(
        default=10,
        description="How often to poll the calendar (minutes)"
    )
    checkout_buffer_minutes: int = Field(
        default=30,
        description="Minutes after checkout start time to still trigger action"
    )

    # Trigger Configuration
    trigger_keyword: str = Field(
        default="TURN_OFF_THERMOSTATS",
        description="Keyword in event description to trigger thermostat off"
    )

    # Server Configuration
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    log_level: str = Field(default="INFO")

    # Email Notification Configuration
    smtp_enabled: bool = Field(
        default=False,
        description="Enable email notifications"
    )
    smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname"
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port (587 for TLS, 465 for SSL)"
    )
    smtp_username: str = Field(
        default="",
        description="SMTP username (email address)"
    )
    smtp_password: str = Field(
        default="",
        description="SMTP password (app password for Gmail)"
    )
    smtp_from_email: str = Field(
        default="",
        description="From email address (defaults to smtp_username)"
    )
    smtp_to_email: str = Field(
        default="",
        description="Recipient email address for notifications"
    )

    # Scheduled ECO mode configuration
    eco_schedule_enabled: bool = Field(
        default=False,
        description="Enable scheduled ECO mode at fixed daily times"
    )
    eco_daytime_hour: int = Field(
        default=11,
        description="Hour (0-23, local time) to set ECO mode during the day"
    )
    eco_nighttime_hour: int = Field(
        default=23,
        description="Hour (0-23, local time) to set ECO mode at night"
    )
    eco_timezone: str = Field(
        default="America/Los_Angeles",
        description="Timezone for ECO schedule (IANA tz name)"
    )

    @property
    def device_ids_list(self) -> List[str]:
        """Parse comma-separated device IDs into a list."""
        if not self.nest_device_ids:
            return []
        return [d.strip() for d in self.nest_device_ids.split(",") if d.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
