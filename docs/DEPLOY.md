# Deploy for free on Render

This puts the whole app online with real `https://` addresses, so the QR codes and invite
links work on any phone. Everything here has a free plan:

| What | Where | Free plan |
|---|---|---|
| API + background worker | Render web service `hvac-api` | 750 hours/month (enough for one service running all month). Sleeps after 15 minutes without visits; the monitor below keeps it awake. |
| Homeowner + technician app | Render static site `hvac-app` | Free, never sleeps |
| Shop portal | Render static site `hvac-portal` | Free, never sleeps |
| Database (and photos) | Neon Postgres | 0.5 GB |
| Keep-awake monitor | cron-job.org | Free, checks as often as every minute |

Photos are stored in the database (encrypted), because Render's free disk is wiped on every
restart. A photo is shrunk to at most 1600 px (about 150–300 KB) and its location data is
removed before saving.

## 1. Database (Neon), about 3 minutes

1. Sign in at https://neon.tech → **New project** (pick the US region closest to you).
2. **Connect** → copy the connection string (the *pooled* one is fine). It looks like
   `postgresql://user:password@ep-xxxx-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require`.

Keep it private: it's the password to all your data.

## 2. Render, about 10 minutes

1. Push the code to GitHub (already done if you use this repo).
2. Sign in at https://render.com with GitHub → **New** → **Blueprint** → pick the
   `ServiceNow` repository. Render reads `render.yaml` and shows the three services.
3. Fill in the values it asks for:
   - `HVAC_DATABASE_URL`: the Neon connection string from step 1.
   - `HVAC_GEMINI_API_KEY`: your Gemini key(s), comma-separated.
   - `HVAC_FIREBASE_API_KEY`: your Firebase Web API key.
4. **Apply**. The first build takes about 5–10 minutes. When all three are green:
   - Homeowner app: `https://hvac-app.onrender.com` (Render may add a suffix such as
     `hvac-app-abcd.onrender.com` if the name is taken; use what the dashboard shows).
   - Shop portal: `https://hvac-portal.onrender.com`
   - API: `https://hvac-api.onrender.com/v1/health` shows `{"status":"ok"}`.

5. **Connect the three addresses** (Render can't fill these in for you). Copy each
   service's address from the top of its page in the dashboard, then:

   | Service → Environment | Variable | Value (example) |
   |---|---|---|
   | hvac-app | `EXPO_PUBLIC_API_URL` | `hvac-api-ab12.onrender.com` |
   | hvac-portal | `VITE_API_URL` | `hvac-api-ab12.onrender.com` |
   | hvac-api | `HVAC_APP_HOST` | `hvac-app-cd34.onrender.com` |
   | hvac-api | `HVAC_PORTAL_HOST` | `hvac-portal-ef56.onrender.com` |

   Save, then on **hvac-app** and **hvac-portal** click **Manual Deploy → Clear build cache
   & deploy** (the API address is built into those sites). If the app says "Can't reach
   the server (…)", the address in brackets is the one it tried: it must be your API's
   address followed by `/v1`.

Secrets that Render generated for you (`HVAC_JWT_SECRET`, `HVAC_ENCRYPTION_KEY`,
`HVAC_ADMIN_TOKEN`) are in **Render → hvac-api → Environment**. Your admin key for
`/admin` in the portal is `HVAC_ADMIN_TOKEN`. **Never change `HVAC_ENCRYPTION_KEY`** once
there is data: it unlocks customer details and photos. Copy it somewhere safe (a password
manager) as a backup.

## 3. Firebase: allow the new addresses (1 minute)

Firebase console → **Authentication** → **Settings** → **Authorized domains** → **Add
domain**: add `hvac-portal.onrender.com` and `hvac-app.onrender.com` (the exact names from
Render). Without this, verification-email links won't open.

If you use Google sign-in: Google Cloud Console → **Credentials** → your OAuth client → add
`https://hvac-app.onrender.com` and `https://hvac-portal.onrender.com` under *Authorized
JavaScript origins*, then add `HVAC_GOOGLE_CLIENT_IDS` in Render's environment.

## 4. Keep the API awake (cron-job.org, free), 3 minutes

The free API goes to sleep after 15 minutes without visits, and the next visitor waits
about a minute. A monitor that visits every few minutes prevents that.

1. Make a free account at https://cron-job.org.
2. **Create cronjob**:
   - URL: `https://hvac-api.onrender.com/v1/health` (your API address).
   - Schedule: **every 5 minutes**.
   - Under *Advanced*: request method GET; turn on **notify on failure** if you want an
     email when it's down.
3. Save. The history should show `200 OK` every 5 minutes.

Why this is safe: `/v1/health` is a public page that returns only `{"status":"ok"}`. The
monitor needs no key or password and can't see or change any data. Never give a monitor
your admin key or database URL.

Why cron-job.org: free, no ads, made for exactly this, and it allows business use.
(UptimeRobot's free plan has been for non-commercial use only since late 2024. For uptime
alerts with business use you can also add a free **HetrixTools** or **StatusCake** monitor
on the same URL.)

A 5-minute visit keeps one service running 24/7, which uses about 744 of the 750 free hours a
month. Don't keep a second free web service awake on the same Render account, or the
hours run out before the month ends.

## 5. Try it

**The one link to share is the portal's address** (`https://hvac-portal-….onrender.com`).
It asks "Who are you?": homeowners go to the app to sign in or create an account, shop
owners create their shop account, and technicians are told to ask their shop for an
email invite (and to check Spam/Junk). Customers and technicians sign in separately, so one
phone can be signed in as both.

- Portal: create the shop account, confirm the email, turn on 2-step verification, add
  the shop address and a technician.
- Phone: open the portal's QR code (**Customers** → *Invite*) with the phone camera → the
  app opens → sign up with a mobile number and an authenticator app.
- On iPhone/Android: **Share → Add to Home Screen** makes it open like an app.

## Updating

Every push to GitHub redeploys automatically (database changes are applied on start).

## Good to know

- Accounts you made on your computer aren't copied: the online version starts empty.
- Training data: **Portal → /admin → Download training data** (a zip with photos and what
  the technician actually found and fixed, without names or addresses). Your privacy policy
  must say that photos and descriptions are used to improve the diagnosis.
- Texts (Twilio) are off; job updates show in the app. Sign-in doesn't use texts.
- Free limits: Neon 0.5 GB is roughly 2,000–3,000 jobs with photos. When you outgrow it,
  move photos to S3/Cloudflare R2 (implement `FileStorage`) or upgrade Neon.
- Render's free plan isn't meant for a real launch at scale (one small instance, slow cold
  builds). The $7/month Starter plan doesn't sleep, so you can drop the monitor.
