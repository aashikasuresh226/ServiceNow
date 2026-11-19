# HVAC Connect

![Shop portal and homeowner app](docs/screenshots/overview.png)

On-demand HVAC service, like Uber for HVAC. Homeowners describe the problem and snap a
photo of their unit. Claude reads the data plate and the likely issue, the app shows a
starting price, and books the qualified technician who can arrive soonest: free now, or at
their next opening (e.g. tomorrow 8 AM) if everyone is busy or off shift. HVAC shops manage technicians and availability (from ServiceTitan or
Housecall Pro later), accept jobs that land on each technician's calendar, and get paid
through Stripe. Technicians are invited by their shop and get their own app: today's jobs,
accept/decline, live location to the customer while driving, chat and calls.

| Part | Tech | Folder |
|---|---|---|
| API + matching engine | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic | `backend/` |
| Homeowner app + technician app | Expo (React Native), runs on web, iOS and Android (`/tech` for technicians) | `mobile/` |
| Shop portal | React + Vite (desktop web) | `shop-portal/` |

---

## Run it on Windows

### 1. Install the prerequisites (once)

- **Python 3.12 or newer**: https://www.python.org/downloads/ (tick *Add python.exe to PATH*)
- **Node.js 22 LTS or newer**: https://nodejs.org/
- An **authenticator app** on your phone (Google Authenticator, Microsoft Authenticator,
  1Password...). Every shop account requires one.

### 2. Set up (once, about 5 minutes)

Open PowerShell in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
```

### 3. Add your keys (any time)

Open `backend\.env` (created by setup from `.env.example`) and fill in the services you
have. Each one switches on when its keys are present; nothing is faked when they're missing.
See [Keys](#keys) below. Restart the API window after editing.

### 4. Start everything

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start-demo.ps1
```

It updates the database, prints which services are ON/OFF, then opens three windows (API,
shop portal, homeowner app) and two browser tabs:

| | URL | |
|---|---|---|
| Shop portal | http://localhost:5173 | **Create account** with Google or email + password, confirm the email link, then scan the QR code with your authenticator app |
| Homeowner app | http://localhost:8081 | **Continue with Google** or with a mobile number |
| Technician app | http://localhost:8081/tech/sign-in | Opened from the shop's invite email; later sign in with a texted code or Google |

To stop, close the three PowerShell windows. To delete **all** accounts and requests and
start over, close the API window and run `scripts\windows\reset-database.ps1`.

> On macOS/Linux, use `./scripts/setup.sh` and `./scripts/start-demo.sh`.

### Creating test accounts

There is no demo data. Create real accounts with real addresses:

1. **Shop owner (left window):** Create account. The password needs 8+ characters, a
   capital letter, a number and a symbol, and can't be a common or leaked password. Open the
   email link (until Firebase is set up, a **TEST MODE** button opens it), then turn on
   2-step verification with your authenticator app → **Shop & payouts**: enter the shop's
   real street address (with city, state and ZIP) → **Technicians**: add at least one tech
   with working hours → flip **Accept on-demand requests** at the top right.
2. **Technician (optional):** on **Technicians**, click **Invite to app**, enter their email
   and choose what they may do (accept/decline jobs, message and call customers, full day or
   next job only). Until Firebase is set up, the invite link is shown for you to send or open.
   The technician opens it on their phone, which confirms the email, and signs in with their
   mobile number (or Google). Use a private/incognito window to test it next to the homeowner.
3. **Homeowner (right window):** Continue with Google or a mobile number → enter a name and a
   real home address near the shop (within the tech's service radius, 25 km by default).
   Google users also confirm a mobile number with a texted code.
4. Start a request and book. The job appears in the shop's **Jobs**, on the tech's
   calendar (**Availability**) and in the technician app, where they accept it, tap **Start
   driving** (the homeowner sees a live map only from then until **Arrived**), chat, quote and
   finish.

Addresses are looked up with the free US Census geocoder, so made-up addresses are rejected.
For more homeowners, sign out (**Account → Sign out**) and use another number or Google
account. Until Twilio is connected, codes are shown on screen (**TEST MODE**), so any real
US number works. Numbers are checked with Google's libphonenumber, so impossible numbers
(e.g. area code 999) are rejected. With a Twilio *trial* account, codes only reach numbers you've verified in
Twilio.

### Troubleshooting

- **"Running scripts is disabled on this system"**: start the command with
  `powershell -ExecutionPolicy Bypass -File ...` exactly as shown above.
- **Windows Firewall prompt on first start**: allow access for Python and Node.
- **"Can't reach the server"**: the API window must be running; check it for errors.
- **"We couldn't find that address"**: include the house number, street, city, state and
  ZIP, e.g. `191 Peachtree St NE, Atlanta, GA 30303`.
- **"No technician available" / waitlisted**: open the shop portal's **Dashboard**. The
  *Ready for jobs* panel lists what's missing (shop not live, address not found, no working
  hours, not qualified for any equipment type) and each tech's next opening. Also check the
  home is inside the tech's service radius (25 km by default). The homeowner's waitlist
  screen says which of these applies.
