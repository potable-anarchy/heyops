# Product Requirements Document (PRD)

## Title: SRE Agent for Scraps n' Bids Auction Platform

**Version:** 1.0 MVP  
**Date:** January 31, 2026  
**Status:** Hackathon Demo

---

## 1. Overview

An AI-powered SRE agent that monitors the Scraps n' Bids live auction platform, detects incidents, diagnoses issues, and communicates status updates via voice. The agent uses web scraping to check site health and speaks alerts using text-to-speech.

**Target Site:** https://scraps-n-bids.vercel.app

**Goal:** Demonstrate a working SRE agent that monitors a live site, detects when something breaks, and responds with voice-based incident communication.

---

## 2. Tech Stack

**Runtime:** Python 3.11+

**Core Dependencies:**
- Toolhouse SDK (agent orchestration)
- rtrvr.ai MCP (web scraping/monitoring)
- ElevenLabs MCP (text-to-speech for alerts)
- Requests (HTTP health checks)

**Infrastructure:**
- Toolhouse account for agent deployment
- rtrvr.ai API key for web automation
- ElevenLabs API key for voice synthesis

---

## 3. Core Features

### 3.1 Site Health Monitor

The agent periodically checks the auction site health:

- **HTTP Health Check:** GET request to site, check for 200 status
- **Content Validation:** Verify auction elements are present (timer, bid history, current item)
- **Performance Check:** Response time monitoring (flag if > 2 seconds)

Health check interval: Every 30 seconds during demo.

### 3.2 Web Scraping via rtrvr.ai

Use rtrvr MCP to extract live site data:

- Current auction item name and emoji
- Current bid amount
- Countdown timer value
- Number of bids in history
- Any error messages visible on page

This validates the auction is actually running, not just that the page loads.

### 3.3 Incident Detection

Detect these incident types:

| Incident Type | Detection Method | Severity |
|---------------|------------------|----------|
| Site Down | HTTP 5xx or timeout | P1 |
| Page Broken | Missing auction elements | P1 |
| Slow Response | Response > 2s | P2 |
| Auction Stalled | Timer not changing between checks | P2 |
| No Bids | Bid history empty for > 60s | P3 |

### 3.4 Voice Alerts via ElevenLabs

When an incident is detected, the agent:

1. Generates an incident summary in plain English
2. Converts to speech using ElevenLabs TTS
3. Plays the audio alert

Example voice alerts:
- "Alert: Scraps n' Bids is down. HTTP 503 error. Investigating now."
- "Warning: Site response time is 4.2 seconds. Performance degraded."
- "All clear: Scraps n' Bids is healthy. Current auction: Tuesday's Pad Thai at $12.50."

### 3.5 Incident Response Actions

When incidents occur, the agent:

- **Logs incident** to console with timestamp, type, and details
- **Announces via voice** the current status
- **Suggests remediation** based on incident type

### 3.6 Status Report Command

On-demand status check that reports:

- Site up/down status
- Current auction item
- Current bid amount
- Response time
- Last incident (if any)

Delivered via voice using ElevenLabs.

---

## 4. Agent Architecture

Single Toolhouse agent with MCP integrations:

```
┌─────────────────────────────────────────────┐
│           SRE Agent (Toolhouse)             │
│                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐ │
│  │ Monitor │  │ Diagnose│  │ Communicate │ │
│  │  Loop   │→ │  Issue  │→ │   Status    │ │
│  └─────────┘  └─────────┘  └─────────────┘ │
│       │            │              │         │
└───────┼────────────┼──────────────┼─────────┘
        │            │              │
        ▼            ▼              ▼
   ┌─────────┐  ┌─────────┐  ┌───────────┐
   │ rtrvr   │  │ rtrvr   │  │ ElevenLabs│
   │ (scrape)│  │ (check) │  │   (TTS)   │
   └─────────┘  └─────────┘  └───────────┘
```

**MCP Servers:**
- rtrvr.ai - web scraping and automation
- ElevenLabs - text-to-speech

---

## 5. Demo Flow (5 minutes)

### Setup (before demo)
1. Agent is running and monitoring scraps-n-bids.vercel.app
2. Site is healthy, agent confirms via voice: "Monitoring active. Site healthy."

### Demo Script

**Minute 1: Show healthy monitoring**
- Agent reports current status via voice
- "Scraps n' Bids is online. Auctioning Tuesday's Pad Thai. Current bid: $8.50."

**Minute 2: Trigger incident**
- Break the site (deploy bad code, or simulate via mock)

**Minute 3: Agent detects and announces**
- Agent voice: "Alert: Scraps n' Bids is down. HTTP 503 error detected."
- Agent logs incident details to console

**Minute 4: Show diagnosis**
- Agent analyzes the error
- Agent voice: "Diagnosis: Application error. Recommend checking recent deployments."

**Minute 5: Recovery**
- Fix the site (redeploy, revert)
- Agent detects recovery
- Agent voice: "Recovery confirmed. Scraps n' Bids is back online. Auction resumed."

---

## 6. File Structure

```
sre-agent/
├── agent.py              # Main agent logic
├── monitor.py            # Health check functions
├── voice.py              # ElevenLabs TTS integration
├── config.py             # Configuration & constants
├── requirements.txt
├── .env.example
└── README.md
```

---

## 7. Configuration

```python
# config.py
TARGET_SITE = "https://scraps-n-bids.vercel.app"
CHECK_INTERVAL = 30  # seconds
SLOW_THRESHOLD = 2.0  # seconds
```

```bash
# .env
TOOLHOUSE_API_KEY=your_key
RTRVR_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
```

---

## 8. Success Criteria

**Must Have (for demo):**
- [ ] Agent monitors site and detects when it's down
- [ ] Agent uses rtrvr to scrape actual page content
- [ ] Agent speaks status updates via ElevenLabs
- [ ] Live demo showing detection → announcement → recovery

**Nice to Have:**
- [ ] Incident history log
- [ ] Vercel status page checking
- [ ] Automated redeploy trigger

---

## 9. API Integration Details

### rtrvr.ai Usage

```python
# Scrape auction status
rtrvr.execute("""
    Go to https://scraps-n-bids.vercel.app
    Extract:
    - The current auction item name
    - The current bid amount
    - The countdown timer value
    - The number of bids in the history section
    Return as JSON
""")
```

### ElevenLabs Usage

```python
# Generate voice alert
from elevenlabs import generate, play

audio = generate(
    text="Alert: Scraps n' Bids is down. Investigating.",
    voice="Rachel",
    model="eleven_flash_v2"
)
play(audio)
```

---

## 10. Timeline

**Hour 1:** Setup & Configuration
- Set up Toolhouse agent
- Configure rtrvr MCP connection
- Configure ElevenLabs MCP connection
- Test each integration individually

**Hour 2:** Core Agent Logic
- Implement health check loop
- Implement incident detection
- Wire up voice alerts
- Test happy path

**Hour 3:** Demo Polish
- Create incident simulation method
- Test full demo flow
- Record backup demo video
- Prepare talking points

---

## 11. Sponsor Integration Summary

| Sponsor | Role in Project |
|---------|-----------------|
| **Toolhouse** | Agent runtime & orchestration |
| **rtrvr.ai** | Web scraping to validate auction is running |
| **ElevenLabs** | Voice alerts for incident communication |
| **PDD** | (Optional) Generate agent prompts from this PRD |

---

## 12. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| rtrvr rate limits | Cache scrape results, reduce frequency |
| ElevenLabs latency | Use Flash model for speed |
| Site actually breaks | Have backup demo video ready |
| MCP connection issues | Test all connections before demo, have fallback to direct API |
