"""
SRE Agent for Scraps n' Bids.

Monitors the live auction platform health, detects incidents, and announces status
updates via ElevenLabs TTS.

Usage:
    python sre_agent.py              # Start monitoring loop
    python sre_agent.py --once       # Single check, then exit
    python sre_agent.py --status     # Speak current status, then exit
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
from elevenlabs import stream
from elevenlabs.client import ElevenLabs

load_dotenv()

# Configuration
TARGET_SITE = "https://scraps-n-bids.vercel.app"
CHECK_INTERVAL = 30  # seconds
SLOW_THRESHOLD = 2.0  # seconds

# Initialize ElevenLabs client
try:
    client = ElevenLabs(
        api_key=os.environ.get("ELEVENLABS_API_KEY"),
    )
except Exception:
    client = None


def _log(message: str) -> None:
    """Log message with timestamp to console."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def health_check() -> Dict[str, Any]:
    """
    Performs HTTP GET to TARGET_SITE.

    Returns:
        Dict containing:
        - status_code: int (or None on error)
        - response_time: float (seconds)
        - is_healthy: bool
        - error: str (optional error message)
    """
    try:
        start_time = time.time()
        response = requests.get(TARGET_SITE, timeout=10)
        duration = time.time() - start_time

        is_healthy = (response.status_code == 200) and (duration < SLOW_THRESHOLD)

        return {
            "status_code": response.status_code,
            "response_time": duration,
            "is_healthy": is_healthy,
            "content": response.text,
            "error": None,
        }
    except requests.RequestException as e:
        return {
            "status_code": None,
            "response_time": 0.0,
            "is_healthy": False,
            "content": "",
            "error": str(e),
        }


def scrape_auction_status_via_rtrvr() -> Dict[str, Any]:
    """
    Uses rtrvr.ai to scrape the JS-rendered auction page.

    Returns:
        Dict containing:
        - current_item: str or None
        - current_bid: float or None
        - is_auction_running: bool
    """
    rtrvr_key = os.environ.get("RTRVR_API_KEY")
    if not rtrvr_key:
        _log("Warning: RTRVR_API_KEY not set, skipping deep scrape")
        return {"current_item": None, "current_bid": None, "is_auction_running": False}

    try:
        response = requests.post(
            "https://api.rtrvr.ai/scrape",
            headers={
                "Authorization": f"Bearer {rtrvr_key}",
                "Content-Type": "application/json",
            },
            json={"urls": [TARGET_SITE]},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("success") or not data.get("tabs"):
            return {
                "current_item": None,
                "current_bid": None,
                "is_auction_running": False,
            }

        tab = data["tabs"][0]
        tree = tab.get("tree", "")

        # Parse the accessibility tree for auction data
        current_item = None
        current_bid = None

        # Find item name after [h2] (but not "Bid History")
        h2_matches = re.findall(r"\[h2\]\s*([^\n\[]+)", tree)
        for match in h2_matches:
            match = match.strip()
            if match and match.lower() not in ["bid history", ""]:
                current_item = match
                break

        # Find price pattern $X.XX
        price_match = re.search(r"\$(\d+\.?\d*)", tree)
        if price_match:
            current_bid = float(price_match.group(1))

        is_auction_running = bool(current_item and current_bid and current_bid > 0)

        return {
            "current_item": current_item,
            "current_bid": current_bid,
            "is_auction_running": is_auction_running,
        }

    except Exception as e:
        _log(f"rtrvr scrape error: {e}")
        return {"current_item": None, "current_bid": None, "is_auction_running": False}


def detect_incident(
    health_result: Dict[str, Any], scrape_result: Dict[str, Any]
) -> Optional[Dict[str, str]]:
    """
    Analyzes results to detect incidents.

    Returns:
        Dict with type, severity, message, or None if healthy.
    """
    # 1. Site Down (Network or HTTP Error)
    if health_result["error"]:
        return {
            "type": "site_down",
            "severity": "P1",
            "message": f"Alert: Scraps n' Bids is down. Connection error detected: {health_result['error']}",
        }

    if health_result["status_code"] != 200:
        return {
            "type": "site_down",
            "severity": "P1",
            "message": f"Alert: Scraps n' Bids is down. HTTP {health_result['status_code']} error detected.",
        }

    # 2. Slow Response
    if health_result["response_time"] >= SLOW_THRESHOLD:
        return {
            "type": "slow_response",
            "severity": "P2",
            "message": f"Warning: Scraps n' Bids response time is {health_result['response_time']:.1f} seconds. Performance degraded.",
        }

    # 3. Page Broken / Auction Stalled (Content Check)
    # Only check this if we got a 200 OK
    if not scrape_result["is_auction_running"]:
        # It might just be between auctions, but if we can't find ANY structure, it's suspicious
        # For this agent, we'll assume missing elements = broken page
        return {
            "type": "page_broken",
            "severity": "P3",
            "message": "Alert: Scraps n' Bids page structure unrecognized. Auction elements not found.",
        }

    return None


def speak_alert(message: str) -> None:
    """
    Uses ElevenLabs API to convert message to speech and play it.
    Falls back to console log if API key missing or error occurs.
    """
    if not client:
        _log(f"[Voice Disabled] {message}")
        return

    try:
        _log("Speaking alert...")
        audio = client.text_to_speech.convert(
            text=message,
            voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel
            model_id="eleven_flash_v2_5",
            output_format="mp3_44100_128",
        )
        # Save to temp file and play
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            for chunk in audio:
                f.write(chunk)
            temp_path = f.name
        # Try different players
        played = False
        try:
            # ffplay with no window and auto-exit
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", temp_path],
                check=True,
                capture_output=True,
            )
            played = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        if not played:
            try:
                subprocess.run(["paplay", temp_path], check=True, capture_output=True)
                played = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        if not played:
            _log(f"[No audio player found] {message}")
        os.unlink(temp_path)
    except Exception as e:
        _log(f"Error generating speech: {e}")
        _log(f"[Fallback] {message}")