- **Google button doesn't appear**: `HVAC_GOOGLE_CLIENT_IDS` isn't set, or the origin
  (`http://localhost:8081` / `http://localhost:5173`) isn't in the OAuth client's
  *Authorized JavaScript origins*.
- **A port is already in use**: close old windows and start again. The apps use ports
  8000, 5173 and 8081.
- **Photo analysis is slow or gives up**: free Gemini models are sometimes overloaded. The app
  waits at most 35 seconds (`HVAC_AI_TIME_BUDGET_SECONDS`), trying backup models, then
  continues without AI so the homeowner can still book.
- **The live map doesn't move**: the technician app must stay open while driving (location
  is shared in the foreground only), and the browser must be allowed to use location.

---

## Keys

All settings live in `backend/.env`. Run `.venv\Scripts\python.exe -m app.cli check` in
`backend\` to see what's on.

| Service | What it powers | Without it | Settings |
|---|---|---|---|
| **Google** (free) | "Continue with Google" for homeowners and shops | Only phone (homeowners) and email + password (shops) | `HVAC_GOOGLE_CLIENT_IDS` |
| **Twilio Verify** | Texted sign-in codes | Development only: the code is shown on screen | `HVAC_TWILIO_ACCOUNT_SID`, `HVAC_TWILIO_AUTH_TOKEN`, `HVAC_TWILIO_VERIFY_SERVICE_SID` |
| **Twilio Messaging** | Job-update texts (matched, on the way, done) | Updates show in the app only | `HVAC_TWILIO_FROM_NUMBER` or `HVAC_TWILIO_MESSAGING_SERVICE_SID` |
| **Gemini** (free tier) or **Anthropic** | "Snap your unit": AI reads the data plate and looks for visible problems | Photos go to the tech; no automatic diagnosis | `HVAC_GEMINI_API_KEY` or `HVAC_ANTHROPIC_API_KEY` |
| **Firebase** (free) | Emails that prove an address is real: shop sign-up and technician invites | Development only: the link is shown on screen | `HVAC_FIREBASE_API_KEY`, `HVAC_FIREBASE_PROJECT_ID` |
| **Neon** (free Postgres) | Hosted database with encrypted storage | A local SQLite file on your computer | `HVAC_DATABASE_URL` |
| **Stripe** | Card on file, hold at booking, charge at completion, shop payouts (Connect) | No card needed; the homeowner pays the shop directly | `HVAC_STRIPE_SECRET_KEY`, `HVAC_STRIPE_PUBLISHABLE_KEY`, `HVAC_STRIPE_WEBHOOK_SECRET` |

**Google:** Google Cloud Console → *APIs & Services* → *OAuth consent screen* (External,
add your email as a test user) → *Credentials* → *Create credentials* → *OAuth client ID* →
*Web application*. Add `http://localhost:8081` and `http://localhost:5173` under *Authorized
JavaScript origins* (add your real domains later). Copy the client ID.

**Twilio:** create an account → *Verify* → *Services* → *Create* → copy the Service SID
(`VA…`), plus your Account SID and Auth Token from the console home page. Only US (+1)
numbers can request codes (blocks SMS-pumping fraud; change with
`HVAC_SMS_ALLOWED_COUNTRY_CODES`). Sending job-update texts from a US number requires A2P 10DLC
registration in Twilio.

**Gemini (free):** sign in at https://aistudio.google.com/apikey with a Google account,
create a key, then run `powershell -ExecutionPolicy Bypass -File scripts\windows\set-gemini-key.ps1`
and paste it. It uses the same instructions, schema and checks as Claude. The free tier has
daily request limits (shown in AI Studio) and Google may use free-tier prompts to improve its
products; only the photos, symptoms and description are sent. If the default model
(`gemini-flash-lite-latest`) isn't offered, set `HVAC_GEMINI_MODEL` to a free model from AI
Studio. When both keys are set, Claude is used.

