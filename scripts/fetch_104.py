#!/usr/bin/env python3
"""抓觀察名單公司在 104 的開缺數，存成每日快照。

用途：職缺數是**搜尋引擎索引不到**的地面情報。財經媒體只會報導已發布的新聞
（那些依定義已知度就高），但「某家公司某部門突然開 30 個缺」不會上新聞。
這是 stage0/auto-flow.md 裡第 01 層唯一真正有領先性的自動化來源。

只抓「數量」，不存個資、不存職缺內文。一天跑一次，每家一個請求。

用法：
    python3 scripts/fetch_104.py                 # 抓今天，寫進 data/jobs/
    python3 scripts/fetch_104.py --stdout        # 只印出來不寫檔
    python3 scripts/fetch_104.py --date 2026-08-28
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "scripts" / "watchlist.json"
OUTDIR = ROOT / "data" / "jobs"

TW = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
REFERER = "https://www.104.com.tw/jobs/search/"

# 104 換過幾次搜尋端點，兩個都試，記錄哪個活著。
ENDPOINTS = [
    ("api/jobs", "https://www.104.com.tw/jobs/search/api/jobs"),
    ("list", "https://www.104.com.tw/jobs/search/list"),
]

SLEEP_BETWEEN = 2.0   # 客氣一點，一天 14 個請求不該造成任何負擔
TIMEOUT = 25


def _get_json(url, params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={
            "User-Agent": UA,
            "Referer": REFERER,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_count(payload):
    """104 的回傳結構換過，總數可能在幾個位置。找不到就 raise。"""
    if not isinstance(payload, dict):
        raise ValueError("回傳不是 JSON object")
    data = payload.get("data", payload)
    for key in ("totalCount", "total", "totalCounts"):
        if isinstance(data, dict) and isinstance(data.get(key), int):
            return data[key]
    meta = data.get("metadata") if isinstance(data, dict) else None
    if isinstance(meta, dict):
        pg = meta.get("pagination")
        if isinstance(pg, dict) and isinstance(pg.get("total"), int):
            return pg["total"]
    raise ValueError(f"找不到總數欄位，回傳的 key 有：{list(data)[:12]}")


def fetch_one(company):
    params = {
        "keyword": company["keyword"],
        "mode": "s",
        "page": 1,
        "pageSize": 20,
        "order": 15,          # 最近更新
        "asc": 0,
        "jobsource": "index_s",
    }
    if company.get("company_id"):
        params["cop"] = company["company_id"]

    errors = []
    for name, url in ENDPOINTS:
        try:
            return _extract_count(_get_json(url, params)), name, None
        except urllib.error.HTTPError as e:
            errors.append(f"{name}: HTTP {e.code}")
        except urllib.error.URLError as e:
            errors.append(f"{name}: 連不上 ({e.reason})")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    return None, None, "; ".join(errors)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(TW).strftime("%Y-%m-%d"))
    ap.add_argument("--stdout", action="store_true", help="只印出來，不寫檔")
    args = ap.parse_args()

    companies = json.loads(WATCHLIST.read_text(encoding="utf-8"))["companies"]

    results, ok, endpoint_used = [], 0, None
    for i, c in enumerate(companies):
        count, endpoint, err = fetch_one(c)
        if count is not None:
            ok += 1
            endpoint_used = endpoint_used or endpoint
        results.append({
            "code": c["code"], "name": c["name"], "tier": c["tier"],
            "coverage": c["coverage"], "keyword": c["keyword"],
            "count": count, "error": err,
        })
        print(f"  {c['code']} {c['name']:<8} {count if count is not None else 'FAIL: ' + (err or '')}",
              file=sys.stderr)
        if i < len(companies) - 1:
            time.sleep(SLEEP_BETWEEN)

    snapshot = {
        "date": args.date,
        "generated_at": datetime.now(TW).isoformat(),
        "source": "104.com.tw job search (count only)",
        "endpoint_used": endpoint_used,
        "ok": ok,
        "total": len(companies),
        "results": results,
    }

    if args.stdout:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        OUTDIR.mkdir(parents=True, exist_ok=True)
        out = OUTDIR / f"{args.date}.json"
        out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"寫入 {out.relative_to(ROOT)}（{ok}/{len(companies)} 家成功）", file=sys.stderr)

    # 全軍覆沒才算失敗；部分失敗照樣留下快照，缺口在 detect.py 會標出來
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
