# Kirana — Setup & Deployment

Written on the assumption you don't write code. Follow it in order. Step 3 is
the only genuinely fiddly one, and it's the one that makes the app work at all.

Budget about 2 hours the first time.

---

## What you need

- A computer that can stay on: an old laptop, a Raspberry Pi 4, or a cheap VPS
  (Hetzner CX22 is ~₹350/month). It just needs to run Docker.
- **Docker Desktop** — https://docs.docker.com/get-started/get-docker/
- **Android Studio** — https://developer.android.com/studio (free, ~1 GB)
- **Chrome** on a desktop, for step 3.
- A phone running Android 8 or newer.

---

## Step 1 — Start the backend

Open a terminal in the `kirana/backend` folder.

```bash
cp .env.example .env
```

Open `.env` in any text editor and replace the API key with a long random
string. Anything works — mash the keyboard, or run `openssl rand -hex 24`.
You'll paste this same string into the app in step 4.

```bash
docker compose up -d --build
curl http://localhost:8000/health
```

You should get back JSON listing four adapters. The backend is running. It
won't return useful prices yet — that's step 3.

---

## Step 2 — Find your coordinates

Open Google Maps, right-click your home, and click the numbers at the top of
the menu. You'll get something like `17.4474, 78.3762`. Write both down.

---

## Step 3 — Capture the store recipes

**This is the important step.** The four store recipes that ship with this
project are skeletons with placeholder values. They will not work until you
capture real requests from your own browser, because each store ties results to
*your* delivery address, set through *your* session cookies.

Do this once per store. Blinkit first — it's the most forgiving.

1. Open **blinkit.com** in Chrome and set your delivery address to your home.
2. Press **F12** to open DevTools. Click the **Network** tab. Click the
   **Fetch/XHR** filter button.
3. Click the 🚫 icon to clear the list.
4. Search the site for **amul**.
5. New rows appear. Click through them and look at the **Preview** tab on the
   right. You're looking for the one whose response contains product names and
   prices — usually named `search`, `products`, or `layout`.
6. Right-click that row → **Copy** → **Copy as cURL**.
7. In your terminal, in the `backend` folder:

```bash
python tools/capture.py --slug blinkit --name Blinkit \
    --term amul --lat 17.4474 --lon 78.3762 --paste
```

Paste, then press **Ctrl-D** (on Windows: **Ctrl-Z** then Enter).

The tool replays the request, finds the product array, guesses which fields are
the title and price, and writes `app/recipes/blinkit.json`. Read what it prints.
If it says it guessed `data.name.text → title`, that's what you want to see.

8. Repeat for the other three, changing `--slug` and `--name`:
   - `zepto` on **zeptonow.com**
   - `instamart` on **swiggy.com/instamart**
   - `bigbasket` on **bigbasket.com**

Then restart and test:

```bash
docker compose restart
curl -H "X-API-Key: YOUR_KEY" \
  "http://localhost:8000/search?q=milk&lat=17.4474&lon=78.3762" | head -50
```

**If a store returns nothing**, open `app/recipes/<store>.json` and compare the
`extract` paths against `/tmp/<store>_response.json`, which `capture.py` saved.
You're matching up names — no coding involved. Fix, `docker compose restart`,
try again.

**If a store returns 403**, it's blocking you. Delete its slug from
`KIRANA_STORES` in `.env` and move on. Don't fight it.

### One caveat about the cookies you just captured

Session cookies expire, typically in weeks to months. When a store silently
stops returning results, re-run `capture.py` for it. That's the maintenance
cost of this design, and it's the honest price of quick commerce having no API.

---

## Step 4 — Build the Android app

1. Open Android Studio → **Open** → select the `kirana/android` folder.
   First open takes a while; it's downloading Gradle.
2. Open `app/build.gradle.kts`. Find the two `buildConfigField` lines and edit:
   - `BASE_URL` → `"http://YOUR_COMPUTER_IP:8000/"` (keep the trailing slash).
     Find your IP with `ipconfig` on Windows or `ifconfig | grep inet` on
     Mac/Linux. It'll look like `192.168.1.42`.
   - `API_KEY` → the string from your `.env`.
3. Click **Sync Now** in the yellow bar at the top.
4. Plug in your phone with USB debugging on (Settings → About phone → tap Build
   number 7 times → Developer options → USB debugging), then press the green
   ▶ Run button.

The app installs and opens. Search for "milk".

**To put it on your friends' phones**: Build → Build Bundle(s)/APK(s) → Build
APK(s). Send them the resulting `app-debug.apk` and have them enable "install
from unknown sources". They'll each need the app pointed at your backend, which
means step 5.

---

## Step 5 — Access it away from home

Right now the app only works on your home wifi. Fix that with **Tailscale** — a
private network between your devices. It's free for personal use and far safer
than opening a port on your router.

1. Install Tailscale on the backend machine and sign in.
2. Run `tailscale ip -4`. You get an address like `100.101.102.103`.
3. Install the Tailscale app on each phone, sign in with the same account, and
   invite your friends to your tailnet.
4. Change `BASE_URL` in `app/build.gradle.kts` to that `100.x.y.z` address,
   rebuild the APK, redistribute.

**Do not port-forward 8000 on your router instead.** That puts a scraping
backend on the public internet under your home IP address. Tailscale takes ten
minutes and removes that entire category of problem.

---

## Step 6 — Living with it

| Symptom | What it means | What to do |
|---|---|---|
| One store missing from results | Cookies expired or API changed | Re-run `capture.py` for it |
| That store returns 403 | You're being blocked | Remove it from `KIRANA_STORES`. Don't escalate |
| Same product shown twice | Match threshold too high | Lower `KIRANA_MATCH_THRESHOLD` to 0.65 |
| Different products merged | Threshold too low | Raise to 0.80, or add the distinguishing word to `VARIANT_TOKENS` in `config.py` |
| App says "Can't reach the backend" | Backend down, or phone off the tailnet | `docker compose ps`, check Tailscale is connected |
| Prices look stale | Cache TTL | Lower `CACHE_TTL_SECONDS` in `config.py` |

Check `docker compose logs -f kirana` when something's confusing. Every store
failure is logged with its reason.

Run the tests after any change to matching:

```bash
cd backend && python -m pytest tests/ -q
```

---

## The rules, restated

You're operating in a gray area, and it stays gray only if you keep it small.

- **Don't publish this.** Not to the Play Store, not to a public GitHub repo
  with working recipes in it, not to a forum. A personal tool that four people
  use is a very different thing from a distributed one.
- **Don't raise the rate limits.** `REQUESTS_PER_SECOND_PER_STORE = 1.0` and a
  10-minute cache are what keep your footprint below a single human shopper's.
- **Don't resell or republish the price data.**
- **If a store blocks you, stop.** Disable it. Building around a block is the
  point where "I'm just looking at public prices" stops being true.
- **Buy through the real apps.** The deep links exist so the stores still get
  the sale. Kirana handles no carts, no logins, no payments.

If you ever want to grow this beyond your household, the honest path is a paid
aggregator API — you'd swap the adapter layer and keep everything else.
