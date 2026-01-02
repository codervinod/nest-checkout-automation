# Claude Code Instructions for nest-checkout-automation

## Project Overview

This is a Python microservice that automatically turns off Nest thermostats when guests check out, triggered by Hospitable iCal calendar events.

**Key Components:**
- `src/main.py` - FastAPI app with APScheduler for polling
- `src/calendar_poller.py` - iCal parsing and checkout detection
- `src/nest_controller.py` - Google SDM API integration
- `src/auth.py` - OAuth token management
- `src/config.py` - Pydantic settings

## Git Workflow

**CRITICAL: Follow these rules:**

1. **Never push directly to main** - Always create feature branches and PRs
2. **Branch naming**: `feature/GH-<issue>-<description>` or `fix/GH-<issue>-<description>`
3. **Use git worktrees** for isolation when working on issues

```bash
# Create worktree for an issue
git worktree add ../nest-checkout-automation-<issue> -b feature/GH-<issue>-<desc> origin/main

# When done
git worktree remove ../nest-checkout-automation-<issue>
```

## Local Development

### Prerequisites
- Python 3.11+ (not 3.14 - pydantic-core doesn't have wheels yet)
- Google Cloud project with SDM API enabled
- Device Access registration ($5 one-time)
- OAuth refresh token (run `scripts/get_oauth_token.py`)

### Setup
```bash
# Create virtual environment with Python 3.11
/opt/homebrew/bin/python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill in credentials
cp .env.example .env
# Edit .env with your values
```

### Running Locally
```bash
source venv/bin/activate
python -m uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

### Testing Calendar Parsing
```bash
source venv/bin/activate
python3 -c "
import httpx
from icalendar import Calendar

url = 'YOUR_ICAL_URL'
response = httpx.get(url, timeout=30)
cal = Calendar.from_ical(response.text)

for component in cal.walk():
    if component.name == 'VEVENT':
        print(component.get('summary'))
        print(component.get('dtstart').dt)
        print(component.get('description'))
        print('-' * 40)
"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check for K8s probes |
| `/status` | GET | Detailed service status |
| `/poll` | POST | Manually trigger calendar poll |
| `/devices` | GET | List discovered thermostats |
| `/devices/{id}/off` | POST | Manually turn off a thermostat |

## Environment Variables

**Required (secrets):**
- `GOOGLE_CLIENT_ID` - OAuth client ID
- `GOOGLE_CLIENT_SECRET` - OAuth client secret
- `GOOGLE_REFRESH_TOKEN` - OAuth refresh token
- `NEST_PROJECT_ID` - Device Access project ID
- `ICAL_URL` - Hospitable checkout calendar URL

**Optional (config):**
- `NEST_DEVICE_IDS` - Comma-separated device IDs (empty = all)
- `POLL_INTERVAL_MINUTES` - Polling interval (default: 10)
- `CHECKOUT_BUFFER_MINUTES` - Time window after checkout (default: 30)
- `TRIGGER_KEYWORD` - Keyword to trigger action (default: TURN_OFF_THERMOSTATS)
- `LOG_LEVEL` - Logging level (default: INFO)

## Deployment

### Kubernetes (obsyk.com cluster)

Deployed to `home-automation` namespace (separate from obsyk workloads).

```bash
# SSH to server and apply manifests
ssh obsyk.com

# Create namespace (first time only)
kubectl apply -f k8s/namespace.yaml

# Create secrets (fill in real values first)
kubectl create secret generic nest-checkout-automation-secrets \
  --namespace=home-automation \
  --from-literal=GOOGLE_CLIENT_ID=xxx \
  --from-literal=GOOGLE_CLIENT_SECRET=xxx \
  --from-literal=GOOGLE_REFRESH_TOKEN=xxx \
  --from-literal=NEST_PROJECT_ID=xxx \
  --from-literal=NEST_DEVICE_IDS= \
  --from-literal=ICAL_URL=xxx

# Apply config and deployment
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml

# Check status
kubectl get pods -n home-automation
kubectl logs -n home-automation -l app=nest-checkout-automation -f
```

### Docker Build
```bash
docker build -t ghcr.io/codervinod/nest-checkout-automation:latest .
docker push ghcr.io/codervinod/nest-checkout-automation:latest
```

## Checkout Detection Logic

1. Service polls iCal feed every 10 minutes
2. Looks for events where:
   - Event START time is within last 30 minutes OR currently happening
   - Summary contains "Check-out" or "checkout"
   - Description contains `TURN_OFF_THERMOSTATS` keyword
3. When triggered:
   - Turns off all configured thermostats (or all if none specified)
   - Marks event as processed (by reservation ID) to prevent duplicates

## Troubleshooting

### Token Refresh Failed
- Check if refresh token is still valid
- Re-run `scripts/get_oauth_token.py` to get new token
- Ensure app is published to production (not testing mode) for long-lived tokens

### No Thermostats Found
- Verify Device Access project ID is correct
- Check OAuth permissions include SDM scope
- Ensure thermostats are in Google Home linked to same account

### Calendar Not Fetching
- Verify iCal URL is accessible (try in browser)
- Check if URL uses `webcal://` (auto-converted to `https://`)

## Files NOT to Commit

These are in `.gitignore`:
- `.env` - Contains secrets
- `venv/` - Virtual environment
- `credentials.json`, `token.json` - OAuth credentials
- `*.pem`, `*.key` - Private keys

## Discovered Thermostats

From last run:
- **Master Bedroom**: `AVPHwEtEmYi0kZG13UX0FMJssXsjFuicc43lEsHmBYrrpvzQdVUzlMtqqnDY1S4gLgxbpYY1QzwK6MLlGRL4norYCjfMkw`
- **Living**: `AVPHwEuAUytt1vkF7xJ8F2lMK6MspuPn309bOdWM1_wWyQxnpgC0bzXuYZOdG9FDR9SUPzrfm8_en1hhyL1qyy3uaMaokQ`
