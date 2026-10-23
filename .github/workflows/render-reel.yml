#!/usr/bin/env python3
"""
ninomae ONLINE リール動画ジェネレーター（バズり型・TikTok／Instagram共通）

構成（14秒・縦長1080x1920・30fps、最後から最初へ自然につながるループ）
  0.0〜2.5秒  つかみ：写真がグッと寄る＋大きな一言（例「枯れない花って知ってた？」）
  2.5〜10.5秒 2秒ごとにテンポよく切り替え（全画面の寄りカット）＋短い一言
  10.5〜14秒  商品名・価格・「プロフィールのリンクから」＋コメントを誘う問いかけ
  BGM：なし（曲はTikTok・Instagramのアプリ内で付ける）。無音の音声トラックだけ入れる
  ※切り替えは120BPM（2秒ごと）なので、流行の曲の拍に合わせやすい

入力（環境変数 PAYLOAD に JSON）:
  {
    "job_id": "20261026-1930-161509504",
    "images": ["https://...jpg", ...],                 # 商品写真（1〜6枚）
    "slides": ["つかみ", "一言1", "一言2", "一言3", "一言4"],
    "question": "どの色が好き？コメントで教えてね",
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

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    import numpy as np
except ImportError:  # GitHub Actions などで未インストールなら自動で入れる
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "numpy"], check=True)
    import numpy as np

W, H = 1080, 1920
FPS = 30
BPM = 120
BEAT = 60 / BPM                     # 0.5秒
HOOK_SEC = 2.5                      # つかみ
MID_SEC = 2.0                       # 途中のカット（4つ）
END_SEC = 3.5                       # 最後（商品名・価格・問いかけ）
N_MID = 4
TOTAL_SEC = HOOK_SEC + MID_SEC * N_MID + END_SEC   # 14.0秒
LOOP_ZOOM = 0.10
# BGM："none"＝音なし（曲はTikTok・Instagramのアプリで付ける）／"musicbox"＝オルゴール風の自作曲
# ※音なしでも、SNSが受け付けやすいように「無音の音声トラック」は入れておく
BGM_MODE = "none"                    # 最後のカットの終わり＝最初のカットの始まりの寄り具合（ループ用）
OUT_DIR = "out"

# ---- 色（ninomae ONLINE のテーマに合わせたピンク系） ----
CREAM = (252, 246, 241)
BLUSH = (246, 226, 228)
PINK = (236, 184, 196)
DEEP_PINK = (214, 112, 146)
MAUVE = (153, 102, 145)
TEXT = (112, 82, 98)
WHITE = (255, 255, 255)

# ---- Instagram／TikTokのボタン・キャプションに隠れない範囲 ----
SAFE_TOP, SAFE_BOTTOM = 230, H - 430
SAFE_RIGHT = W - 140
HOOK_CENTER_Y = 470                 # つかみの文字（上のほう）
MID_CENTER_Y = 1330                 # 途中の一言（下のほう）
TEXT_MAX_W = 860

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIRS = [os.path.join(HERE, "..", "fonts"), "fonts"]
NOTO_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
]
# Google Fonts（OFLライセンス・商用利用可）。初回に自動でダウンロード
FONT_URLS = {
    "ZenMaruGothic-Black.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/zenmarugothic/ZenMaruGothic-Black.ttf",
    "ZenMaruGothic-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/zenmarugothic/ZenMaruGothic-Bold.ttf",
    "DancingScript-VF.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/dancingscript/DancingScript%5Bwght%5D.ttf",
}


def log(msg):
    print(msg, flush=True)


# ============================================================
#  フォント
# ============================================================

def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def _find(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def ensure_fonts():
    folder = FONT_DIRS[0]
    os.makedirs(folder, exist_ok=True)
    for name, url in FONT_URLS.items():
        if _find(name):
            continue
        try:
            download(url, os.path.join(folder, name))
            log(f"フォントを取得: {name}")
        except Exception as e:
            log(f"フォントを取得できませんでした（代わりのフォントを使います）: {name} / {e}")


_font_cache = {}


def jp_font(size, weight="black"):
    """丸文字（Zen Maru Gothic）。black=極太（字幕用）、bold=太字"""
    key = ("jp", size, weight)
    if key not in _font_cache:
        name = "ZenMaruGothic-Black.ttf" if weight == "black" else "ZenMaruGothic-Bold.ttf"
        path = _find(name) or _find("ZenMaruGothic-Bold.ttf")
        if path:
            _font_cache[key] = ImageFont.truetype(path, size)
        else:
            noto = next((p for p in NOTO_CANDIDATES if os.path.exists(p)), None)
            if not noto:
                sys.exit("日本語フォントが見つかりません")
            _font_cache[key] = ImageFont.truetype(noto, size, index=0)
    return _font_cache[key]


def script_font(size):
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
            _font_cache[key] = jp_font(size, "bold")
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


def break_penalty(text, i, size):
    """text の i 文字目の前で改行したときの「読みにくさ」（小さいほど自然）"""
    a, b = text[i - 1], text[i]
    sa, sb = script_of(a), script_of(b)
    p = 0.0
    if a in GOOD_BREAK_AFTER:
        p -= 4                                   # 読点・句点のあと
    elif a in PARTICLES:
        p -= 2.5                                 # 助詞のあと（文節の切れ目）
    if sa == sb and sa in ("kata", "kanji"):
        p += 1.5                                 # 漢字・カタカナの語の途中
    if sa == "hira" and sb in ("kanji", "kata"):
        p += 3 if a in "おご" else -1.5           # 「お｜礼」はダメ、「って｜知ってた」は良い
    if b in "おご" and i + 1 < len(text) and script_of(text[i + 1]) == "kanji" and sa == "hira":
        p -= 2.5                                 # 「自分への｜ご褒美」
    if sa in ("kanji", "kata") and sb == "hira":
        p += 2                                   # 「花束｜が」のような送り仮名・助詞の前
    if sa == "hira" and sb == "hira" and a not in PARTICLES:
        p += 1                                   # 「開け｜た」などひらがなの途中
    if b in PARTICLES + "のね" and sa in ("hira", "kanji", "kata"):
        p += 3                                   # 行の頭に助詞（「の」「も」など）が来ないように
    if a in "っゃゅょぁぃぅぇぉッャュョ":
        p += 4                                   # 小さい「っ」などの直後
    return p


def smart_wrap(text, fnt, max_width, draw, max_lines=2):
    """1行に収まればそのまま。2行なら自然な区切りで、左右が近い長さになる位置で改行。
    戻り値：(行のリスト, 区切りの読みにくさ)"""
    text = text.replace("\n", "")
    if draw.textlength(text, font=fnt) <= max_width:
        return [text], -99
    if max_lines >= 2:
        best, best_score, best_pen = None, None, None
        for i in range(1, len(text)):
            a, b = text[:i].rstrip(), text[i:].lstrip()
            if not a or not b or b[0] in NO_LINE_START or a[-1] in NO_LINE_END:
                continue
            wa, wb = draw.textlength(a, font=fnt), draw.textlength(b, font=fnt)
            if wa > max_width or wb > max_width:
                continue
            pen = break_penalty(text, i, fnt.size)
            score = abs(wa - wb) / fnt.size + pen * 1.8   # 長さのバランスより、区切りの自然さを重視
            if best_score is None or score < best_score:
                best, best_score, best_pen = [a, b], score, pen
        if best:
            return best, best_pen
    return greedy_wrap(text, fnt, max_width, draw), 9


def fit_text(text, draw, max_width, sizes, weight="black", max_lines=2):
    """大きい文字から順に試し、自然な区切りで収まる最大サイズを選ぶ"""
    fallback = None
    for size in sizes:
        fnt = jp_font(size, weight)
        lines, pen = smart_wrap(text, fnt, max_width, draw, max_lines)
        if len(lines) > max_lines:
            continue
        if pen <= 0:
            return fnt, lines
        if fallback is None or pen < fallback[2]:
            fallback = (fnt, lines, pen)
    if fallback:
        return fallback[0], fallback[1]
    fnt = jp_font(sizes[-1], weight)
    return fnt, smart_wrap(text, fnt, max_width, draw, max_lines)[0][:max_lines]


# ============================================================
#  写真のコマ
# ============================================================

def load_image(src):
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def cover(img, w, h, fx=0.5, fy=0.5, extra=1.0):
    """枠いっぱいに広げて切り取る。fx,fy は残したい位置（0〜1）、extra は寄りの倍率"""
    scale = max(w / img.width, h / img.height) * extra
    rw, rh = max(w, round(img.width * scale)), max(h, round(img.height * scale))
    resized = img.resize((rw, rh), Image.LANCZOS)
    left = int(min(max(fx * rw - w / 2, 0), rw - w))
    top = int(min(max(fy * rh - h / 2, 0), rh - h))
    return resized.crop((left, top, left + w, top + h))


def pastel_blur_bg(img):
    """写真をぼかして明るく・ピンク寄りにした背景"""
    bg = cover(img, W, H).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), CREAM), 0.45)
    return Image.blend(bg, Image.new("RGB", (W, H), BLUSH), 0.2)


def frame_fit(img, out_path, photo_center_y=980):
    """写真の全体が見えるよう横幅いっぱいに置き、上下はぼかし背景（最初と最後のカット）"""
    bg = pastel_blur_bg(img).convert("RGBA")
    scale = W / img.width
    if img.height * scale > 1300:                     # 縦長すぎる写真は少し縮める
        scale = 1300 / img.height
    photo = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    y = photo_center_y - photo.height // 2
    mask = Image.new("L", photo.size, 255)            # 上下のふちをなじませる
    md = ImageDraw.Draw(mask)
    fade = 50
    for i in range(fade):
        a = int(255 * i / fade)
        md.line((0, i, photo.width, i), fill=a)
        md.line((0, photo.height - 1 - i, photo.width, photo.height - 1 - i), fill=a)
    bg.paste(photo, ((W - photo.width) // 2, y), mask)
    bg.convert("RGB").save(out_path, quality=95)


def frame_cover(img, out_path, fx, fy, extra):
    """全画面の寄りカット"""
    cover(img, W, H, fx, fy, extra).save(out_path, quality=95)


# ============================================================
#  文字レイヤー
# ============================================================

def outlined_text(d, xy, text, fnt, fill, stroke, stroke_w):
    """太いふちどり＋うしろに淡い影（TikTokの字幕風）"""
    x, y = xy
    d.text((x + 4, y + 7), text, font=fnt, fill=(120, 50, 80, 90), stroke_width=stroke_w, stroke_fill=(120, 50, 80, 90))
    d.text((x, y), text, font=fnt, fill=fill, stroke_width=stroke_w, stroke_fill=stroke)


def draw_sparkle(d, cx, cy, r, color):
    pts = []
    for k in range(8):
        a = k * math.pi / 4
        rr = r if k % 2 == 0 else r * 0.28
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    d.polygon(pts, fill=color)


def text_block(d, lines, fnt, center_y, fill, stroke, stroke_w, gap=10):
    total = len(lines) * fnt.size + (len(lines) - 1) * gap
    y = center_y - total / 2 - fnt.size * 0.1
    cx = SAFE_RIGHT / 2 + 30                       # 右のボタンを避けて、少し左寄りの中央
    boxes = []
    for ln in lines:
        w = d.textlength(ln, font=fnt)
        x = cx - w / 2
        outlined_text(d, (x, y), ln, fnt, fill, stroke, stroke_w)
        boxes.append((x, y, x + w, y + fnt.size))
        y += fnt.size + gap
    return boxes


def make_hook_layer(out_path, text):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fnt, lines = fit_text(text, d, TEXT_MAX_W, [104, 96, 88, 80, 72], "black")
    boxes = text_block(d, lines, fnt, HOOK_CENTER_Y, (255, 255, 255, 255), (*DEEP_PINK, 255), 14, gap=14)
    x1, x2 = min(b[0] for b in boxes), max(b[2] for b in boxes)
    y1, y2 = min(b[1] for b in boxes), max(b[3] for b in boxes)
    draw_sparkle(d, x1 - 34, y1 + 4, 26, (255, 236, 150, 255))
    draw_sparkle(d, x2 + 30, y2 - 4, 22, (255, 255, 255, 255))
    draw_sparkle(d, x2 + 8, y1 - 24, 14, (255, 236, 150, 255))
    layer.save(out_path)


def make_caption_layer(out_path, text, idx):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if text:
        fnt, lines = fit_text(text, d, TEXT_MAX_W, [86, 80, 74, 68, 62], "black")
        # 白文字＋ピンクのふち と ピンク文字＋白のふち を交互に（単調にならないように）
        if idx % 2 == 0:
            text_block(d, lines, fnt, MID_CENTER_Y, (255, 255, 255, 255), (*DEEP_PINK, 255), 12)
        else:
            text_block(d, lines, fnt, MID_CENTER_Y, (*DEEP_PINK, 255), (255, 255, 255, 255), 12)
    layer.save(out_path)


def make_end_layer(out_path, question, title, price, brand):
    """最後：上に問いかけの吹き出し、下に店名・商品名・価格・案内のカード"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = SAFE_RIGHT / 2 + 30

    if question:
        qf, ql = fit_text(question, d, 760, [62, 56, 52, 48], "black")
        lh = qf.size + 10
        bh = len(ql) * lh - 10 + 60
        bw = max(d.textlength(t, font=qf) for t in ql) + 90
        top = HOOK_CENTER_Y - bh / 2
        box = (cx - bw / 2, top, cx + bw / 2, top + bh)
        d.rounded_rectangle((box[0] + 4, box[1] + 8, box[2] + 4, box[3] + 8), radius=40, fill=(120, 50, 80, 70))
        d.rounded_rectangle(box, radius=40, fill=(255, 255, 255, 250), outline=(*DEEP_PINK, 255), width=6)
        tail_x = cx - bw / 4
        d.polygon([(tail_x - 26, box[3] - 3), (tail_x + 26, box[3] - 3), (tail_x - 6, box[3] + 40)], fill=(255, 255, 255, 250))
        d.line([(tail_x - 26, box[3] - 1), (tail_x - 6, box[3] + 40), (tail_x + 26, box[3] - 1)], fill=(*DEEP_PINK, 255), width=6)
        y = top + 30 - qf.size * 0.1
        for t in ql:
            w = d.textlength(t, font=qf)
            d.text((cx - w / 2, y), t, font=qf, fill=(*TEXT, 255))
            y += lh

    tf, tl = fit_text(title, d, 760, [58, 52, 48, 44], "black") if title else (None, [])
    pf = jp_font(56, "black")
    cf = jp_font(40, "bold")
    cta = "プロフィールのリンクから" + (" ♡" if has_glyph(cf, "♡") else "")
    bf = script_font(58)
    name = brand.split()[0] if brand else "ninomae"
    inner = bf.size + 6 + (len(tl) * (tf.size + 8) if tl else 0) + (pf.size + 20 + 28 if price else 0) + cf.size + 6
    card_top = max(1060, SAFE_BOTTOM - inner - 60)
    card = (90, card_top, SAFE_RIGHT - 20, card_top + inner + 60)
    d.rounded_rectangle((card[0] + 6, card[1] + 12, card[2] + 6, card[3] + 12), radius=48, fill=(120, 50, 80, 60))
    d.rounded_rectangle(card, radius=48, fill=(255, 255, 255, 242), outline=(*PINK, 255), width=5)
    ccx = (card[0] + card[2]) / 2
    y = card[1] + 26
    w = d.textlength(name, font=bf)
    d.text((ccx - w / 2, y - 8), name, font=bf, fill=(*MAUVE, 255))
    y += bf.size + 6
    for t in tl:
        w = d.textlength(t, font=tf)
        d.text((ccx - w / 2, y - tf.size * 0.1), t, font=tf, fill=(*TEXT, 255))
        y += tf.size + 8
    if price:
        y += 10
        w = d.textlength(price, font=pf)
        ph = pf.size + 20
        d.rounded_rectangle((ccx - w / 2 - 40, y, ccx + w / 2 + 40, y + ph), radius=ph // 2, fill=(*DEEP_PINK, 255))
        d.text((ccx - w / 2, y + 10 - pf.size * 0.1), price, font=pf, fill=(255, 255, 255, 255))
        y += ph + 18
    w = d.textlength(cta, font=cf)
    d.text((ccx - w / 2, y - cf.size * 0.1), cta, font=cf, fill=(*TEXT, 255))
    draw_sparkle(d, card[0] + 30, card[1] + 26, 20, (*DEEP_PINK, 255))
    draw_sparkle(d, card[2] - 32, card[3] - 30, 16, (*PINK, 255))
    layer.save(out_path)


# ============================================================
#  BGM（120BPM・オルゴール風・オリジナル）
# ============================================================

def make_music_box(out_wav, cut_times):
    sr = 48000
    n = int(TOTAL_SEC * sr)
    buf = np.zeros(n)
    note = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    bar = BEAT * 4                                     # 2秒
    # C → G → Am → F → C → G → C（7小節＝14秒）。最後はCで終わり、頭のCにつながる
    chords = [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60], [60, 64, 67], [55, 59, 62], [60, 64, 67]]
    melody = [[84, 83, 79, 76], [79, 81, 83, 86], [84, 83, 81, 76], [77, 76, 74, 72],
              [84, 86, 88, 84], [86, 83, 79, 83], [84, 79, 76, 72]]

    def pluck(t0, freq, amp, decay, length=1.8):
        i0 = int(t0 * sr)
        ln = min(n - i0, int(length * sr))
        if ln <= 0:
            return
        t = np.arange(ln) / sr
        env = np.exp(-t * decay) * np.minimum(1, t / 0.002)
        tone = (np.sin(2 * np.pi * freq * t)
                + 0.35 * np.sin(2 * np.pi * freq * 2.0 * t) * np.exp(-t * decay * 1.6)
                + 0.15 * np.sin(2 * np.pi * freq * 4.17 * t) * np.exp(-t * decay * 3.0))
        buf[i0:i0 + ln] += amp * env * tone

    def kick(t0, amp):
        i0 = int(t0 * sr)
        ln = min(n - i0, int(0.25 * sr))
        if ln <= 0:
            return
        t = np.arange(ln) / sr
        f = 110 * np.exp(-t * 18) + 45
        buf[i0:i0 + ln] += amp * np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 14)

    for b, ch in enumerate(chords):
        t0 = b * bar
        tones = [m + 12 for m in ch] + [m + 24 for m in ch]
        pluck(t0, note(ch[0] - 12), 0.32, 1.4, 2.2)                     # 低音
        for k in range(8):                                               # 8分音符のアルペジオ
            pluck(t0 + k * BEAT / 2, note(tones[[0, 1, 2, 4, 3, 4, 2, 1][k]]), 0.13, 4.0)
        for k, m in enumerate(melody[b]):                                # 4分音符のメロディ
            pluck(t0 + k * BEAT, note(m), 0.20, 3.0)
        for k in range(4):                                               # 軽いリズム
            kick(t0 + k * BEAT, 0.28 if k % 2 == 0 else 0.18)
    for ct in cut_times:                                                 # 切り替えの瞬間に「キラッ」
        pluck(ct, note(96), 0.16, 6.0, 0.8)
        pluck(ct, note(103), 0.10, 7.0, 0.8)

    buf[: int(0.01 * sr)] *= np.linspace(0, 1, int(0.01 * sr))
    buf[-int(0.03 * sr):] *= np.linspace(1, 0, int(0.03 * sr))       # ループで「プツッ」とならないように
    buf = buf / (np.max(np.abs(buf)) + 1e-9) * 0.7
    pcm = (buf * 32767).astype(np.int16)
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.column_stack([pcm, pcm]).ravel().tobytes())


