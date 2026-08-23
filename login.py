"""
login.py - Kite Connect Authentication
Handles TOTP 2FA, session caching, retry with backoff.
"""

import os
import sys
import time
import requests
import pyotp
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv, set_key
from kiteconnect import KiteConnect

from config import DOTENV_PATH, PROJECT_ROOT, log

# -- Constants --
MAX_LOGIN_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5
TOTP_SAFE_WINDOW_SECONDS = 5


class LoginError(Exception):
    """Raised when Kite login fails after all retries."""
    pass


def _wait_for_fresh_totp():
    """
    If the current TOTP window is about to expire (< TOTP_SAFE_WINDOW_SECONDS
    remaining), sleep until the next 30-second window starts.
    """
    now = time.time()
    seconds_into_window = now % 30
    seconds_remaining = 30 - seconds_into_window
    if seconds_remaining < TOTP_SAFE_WINDOW_SECONDS:
        wait_time = seconds_remaining + 1
        log.info(
            "⏳ TOTP window expiring in %.0fs — waiting %.0fs for a fresh code...",
            seconds_remaining, wait_time,
        )
        time.sleep(wait_time)


def perform_auto_login() -> str:
    """
    Automates the Zerodha Kite login process via API requests,
    handles 2FA with TOTP, and saves the new token to .env.
    """
    load_dotenv(DOTENV_PATH, override=True)

    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    user_id = os.getenv("ZERODHA_USER_ID")
    password = os.getenv("ZERODHA_PASSWORD")
    totp_secret = os.getenv("TOTP_SECRET")

    if not all([api_key, api_secret, user_id, password]):
        raise LoginError(
            "Missing credentials in .env. "
            "Required: API_KEY, API_SECRET, ZERODHA_USER_ID, ZERODHA_PASSWORD"
        )

    last_error = None

    for attempt in range(1, MAX_LOGIN_RETRIES + 1):
        try:
            log.info("🚀 Kite Auto-Login attempt %d/%d...", attempt, MAX_LOGIN_RETRIES)
            session = requests.Session()

            # 1. Get the initial login page
            login_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
            login_page_res = session.get(url=login_url, timeout=15)
            if login_page_res.status_code != 200:
                try:
                    err_data = login_page_res.json()
                    err_msg = err_data.get("message", login_page_res.text)
                except Exception:
                    err_msg = login_page_res.text
                raise LoginError(
                    f"Kite Connect login endpoint error "
                    f"(HTTP {login_page_res.status_code}): {err_msg}"
                )
            login_page_url = login_page_res.url

            # 2. Post login credentials
            log.info("🔑 Submitting User ID and Password...")
            login_resp = session.post(
                url="https://kite.zerodha.com/api/login",
                data={"user_id": user_id, "password": password},
                timeout=15,
            )
            login_json = login_resp.json()
            log.debug("Raw login response: %s", login_json)

            if "data" not in login_json or "request_id" not in login_json.get("data", {}):
                status = login_json.get("status", "unknown")
                message = login_json.get("message", "no message")
                raise LoginError(
                    f"Credential submission failed - status: {status}, message: {message}"
                )

            request_id = login_json["data"]["request_id"]
            log.info("✅ Credentials accepted.")

            # 3. Post 2FA (TOTP)
            log.info("⏱️ Handling Two-Factor Authentication...")
            if totp_secret:
                _wait_for_fresh_totp()
                log.info("🔄 Generating TOTP code...")
                twofa_value = pyotp.TOTP(totp_secret).now()
            else:
                print("\n" + "=" * 50)
                print("PLEASE CHECK YOUR PHONE!")
                print("Zerodha requires a 6-digit TOTP from your Google Authenticator app.")
                twofa_value = input("Enter the 6-digit TOTP here: ").strip()
                print("=" * 50 + "\n")

            twofa_resp = session.post(
                url="https://kite.zerodha.com/api/twofa",
                data={
                    "user_id": user_id,
                    "request_id": request_id,
                    "twofa_value": twofa_value,
                },
                timeout=15,
            )
            twofa_json = twofa_resp.json()
            log.debug("Raw 2FA response: %s", twofa_json)

            if twofa_json.get("status") != "success":
                raise LoginError(f"2FA failed: {twofa_json.get('message', 'unknown error')}")

            log.info("✅ 2FA successful.")

            # 4. Get the redirect URL and extract the request_token
            log.info("⏳ Fetching request_token...")
            current_url = ""
            target_urls = [
                login_url,
                login_page_url.replace("skip_session=true", "").replace("&&", "&").rstrip("?&"),
                login_page_url,
            ]
            for target_url in target_urls:
                try:
                    final_response = session.get(url=target_url, allow_redirects=True, timeout=15)
                    current_url = final_response.url
                except requests.exceptions.ConnectionError as e:
                    if hasattr(e, "request") and e.request:
                        current_url = e.request.url
                    else:
                        current_url = str(e)
                except Exception as e:
                    log.debug("Target URL fetch error (%s): %s", target_url, e)
                if "request_token" in current_url:
                    break

            if "request_token" not in current_url:
                parsed_url = urlparse(current_url)
                raise LoginError(
                    f"Failed to capture request_token. "
                    f"Final URL domain: {parsed_url.netloc or 'unknown'}"
                )

            request_token = parse_qs(urlparse(current_url).query)["request_token"][0]
            log.info("✅ Captured Request Token!")

            # 5. Generate Access Token
            log.info("🔄 Generating Access Token from KiteConnect...")
            kite = KiteConnect(api_key=api_key, timeout=25)
            data = kite.generate_session(request_token, api_secret=api_secret)
            access_token = data["access_token"]

            # 6. Save to .env
            set_key(DOTENV_PATH, "ACCESS_TOKEN", access_token, quote_mode="never")
            log.info("🎉 Success! New ACCESS_TOKEN saved to .env")
            return access_token

        except LoginError:
            raise

        except Exception as e:
            last_error = e
            log.warning("⚠️ Login attempt %d/%d failed: %s", attempt, MAX_LOGIN_RETRIES, e)
            if attempt < MAX_LOGIN_RETRIES:
                delay = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                log.info("Retrying in %ds...", delay)
                time.sleep(delay)

    raise LoginError(
        f"Auto-login failed after {MAX_LOGIN_RETRIES} attempts. Last error: {last_error}"
    )


