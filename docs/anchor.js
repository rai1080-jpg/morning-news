// AIで作ったキャスターの「話している動画」と「黙っている動画」を、読み上げに合わせて切り替える。
// 話しているかどうかは、ニュース生成時に記録した単語ごとの発話区間（data/speech.json）と音声の再生位置で判断する。
// 音声そのものは解析しない（iPhoneで画面ロック中も再生を止めないため）。
(() => {
  const audio = document.getElementById("audio");
  const stage = document.querySelector(".stage");
  const idle = document.getElementById("anchor-idle");
  const talk = document.getElementById("anchor-talk");

  const HOLD_SEC = 0.5;     // これ以上黙ったら「黙っている動画」に戻す（息継ぎでチカチカさせない）

  let speech = [];          // [開始秒, 長さ秒, 開始秒, 長さ秒, ...]
  let visible = true;
  let lastWordEnd = -Infinity;

  async function loadSpeech() {
    try {
      const res = await fetch(`data/speech.json?t=${Date.now()}`);
      if (res.ok) speech = await res.json();
    } catch {
      speech = [];
    }
  }

  // 再生位置 t で話している単語の終わりの秒（話していなければ null）
  function wordEndAt(t) {
    let lo = 0, hi = speech.length / 2 - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const start = speech[mid * 2], end = start + speech[mid * 2 + 1];
      if (t < start) hi = mid - 1;
      else if (t > end) lo = mid + 1;
      else return end;
    }
    return null;
  }

  function playVideos() {
    for (const v of [idle, talk]) v.play().catch(() => {});
  }

  function pauseVideos() {
    for (const v of [idle, talk]) v.pause();
  }

  function tick() {
    requestAnimationFrame(tick);
    if (!visible || document.hidden) return;
    const t = audio.currentTime;
    const end = audio.paused ? null : wordEndAt(t);
    if (end !== null) lastWordEnd = end;
    const talking = !audio.paused && (end !== null || t - lastWordEnd < HOLD_SEC);
    stage.classList.toggle("talking", talking);
  }

  // 画面外・裏に回ったときは動画を止めて電池を節約する
  new IntersectionObserver(([e]) => {
    visible = e.isIntersecting;
    if (visible && !document.hidden) playVideos(); else pauseVideos();
  }).observe(stage);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pauseVideos(); else if (visible) playVideos();
  });
  // 省電力モードなどで自動再生が止められていても、再生ボタンを押したら動き出すようにする
  audio.addEventListener("play", playVideos);
  audio.addEventListener("seeked", () => { lastWordEnd = -Infinity; });

  loadSpeech();
  playVideos();
  tick();
})();
