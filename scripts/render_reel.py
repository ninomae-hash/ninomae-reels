#!/usr/bin/env python3
"""
ninomae ONLINE リール動画ジェネレーター（パステル・ポラロイド版）

商品写真（最大3枚）と短い文字から、Instagramリール用の
15秒・縦長（1080x1920）・30fps の MP4 を作ります。

デザイン
  ・淡いクリーム〜ピンクの背景（ショップのテーマカラー）
  ・白フチのポラロイド風の写真＋マスキングテープ
  ・丸文字（Zen Maru Gothic）と筆記体の店名（Dancing Script）
  ・ふんわり舞う花びら、文字はふわっと浮き上がる
  ・オルゴール風のオリジナルBGM（music/ に曲があればそちらを使用）

入力（環境変数 PAYLOAD に JSON）:
  {
    "job_id": "20261026-1930-161509504",
    "images": ["https://...jpg", ...],
    "slides": ["見出し1", "見出し2", "見出し3"],
    "title": "プリザーブドフラワー「プティットボックス イエロー」｜…",
    "price": "¥7,150（税込）",
    "brand": "ninomae ONLINE"
  }

出力: out/<job_id>.mp4
"""
import glob
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.request
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920
FPS = 30
SLIDE_SEC = 5.4
FADE_SEC = 0.6
TOTAL_SEC = 15.0
N_FRAMES = int(TOTAL_SEC * FPS)
OUT_DIR = "out"

# ---- 色（ninomae ONLINE のショップテーマに合わせたパステル） ----
CREAM = (252, 246, 241)
BLUSH = (246, 226, 228)
PINK = (236, 184, 196)
DEEP_PINK = (206, 132, 156)
MAUVE = (153, 102, 145)      # #996691
ROSE = (184, 154, 148)       # #b89a94
TEXT = (112, 82, 98)         # #705262 付近（読みやすい濃いモーブ）
WHITE = (255, 255, 255)

# ---- Instagramのボタン・キャプションに隠れない範囲 ----
SAFE_TOP, SAFE_BOTTOM = 220, H - 420
BRAND_Y = 222
PHOTO_CENTER_Y = 790
PHOTO_MAX_W, PHOTO_MAX_H = 760, 640
PHOTO_CENTER_Y_LAST, PHOTO_MAX_H_LAST = 735, 540
TEXT_TOP = 1170
CARD_X1, CARD_X2 = 90, W - 130          # 右側はいいね等のボタンを避ける
TEXT_MAX_W = CARD_X2 - CARD_X1 - 90
ZOOM = 0.04
TILTS = [-2.5, 2.0, -1.5]               # ポラロイドの傾き（度）

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIRS = [os.path.join(HERE, "..", "fonts"), "fonts"]
NOTO_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
]


def log(msg):
    print(msg, flush=True)


# ============================================================
#  フォント
# ============================================================

