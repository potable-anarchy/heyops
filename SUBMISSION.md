# HeyOps

## Inspiration

Every on-call engineer knows the pain of getting paged at 3am, fumbling for a laptop, and staring at dashboards trying to figure out what's broken. We wanted to flip that experience on its head — what if you could just *ask* your infrastructure what's wrong and hear it talk back? The idea was simple: "Hey Siri" but for SRE. Press a button, ask a question in plain English, and get a spoken diagnosis with an actionable fix.

## What it does

HeyOps is a voice-controlled SRE agent that monitors a live web application in real time. It scrapes the target site using headless browser automation, runs health checks, detects incidents by severity (P1 through P3), diagnoses the root cause, and speaks the answer back to you — including a specific fix. You can interact with it by voice through a web dashboard or trigger checks on demand. It monitors our companion project, Scraps n' Bids (a live auction site), detecting issues like broken image paths, stalled auction transitions, missing item names, and site outages.

## How we built it

- **Backend:** Python with FastAPI, deployed as a serverless function on Vercel
- **Web scraping:** rtrvr.ai API to render JavaScript-heavy pages and extract the accessibility tree, giving us structured data about what's actually visible on the page
- **Voice input:** ElevenLabs Scribe v1 for speech-to-text transcription of user questions
- **Voice output:** ElevenLabs Flash v2.5 for text-to-speech, streaming back MP3 audio responses
- **Frontend:** A single-page dashboard with real-time status indicators, microphone recording via the MediaRecorder API, and an activity log
- **Logo generation:** Flux Schnell via mflux on a Mac Studio with Apple Silicon (MLX)

The diagnostic engine analyzes three data sources in parallel: HTTP health checks, scraped auction page data, and a dedicated status page. It pattern-matches against known failure modes (wrong image paths, excessive transition delays, missing auction elements) and generates both a human-readable diagnosis and a specific remediation step.

## Challenges we ran into

- **Speech-to-text API mismatch:** The ElevenLabs SDK's STT method signature changed — it expects a file-like object with `model_id`, not raw bytes. Getting the browser's WebM audio recording to work end-to-end with the API took debugging.
- **Scraping dynamic content:** The auction site is entirely JavaScript-rendered, so a simple HTTP GET returns nothing useful. We needed rtrvr.ai's headless browser to actually execute the JS and give us the accessibility tree. Then we had to write parsers that work against the tree format rather than raw HTML.
- **Environment variable newlines:** Vercel's `echo` piping added trailing newlines to API keys, causing `Invalid header value` errors that were hard to trace. Switching to `printf '%s'` fixed it.
- **Auction state detection:** The auction starts with $0.00 bids, which our original logic treated as "not running." We had to rethink what "running" means — the LIVE indicator matters more than the bid amount.

## Accomplishments that we're proud of

- Full voice loop works end-to-end: speak a question, get a spoken diagnosis with a concrete fix
- The diagnostic engine gives genuinely useful answers — it doesn't just say "something's wrong," it tells you which file to open and what line to change
- Deployed and working live on Vercel with real API integrations, not mocked
- Built the entire thing — both the auction site being monitored and the SRE agent monitoring it — in one hackathon session

## What we learned

- Accessibility trees from headless browsers are a surprisingly useful data format for automated monitoring — more structured than raw HTML, more reliable than screenshot-based approaches
- Voice interfaces for DevOps tooling feel natural once they work. The friction of "open laptop, find dashboard, interpret graph" versus "ask the question out loud" is significant.
- ElevenLabs' Scribe model handles noisy browser-recorded WebM audio well, which was not a given
- Serverless deployment of Python monitoring agents works but has tradeoffs — cold starts add latency to the first voice response

## What's next for HeyOps

- **Conversational context:** Remember previous checks so you can ask follow-up questions like "is that image issue from earlier fixed now?"
- **Auto-remediation:** Go beyond suggesting fixes to actually applying them — trigger a Vercel redeploy, push a config change, or roll back a bad deployment
- **Multi-site monitoring:** Monitor a fleet of sites from one dashboard, with voice alerts that tell you which site needs attention
- **Continuous background monitoring:** Run as a persistent service with push notifications and voice calls via ElevenLabs when something breaks, not just on-demand checks
- **Custom incident playbooks:** Let teams define their own diagnostic patterns and remediation steps so HeyOps learns their specific failure modes
