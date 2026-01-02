"""Main application - FastAPI server with APScheduler for calendar polling."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .auth import TokenManager
from .calendar_poller import CalendarPoller, CheckoutEvent
from .config import settings
from .nest_controller import NestController
from .notifier import notifier

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Global state
scheduler: Optional[AsyncIOScheduler] = None
calendar_poller: Optional[CalendarPoller] = None
nest_controller: Optional[NestController] = None
last_poll_time: Optional[datetime] = None
last_action_time: Optional[datetime] = None
last_action_result: Optional[dict] = None


async def process_checkout_event(event: CheckoutEvent) -> dict:
    """Process a single checkout event - turn off thermostats.

    Args:
        event: The checkout event to process.

    Returns:
        Dictionary with results.
    """
    global last_action_time, last_action_result

    logger.info(f"Processing checkout event: {event.reservation_id}")
    logger.info(f"  Property: {event.property_name}")
    logger.info(f"  Guest: {event.guest_name}")
    logger.info(f"  Event time: {event.event_start}")

    # Get all devices to build ID -> name mapping
    devices = await nest_controller.list_devices()
    device_id_to_name = {d.device_id: d.display_name for d in devices}

    device_ids = settings.device_ids_list

    if not device_ids:
        # If no specific devices configured, try to turn off all discovered thermostats
        logger.warning("No specific device IDs configured, discovering all thermostats...")
        device_ids = [d.device_id for d in devices]

    if not device_ids:
        logger.error("No thermostats found to turn off!")
        return {"success": False, "error": "No thermostats found"}

    logger.info(f"Turning off {len(device_ids)} thermostat(s)...")
    results = await nest_controller.turn_off_thermostats(device_ids)

    # Log results
    success_count = sum(1 for v in results.values() if v)
    fail_count = len(results) - success_count

    if fail_count == 0:
        logger.info(f"Successfully turned off all {success_count} thermostat(s)")
    else:
        logger.warning(f"Turned off {success_count} thermostat(s), {fail_count} failed")

    # Mark event as processed
    calendar_poller.mark_processed(event)

    last_action_time = datetime.now(pytz.UTC)
    last_action_result = {
        "reservation_id": event.reservation_id,
        "property": event.property_name,
        "thermostats_off": success_count,
        "thermostats_failed": fail_count,
        "results": results,
    }

    # Send email notification
    if notifier.is_configured():
        # Convert device IDs to names for the notification
        named_results = {
            device_id_to_name.get(device_id, device_id): success
            for device_id, success in results.items()
        }
        try:
            await notifier.send_thermostat_notification(
                property_name=event.property_name,
                guest_name=event.guest_name,
                reservation_id=event.reservation_id,
                thermostat_results=named_results,
                event_time=event.event_start,
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    return last_action_result


async def poll_calendar_job():
    """Scheduled job to poll calendar and process checkout events."""
    global last_poll_time

    logger.info("Running calendar poll job...")
    last_poll_time = datetime.now(pytz.UTC)

    try:
        # Get actionable checkout events
        events = await calendar_poller.get_actionable_checkouts(
            buffer_minutes=settings.checkout_buffer_minutes
        )

        if not events:
            logger.info("No checkout events requiring action")
            return

        # Process each event
        for event in events:
            try:
                await process_checkout_event(event)
            except Exception as e:
                logger.error(f"Failed to process event {event.reservation_id}: {e}")

    except Exception as e:
        logger.error(f"Calendar poll job failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    global scheduler, calendar_poller, nest_controller

    logger.info("Starting Nest Checkout Automation Service...")
    logger.info(f"Poll interval: {settings.poll_interval_minutes} minutes")
    logger.info(f"Checkout buffer: {settings.checkout_buffer_minutes} minutes")
    logger.info(f"Trigger keyword: {settings.trigger_keyword}")

    # Initialize components
    token_manager = TokenManager(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        refresh_token=settings.google_refresh_token,
    )

    calendar_poller = CalendarPoller(
        ical_url=settings.ical_url,
        trigger_keyword=settings.trigger_keyword,
    )

    nest_controller = NestController(
        project_id=settings.nest_project_id,
        token_manager=token_manager,
    )

    # Discover and log available thermostats on startup
    try:
        await nest_controller.discover_and_log_devices()
    except Exception as e:
        logger.error(f"Failed to discover devices on startup: {e}")

    # Initialize scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_calendar_job,
        trigger=IntervalTrigger(minutes=settings.poll_interval_minutes),
        id="calendar_poll",
        name="Poll calendar for checkout events",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")

    # Run initial poll
    logger.info("Running initial calendar poll...")
    await poll_calendar_job()

    yield

    # Shutdown
    logger.info("Shutting down...")
    if scheduler:
        scheduler.shutdown(wait=False)
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Nest Checkout Automation",
    description="Automatically turns off Nest thermostats on guest checkout",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint for Kubernetes probes."""
    return {"status": "healthy"}


