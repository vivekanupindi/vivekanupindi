#!/usr/bin/env python3
"""Generate a compact public-repository language breakdown card."""

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
TOKEN = os.environ["GITHUB_TOKEN"]
API_ROOT = "https://api.github.com"
OUTPUT = Path("assets/github-profile-stats.svg")

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


def build_svg(languages: dict[str, int], refreshed: str) -> str:
    top = list(languages.items())[:6]
    total_bytes = sum(languages.values())
    language_rows = []

    if not top or total_bytes == 0:
        language_rows.append(
            f'<text x="480" y="174" text-anchor="middle" fill="{MUTED}" '
            'font-family="Arial,sans-serif" font-size="14">No public language data returned.</text>'
        )
    else:
        for index, (language, byte_count) in enumerate(top):
            y = 119 + index * 27
            share = byte_count / total_bytes * 100
            bar_width = 650 * share / 100
            color = LANGUAGE_COLORS[index % len(LANGUAGE_COLORS)]
            safe_language = html.escape(language)
            language_rows.append(
                f'<g><text x="42" y="{y + 10}" fill="{INK}" '
                f'font-family="Arial,sans-serif" font-size="12">{safe_language}</text>'
                f'<rect x="190" y="{y}" width="650" height="10" rx="5" fill="{TRACK}"/>'
                f'<rect x="190" y="{y}" width="{bar_width:.1f}" height="10" rx="5" fill="{color}"/>'
                f'<text x="900" y="{y + 10}" text-anchor="end" fill="{MUTED}" '
                f'font-family="Arial,sans-serif" font-size="11">{share:.1f}%</text></g>'
            )

    safe_refreshed = html.escape(refreshed)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="320"
 viewBox="0 0 960 320" role="img" aria-labelledby="title desc">
  <title id="title">Vivek Anupindi — public repository language breakdown</title>
  <desc id="desc">Top public repository languages by code bytes. Refreshed {safe_refreshed}.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#211818"/><stop offset="1" stop-color="#111112"/>
    </linearGradient>
    <radialGradient id="glow" cx="96%" cy="0%" r="70%">
      <stop offset="0" stop-color="{RED}" stop-opacity=".14"/>
      <stop offset="1" stop-color="{RED}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="960" height="320" rx="18" fill="url(#background)"/>
  <rect width="960" height="320" rx="18" fill="url(#glow)"/>
  <rect x=".5" y=".5" width="959" height="319" rx="17.5" fill="none" stroke="{LINE}"/>
  <text x="28" y="40" fill="{INK}" font-family="Arial,sans-serif" font-size="19" font-weight="700">GitHub snapshot</text>
  <text x="28" y="62" fill="{MUTED}" font-family="Arial,sans-serif" font-size="11">Public repository languages · refreshed {safe_refreshed}</text>
  <text x="28" y="96" fill="{AMBER}" font-family="Arial,sans-serif" font-size="11" font-weight="700" letter-spacing="1.3">LANGUAGES BY CODE SIZE</text>
  {''.join(language_rows)}
  <text x="28" y="298" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Language distribution is calculated from code bytes across public, non-fork repositories.</text>
  <text x="932" y="298" text-anchor="end" fill="{MUTED}" font-family="Arial,sans-serif" font-size="10">Top six languages</text>
</svg>'''


def main() -> None:
    now_text = datetime.now(timezone.utc).strftime(
        "%d %b %Y · %H:%M UTC"
    )
    repositories = fetch_public_repositories()
    languages = fetch_language_totals(repositories)

    # Write only after the API calls finish, preserving the previous card on failure.
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_svg(languages, now_text), encoding="utf-8")
    print(f"Updated profile card: {len(languages)} public repository languages.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Profile stats refresh failed: {error}", file=sys.stderr)
        sys.exit(1)