def _find(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _noto():
    for p in NOTO_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


_font_cache = {}


def jp_font(size, bold=True):
    """丸文字（Zen Maru Gothic）。なければ Noto Sans CJK"""
    key = ("jp", size, bold)
    if key not in _font_cache:
        path = _find("ZenMaruGothic-Bold.ttf" if bold else "ZenMaruGothic-Medium.ttf")
        if path:
            _font_cache[key] = ImageFont.truetype(path, size)
        else:
            noto = _noto()
            if not noto:
                sys.exit("日本語フォントが見つかりません")
            _font_cache[key] = ImageFont.truetype(noto, size, index=0)
    return _font_cache[key]


def script_font(size):
    """店名用の筆記体（Dancing Script）。なければ丸文字"""
    key = ("script", size)
    if key not in _font_cache:
        path = _find("DancingScript-VF.ttf")
        if path:
            f = ImageFont.truetype(path, size)
            try:
                f.set_variation_by_axes([700])
            except Exception:
                pass
            _font_cache[key] = f
        else:
            _font_cache[key] = jp_font(size)
    return _font_cache[key]


def has_glyph(fnt, ch):
    try:
        return fnt.getmask(ch).getbbox() is not None
    except Exception:
        return False


# ============================================================
#  文字の整形
# ============================================================

def clean_text(s, limit=40):
    """絵文字など、フォントにない文字を取り除く"""
    s = str(s or "")
    s = re.sub(r"[\U00010000-\U0010FFFF☀-♠♢-♤♦-➿️‍]", "", s)
    return s.strip()[:limit]


def short_title(name):
    name = str(name or "")
    m = re.search(r"[「『](.+?)[」』]", name)
    if m:
        return m.group(1).strip()
    return re.split(r"[｜|]", name)[0].strip()


NO_LINE_START = "、。，．！？!?」』）)ー～〜ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ・♡"
NO_LINE_END = "「『（("
GOOD_BREAK_AFTER = "、。！？!? 　"
PARTICLES = "をにがはでとへもや"


def script_of(ch):
    o = ord(ch)
    if 0x30A0 <= o <= 0x30FF:
        return "kata"
    if 0x4E00 <= o <= 0x9FFF:
        return "kanji"
    if 0x3040 <= o <= 0x309F:
        return "hira"
    return "other"


def greedy_wrap(text, fnt, max_width, draw):
    lines, line = [], ""
    for ch in text:
        test = line + ch
        if draw.textlength(test, font=fnt) <= max_width or not line or ch in NO_LINE_START:
            line = test
        else:
            lines.append(line)
            line = ch
    if line:
        lines.append(line)
    return lines


def smart_wrap(text, fnt, max_width, draw, max_lines=2):
    """1行に収まればそのまま。2行なら読点・助詞の後ろで、左右が近い長さになる位置で改行"""
    text = text.replace("\n", "")
    if draw.textlength(text, font=fnt) <= max_width:
        return [text]
    if max_lines >= 2:
        best, best_score = None, None
        for i in range(1, len(text)):
            a, b = text[:i].rstrip(), text[i:].lstrip()
            if not a or not b or b[0] in NO_LINE_START or a[-1] in NO_LINE_END:
                continue
            wa, wb = draw.textlength(a, font=fnt), draw.textlength(b, font=fnt)
            if wa > max_width or wb > max_width:
                continue
            score = abs(wa - wb)
            if text[i - 1] in GOOD_BREAK_AFTER:
                score -= fnt.size * 4
            elif text[i - 1] in PARTICLES:
                score -= fnt.size * 2
            sa, sb = script_of(text[i - 1]), script_of(text[i])
            if sa == sb and sa in ("kata", "kanji"):
                score += fnt.size * 1.5
            if best_score is None or score < best_score:
                best, best_score = [a, b], score
        if best:
            return best
    return greedy_wrap(text, fnt, max_width, draw)


def fit_text(text, draw, max_width, sizes, bold=True, max_lines=2):
    for size in sizes:
        fnt = jp_font(size, bold)
        lines = smart_wrap(text, fnt, max_width, draw, max_lines)
        if len(lines) <= max_lines:
            return fnt, lines
    fnt = jp_font(sizes[-1], bold)
    return fnt, smart_wrap(text, fnt, max_width, draw, max_lines)[:max_lines]


# ============================================================
#  画像
# ============================================================

def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def load_image(src):
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def contain(img, w, h):
    scale = min(w / img.width, h / img.height)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def draw_flower(d, cx, cy, r, petal_color, center_color=WHITE):
    """5枚花びらの小さなお花（飾り）"""
    for k in range(5):
        a = -math.pi / 2 + k * 2 * math.pi / 5
        px, py = cx + math.cos(a) * r * 0.62, cy + math.sin(a) * r * 0.62
        d.ellipse((px - r * 0.5, py - r * 0.5, px + r * 0.5, py + r * 0.5), fill=petal_color)
    d.ellipse((cx - r * 0.32, cy - r * 0.32, cx + r * 0.32, cy + r * 0.32), fill=center_color)


def draw_sparkle(d, cx, cy, r, color):
    """4方向にのびるキラキラ"""
    pts = []
    for k in range(8):
        a = k * math.pi / 4
        rr = r if k % 2 == 0 else r * 0.28
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    d.polygon(pts, fill=color)


def make_background(seed):
    """クリーム→ピンクのグラデーション＋水玉＋ぼんやりした丸"""
    rng = random.Random(seed)
    y = np.linspace(0, 1, H)[:, None]
    top, bottom = np.array(CREAM, float), np.array(BLUSH, float)
    grad = (top * (1 - y) + bottom * y)[:, None, :].repeat(W, axis=1).reshape(H, W, 3)
    bg = Image.fromarray(grad.astype(np.uint8), "RGB").convert("RGBA")

    # ぼんやりした大きな丸（奥行き）
    blobs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blobs)
    for cx, cy, r, col in [(160, 420, 300, (*PINK, 90)), (960, 1250, 360, (*PINK, 80)), (900, 260, 180, (255, 236, 214, 120))]:
        bd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    blobs = blobs.filter(ImageFilter.GaussianBlur(70))
    bg.alpha_composite(blobs)

    # 小さな水玉
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    step = 72
    for j, yy in enumerate(range(20, H, step)):
        off = (step // 2) if j % 2 else 0
        for xx in range(20 + off, W, step):
            dd.ellipse((xx - 4, yy - 4, xx + 4, yy + 4), fill=(*PINK, 70))
    bg.alpha_composite(dots)

    # 写真まわりのキラキラとお花（ランダムに少しだけ）
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dc = ImageDraw.Draw(deco)
    for _ in range(5):
        cx, cy = rng.choice([rng.uniform(60, 200), rng.uniform(880, 1020)]), rng.uniform(380, 1150)
        draw_sparkle(dc, cx, cy, rng.uniform(14, 24), (*WHITE, 230))
    for _ in range(3):
        cx, cy = rng.choice([rng.uniform(70, 170), rng.uniform(900, 1010)]), rng.uniform(420, 1100)
        draw_flower(dc, cx, cy, rng.uniform(18, 26), (*PINK, 200), (255, 246, 214, 255))
    bg.alpha_composite(deco)
    return bg


def make_polaroid(img, max_w, max_h, tilt, seed):
    """白フチ＋下が広いポラロイド風、マスキングテープ付き、少し傾ける"""
    rng = random.Random(seed)
    photo = contain(img, max_w, max_h)
    side, top, bottom = 26, 26, 86
    pw, ph = photo.width + side * 2, photo.height + top + bottom
    card = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=14, fill=(255, 253, 250, 255))
    card.paste(photo, (side, top))
    # 下の余白に小さなハートとキラキラ
    hf = jp_font(30)
    if has_glyph(hf, "♡"):
        cd.text((pw - side - 46, ph - bottom + 24), "♡", font=hf, fill=(*DEEP_PINK, 255))
    draw_sparkle(cd, side + 28, ph - bottom / 2, 13, (*PINK, 255))

    # マスキングテープ（半透明のピンク、ストライプ）
    tw, th = 210, 58
    tape = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    td = ImageDraw.Draw(tape)
    td.rectangle((0, 0, tw, th), fill=(*PINK, 175))
    for x in range(-th, tw, 22):
        td.line((x, th, x + th, 0), fill=(255, 255, 255, 70), width=8)
    tape = tape.rotate(rng.uniform(-8, 8), resample=Image.BICUBIC, expand=True)

    pad = 60
    canvas = Image.new("RGBA", (pw + pad * 2, ph + pad * 2), (0, 0, 0, 0))
    canvas.alpha_composite(card, (pad, pad))
    canvas.alpha_composite(tape, (pad + pw // 2 - tape.width // 2, pad - tape.height // 2 + 6))
    canvas = canvas.rotate(tilt, resample=Image.BICUBIC, expand=True)

    # やわらかい影
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    alpha = canvas.getchannel("A").point(lambda a: 70 if a > 200 else 0)
    shadow.putalpha(alpha)
    shadow = Image.composite(Image.new("RGBA", canvas.size, (120, 70, 90, 255)), shadow, alpha)
    shadow.putalpha(alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    out = Image.new("RGBA", (canvas.width + 40, canvas.height + 40), (0, 0, 0, 0))
    out.alpha_composite(shadow, (24, 34))
    out.alpha_composite(canvas, (20, 20))
    return out


def make_base_frame(img, out_path, idx, is_last):
    bg = make_background(seed=idx * 11 + 3)
    pol = make_polaroid(img, PHOTO_MAX_W, PHOTO_MAX_H_LAST if is_last else PHOTO_MAX_H, TILTS[idx % 3], seed=idx)
    cy = PHOTO_CENTER_Y_LAST if is_last else PHOTO_CENTER_Y
    bg.alpha_composite(pol, (W // 2 - pol.width // 2, cy - pol.height // 2))
    bg.convert("RGB").save(out_path, quality=95)


# ============================================================
#  文字レイヤー
# ============================================================

def make_brand_layer(out_path, brand):
    """上部の店名（筆記体 ninomae ＋ 小さく ONLINE）。全編通して固定表示"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    parts = brand.split()
    main = parts[0] if parts else brand
    sub = " ".join(parts[1:]).upper()
    sf = script_font(92)
    mw = d.textlength(main, font=sf)
    # 白いふちどりで、どんな背景でも読みやすく
    d.text(((W - mw) / 2, BRAND_Y - 10), main, font=sf, fill=(*MAUVE, 255),
           stroke_width=6, stroke_fill=(255, 255, 255, 230))
    if sub:
        of = jp_font(26, bold=False)
        spaced = " ".join(sub)
        ow = d.textlength(spaced, font=of)
        y = BRAND_Y + 104
        d.text(((W - ow) / 2, y), spaced, font=of, fill=(*ROSE, 255),
               stroke_width=3, stroke_fill=(255, 255, 255, 200))
        d.line(((W - ow) / 2 - 70, y + 16, (W - ow) / 2 - 20, y + 16), fill=(*ROSE, 200), width=2)
        d.line(((W + ow) / 2 + 20, y + 16, (W + ow) / 2 + 70, y + 16), fill=(*ROSE, 200), width=2)
    layer.save(out_path)


def draw_lines(d, lines, fnt, y, color, gap):
    cx = (CARD_X1 + CARD_X2) / 2
    for ln in lines:
        w = d.textlength(ln, font=fnt)
        d.text((cx - w / 2, y), ln, font=fnt, fill=color)
        y += fnt.size + gap
    return y


def make_text_layer(out_path, headline, is_last=False, title="", price=""):
    """写真の下の、白いカードに丸文字。最後の1枚は商品名・価格・案内つき"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    blocks = []   # (種類, 行, フォント, 行間)
    if headline:
        sizes = [56, 52, 48, 44] if is_last else [66, 62, 58, 54, 50]
        hf, lines = fit_text(headline, d, TEXT_MAX_W, sizes)
        blocks.append(("head", lines, hf, 14))
    if is_last:
        if title:
            tf, tl = fit_text(title, d, TEXT_MAX_W, [42, 38, 34], max_lines=2)
            blocks.append(("title", tl, tf, 8))
        if price:
            blocks.append(("price", [price], jp_font(46), 0))
        cta_f = jp_font(34, bold=False)
        cta = "プロフィールのリンクから " + ("♡" if has_glyph(cta_f, "♡") else "")
        blocks.append(("cta", [cta.strip()], cta_f, 0))
    if not blocks:
        layer.save(out_path)
        return

    gap_between = 22
    pill_pad_y = 12
    heights = []
    for kind, lines, fnt, gap in blocks:
        h = len(lines) * (fnt.size + gap) - gap
        if kind == "price":
            h += pill_pad_y * 2
        heights.append(h)
    total = sum(heights) + gap_between * (len(blocks) - 1)
    pad_y = 46
    top = TEXT_TOP + pad_y
    if top + total + pad_y > SAFE_BOTTOM:
        top = max(SAFE_TOP, SAFE_BOTTOM - pad_y - total)
    card = (CARD_X1, top - pad_y, CARD_X2, top + total + pad_y)

    # カード：白（少し透ける）＋ピンクの細いふち＋影
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((card[0] + 6, card[1] + 12, card[2] + 6, card[3] + 12), radius=46, fill=(150, 90, 110, 60))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    layer.alpha_composite(sh)
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(card, radius=46, fill=(255, 255, 255, 238), outline=(*PINK, 255), width=4)
    d.rounded_rectangle((card[0] + 12, card[1] + 12, card[2] - 12, card[3] - 12), radius=36, outline=(*BLUSH, 255), width=2)
    # 角のお花
    draw_flower(d, card[0] + 14, card[1] + 10, 26, (*PINK, 255), (255, 240, 200, 255))
    draw_flower(d, card[2] - 14, card[3] - 10, 22, (*DEEP_PINK, 230), (255, 240, 200, 255))
    draw_sparkle(d, card[2] - 40, card[1] + 6, 16, (*DEEP_PINK, 255))

    y = top
    colors = {"head": (*TEXT, 255), "title": (*MAUVE, 255), "cta": (*TEXT, 230)}
    for (kind, lines, fnt, gap), h in zip(blocks, heights):
        off = int(fnt.size * 0.10)   # 和文フォントの上の余白の分だけ上げる
        if kind == "price":
            tw = d.textlength(lines[0], font=fnt)
            cx = (CARD_X1 + CARD_X2) / 2
            d.rounded_rectangle((cx - tw / 2 - 34, y, cx + tw / 2 + 34, y + h), radius=h // 2, fill=(*DEEP_PINK, 255))
            d.text((cx - tw / 2, y + pill_pad_y - off), lines[0], font=fnt, fill=(255, 255, 255, 255))
        else:
            draw_lines(d, lines, fnt, y - off, colors[kind], gap)
        y += h + gap_between
    layer.save(out_path)


# ============================================================
#  花びら（全編に重ねる動き）
# ============================================================

def make_petal_frames(folder, seed=7):
    """ふんわり舞い落ちる花びらを、半分の解像度で連番PNGにする（動画の上で拡大して使う）"""
    rng = random.Random(seed)
    sw, sh = W // 2, H // 2
    petals = []
    for _ in range(13):
        size = rng.uniform(10, 18)
        col = rng.choice([PINK, (244, 200, 210), (250, 214, 222), (232, 176, 196)])
        sprite = Image.new("RGBA", (int(size * 2.4), int(size * 2.4)), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sprite)
        c = sprite.width / 2
        sd.ellipse((c - size, c - size * 0.6, c + size, c + size * 0.6), fill=(*col, 190))
        sd.ellipse((c - size * 0.5, c - size * 0.25, c + size * 0.2, c + size * 0.15), fill=(255, 255, 255, 70))
        petals.append({
            "sprite": sprite,
            "x0": rng.uniform(0, sw),
            "y0": rng.uniform(-sh, sh),
            "vy": rng.uniform(22, 42),          # 1秒あたりの落下（半解像度px）
            "amp": rng.uniform(14, 34),
            "freq": rng.uniform(0.25, 0.55),
            "phase": rng.uniform(0, math.tau),
            "spin": rng.uniform(-60, 60),
            "rot0": rng.uniform(0, 360),
        })
    os.makedirs(folder, exist_ok=True)
    for f in range(N_FRAMES):
        t = f / FPS
        frame = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        for p in petals:
            y = (p["y0"] + p["vy"] * t) % (sh + 60) - 30
            x = p["x0"] + p["amp"] * math.sin(p["freq"] * math.tau * t + p["phase"])
            spr = p["sprite"].rotate(p["rot0"] + p["spin"] * t, resample=Image.BICUBIC)
            ix, iy = int(x % sw - spr.width / 2), int(y - spr.height / 2)
            if -spr.height < iy < sh:
                # paste は画面外にはみ出しても自動で切り取ってくれる
                frame.paste(spr, (ix, iy), spr)
        frame.save(os.path.join(folder, f"p{f:04d}.png"), compress_level=1)


# ============================================================
#  BGM（オルゴール風・オリジナル）
# ============================================================

def make_music_box(out_wav):
    sr = 48000
    n = int(TOTAL_SEC * sr)
    buf = np.zeros(n)
    note = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    # C → Am → F → G（各3.75秒）。オルゴールらしく高めの音でアルペジオ
    chords = [[60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62]]
    pattern = [0, 1, 2, 4, 3, 4, 2, 1, 0, 2, 1, 2]          # 和音の構成音をなぞる順番
    melody_top = [[79, 76, 77, 79], [76, 72, 74, 76], [77, 76, 74, 72], [74, 71, 72, 74]]
    seg = TOTAL_SEC / len(chords)
    step = seg / len(pattern)

    def pluck(t0, freq, amp, decay):
        i0 = int(t0 * sr)
        length = min(n - i0, int(2.2 * sr))
        if length <= 0:
            return
        t = np.arange(length) / sr
        env = np.exp(-t * decay) * np.minimum(1, t / 0.003)
        tone = (np.sin(2 * np.pi * freq * t)
                + 0.35 * np.sin(2 * np.pi * freq * 2.0 * t) * np.exp(-t * decay * 1.6)
                + 0.18 * np.sin(2 * np.pi * freq * 4.17 * t) * np.exp(-t * decay * 3.0))
        buf[i0:i0 + length] += amp * env * tone

    for ci, ch in enumerate(chords):
        base = ci * seg
        tones = [m + 12 for m in ch] + [m + 24 for m in ch]
        pluck(base, note(ch[0] - 12), 0.30, 1.6)                       # 低い音（ふんわり）
        for k, idx in enumerate(pattern):
            pluck(base + k * step, note(tones[idx]), 0.16, 3.2)        # アルペジオ
        for k, m in enumerate(melody_top[ci]):
            pluck(base + k * seg / 4, note(m + 12), 0.20, 2.6)          # 上のメロディ

    # 最後はやさしくフェードアウト
    fade = int(1.8 * sr)
    buf[-fade:] *= np.linspace(1, 0, fade)
    buf[: int(0.05 * sr)] *= np.linspace(0, 1, int(0.05 * sr))
    buf = buf / (np.max(np.abs(buf)) + 1e-9) * 0.6
    pcm = (buf * 32767).astype(np.int16)
    stereo = np.column_stack([pcm, pcm]).ravel()
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())


def make_music(out_path, workdir):
    tracks = sorted(glob.glob("music/*.mp3") + glob.glob("music/*.m4a") + glob.glob("music/*.wav"))
    if tracks:
        track = random.choice(tracks)
        log(f"BGM: {track}")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", track, "-t", str(TOTAL_SEC),
                        "-af", f"volume=0.8,afade=t=in:st=0:d=0.8,afade=t=out:st={TOTAL_SEC - 1.5}:d=1.5",
                        "-ar", "48000", "-ac", "2", out_path], check=True)
        return
    log("BGM: オルゴール風（自動生成）")
    raw = os.path.join(workdir, "musicbox.wav")
    make_music_box(raw)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                    "-af", "aecho=0.8:0.7:90|160:0.25|0.15,highpass=f=120,volume=0.9",
                    "-ar", "48000", "-ac", "2", out_path], check=True)


# ============================================================
#  組み立て
# ============================================================

def render(payload, workdir):
    job_id = re.sub(r"[^0-9A-Za-z_-]", "", str(payload.get("job_id") or "test"))
    brand = clean_text(payload.get("brand") or "ninomae ONLINE", 30)
    slides = [clean_text(s, 30) for s in (payload.get("slides") or [])][:3]
    while len(slides) < 3:
        slides.append("")
    title = clean_text(short_title(payload.get("title")), 40)
    price = clean_text(payload.get("price"), 30)

    sources = []
    for i, src in enumerate((payload.get("images") or [])[:3]):
        try:
            path = src if os.path.exists(src) else download(src, os.path.join(workdir, f"src{i}.jpg"))
            load_image(path)
            sources.append(path)
        except Exception as e:
            log(f"画像を取得できませんでした: {src} / {e}")
    if not sources:
        sys.exit("使える商品写真がありません")
    while len(sources) < 3:
        sources.append(sources[len(sources) % len(sources)])

    log("素材を作成中…")
    inputs, filters = [], []
    for i in range(3):
        base = os.path.join(workdir, f"base{i}.jpg")
        text = os.path.join(workdir, f"text{i}.png")
        make_base_frame(load_image(sources[i]), base, i, is_last=(i == 2))
        make_text_layer(text, slides[i], is_last=(i == 2), title=title, price=price)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(SLIDE_SEC), "-i", base,
                   "-loop", "1", "-framerate", str(FPS), "-t", str(SLIDE_SEC), "-i", text]
        z = f"{1 + ZOOM}-{ZOOM}*t/{SLIDE_SEC}" if i == 1 else f"1.0+{ZOOM}*t/{SLIDE_SEC}"
        filters.append(
            f"[{2 * i}:v]scale=w='trunc({W}*({z})/2)*2':h='trunc({H}*({z})/2)*2':eval=frame,"
            f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p[bz{i}];"
            f"[{2 * i + 1}:v]format=rgba,fade=t=in:st=0.35:d=0.55:alpha=1[tx{i}];"
            # 文字は少し下から、ふわっと浮き上がる
            f"[bz{i}][tx{i}]overlay=x=0:y='if(lt(t,0.35),36,if(lt(t,0.9),36*(1-(t-0.35)/0.55),0))':format=auto,"
            f"format=yuv420p[s{i}]"
        )

    brand_png = os.path.join(workdir, "brand.png")
    make_brand_layer(brand_png, brand)
    inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(TOTAL_SEC), "-i", brand_png]   # 6

    petal_dir = os.path.join(workdir, "petals")
    log("花びらを作成中…")
    make_petal_frames(petal_dir)
    inputs += ["-framerate", str(FPS), "-i", os.path.join(petal_dir, "p%04d.png")]           # 7

    off1 = SLIDE_SEC - FADE_SEC
    off2 = off1 + SLIDE_SEC - FADE_SEC
    filters.append(
        f"[s0][s1]xfade=transition=smoothleft:duration={FADE_SEC}:offset={off1:.2f}[x1];"
        f"[x1][s2]xfade=transition=circleopen:duration={FADE_SEC}:offset={off2:.2f}[x2];"
        f"[7:v]scale={W}:{H}:flags=bicubic,format=rgba[pt];"
        f"[x2][pt]overlay=0:0:format=auto[x3];"
        f"[6:v]format=rgba[br];"
        f"[x3][br]overlay=0:0:format=auto,"
        f"fade=t=in:st=0:d=0.4:color=white,fade=t=out:st={TOTAL_SEC - 0.5}:d=0.5:color=white,format=yuv420p[v]"
    )

    music = os.path.join(workdir, "music.m4a")
    make_music(music, workdir)
    inputs += ["-i", music]                                                                    # 8

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{job_id}.mp4")
    log("動画を書き出し中…")
    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + inputs +
           ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "8:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-t", str(TOTAL_SEC), "-movflags", "+faststart", out])
    subprocess.run(cmd, check=True)
    log(f"完成: {out}（{os.path.getsize(out) / 1024 / 1024:.1f} MB）")
    return out


def main():
    raw = os.environ.get("PAYLOAD") or (open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else "")
    if not raw or raw == "null":
        sys.exit("PAYLOAD がありません")
    payload = json.loads(raw)
    if isinstance(payload, dict) and isinstance(payload.get("payload"), str):
        payload = json.loads(payload["payload"])
    with tempfile.TemporaryDirectory() as tmp:
        render(payload, tmp)


if __name__ == "__main__":
    main()
