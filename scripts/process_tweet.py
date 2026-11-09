#!/usr/bin/env python3
"""Auto-ingest a GPT-6.2 gray-rollout tweet into data/cases.json.

Pipeline: FxTwitter public API (metadata + direct media links) ->
optional media download + WebP preview (yt-dlp, direct-URL fallback) ->
optional LLM structured extraction -> append to data/cases.json.

Environment:
  TWEET_URL    (required) https://x.com/<author>/status/<id>
  USER_NOTES   (optional) free-text notes / prompt supplied by the submitter
  LLM_API_KEY  (optional) if unset, a basic record is built from metadata
  LLM_BASE_URL (optional, default https://api.openai.com/v1)
  LLM_MODEL    (optional, default gpt-4o-mini)

Note: preview generation downloads the original video and stores a short
(5s) WebP derivative in assets/previews/. The repository owner has accepted
this republication scope; all entries keep author attribution and link back
to the original post.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import requests

CASES_FILE = "data/cases.json"
PREVIEW_DIR = "assets/previews"

CATEGORIES = {
    "demo_3d": "🧊 3D 与游戏演示",
    "sighting": "🔍 灰度目击",
    "signal": "📡 信号与讨论",
}


def extract_tweet_ref(url: str):
    match = re.search(r"(?:twitter\.com|x\.com)/([^/]+)/status/(\d+)", url or "")
    if not match:
        raise ValueError(f"无效的推文链接: {url}")
    return match.group(1), match.group(2)


def fetch_tweet_metadata(author: str, tweet_id: str) -> dict:
    """Fetch tweet text/author/media via the FxTwitter public API."""
    api_url = f"https://api.fxtwitter.com/{author}/status/{tweet_id}"
    resp = requests.get(api_url, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("tweet", {})

    created_at = ""
    raw_date = data.get("created_at", "")
    if raw_date:
        try:
            created_at = datetime.strptime(
                raw_date, "%a %b %d %H:%M:%S %z %Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            created_at = ""

    media_urls = [
        m.get("url")
        for m in (data.get("media") or {}).get("all", [])
        if m.get("type") in ("video", "gif") and m.get("url")
    ]
    duration_sec = None
    for m in (data.get("media") or {}).get("all", []):
        if m.get("type") == "video" and m.get("duration"):
            duration_sec = m["duration"]
            break

    return {
        "text": data.get("text", ""),
        "author": f"@{data.get('author', {}).get('screen_name', author)}",
        "media_urls": media_urls,
        "duration_sec": duration_sec,
        "created_at": created_at,
    }


def fetch_thread_posts(tweet_id: str) -> list[dict]:
    """Fetch the tweet's self-thread via the FxTwitter v2 thread endpoint.

    Creators often post the full prompt as a follow-up in their own
    thread rather than in the main post, so prompt extraction needs the
    whole thread, not just the main post. Best-effort: returns [] on any
    failure so ingestion never breaks because of it.
    """
    try:
        resp = requests.get(
            f"https://api.fxtwitter.com/2/thread/{tweet_id}", timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"串帖抓取失败（不影响收录）: {e}")
        return []
    posts: list[dict] = []
    seen: set[str] = set()
    items = []
    if isinstance(data.get("status"), dict):
        items.append(data["status"])
    items.extend(data.get("thread") or [])
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id", ""))
        if not pid or pid in seen:
            continue
        seen.add(pid)
        raw = item.get("raw_text") or {}
        text = raw.get("text") or item.get("text") or ""
        posts.append(
            {
                "id": pid,
                "author": (item.get("author") or {}).get("screen_name", ""),
                "text": text,
            }
        )
    return posts


_PROMPT_MARKERS = (
    "prompt", "提示词", "write ", "create ", "build ", "generate ",
    "make a ", "make an ", "draw ", "render ", "请用", "请写", "生成",
    "创建一个", "写一个", "绘制", "```",
)


def _prompt_score(text: str) -> float:
    low = (text or "").lower()
    markers = sum(1 for m in _PROMPT_MARKERS if m in low)
    return markers * 25 + min(len(text), 1000) / 20.0


def best_prompt_candidate(
    posts: list[dict], main_id: str, main_author: str
) -> tuple[str, str] | tuple[None, str]:
    """Deterministically pick the most prompt-like post in the thread.

    Whole-post prompts live in the author's own follow-ups, so those get
    a bonus; the main post itself is usually an announcement, not the
    prompt. Returns (text, source) with source "thread" or "main".
    """
    best: tuple[float, str, str] | None = None
    for p in posts:
        text = (p.get("text") or "").strip()
        if len(text) < 60:
            continue
        score = _prompt_score(text)
        is_main = p["id"] == main_id
        if not is_main and p.get("author", "").lower() == main_author.lower():
            score *= 1.5
        if is_main:
            score *= 0.5
        if best is None or score > best[0]:
            best = (score, text, "main" if is_main else "thread")
    if best and best[0] >= 40:
        return best[1], best[2]
    return None, ""


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().strip('"“”')


def resolve_prompt(
    llm_prompt: str | None,
    posts: list[dict],
    main_id: str,
    main_author: str,
) -> tuple[str, str]:
    """Decide the case's prompt text and where it came from.

    The LLM's extraction is only trusted if it appears VERBATIM
    (whitespace-normalized) inside the main post or the thread — this
    stops paraphrases and silent truncations. Otherwise fall back to
    the best deterministic whole-post candidate, else 未公开.
    """
    candidate = (llm_prompt or "").strip()
    if candidate and candidate != "未公开":
        needle = _norm_ws(candidate)
        for p in posts:
            if needle and needle in _norm_ws(p.get("text", "")):
                return candidate, "main" if p["id"] == main_id else "thread"
        # Not verbatim anywhere -> do not trust it.
    text, source = best_prompt_candidate(posts, main_id, main_author)
    if text:
        return text, source
    return "未公开", ""


def _to_webp(mp4_path: str, webp_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", mp4_path,
        "-t", "5",
        "-vf", "fps=12,scale=480:-1:flags=lanczos",
        "-vcodec", "libwebp", "-lossless", "0", "-compression_level", "6",
        "-q:v", "65", "-loop", "0", "-an",
        webp_path,
    ]
    subprocess.run(cmd, check=True)
    return os.path.exists(webp_path)


def download_and_convert_media(tweet_url: str, tweet_id: str, direct_url: str = "") -> str:
    """Download the tweet video and convert the first 5s to a WebP preview."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    mp4_path = f"/tmp/{tweet_id}.mp4"
    webp_path = f"{PREVIEW_DIR}/{tweet_id}.webp"

    got = False
    try:
        subprocess.run(
            ["yt-dlp", "-f", "best[ext=mp4]", "-o", mp4_path, tweet_url],
            check=True, capture_output=True, timeout=300,
        )
        got = os.path.exists(mp4_path)
    except Exception as e:
        print(f"yt-dlp 下载失败，尝试直链: {e}")
    if not got and direct_url:
        r = requests.get(direct_url, timeout=300)
        r.raise_for_status()
        with open(mp4_path, "wb") as f:
            f.write(r.content)
        got = os.path.exists(mp4_path)
    if not got:
        raise RuntimeError("视频下载失败")
    if not _to_webp(mp4_path, webp_path):
        raise RuntimeError("WebP 转码失败")
    return webp_path