@app.get("/status")
async def get_status():
    """Get detailed service status."""
    scheduler_running = scheduler is not None and scheduler.running if scheduler else False

    # Get next scheduled run
    next_run = None
    if scheduler and scheduler.running:
        job = scheduler.get_job("calendar_poll")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

    # Get token expiry
    token_expiry = None
    if nest_controller and nest_controller.token_manager:
        expiry = nest_controller.token_manager.token_expiry
        if expiry:
            token_expiry = expiry.isoformat()

    return {
        "status": "running" if scheduler_running else "stopped",
        "scheduler_running": scheduler_running,
        "last_poll_time": last_poll_time.isoformat() if last_poll_time else None,
        "next_poll_time": next_run,
        "last_action_time": last_action_time.isoformat() if last_action_time else None,
        "last_action_result": last_action_result,
        "token_expiry": token_expiry,
        "config": {
            "poll_interval_minutes": settings.poll_interval_minutes,
            "checkout_buffer_minutes": settings.checkout_buffer_minutes,
            "trigger_keyword": settings.trigger_keyword,
            "configured_device_ids": settings.device_ids_list,
        },
    }


@app.post("/poll")
async def trigger_poll():
    """Manually trigger a calendar poll."""
    logger.info("Manual poll triggered via API")
    await poll_calendar_job()
    return {
        "message": "Poll completed",
        "last_poll_time": last_poll_time.isoformat() if last_poll_time else None,
    }


@app.get("/devices")
async def list_devices():
    """List all discovered Nest thermostats."""
    if not nest_controller:
        return JSONResponse(
            status_code=503, content={"error": "Service not initialized"}
        )

    try:
        devices = await nest_controller.list_devices(force_refresh=True)
        return {
            "devices": [
                {
                    "device_id": d.device_id,
                    "name": d.display_name,
                    "mode": d.current_mode,
                    "temperature_celsius": d.ambient_temperature_celsius,
                    "humidity_percent": d.humidity_percent,
                }
                for d in devices
            ]
        }
    except Exception as e:
        logger.error(f"Failed to list devices: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/devices/{device_id}/off")
async def turn_off_device(device_id: str):
    """Manually turn off a specific thermostat."""
    if not nest_controller:
        return JSONResponse(
            status_code=503, content={"error": "Service not initialized"}
        )

    try:
        success = await nest_controller.turn_off_thermostat(device_id)
        return {"device_id": device_id, "success": success, "mode": "OFF"}
    except Exception as e:
        logger.error(f"Failed to turn off device {device_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/test-notification")
async def test_notification():
    """Send a test email notification without turning off thermostats."""
    if not notifier.is_configured():
        return JSONResponse(
            status_code=400,
            content={"error": "Email notifications not configured. Set SMTP_ENABLED=true and provide SMTP credentials."}
        )

    # Get thermostat names for realistic test data
    devices = await nest_controller.list_devices() if nest_controller else []
    test_results = {d.display_name: True for d in devices} or {"Test Thermostat": True}

    try:
        success = await notifier.send_thermostat_notification(
            property_name="Test Property",
            guest_name="Test Guest",
            reservation_id="TEST-123",
            thermostat_results=test_results,
            event_time=datetime.now(pytz.UTC),
        )
        if success:
            return {"message": "Test notification sent successfully", "recipients": notifier.to_emails}
        else:
            return JSONResponse(
                status_code=500,
                content={"error": "Failed to send notification - check logs for details"}
            )
    except Exception as e:
        logger.error(f"Failed to send test notification: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


def main():
    """Run the application."""
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
