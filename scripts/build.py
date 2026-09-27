"""朝のニュースを収集・要約し、読み上げ音声とJSONを docs/ に生成する。"""

import asyncio
import calendar
import difflib
import html
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import edge_tts
import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
# edge-tts の既定出力は 48kbps の MP3 なので、バイト数から秒数が求まる
MP3_BYTES_PER_SEC = 48_000 / 8
WEEKDAYS = "月火水木金土日"


def log(msg):
    print(msg, flush=True)


# ---------- 収集 ----------

def fetch(url, timeout=15):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    res.raise_for_status()
    return res.content


def clean_text(raw):
    text = html.unescape(re.sub(r"<[^>]+>", "", raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def og_description(url):
    try:
        page = fetch(url, timeout=10).decode("utf-8", errors="ignore")
    except Exception as e:
        log(f"  ! 記事ページ取得失敗 {url}: {e}")
        return ""
    for pattern in (r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"',
                    r'<meta[^>]+name="description"[^>]+content="([^"]*)"'):
        m = re.search(pattern, page)
        if m:
            return clean_text(m.group(1))
    return ""


def summarize(text, title, limit):
    """先頭から句点までの文を limit 文字程度まで集める（抽出型要約）。"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"^.{0,60}?\[[^\]]{0,30}(ロイター|時事|共同|AFP|Bloomberg)[^\]]*\]\s*-?\s*", "", text)  # 通信社のクレジット
    text = re.sub(r"(?<=[。！？])\s+", "", text)
    text = text.rstrip("…").strip()
    if len(text) < 30 or text.startswith(title[:15]):
        return ""
    sentences = [s + "。" for s in text.split("。") if s.strip()]
    if not text.endswith("。"):
        sentences[-1] = sentences[-1][:-1]  # 末尾は途中で切れた断片
    picked = ""
    for i, s in enumerate(sentences):
        complete = i < len(sentences) - 1 or text.endswith("。")
        if picked and (len(picked) + len(s) > limit or not complete):
            break
        picked += s
    if len(picked) > limit * 1.5:
        picked = picked[:limit].rstrip("、")
    picked = picked.strip()
    if picked and not picked.endswith(("。", "！", "？")):
        picked += "…"
    return picked


def entry_time(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return calendar.timegm(t) if t else None


def collect_feed(feed, genre, limit_chars, now):
    try:
        parsed = feedparser.parse(fetch(feed["url"]))
    except Exception as e:
        log(f"  ! フィード取得失敗 {feed['url']}: {e}")
        return []

    keywords = genre.get("title_keywords")
    excluded = genre.get("exclude_domains", [])
    max_age = genre.get("max_age_hours", 48) * 3600
    items = []
    for entry in parsed.entries:
        published = entry_time(entry)
        if published and now - published > max_age:
            continue

        title = clean_text(entry.get("title"))
        source = feed["source"]
        # Googleニュースは「タイトル - 媒体名」形式で、媒体名は <source> にある
        src = entry.get("source") or {}
        if src.get("title"):
            source = src["title"]
            title = re.sub(r"\s+-\s+" + re.escape(source) + r"$", "", title)
            domain = urlparse(src.get("href", "")).netloc
            if any(domain.endswith(d) for d in excluded):
                continue
        title = re.sub(r"\s*[（(]\d+/\d+\s*ページ[）)]|\s+執筆$", "", title)
        if keywords and not any(k in title for k in keywords):
            continue

        items.append({
            "title": title,
            "source": source,
            "url": entry.get("link", ""),
            "published": published,
            "raw": clean_text(entry.get("summary") or entry.get("description")),
            "fetch_page": feed.get("fetch_page", False),
        })
    log(f"  {feed['source']}: {len(items)}件 ({feed['url'][:60]})")
    return items


def is_duplicate(item, chosen):
    for c in chosen:
        if item["url"] == c["url"]:
            return True
        if difflib.SequenceMatcher(None, item["title"], c["title"]).ratio() > 0.6:
            return True
    return False


def collect_genre(genre, limit_chars, now, seen):
    log(f"[{genre['name']}]")
    per_feed = [collect_feed(f, genre, limit_chars, now) for f in genre["feeds"]]
    for items in per_feed:
        items.sort(key=lambda x: x["published"] or 0, reverse=True)

    # 複数サイトの記事が交互に並ぶように1件ずつ取り出す
    chosen = []
    while len(chosen) < genre.get("max_items", 5) and any(per_feed):
        for items in per_feed:
            if not items or len(chosen) >= genre.get("max_items", 5):
                continue
            item = items.pop(0)
            if is_duplicate(item, seen + chosen):
                continue
            text = item["raw"]
            if item["fetch_page"] or len(text) < 30:
                if urlparse(item["url"]).netloc != "news.google.com":
                    text = og_description(item["url"]) or text
            item["summary"] = summarize(text, item["title"], limit_chars)
            chosen.append(item)
    seen.extend(chosen)
    return chosen


# ---------- 読み上げ原稿 ----------

def spoken_title(title):
    return re.sub(r"[\s　]+", "、", title).strip("、")


def build_segments(genres, today):
    """(種類, テキスト, 対象) の列。対象は音声開始位置を書き込む dict。"""
    date = f"{today.month}月{today.day}日、{WEEKDAYS[today.weekday()]}曜日"
    total = sum(len(g["items"]) for g in genres)
    names = "、".join(g["name"] for g in genres)
    segs = [("intro", f"おはようございます。{date}、朝のニュースです。今日は、{names}のニュース、合わせて{total}本をお伝えします。", None)]
    for i, g in enumerate(genres):
        lead = "まずは、" if i == 0 else "続いて、"
        if g["items"]:
            segs.append(("genre", f"{lead}{g['name']}のニュースです。", g))
        else:
            segs.append(("genre", f"{lead}{g['name']}です。新しいニュースはありませんでした。", g))
        for item in g["items"]:
            text = spoken_title(item["title"]) + "。"
            if item["summary"]:
                text += item["summary"]
            segs.append(("item", text, item))
    segs.append(("outro", f"以上、{today.month}月{today.day}日のニュースでした。今日も良い一日を。", None))
    return segs


# ---------- 音声合成 ----------

async def synth(text, voice, rate, sem):
    async with sem:
        for attempt in range(3):
            try:
                data = b""
                async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
                    if chunk["type"] == "audio":
                        data += chunk["data"]
                if data:
                    return data
            except Exception as e:
                log(f"  ! 音声合成リトライ {attempt + 1}: {e}")
            await asyncio.sleep(2 * (attempt + 1))
        raise RuntimeError(f"音声合成に失敗: {text[:30]}")


async def synth_all(segs, voice, rate):
    sem = asyncio.Semaphore(4)
    return await asyncio.gather(*(synth(text, voice, rate, sem) for _, text, _ in segs))


# ---------- メイン ----------

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    now_ts = time.time()
    today = datetime.now(JST)
    limit = config.get("summary_chars", 120)

    seen = []
    genres = [{"name": g["name"], "items": collect_genre(g, limit, now_ts, seen)} for g in config["genres"]]
    if not seen:
        log("記事が1件も取得できなかったため中止します")
        sys.exit(1)

    segs = build_segments(genres, today)
    log(f"音声合成中… ({len(segs)}セグメント)")
    chunks = asyncio.run(synth_all(segs, config["voice"], config.get("rate", "+0%")))

    # MP3フレームはそのまま連結でき、各セグメントの開始秒はバイト数から計算できる
    offset = 0
    for (_, _, target), chunk in zip(segs, chunks):
        if target is not None:
            target["start"] = round(offset / MP3_BYTES_PER_SEC, 2)
        offset += len(chunk)
    duration = round(offset / MP3_BYTES_PER_SEC, 1)

    (DOCS / "audio").mkdir(parents=True, exist_ok=True)
    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    (DOCS / "audio" / "latest.mp3").write_bytes(b"".join(chunks))

    data = {
        "date": today.strftime("%Y-%m-%d"),
        "date_label": f"{today.month}月{today.day}日（{WEEKDAYS[today.weekday()]}）",
        "generated_at": today.isoformat(timespec="minutes"),
        "audio": "audio/latest.mp3",
        "duration": duration,
        "genres": [{
            "name": g["name"],
            "start": g.get("start", 0),
            "items": [{
                "title": it["title"],
                "summary": it["summary"],
                "source": it["source"],
                "url": it["url"],
                "published": datetime.fromtimestamp(it["published"], JST).isoformat(timespec="minutes") if it["published"] else None,
                "start": it["start"],
            } for it in g["items"]],
        } for g in genres],
    }
    (DOCS / "data" / "latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"完了: {len(seen)}本 / {int(duration // 60)}分{int(duration % 60)}秒")


if __name__ == "__main__":
    main()
