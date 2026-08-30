#!/usr/bin/env bash
#
# preflight.sh — run this before every push.
#
# Checks that no secret is about to be committed, then runs the tests.
# Exits non-zero if anything is wrong, so it's safe to chain:
#
#     ./scripts/preflight.sh && git push
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
fail=0

say()  { printf "\n%s%s%s\n" "$DIM" "$1" "$OFF"; }
ok()   { printf "  %s✓%s %s\n" "$GREEN" "$OFF" "$1"; }
bad()  { printf "  %s✗ %s%s\n" "$RED" "$1" "$OFF"; fail=1; }
warn() { printf "  %s! %s%s\n" "$YELLOW" "$1" "$OFF"; }

if [ ! -d .git ]; then
  printf "%sNo git repo here yet. Run 'git init' first.%s\n" "$RED" "$OFF"
  exit 1
fi

# ---------------------------------------------------------------------------
say "1. Files git is about to publish"

# Stage everything so the check sees what a real commit would include.
git add -A >/dev/null 2>&1

tracked=$(git ls-files)

# Secrets. Note 'recipes/[a-z]*.json' matches blinkit.json (your captured
# session cookies) but NOT blinkit.example.json (placeholders, safe).
leaks=$(printf '%s\n' "$tracked" | grep -Ei \
  '(^|/)\.env$|recipes/[a-z]+\.json$|_response\.json$|\.(jks|keystore)$|local\.properties$|\.sqlite3' \
  || true)

if [ -n "$leaks" ]; then
  bad "These would be published and must not be:"
  printf '%s\n' "$leaks" | sed 's/^/      /'
  printf "\n      Fix: git rm --cached <file>   (keeps your local copy)\n"
else
  ok "No secrets staged"
fi

# Affirmatively confirm .gitignore is doing its job. Without this, a pass looks
# identical whether the rules worked or the files simply weren't there yet.
present=0
for f in backend/.env backend/data backend/blinkit_response.json; do
  [ -e "$f" ] && present=$((present + 1))
done
ignored=$(git status --porcelain --ignored 2>/dev/null | grep -c '^!!' || true)
if [ "$present" -gt 0 ]; then
  ok "$ignored local path(s) held back by .gitignore, including your .env"
else
  warn "No .env or captured recipes on disk yet — nothing to protect so far"
fi

examples=$(printf '%s\n' "$tracked" | grep -c 'recipes/.*\.example\.json$' || true)
if [ "$examples" -ge 1 ]; then
  ok "$examples recipe skeleton(s) tracked, as expected"
else
  warn "No *.example.json skeletons tracked — a fresh clone won't have templates"
fi

# ---------------------------------------------------------------------------
say "2. Scanning file contents for stray credentials"

# Catches a real key pasted somewhere .gitignore doesn't cover — most likely
# the Android build file, or a key hardcoded into a doc while debugging.
hits=$(git grep -nIE \
  'KIRANA_API_KEY[[:space:]]*=[[:space:]]*[A-Za-z0-9_-]{12,}|"API_KEY",[[:space:]]*"\\"[A-Za-z0-9]{12,}' \
  -- . ':(exclude).env.example' 2>/dev/null | grep -v 'put-a-long-random-string-here' || true)

if [ -n "$hits" ]; then
  bad "Possible hardcoded key:"
  printf '%s\n' "$hits" | sed 's/^/      /'
else
  ok "No hardcoded keys found"
fi

cookies=$(git grep -lIE '"(cookie|Cookie|_bb_addressinfo|gr_1_lat)"[[:space:]]*:[[:space:]]*"[^"]{25,}' \
  -- 'backend/app/recipes' 2>/dev/null | grep -v '\.example\.json$' || true)
if [ -n "$cookies" ]; then
  bad "Live session cookies in a tracked recipe: $cookies"
else
  ok "No live cookies in tracked recipes"
fi

# ---------------------------------------------------------------------------
say "3. Tests"

if command -v python3 >/dev/null 2>&1; then
  if (cd backend && python3 -m pytest tests/ -q >/tmp/kirana_tests.log 2>&1); then
    ok "$(grep -oE '[0-9]+ passed' /tmp/kirana_tests.log | head -1)"
  else
    bad "Tests failed — see /tmp/kirana_tests.log"
    tail -12 /tmp/kirana_tests.log | sed 's/^/      /'
  fi
else
  warn "python3 not found; skipped tests"
fi

# ---------------------------------------------------------------------------
say "4. Repo visibility"

remote=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$remote" ]; then
  warn "No remote set yet (that's fine before your first push)"
elif command -v gh >/dev/null 2>&1; then
  vis=$(gh repo view --json visibility -q .visibility 2>/dev/null || echo "unknown")
  case "$vis" in
    PRIVATE) ok "Remote repo is private" ;;
    PUBLIC)  bad "Remote repo is PUBLIC. Make it private: gh repo edit --visibility private" ;;
    *)       warn "Couldn't read visibility; check manually on github.com" ;;
  esac
else
  warn "Install the 'gh' CLI to auto-check the repo is private"
fi

# ---------------------------------------------------------------------------
echo
if [ "$fail" -eq 0 ]; then
  printf "%sSafe to push.%s  git push\n\n" "$GREEN" "$OFF"
else
  printf "%sDo not push yet.%s Fix the items marked ✗ above.\n\n" "$RED" "$OFF"
fi
exit "$fail"
