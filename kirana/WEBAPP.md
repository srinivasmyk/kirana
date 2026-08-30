# Kirana — running the web app

The web app replaces steps 4 and 5 of SETUP.md. Steps 1–3 (start the backend,
find your coordinates, capture the store recipes) are unchanged and still
required — without recipes there are no prices to show.

## What changed from the Android version

| | Android | Web |
|---|---|---|
| Distribution | Build an APK, sideload on each phone | Send a URL |
| Updates | Rebuild, resend, everyone reinstalls | Edit a file, they reload |
| Google's rules | Play policies, developer verification | None apply |
| Install to home screen | Yes | Yes, via "Add to Home Screen" |
| Location | Android permission | Needs HTTPS — see below |

The app is served by the same FastAPI process as the API, on the same origin.
That means no CORS to configure, one container, one URL. There is no build
step — `web/index.html` is a single file you can open in any text editor.

## Step 4 — Set a password and start it

The password is just `KIRANA_API_KEY` from `backend/.env`. You already set it in
step 1. Restart so the web files get picked up:

```bash
cd backend
docker compose up -d --build
```

Open `http://localhost:8000` on the same machine. You should get a sign-in box.
Enter the key, and you're in.

The browser never holds that key. It's posted once to `/login`, which sets an
HttpOnly cookie — meaning JavaScript can't read it and it won't show up in
DevTools. Changing `KIRANA_API_KEY` signs everyone out.

## Step 5 — Serve it over HTTPS (do not skip this)

**The browser will not give the app your location over plain HTTP.**
`navigator.geolocation` only exists in a secure context, so on
`http://100.x.y.z:8000` it is simply undefined. The app detects this and offers
a manual coordinate entry box as a fallback, which works fine but is annoying.

Tailscale solves it in one command — it issues a real Let's Encrypt certificate
for your machine and terminates TLS for you:

```bash
tailscale serve --bg 8000
tailscale serve status
```

That prints a URL like `https://your-machine.your-tailnet.ts.net`. It's a real
HTTPS URL with a valid certificate, reachable only by devices on your tailnet.
Geolocation works, the service worker registers, and the app becomes installable.

Give that URL to your friends after adding them to your tailnet. They install
Tailscale, open the link, enter the password once.

**Don't put this on a public domain instead.** A public HTTPS URL is a scraping
backend on the open internet under your name, which is exactly the exposure that
made the Play Store a bad idea.

## Step 6 — Install to the home screen

It's a PWA, so it gets an icon and opens without browser chrome:

- **Android/Chrome**: menu → Add to Home screen
- **iPhone/Safari**: Share → Add to Home Screen

The service worker caches only the page shell, never prices. A price comparison
app that shows you yesterday's numbers would be worse than one that shows you
nothing.

## Editing the design

Everything is in `backend/web/index.html`. The CSS variables at the top are the
whole palette:

```css
--mint: #3DDC97;   /* means "cheapest". Used for nothing else. */
--blinkit: #F8CB46;
--zepto: #8B5CF6;
```

Change a colour, save, reload. The file is mounted into the container, so no
rebuild is needed — though you may need a hard reload (Ctrl-Shift-R) to get past
the service worker cache.

## About the price bars

Each store's bar length shows how much *more* it costs than the cheapest store
in that row, not the absolute price. A 25% premium fills the track.

This is deliberate. Scaling bars to the absolute price made ₹27 and ₹31 render
at 87% and 100% — visually identical, which told you nothing. Now a ₹27/29/31
spread reads as short/medium/long, and a ₹27/28 spread stays visibly tight. The
bar answers "is this worth switching apps for?" at a glance.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Location needs HTTPS" | Running over plain http | Set up `tailscale serve`, or tap "change" and paste coordinates |
| Sign-in loops | Cookie blocked | Don't use private browsing; check the clock is right |
| Old version after editing | Service worker cache | Hard reload, or DevTools → Application → Unregister |
| Empty results, no error | Recipes not captured | SETUP.md step 3 |
| One store missing | Cookies expired | Re-run `capture.py` for it |

## The Android app

`android/` still works and is unchanged — it talks to the same API using the
`X-API-Key` header. Keep it or delete the folder; nothing else depends on it.