**Firebase (free):** console.firebase.google.com → *Add project* → *Build → Authentication*
→ *Get started* → *Sign-in method* → *Email/Password* → turn on **Email link (passwordless
sign-in)**. Then *Project settings → General → Your apps → Web* to register an app and copy
`apiKey` and `projectId`, and run
`powershell -ExecutionPolicy Bypass -File scripts\windows\set-firebase.ps1`. `localhost` is
already an authorized domain; add your real domain later (*Authentication → Settings*). The
free plan covers this; Firebase only sends the emails, and the API checks the proof.

**Neon (free Postgres):** neon.com → create a project → *Connect* → copy the connection
string, then run `powershell -ExecutionPolicy Bypass -File scripts\windows\set-database.ps1`.
Neon stores data encrypted (AES-256) and requires encrypted connections; the API verifies
Neon's certificate. Free plan: 1 GB per project, scales to zero after 5 idle minutes (the
first request after that takes a second), no deletion. The new database starts empty; to go
back to the local file, delete the `HVAC_DATABASE_URL` line in `backend\.env`.

**Anthropic:** console.anthropic.com → *API keys* (add credits under *Billing*). Then run
`powershell -ExecutionPolicy Bypass -File scripts\windows\set-anthropic-key.ps1` and paste
the key: it saves it in `backend\.env` (never uploaded to GitHub) and sends a test image to
Claude to prove it works. To check a real data plate photo yourself:
`.venv\Scripts\python.exe -m app.cli test-ai C:\path\to\plate.jpg` in `backend\`. The model
is `HVAC_ANTHROPIC_MODEL` (default `claude-sonnet-5-5`; `claude-haiku-5-5` is ~20× cheaper
and faster but reads worn labels less reliably).

**Stripe:** dashboard.stripe.com → *Developers* → *API keys* (start with test keys) and turn
on **Connect** (shops get Express accounts). For webhooks locally:
`stripe listen --forward-to localhost:8000/v1/webhooks/payments` and put the `whsec_…` it
prints in `HVAC_STRIPE_WEBHOOK_SECRET`. Test card: `4242 4242 4242 4242`, any future date
and CVC. Payments are **cards only** (no Apple Pay / Google Pay).

The apps read the API address from `mobile/.env` (`EXPO_PUBLIC_API_URL`) and
`shop-portal/.env` (`VITE_API_URL`).

---

## VC demo script (about 5 minutes)

Before the meeting, create one shop with two or three technicians (working hours covering
the meeting time) and one homeowner, with real addresses a few miles apart. Put the shop
portal on the left and the homeowner app on the right.

1. **Homeowner (right):** **Start a request** → **No cooling** → **Next** → upload a photo of
   a real unit's label → **Analyze my unit**. With the Anthropic key set, Claude reads the
   brand, model, serial, manufacture year (age), refrigerant and tonnage, and lists anything
   visibly wrong. Show the low-end estimate, labeled as an estimate.
2. **Matching (right):** **Continue** → **Find a technician** → the qualified tech who can
   arrive soonest is reserved for 3 minutes (after hours, it's their first opening the next
   morning) → **Confirm booking**.
3. **Shop (left):** the offer appears with a countdown. **Availability** already shows the job
   on the tech's calendar as *Pending*. **Accept & dispatch**: the calendar entry fills in
   with the customer's name and address, and the tech can subscribe to it from their phone
   (**Calendar link**).
4. **Job (both):** **Mark en route** → **Arrived on site** → enter a price → the homeowner
   approves → **Mark complete**. The homeowner rates the tech.
5. **Busy techs (both):** mark the closest tech **Busy 45m** and start another request: the
   app books whoever can arrive first, even if they're farther away.

---

## How it works

### Request lifecycle

```
draft ─► analyzed ─► proposed ──(homeowner confirms, card hold)──► offered ──(shop accepts)──► dispatched
            │            │ expires (3 min) → analyzed                 │ declined / no reply (2 min)
            │            ▼                                            ▼   → offered to next best tech
            └──► waitlisted ◄──────────────── nobody free ────────────┘   → or back to waitlist
