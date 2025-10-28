#!/usr/bin/env python3
import requests
import json
import os
import sys
import time
import argparse
from collections import defaultdict


TOKEN = os.environ.get("TOKEN")
REPOS = ["NepTechTribe/CodeVault", "NepTechTribe/EventLog"] 
PER_PAGE = 100
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"token {TOKEN}"

def load_participants(path="data/participants.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
            return set(items)
    except FileNotFoundError:
        print(f"Participants file not found at {path}. Exiting.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading participants: {e}", file=sys.stderr)
        sys.exit(1)

def handle_rate_limit(resp):
    if resp.status_code == 403:
        rem = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")
        if rem == "0" and reset:
            reset_ts = int(reset)
            wait = max(0, reset_ts - int(time.time())) + 2
            print(f"Rate limit reached. Sleeping for {wait}s until reset.")
            time.sleep(wait)
            return True
    return False

def fetch_contributors_for_repo(repo):
    """
    Fetch contributors for a repo using the contributors endpoint with pagination.
    Returns a list of contributor dicts (as returned by the API).
    """
    contributors = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/contributors"
        params = {"per_page": PER_PAGE, "page": page}
        resp = requests.get(url, headers=HEADERS, params=params)
        if handle_rate_limit(resp):
            continue
        if resp.status_code != 200:
            print(f"Warning: failed to fetch contributors for {repo} (page {page}): {resp.status_code} {resp.text}", file=sys.stderr)
            break
        page_items = resp.json()
        if not page_items:
            break
        contributors.extend(page_items)
        if len(page_items) < PER_PAGE:
            break
        page += 1
    return contributors

def fetch_issues_and_prs_for_author(repo, author):
    """
    Count issues and PRs in repo created by author (all states).
    Uses the issues endpoint with creator=author; paginated.
    Returns tuple (num_issues, num_prs).
    """
    issues_count = 0
    prs_count = 0
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues"
        params = {"per_page": PER_PAGE, "page": page, "state": "all", "creator": author}
        resp = requests.get(url, headers=HEADERS, params=params)
        if handle_rate_limit(resp):
            continue
        if resp.status_code != 200:
            print(f"Warning: failed to fetch issues for {author} in {repo} (page {page}): {resp.status_code} {resp.text}", file=sys.stderr)
            break
        items = resp.json()
        if not items:
            break
        for it in items:
            if it.get("pull_request"):
                prs_count += 1
            else:
                issues_count += 1
        if len(items) < PER_PAGE:
            break
        page += 1
    return issues_count, prs_count

def get_user_meta(login):
    """
    Fetch avatar_url and html_url for a GitHub login. Returns dict with 'avatar' and 'url'.
    """
    url = f"https://api.github.com/users/{login}"
    resp = requests.get(url, headers=HEADERS)
    if handle_rate_limit(resp):
        resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        j = resp.json()
        return {"avatar": j.get("avatar_url", ""), "url": j.get("html_url", f"https://github.com/{login}")}
    return {"avatar": "", "url": f"https://github.com/{login}"}

def build_markdown(sorted_users, include_prs_issues=False, show_zero=False):
    if include_prs_issues:
        md = ["# 🧑‍💻 All-time Contribution Leaderboard (Commits + PRs + Issues)\n"]
        md.append("| Rank | Avatar | User | Total Commits | PRs | Issues | Total |")
        md.append("|------|---------|------|----------------|-----:|-------:|------:|")
        for i, (login, data) in enumerate(sorted_users, 1):
            avatar_md = f'<img src="{data.get("avatar", "")}" width="40" height="40" style="border-radius:50%"/>' if data.get("avatar") else ""
            commits = data.get("commits", 0)
            prs = data.get("prs", 0)
            issues = data.get("issues", 0)
            total = commits + prs + issues
            md.append(f"| {i} | {avatar_md} | [{login}]({data['url']}) | {commits} | {prs} | {issues} | {total} |")
    else:
        md = ["# 🧑‍💻 All-time Contribution Leaderboard (Commits)\n"]
        md.append("| Rank | Avatar | User | Total Commits |")
        md.append("|------|---------|------|----------------|")
        for i, (login, data) in enumerate(sorted_users, 1):
            avatar_md = f'<img src="{data.get("avatar", "")}" width="40" height="40" style="border-radius:50%"/>' if data.get("avatar") else ""
            md.append(f"| {i} | {avatar_md} | [{login}]({data['url']}) | {data.get('commits',0)} |")
    return "\n".join(md)

def main():
    parser = argparse.ArgumentParser(description="Generate an all-time contribution leaderboard.")
    parser.add_argument("--include-zero", action="store_true", help="Include participants with zero contributions in the leaderboard.")
    parser.add_argument("--include-prs-issues", action="store_true", help="Include PRs and issues in the counts (adds PRs and issues columns).")
    parser.add_argument("--repos", nargs="*", help="Override REPOS from environment; pass owner/repo pairs", default=None)
    args = parser.parse_args()

    repos = args.repos if args.repos else REPOS

    participants = load_participants()
    if not participants:
        print("Participants list is empty. Exiting.", file=sys.stderr)
        sys.exit(1)

    if not TOKEN:
        print("Warning: TOKEN environment variable missing. Unauthenticated requests are severely rate-limited and private repos won't be included.", file=sys.stderr)

    print(f"Computing all-time contributions across repos: {repos}")
    print(f"Options: include_zero={args.include_zero}, include_prs_issues={args.include_prs_issues}")

    commits_counts = defaultdict(int)
    prs_counts = defaultdict(int)
    issues_counts = defaultdict(int)

    for repo in repos:
        print(f"Processing contributors for repo: {repo}")
        contribs = fetch_contributors_for_repo(repo)
        for c in contribs:
            login = c.get("login")
            if not login:
                continue
            if login not in participants:
                continue
            contributions = c.get("contributions", 0)
            commits_counts[login] += contributions

    if args.include_prs_issues:
        print("Counting PRs and Issues authored by participants (this may make many API calls)...")
        for repo in repos:
            print(f"Processing issues/PRs for repo: {repo}")
            for login in participants:
                i_count, p_count = fetch_issues_and_prs_for_author(repo, login)
                if i_count:
                    issues_counts[login] += i_count
                if p_count:
                    prs_counts[login] += p_count

    users = {}

    for login in participants:
        commits = commits_counts.get(login, 0)
        prs = prs_counts.get(login, 0)
        issues = issues_counts.get(login, 0)
        total = commits + prs + issues
        if not args.include_zero and total == 0:
            continue
        meta = get_user_meta(login)
        users[login] = {
            "avatar": meta.get("avatar", ""),
            "url": meta.get("url", f"https://github.com/{login}"),
            "commits": commits,
            "prs": prs,
            "issues": issues,
        }

    # Sort
    if args.include_prs_issues:
        sorted_users = sorted(users.items(), key=lambda x: (x[1].get("commits",0) + x[1].get("prs",0) + x[1].get("issues",0)), reverse=True)
    else:
        sorted_users = sorted(users.items(), key=lambda x: x[1].get("commits",0), reverse=True)

    md = build_markdown(sorted_users, include_prs_issues=args.include_prs_issues, show_zero=args.include_zero)

    out_path = "README.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote leaderboard to {out_path}")

if __name__ == "__main__":
    main()
