// キャスターのリップシンク。
// 口を閉じた写真（anchor/base.jpg）の上に、口の形（a i u e o）とまばたきの画像を重ね、
// 読み上げに合わせて表示を切り替える。
// どの瞬間にどの音を話しているかは、ニュース生成時に記録した
// [開始秒, 長さ秒, 口の形の並び, ...]（data/speech.json）と音声の再生位置から計算する。
// 音声そのものは解析しない（iPhoneで画面ロック中も再生を止めないため）。
(() => {
  const audio = document.getElementById("audio");
  const stage = document.querySelector(".stage");
  const face = document.getElementById("anchor-face");
  const mouths = Object.fromEntries([...face.querySelectorAll("[data-mouth]")].map((el) => [el.dataset.mouth, el]));
  const blink = face.querySelector(".blink");

  let speech = [];
  let visible = true;
  let shown = "";
  let nextBlink = performance.now() + 2500;

  async function loadSpeech() {
    try {
      const res = await fetch(`data/speech.json?t=${Date.now()}`);
      if (res.ok) speech = await res.json();
    } catch {
      speech = [];
    }
  }

  // 再生位置 t で出している音の口の形（a i u e o / 話していなければ ""）
  function shapeAt(t) {
    let lo = 0, hi = speech.length / 3 - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const start = speech[mid * 3], dur = speech[mid * 3 + 1];
      if (t < start) hi = mid - 1;
      else if (t > start + dur) lo = mid + 1;
      else {
        // 単語の長さを音（モーラ）の数で等分し、今の音の口の形を選ぶ
        const shapes = speech[mid * 3 + 2];
        const i = Math.min(shapes.length - 1, Math.floor(((t - start) / dur) * shapes.length));
        const s = shapes[i];
        return s === "n" ? "" : s;
      }
    }
    return "";
  }

  function show(shape) {
    if (shape === shown) return;
    mouths[shown]?.classList.remove("on");
    mouths[shape]?.classList.add("on");
    shown = shape;
  }

  function tick(now) {
    requestAnimationFrame(tick);
    if (!visible || document.hidden) return;
    show(audio.paused ? "" : shapeAt(audio.currentTime));
    // まばたき：2.5〜6秒おきに0.13秒
    if (now >= nextBlink) {
      blink.classList.add("on");
      setTimeout(() => blink.classList.remove("on"), 130);
      nextBlink = now + 2500 + Math.random() * 3500;
    }
  }

  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);
  loadSpeech();
  requestAnimationFrame(tick);
})();
