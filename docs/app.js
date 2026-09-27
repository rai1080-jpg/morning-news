const $ = (id) => document.getElementById(id);
const audio = $("audio");
const RATES = [1, 1.25, 1.5, 1.75];

let items = [];      // 全記事（音声の順）
let current = -1;    // 再生中の記事の index
let activeTab = localGet("tab") || "すべて";

function localGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function localSet(key, v) { try { localStorage.setItem(key, v); } catch {} }

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}

async function load() {
  let data;
  try {
    const res = await fetch(`data/latest.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(res.status);
    data = await res.json();
  } catch {
    $("date").textContent = "";
    $("error").textContent = "ニュースがまだ生成されていません。";
    $("error").hidden = false;
    return;
  }

  $("date").textContent = data.date_label;
  const total = data.genres.reduce((n, g) => n + g.items.length, 0);
  const updated = data.generated_at.slice(11, 16);
  $("meta").textContent = `${total}本・約${Math.round(data.duration / 60)}分・${updated}更新`;

  items = data.genres.flatMap((g) => g.items.map((it) => ({ ...it, genre: g.name })));
  audio.src = `${data.audio}?d=${data.date}`;
  $("play").disabled = false;

  renderTabs(data.genres);
  renderList(data.genres);
  setupMediaSession(data);

  const savedRate = parseFloat(localGet("rate"));
  if (RATES.includes(savedRate)) setRate(savedRate);
}

function renderTabs(genres) {
  const names = ["すべて", ...genres.map((g) => g.name)];
  if (!names.includes(activeTab)) activeTab = "すべて";
  $("tabs").replaceChildren(...names.map((name) =>
    el("button", {
      class: "tab", role: "tab", "aria-selected": String(name === activeTab),
      onclick: () => {
        activeTab = name;
        localSet("tab", name);
        document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.textContent === name)));
        document.querySelectorAll(".genre").forEach((s) => { s.hidden = name !== "すべて" && s.dataset.name !== name; });
      },
    }, name)));
}

function renderList(genres) {
  let index = 0;
  $("list").replaceChildren(...genres.map((g) => {
    const section = el("section", { class: "genre", "data-name": g.name },
      el("h2", {}, g.name, el("span", { class: "count" }, `${g.items.length}本`)));
    section.hidden = activeTab !== "すべて" && activeTab !== g.name;
    if (!g.items.length) section.append(el("p", { class: "empty" }, "新しいニュースはありませんでした"));
    for (const it of g.items) {
      const i = index++;
      const time = it.published ? it.published.slice(5, 16).replace("T", " ").replace("-", "/") : "";
      section.append(el("article", { class: "card", id: `item-${i}` },
        el("h3", {}, it.title),
        it.summary ? el("p", {}, it.summary) : null,
        el("div", { class: "card-foot" },
          el("span", {}, el("a", { href: it.url, target: "_blank", rel: "noopener" }, it.source), time ? `・${time}` : ""),
          el("button", { class: "from", onclick: () => playFrom(i) }, "▶ ここから"))));
    }
    return section;
  }));
}

function playFrom(i) {
  audio.currentTime = items[i].start;
  audio.play();
}

function indexAt(t) {
  let idx = -1;
  items.forEach((it, i) => { if (it.start <= t + 0.05) idx = i; });
  return idx;
}

function updateCurrent() {
  const idx = indexAt(audio.currentTime);
  if (idx === current) return;
  document.getElementById(`item-${current}`)?.classList.remove("current");
  current = idx;
  const card = document.getElementById(`item-${idx}`);
  card?.classList.add("current");
  $("now").textContent = idx >= 0 ? `${items[idx].genre}｜${items[idx].title}` : "全部聴く";
  if (card && !audio.paused && !card.closest("[hidden]")) card.scrollIntoView({ behavior: "smooth", block: "center" });
  if ("mediaSession" in navigator && navigator.mediaSession.metadata && idx >= 0) {
    navigator.mediaSession.metadata.title = items[idx].title;
    navigator.mediaSession.metadata.album = items[idx].genre;
  }
}

function setRate(r) {
  audio.playbackRate = r;
  $("rate").textContent = `${r.toFixed(r % 1 ? 2 : 1).replace(/0$/, "")}×`;
  localSet("rate", r);
}

function skip(dir) {
  const idx = indexAt(audio.currentTime);
  // 記事の頭から3秒以上経っていれば「前へ」はその記事の頭に戻る
  let target = dir < 0 && idx >= 0 && audio.currentTime - items[idx].start > 3 ? idx : idx + dir;
  target = Math.max(0, Math.min(items.length - 1, target));
  if (items[target]) playFrom(target);
}

function setupMediaSession(data) {
  if (!("mediaSession" in navigator)) return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: `朝のニュース ${data.date_label}`, artist: "朝のニュース", album: "",
    artwork: [{ src: "icons/icon-512.png", sizes: "512x512", type: "image/png" }],
  });
  navigator.mediaSession.setActionHandler("play", () => audio.play());
  navigator.mediaSession.setActionHandler("pause", () => audio.pause());
  navigator.mediaSession.setActionHandler("previoustrack", () => skip(-1));
  navigator.mediaSession.setActionHandler("nexttrack", () => skip(1));
}

$("play").addEventListener("click", () => (audio.paused ? audio.play() : audio.pause()));
$("prev").addEventListener("click", () => skip(-1));
$("next").addEventListener("click", () => skip(1));
$("rate").addEventListener("click", () => setRate(RATES[(RATES.indexOf(audio.playbackRate) + 1) % RATES.length]));
$("seek").addEventListener("input", (e) => { audio.currentTime = (e.target.value / 100) * audio.duration; });

audio.addEventListener("play", () => $("play").classList.add("playing"));
audio.addEventListener("pause", () => $("play").classList.remove("playing"));
audio.addEventListener("ratechange", () => { if (!RATES.includes(audio.playbackRate)) setRate(1); });
audio.addEventListener("timeupdate", () => {
  if (audio.duration) $("seek").value = (audio.currentTime / audio.duration) * 100;
  $("time").textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
  updateCurrent();
});
audio.addEventListener("loadedmetadata", () => { $("time").textContent = `0:00 / ${fmt(audio.duration)}`; });
audio.addEventListener("error", () => {
  $("error").textContent = "音声を読み込めませんでした。";
  $("error").hidden = false;
});

load();
