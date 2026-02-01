"""
HeyOps - Voice-controlled SRE agent that monitors your site and tells you how to fix it.
"""

import base64
import os
import re
import time
from typing import Optional

import requests
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

load_dotenv()

app = FastAPI(title="HeyOps")

# Configuration
TARGET_SITE = "https://scraps-n-bids.brad-dougherty.com"
STATUS_PAGE = "https://scraps-n-bids.brad-dougherty.com/status.html"
SLOW_THRESHOLD = 2.0

# ElevenLabs client
client = None
try:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if api_key:
        client = ElevenLabs(api_key=api_key)
except Exception:
    pass


def health_check():
    try:
        start = time.time()
        resp = requests.get(TARGET_SITE, timeout=10)
        duration = time.time() - start
        return {
            "status_code": resp.status_code,
            "response_time": round(duration, 2),
            "is_healthy": resp.status_code == 200 and duration < SLOW_THRESHOLD,
            "error": None,
        }
    except Exception as e:
        return {
            "status_code": None,
            "response_time": 0,
            "is_healthy": False,
            "error": str(e),
        }


def scrape_auction():
    """Scrape main auction page for current item and bid."""
    rtrvr_key = os.environ.get("RTRVR_API_KEY")
    if not rtrvr_key:
        return {"current_item": None, "current_bid": None, "is_auction_running": False}

    try:
        resp = requests.post(
            "https://api.rtrvr.ai/scrape",
            headers={
                "Authorization": f"Bearer {rtrvr_key}",
                "Content-Type": "application/json",
            },
            json={"urls": [TARGET_SITE]},
            timeout=30,
        )
        data = resp.json()
        if not data.get("success") or not data.get("tabs"):
            return {
                "current_item": None,
                "current_bid": None,
                "is_auction_running": False,
            }

        tree = data["tabs"][0].get("tree", "")

        # Parse item name from h2 elements (skip "Bid History" and empty ones)
        current_item = None
        h2_matches = re.findall(r"\[h2\]\s*([^\n\[]*)", tree)
        for match in h2_matches:
            match = match.strip()
            if match and match.lower() not in ["bid history"]:
                current_item = match
                break

        # Parse bid from "Current Bid $X.XX" pattern in textNode
        current_bid = None
        bid_match = re.search(r"Current Bid\s*\$(\d+\.?\d*)", tree)
        if bid_match:
            current_bid = float(bid_match.group(1))

        # Check if auction is live (look for LIVE indicator)
        is_live = bool(re.search(r"LIVE", tree))

        # If no item name from h2, try to get it from the img alt text
        if not current_item:
            img_match = re.search(r"\[img\]\s*([^\[\n]+)", tree)
            if img_match:
                alt = img_match.group(1).strip()
                if alt and alt.lower() not in ["meal photo"]:
                    current_item = alt

        return {
            "current_item": current_item,
            "current_bid": current_bid,
            "is_auction_running": is_live and current_bid is not None,
            "raw_tree": tree,
        }
    except Exception as e:
        return {
            "current_item": None,
            "current_bid": None,
            "is_auction_running": False,
            "error": str(e),
        }


def scrape_status_page():
    """Scrape status.html for detailed diagnostics."""
    rtrvr_key = os.environ.get("RTRVR_API_KEY")
    if not rtrvr_key:
        return None

    try:
        resp = requests.post(
            "https://api.rtrvr.ai/scrape",
            headers={
                "Authorization": f"Bearer {rtrvr_key}",
                "Content-Type": "application/json",
            },
            json={"urls": [STATUS_PAGE]},
            timeout=30,
        )
        data = resp.json()
        if not data.get("success") or not data.get("tabs"):
            return None

        tree = data["tabs"][0].get("tree", "")

        # Parse status page
        result = {
            "overall_status": None,
            "image_error_rate": None,
            "failed_images": [],
            "auction_transition": None,
        }

        # Look for status indicators
        if "CRITICAL" in tree:
            result["overall_status"] = "CRITICAL"
        elif "DEGRADED" in tree:
            result["overall_status"] = "DEGRADED"
        elif "HEALTHY" in tree:
            result["overall_status"] = "HEALTHY"

        # Look for failed image URLs
        failed_urls = re.findall(r"(https?://[^\s]+\.png)", tree)
        result["failed_images"] = failed_urls

        # Look for error percentages
        error_match = re.search(r"(\d+)%\s*error", tree, re.IGNORECASE)
        if error_match:
            result["image_error_rate"] = int(error_match.group(1))

        # Look for transition delay issues
        if "stalled" in tree.lower() or "transition" in tree.lower():
            transition_match = re.search(r"(\d+\.?\d*)\s*m(?:in)?", tree)
            if transition_match:
                result["auction_transition"] = f"{transition_match.group(1)} minutes"

        result["raw_tree"] = tree
        return result
    except Exception as e:
        return {"error": str(e)}


