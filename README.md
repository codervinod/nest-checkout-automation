# Nest Checkout Automation

Automatically turn off Nest thermostats when guests check out, triggered by Hospitable iCal calendar events.

## Features

- Polls Hospitable iCal calendar for checkout events
- Detects `TURN_OFF_THERMOSTATS` keyword in event notes
- Turns off specified Nest thermostats via Google Smart Device Management API
- FastAPI server with health endpoints for Kubernetes
- Configurable polling interval and checkout buffer window
- Deduplication to prevent multiple triggers per checkout

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Kubernetes (home-automation namespace)          │
│  ┌───────────────────────────────────────────────────┐  │
│  │          nest-checkout-automation pod             │  │
│  │                                                   │  │
│  │  ┌─────────────┐     ┌──────────────────────┐    │  │
│  │  │ APScheduler │────▶│ Calendar Poller      │    │  │
│  │  │ (10 min)    │     │ - Fetch iCal feed    │    │  │
│  │  └─────────────┘     │ - Parse checkouts    │    │  │
│  │        │             └──────────┬───────────┘    │  │
│  │        │                        │                │  │
│  │        │             ┌──────────▼───────────┐    │  │
│  │        └────────────▶│ Nest Controller      │    │  │
│  │                      │ - Turn off thermo    │    │  │
│  │                      └──────────────────────┘    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
          │                           │
          ▼                           ▼
   [Hospitable iCal]         [Google SDM API]
```

## Prerequisites

### 1. Google Cloud Setup

1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable the **Smart Device Management API**
3. Create OAuth 2.0 credentials (Web application type)
4. Add redirect URI: `https://www.google.com`
5. Configure OAuth consent screen:
   - User type: External
   - Add scope: `https://www.googleapis.com/auth/sdm.service`
   - **Publish to production** (to avoid 7-day token expiry)

### 2. Device Access Registration

1. Go to https://console.nest.google.com/device-access
2. Pay the $5 one-time registration fee
3. Create a project and link your OAuth client ID
4. Save the **Device Access Project ID**

### 3. Get OAuth Refresh Token

```bash
# Set environment variables
export GOOGLE_CLIENT_ID=your-client-id
export GOOGLE_CLIENT_SECRET=your-client-secret
export NEST_PROJECT_ID=your-device-access-project-id

# Run the token script
python scripts/get_oauth_token.py
```

Follow the browser prompts to authorize and copy the refresh token.

## Installation

### Local Development

```bash
# Clone the repository
git clone https://github.com/codervinod/nest-checkout-automation.git
cd nest-checkout-automation

# Create virtual environment (Python 3.11 recommended)
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run the service
python -m uvicorn src.main:app --host 0.0.0.0 --port 8080
```

### Docker

```bash
# Build
docker build -t nest-checkout-automation:latest .

# Run
docker run -d \
  --name nest-checkout \
  -p 8080:8080 \
  --env-file .env \
  nest-checkout-automation:latest
```

### Kubernetes

See [Deployment](#deployment) section below.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | - | OAuth 2.0 Client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | - | OAuth 2.0 Client Secret |
| `GOOGLE_REFRESH_TOKEN` | Yes | - | OAuth refresh token |
| `NEST_PROJECT_ID` | Yes | - | Device Access Project ID |
| `ICAL_URL` | Yes | - | Hospitable checkout calendar URL |
| `NEST_DEVICE_IDS` | No | (all) | Comma-separated device IDs to control |
| `POLL_INTERVAL_MINUTES` | No | 10 | How often to poll calendar |
| `CHECKOUT_BUFFER_MINUTES` | No | 30 | Minutes after checkout to still trigger |
| `TRIGGER_KEYWORD` | No | TURN_OFF_THERMOSTATS | Keyword in event to trigger action |
| `LOG_LEVEL` | No | INFO | Logging level |

### Hospitable Calendar Setup

1. In Hospitable, create a checkout task calendar
2. Export the iCal URL
3. Add `TURN_OFF_THERMOSTATS` to the Notes field of checkout tasks

Example event format:
```
Task type: Check-out
Property: Your Property Name
Reservation: ABC123
Notes: TURN_OFF_THERMOSTATS
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /health` | GET | Health check (for K8s probes) |
| `GET /status` | GET | Detailed service status |
| `POST /poll` | POST | Manually trigger calendar poll |
| `GET /devices` | GET | List discovered thermostats |
| `POST /devices/{id}/off` | POST | Manually turn off a thermostat |

### Example: Check Status

```bash
curl http://localhost:8080/status
```

Response:
```json
{
  "status": "running",
  "scheduler_running": true,
  "last_poll_time": "2024-01-01T10:00:00Z",
  "next_poll_time": "2024-01-01T10:10:00Z",
  "config": {
    "poll_interval_minutes": 10,
    "checkout_buffer_minutes": 30,
    "trigger_keyword": "TURN_OFF_THERMOSTATS"
  }
}
```

## Deployment

### Kubernetes (Recommended)

1. **Create namespace:**
   ```bash
   kubectl apply -f k8s/namespace.yaml
   ```

2. **Create secrets:**
   ```bash
   kubectl create secret generic nest-checkout-automation-secrets \
     --namespace=home-automation \
     --from-literal=GOOGLE_CLIENT_ID=your-client-id \
     --from-literal=GOOGLE_CLIENT_SECRET=your-client-secret \
     --from-literal=GOOGLE_REFRESH_TOKEN=your-refresh-token \
     --from-literal=NEST_PROJECT_ID=your-project-id \
     --from-literal=ICAL_URL=your-ical-url \
     --from-literal=NEST_DEVICE_IDS=
   ```

3. **Apply manifests:**
   ```bash
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/deployment.yaml
   ```

4. **Verify:**
   ```bash
   kubectl get pods -n home-automation
   kubectl logs -n home-automation -l app=nest-checkout-automation -f
   ```

## How It Works

1. **Polling**: Service polls the iCal calendar every 10 minutes (configurable)

2. **Detection**: When a checkout event is found where:
   - Event START time is within the buffer window (currently happening or just started)
   - Event summary contains "Check-out"
   - Event description contains `TURN_OFF_THERMOSTATS`

3. **Action**: Turns off all configured thermostats (or all discovered if none specified)

4. **Deduplication**: Events are tracked by reservation ID to prevent duplicate actions

## Troubleshooting

### Token Refresh Failed

If you see "invalid_grant" errors:
1. Your refresh token may have expired
2. Re-run `scripts/get_oauth_token.py` to get a new token
3. Ensure your OAuth app is published to production (not testing mode)

### No Thermostats Found

1. Verify the Device Access Project ID is correct
2. Ensure the OAuth token was created with the correct Google account
3. Check that thermostats are in Google Home linked to the same account

### Calendar Not Fetching

1. Verify the iCal URL is accessible (try opening in browser)
2. Check if URL uses `webcal://` - it's auto-converted to `https://`
3. Ensure the calendar has checkout events with the trigger keyword

## Security

**Never commit credentials to the repository.**

Sensitive data should be stored in:
- `.env` file (local development) - in `.gitignore`
- Kubernetes secrets (production)

The following files are in `.gitignore`:
- `.env`
- `credentials.json`
- `token.json`
- `*.pem`, `*.key`

## Contributing

1. Create an issue for the work
2. Create a feature branch: `feature/GH-<issue>-<description>`
3. Make changes and test locally
4. Create a pull request
5. Wait for review and CI checks

## License

MIT
