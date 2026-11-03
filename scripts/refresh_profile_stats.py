#!/usr/bin/env python3
"""Generate self-hosted GitHub profile cards from GitHub API data."""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USERNAME = os.environ.get("GITHUB_USERNAME", "vivekanupindi")
WRITE_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CONTRIBUTION_TOKEN = os.environ.get("PROFILE_STATS_TOKEN") or WRITE_TOKEN
API_ROOT = "https://api.github.com"
OUTPUT = Path(os.environ.get("STATS_OUTPUT_DIR", "assets"))
INK, MUTED, LINE = "#f2e9e4", "#b7a7a1", "#573333"
RED, AMBER, TRACK = "#e50914", "#e5b68b", "#3a2a2a"
LEVEL_COLORS = {"NONE": "#2b2323", "FIRST_QUARTILE": "#633033", "SECOND_QUARTILE": "#8d383b", "THIRD_QUARTILE": "#bd4245", "FOURTH_QUARTILE": RED}


def api_get(url: str):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "vivekanupindi-profile-stats"}
    if WRITE_TOKEN:
        headers["Authorization"] = f"Bearer {WRITE_TOKEN}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API returned HTTP {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach GitHub API: {exc}") from exc


def graphql(query: str, variables: dict):
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = Request("https://api.github.com/graphql", data=payload, headers={
        "Accept": "application/vnd.github+json", "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "vivekanupindi-profile-stats",
        "Authorization": f"Bearer {CONTRIBUTION_TOKEN}",
    })
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub GraphQL returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach GitHub GraphQL API: {exc}") from exc
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL error: " + "; ".join(e.get("message", "unknown error") for e in result["errors"]))
    return result["data"]["user"]["contributionsCollection"]


def fetch_public_repositories():
    repositories, page = [], 1
    while True:
        batch = api_get(f"{API_ROOT}/users/{USERNAME}/repos?type=owner&sort=updated&per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected repository response.")
        repositories.extend(r for r in batch if r.get("owner", {}).get("login", "").lower() == USERNAME.lower() and not r.get("private", False))
        if len(batch) < 100:
            break
        page += 1
    return repositories


def fetch_language_totals(repositories):
    totals = {}
    for repository in repositories:
        if repository.get("fork") or repository.get("archived"):
            continue
        languages_url = repository.get("languages_url")
        if not languages_url:
            continue
        data = api_get(languages_url)
        if isinstance(data, dict):
            for language, byte_count in data.items():
                if isinstance(byte_count, int) and byte_count >= 0:
                    totals[language] = totals.get(language, 0) + byte_count
    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))


