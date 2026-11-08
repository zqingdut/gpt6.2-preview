#!/usr/bin/env python3
"""Re-extract the original prompt for existing cases, now looking at
the author's whole thread — not just the main post.

Why this exists: creators often publish the full prompt as a follow-up
in their own thread (e.g. chetaslua's "Full Prompt" post under The Last
Page). The original ingest only read the main post, so many cases carry
prompt="未公开" even though the prompt is public one reply below.

Scope and safety:
  - Cases whose prompt is empty or "未公开": full re-extraction
    (LLM-assisted when LLM_API_KEY is set, deterministic otherwise).
  - Cases that already have a prompt but no prompt_source yet:
    verify-only — if the existing prompt appears verbatim in the main
    post or thread, stamp prompt_source; the text is NEVER modified
    (hand-curated seed prompts stay exactly as the owner wrote them).
  - Only the fields `prompt` and `prompt_source` are ever written.

Usage (from the repo root):
  python scripts/backfill_prompts.py --dry-run
  python scripts/backfill_prompts.py --id 2117224839010459987
  python scripts/backfill_prompts.py --all [--rebuild-readme]

Environment: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL (optional; without
them only deterministic whole-post candidates are used).
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from process_tweet import (  # noqa: E402
    analyze_with_llm,
    extract_tweet_ref,
    fetch_thread_posts,
    fetch_tweet_metadata,
    resolve_prompt,
)

CASES_FILE = "data/cases.json"


def load_cases() -> list[dict]:
    with open(CASES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cases(cases: list[dict]) -> None:
    with open(CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)


def process_case(case: dict, dry_run: bool) -> str:
    """Returns a human-readable outcome line for one case."""
    author_ref, tweet_id = extract_tweet_ref(case["tweet_url"])
    meta = fetch_tweet_metadata(author_ref, tweet_id)
    posts = fetch_thread_posts(tweet_id)
    main_author = meta["author"].lstrip("@")
    current = (case.get("prompt") or "").strip()
    missing = current in ("", "未公开")

    if not missing and "prompt_source" in case:
        return f"skip（已有 prompt 与来源）: {case['id']}"

    if missing:
        llm_prompt = None
        if os.environ.get("LLM_API_KEY"):
            try:
                data = analyze_with_llm(
                    meta["text"],
                    "",
                    thread_texts=[
                        p["text"] for p in posts if p["id"] != tweet_id and p["text"]
                    ],
                )
                llm_prompt = data.get("prompt")
            except Exception as e:
                print(f"  LLM 调用失败，改走确定性提取: {e}")
        text, source = resolve_prompt(llm_prompt, posts, tweet_id, main_author)
        if text == "未公开":
            if not dry_run:
                case["prompt_source"] = ""
            return f"仍未公开（主贴与串帖均无）: {case['id']}"
        if not dry_run:
            case["prompt"] = text
            case["prompt_source"] = source
        return (
            f"补齐 prompt（来源: {source}，{len(text)} 字）: "
            f"{case['id']} — {text[:50]}…"
        )

    # Verify-only: stamp the source of the existing prompt, never edit it.
    _, source = resolve_prompt(current, posts, tweet_id, main_author)
    verified = source in ("main", "thread")
    if not dry_run:
        case["prompt_source"] = source if verified else ""
    return (
        f"仅标注来源（{source or '未验证'}）: {case['id']}"
        if verified
        else f"已有 prompt 但未在主贴/串帖中逐字找到，保留原文: {case['id']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="处理全部符合条件的案例")
    parser.add_argument("--id", default="", help="只处理指定推文 ID")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    parser.add_argument(
        "--rebuild-readme",
        action="store_true",
        help="处理后用 build_readme.py 重新渲染双语 README",
    )
    args = parser.parse_args()
    if not args.all and not args.id:
        parser.error("需要 --all 或 --id")

    cases = load_cases()
    targets = [
        c
        for c in cases
        if (not args.id or c["id"] == args.id)
        and ((c.get("prompt") or "").strip() in ("", "未公开") or "prompt_source" not in c)
    ]
    print(f"待处理: {len(targets)} 条（dry_run={args.dry_run}）")
    changed = 0
    for case in targets:
        try:
            line = process_case(case, args.dry_run)
        except Exception as e:
            print(f"处理失败，跳过 {case['id']}: {e}")
            continue
        print(" ", line)
        if not line.startswith("skip"):
            changed += 1

    if not args.dry_run:
        save_cases(cases)
        print(f"已写入 {CASES_FILE}（处理 {changed} 条）")
        if args.rebuild_readme:
            subprocess.run(
                [sys.executable, "scripts/build_readme.py"], check=True
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
