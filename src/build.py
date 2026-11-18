"""메인: 수집 → 필터·점수 → 공개 페이지 데이터 → 블로그 초안·이미지 → ZIP

실행:
  python src/build.py            # 실제 API (환경변수 DATA_GO_KR_KEY(공공데이터포털 공용), KOPIS_KEY)
  python src/build.py --sample   # 키 없이 샘플 데이터로 미리보기
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect_culture  # noqa: E402
import collect_kopis  # noqa: E402
import collect_manual  # noqa: E402
import collect_tour  # noqa: E402
import draft  # noqa: E402
import images  # noqa: E402
from common import (CATEGORIES, KST, SIDO, Event, category_of, overlaps, parse_ymd,  # noqa: E402
                    today_kst, upcoming_weekend)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def load_sample() -> list[Event]:
    rows = json.loads((ROOT / "tests" / "fixtures" / "sample_events.json").read_text(encoding="utf-8"))
    out = []
    for r in rows:
        r = dict(r)
        r["start"], r["end"] = parse_ymd(r["start"]), parse_ymd(r["end"])
        out.append(Event(**r))
    return out


def score(ev: Event, kw: dict, wk_end) -> int:
    text = f"{ev.title} {ev.genre} {ev.place} {ev.age}"
    if any(x in text for x in kw.get("exclude", [])):
        return -1
    s = 0
    if ev.kid_flag:
        s += 5
    s += min(3, sum(1 for x in kw.get("strong", []) if x in text)) * 3
    s += min(3, sum(1 for x in kw.get("weak", []) if x in text))
    if ev.is_free:
        s += 2
        ev.tags.append("무료")
    if ev.image:
        s += 1
    if ev.end <= wk_end and (ev.end - ev.start).days >= 2:
        ev.tags.append("이번 주말 마감")
        s += 1
    if any(x in text for x in ("인형극", "그림책", "동화", "유아")):
        ev.tags.append("유아 추천")
    elif any(x in text for x in ("과학", "공룡", "체험", "만들기")):
        ev.tags.append("초등 추천")
    return s


def dedup(events: list[Event]) -> list[Event]:
    best: dict[str, Event] = {}
    for e in events:
        cur = best.get(e.key)
        if cur is None or (e.score, bool(e.image)) > (cur.score, bool(cur.image)):
            best[e.key] = e
    return list(best.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    blog_regions: list[str] = cfg.get("blog_regions", ["세종", "대전"])
    today = today_kst()
    wk_start, wk_end = upcoming_weekend(today, cfg["weekend"].get("include_friday", True))
    nx_start, nx_end = wk_start + timedelta(days=7), wk_end + timedelta(days=7)
    win_start, win_end = min(today, wk_start), nx_end  # 페이지: 오늘 ~ 다음 주말
    print(f"이번 주말 {wk_start}~{wk_end} / 다음 주말 {nx_start}~{nx_end}")

    status: dict[str, str] = {}
    events: list[Event] = []
    if args.sample:
        events = load_sample()
        status["sample"] = f"{len(events)}건 (샘플)"
    else:
        sources = [
            ("tour", "DATA_GO_KR_KEY", collect_tour.collect),
            ("kopis", "KOPIS_KEY", collect_kopis.collect),
            ("culture", "DATA_GO_KR_KEY", collect_culture.collect),
        ]
        for name, env, fn in sources:
            key = os.environ.get(env, "").strip()
            if not key:
                status[name] = "키 없음 (건너뜀)"
                continue
            try:  # 한 소스가 죽어도 나머지는 계속
                got = fn(key, win_start, win_end)
                events += got
                status[name] = f"{len(got)}건"
                if name == "culture" and collect_culture.DEBUG:
                    status[name] += f" ({collect_culture.DEBUG})"
            except Exception as e:  # noqa: BLE001
                status[name] = f"실패: {e}"[:200]
                print(f"[경고] {name} 실패: {e}")
    manual = collect_manual.collect(ROOT / "manual_events.yaml")
    events += manual
    status["manual"] = f"{len(manual)}건"
    print("수집 결과:", status)

    kw = cfg["keywords"]
    picked = []
    for e in events:
        if not overlaps(e, win_start, win_end):
            continue
        e.score = score(e, kw, wk_end)
        if e.score < 0:
            continue
        e.category = category_of(e.genre, e.title, e.source)
        picked.append(e)
    picked = dedup(picked)
    picked.sort(key=lambda e: (-e.score, e.end))
    print(f"기간 내 행사: {len(picked)}건")

    # 1) 공개 페이지 데이터 (전국)
    DOCS.mkdir(exist_ok=True)
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    present = {e.region for e in picked}
    page = {
        "updated": now,
        "site": cfg.get("site", {}),
        "today": today.isoformat(),
        "weekend": [wk_start.isoformat(), wk_end.isoformat()],
        "next_weekend": [nx_start.isoformat(), nx_end.isoformat()],
        "regions": [r for r in SIDO if r in present],
        "categories": [c for c in CATEGORIES if any(e.category == c for e in picked)],
        "status": status,
        "sample": args.sample,
        "events": [e.to_dict() for e in picked],
    }
    (DOCS / "data.json").write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 2) 블로그 초안: blog_regions 의 이번 주말 행사, 지역별 상위 N개 고르게
    max_n = cfg.get("max_events_in_post", 10)
    per = max(1, max_n // len(blog_regions))
    post_events = []
    for r in blog_regions:
        post_events += [e for e in picked if e.region == r and e.score >= 3
                        and overlaps(e, wk_start, wk_end)][:per]
    if not post_events:
        print("[안내] 글에 넣을 행사가 없어 초안은 만들지 않습니다.")
        return

    page_url = os.environ.get("PAGE_URL", "")
    seed = wk_start.isoformat()
    d = draft.build(post_events, blog_regions, wk_start, wk_end, seed, page_url)

    out = DOCS / "drafts" / wk_start.isoformat()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    images.cover(out / "01_표지.png", *d["cover_lines"], d["badge"], seed)
    for fname, _ in d["images"][1:-1]:
        reg = fname.split("_", 1)[1].replace("편.png", "")
        images.subtitle(out / fname, f"{reg} 아이랑 행사", seed + reg)
    images.quote(out / d["images"][-1][0], "세 아이 아빠 꿀팁", d["tip"], seed + "tip")

    guide = "\n".join(f"- {f}: {where}" for f, where in d["images"])
    (out / "본문.txt").write_text(d["body"], encoding="utf-8")
    (out / "제목후보.txt").write_text("\n".join(d["titles"]), encoding="utf-8")
    (out / "이미지_넣을위치.txt").write_text(guide, encoding="utf-8")

    zpath = out / "이미지.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, _ in d["images"]:
            z.write(out / fname, fname)

    meta = {"week": wk_start.isoformat(), "titles": d["titles"], "body": d["body"],
            "images": [{"file": f, "where": w} for f, w in d["images"]], "zip": "이미지.zip"}
    (out / "draft.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (DOCS / "drafts" / "latest.json").write_text(
        json.dumps({"week": wk_start.isoformat()}, ensure_ascii=False), encoding="utf-8")
    # 오래된 초안 정리 (최근 8주만 보관)
    olds = sorted(p for p in (DOCS / "drafts").iterdir() if p.is_dir())
    for p in olds[:-8]:
        shutil.rmtree(p)
    print(f"초안 생성 완료: {out}")


if __name__ == "__main__":
    main()