dispatched ─► en_route ─► on_site ─► quoted ─► in_progress ─► completed (card charged, if Stripe is on)
```

Every status change goes through one function (`services/lifecycle.py`), which checks it
against the allowed transitions (`domain/state_machine.py`) and writes an audit event.

### Matching (`backend/app/domain/matching.py`)

**One request: earliest arrival.**
1. **Hard filters:** technician active; shop live (with payouts when Stripe is on); home
   inside the tech's service radius; qualified for the identified equipment type; EPA 608
   certified when refrigerant work is likely; hasn't declined this job.
2. **Availability:** for each remaining tech, find the earliest moment *t* they can leave so
   that the drive + a 90-minute job fit inside their shift without overlapping anything on
   their calendar (booked jobs, 3-minute reservations, time marked busy). Only "now", shift
   starts and ends of busy blocks can be the answer, so each tech takes O(B log B) for B
   calendar blocks (`domain/availability.py: earliest_window`).
3. **Pick** the minimum arrival time *t + drive time*. Ties: closer, then fewer jobs today
   (spreads work), then higher rating.

Every feasible tech is evaluated, so the arrival time is the earliest possible given
existing bookings. Off-hours requests are booked into the next shift (the shop then has
until an hour before the visit to accept), so homeowners are only waitlisted when no
qualified tech has an opening in the next 7 days; the waitlist screen says why.

**A backlog: the Hungarian algorithm.** The worker places waitlisted requests every few
seconds as a minimum-cost assignment (`domain/assignment.py`, O(n³)): rows are requests,
columns are techs, cost = minutes until arrival − minutes already waited. It serves as many
requests as possible with the least total waiting, favoring whoever waited longest, instead
of letting the first request in line take the tech a later request needed more. It's checked
against brute force in the tests.

Two homeowners can't book the same slot: the tech's row is locked during reservation (on
Postgres) and the slot is re-planned with fresh data before it's confirmed; requests use
optimistic version checks so the API and the worker can't overwrite each other.

### Choosing, rating and sharing

- **Who should come?** Before booking, homeowners pick *Soonest* (default), a **company**
  (its soonest technician) or a **specific technician**. Each option shows its earliest
  arrival from the same scheduling engine. If the pick has no opening, the app says so and
  lets them choose again; if a picked technician declines, the job goes to another tech at
  the same company, then to anyone. The shop sees "Customer chose you".
- **Ratings:** after the job, homeowners rate the technician and the company separately
  (1–5 stars, plus an optional comment). Shops see both on completed jobs; the company
  rating shows on the dashboard.
- **Share:** the completed screen has ready-made messages recommending the technician or
  the company (rating, shop phone, booking link) with Share…, Text, WhatsApp and Copy. The
  link opens a public page (`/p/technician/<id>` or `/p/shop/<id>`) with ratings, phone and
  a **Book** button; a friend who signs up gets that technician or company preselected.
  Set `HVAC_PUBLIC_APP_URL` to the homeowner app's real address once it's hosted.

### Technician app (`mobile/app/tech/`)

The shop invites a technician by email from **Technicians → Invite to app** and chooses:

| Permission | On | Off |
|---|---|---|
| Accept or decline job offers | Offers appear in the tech's app (the office can still respond in the portal) | The office accepts; jobs just appear. The tech can tap *I can't make this one*, which flags the job for the office |
| Message and call customers | Chat in the app; customer and tech see each other's number | The office handles messages and calls; the customer sees the shop's number |
| Schedule they can see | Full day, plus recent jobs | Only the current or next job |

On a job the technician sees the problem, the AI's read of the data plate and the photos
(name and address only after the job is accepted), then **Start driving** → **Arrived** →
price → **Mark job complete**. The homeowner's app shows a live OpenStreetMap map only between
*Start driving* and *Arrived*. Chat is shared by the homeowner, the shop office and (if
allowed) the technician, from acceptance until 48 hours after the job.

### Technician calendars

When the homeowner confirms, the job is put on the assigned tech's calendar as *Pending*
(no customer details yet). When the shop accepts, the entry gets the customer's name,
phone, address and the likely issue. Declines, expiries and cancellations remove it; a
completed job is trimmed to its finish time. The entries show on the **Availability**
board, count as busy time for matching, and are published to each tech's private
calendar feed (`.ics`) that they can subscribe to from Google Calendar, Apple Calendar or
Outlook. Google Calendar fetches feeds from Google's servers, so it needs the API on a
public URL; Apple Calendar and Outlook on the same computer work with localhost.

ServiceTitan and Housecall Pro sync is optional and shows as *Coming soon* until API access
is granted (`HVAC_SCHEDULING_INTEGRATIONS_ENABLED`). The adapters are in
`integrations/scheduling/`.

### Snap your unit (Claude)

Photos are auto-rotated and resized to 1568 px. Claude answers in a strict JSON schema
(structured outputs) with everything on the data plate: brand, model and serial (only if
legible), manufacture date and year, equipment type, tonnage, cooling/heating capacity,
voltage, phase, Hz, MCA, MOCP, compressor RLA/LRA, fan FLA, refrigerant and factory charge,
design pressure, SEER/SEER2/EER/HSPF/AFUE, gas type, plus visible problems, the likely issue
with confidence, a safety warning, and retake advice for unreadable labels. The server
validates every field, computes age from the year and adds plain notes (e.g. past typical
lifespan, R-22 phased out). **Prices never come from the model** (`domain/pricing.py`).

If Claude fails (bad key, no credits, network), the request still goes ahead: the
homeowner sees the reason on the diagnosis screen and the technician diagnoses on site. The
full error is in the API window.

**Scaling:** each API process allows `HVAC_AI_MAX_CONCURRENCY` (8) Claude calls at once;
the SDK retries rate-limit/overload errors with backoff; the instructions are prompt-cached;
each homeowner can run `HVAC_AI_ANALYSES_PER_HOUR` (15) analyses. Token usage is logged per
call.

### Payments (Uber-style, Stripe Connect)

- Sign-up saves a card with a **SetupIntent** (cards only); nothing is charged.
- Confirming a booking places a **hold** for the estimate (manual-capture PaymentIntent)
  routed to the shop's Connect account, with the platform fee attached.
- If the approved final price is higher than the hold, the hold is replaced with one for the
  final amount; **capture** happens when the shop marks the job complete.
- Declines, cancellations and re-matches release holds; uncaptured holds also expire on
  their own. Shops pick daily, weekly or manual payouts.
- Without Stripe keys, payments are off: no card is asked for, nothing is held or charged,
  and shops can go live without payouts.

### Security

**Customer data in the database is encrypted by the app** (`backend/app/core/fieldcrypt.py`):
homeowner names, phone numbers, emails and addresses; request addresses and descriptions;
technician phones and emails; chat messages; live locations. Photos are encrypted on disk.
The key is `HVAC_ENCRYPTION_KEY` in `backend/.env`, outside the database, so a copy of the
database (or the database password) shows only ciphertext. Phone and email also store a
keyed hash ("blind index") so sign-in can find an account without decrypting every row.
`setup.ps1` / `start-demo.ps1` create a private random key for your computer; if your
database already had data, it keeps the built-in development key until you reset the
database. **Back up `backend/.env`**: without the key, the data can't be read. In production,
keep the key in a secrets manager.

- **Passwords** (shops): 8+ characters with a capital letter, a number and a symbol; common
  passwords are rejected, and Have I Been Pwned's free *Pwned Passwords* service blocks
  leaked ones. Only the first 5 characters of the password's SHA-1 hash are sent
  (k-anonymity); the password never leaves the server. Stored with Argon2.
- **Shop accounts:** the email is proven with a link (Firebase), then a mandatory
  authenticator-app code (TOTP) at every sign-in, with a per-account guess limit. Typos like
  `gmial.com` and domains that can't receive mail are caught first.
- **Technicians** can't sign up on their own: the shop invites them by email. The invite is
  single-use, stored hashed and expires in 7 days; opening it only counts with Firebase's
  proof that the person controls that inbox, so the shop that sent it can't accept it for
  them. The company's permissions (accept/decline, contact customers, full day or next job)
  are enforced by the API, not just hidden. Removing access ends their sessions at once.
- **Live location** is accepted only while that job is *en route*, readable only by that
  job's homeowner, stored as a single encrypted position (no history) and deleted on arrival
  or cancel; a background job removes any leftovers.
- **Phone codes** are generated, sent and checked by Twilio Verify, with a resend cooldown,
  an hourly cap per number, an attempt limit, a per-IP limit and a US-only allowlist. Numbers
  are validated with libphonenumber. (Without Twilio, in development only, codes are
  generated locally and only a keyed hash is stored, keyed by the number's blind index.)
- **Google sign-in** verifies the ID token's signature, issuer, audience, expiry, a verified
  email and a single-use nonce. **Firebase** proofs are checked the same way (signature
  against Google's keys, issuer and audience = your Firebase project, verified email).
- Short-lived access tokens; rotating refresh tokens stored hashed. Reuse of an old refresh
  token ends every session in that family.
- Shops see a job's photos and AI summary before accepting, but not the homeowner's
  address or phone until dispatch. Homeowners can only read their own requests.
- Calls use the phone's own dialer (free). When a company lets a technician contact
  customers, the customer and technician see each other's real number; otherwise only the
  shop's number is shown.
- **Hosted Postgres** connections are encrypted and the certificate is verified.
- Security headers on every response; production startup refuses to run with dev secrets,
  test doubles, or without Twilio and Firebase.

### Code map

```
backend/app/
  domain/        Pure business rules, no I/O: matching, waitlist, availability, pricing, states
  services/      Use cases: auth, requests, matching, jobs, payments, shops, availability sync
  integrations/  Adapters behind interfaces: Claude, Stripe, Twilio Verify + Messaging,
                 Google sign-in, geocoding (US Census / Google / Mapbox), scheduling
                 (ServiceTitan, Housecall Pro), photo storage. *fake* modules are test-only.
  api/           HTTP routes, auth dependencies, response shaping (privacy rules live here)
  models/        Database tables          worker.py  Background loop
  container.py   Wires adapters from settings in one place; a service without keys is None (off)
