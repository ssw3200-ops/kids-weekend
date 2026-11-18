"""블로그용 이미지 생성 (Pillow, 무료 폰트 Jua)

- 표지: 매주 다른 배경색·캐릭터·장식 (날짜로 시드 → 같은 주는 같은 결과)
- 소제목: 무지개 통통 글씨 띠 이미지
- 인용구: 말풍선 박스 이미지
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent.parent / "fonts" / "Jua.ttf"

RAINBOW = ["#FF5A5F", "#FF9F1C", "#FFC93C", "#5BC85B", "#3FA7F5", "#6C63FF", "#C86DD7"]
THEMES = [
    {"bg": "#FFF4E0", "dot": ["#FFD6A5", "#FDFFB6", "#CAFFBF", "#9BF6FF"], "card": "#FFFFFF"},
    {"bg": "#E8F7FF", "dot": ["#BDE0FE", "#A2D2FF", "#FFC8DD", "#FFAFCC"], "card": "#FFFFFF"},
    {"bg": "#F1FFE8", "dot": ["#D8F3DC", "#B7E4C7", "#FFE5EC", "#FFF3B0"], "card": "#FFFFFF"},
    {"bg": "#FFF0F6", "dot": ["#FFD6E8", "#E0C3FC", "#C9F2FF", "#FFF1A8"], "card": "#FFFFFF"},
    {"bg": "#F3EEFF", "dot": ["#D7C7FF", "#FFDDE1", "#C7F9CC", "#FFE8A3"], "card": "#FFFFFF"},
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def rainbow_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int,
                 offset: int = 0, anchor_center: bool = True, stroke: int = 8) -> None:
    """글자마다 무지개색 + 흰 외곽선 = 통통한 느낌"""
    f = font(size)
    total = draw.textlength(text, font=f)
    x, y = xy
    if anchor_center:
        x = int(x - total / 2)
    ci = offset
    for ch in text:
        color = "#555555" if ch == " " else RAINBOW[ci % len(RAINBOW)]
        # 그림자
        draw.text((x + 4, y + 6), ch, font=f, fill="#E6D8C8",
                  stroke_width=stroke, stroke_fill="#E6D8C8")
        draw.text((x, y), ch, font=f, fill=color, stroke_width=stroke, stroke_fill="#FFFFFF")
        x += draw.textlength(ch, font=f)
        if ch != " ":
            ci += 1


def _face(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """웃는 얼굴 + 볼터치"""
    eye = r * 0.12
    for dx in (-0.35, 0.35):
        draw.ellipse([cx + dx * r - eye, cy - 0.15 * r - eye, cx + dx * r + eye, cy - 0.15 * r + eye], fill="#3B3B3B")
    draw.arc([cx - 0.35 * r, cy - 0.15 * r, cx + 0.35 * r, cy + 0.4 * r], 20, 160, fill="#3B3B3B", width=max(4, r // 14))
    for dx in (-0.6, 0.6):
        draw.ellipse([cx + dx * r - r * 0.16, cy + 0.08 * r, cx + dx * r + r * 0.16, cy + 0.28 * r], fill="#FF9AA2")


def char_sun(draw, cx, cy, r):
    for i in range(12):
        a = math.radians(i * 30)
        x1, y1 = cx + math.cos(a) * r * 1.15, cy + math.sin(a) * r * 1.15
        x2, y2 = cx + math.cos(a) * r * 1.45, cy + math.sin(a) * r * 1.45
        draw.line([x1, y1, x2, y2], fill="#FFB703", width=max(8, r // 7))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#FFD60A", outline="#FFB703", width=6)
    _face(draw, cx, cy, r)


def char_cloud(draw, cx, cy, r):
    for dx, dy, rr in [(-0.7, 0.15, 0.6), (0.7, 0.15, 0.6), (-0.3, -0.25, 0.7), (0.35, -0.3, 0.65), (0, 0.2, 0.8)]:
        draw.ellipse([cx + dx * r - rr * r, cy + dy * r - rr * r, cx + dx * r + rr * r, cy + dy * r + rr * r], fill="#FFFFFF")
    _face(draw, cx, cy + int(0.1 * r), int(r * 0.8))


def char_star(draw, cx, cy, r):
    pts = []
    for i in range(10):
        rr = r * 1.25 if i % 2 == 0 else r * 0.6
        a = math.radians(-90 + i * 36)
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    draw.polygon(pts, fill="#FFE066", outline="#F4B400")
    _face(draw, cx, cy + int(0.1 * r), int(r * 0.7))


def char_balloon(draw, cx, cy, r):
    draw.line([cx, cy + r * 1.2, cx - r * 0.2, cy + r * 2.0], fill="#888888", width=4)
    draw.ellipse([cx - r * 0.9, cy - r * 1.1, cx + r * 0.9, cy + r * 1.2], fill="#FF8FAB")
    draw.polygon([(cx - 14, cy + r * 1.2), (cx + 14, cy + r * 1.2), (cx, cy + r * 1.35)], fill="#FF8FAB")
    _face(draw, cx, cy, int(r * 0.85))


CHARACTERS = [char_sun, char_cloud, char_star, char_balloon]


def _confetti(draw, w, h, colors, rnd, n=60, avoid=None):
    for _ in range(n):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        if avoid and avoid[0] < x < avoid[2] and avoid[1] < y < avoid[3]:
            continue
        s = rnd.randint(8, 22)
        c = rnd.choice(colors)
        if rnd.random() < 0.5:
            draw.ellipse([x, y, x + s, y + s], fill=c)
        else:
            draw.rounded_rectangle([x, y, x + s, y + s // 2 + 4], radius=4, fill=c)


def cover(path: Path, line1: str, line2: str, badge: str, seed: str) -> None:
    rnd = random.Random(seed)
    th = rnd.choice(THEMES)
    W = H = 1080
    img = Image.new("RGB", (W, H), th["bg"])
    d = ImageDraw.Draw(img, "RGBA")
    _confetti(d, W, H, th["dot"], rnd, n=90)

    # 카드
    d.rounded_rectangle([70, 300, W - 70, 860], radius=60, fill=th["card"], outline="#F2E6D9", width=6)
    off = rnd.randint(0, 6)
    rainbow_text(d, (W // 2, 380), line1, 108, offset=off, stroke=10)
    rainbow_text(d, (W // 2, 560), line2, 84, offset=off + 3, stroke=8)

    # 배지 (날짜)
    f = font(46)
    bw = d.textlength(badge, font=f) + 70
    bx = (W - bw) / 2
    d.rounded_rectangle([bx, 720, bx + bw, 800], radius=40, fill="#FFE5EC")
    d.text((W / 2, 760), badge, font=f, fill="#E85D75", anchor="mm")

    # 캐릭터 2개 (매주 다른 조합)
    c1, c2 = rnd.sample(CHARACTERS, 2)
    c1(d, 200, 175, 95)
    c2(d, W - 200, 960, 80)
    img.save(path, optimize=True)


def subtitle(path: Path, text: str, seed: str) -> None:
    rnd = random.Random(seed)
    th = rnd.choice(THEMES)
    W, H = 1080, 260
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([20, 30, W - 20, H - 30], radius=100, fill=th["bg"])
    _confetti(d, W, H, th["dot"], rnd, n=25, avoid=(160, 50, W - 160, H - 50))
    rainbow_text(d, (W // 2, 75), text, 92, offset=rnd.randint(0, 6), stroke=8)
    rnd.choice(CHARACTERS)(d, 95, H // 2, 48)
    img.save(path, optimize=True)


def _wrap(draw, text: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split(" "):
        test = (cur + " " + word).strip()
        if draw.textlength(test, font=f) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def quote(path: Path, head: str, body: str, seed: str) -> None:
    rnd = random.Random(seed)
    th = rnd.choice(THEMES)
    W = 1080
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    fb = font(50)
    lines = _wrap(tmp, body, fb, W - 260)
    H = 260 + len(lines) * 72
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([40, 40, W - 40, H - 40], radius=50, fill=th["bg"], outline=rnd.choice(th["dot"]), width=8)
    rnd.choice(CHARACTERS)(d, 120, 105, 42)
    rainbow_text(d, (W // 2, 80), head, 64, offset=rnd.randint(0, 6), stroke=6)
    y = 190
    for ln in lines:
        d.text((W / 2, y), ln, font=fb, fill="#4A4A4A", anchor="mt")
        y += 72
    img.save(path, optimize=True)
