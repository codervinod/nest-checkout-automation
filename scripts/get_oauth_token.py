#!/usr/bin/env python3
"""
One-time OAuth token generation script.

This script performs the initial OAuth flow to get a refresh token
for the Google Smart Device Management API.

Usage:
    1. Set environment variables or create .env file:
       - GOOGLE_CLIENT_ID
       - GOOGLE_CLIENT_SECRET
       - NEST_PROJECT_ID

    2. Run this script:
       python scripts/get_oauth_token.py

    3. Follow the browser prompts to authorize the app

    4. Copy the refresh token to your deployment secrets
"""

import os
import sys
import webbrowser
from urllib.parse import urlencode, parse_qs, urlparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

# Configuration
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
PROJECT_ID = os.environ.get("NEST_PROJECT_ID")

# OAuth endpoints
AUTHORIZATION_URL = "https://nestservices.google.com/partnerconnections/{project_id}/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "https://www.google.com"
SCOPES = ["https://www.googleapis.com/auth/sdm.service"]


def get_authorization_url() -> str:
    """Generate the authorization URL."""
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    base_url = AUTHORIZATION_URL.format(project_id=PROJECT_ID)
    return f"{base_url}?{urlencode(params)}"


def exchange_code_for_tokens(authorization_code: str) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": authorization_code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post(TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


def main():
    print("=" * 60)
    print("Nest OAuth Token Generator")
    print("=" * 60)
    print()

    # Validate configuration
    missing = []
    if not CLIENT_ID:
        missing.append("GOOGLE_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not PROJECT_ID:
        missing.append("NEST_PROJECT_ID")

    if missing:
        print("ERROR: Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print()
        print("Set these variables or create a .env file with them.")
        sys.exit(1)

    print("Configuration:")
    print(f"  Client ID: {CLIENT_ID[:20]}...")
    print(f"  Project ID: {PROJECT_ID}")
    print()

    # Generate authorization URL
    auth_url = get_authorization_url()

    print("Step 1: Authorization")
    print("-" * 40)
    print("Opening browser for Google authorization...")
    print()
    print("If browser doesn't open, visit this URL manually:")
    print()
    print(auth_url)
    print()

    # Try to open browser
    try:
        webbrowser.open(auth_url)
    except Exception:
        print("(Could not open browser automatically)")

    print()
    print("Step 2: Grant Access")
    print("-" * 40)
    print("1. Sign in to your Google account (the one with Nest devices)")
    print("2. Review and grant the requested permissions")
    print("3. You'll be redirected to google.com with a 'code' parameter")
    print()
    print("Step 3: Copy the Authorization Code")
    print("-" * 40)
    print("After granting access, you'll be redirected to a URL like:")
    print("  https://www.google.com?code=4/0ABC123...&scope=...")
    print()
    print("Copy the ENTIRE redirect URL and paste it below:")
    print()

    redirect_url = input("Paste redirect URL here: ").strip()

    # Parse the authorization code from the URL
    try:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)

        if "code" not in params:
            print()
            print("ERROR: No authorization code found in URL")
            print("Make sure you copied the entire URL including ?code=...")
            sys.exit(1)

        authorization_code = params["code"][0]
        print()
        print(f"Authorization code extracted: {authorization_code[:20]}...")

    except Exception as e:
        print()
        print(f"ERROR: Failed to parse URL: {e}")
        sys.exit(1)

    # Exchange code for tokens
    print()
    print("Step 4: Exchanging code for tokens...")
    print("-" * 40)

    try:
        tokens = exchange_code_for_tokens(authorization_code)

        print()
        print("SUCCESS! Tokens received.")
        print()
        print("=" * 60)
        print("YOUR REFRESH TOKEN (save this securely!):")
        print("=" * 60)
        print()
        print(tokens.get("refresh_token"))
        print()
        print("=" * 60)
        print()
        print("Access Token (expires in ~1 hour):")
        print(f"  {tokens.get('access_token', 'N/A')[:50]}...")
        print()
        print("Token Type:", tokens.get("token_type"))
        print("Expires In:", tokens.get("expires_in"), "seconds")
        print("Scope:", tokens.get("scope"))
        print()
        print("=" * 60)
        print("NEXT STEPS:")
        print("=" * 60)
        print()
        print("1. Copy the refresh token above")
        print("2. Store it securely (e.g., Kubernetes secret)")
        print("3. Set GOOGLE_REFRESH_TOKEN environment variable")
        print()
        print("Example .env file:")
        print("-" * 40)
        print(f"GOOGLE_CLIENT_ID={CLIENT_ID}")
        print(f"GOOGLE_CLIENT_SECRET={CLIENT_SECRET}")
        print(f"GOOGLE_REFRESH_TOKEN={tokens.get('refresh_token')}")
        print(f"NEST_PROJECT_ID={PROJECT_ID}")
        print("ICAL_URL=webcal://your-calendar-url")
        print("NEST_DEVICE_IDS=device-id-1,device-id-2")
        print("-" * 40)

    except requests.exceptions.HTTPError as e:
        print()
        print(f"ERROR: Token exchange failed: {e}")
        print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