mobile/app/      Screens (file-based routes); mobile/components, mobile/lib for shared code
shop-portal/src/ pages/, components/, lib/
```

---

## Development

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"   # test + lint tools (once)
.\.venv\Scripts\python.exe -m pytest -q          # 71 tests: matching, sign-in, calendars, full flows
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload   # API docs at http://localhost:8000/docs
```

Tests use a temporary SQLite database. Set `HVAC_TEST_DATABASE_URL` to a Postgres URL to
run the same suite against Postgres, as CI does (`.github/workflows/ci.yml`).

Changing a model: `python -m alembic revision --autogenerate -m "describe change"`, review
the file, then `python -m app.cli migrate`.

Type-checks for the apps: `npx tsc --noEmit` in `mobile/` and `shop-portal/`.

### Production

`docker compose up --build` runs Postgres, the API and the worker as separate processes,
which is how production should run (`HVAC_RUN_WORKER_IN_PROCESS=false`). Before going live:
set `HVAC_ENVIRONMENT=prod` with real secrets and providers, store photos in S3 or GCS
(implement `FileStorage`), put the API behind HTTPS with rate limiting at the gateway, and
host the portal's `dist/` and the Expo web build on a CDN.

---

## Known gaps / next steps

- **ServiceTitan and Housecall Pro** show as *Coming soon*. The adapters follow their
  published APIs but haven't been run against live accounts.
