// 福岡市の今日の天気ダッシュボード。ページを開くたびに最新のデータを取得する。
//   気象庁：天気（福岡地方）・最高/最低気温（福岡）・6時間ごとの降水確率
//   Open-Meteo：今の気温・体感・湿度・風、1時間ごとの気温と降水確率（グラフ用）
(() => {
  const JMA_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/400000.json";
  const JMA_AREA = "400010";     // 福岡地方
  const JMA_TEMP = "82182";      // 福岡（気温の観測地点）
  const METEO_URL = "https://api.open-meteo.com/v1/forecast?latitude=33.5902&longitude=130.4017"
    + "&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code"
    + "&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min"
    + "&timezone=Asia%2FTokyo&forecast_days=1&wind_speed_unit=ms";

  const box = document.getElementById("weather");
  const $ = (sel) => box.querySelector(sel);
  const SVG = "http://www.w3.org/2000/svg";
  let hourly = null;   // [{ hour, temp, pop }]

  const today = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);   // 日本時間の日付
  const nowHour = () => new Date(Date.now() + 9 * 3600e3).getUTCHours();

  async function getJson(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    return res.json();
  }

  // 気象庁の天気文（全角スペース区切り）を読みやすく
  function tidyWeather(text) {
    return text.replace(/[\s　]+/g, "").replace(/(.)所により/, "$1、所により");
  }

  // 気象庁の天気コードの先頭（1晴れ・2くもり・3雨・4雪）で主な天気を決め、「時々晴れ」などを添える
  function icon(code, text) {
    const main = String(code)[0];
    if (main === "4") return "❄️";
    if (main === "3") return text.includes("晴") ? "🌦️" : "🌧️";
    if (main === "1") return text.includes("くもり") || text.includes("雨") ? "🌤️" : "☀️";
    return /時々晴|のち晴|一時晴/.test(text) ? "⛅" : "☁️";
  }

  function parseJma(data) {
    const series = data[0].timeSeries;
    const area = series[0].areas.find((a) => a.area.code === JMA_AREA);
    const date = today();
    // 降水確率：今日の6時間ごと
    const pops = series[1].timeDefines
      .map((t, i) => ({ from: Number(t.slice(11, 13)), date: t.slice(0, 10), pop: series[1].areas.find((a) => a.area.code === JMA_AREA).pops[i] }))
      .filter((p) => p.date === date && p.pop !== "");
    // 気温：今日の 09:00 の値＝日中の最高、00:00 の値＝朝の最低（朝を過ぎると最高と同じ値になるので使わない）
    const temps = series[2].areas.find((a) => a.area.code === JMA_TEMP).temps;
    let max = null, min = null;
    series[2].timeDefines.forEach((t, i) => {
      if (t.slice(0, 10) !== date) return;
      if (t.slice(11, 13) === "09") max = Number(temps[i]);
      if (t.slice(11, 13) === "00") min = Number(temps[i]);
    });
    if (min === max) min = null;
    return {
      weather: tidyWeather(area.weathers[0]),
      code: area.weatherCodes[0],
      reported: data[0].reportDatetime.slice(11, 16),
      pops, max, min,
    };
  }

  function render(jma, meteo) {
    const c = meteo.current;
    const weather = jma ? jma.weather : "";
    $(".wx-icon").textContent = weather ? icon(jma.code, weather) : "🌡️";
    $(".wx-text").textContent = weather || "天気予報を取得できませんでした";
    $(".wx-now").textContent = `${c.temperature_2m.toFixed(1)}°`;
    $(".wx-feel").textContent = `体感 ${Math.round(c.apparent_temperature)}° ・ 湿度 ${c.relative_humidity_2m}% ・ 風 ${c.wind_speed_10m.toFixed(1)}m/s`;

    const max = jma?.max ?? Math.round(meteo.daily.temperature_2m_max[0]);
    const min = jma?.min ?? Math.round(meteo.daily.temperature_2m_min[0]);
    $(".wx-max").textContent = `${max}°`;
    $(".wx-min").textContent = `${min}°`;

    // 降水確率：気象庁の「今の時間帯」の値（なければ1時間ごと予報の今の値）
    const h = nowHour();
    const block = jma?.pops.filter((p) => p.from <= h).at(-1) ?? jma?.pops[0];
    const nowPop = block ? `${block.pop}%` : `${meteo.hourly.precipitation_probability[h]}%`;
    $(".wx-pop").textContent = nowPop;
    $(".wx-pop-time").textContent = block ? `${block.from}〜${block.from + 6}時` : "今の時間";
    $(".wx-pops").textContent = jma?.pops.length
      ? jma.pops.map((p) => `${p.from}〜${p.from + 6}時 ${p.pop}%`).join("　")
      : "";

    $(".wx-source").textContent = jma ? `気象庁 ${jma.reported}発表・Open-Meteo` : "Open-Meteo";

    hourly = meteo.hourly.time.map((t, i) => ({
      hour: Number(t.slice(11, 13)),
      temp: meteo.hourly.temperature_2m[i],
      pop: meteo.hourly.precipitation_probability[i],
    }));
    drawCharts();
    renderTable();
    box.classList.remove("loading");
  }

  // ---------- グラフ（気温の折れ線・降水確率の棒。単位が違うので上下に分け、時刻をそろえる） ----------

  function el(name, attrs = {}, parent) {
    const node = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    parent?.appendChild(node);
    return node;
  }

  function drawCharts() {
    if (!hourly) return;
    const wrap = $(".wx-charts");
    const W = wrap.clientWidth;
    if (!W) return;
    const padL = 30, padR = 12;
    const x = (hr) => padL + (hr / 23) * (W - padL - padR);
    const h = nowHour();

    // 気温
    const tempSvg = $(".wx-temp-chart");
    tempSvg.replaceChildren();
    const TH = 120, tTop = 14, tBottom = TH - 6;
    tempSvg.setAttribute("viewBox", `0 0 ${W} ${TH}`);
    const temps = hourly.map((d) => d.temp);
    const lo = Math.floor(Math.min(...temps) - 1), hi = Math.ceil(Math.max(...temps) + 1);
    const yT = (v) => tBottom - ((v - lo) / (hi - lo)) * (tBottom - tTop);
    const step = hi - lo > 8 ? 4 : 2;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      el("line", { x1: padL, x2: W - padR, y1: yT(v), y2: yT(v), class: "wx-grid" }, tempSvg);
      el("text", { x: padL - 6, y: yT(v) + 4, class: "wx-tick", "text-anchor": "end" }, tempSvg).textContent = `${v}°`;
    }
    const pts = hourly.map((d) => `${x(d.hour)},${yT(d.temp)}`).join(" ");
    el("polygon", { points: `${x(0)},${tBottom} ${pts} ${x(23)},${tBottom}`, class: "wx-temp-area" }, tempSvg);
    el("polyline", { points: pts, class: "wx-temp-line" }, tempSvg);
    // 最高気温の点にだけ値を添える
    const peak = hourly.reduce((a, b) => (b.temp > a.temp ? b : a));
    el("text", { x: x(peak.hour), y: yT(peak.temp) - 7, class: "wx-label", "text-anchor": "middle" }, tempSvg).textContent = `${peak.temp.toFixed(0)}°`;
    // 今の時刻
    const now = hourly[h];
    el("line", { x1: x(h), x2: x(h), y1: tTop - 6, y2: tBottom, class: "wx-now-line" }, tempSvg);
    el("circle", { cx: x(h), cy: yT(now.temp), r: 4.5, class: "wx-temp-dot" }, tempSvg);

    // 降水確率
    const popSvg = $(".wx-pop-chart");
    popSvg.replaceChildren();
    const PH = 74, pTop = 6, pBottom = PH - 20;
    popSvg.setAttribute("viewBox", `0 0 ${W} ${PH}`);
    const yP = (v) => pBottom - (v / 100) * (pBottom - pTop);
    for (const v of [0, 50, 100]) {
      el("line", { x1: padL, x2: W - padR, y1: yP(v), y2: yP(v), class: v === 0 ? "wx-base" : "wx-grid" }, popSvg);
      el("text", { x: padL - 6, y: yP(v) + 4, class: "wx-tick", "text-anchor": "end" }, popSvg).textContent = `${v}%`;
    }
    const bw = Math.min(10, ((W - padL - padR) / 24) - 2);
    for (const d of hourly) {
      if (!d.pop) continue;
      const top = yP(d.pop), r = Math.min(3, (pBottom - top) / 2);
      // 先端だけ角を丸め、根元は四角のまま
      el("path", {
        d: `M${x(d.hour) - bw / 2},${pBottom} V${top + r} q0,-${r} ${r},-${r} H${x(d.hour) + bw / 2 - r} q${r},0 ${r},${r} V${pBottom} Z`,
        class: "wx-pop-bar",
      }, popSvg);
    }
    for (const hr of [0, 6, 12, 18, 23]) {
      el("text", { x: x(hr), y: PH - 4, class: "wx-tick", "text-anchor": "middle" }, popSvg).textContent = `${hr}時`;
    }
    el("line", { x1: x(h), x2: x(h), y1: pTop, y2: pBottom, class: "wx-now-line" }, popSvg);

    setupHover(W, x, padL, padR);
  }

  // グラフに触れると、その時刻の気温と降水確率を表示する
  function setupHover(W, x, padL, padR) {
    const charts = $(".wx-charts");
    const tip = $(".wx-tip");
    const cross = $(".wx-cross");
    const show = (clientX) => {
      const rect = charts.getBoundingClientRect();
      const px = ((clientX - rect.left) / rect.width) * W;
      const hr = Math.max(0, Math.min(23, Math.round(((px - padL) / (W - padL - padR)) * 23)));
      const d = hourly[hr];
      const left = (x(hr) / W) * rect.width;
      tip.innerHTML = `<b>${hr}時</b> ${d.temp.toFixed(1)}° ・ 降水 ${d.pop}%`;
      tip.hidden = false;
      tip.style.left = `${Math.max(60, Math.min(rect.width - 60, left))}px`;
      cross.hidden = false;
      cross.style.left = `${left}px`;
    };
    const hide = () => { tip.hidden = true; cross.hidden = true; };
    charts.onpointermove = (e) => show(e.clientX);
    charts.onpointerdown = (e) => show(e.clientX);
    charts.onpointerleave = hide;
    charts.onkeydown = (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const cur = Number(charts.dataset.hour ?? nowHour()) + (e.key === "ArrowRight" ? 1 : -1);
      const hr = Math.max(0, Math.min(23, cur));
      charts.dataset.hour = hr;
      const rect = charts.getBoundingClientRect();
      show(rect.left + (x(hr) / W) * rect.width);
    };
    charts.onblur = hide;
  }

  function renderTable() {
    const rows = hourly.map((d) => `<tr><td>${d.hour}時</td><td>${d.temp.toFixed(1)}°</td><td>${d.pop}%</td></tr>`).join("");
    $(".wx-table tbody").innerHTML = rows;
  }

  async function load() {
    const [jma, meteo] = await Promise.allSettled([getJson(JMA_URL), getJson(METEO_URL)]);
    if (meteo.status !== "fulfilled") {
      box.classList.remove("loading");
      $(".wx-text").textContent = "天気を取得できませんでした（電波の良い場所で開き直してください）";
      return;
    }
    let parsed = null;
    try { if (jma.status === "fulfilled") parsed = parseJma(jma.value); } catch { parsed = null; }
    render(parsed, meteo.value);
  }

  new ResizeObserver(() => drawCharts()).observe($(".wx-charts"));
  load();
  // 開いたままの日も、30分ごとに最新に
  setInterval(load, 30 * 60 * 1000);
})();