def diagnose_and_suggest_fix(health, auction, status_page):
    """Analyze all data and provide diagnosis with fix suggestion."""

    # Check for site down
    if health.get("error") or health.get("status_code") != 200:
        return {
            "diagnosis": "The site is completely down.",
            "cause": f"HTTP error: {health.get('error') or health.get('status_code')}",
            "fix": "Check Vercel deployment logs. The site may need to be redeployed.",
            "severity": "P1",
        }

    # Check status page for specific issues
    if status_page:
        # Image path issues
        if status_page.get("image_error_rate", 0) > 0 or status_page.get(
            "failed_images"
        ):
            failed = status_page.get("failed_images", [])
            # Detect wrong path pattern
            wrong_path = None
            if any("imgs/" in url for url in failed):
                wrong_path = "imgs/"
                correct_path = "images/"
            elif any("/img/" in url for url in failed):
                wrong_path = "img/"
                correct_path = "images/"

            if wrong_path:
                return {
                    "diagnosis": f"Images are failing to load. The image paths are using '{wrong_path}' instead of 'images/'.",
                    "cause": f"The photo property in the MEALS array in index.html has incorrect paths.",
                    "fix": f"Open index.html, find the MEALS array, and change all '{wrong_path}' to '{correct_path}' in the photo properties.",
                    "severity": "P2",
                    "failed_images": failed,
                }
            else:
                return {
                    "diagnosis": "Images are failing to load with 404 errors.",
                    "cause": "Image paths in the MEALS array don't match actual files in the images directory.",
                    "fix": "Check the photo properties in the MEALS array in index.html. Make sure they match the actual filenames in the images folder.",
                    "severity": "P2",
                    "failed_images": failed,
                }

        # Auction transition delay issue
        if status_page.get("auction_transition") and "minute" in str(
            status_page.get("auction_transition", "")
        ):
            return {
                "diagnosis": "Auctions are getting stuck after showing SOLD.",
                "cause": "The AUCTION_TRANSITION_DELAY constant is set too high, probably 300000 instead of 3000.",
                "fix": "Open index.html, search for AUCTION_TRANSITION_DELAY, and change it from 300000 to 3000. That's 3 seconds instead of 5 minutes.",
                "severity": "P2",
            }

        if status_page.get("overall_status") == "CRITICAL":
            return {
                "diagnosis": "The status page shows CRITICAL status.",
                "cause": "Multiple issues detected on the status page.",
                "fix": "Check the status page at /status.html for specific errors. Common issues are image paths or transition delays.",
                "severity": "P1",
            }

    # Check auction status
    if not auction.get("is_auction_running"):
        return {
            "diagnosis": "The auction doesn't appear to be running.",
            "cause": "Could not find LIVE indicator or bid info on the page. Possible JavaScript error or the bidding engine is disabled.",
            "fix": "Check the browser console for JavaScript errors. Make sure the MEALS array has valid data and no syntax errors.",
            "severity": "P2",
        }

    # Auction is live but no item name visible
    if not auction.get("current_item"):
        return {
            "diagnosis": "The auction is live but the item name isn't showing.",
            "cause": "The auction timer is running and bids are accepted, but the current item name is empty.",
            "fix": "Check the MEALS array in index.html. The current item's name property might be empty or undefined.",
            "severity": "P3",
            "status": "degraded",
            "current_bid": auction.get("current_bid"),
        }

    # All good
    return {
        "diagnosis": "Everything looks healthy.",
        "status": "healthy",
        "current_auction": auction.get("current_item"),
        "current_bid": auction.get("current_bid"),
        "severity": None,
    }


def generate_voice_response(diagnosis_result, auction):
    """Generate a natural voice response based on diagnosis."""

    if diagnosis_result.get("status") == "healthy":
        item = auction.get("current_item", "an item")
        bid = auction.get("current_bid", 0)
        bid_str = f"at ${bid:.2f}" if bid else "with no bids yet"
        return f"The site is looking good. We're currently auctioning {item} {bid_str}. No issues detected."

    if diagnosis_result.get("status") == "degraded":
        bid = auction.get("current_bid", 0)
        return f"{diagnosis_result.get('diagnosis', '')} The current bid is ${bid:.2f}. {diagnosis_result.get('fix', '')}"

    diagnosis = diagnosis_result.get("diagnosis", "There's an issue.")
    fix = diagnosis_result.get("fix", "")

    response = f"{diagnosis} "
    if fix:
        response += f"To fix this: {fix}"

    return response