def fetch_contributions(now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount contributionLevel } }
          }
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          restrictedContributionsCount
        }
      }
    }
    """
    collection = graphql(query, {"login": USERNAME, "from": start.isoformat(), "to": now.isoformat()})
    calendar = collection["contributionCalendar"]
    weeks = calendar.get("weeks", [])
    if not weeks or not isinstance(calendar.get("totalContributions"), int):
        raise RuntimeError("GitHub returned an incomplete contribution calendar.")
    return {
        "total": calendar["totalContributions"],
        "weeks": weeks,
        "commits": collection["totalCommitContributions"],
        "issues": collection["totalIssueContributions"],
        "pull_requests": collection["totalPullRequestContributions"],
        "reviews": collection["totalPullRequestReviewContributions"],
        "restricted": collection.get("restrictedContributionsCount", 0),
    }


def fmt_number(value):
    return f"{int(value):,}"


def build_stats_svg(metrics, refreshed):
    width, height, card_width, card_height, gap = 960, 284, 211, 112, 20
    labels = [("PUBLIC REPOS", metrics["repositories"], "Public repositories owned"), ("STARS", metrics["stars"], "Across public repositories"), ("FORKS", metrics["forks"], "Across public repositories"), ("FOLLOWERS", metrics["followers"], "Public GitHub followers")]
    cards = []
    for i, (label, value, note) in enumerate(labels):
        x, value_text = 28 + i * (card_width + gap), fmt_number(value)
        cards.append(f'''<g transform="translate({x},91)"><rect width="{card_width}" height="{card_height}" rx="13" fill="#251c1c" stroke="{LINE}"/><rect x="16" y="16" width="4" height="22" rx="2" fill="{RED}"/><text x="31" y="32" fill="{AMBER}" font-family="Arial,sans-serif" font-size="11" font-weight="700" letter-spacing="1.4">{html.escape(label)}</text><text x="17" y="76" fill="{INK}" font-family="Arial,sans-serif" font-size="31" font-weight="700">{html.escape(value_text)}</text><text x="17" y="98" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">{html.escape(note)}</text></g>''')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"><title id="title">Vivek Anupindi — public GitHub statistics</title><desc id="desc">Public repository, star, fork, and follower counts from GitHub.</desc><defs><linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#211818"/><stop offset="1" stop-color="#111112"/></linearGradient><radialGradient id="glow" cx="96%" cy="0%" r="70%"><stop offset="0" stop-color="{RED}" stop-opacity=".16"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient></defs><rect width="{width}" height="{height}" rx="18" fill="url(#background)"/><rect width="{width}" height="{height}" rx="18" fill="url(#glow)"/><rect x=".5" y=".5" width="959" height="283" rx="17.5" fill="none" stroke="{LINE}"/><text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif" font-size="19" font-weight="700">GitHub at a glance</text><text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">Public profile snapshot · {html.escape(USERNAME)}</text>{''.join(cards)}<text x="28" y="252" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">PUBLIC DATA ONLY</text><text x="932" y="252" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Refreshed {html.escape(refreshed)}</text></svg>'''


def build_languages_svg(language_totals, refreshed):
    width, height = 960, 292
    top, colors = list(language_totals.items())[:6], [RED, AMBER, "#d78273", "#c7a18a", "#9d6a60", "#79534e"]
    total_bytes = sum(value for _, value in top)
    rows = []
    if not top or total_bytes <= 0:
        rows.append(f'<text x="34" y="143" fill="{MUTED}" font-family="Arial,sans-serif" font-size="14">Language data will appear after the first successful refresh.</text>')
    else:
        for i, (language, byte_count) in enumerate(top):
            y, share, color = 94 + i * 29, byte_count / total_bytes * 100, colors[i % len(colors)]
            rows.append(f'<g><text x="34" y="{y+10}" fill="{INK}" font-family="Arial,sans-serif" font-size="12">{html.escape(language)}</text><rect x="205" y="{y-2}" width="560" height="12" rx="6" fill="{TRACK}"/><rect x="205" y="{y-2}" width="{max(4, 560*share/100):.1f}" height="12" rx="6" fill="{color}"/><text x="795" y="{y+10}" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">{share:.1f}%</text></g>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"><title id="title">Vivek Anupindi — language breakdown</title><desc id="desc">Top languages by code size in non-fork, non-archived public repositories.</desc><defs><linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#211818"/><stop offset="1" stop-color="#111112"/></linearGradient><radialGradient id="glow" cx="96%" cy="0%" r="70%"><stop offset="0" stop-color="{RED}" stop-opacity=".12"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient></defs><rect width="960" height="292" rx="18" fill="url(#background)"/><rect width="960" height="292" rx="18" fill="url(#glow)"/><rect x=".5" y=".5" width="959" height="291" rx="17.5" fill="none" stroke="{LINE}"/><text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif" font-size="19" font-weight="700">Languages across public projects</text><text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">Repository language byte counts · forks and archived repos excluded</text>{''.join(rows)}<text x="28" y="267" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">TOP SIX LANGUAGES BY CODE SIZE</text><text x="932" y="267" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Refreshed {html.escape(refreshed)}</text></svg>'''


def build_contributions_svg(data, refreshed, private_token_configured=False):
    width, height = 960, 392
    weeks = data["weeks"][-53:]
    cell, step, x0, y0 = 11, 15, 86, 121
    month_labels, squares = [], []
    previous_month = None
    for col, week in enumerate(weeks):
        days = week.get("contributionDays", [])
        for row, day in enumerate(days[:7]):
            date = day["date"]
            month_key = date[:7]
            if month_key != previous_month:
                month_name = datetime.strptime(date, "%Y-%m-%d").strftime("%b")
                month_labels.append(f'<text x="{x0+col*step}" y="107" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">{month_name}</text>')
                previous_month = month_key
            count = int(day.get("contributionCount", 0))
            level = day.get("contributionLevel", "NONE")
            color = LEVEL_COLORS.get(level, LEVEL_COLORS["NONE"])
            label = f'{count} contributions on {date}'
            squares.append(f'<rect x="{x0+col*step}" y="{y0+row*step}" width="{cell}" height="{cell}" rx="2" fill="{color}"><title>{html.escape(label)}</title></rect>')
    weekdays = ''.join(f'<text x="42" y="{y0+r*step+9}" fill="{MUTED}" font-family="Arial,sans-serif" font-size="9">{label}</text>' for r, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")])
    mode = ("Private/internal counts included when enabled in GitHub's profile settings." if private_token_configured else "Public contributions only · private/internal activity requires the optional read:user token.")
    cards = [("COMMITS", data["commits"]), ("ISSUES", data["issues"]), ("PULL REQUESTS", data["pull_requests"]), ("REVIEWS", data["reviews"])]
    breakdown = []
    for i, (label, value) in enumerate(cards):
        x = 28 + i * 231
        breakdown.append(f'<g transform="translate({x},260)"><rect width="211" height="68" rx="11" fill="#251c1c" stroke="{LINE}"/><rect x="14" y="15" width="3" height="19" rx="2" fill="{RED}"/><text x="26" y="28" fill="{AMBER}" font-family="Arial,sans-serif" font-size="10" font-weight="700" letter-spacing="1">{label}</text><text x="14" y="55" fill="{INK}" font-family="Arial,sans-serif" font-size="20" font-weight="700">{fmt_number(value)}</text></g>')
    total = fmt_number(data["total"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"><title id="title">Vivek Anupindi — GitHub contribution activity</title><desc id="desc">{total} contributions in the last 365 days, shown as a weekly calendar heatmap, with commit, issue, pull request, and review totals. {html.escape(mode)}</desc><defs><linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#211818"/><stop offset="1" stop-color="#111112"/></linearGradient><radialGradient id="glow" cx="96%" cy="0%" r="70%"><stop offset="0" stop-color="{RED}" stop-opacity=".13"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient></defs><rect width="{width}" height="{height}" rx="18" fill="url(#background)"/><rect width="{width}" height="{height}" rx="18" fill="url(#glow)"/><rect x=".5" y=".5" width="959" height="391" rx="17.5" fill="none" stroke="{LINE}"/><text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif" font-size="19" font-weight="700">Contribution activity</text><text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">Trailing 365 days · contribution calendar</text><text x="930" y="48" text-anchor="end" fill="{AMBER}" font-family="Arial,sans-serif" font-size="25" font-weight="700">{total}</text><text x="930" y="66" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">TOTAL CONTRIBUTIONS</text>{''.join(month_labels)}{weekdays}{''.join(squares)}<text x="28" y="246" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">ACTIVITY BREAKDOWN</text>{''.join(breakdown)}<text x="28" y="356" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">{html.escape(mode)}</text><text x="932" y="356" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Refreshed {html.escape(refreshed)}</text><text x="738" y="372" fill="{MUTED}" font-family="Arial,sans-serif" font-size="9">Less</text>{''.join(f'<rect x="{772+i*15}" y="363" width="11" height="11" rx="2" fill="{color}"/>' for i, color in enumerate([LEVEL_COLORS["NONE"], LEVEL_COLORS["FIRST_QUARTILE"], LEVEL_COLORS["SECOND_QUARTILE"], LEVEL_COLORS["THIRD_QUARTILE"], LEVEL_COLORS["FOURTH_QUARTILE"]]))}<text x="855" y="372" fill="{MUTED}" font-family="Arial,sans-serif" font-size="9">More</text></svg>'''


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Retrieve all source data before writing, so failures leave the prior cards intact.
    profile = api_get(f"{API_ROOT}/users/{USERNAME}")
    repositories = fetch_public_repositories()
    languages = fetch_language_totals(repositories)
    contributions = fetch_contributions()
    active = [r for r in repositories if not r.get("archived")]
    metrics = {"repositories": len(active), "stars": sum(r.get("stargazers_count", 0) for r in active), "forks": sum(r.get("forks_count", 0) for r in active), "followers": profile.get("followers", 0)}
    refreshed = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    cards = {
        "github-public-stats.svg": build_stats_svg(metrics, refreshed),
        "github-language-breakdown.svg": build_languages_svg(languages, refreshed),
        "github-contributions.svg": build_contributions_svg(contributions, refreshed, bool(os.environ.get("PROFILE_STATS_TOKEN"))),
    }
    for name, svg in cards.items():
        (OUTPUT / name).write_text(svg, encoding="utf-8")
    print("Updated public GitHub profile cards and contribution activity.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Profile statistics refresh failed: {error}", file=sys.stderr)
        sys.exit(1)