def run_check(speak_status: bool = False) -> None:
    """
    Runs a single iteration of the monitoring logic.

    Args:
        speak_status: If True, speaks the status even if healthy.
    """
    # 1. Health Check
    health = health_check()
    status_msg = f"{health['status_code']} OK" if health["status_code"] else "FAILED"
    _log(f"Health check: {status_msg} ({health['response_time']:.2f}s)")

    # 2. Scrape via rtrvr (handles JS-rendered content)
    scrape = scrape_auction_status_via_rtrvr()
    if scrape["current_item"]:
        _log(f"Auction: {scrape['current_item']} @ ${scrape['current_bid']}")
    else:
        _log("Auction: No active item found")

    # 3. Detect Incident
    incident = detect_incident(health, scrape)

    if incident:
        _log(
            f"INCIDENT {incident['severity']}: {incident['type']} - {incident['message']}"
        )
        speak_alert(incident["message"])
    else:
        _log("Status: HEALTHY")
        if speak_status:
            item = scrape.get("current_item", "unknown item")
            price = scrape.get("current_bid", 0.00)
            msg = f"Scraps n' Bids is online. Currently auctioning {item} at ${price:.2f}."
            speak_alert(msg)


def run_monitor_loop() -> None:
    """Main monitoring loop."""
    _log(f"Starting SRE Agent for {TARGET_SITE}")
    _log(f"Interval: {CHECK_INTERVAL}s | Slow Threshold: {SLOW_THRESHOLD}s")

    if not client:
        _log("Warning: ELEVENLABS_API_KEY not set. Voice alerts disabled.")

    try:
        while True:
            run_check(speak_status=False)
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        _log("Stopping SRE Agent.")
        sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="SRE Agent for Scraps n' Bids")
    parser.add_argument(
        "--once", action="store_true", help="Run a single check and exit"
    )
    parser.add_argument(
        "--status", action="store_true", help="Run check, speak status, and exit"
    )

    args = parser.parse_args()

    if args.once:
        run_check(speak_status=False)
    elif args.status:
        run_check(speak_status=True)
    else:
        run_monitor_loop()


if __name__ == "__main__":
    main()
