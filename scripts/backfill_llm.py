#!/usr/bin/env python3
"""Re-run LLM classification for cases that were ingested as degraded
fallback records (LLM step failed or was unconfigured at ingest time).

Why this exists: the ingest pipeline deliberately never retries a case
once it is in data/cases.json (deduplication skips it), so a case that
landed with a raw-tweet title, empty tech_stack and verification
"灰度路由/传闻" stays that way forever unless something re-classifies
it. This script does exactly that one job, and nothing else.

Scope guard: only cases matching the fallback signature are touched:
  tech_stack == [] AND verification == "灰度路由/传闻"
The 7 hand-curated seed cases (Clockwork Bird ... Whale Breach) do not
match that signature and are never rewritten. Preserved on every
re-classified case: id, tweet_url, author, preview_webp, video_url,
duration_sec, work_time, cost_usd, highlights, created_at.
Only the LLM-owned fields are replaced: category, category_name,
title, summary, prompt, tech_stack, demo_url, verification.

Usage (run from the repo root, after LLM_MODEL is fixed in Secrets
for Actions, or with env vars set locally):
  python scripts/backfill_llm.py --dry-run        # list what would change
  python scripts/backfill_llm.py --id 2107097706661560595
  python scripts/backfill_llm.py --all            # every degraded case
  python scripts/backfill_llm.py --all --rebuild-readme

Environment: LLM_API_KEY (required), LLM_BASE_URL, LLM_MODEL.
If the LLM call fails for a case, that case is left untouched and the
error is printed — no silent fallback write.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from process_tweet import (  # noqa: E402
    CATEGORIES,
    analyze_with_llm,
    extract_tweet_ref,
    fetch_tweet_metadata,
)

CASES_FILE = "data/cases.json"
LLM_FIELDS = [
    "category",
    "category_name",
    "title",
    "summary",
    "title_en",
    "summary_en",
    "prompt",
    "tech_stack",
    "demo_url",
    "verification",
]


def is_degraded(case: dict) -> bool:
    """Fallback records from process_tweet.fallback_record()."""
    return case.get("tech_stack") == [] and case.get("verification") == "灰度路由/传闻"


def reclassify(case: dict) -> dict:
    author, tweet_id = extract_tweet_ref(case["tweet_url"])
    meta = fetch_tweet_metadata(author, tweet_id)
    llm_data = analyze_with_llm(meta["text"], "")
    if llm_data.get("category") not in CATEGORIES:
        llm_data["category"] = "video_gen"
        llm_data["category_name"] = CATEGORIES["video_gen"]
    updated = dict(case)
    for field in LLM_FIELDS:
        if field in llm_data:
            updated[field] = llm_data[field]
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", dest="case_id", help="Re-classify one case by tweet id")
    group.add_argument("--all", action="store_true", help="Re-classify every degraded case")
    group.add_argument("--dry-run", action="store_true", help="List degraded cases, change nothing")
    parser.add_argument("--rebuild-readme", action="store_true",
                        help="Also run scripts/build_readme.py afterwards")
    args = parser.parse_args()

    if not os.environ.get("LLM_API_KEY") and not args.dry_run:
        print("LLM_API_KEY 未设置：先修好仓库 Secrets 里的 LLM_MODEL/LLM_API_KEY 再跑。")
        print("（只想看看哪些案例是降级的，用 --dry-run，不需要密钥。）")
        return 2

    with open(CASES_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)

    if args.dry_run:
        degraded = [c for c in cases if is_degraded(c)]
        print(f"共 {len(cases)} 条案例，其中降级记录 {len(degraded)} 条：")
        for c in degraded:
            print(f"  - {c['id']} {c.get('author','')} 《{c.get('title','')}》")
        return 0

    targets = []
    if args.case_id:
        targets = [c for c in cases if c["id"] == args.case_id]
        if not targets:
            print(f"找不到 id={args.case_id} 的案例。")
            return 1
        if not is_degraded(targets[0]):
            print(f"{args.case_id} 不是降级记录（已有完整分类），不改动。")
            return 0
    else:
        targets = [c for c in cases if is_degraded(c)]

    if not targets:
        print("没有需要补分类的降级记录。")
        return 0

    changed = 0
    for case in targets:
        try:
            updated = reclassify(case)
        except Exception as e:
            print(f"跳过 {case['id']}：LLM 调用失败，记录原样保留：{e}")
            continue
        idx = cases.index(case)
        cases[idx] = updated
        changed += 1
        print(f"已补分类: {case['id']} 《{updated.get('title')}》 "
              f"tech_stack={updated.get('tech_stack')}")

    if changed:
        with open(CASES_FILE, "w", encoding="utf-8") as f:
            json.dump(cases, f, ensure_ascii=False, indent=2)
        print(f"cases.json 已更新，共补 {changed} 条。")
        if args.rebuild_readme:
            import subprocess
            subprocess.run([sys.executable, "scripts/build_readme.py"], check=True)
            print("README.md 已重渲染。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
