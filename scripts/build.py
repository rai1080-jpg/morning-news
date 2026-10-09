"""朝のニュースを収集・要約し、読み上げ音声とJSONを docs/ に生成する。"""

import asyncio
import calendar
import html
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import edge_tts
import feedparser
import pykakasi
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
# edge-tts の既定出力は 48kbps の MP3 なので、バイト数から秒数が求まる
MP3_BYTES_PER_SEC = 48_000 / 8
# 無音のMP3フレーム（edge-tts と同じ 24kHz・モノラル・48kbps。1フレーム144バイト＝0.024秒）
SILENT_FRAME = bytes.fromhex("fff364c4") + bytes(140)
# 読み上げの「間」（秒）
PAUSE_AFTER_HEADLINE = 0.8
PAUSE_BETWEEN_ITEMS = 1.0
PAUSE_AFTER_GENRE = 0.6
WEEKDAYS = "月火水木金土日"


def log(msg):
    print(msg, flush=True)


# ---------- 収集 ----------

def fetch(url, timeout=15):
    res = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    res.raise_for_status()
    return res.content


def fetch_html(url, timeout=10):
    """記事ページを文字コードを判定して読む（Shift_JIS のサイトもあるため）。"""
    res = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    res.raise_for_status()
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", res.content[:4096], re.I)
    encoding = m.group(1).decode() if m else res.apparent_encoding
    return res.content.decode(encoding or "utf-8", errors="ignore")


def clean_text(raw):
    text = html.unescape(re.sub(r"<[^>]+>", "", raw or ""))
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def feed_url(feed):
    if "google" in feed:
        return f"https://news.google.com/rss/search?q={quote(feed['google'])}&hl=ja&gl=JP&ceid=JP:ja"
    return feed["url"]


def resolve_google_news(url):
    """Googleニュースの中継URLから元記事のURLを取り出す。非公式の方法なので、失敗したら中継URLのまま返す。"""
    try:
        article_id = urlparse(url).path.rsplit("/", 1)[-1]
        page = fetch(f"https://news.google.com/rss/articles/{article_id}", timeout=10).decode("utf-8", errors="ignore")
        signature = re.search(r'data-n-a-sg="([^"]+)"', page).group(1)
        timestamp = re.search(r'data-n-a-ts="([^"]+)"', page).group(1)
        req = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                              "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
               article_id, int(timestamp), signature]
        res = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data="f.req=" + quote(json.dumps([[["Fbv4je", json.dumps(req), None, "generic"]]])),
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            timeout=10,
        )
        res.raise_for_status()
        return json.loads(json.loads(res.text.split("\n\n")[1])[0][2])[1]
    except Exception as e:
        log(f"  ! Googleニュースの元記事URL取得失敗: {e}")
        return url


def og_description(url):
    try:
        page = fetch_html(url)
    except Exception as e:
        log(f"  ! 記事ページ取得失敗 {url}: {e}")
        return ""
    for pattern in (r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"',
                    r'<meta[^>]+content="([^"]*)"[^>]+property="og:description"',
                    r'<meta[^>]+name="description"[^>]+content="([^"]*)"'):
        m = re.search(pattern, page)
        if m:
            return clean_text(m.group(1))
    return ""


