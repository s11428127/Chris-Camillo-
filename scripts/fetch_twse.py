#!/usr/bin/env python3
"""抓證交所開放資料：觀察名單的月營收與近月價量。

為什麼是這個而不是 104：104 與 Dcard 都擋在 Cloudflare 反機器人後面
（2026-08-28 於 GitHub Actions 實測，四個端點全回 403 挑戰頁），繞過那個
等於規避存取控制，不做。證交所 OpenAPI 是官方開放資料，可以放心用。

抓兩樣：
  1. 月營收（每月 10 日左右更新）—— PLAN.md §3.2C 說的台灣獨有 ground truth
  2. 近月日成交 —— 餵 auto-flow.md 已知度公式的「近一個月漲幅 > 20%」那一項

用法：
    python3 scripts/fetch_twse.py
    python3 scripts/fetch_twse.py --stdout
"""
import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "scripts" / "watchlist.json"
OUTDIR = ROOT / "data" / "market"
TW = timezone(timedelta(hours=8))

REVENUE_LISTED = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"      # 上市
REVENUE_OTC = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"      # 上櫃
STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
# 上櫃股（茂達、雍智、精測、弘塑、旺矽…）不在證交所的 STOCK_DAY 裡，
# 櫃買中心只給「今天的收盤」，所以近月漲幅要靠自己累積的快照回推。
TPEX_DAILY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

UA = "signal-window/0.1 (research project; contact via github.com/s11428127/Chris-Camillo-)"
TIMEOUT = 30
SLEEP = 1.5


def get_json(url, params=None):
    # 注意：urllib.parse 一定要在模組層 import。在函式裡 import 會讓 urllib
    # 變成區域名稱，同一個函式裡的 urllib.request 就會炸掉（2026-08-28 踩過）。
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_revenue(codes):
    """一個請求拿全市場月營收，再篩出名單。上櫃表拿不到就只用上市表。"""
    table, errors = {}, []
    for label, url in (("上市", REVENUE_LISTED), ("上櫃", REVENUE_OTC)):
        try:
            for row in get_json(url):
                code = row.get("公司代號") or row.get("SecuritiesCompanyCode")
                if code in codes:
                    table[code] = {
                        "資料年月": row.get("資料年月") or row.get("Dates"),
                        "當月營收": row.get("營業收入-當月營收") or row.get("Revenue"),
                        "上月比較增減%": row.get("營業收入-上月比較增減(%)") or row.get("MonthlyRevenueChange"),
                        "去年同月增減%": row.get("營業收入-去年同月增減(%)") or row.get("LastYearMonthlyRevenueChange"),
                        "market": label,
                    }
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}營收表: {e}")
    return table, errors


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_prices(code, yyyymmdd):
    """回傳（近一月漲幅 %, 最新收盤, 平均成交股數）。"""
    payload = get_json(STOCK_DAY, {"date": yyyymmdd, "stockNo": code, "response": "json"})
    if payload.get("stat") != "OK":
        raise ValueError(payload.get("stat", "無資料"))
    rows = payload.get("data") or []
    closes = [_num(r[6]) for r in rows if _num(r[6]) is not None]
    vols = [_num(r[1]) for r in rows if _num(r[1]) is not None]
    if not closes:
        raise ValueError("沒有收盤價")
    change = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else None
    return {
        "近月漲幅%": round(change, 2) if change is not None else None,
        "最新收盤": closes[-1],
        "平均成交股數": round(sum(vols) / len(vols)) if vols else None,
        "交易日數": len(closes),
    }


def fetch_tpex_closes(codes):
    """櫃買中心：一個請求拿全上櫃今日收盤。回傳 {代號: (收盤, 成交股數)}。"""
    out = {}
    for row in get_json(TPEX_DAILY):
        code = row.get("SecuritiesCompanyCode") or row.get("Code")
        if code in codes:
            out[code] = (_num(row.get("Close") or row.get("ClosingPrice")),
                         _num(row.get("TradingShares") or row.get("TradeVolume")))
    return out


def history_change(code, today_close):
    """用我們自己存的快照回推近月漲幅（上櫃股專用）。不足兩天就回 None。"""
    if today_close is None:
        return None
    closes = []
    for p in sorted(OUTDIR.glob("*.json"))[-25:]:
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for r in snap.get("results", []):
            if r["code"] == code and (r.get("price") or {}).get("最新收盤"):
                closes.append(r["price"]["最新收盤"])
    if not closes:
        return None
    first = closes[0]
    return round((today_close - first) / first * 100, 2) if first else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(TW).strftime("%Y-%m-%d"))
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    companies = json.loads(WATCHLIST.read_text(encoding="utf-8"))["companies"]
    codes = {c["code"] for c in companies}

    revenue, rev_errors = fetch_revenue(codes)
    for e in rev_errors:
        print(f"⚠️  {e}", file=sys.stderr)

    try:
        tpex = fetch_tpex_closes(codes)
    except Exception as e:  # noqa: BLE001
        tpex, _ = {}, rev_errors.append(f"櫃買中心收盤表: {e}")

    month = args.date.replace("-", "")[:6] + "01"
    results, ok = [], 0
    for i, c in enumerate(companies):
        entry = {"code": c["code"], "name": c["name"], "tier": c["tier"],
                 "coverage": c["coverage"], "revenue": revenue.get(c["code"]),
                 "price": None, "error": None}
        try:
            entry["price"] = fetch_prices(c["code"], month)
            ok += 1
        except urllib.error.HTTPError as e:
            entry["error"] = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            # 證交所查不到通常代表它是上櫃股，改走櫃買中心
            close, vol = tpex.get(c["code"], (None, None))
            if close is not None:
                entry["price"] = {
                    "近月漲幅%": history_change(c["code"], close),
                    "最新收盤": close,
                    "平均成交股數": vol,
                    "交易日數": None,
                    "來源": "櫃買中心（近月漲幅由本專案自己的快照回推，需要累積天數）",
                }
                ok += 1
            else:
                entry["error"] = f"證交所：{e}；櫃買中心也沒有這檔"
        results.append(entry)
        print(f"  {c['code']} {c['name']:<8} "
              f"價:{entry['price']['近月漲幅%'] if entry['price'] else 'FAIL'} "
              f"營收:{'有' if entry['revenue'] else '無'}", file=sys.stderr)
        if i < len(companies) - 1:
            time.sleep(SLEEP)

    snapshot = {
        "date": args.date,
        "generated_at": datetime.now(TW).isoformat(),
        "source": "TWSE / TPEx open data",
        "revenue_errors": rev_errors,
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
        print(f"寫入 {out.relative_to(ROOT)}（價量 {ok}/{len(companies)}，"
              f"營收 {sum(1 for r in results if r['revenue'])}/{len(companies)}）", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