def create_kite_session() -> KiteConnect:
    """
    Initialize KiteConnect with credentials from .env.
    1. Try the saved ACCESS_TOKEN first.
    2. If expired/missing, run auto-login.
    3. Attach session-expiry hook after valid session.
    """
    load_dotenv(DOTENV_PATH, override=True)

    api_key = os.getenv("API_KEY", "")
    access_token = os.getenv("ACCESS_TOKEN", "")

    if not api_key:
        raise LoginError("API_KEY not found in .env. Cannot proceed.")

    kite = KiteConnect(api_key=api_key, timeout=25)

    def on_session_expiry():
        log.warning("⚠️ Kite session expired mid-day! Attempting auto-re-login...")
        try:
            new_token = perform_auto_login()
            kite.set_access_token(new_token)
            log.info("✅ Re-authentication successful! Resuming operations.")
        except Exception as e:
            log.critical("🚨 Mid-day re-authentication FAILED: %s", e)

    kite.set_session_expiry_hook(on_session_expiry)

    # Validate existing token
    if access_token:
        kite.set_access_token(access_token)
        try:
            kite.profile()
            return kite
        except Exception as e:
            log.warning("⚠️ Saved ACCESS_TOKEN is invalid/expired: %s", e)

    # Perform fresh login
    log.info("🔄 Attempting auto-login to get a fresh token...")
    new_token = perform_auto_login()
    kite.set_access_token(new_token)
    return kite