def summarize(text, title, limit):
    """先頭から句点までの文を limit 文字程度まで集める（抽出型要約）。"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"^.{0,60}?\[[^\]]{0,30}(ロイター|時事|共同|AFP|Bloomberg)[^\]]*\]\s*-?\s*", "", text)  # 通信社のクレジット
    text = re.sub(r"^.{0,40}のプレスリリース\(\d{4}年[^)]*\)", "", text)  # PR TIMES の定型文
    text = re.sub(r"(?<=[。！？])\s+", "", text)
    text = text.rstrip("…").strip()
    if text.startswith(title):
        text = text[len(title):].lstrip(" 。、")  # タイトルの繰り返しは読まない
    if len(text) < 30:
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


def collect_feed(feed, genre, now, exclude_words, age_limit):
    url = feed_url(feed)
    try:
        parsed = feedparser.parse(fetch(url))
    except Exception as e:
        log(f"  ! フィード取得失敗 {url}: {e}")
        return []

    keywords = [k.lower() for k in feed.get("title_keywords", genre.get("title_keywords", []))]
    excluded = genre.get("exclude_domains", [])
    # ジャンルやフィードの指定に関係なく、全体の上限（age_limit 時間）より古い記事は対象外
    max_age = min(feed.get("max_age_hours", genre.get("max_age_hours", age_limit)), age_limit) * 3600
    items = []
    for entry in parsed.entries:
        published = entry_time(entry)
        if not published or now - published > max_age:  # 日付のない記事も古い可能性があるので除外
            continue

        title = clean_text(entry.get("title"))
        source = feed.get("source", "Googleニュース")
        # Googleニュースは「タイトル - 媒体名」形式で、媒体名は <source> にある
        src = entry.get("source") or {}
        if src.get("title"):
            source = clean_text(src["title"])
            title = re.sub(r"\s+-\s+" + re.escape(source) + r"$", "", title)
            domain = urlparse(src.get("href", "")).netloc
            if any(domain.endswith(d) for d in excluded):
                continue
        title = re.sub(r"\s*[(]\d+/\d+\s*ページ[)]|\s+執筆$|^画像\d+\s*/\s*\d+>\s*", "", title)
        if keywords and not any(k in title.lower() for k in keywords):
            continue
        raw = clean_text(entry.get("summary") or entry.get("description"))
        if any(w in title or w in raw for w in exclude_words):
            continue
        if re.search(r"[가-힣]", title + source):
            continue  # 韓国語サイトの翻訳記事

        items.append({
            "title": title,
            "source": source,
            "url": entry.get("link", ""),
            "published": published,
            "raw": raw,
            "fetch_page": feed.get("fetch_page", False),
            "grams": title_grams(title),
        })
    log(f"  {feed.get('source', 'Googleニュース')}: {len(items)}件 ({feed.get('google') or url[:60]})")
    return items


def title_grams(title):
    text = re.sub(r"[\W_]", "", title.lower())
    return {text[i:i + 2] for i in range(len(text) - 1)}


def overlap(x, y):
    """短い方の文字の組（2文字ずつ）のうち、相手にも含まれる割合。"""
    return len(x & y) / min(len(x), len(y)) if x and y else 0


def is_similar(a, b):
    """同じ話題かどうか。タイトルがよく似ていれば同じ、そこそこ似ていれば要約の中身も比べる。"""
    if a["url"] == b["url"]:
        return True
    title = overlap(a["grams"], b["grams"])
    if title >= 0.5:
        return True
    if title >= 0.3 and a.get("summary") and b.get("summary"):
        return overlap(title_grams(a["title"] + a["summary"]), title_grams(b["title"] + b["summary"])) >= 0.3
    return False


def enrich(item, limit_chars):
    """要約を作り、わかりやすさの点数を付ける。"""
    if urlparse(item["url"]).netloc == "news.google.com":
        item["url"] = resolve_google_news(item["url"])
        item["fetch_page"] = True
    text = item["raw"]
    if (item["fetch_page"] or len(text) < 30) and urlparse(item["url"]).netloc != "news.google.com":
        text = og_description(item["url"]) or text
    item["summary"] = summarize(text, item["title"], limit_chars)
    shared = item["grams"] & title_grams(item["summary"])
    if item["summary"] and len(shared) < 3:
        item["summary"] = ""  # タイトルとほとんど共通の語がない＝サイト共通の紹介文など
    # 要約が長く、文として完結しているほど内容が伝わりやすい
    item["score"] = min(len(item["summary"]), limit_chars) + (30 if item["summary"].endswith("。") else 0)
    return item


def collect_genre(genre, limit_chars, now, seen, exclude_words, age_limit):
    log(f"[{genre['name']}]")
    per_feed = [collect_feed(f, genre, now, exclude_words, age_limit) for f in genre["feeds"]]
    for items in per_feed:
        items.sort(key=lambda x: x["published"] or 0, reverse=True)

    # 複数サイトの記事が交互に並ぶように取り出し、類似記事の比較用に多めに候補を集める
    max_items = genre.get("max_items", 5)
    candidates = []
    while len(candidates) < max_items * 3 and any(per_feed):
        for items in per_feed:
            if items and len(candidates) < max_items * 3:
                candidates.append(items.pop(0))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda it: enrich(it, limit_chars), candidates))

    chosen = []
    for item in candidates:
        twin = next((c for c in seen + chosen if is_similar(item, c)), None)
        if twin is None:
            if len(chosen) < max_items:
                chosen.append(item)
        elif item["score"] > twin["score"]:
            # 同じ話題なら、要約がよりわかりやすい記事に差し替える（並び順・ジャンルはそのまま）
            log(f"  差し替え: {twin['title'][:28]}（{twin['source']}）→ {item['source']}")
            twin.update(item)
        else:
            log(f"  類似のため除外: {item['title'][:28]}（{item['source']}）")
    seen.extend(chosen)
    return chosen


# ---------- 読み上げ原稿 ----------

def for_speech(text):
    """読み上げに向かない記号を整える。"""
    text = re.sub(r"【[^】]*】|\[[^\]]*\]", "", text)                 # 【気象予報士解説】などのラベル
    text = re.sub(r"\s*[|｜].*$", "", text)                            # 「|著者名」「|サイト名」
    text = re.sub(r"\((?:[A-Za-z0-9 .&-]{1,12})\)", "", text)          # 人工知能(AI) の (AI)
    text = re.sub(r"(\d)\s*[~〜]\s*(\d)", r"\1から\2", text)           # 10~20 → 10から20
    text = re.sub(r"[~〜→⇒“”\"#*]", "", text)
    text = re.sub(r"\.{3,}", "、", text)
    return text.strip(" 、")


ENDINGS = ("。", "！", "？", "!", "?")


def spoken_title(title):
    text = re.sub(r"[\s　]+", "、", for_speech(title) or title).strip("、")
    text = re.sub(r"([!?！？])、", r"\1 ", text)                        # 「見える?、4回の」→「見える? 4回の」
    return text if text.endswith(ENDINGS) else text + "。"


def spoken_summary(summary):
    """本文は文として完結した部分だけを読む（途中で切れた断片は読まない）。"""
    text = for_speech(summary)
    if text.endswith("…") or not re.search(r"\w", text):
        return ""
    return text if text.endswith(ENDINGS) else text + "。"


def build_segments(genres, today):
    """(種類, テキスト, 対象) の列。対象は音声開始位置を書き込む dict。"""
    date = f"{today.month}月{today.day}日、{WEEKDAYS[today.weekday()]}曜日"
    segs = [("intro", f"おはようございます。{date}、朝のニュースです。", None), ("pause", PAUSE_AFTER_GENRE, None)]
    for i, g in enumerate(genres):
        lead = "まずは、" if i == 0 else "続いて、"
        if g["items"]:
            segs.append(("genre", f"{lead}{g['name']}のニュースです。", g))
        else:
            segs.append(("genre", f"{lead}{g['name']}です。新しいニュースはありませんでした。", g))
        segs.append(("pause", PAUSE_AFTER_GENRE, None))
        for item in g["items"]:
            # 見出しのあとにワンテンポ置いてから本文を読む
            segs.append(("item", spoken_title(item["title"]), item))
            body = spoken_summary(item["summary"])
            if body:
                segs.append(("pause", PAUSE_AFTER_HEADLINE, None))
                segs.append(("body", body, item))
            segs.append(("pause", PAUSE_BETWEEN_ITEMS, None))
    segs.append(("outro", f"以上、{today.month}月{today.day}日のニュースでした。今日も良い一日を。", None))
    return segs


# ---------- 口の形（リップシンク用） ----------

KAKASI = pykakasi.kakasi()


def word_vowels(text):
    """単語の読みから、口の形の並びを返す（a i u e o、口を閉じる n）。例：首相 → shushou → uou"""
    shapes = ""
    for part in KAKASI.convert(text):
        roman = part["hepburn"].lower()
        if not re.fullmatch(r"[a-z']+", roman):
            # 読めなかった数字・英字などは、文字数ぶん「あ」「え」を交互に当てる
            shapes += "".join("ae"[i % 2] for i, ch in enumerate(roman) if ch.isalnum())
            continue
        for i, ch in enumerate(roman):
            if ch in "aiueo":
                shapes += ch
            elif ch == "n" and (i + 1 == len(roman) or roman[i + 1] not in "aiueoy"):
                shapes += "n"                       # 「ん」は口を閉じる
    return shapes or "a"


# ---------- 音声合成 ----------

async def synth(text, voice, rate, sem):
    """音声と、単語ごとの発話タイミング [(開始秒, 長さ秒, 口の形の並び), ...] を返す（キャスターのリップシンク用）。"""
    async with sem:
        for attempt in range(3):
            try:
                data, words = b"", []
                async for chunk in edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary").stream():
                    if chunk["type"] == "audio":
                        data += chunk["data"]
                    elif chunk["type"] == "WordBoundary":
                        words.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7, word_vowels(chunk["text"])))
                if data:
                    return data, words
            except Exception as e:
                log(f"  ! 音声合成リトライ {attempt + 1}: {e}")
            await asyncio.sleep(2 * (attempt + 1))
        # 1か所の失敗で全体を止めない（その部分は短い無音にする）
        log(f"  ! 音声合成に失敗したので飛ばします: {text[:30]}")
        return SILENT_FRAME * 10, []


async def synth_all(segs, voice, rate):
    sem = asyncio.Semaphore(4)
    async def one(kind, value):
        if kind == "pause":
            return SILENT_FRAME * round(value / 0.024), []
        return await synth(value, voice, rate, sem)
    return await asyncio.gather(*(one(kind, value) for kind, value, _ in segs))


# ---------- メイン ----------

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    now_ts = time.time()
    today = datetime.now(JST)
    limit = config.get("summary_chars", 120)
    age_limit = config.get("max_age_hours", 48)

    seen = []
    exclude_words = config.get("exclude_title_words", [])
    genres = [{"name": g["name"], "items": collect_genre(g, limit, now_ts, seen, exclude_words, age_limit)} for g in config["genres"]]
    if not seen:
        log("記事が1件も取得できなかったため中止します")
        sys.exit(1)

    segs = build_segments(genres, today)
    log(f"音声合成中… ({sum(k != 'pause' for k, _, _ in segs)}セグメント)")
    results = asyncio.run(synth_all(segs, config["voice"], config.get("rate", "+0%")))
    chunks = [audio for audio, _ in results]

    # MP3フレームはそのまま連結でき、各セグメントの開始秒はバイト数から計算できる
    offset = 0
    cues, speech = [], []   # 字幕（話している文）と、単語ごとの発話区間（口パク用）
    for (kind, value, target), (chunk, words) in zip(segs, results):
        start = offset / MP3_BYTES_PER_SEC
        if target is not None:
            target["body_start" if kind == "body" else "start"] = round(start, 2)
        if kind != "pause":
            cues.append({"start": round(start, 2), "end": round(start + len(chunk) / MP3_BYTES_PER_SEC, 2), "kind": kind, "text": value})
            for w, d, shapes in words:
                speech += [round(start + w, 2), round(d, 2), shapes]
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
                "body_start": it.get("body_start"),
            } for it in g["items"]],
        } for g in genres],
        "cues": cues,
    }
    (DOCS / "data" / "latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    # リップシンク用の発話区間（[開始秒, 長さ秒, 口の形, ...]）は数千件になるので、別ファイルに詰めて保存
    (DOCS / "data" / "speech.json").write_text(json.dumps(speech, separators=(",", ":")), encoding="utf-8")
    log(f"完了: {len(seen)}本 / {int(duration // 60)}分{int(duration % 60)}秒")


if __name__ == "__main__":
    main()
