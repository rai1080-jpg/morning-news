"""口の形（あいうえお）とまばたきの部分画像を作る。
口は「頭を動かさず母音を発音する」見本動画（frames_vowels）から、まばたきは黙っている動画から切り出し、
口を閉じた土台の写真（base_closed.png）に位置と肌色を合わせて保存する。"""
import json, os, sys, numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

vowel = {r["f"].replace("\\", "/"): r for r in json.load(open("vowel_features.json"))}     # 土台からのずれ
older = {r["f"].replace("\\", "/"): r for r in json.load(open("frame_features.json"))}     # talk2 先頭コマからのずれ
CHOICE = {"i": 5, "e": 9, "a": 12, "o": 10, "u": 3}
BLINK = "frames_idle/0072.png"
MOUTH, EYES = (204, 340, 352, 462), (172, 228, 392, 296)
base = Image.open("base_closed.png").convert("RGB")

def shift_of(src):
    if src in vowel: return vowel[src]["dy"], vowel[src]["dx"]
    b = older["frames_talk2/0029.png"]; s = older[src]
    return s["dy"] - b["dy"], s["dx"] - b["dx"]

def patch(src, box, blur):
    dy, dx = shift_of(src)
    x0, y0, x1, y1 = box
    piece = np.asarray(Image.open(src).convert("RGB").crop((x0 + dx, y0 + dy, x1 + dx, y1 + dy)) if src in vowel
                       else Image.open(src).convert("RGB").crop((x0 - dx, y0 - dy, x1 - dx, y1 - dy)), dtype=np.float32)
    ref = np.asarray(base.crop(box), dtype=np.float32)
    m = Image.new("L", (x1 - x0, y1 - y0), 0); ImageDraw.Draw(m).ellipse((8, 8, x1 - x0 - 8, y1 - y0 - 8), fill=255)
    alpha = np.asarray(m.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32) / 255
    ring = (alpha > 0.05) & (alpha < 0.6)                 # 境目の帯で、色ごとの明るさを土台に合わせる
    piece = np.clip(piece * (ref[ring].mean(0) / np.maximum(piece[ring].mean(0), 1)), 0, 255)
    return Image.fromarray(np.dstack([piece, alpha * 255]).astype(np.uint8), "RGBA")

out_dir = sys.argv[1]; os.makedirs(out_dir, exist_ok=True)
parts = {k: patch(f"frames_vowels/{n:04d}.png", MOUTH, 10) for k, n in CHOICE.items()}
parts["blink"] = patch(BLINK, EYES, 7)
base.save(f"{out_dir}/base.jpg", quality=88)
for k, p in parts.items(): p.save(f"{out_dir}/{k}.png", optimize=True)
json.dump({"width": base.width, "height": base.height, "mouth": list(MOUTH), "eyes": list(EYES)}, open(f"{out_dir}/layout.json", "w"))
f = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 20)
S = Image.new("RGB", (4 * 300, 2 * 330), "white"); d = ImageDraw.Draw(S)
for i, k in enumerate(["n", *parts]):
    comp = base.copy()
    if k != "n": box = EYES if k == "blink" else MOUTH; comp.paste(parts[k], box[:2], parts[k])
    x, y = (i % 4) * 300, (i // 4) * 330; S.paste(comp.crop((130, 180, 430, 500)), (x, y)); d.text((x + 8, y + 296), k, fill="white", font=f)
S.save("viseme_composite3.png"); print("ok")
