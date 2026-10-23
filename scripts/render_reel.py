#!/usr/bin/env python3
"""
ninomae ONLINE リール動画ジェネレーター

商品写真（最大3枚）と短い文字から、Instagramリール用の
15秒・縦長（1080x1920）・30fps の MP4 を作ります。

入力（環境変数 PAYLOAD に JSON）:
  {
    "job_id": "20261026-1930-161509504",
    "images": ["https://...jpg", ...],      # 商品写真のURL（1〜3枚以上）
    "slides": ["見出し1", "見出し2", "見出し3"],  # 各スライドの大きな文字
    "title": "プティットボックス イエロー",       # 最後のスライドに出す商品名
    "price": "¥7,150（税込）",
    "brand": "ninomae ONLINE"
  }

出力: out/<job_id>.mp4
"""
import glob
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920
FPS = 30
SLIDE_SEC = 5.4          # 1枚あたりの長さ
FADE_SEC = 0.6           # 切り替えの長さ（3枚で 5.4*3 - 0.6*2 = 15.0 秒）
TOTAL_SEC = 15.0
OUT_DIR = "out"

# Instagramのリール画面では、上部（約220px）・下部（約420px）・右端（約120px）が
# ボタンやキャプションで隠れるため、大事な要素はその内側に配置する
SAFE_TOP, SAFE_BOTTOM = 220, H - 420
BRAND_Y = 228
ZOOM = 0.05                                    # ゆっくりズームする量（5%）
PHOTO_MAX_W, PHOTO_MAX_H = 880, 760            # 1・2枚目の写真の最大サイズ
PHOTO_CENTER_Y = 740
PHOTO_MAX_H_LAST, PHOTO_CENTER_Y_LAST = 640, 680   # 最後の1枚は文字が多いので写真を少し小さく
TEXT_TOP, TEXT_BOTTOM = 1150, SAFE_BOTTOM      # 文字帯を置ける範囲
TEXT_BOX_X1, TEXT_BOX_X2 = 80, W - 120         # 右側はいいね等のボタンを避ける
TEXT_MAX_W = TEXT_BOX_X2 - TEXT_BOX_X1 - 70

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
]


def log(msg):
    print(msg, flush=True)


def find_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    try:
        path = subprocess.check_output(["fc-match", "-f", "%{file}", "Noto Sans CJK JP:bold"], text=True).strip()
        if path:
            return path
    except Exception:
        pass
    sys.exit("日本語フォントが見つかりません（fonts-noto-cjk をインストールしてください）")


FONT_PATH = find_font()


def font(size):
    # .ttc の 0 番目が日本語（JP）
    return ImageFont.truetype(FONT_PATH, size, index=0)


def clean_text(s, limit=40):
    """絵文字など、フォントにない文字を取り除く（表示が□になるのを防ぐ）"""
    s = str(s or "")
    s = re.sub(r"[\U00010000-\U0010FFFF☀-➿️‍]", "", s)
    return s.strip()[:limit]


