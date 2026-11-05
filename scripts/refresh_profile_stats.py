#!/usr/bin/env python3
"""Generate public language, streak, and contribution-mix cards."""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USERNAME = os.environ.get("GITHUB_USERNAME", "vivekanupindi")
TOKEN = os.environ["GITHUB_TOKEN"]
API_ROOT = "https://api.github.com"
OUTPUT = Path("assets/github-profile-stats.svg")
ACTIVITY_OUTPUT = Path("assets/github-activity-breakdown.svg")

INK = "#f2e9e4"
MUTED = "#b7a7a1"
LINE = "#573333"
RED = "#e50914"
AMBER = "#e5b68b"
TRACK = "#3a2a2a"
LANGUAGE_COLORS = [RED, AMBER, "#d78273", "#c7a18a", "#9d6a60", "#79534e"]


def request_json(url: str, payload: dict | None = None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vivekanupindi-profile-stats",
        "Authorization": f"Bearer {TOKEN}",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach GitHub API: {exc}") from exc


def fetch_public_repositories() -> list[dict]:
    repositories = []
    page = 1
    while True:
        batch = request_json(
            f"{API_ROOT}/users/{USERNAME}/repos"
            f"?type=owner&sort=updated&per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected repository response.")
        repositories.extend(
            repository
            for repository in batch
            if repository.get("owner", {}).get("login", "").lower() == USERNAME.lower()
            and not repository.get("private", False)
        )
        if len(batch) < 100:
            return repositories
        page += 1


def fetch_language_totals(repositories: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for repository in repositories:
        if repository.get("fork") or repository.get("archived"):
            continue
        url = repository.get("languages_url")
        if not url:
            continue
        languages = request_json(url)
        if not isinstance(languages, dict):
            raise RuntimeError(f"Unexpected language response for {repository.get('name')}.")
        for language, byte_count in languages.items():
            if isinstance(byte_count, int) and byte_count >= 0:
                totals[language] = totals.get(language, 0) + byte_count
    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))


def fetch_public_contribution_data(now: datetime) -> tuple[dict[date, int], dict[str, int]]:
    # GitHub limits contributionsCollection queries to a one-year period.
    start = now - timedelta(days=365)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    result = request_json(
        "https://api.github.com/graphql",
        {
            "query": query,
            "variables": {
                "login": USERNAME,
                "from": start.isoformat().replace("+00:00", "Z"),
                "to": now.isoformat().replace("+00:00", "Z"),
            },
        },
    )
    if result.get("errors"):
        message = "; ".join(error.get("message", "unknown error") for error in result["errors"])
        raise RuntimeError(f"GitHub GraphQL error: {message}")
    try:
        collection = result["data"]["user"]["contributionsCollection"]
        weeks = collection["contributionCalendar"]["weeks"]
        activity = {
            "commits": int(collection["totalCommitContributions"]),
            "issues": int(collection["totalIssueContributions"]),
            "pull_requests": int(collection["totalPullRequestContributions"]),
            "code_reviews": int(collection["totalPullRequestReviewContributions"]),
        }
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("GitHub returned an incomplete contribution collection.") from None

    counts = {}
    for week in weeks:
        for day in week.get("contributionDays", []):
            counts[date.fromisoformat(day["date"])] = int(day["contributionCount"])
    if not counts:
        raise RuntimeError("GitHub returned no contribution calendar days.")
    return counts, activity


def current_streak(counts: dict[date, int], today: date) -> str:
    cursor = today if counts.get(today, 0) > 0 else today - timedelta(days=1)
    streak = 0
    while counts.get(cursor, 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)

    # Mark a streak that reaches beyond the queried range as a lower bound.
    if streak and cursor < min(counts):
        return f"{streak}+"
    return str(streak)