- **Outside services were tested against stand-ins**, not live accounts: Google sign-in is
  tested with real signed tokens and key sets, Twilio Verify and the Census geocoder against
  their documented responses, and the Claude prompt/parser with sample outputs. Try each one
  with your keys before a demo.
- **Business verification** for shops was removed for now, as requested. Payouts still
  require Stripe's identity and bank verification.
- **Google sign-in on the iOS/Android apps** needs native Google Sign-In with iOS and
  Android client IDs; until then the phone apps offer phone sign-in. Push notifications
  aren't built yet; updates reach homeowners through live screen refresh and texts.
- **Homeowners can't pick a time slot** yet: they get the earliest opening. Drive times are
  straight-line distance at 40 km/h; a routing API would make arrival times more accurate.
- **Live location is foreground-only:** the technician app must stay open while driving.
  Background tracking needs the native iOS/Android build with background location permission.
  Arrival times are straight-line estimates; a routing API would improve them.
- **Firebase email links open the web version of the app.** The native iOS/Android builds
  would need Firebase's mobile link handling.
- **Calls show real phone numbers** (free). Hidden "proxy" numbers would need a paid service
  such as Twilio.
- **Not yet built:** tips, refunds and disputes, an internal admin console, push
  notifications.
- **Card re-authorization** for a higher quote can need the homeowner to confirm in the app
  (3-D Secure); that error is surfaced, but there's no in-app confirmation flow yet.