def make_music(out_path, workdir, cut_times):
    if BGM_MODE == "none":
        log("BGM: なし（無音）")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                        "-t", f"{TOTAL_SEC:.3f}", "-c:a", "aac", "-b:a", "64k", out_path], check=True)
        return
    tracks = sorted(glob.glob("music/*.mp3") + glob.glob("music/*.m4a") + glob.glob("music/*.wav"))
    if tracks:
        track = random.choice(tracks)
        log(f"BGM: {track}")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", track, "-t", str(TOTAL_SEC),
                        "-af", f"volume=0.8,afade=t=out:st={TOTAL_SEC - 0.6}:d=0.6",
                        "-ar", "48000", "-ac", "2", out_path], check=True)
        return
    log("BGM: 120BPMのオルゴール風（自動生成）")
    raw = os.path.join(workdir, "musicbox.wav")
    make_music_box(raw, cut_times)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                    "-af", "aecho=0.8:0.6:75:0.18,highpass=f=40,volume=0.95",
                    "-ar", "48000", "-ac", "2", out_path], check=True)


# ============================================================
#  組み立て
# ============================================================

def render(payload, workdir):
    ensure_fonts()
    job_id = re.sub(r"[^0-9A-Za-z_-]", "", str(payload.get("job_id") or "test"))
    brand = clean_text(payload.get("brand") or "ninomae ONLINE", 30)
    slides = [clean_text(s, 32) for s in (payload.get("slides") or [])]
    hook = slides[0] if slides and slides[0] else "枯れない花って知ってた？"
    mids = (slides[1:] + [""] * N_MID)[:N_MID]
    question = clean_text(payload.get("question"), 32)
    title = clean_text(short_title(payload.get("title")), 40)
    price = clean_text(payload.get("price"), 30)

    sources = []
    for i, src in enumerate((payload.get("images") or [])[:6]):
        try:
            path = src if os.path.exists(src) else download(src, os.path.join(workdir, f"src{i}.jpg"))
            load_image(path)
            sources.append(path)
        except Exception as e:
            log(f"画像を取得できませんでした: {src} / {e}")
    if not sources:
        sys.exit("使える商品写真がありません")
    imgs = [load_image(p) for p in sources]

    # 途中の4カット：写真が足りないときは、寄る位置と倍率を変えて別カットに見せる
    focus = [(0.5, 0.45, 1.0), (0.35, 0.4, 1.35), (0.65, 0.55, 1.35), (0.5, 0.35, 1.6), (0.5, 0.6, 1.25)]
    mid_frames = []
    for k in range(N_MID):
        img = imgs[(k + 1) % len(imgs)]
        fx, fy, ex = focus[(k + (0 if len(imgs) > 2 else 1)) % len(focus)]
        mid_frames.append((img, fx, fy, ex))

    log("素材を作成中…")
    segs = []   # (背景, 文字, 長さ, ズームの式, 文字の出し方)
    f0, t0 = os.path.join(workdir, "f_hook.jpg"), os.path.join(workdir, "t_hook.png")
    frame_fit(imgs[0], f0)
    make_hook_layer(t0, hook)
    # 最初：寄った状態（＝最後のカットの終わりと同じ倍率）から、グッと引いて止まる
    segs.append((f0, t0, HOOK_SEC, f"1.0+{LOOP_ZOOM}*pow(max(0,1-t/0.35),2)+0.02*t/{HOOK_SEC}", "now"))
    for k, (img, fx, fy, ex) in enumerate(mid_frames):
        fp, tp = os.path.join(workdir, f"f_mid{k}.jpg"), os.path.join(workdir, f"t_mid{k}.png")
        frame_cover(img, fp, fx, fy, ex)
        make_caption_layer(tp, mids[k], k)
        segs.append((fp, tp, MID_SEC, f"1.0+0.07*pow(max(0,1-t/0.22),2)+0.05*t/{MID_SEC}", "pop"))
    fe, te = os.path.join(workdir, "f_end.jpg"), os.path.join(workdir, "t_end.png")
    frame_fit(imgs[0], fe)
    make_end_layer(te, question, title, price, brand)
    # 最後：ゆっくり寄っていき、最初のカットの始まりと同じ倍率で終わる＝自然にループ
    segs.append((fe, te, END_SEC, f"1.0+{LOOP_ZOOM}*t/{END_SEC}", "pop"))

    inputs, filters, labels = [], [], []
    for i, (bgp, txp, dur, z, mode) in enumerate(segs):
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", bgp,
                   "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", txp]
        a, b = 2 * i, 2 * i + 1
        if mode == "now":
            txt = f"[{b}:v]format=rgba[tx{i}];[bz{i}][tx{i}]overlay=0:0:format=auto"
        else:
            # ポンッと出る：少し下から一瞬で上がり、同時に表示
            txt = (f"[{b}:v]format=rgba,fade=t=in:st=0.05:d=0.12:alpha=1[tx{i}];"
                   f"[bz{i}][tx{i}]overlay=x=0:y='if(lt(t,0.05),40,if(lt(t,0.2),40*(1-(t-0.05)/0.15),0))':format=auto")
        filters.append(
            f"[{a}:v]scale=w='trunc({W}*({z})/2)*2':h='trunc({H}*({z})/2)*2':eval=frame,"
            f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p[bz{i}];"
            f"{txt},format=yuv420p,setsar=1[s{i}]"
        )
        labels.append(f"[s{i}]")
    filters.append("".join(labels) + f"concat=n={len(segs)}:v=1:a=0[v]")

    cut_times = [HOOK_SEC + MID_SEC * k for k in range(N_MID + 1)]
    music = os.path.join(workdir, "music.m4a")
    make_music(music, workdir, cut_times)
    inputs += ["-i", music]
    audio_idx = len(segs) * 2

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{job_id}.mp4")
    log("動画を書き出し中…")
    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + inputs +
           ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", f"{audio_idx}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-g", str(FPS),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-t", f"{TOTAL_SEC:.3f}", "-movflags", "+faststart", out])
    subprocess.run(cmd, check=True)
    log(f"完成: {out}（{os.path.getsize(out) / 1024 / 1024:.1f} MB・{TOTAL_SEC:.0f}秒）")
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