def build_svg(languages: dict[str, int], streak: str, refreshed: str) -> str:
    top = list(languages.items())[:6]
    total_bytes = sum(languages.values())
    language_rows = []

    if not top or total_bytes == 0:
        language_rows.append(
            f'<text x="410" y="160" fill="{MUTED}" font-family="Arial,sans-serif" '
            'font-size="14">No public language data returned.</text>'
        )
    else:
        for index, (language, byte_count) in enumerate(top):
            y = 105 + index * 27
            share = byte_count / total_bytes * 100
            bar_width = 340 * share / 100
            color = LANGUAGE_COLORS[index % len(LANGUAGE_COLORS)]
            safe_language = html.escape(language)
            language_rows.append(
                f'<g><text x="410" y="{y + 10}" fill="{INK}" '
                f'font-family="Arial,sans-serif" font-size="12">{safe_language}</text>'
                f'<rect x="540" y="{y}" width="340" height="10" rx="5" fill="{TRACK}"/>'
                f'<rect x="540" y="{y}" width="{bar_width:.1f}" height="10" rx="5" fill="{color}"/>'
                f'<text x="900" y="{y + 10}" text-anchor="end" fill="{MUTED}" '
                f'font-family="Arial,sans-serif" font-size="11">{share:.1f}%</text></g>'
            )

    safe_refreshed = html.escape(refreshed)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="300"
 viewBox="0 0 960 300" role="img" aria-labelledby="title desc">
  <title id="title">Vivek Anupindi — GitHub languages and streak</title>
  <desc id="desc">Current public contribution streak: {html.escape(streak)} days. Top public repository languages by code bytes. Refreshed {safe_refreshed}.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#211818"/><stop offset="1" stop-color="#111112"/>
    </linearGradient>
    <radialGradient id="glow" cx="96%" cy="0%" r="70%">
      <stop offset="0" stop-color="{RED}" stop-opacity=".14"/>
      <stop offset="1" stop-color="{RED}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="960" height="300" rx="18" fill="url(#background)"/>
  <rect width="960" height="300" rx="18" fill="url(#glow)"/>
  <rect x=".5" y=".5" width="959" height="299" rx="17.5" fill="none" stroke="{LINE}"/>
  <text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif" font-size="19" font-weight="700">GitHub snapshot</text>
  <text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">Public data · refreshed {safe_refreshed}</text>
  <g transform="translate(28 88)">
    <rect width="330" height="166" rx="13" fill="#251c1c" stroke="{LINE}"/>
    <rect x="18" y="20" width="4" height="23" rx="2" fill="{RED}"/>
    <text x="32" y="36" fill="{AMBER}" font-family="Arial,sans-serif" font-size="11" font-weight="700" letter-spacing="1.3">CURRENT STREAK</text>
    <text x="20" y="101" fill="{INK}" font-family="Arial,sans-serif" font-size="46" font-weight="700">{html.escape(streak)}</text>
    <text x="20" y="124" fill="{MUTED}" font-family="Arial,sans-serif" font-size="12">consecutive days</text>
    <text x="20" y="147" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Public activity · UTC days</text>
  </g>
  <text x="390" y="101" fill="{AMBER}" font-family="Arial,sans-serif" font-size="11" font-weight="700" letter-spacing="1.3">LANGUAGES BY CODE SIZE</text>
  {''.join(language_rows)}
  <text x="28" y="280" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Streak ends today or yesterday; only publicly visible activity is counted.</text>
  <text x="932" y="280" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Top six languages · public, non-fork repos</text>
</svg>'''


def build_activity_svg(activity: dict[str, int], refreshed: str) -> str:
    categories = [
        ("code_reviews", "Code reviews"),
        ("issues", "Issues"),
        ("pull_requests", "Pull requests"),
        ("commits", "Commits"),
    ]
    total = sum(max(0, activity[key]) for key, _ in categories)
    values = {
        key: (max(0, activity[key]) / total * 100 if total else 0.0)
        for key, _ in categories
    }
    counts = {key: max(0, activity[key]) for key, _ in categories}
    cx, cy, radius = 480.0, 190.0, 105.0
    coords = {
        "code_reviews": (cx, cy - radius * values["code_reviews"] / 100),
        "issues": (cx + radius * values["issues"] / 100, cy),
        "pull_requests": (cx, cy + radius * values["pull_requests"] / 100),
        "commits": (cx - radius * values["commits"] / 100, cy),
    }
    polygon = ""
    markers = ""
    if total:
        points = " ".join(f"{coords[key][0]:.1f},{coords[key][1]:.1f}" for key, _ in categories)
        polygon = f'<polygon points="{points}" fill="{RED}" fill-opacity=".24" stroke="#ff7770" stroke-width="2"/>'
        markers = "".join(
            f'<circle cx="{coords[key][0]:.1f}" cy="{coords[key][1]:.1f}" r="4" fill="{AMBER}" stroke="{INK}" stroke-width="1.5"/>'
            for key, _ in categories
        )

    label_specs = {
        "code_reviews": (cx, 73, "middle"),
        "issues": (cx + radius + 25, cy + 4, "start"),
        "pull_requests": (cx, 321, "middle"),
        "commits": (cx - radius - 25, cy + 4, "end"),
    }
    labels = []
    for key, name in categories:
        x, y, anchor = label_specs[key]
        percent = f"{values[key]:.1f}%"
        count = f"{counts[key]:,}"
        labels.append(
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" fill="{INK}" '
            f'font-family="Arial,sans-serif" font-size="13" font-weight="700">{name}</text>'
            f'<text x="{x}" y="{y + 18}" text-anchor="{anchor}" fill="{AMBER}" '
            f'font-family="Arial,sans-serif" font-size="11">{percent} · {count}</text>'
        )
    safe_refreshed = html.escape(refreshed)
    description = "; ".join(
        f"{name}: {values[key]:.1f}% ({counts[key]} contributions)"
        for key, name in categories
    )
    if not total:
        description = "No public contributions recorded in the last 365 days."
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="350"
 viewBox="0 0 960 350" role="img" aria-labelledby="title desc">
  <title id="title">Public GitHub contribution mix</title>
  <desc id="desc">{html.escape(description)}. Trailing 365 days; refreshed {safe_refreshed}.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#211818"/><stop offset="1" stop-color="#111112"/>
    </linearGradient>
  </defs>
  <rect width="960" height="350" rx="18" fill="url(#background)"/>
  <rect x=".5" y=".5" width="959" height="349" rx="17.5" fill="none" stroke="{LINE}"/>
  <text x="28" y="34" fill="{INK}" font-family="Arial,sans-serif" font-size="18" font-weight="700">Contribution activity</text>
  <text x="28" y="55" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">Trailing 365 days · public contributions only · refreshed {safe_refreshed}</text>
  <g fill="none" stroke="{LINE}" stroke-width="1">
    <polygon points="{cx},{cy-radius*.75} {cx+radius*.75},{cy} {cx},{cy+radius*.75} {cx-radius*.75},{cy}"/>
    <polygon points="{cx},{cy-radius*.5} {cx+radius*.5},{cy} {cx},{cy+radius*.5} {cx-radius*.5},{cy}"/>
    <polygon points="{cx},{cy-radius*.25} {cx+radius*.25},{cy} {cx},{cy+radius*.25} {cx-radius*.25},{cy}"/>
  </g>
  <g stroke="{AMBER}" stroke-opacity=".65" stroke-width="1">
    <line x1="{cx}" y1="{cy-radius}" x2="{cx}" y2="{cy+radius}"/>
    <line x1="{cx-radius}" y1="{cy}" x2="{cx+radius}" y2="{cy}"/>
  </g>
  {polygon}
  {markers}
  {''.join(labels)}
</svg>'''


def main() -> None:
    now = datetime.now(timezone.utc)
    repositories = fetch_public_repositories()
    languages = fetch_language_totals(repositories)
    contribution_days, activity = fetch_public_contribution_data(now)
    streak = current_streak(contribution_days, now.date())
    refreshed = now.strftime("%d %b %Y · %H:%M UTC")

    # All API calls finish before either card is written, preserving prior files on failure.
    stats_svg = build_svg(languages, streak, refreshed)
    activity_svg = build_activity_svg(activity, refreshed)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(stats_svg, encoding="utf-8")
    ACTIVITY_OUTPUT.write_text(activity_svg, encoding="utf-8")
    print(f"Updated public profile cards: {len(languages)} languages, {streak} day streak, {sum(activity.values())} categorized contributions.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Profile stats refresh failed: {error}", file=sys.stderr)
        sys.exit(1)
