#!/usr/bin/env python3
"""Generate self-hosted GitHub profile stats cards from public GitHub API data.

No third-party stats image service is used. The GitHub Actions workflow runs
this script on a schedule and commits the resulting SVG files to the repo.
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USERNAME = os.environ.get("GITHUB_USERNAME", "vivekanupindi")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_ROOT = "https://api.github.com"
OUTPUT = Path("assets")
INK = "#f2e9e4"
MUTED = "#b7a7a1"
LINE = "#573333"
RED = "#e50914"
AMBER = "#e5b68b"
TRACK = "#3a2a2a"


def api_get(url: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vivekanupindi-profile-stats",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"GitHub API returned HTTP {exc.code} for {url}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach GitHub API: {exc}") from exc


def fetch_public_repositories():
    repositories = []
    page = 1

    while True:
        url = (
            f"{API_ROOT}/users/{USERNAME}/repos"
            f"?type=owner&sort=updated&per_page=100&page={page}"
        )
        batch = api_get(url)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected repository response.")

        repositories.extend(
            repository for repository in batch
            if repository.get("owner", {}).get("login", "").lower() == USERNAME.lower()
            and not repository.get("private", False)
        )

        if len(batch) < 100:
            break
        page += 1

    return repositories


def fetch_language_totals(repositories):
    totals = {}

    for repository in repositories:
        # Exclude forks and archived repositories from language attribution.
        if repository.get("fork") or repository.get("archived"):
            continue

        languages_url = repository.get("languages_url")
        if not languages_url:
            continue

        language_bytes = api_get(languages_url)
        if not isinstance(language_bytes, dict):
            continue

        for language, byte_count in language_bytes.items():
            if isinstance(byte_count, int):
                totals[language] = totals.get(language, 0) + byte_count

    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))


def fmt_number(value):
    return f"{int(value):,}"


def build_stats_svg(metrics, refreshed):
    width, height = 960, 284
    card_width, card_height, gap = 211, 112, 20
    labels = [
        ("PUBLIC REPOS", metrics["repositories"], "Public repositories owned"),
        ("STARS", metrics["stars"], "Across public repositories"),
        ("FORKS", metrics["forks"], "Across public repositories"),
        ("FOLLOWERS", metrics["followers"], "Public GitHub followers"),
    ]

    cards = []
    for index, (label, value, note) in enumerate(labels):
        x = 28 + index * (card_width + gap)
        value_text = fmt_number(value)
        value_size = 31 if len(value_text) < 8 else 25
        cards.append(f"""
        <g transform="translate({x},91)">
          <rect width="{card_width}" height="{card_height}" rx="13"
                fill="#251c1c" stroke="{LINE}"/>
          <rect x="16" y="16" width="4" height="22" rx="2" fill="{RED}"/>
          <text x="31" y="32" fill="{AMBER}" font-family="Arial,sans-serif"
                font-size="11" font-weight="700" letter-spacing="1.4">{html.escape(label)}</text>
          <text x="17" y="76" fill="{INK}" font-family="Arial,sans-serif"
                font-size="{value_size}" font-weight="700">{html.escape(value_text)}</text>
          <text x="17" y="98" fill="{MUTED}" font-family="Arial,sans-serif"
                font-size="10">{html.escape(note)}</text>
        </g>""")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
 viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Vivek Anupindi — public GitHub statistics</title>
  <desc id="desc">Public repository, star, fork, and follower counts from GitHub.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#211818"/>
      <stop offset="1" stop-color="#111112"/>
    </linearGradient>
    <radialGradient id="glow" cx="96%" cy="0%" r="70%">
      <stop offset="0" stop-color="{RED}" stop-opacity=".16"/>
      <stop offset="1" stop-color="{RED}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="url(#background)"/>
  <rect width="{width}" height="{height}" rx="18" fill="url(#glow)"/>
  <rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="17.5"
        fill="none" stroke="{LINE}"/>
  <text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif"
        font-size="19" font-weight="700">GitHub at a glance</text>
  <text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif"
        font-size="11">Public profile snapshot · {html.escape(USERNAME)}</text>
  {''.join(cards)}
  <text x="28" y="252" fill="{MUTED}" font-family="Arial,sans-serif"
        font-size="10">PUBLIC DATA ONLY</text>
  <text x="{width-28}" y="252" text-anchor="end" fill="{MUTED}"
        font-family="Arial,sans-serif" font-size="10">Refreshed {html.escape(refreshed)}</text>
</svg>
"""