def analyze_with_llm(
    tweet_text: str, user_notes: str = "", thread_texts: list[str] | None = None
) -> dict:
    """Structured extraction with an OpenAI-compatible LLM endpoint."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    system_prompt = """你是一个开源项目整理助手，负责整理 GPT-6.2（Astra 与 Sol 两条线）的灰度目击与社区实测案例。
请根据推文内容提取以下 JSON 字段（严格输出合法 JSON）：
- category: 只能是 ["demo_3d", "sighting", "signal"] 之一（demo_3d=作者发布的演示作品，sighting=用量/配额/界面等目击截图，signal=暗示、报道与讨论帖）
- category_name: 对应 ["🧊 3D 与游戏演示", "🔍 灰度目击", "📡 信号与讨论"]
- title: 简短有吸引力的中文标题（15字以内）
- summary: 一句话中文摘要，说明测试效果与亮点（40字以内）
- title_en: 对应的英文标题（8个词以内）
- summary_en: 对应的一句英文摘要（25个词以内）
- prompt: 找出作者生成该作品时给模型的原始 Prompt。它可能在主贴里，也可能在作者自己串帖的后续发言里（我会一并提供）。必须逐字复制原文，不要改写、不要翻译、不要截断、不要补全；确实没有公开时填 "未公开"
- tech_stack: 数组，提取涉及的技术栈如 ["Three.js", "HTML5", "Canvas", "Remotion"]
- demo_url: 推文中包含的在线预览链接（若无则填 ""）
- verification: 判断属于 "作者标注/未验证" 还是 "灰度目击/未官宣"；官方人员暗示或媒体报道类帖子填 "信号/讨论"
"""
    user_content = f"主贴内容:\n{tweet_text}"
    if thread_texts:
        joined = "\n".join(
            f"[串帖 {i + 1}] {t}" for i, t in enumerate(thread_texts)
        )
        user_content += f"\n\n作者在同一串帖中的后续发言:\n{joined}"
    user_content += f"\n\n补充说明:\n{user_notes}"
    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    content = response.choices[0].message.content
    # Some providers return content as a list of parts instead of a string.
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    parsed = json.loads(content)
    # Some models wrap the object in a one-element JSON array.
    if isinstance(parsed, list):
        parsed = next((x for x in parsed if isinstance(x, dict)), {})
    return parsed


def fallback_record(meta: dict, user_notes: str) -> dict:
    """Used when LLM_API_KEY is not configured: keep the pipeline working."""
    if "### " in (user_notes or ""):
        # Raw issue-form dump, not real notes — don't leak form scaffolding
        # into the record.
        user_notes = ""
    first_line = (meta["text"] or "").strip().split("\n")[0][:40]
    return {
        "category": "demo_3d",
        "category_name": CATEGORIES["demo_3d"],
        "title": first_line or "GPT-6.2 灰度案例",
        "summary": (meta["text"] or "")[:60],
        "title_en": first_line or "GPT-6.2 gray-rollout case",
        "summary_en": (meta["text"] or "")[:120],
        "prompt": user_notes or "未公开",
        "tech_stack": [],
        "demo_url": "",
        "verification": "灰度路由/传闻",
    }


def ingest_case(tweet_url: str, user_notes: str = "") -> dict | None:
    """Ingest one tweet into data/cases.json. Returns the new case, or None
    if the tweet is already indexed. Raises on unrecoverable fetch errors
    so batch callers can skip the tweet and continue."""
    author, tweet_id = extract_tweet_ref(tweet_url)

    with open(CASES_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)
    if any(c["id"] == tweet_id for c in cases):
        print(f"推文 {tweet_id} 已存在，跳过处理。")
        return None

    meta = fetch_tweet_metadata(author, tweet_id)
    # The full prompt often lives in the author's own thread follow-ups,
    # not in the main post — fetch the thread for prompt extraction.
    posts = fetch_thread_posts(tweet_id)

    preview_webp = ""
    if meta["media_urls"]:
        try:
            preview_webp = download_and_convert_media(
                tweet_url, tweet_id, meta["media_urls"][0]
            )
        except Exception as e:
            print(f"媒体处理失败，降级为纯文本收录: {e}")

    if os.environ.get("LLM_API_KEY"):
        try:
            llm_data = analyze_with_llm(
                meta["text"],
                user_notes,
                thread_texts=[
                    p["text"] for p in posts if p["id"] != tweet_id and p["text"]
                ],
            )
        except Exception as e:
            print(f"LLM 解析失败，降级为基础记录: {e}")
            llm_data = fallback_record(meta, user_notes)
    else:
        print("未配置 LLM_API_KEY，使用基础记录（请在仓库 Secrets 中添加后获得完整分类）。")
        llm_data = fallback_record(meta, user_notes)

    if llm_data.get("category") not in CATEGORIES:
        llm_data["category"] = "demo_3d"
        llm_data["category_name"] = CATEGORIES["demo_3d"]

    # Never let a missing LLM field crash ingestion downstream.
    first_line = (meta["text"] or "").strip().split("\n")[0][:40]
    if not llm_data.get("title"):
        llm_data["title"] = first_line or "GPT-6.2 灰度案例"
    if not llm_data.get("summary"):
        llm_data["summary"] = (meta["text"] or "")[:60]
    if not llm_data.get("title_en"):
        llm_data["title_en"] = llm_data["title"]
    if not llm_data.get("summary_en"):
        llm_data["summary_en"] = llm_data["summary"]

    new_case = {
        "id": tweet_id,
        "tweet_url": tweet_url,
        "author": meta["author"],
        **llm_data,
        "preview_webp": preview_webp,
        "video_url": "",
        "demo_url": llm_data.get("demo_url", ""),
        "duration_sec": meta["duration_sec"],
        "work_time": "",
        "cost_usd": "",
        "highlights": [],
        "created_at": meta["created_at"] or datetime.now().strftime("%Y-%m-%d"),
    }

    prompt_text, prompt_source = resolve_prompt(
        llm_data.get("prompt"),
        posts,
        tweet_id,
        meta["author"].lstrip("@"),
    )
    new_case["prompt"] = prompt_text
    new_case["prompt_source"] = prompt_source

    cases.insert(0, new_case)
    with open(CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print(f"成功收录案例: {new_case.get('title', '')}")
    return new_case


def main() -> int:
    tweet_url = os.environ.get("TWEET_URL", "").strip()
    user_notes = os.environ.get("USER_NOTES", "").strip()
    if not tweet_url:
        print("TWEET_URL 为空，跳过。")
        return 0
    ingest_case(tweet_url, user_notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