def short_title(name):
    """「プリザーブドフラワーフレーム「ガーデン ピンク」｜結婚祝い…」→「ガーデン ピンク」のように短くする"""
    name = str(name or "")
    m = re.search(r"[「『](.+?)[」』]", name)
    if m:
        return m.group(1).strip()
    return re.split(r"[｜|]", name)[0].strip()


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def load_image(src):
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def cover(img, w, h):
    """枠いっぱいに広げて、はみ出た部分を切る"""
    scale = max(w / img.width, h / img.height)
    resized = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def contain(img, w, h):
    """枠の中に全体が収まるように縮小する"""
    scale = min(w / img.width, h / img.height)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def make_base_frame(img, out_path, is_last=False):
    """背景：同じ写真をぼかして暗く ／ 手前：商品写真の全体を角丸で中央に"""
    bg = cover(img, W, H).filter(ImageFilter.GaussianBlur(45))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (20, 14, 18)), 0.45)

    # 写真は「上の見出し」と「下の文字帯」の間（Instagramの画面表示に隠れない範囲）に収める
    fg = contain(img, PHOTO_MAX_W, PHOTO_MAX_H_LAST if is_last else PHOTO_MAX_H)
    shadow = Image.new("RGBA", (fg.width + 80, fg.height + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((40, 40, fg.width + 40, fg.height + 40), radius=36, fill=(0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))

    cx, cy = W // 2, (PHOTO_CENTER_Y_LAST if is_last else PHOTO_CENTER_Y)
    x, y = cx - fg.width // 2, cy - fg.height // 2
    canvas = bg.convert("RGBA")
    canvas.alpha_composite(shadow, (x - 40, y - 30))
    canvas.paste(fg, (x, y), rounded_mask(fg.size, 36))
    canvas.convert("RGB").save(out_path, quality=95)


NO_LINE_START = "、。，．！？!?」』）)ー～〜ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ・"
NO_LINE_END = "「『（("
GOOD_BREAK_AFTER = "、。！？!? 　"
PARTICLES = "をにがはでとへもや"


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
    """1行に収まればそのまま。2行になるときは、読点や助詞の後ろで、左右の長さが近くなる位置で改行する"""
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
            # カタカナ・漢字・ひらがなの語の途中で切るのを少し避ける
            if is_same_script(text[i - 1], text[i]):
                score += fnt.size * 1.5
            if best_score is None or score < best_score:
                best, best_score = [a, b], score
        if best:
            return best
    return greedy_wrap(text, fnt, max_width, draw)


def script_of(ch):
    o = ord(ch)
    if 0x30A0 <= o <= 0x30FF:
        return "kata"
    if 0x4E00 <= o <= 0x9FFF:
        return "kanji"
    if 0x3040 <= o <= 0x309F:
        return "hira"
    return "other"


def is_same_script(a, b):
    sa, sb = script_of(a), script_of(b)
    return sa == sb and sa in ("kata", "kanji")


def fit_text(text, draw, max_width, sizes, max_lines=2):
    """文字が max_lines 行に収まるまで、文字サイズを段階的に小さくする"""
    for size in sizes:
        fnt = font(size)
        lines = smart_wrap(text, fnt, max_width, draw, max_lines)
        if len(lines) <= max_lines:
            return fnt, lines
    fnt = font(sizes[-1])
    return fnt, smart_wrap(text, fnt, max_width, draw, max_lines)[:max_lines]


def draw_text_block(draw, lines, fnt, y, fill, line_gap):
    cx = (TEXT_BOX_X1 + TEXT_BOX_X2) / 2
    for ln in lines:
        w = draw.textlength(ln, font=fnt)
        draw.text((cx - w / 2, y), ln, font=fnt, fill=fill)
        y += fnt.size + line_gap
    return y


def make_text_layer(out_path, headline, brand, is_last=False, title="", price=""):
    """文字だけの透明レイヤー（写真のズームとは別に、文字は動かさない）"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # 上部のブランド名
    bf = font(40)
    bw = d.textlength(brand, font=bf)
    d.text(((W - bw) / 2, BRAND_Y), brand, font=bf, fill=(255, 255, 255, 235))
    d.line(((W - bw) / 2, BRAND_Y + 60, (W + bw) / 2, BRAND_Y + 60), fill=(255, 255, 255, 160), width=2)

    # 写真の下の見出し（半透明の帯の上に白文字）
    blocks = []
    if headline:
        sizes = [58, 52, 48] if is_last else [74, 68, 62, 56, 50]
        hf, head_lines = fit_text(headline, d, TEXT_MAX_W, sizes, max_lines=2)
        blocks.append(("head", head_lines, hf, 14))
    if is_last:
        if title:
            tf, title_lines = fit_text(title, d, TEXT_MAX_W, [46, 42, 38], max_lines=2)
            blocks.append(("title", title_lines, tf, 0))
        if price:
            blocks.append(("price", [price], font(50), 0))
        blocks.append(("cta", ["▶ プロフィールのリンクから"], font(36), 0))

    if not blocks:
        layer.save(out_path)
        return

    gaps = 20
    pad = 40
    total_h = sum(len(b[1]) * (b[2].size + b[3]) - b[3] for b in blocks) + gaps * (len(blocks) - 1)
    top = TEXT_TOP + pad
    if top + total_h + pad > TEXT_BOTTOM:          # 収まらないときは少し上に詰める
        top = max(SAFE_TOP, TEXT_BOTTOM - pad - total_h)
    d.rounded_rectangle((TEXT_BOX_X1, top - pad, TEXT_BOX_X2, top + total_h + pad), radius=40, fill=(25, 15, 20, 165))

    y = top
    colors = {"head": (255, 255, 255, 255), "title": (255, 240, 245, 255),
              "price": (255, 214, 226, 255), "cta": (255, 255, 255, 230)}
    for kind, lines, fnt, gap in blocks:
        # 日本語フォントは上側に余白があるため、少し上に寄せて縦の中心をそろえる
        y = draw_text_block(d, lines, fnt, y - int(fnt.size * 0.12), colors[kind], gap) + int(fnt.size * 0.12) - gap + gaps
    layer.save(out_path)


def make_music(out_path):
    """music/ フォルダに曲があればランダムに1曲、なければ穏やかな和音を自動生成"""
    tracks = sorted(glob.glob("music/*.mp3") + glob.glob("music/*.m4a") + glob.glob("music/*.wav"))
    if tracks:
        track = random.choice(tracks)
        log(f"BGM: {track}")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", track, "-t", str(TOTAL_SEC),
                        "-af", f"volume=0.8,afade=t=in:st=0:d=0.8,afade=t=out:st={TOTAL_SEC - 1.5}:d=1.5",
                        "-ar", "48000", "-ac", "2", out_path], check=True)
        return

    log("BGM: 自動生成（music/ フォルダに曲を入れるとそちらを使います）")
    # C → Am → F → G の穏やかな和音（各3.75秒）。著作権の心配がない自作音源
    chords = [(261.63, 329.63, 392.00), (220.00, 261.63, 329.63), (174.61, 220.00, 261.63), (196.00, 246.94, 293.66)]
    seg = TOTAL_SEC / len(chords)
    terms = []
    for i, (a, b, c) in enumerate(chords):
        env = f"between(t,{i * seg:.3f},{(i + 1) * seg:.3f})"
        tone = (f"(0.30*sin(2*PI*{a}*t)+0.24*sin(2*PI*{b}*t)+0.22*sin(2*PI*{c}*t)"
                f"+0.10*sin(2*PI*{a * 2}*t)+0.12*sin(2*PI*{a / 2}*t))")
        terms.append(f"{env}*{tone}")
    expr = "0.22*(" + "+".join(terms) + ")*(0.85+0.15*sin(2*PI*0.5*t))"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"aevalsrc='{expr}|{expr}':s=48000:d={TOTAL_SEC}",
                    "-af", f"lowpass=f=2200,aecho=0.8:0.6:120:0.25,afade=t=in:st=0:d=1,afade=t=out:st={TOTAL_SEC - 2}:d=2",
                    "-ar", "48000", out_path], check=True)


def render(payload, workdir):
    job_id = re.sub(r"[^0-9A-Za-z_-]", "", str(payload.get("job_id") or "test"))
    brand = clean_text(payload.get("brand") or "ninomae ONLINE", 30)
    slides = [clean_text(s, 30) for s in (payload.get("slides") or [])][:3]
    while len(slides) < 3:
        slides.append("")
    title = clean_text(short_title(payload.get("title")), 40)
    price = clean_text(payload.get("price"), 30)

    # 写真を用意（3枚に満たなければ繰り返して使う）
    sources = []
    for i, src in enumerate((payload.get("images") or [])[:3]):
        try:
            path = src if os.path.exists(src) else download(src, os.path.join(workdir, f"src{i}.jpg"))
            load_image(path)  # 壊れた画像を弾く
            sources.append(path)
        except Exception as e:
            log(f"画像を取得できませんでした: {src} / {e}")
    if not sources:
        sys.exit("使える商品写真がありません")
    while len(sources) < 3:
        sources.append(sources[len(sources) % len(sources)])

    inputs, filters = [], []
    for i in range(3):
        base = os.path.join(workdir, f"base{i}.jpg")
        text = os.path.join(workdir, f"text{i}.png")
        make_base_frame(load_image(sources[i]), base, is_last=(i == 2))
        make_text_layer(text, slides[i], brand, is_last=(i == 2), title=title, price=price)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(SLIDE_SEC), "-i", base,
                   "-loop", "1", "-framerate", str(FPS), "-t", str(SLIDE_SEC), "-i", text]
        # 写真だけゆっくりズーム（1枚目と3枚目は寄る、2枚目は引く）
        z = (f"{1 + ZOOM}-{ZOOM}*t/{SLIDE_SEC}" if i == 1 else f"1.0+{ZOOM}*t/{SLIDE_SEC}")
        filters.append(
            f"[{2 * i}:v]scale=w='trunc({W}*({z})/2)*2':h='trunc({H}*({z})/2)*2':eval=frame,"
            f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p[bz{i}];"
            f"[{2 * i + 1}:v]format=rgba,fade=t=in:st=0.35:d=0.6:alpha=1[tx{i}];"
            f"[bz{i}][tx{i}]overlay=0:0:format=auto,format=yuv420p[s{i}]"
        )

    off1 = SLIDE_SEC - FADE_SEC
    off2 = off1 + SLIDE_SEC - FADE_SEC
    filters.append(f"[s0][s1]xfade=transition=fade:duration={FADE_SEC}:offset={off1:.2f}[x1];"
                   f"[x1][s2]xfade=transition=fade:duration={FADE_SEC}:offset={off2:.2f},"
                   f"fade=t=in:st=0:d=0.4,fade=t=out:st={TOTAL_SEC - 0.5}:d=0.5[v]")

    music = os.path.join(workdir, "music.m4a")
    make_music(music)
    inputs += ["-i", music]

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{job_id}.mp4")
    cmd = (["ffmpeg", "-y", "-loglevel", "error"] + inputs +
           ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "6:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-t", str(TOTAL_SEC), "-movflags", "+faststart", out])
    subprocess.run(cmd, check=True)
    size = os.path.getsize(out)
    log(f"完成: {out}（{size / 1024 / 1024:.1f} MB）")
    return out


def main():
    raw = os.environ.get("PAYLOAD") or (open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else "")
    if not raw or raw == "null":
        sys.exit("PAYLOAD がありません")
    payload = json.loads(raw)
    # workflow_dispatch（手動実行）の場合は payload が文字列で入ってくる
    if isinstance(payload, dict) and isinstance(payload.get("payload"), str):
        payload = json.loads(payload["payload"])
    with tempfile.TemporaryDirectory() as tmp:
        render(payload, tmp)


if __name__ == "__main__":
    main()