def get_voice_audio(message: str) -> Optional[str]:
    """Generate audio and return as base64."""
    if not client:
        return None
    try:
        audio = client.text_to_speech.convert(
            text=message,
            voice_id="21m00Tcm4TlvDq8ikWAM",
            model_id="eleven_flash_v2_5",
            output_format="mp3_44100_128",
        )
        audio_bytes = b"".join(audio)
        return base64.b64encode(audio_bytes).decode()
    except Exception:
        return None


def transcribe_audio(audio_bytes: bytes) -> Optional[str]:
    """Transcribe audio using ElevenLabs speech-to-text."""
    if not client:
        return None
    try:
        import io

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "recording.webm"
        result = client.speech_to_text.convert(
            file=audio_file,
            model_id="scribe_v1",
        )
        return result.text if result.text else None
    except Exception as e:
        print(f"STT error: {e}")
        return None


@app.get("/logo.png")
async def logo():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "logo.png"),
        media_type="image/png",
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>HeyOps - Voice-Controlled SRE</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
            padding: 2rem;
        }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { font-size: 2rem; margin-bottom: 0.5rem; }
        .subtitle { color: #94a3b8; margin-bottom: 2rem; }
        .card {
            background: #1e293b;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
        }
        .status { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
        .status-dot {
            width: 16px; height: 16px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        .status-dot.healthy { background: #22c55e; }
        .status-dot.unhealthy { background: #ef4444; }
        .status-dot.loading { background: #eab308; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .label { color: #94a3b8; font-size: 0.875rem; margin-bottom: 0.5rem; }
        .value { font-size: 1.25rem; font-weight: 600; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        .btn {
            background: #3b82f6;
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-size: 1rem;
            cursor: pointer;
            width: 100%;
            margin-bottom: 0.5rem;
        }
        .btn:hover { background: #2563eb; }
        .btn:disabled { background: #475569; cursor: not-allowed; }
        .btn.recording { background: #ef4444; animation: pulse 1s infinite; }
        .btn.mic { background: #8b5cf6; }
        .btn.mic:hover { background: #7c3aed; }

        .diagnosis {
            background: #0f172a;
            padding: 1rem;
            border-radius: 8px;
            margin-top: 1rem;
        }
        .diagnosis h3 { color: #f59e0b; margin-bottom: 0.5rem; }
        .diagnosis .fix { color: #22c55e; margin-top: 0.5rem; }
        .log {
            background: #0f172a;
            padding: 1rem;
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.875rem;
            max-height: 200px;
            overflow-y: auto;
        }
        .log-entry { margin-bottom: 0.5rem; }
        .log-time { color: #64748b; }
        .incident { color: #ef4444; }
        .healthy { color: #22c55e; }
        .voice-status {
            text-align: center;
            padding: 1rem;
            color: #94a3b8;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <img src="/logo.png" alt="HeyOps" style="max-width: 320px; margin-bottom: 1.5rem;">

        <div class="card">
            <div class="status">
                <div class="status-dot loading" id="statusDot"></div>
                <span class="value" id="statusText">Ready</span>
            </div>
            <div class="grid">
                <div>
                    <div class="label">Response Time</div>
                    <div class="value" id="responseTime">--</div>
                </div>
                <div>
                    <div class="label">HTTP Status</div>
                    <div class="value" id="httpStatus">--</div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="label">Current Auction</div>
            <div class="value" id="auctionItem">--</div>
            <div class="value" style="color: #22c55e;" id="auctionBid"></div>
        </div>

        <div class="card">
            <div class="voice-status" id="voiceStatus">Say "Hey Ops, how's the site looking?"</div>
            <button class="btn mic" id="micBtn" onclick="toggleRecording()">🎤 Ask the Agent</button>
            <button class="btn" id="checkBtn" onclick="runCheck()">🔍 Run Check</button>
            <button class="btn" onclick="askQuestion('auction')">🏷️ Current Auction</button>
            <button class="btn" onclick="askQuestion('latency')">⏱️ Latency</button>
            <button class="btn" onclick="askQuestion('status')">📡 Response Code</button>
        </div>

        <div class="card" id="diagnosisCard" style="display: none;">
            <div class="label">Diagnosis</div>
            <div class="diagnosis">
                <h3 id="diagnosisText"></h3>
                <p id="causeText"></p>
                <p class="fix" id="fixText"></p>
            </div>
        </div>

        <div class="card">
            <div class="label">Log</div>
            <div class="log" id="log"></div>
        </div>
    </div>

    <audio id="audio" style="display:none;"></audio>

    <script>
        let mediaRecorder;
        let audioChunks = [];
        let isRecording = false;

        function log(msg, type = '') {
            const el = document.getElementById('log');
            const time = new Date().toLocaleTimeString();
            el.innerHTML = `<div class="log-entry ${type}"><span class="log-time">[${time}]</span> ${msg}</div>` + el.innerHTML;
        }

        async function toggleRecording() {
            const btn = document.getElementById('micBtn');
            const status = document.getElementById('voiceStatus');

            if (!isRecording) {
                // Start recording
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];

                    mediaRecorder.ondataavailable = (e) => {
                        audioChunks.push(e.data);
                    };

                    mediaRecorder.onstop = async () => {
                        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                        status.textContent = 'Processing your question...';
                        await sendAudioToAgent(audioBlob);
                        stream.getTracks().forEach(track => track.stop());
                    };

                    mediaRecorder.start();
                    isRecording = true;
                    btn.textContent = '⏹️ Stop Recording';
                    btn.classList.add('recording');
                    status.textContent = 'Listening... Ask your question';
                    log('Recording started...');
                } catch (err) {
                    log('Microphone access denied: ' + err.message, 'incident');
                    status.textContent = 'Microphone access denied';
                }
            } else {
                // Stop recording
                mediaRecorder.stop();
                isRecording = false;
                btn.textContent = '🎤 Ask the Agent';
                btn.classList.remove('recording');
            }
        }

        async function sendAudioToAgent(audioBlob) {
            const formData = new FormData();
            formData.append('audio', audioBlob, 'recording.webm');

            try {
                const resp = await fetch('/api/voice-query', {
                    method: 'POST',
                    body: formData
                });
                const data = await resp.json();

                log('You asked: ' + (data.transcription || '(could not transcribe)'));

                // Update UI with results
                updateUIWithResults(data);

                // Play audio response
                if (data.audio) {
                    log('Agent responding...');
                    const audio = document.getElementById('audio');
                    audio.src = 'data:audio/mp3;base64,' + data.audio;
                    audio.play();
                }

                document.getElementById('voiceStatus').textContent = 'Click the microphone to ask another question';

            } catch (err) {
                log('Error: ' + err.message, 'incident');
                document.getElementById('voiceStatus').textContent = 'Error processing request';
            }
        }

        function updateUIWithResults(data) {
            const dot = document.getElementById('statusDot');
            const statusText = document.getElementById('statusText');

            if (data.diagnosis?.status === 'healthy') {
                dot.className = 'status-dot healthy';
                statusText.textContent = 'HEALTHY';
                document.getElementById('diagnosisCard').style.display = 'none';
            } else if (data.diagnosis) {
                dot.className = 'status-dot unhealthy';
                statusText.textContent = data.diagnosis.severity || 'ISSUE';

                document.getElementById('diagnosisCard').style.display = 'block';
                document.getElementById('diagnosisText').textContent = data.diagnosis.diagnosis;
                document.getElementById('causeText').textContent = data.diagnosis.cause || '';
                document.getElementById('fixText').textContent = data.diagnosis.fix ? '💡 Fix: ' + data.diagnosis.fix : '';

                log('Issue detected: ' + data.diagnosis.diagnosis, 'incident');
            }

            if (data.health) {
                document.getElementById('responseTime').textContent = data.health.response_time + 's';
                document.getElementById('httpStatus').textContent = data.health.status_code || 'Error';
            }

            if (data.auction?.current_item) {
                document.getElementById('auctionItem').textContent = data.auction.current_item;
                document.getElementById('auctionBid').textContent = '$' + data.auction.current_bid;
            }
        }

        async function runCheck() {
            const btn = document.getElementById('checkBtn');
            btn.disabled = true;
            btn.textContent = '⏳ Checking...';

            document.getElementById('statusDot').className = 'status-dot loading';
            document.getElementById('statusText').textContent = 'Checking...';

            log('Starting health check...');

            try {
                const resp = await fetch('/api/check');
                const data = await resp.json();
                updateUIWithResults(data);

                if (data.audio) {
                    const audio = document.getElementById('audio');
                    audio.src = 'data:audio/mp3;base64,' + data.audio;
                    audio.play();
                }

            } catch (err) {
                log('Error: ' + err.message, 'incident');
            }

            btn.disabled = false;
            btn.textContent = '🔍 Run Check';
        }

        async function askQuestion(type) {
            const btns = document.querySelectorAll('.btn');
            btns.forEach(b => b.disabled = true);
            log('Asking: ' + type + '...');

            try {
                const resp = await fetch('/api/ask?q=' + type);
                const data = await resp.json();
                updateUIWithResults(data);

                if (data.audio) {
                    const audio = document.getElementById('audio');
                    audio.src = 'data:audio/mp3;base64,' + data.audio;
                    audio.play();
                }

                log('Agent: ' + data.voice_response, data.diagnosis?.status === 'healthy' ? 'healthy' : '');
            } catch (err) {
                log('Error: ' + err.message, 'incident');
            }

            btns.forEach(b => b.disabled = false);
            document.getElementById('checkBtn').textContent = '🔍 Run Check';
        }
    </script>
</body>
</html>
"""


@app.post("/api/voice-query")
async def voice_query(audio: UploadFile = File(...)):
    """Handle voice query - transcribe, analyze, respond."""

    # Read audio
    audio_bytes = await audio.read()

    # Transcribe
    transcription = transcribe_audio(audio_bytes)

    # Run checks
    health = health_check()
    auction = scrape_auction()
    status_page = scrape_status_page()

    # Diagnose
    diagnosis = diagnose_and_suggest_fix(health, auction, status_page)

    # Generate voice response
    voice_text = generate_voice_response(diagnosis, auction)
    audio_b64 = get_voice_audio(voice_text)

    return {
        "transcription": transcription,
        "health": health,
        "auction": {k: v for k, v in auction.items() if k != "raw_tree"},
        "diagnosis": diagnosis,
        "voice_response": voice_text,
        "audio": audio_b64,
    }


@app.get("/api/ask")
async def api_ask(q: str = "check"):
    """Answer a specific text question."""
    health = health_check()
    auction = scrape_auction()

    if q == "auction":
        item = auction.get("current_item") or "unknown"
        bid = auction.get("current_bid")
        running = auction.get("is_auction_running")
        if running and bid is not None:
            bid_str = f"${bid:.2f}" if bid else "no bids yet"
            voice_text = f"The current auction item is {item}, with a bid of {bid_str}."
        else:
            voice_text = "The auction doesn't appear to be running right now."
        diagnosis = {
            "diagnosis": voice_text,
            "status": "healthy" if running else "degraded",
            "severity": None if running else "P2",
        }
    elif q == "latency":
        rt = health.get("response_time", 0)
        slow = rt >= SLOW_THRESHOLD
        voice_text = f"Current response time is {rt} seconds." + (
            f" That's above the {SLOW_THRESHOLD}s threshold."
            if slow
            else " Looking good."
        )
        diagnosis = {
            "diagnosis": voice_text,
            "status": "healthy" if not slow else "degraded",
            "severity": "P2" if slow else None,
        }
    elif q == "status":
        code = health.get("status_code")
        err = health.get("error")
        if err:
            voice_text = f"The site returned an error: {err}"
            diagnosis = {"diagnosis": voice_text, "status": "down", "severity": "P1"}
        elif code == 200:
            voice_text = f"HTTP status code is {code}. The site is responding normally."
            diagnosis = {"diagnosis": voice_text, "status": "healthy", "severity": None}
        else:
            voice_text = f"HTTP status code is {code}. That's unexpected."
            diagnosis = {
                "diagnosis": voice_text,
                "status": "degraded",
                "severity": "P2",
            }
    else:
        return await api_check()

    audio_b64 = get_voice_audio(voice_text)
    return {
        "health": health,
        "auction": {k: v for k, v in auction.items() if k != "raw_tree"},
        "diagnosis": diagnosis,
        "voice_response": voice_text,
        "audio": audio_b64,
    }


@app.get("/api/check")
async def api_check():
    health = health_check()
    auction = scrape_auction()
    status_page = scrape_status_page()

    diagnosis = diagnose_and_suggest_fix(health, auction, status_page)
    voice_text = generate_voice_response(diagnosis, auction)
    audio_b64 = get_voice_audio(voice_text)

    return {
        "health": health,
        "auction": {k: v for k, v in auction.items() if k != "raw_tree"},
        "diagnosis": diagnosis,
        "voice_response": voice_text,
        "audio": audio_b64,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
