#!/usr/bin/env python3
"""
Fetch GitHub stats for apraba05 and update dark_mode.svg + light_mode.svg.

Stats fetched:
  - public repos
  - contributed-to repos (repos_contributed)
  - total stars across all public repos
  - total commits (contributions this year + all time via GraphQL)
  - followers
  - lines added / lines deleted (iterated across all repos)

Requires: GITHUB_TOKEN env var (set automatically in Actions).
"""

import os
import re
import sys
import math
import requests

USERNAME  = "apraba05"
TOKEN     = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
HEADERS   = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
GRAPHQL   = "https://api.github.com/graphql"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── helpers ──────────────────────────────────────────────────────────────────

def gh_get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def graphql(query, variables=None):
    r = requests.post(GRAPHQL, json={"query": query, "variables": variables or {}},
                      headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        print("GraphQL errors:", data["errors"], file=sys.stderr)
    return data.get("data", {})


def fmt(n):
    """Format a number with commas: 1234567 → '1,234,567'."""
    return f"{n:,}"


def pad_dots(value_str, base_dots):
    """
    Adjust dot count so that  dots + value_str  stays constant width.
    base_dots is the number of dots used when value_str is 1 char wide.
    Returns a dot string like ' ........ '.
    """
    n = max(1, base_dots - (len(value_str) - 1))
    return " " + "." * n + " "


# ── fetch stats ──────────────────────────────────────────────────────────────

def fetch_user():
    return gh_get(f"https://api.github.com/users/{USERNAME}")


def fetch_all_repos():
    repos, page = [], 1
    while True:
        batch = gh_get(f"https://api.github.com/users/{USERNAME}/repos",
                       params={"per_page": 100, "page": page, "type": "owner"})
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


def fetch_contributions():
    """Total commits via GraphQL contributionsCollection."""
    q = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          totalCommitContributions
          totalRepositoriesWithContributedCommits
        }
      }
    }
    """
    data = graphql(q, {"login": USERNAME})
    cc = data.get("user", {}).get("contributionsCollection", {})
    return (
        cc.get("totalCommitContributions", 0),
        cc.get("totalRepositoriesWithContributedCommits", 0),
    )


def fetch_loc(repos):
    """
    Sum lines added/deleted across all repos by iterating contributor stats.
    GitHub caches this; first call may return 202 (computing) — we retry once.
    """
    added, deleted = 0, 0
    for repo in repos:
        name = repo["full_name"]
        url  = f"https://api.github.com/repos/{name}/stats/contributors"
        for attempt in range(2):
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 202:
                import time; time.sleep(3)
                continue
            if r.status_code != 200:
                break
            for contributor in r.json():
                if contributor.get("author", {}).get("login", "").lower() == USERNAME.lower():
                    for week in contributor.get("weeks", []):
                        added   += week.get("a", 0)
                        deleted += week.get("d", 0)
            break
    return added, deleted


# ── SVG update ───────────────────────────────────────────────────────────────

def update_id(content, element_id, new_value):
    """Replace the text inside <tspan id="ELEMENT_ID">VALUE</tspan>."""
    return re.sub(
        rf'(id="{re.escape(element_id)}">)[^<]*(</tspan>)',
        rf'\g<1>{re.escape(new_value)}\g<2>',
        content
    )


def update_svg(path, stats):
    with open(path, encoding="utf-8") as f:
        svg = f.read()

    repos    = fmt(stats["repos"])
    contrib  = fmt(stats["contrib"])
    stars    = fmt(stats["stars"])
    commits  = fmt(stats["commits"])
    followers = fmt(stats["followers"])
    loc      = fmt(stats["loc"])
    loc_add  = fmt(stats["loc_add"])
    loc_del  = fmt(stats["loc_del"])

    # Update values
    svg = update_id(svg, "repo_data",     repos)
    svg = update_id(svg, "contrib_data",  contrib)
    svg = update_id(svg, "star_data",     stars)
    svg = update_id(svg, "commit_data",   commits)
    svg = update_id(svg, "follower_data", followers)
    svg = update_id(svg, "loc_data",      loc)
    svg = update_id(svg, "loc_add",       loc_add)
    svg = update_id(svg, "loc_del",       loc_del)

    # Adjust dot padding to keep alignment
    svg = update_id(svg, "repo_data_dots",     pad_dots(repos,    5))
    svg = update_id(svg, "star_data_dots",     pad_dots(stars,    10))
    svg = update_id(svg, "commit_data_dots",   pad_dots(commits,  18))
    svg = update_id(svg, "follower_data_dots", pad_dots(followers, 8))
    svg = update_id(svg, "loc_data_dots",      pad_dots(loc,      2))

    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"  updated {os.path.basename(path)}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Fetching stats for @{USERNAME}...")

    user  = fetch_user()
    repos = fetch_all_repos()

    stars     = sum(r.get("stargazers_count", 0) for r in repos)
    commits, contrib_repos = fetch_contributions()

    print("Fetching LOC (this may take a moment)...")
    loc_add, loc_del = fetch_loc(repos)

    stats = {
        "repos":     user.get("public_repos", 0),
        "contrib":   contrib_repos,
        "stars":     stars,
        "commits":   commits,
        "followers": user.get("followers", 0),
        "loc":       loc_add - loc_del,
        "loc_add":   loc_add,
        "loc_del":   loc_del,
    }

    print("Stats:", stats)

    for fname in ("dark_mode.svg", "light_mode.svg"):
        path = os.path.join(REPO_ROOT, fname)
        if os.path.exists(path):
            update_svg(path, stats)
        else:
            print(f"  WARNING: {path} not found, skipping")

    print("Done.")


if __name__ == "__main__":
    main()
