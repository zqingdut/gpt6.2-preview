#!/usr/bin/env python3
"""Discover new GPT-6.2 Sol gray-rollout tweets from curated source collections and
ingest them automatically.

Discovery channels (no X API key required):
  1. Sibling awesome-lists on GitHub (their READMEs link many test tweets).
  2. Optional: X API v2 search, only if X_BEARER_TOKEN is set.

New tweet IDs (not already in data/cases.json) are ingested one by one via
process_tweet.ingest_case(). The per-run cap (MAX_NEW, default 5) keeps
each run cheap and reviewable; remaining candidates are picked up by the
next scheduled run.

Environment:
  MAX_NEW         max new cases to ingest this run (default 5)
  X_BEARER_TOKEN  optional, enables X API search
  LLM_API_KEY     optional, forwarded to the ingestion step
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from process_tweet import CASES_FILE, ingest_case  # noqa: E402

SOURCES = [
    # (source name, page URL whose text links the source tweets)
    ("payforchat-gpt-6-2",
     "https://www.payforchat.com/gpt-6-2"),
]

LINK_RE = re.compile(r"https://(?:x|twitter)\.com/([^/\s)\"']+)/status/(\d+)")

# Editorial cutoff (set by the repo owner): only tweets posted in
# November 2026 or later are eligible — the verifiable GPT-6.2 gray-rollout
# wave started in November; earlier posts are gray-route claims.
CUTOFF_MS = int(
    datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000
)


def tweet_ms(tweet_id: str) -> int:
    """Post time (ms) decoded from the tweet snowflake ID — no API call."""
    return (int(tweet_id) >> 22) + 1288834974657


def from_sibling_lists() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name, url in SOURCES:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"来源 {name} 拉取失败: {e}")
            continue
        pairs = LINK_RE.findall(r.text)
        print(f"来源 {name}: 发现 {len(pairs)} 条推文链接")
        found.extend(pairs)
    return found


def from_x_api() -> list[tuple[str, str]]:
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        return []
    try:
        r = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "query": '"GPT-6.2 Sol" OR "gpt-6.2-sol" (has:videos OR has:links) -is:retweet',
                "max_results": 50,
                "expansions": "author_id",
                "user.fields": "username",
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        users = {u["id"]: u["username"] for u in data.get("includes", {}).get("users", [])}
        return [
            (users.get(t["author_id"], ""), t["id"])
            for t in data.get("data", [])
            if t.get("author_id") in users
        ]
    except Exception as e:
        print(f"X API 搜索失败（忽略）: {e}")
        return []


def main() -> int:
    max_new = int(os.environ.get("MAX_NEW", "5"))
    with open(CASES_FILE, "r", encoding="utf-8") as f:
        known = {c["id"] for c in json.load(f)}

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for author, tid in from_sibling_lists() + from_x_api():
        if tid in known or tid in seen:
            continue
        seen.add(tid)
        candidates.append((author, tid))
    before = len(candidates)
    candidates = [c for c in candidates if tweet_ms(c[1]) >= CUTOFF_MS]
    # Newest first, so each run ingests the freshest cases.
    candidates.sort(key=lambda p: int(p[1]), reverse=True)
    print(f"候选新推文: {len(candidates)} 条（日期过滤掉 {before - len(candidates)} 条"
          f" 2026-11 之前的），本次最多收录 {max_new} 条")
    if os.environ.get("DRY_RUN"):
        for author, tid in candidates[:15]:
            print(f"  [dry-run] https://x.com/{author}/status/{tid}")
        return 0

    added = 0
    for author, tid in candidates:
        if added >= max_new:
            break
        url = f"https://x.com/{author}/status/{tid}"
        try:
            if ingest_case(url, "via auto-discovery") is not None:
                added += 1
        except Exception as e:
            print(f"跳过 {url}: {e}")
    print(f"本次新增收录: {added} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
