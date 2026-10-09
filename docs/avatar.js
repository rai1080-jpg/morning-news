// 3Dアバター（VRM）がニュースを読み上げているように動かす。
// 口パクは、ニュース生成時に記録した「単語ごとの発話区間」（data/speech.json）と音声の再生位置を合わせて行う。
// 音声そのものは解析しない（iPhoneで画面ロック中も再生を止めないため）。
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

const MODEL_URL = "avatar/caster.vrm";
const VOWELS = ["aa", "ih", "ou", "ee", "oh"];

const audio = document.getElementById("audio");
const canvas = document.getElementById("avatar");
const stage = document.querySelector(".stage");
const status = document.getElementById("stage-status");

let speech = [];          // [開始秒, 長さ秒, 開始秒, 長さ秒, ...] の平たい配列
let vrm = null;
let visible = true;
let nextBlink = 2;
const mouth = Object.fromEntries(VOWELS.map((v) => [v, 0]));

const renderer = createRenderer();
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(22, 1, 0.1, 20);
const clock = new THREE.Clock();

function createRenderer() {
  try {
    const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    return r;
  } catch {
    return null;
  }
}

function showStatus(text) {
  status.textContent = text;
  status.hidden = !text;
}

async function loadSpeech() {
  try {
    const res = await fetch(`data/speech.json?t=${Date.now()}`);
    if (res.ok) speech = await res.json();
  } catch {
    speech = [];
  }
}

function loadModel() {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  loader.load(
    MODEL_URL,
    (gltf) => {
      vrm = gltf.userData.vrm;
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      VRMUtils.rotateVRM0(vrm);
      vrm.scene.traverse((o) => { o.frustumCulled = false; });
      scene.add(vrm.scene);
      relaxPose();
      // 腕を下ろした姿勢を揺れ物（袖・髪）の基準にする。これをしないとTポーズの位置に引っ張られて袖が浮く
      vrm.humanoid.update();
      vrm.scene.updateMatrixWorld(true);
      vrm.springBoneManager?.setInitState();
      vrm.springBoneManager?.reset();
      frameBustShot();
      if (vrm.lookAt) vrm.lookAt.target = camera;
      showStatus("");
    },
    (e) => { if (e.total) showStatus(`キャスターを準備中… ${Math.round((e.loaded / e.total) * 100)}%`); },
    () => showStatus("キャスターを表示できませんでした"),
  );
}

// Tポーズから、腕を下ろした自然な立ち姿にする
function relaxPose() {
  const bone = (name) => vrm.humanoid.getNormalizedBoneNode(name);
  bone("leftUpperArm").rotation.z = -1.33;
  bone("rightUpperArm").rotation.z = 1.33;
  bone("leftLowerArm").rotation.z = -0.12;
  bone("rightLowerArm").rotation.z = 0.12;
  bone("leftHand").rotation.z = -0.1;
  bone("rightHand").rotation.z = 0.1;
}

// 頭から胸までが入るバストアップの構図
function frameBustShot() {
  vrm.scene.updateMatrixWorld(true);
  const head = new THREE.Vector3();
  vrm.humanoid.getNormalizedBoneNode("head").getWorldPosition(head);
  camera.position.set(0, head.y + 0.02, 1.75);
  camera.lookAt(0, head.y - 0.12, 0);
}

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

// 再生位置 t で話している単語の [開始秒, 長さ秒]（話していなければ null）
function wordAt(t) {
  let lo = 0, hi = speech.length / 2 - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const start = speech[mid * 2], dur = speech[mid * 2 + 1];
    if (t < start) hi = mid - 1;
    else if (t > start + dur) lo = mid + 1;
    else return [start, dur, mid];
  }
  return null;
}

function updateMouth(dt) {
  const talking = !audio.paused && wordAt(audio.currentTime);
  const target = Object.fromEntries(VOWELS.map((v) => [v, 0]));
  if (talking) {
    const [start, , index] = talking;
    // 約0.11秒ごとに母音を切り替え、開き具合も揺らして「しゃべっている」口にする
    const step = Math.floor((audio.currentTime - start) / 0.11);
    const vowel = VOWELS.at((index * 3 + step) % VOWELS.length);
    target[vowel] = 0.55 + 0.35 * Math.abs(Math.sin(audio.currentTime * 17));
  }
  const ease = 1 - Math.exp(-dt * 22);
  for (const v of VOWELS) {
    mouth[v] += (target[v] - mouth[v]) * ease;
    vrm.expressionManager.setValue(v, mouth[v]);
  }
  return Boolean(talking);
}

function updateBlink(time) {
  const left = nextBlink - time;
  let w = 0;
  if (left <= 0) {
    const p = -left / 0.16;                 // 0.16秒でまばたき
    w = p < 1 ? Math.sin(p * Math.PI) : 0;
    if (p >= 1) nextBlink = time + 2 + Math.random() * 4;
  }
  vrm.expressionManager.setValue("blink", w);
}

function updateBody(time, talking) {
  const bone = (name) => vrm.humanoid.getNormalizedBoneNode(name);
  bone("chest").rotation.x = Math.sin(time * 1.6) * 0.012;                       // 呼吸
  bone("spine").rotation.z = Math.sin(time * 0.45) * 0.012;
  const nod = talking ? Math.sin(time * 3.1) * 0.025 : 0;                       // 話しながら小さくうなずく
  bone("head").rotation.x = Math.sin(time * 0.7) * 0.02 + nod;
  bone("head").rotation.y = Math.sin(time * 0.33) * 0.05;
  bone("head").rotation.z = Math.sin(time * 0.5) * 0.015;
  vrm.expressionManager.setValue("relaxed", 0.25);                              // やわらかい表情
}

function tick() {
  requestAnimationFrame(tick);
  const dt = Math.min(clock.getDelta(), 0.1);
  if (!vrm || !visible || document.hidden) return;
  const time = clock.elapsedTime;
  const talking = updateMouth(dt);
  updateBlink(time);
  updateBody(time, talking);
  vrm.update(dt);
  renderer.render(scene, camera);
}

function setupLights() {
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(0.6, 1.4, 2);
  scene.add(key, new THREE.AmbientLight(0xffffff, 0.7));
}

if (renderer) {
  setupLights();
  resize();
  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);
  // 再生ボタンを押したり新しいニュースを読み込んだりしたら、口パク用データも読み直す
  audio.addEventListener("loadedmetadata", loadSpeech);
  loadSpeech();
  showStatus("キャスターを準備中…");
  loadModel();
  tick();
} else {
  showStatus("この端末では3D表示に対応していません");
}
