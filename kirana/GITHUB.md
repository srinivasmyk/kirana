# Pushing to GitHub

## Make the repo private

Use a **private** repo. This is the same reasoning as not publishing to the Play
Store: a public repo containing working recipes for four named retailers is
findable by those retailers, and it's the artifact that turns "someone checking
prices" into "someone distributing a scraping tool." Private costs nothing and
removes the issue.

On GitHub: **New repository → Private**. Don't initialise it with a README,
since you already have one.


## Before you start: git and a GitHub login

Two things trip people up here, and neither is about your code.

**1. Is git installed?** Run `git --version`. If it errors:
- **Windows** — install [Git for Windows](https://git-scm.com/download/win). It
  gives you "Git Bash", which is where you should run every command in this file.
- **Mac** — run `xcode-select --install`.
- **Linux** — `sudo apt install git`.

**2. GitHub no longer accepts your account password over git.** It was removed
in 2021, so if you type your password when prompted, it will fail with a
confusing error. Use the GitHub CLI instead — it handles login, and it can
create the repo for you:

```bash
# Install: https://cli.github.com  (winget install GitHub.cli / brew install gh)
gh auth login
```

Pick "GitHub.com", then "HTTPS", then "Login with a web browser". It prints a
code, opens your browser, and you're done. Git will use those credentials from
then on.

## Run the safety check

```bash
./scripts/preflight.sh
```

It stages everything, checks that no `.env`, captured recipe, saved response or
signing key is about to be published, greps the actual file contents for a
hardcoded key, and runs the tests. It exits non-zero on failure, so you can
chain it:

```bash
./scripts/preflight.sh && git push
```

Get into the habit of running that instead of a bare `git push`. It takes two
seconds and it is the thing standing between you and a leaked session cookie.

## Before your first commit

Run this from the `kirana` folder. It shows exactly what git would upload:

```bash
git init
git add -A
git status --short
```

Read that list. Then confirm nothing sensitive is in it:

```bash
git ls-files | grep -Ei '\.env$|recipes/[a-z]+\.json$|_response\.json|\.jks$|\.keystore$'
```

**That command must print nothing.** If it prints anything, stop and tell me
what it printed before committing.

Note the pattern `recipes/[a-z]+\.json$` — it deliberately matches
`blinkit.json` (your captured recipe, secret) but not
`blinkit.example.json` (the placeholder skeleton, safe and tracked).

## Then push

With the `gh` CLI, this creates the private repo and pushes in one step:

```bash
git commit -m "Kirana: grocery price comparison"
git branch -M main
gh repo create kirana --private --source=. --push
```

Or, if you made the repo on github.com yourself:

```bash
git commit -m "Kirana: grocery price comparison"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/kirana.git
git push -u origin main
```

## After the first push

Open the repo on github.com and confirm three things by eye. The automated
checks are good, but thirty seconds of looking is worth it once:

1. You see `backend/app/recipes/blinkit.example.json` and **no** `blinkit.json`.
2. There is no `.env` anywhere.
3. The repo header says **Private**.

The Actions tab will show a "tests" run. It runs the 13 matcher tests on every
push and separately fails the build if a secret file ever gets tracked — a
backstop in case you push from a machine where you skipped preflight.

## About a licence

Don't add one. GitHub will offer you MIT or Apache; both are grants of
permission for other people to use and redistribute this. That is the opposite
of what you want here. With no licence file, default copyright applies and all
rights stay with you, which suits a private personal tool.

## What's protected and why

| Path | Status | Why |
|---|---|---|
| `backend/.env` | ignored | Your API key / web password |
| `backend/app/recipes/*.json` | **ignored** | Live session cookies for the four stores |
| `backend/app/recipes/*.example.json` | tracked | Placeholders only, safe to share |
| `*_response.json` | ignored | Saved store responses; often contain your address |
| `backend/data/` | ignored | Your price history database |
| `*.jks`, `*.keystore` | ignored | Android signing keys |

The recipe split is the important one. `capture.py` writes `blinkit.json`, which
holds your logged-in session. The tracked `blinkit.example.json` holds
placeholder text. The adapter loader skips anything ending in `.example.json`,
so the two never collide.

## One thing to check manually

`android/app/build.gradle.kts` contains two placeholder lines:

```kotlin
buildConfigField("String", "BASE_URL", "\"http://100.64.0.1:8000/\"")
buildConfigField("String", "API_KEY", "\"put-a-long-random-string-here\"")
```

If you edit these with your real key and commit, the key lands in git history.
Either leave the placeholders and re-edit after each clone, or delete the
`android/` folder entirely — you're using the web app now, so nothing depends
on it.

## If you ever leak a secret

Don't just delete the file and commit. Git keeps history.

1. Rotate the secret first — change `KIRANA_API_KEY`, and log out of the store
   websites in your browser to kill the captured sessions.
2. Then clean history (`git filter-repo`) or, on a private solo repo, delete the
   repo and push fresh.

Rotation matters more than history cleanup. A cookie you've invalidated is
harmless even if it's still in a commit.