def build_languages_svg(language_totals, refreshed):
    width, height = 960, 292
    top = list(language_totals.items())[:6]
    total_bytes = sum(value for _, value in top)
    colors = [RED, AMBER, "#d78273", "#c7a18a", "#9d6a60", "#79534e"]

    if not top or total_bytes == 0:
        rows = (
            f'<text x="34" y="143" fill="{MUTED}" '
            'font-family="Arial,sans-serif" font-size="14">'
            "Language data will appear after the first successful refresh."
            "</text>"
        )
    else:
        rendered = []
        for index, (language, byte_count) in enumerate(top):
            y = 94 + index * 29
            share = byte_count / total_bytes * 100
            bar_width = max(4, 560 * share / 100)
            color = colors[index % len(colors)]
            rendered.append(f"""
            <g>
              <text x="34" y="{y+10}" fill="{INK}" font-family="Arial,sans-serif"
                    font-size="12">{html.escape(language)}</text>
              <rect x="205" y="{y-2}" width="560" height="12" rx="6"
                    fill="{TRACK}"/>
              <rect x="205" y="{y-2}" width="{bar_width:.1f}" height="12"
                    rx="6" fill="{color}"/>
              <text x="795" y="{y+10}" text-anchor="end" fill="{MUTED}"
                    font-family="Arial,sans-serif" font-size="11">{share:.1f}%</text>
            </g>""")
        rows = "".join(rendered)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
 viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Vivek Anupindi — language breakdown</title>
  <desc id="desc">Top languages by code size in non-fork, non-archived public repositories.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#211818"/>
      <stop offset="1" stop-color="#111112"/>
    </linearGradient>
    <radialGradient id="glow" cx="96%" cy="0%" r="70%">
      <stop offset="0" stop-color="{RED}" stop-opacity=".12"/>
      <stop offset="1" stop-color="{RED}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="url(#background)"/>
  <rect width="{width}" height="{height}" rx="18" fill="url(#glow)"/>
  <rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="17.5"
        fill="none" stroke="{LINE}"/>
  <text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif"
        font-size="19" font-weight="700">Languages across public projects</text>
  <text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif"
        font-size="11">Repository language byte counts · forks and archived repos excluded</text>
  {rows}
  <text x="28" y="267" fill="{MUTED}" font-family="Arial,sans-serif"
        font-size="10">TOP SIX LANGUAGES BY CODE SIZE</text>
  <text x="{width-28}" y="267" text-anchor="end" fill="{MUTED}"
        font-family="Arial,sans-serif" font-size="10">Refreshed {html.escape(refreshed)}</text>
</svg>
"""


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # Fetch all source data before writing. On API failure, existing cards remain.
    profile = api_get(f"{API_ROOT}/users/{USERNAME}")
    repositories = fetch_public_repositories()
    languages = fetch_language_totals(repositories)

    active_repositories = [
        repository for repository in repositories
        if not repository.get("archived")
    ]

    metrics = {
        "repositories": len(active_repositories),
        "stars": sum(repo.get("stargazers_count", 0) for repo in active_repositories),
        "forks": sum(repo.get("forks_count", 0) for repo in active_repositories),
        "followers": profile.get("followers", 0),
    }
    refreshed = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

    (OUTPUT / "github-public-stats.svg").write_text(
        build_stats_svg(metrics, refreshed), encoding="utf-8"
    )
    (OUTPUT / "github-language-breakdown.svg").write_text(
        build_languages_svg(languages, refreshed), encoding="utf-8"
    )

    print("Updated public GitHub profile cards.")
    print(f"Public repositories: {metrics['repositories']}")
    print(
        f"Stars: {metrics['stars']}; forks: {metrics['forks']}; "
        f"followers: {metrics['followers']}"
    )
    print(f"Languages measured: {len(languages)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Profile statistics refresh failed: {error}", file=sys.stderr)
        sys.exit(1)
