#!/bin/sh
# Status line: model │ minutes left before the prompt cache expires │ 5h and 7-day usage limits.
# Also forwards the payload to Orca's status line hook so its integration keeps working.

input=$(cat)

orca="$HOME/.orca/agent-hooks/claude-statusline.sh"
if [ -x "$orca" ]; then
  printf '%s' "$input" | /bin/sh "$orca" >/dev/null 2>&1 &
fi

green='\033[32m'; yellow='\033[33m'; red='\033[31m'; bold='\033[1m'; dim='\033[2m'; reset='\033[0m'
sep=" ${dim}│${reset} "

eval "$(printf '%s' "$input" | jq -r '
  @sh "model=\(.model.display_name // "")",
  @sh "warm=\(.prompt_cache.warm // "")",
  @sh "expires=\(.prompt_cache.expires_at // "")",
  @sh "five_pct=\(.rate_limits.five_hour.used_percentage // "")",
  @sh "five_reset=\(.rate_limits.five_hour.resets_at // "")",
  @sh "week_pct=\(.rate_limits.seven_day.used_percentage // "")",
  @sh "week_reset=\(.rate_limits.seven_day.resets_at // "")"
' 2>/dev/null)"

now=$(date +%s)
out=""

# Save Claude usage for the AI Usage menu bar app (fallback when its live API read fails). Every session reports its own last-seen
# snapshot, and idle sessions report stale ones, so merge per window instead of overwriting:
# the later window (resets_at) wins, and within the same window the higher percentage wins.
if [ -n "$five_pct$week_pct" ]; then
  usage_file="$HOME/.claude/usage-cache.json"
  previous=$usage_file; [ -s "$previous" ] || previous=/dev/null
  printf '%s' "$input" | jq -c --slurpfile old "$previous" '
    def pick(a; b):
      if a == null then b elif b == null then a
      elif (a.resets_at // 0) != (b.resets_at // 0) then (if (a.resets_at // 0) > (b.resets_at // 0) then a else b end)
      elif (a.used_percentage // 0) >= (b.used_percentage // 0) then a else b end;
    (($old[0] // {}).rate_limits // {}) as $o | (.rate_limits // {}) as $n
    | {rate_limits: (reduce (($o + $n) | keys[]) as $k ({}; .[$k] = pick($n[$k]; $o[$k]))),
       updated_at: (now | floor)}' > "$usage_file.$$" 2>/dev/null && mv "$usage_file.$$" "$usage_file"
fi

[ -n "$model" ] && out="${bold}${model}${reset}"

# Prompt cache
if [ -n "$expires" ]; then
  left=$((expires - now))
  if [ "$warm" != "true" ] || [ "$left" -le 0 ]; then
    cache="${red}cache expired${reset}"
  else
    mins=$(((left + 59) / 60))
    if [ "$mins" -le 5 ]; then color=$red
    elif [ "$mins" -le 15 ]; then color=$yellow
    else color=$green
    fi
    cache="${color}cache ${mins}m${reset}"
  fi
  out="${out:+$out$sep}$cache"
fi

# Usage limits: time left before reset + percentage used, colored by percentage
usage() {
  label=$1; pct=$2; reset_at=$3
  [ -n "$pct" ] || return
  pct=${pct%.*}
  if [ "$pct" -ge 80 ]; then color=$red
  elif [ "$pct" -ge 50 ]; then color=$yellow
  else color=$green
  fi
  when=""
  if [ -n "$reset_at" ]; then
    r=$((reset_at - now)); [ "$r" -lt 0 ] && r=0
    if [ "$r" -ge 86400 ]; then when="$((r / 86400))d"
    elif [ "$r" -ge 3600 ]; then when=$(printf '%dh%02d' $((r / 3600)) $((r % 3600 / 60)))
    else when="$((r / 60))m"
    fi
  fi
  out="${out:+$out$sep}${label}: ${color}${when:+$when }${pct}%${reset}"
}
usage "session" "$five_pct" "$five_reset"
usage "weekly" "$week_pct" "$week_reset"

printf "%b" "$out"
