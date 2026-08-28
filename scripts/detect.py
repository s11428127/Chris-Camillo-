#!/usr/bin/env python3
"""比對最新的 104 職缺快照與歷史基線，挑出異常。

這是 auto-flow.md 第 01→02 層之間的那一刀：把 14 家的原始數字，
壓成「今天有哪幾家不對勁」。跑完的報告給 Claude 巡邏任務接手跑 03、04 層。

刻意設計成寧可漏也不要吵：
  - 基線不足 7 天 → 一律不報異常（還在建基線）
  - 小數字不報（3 個缺變 5 個缺不是訊號，是雜訊）
  - Tier B（IC 設計）依 watchlist.md 的規則，要兩家以上同時異常才算數

用法：
    python3 scripts/detect.py                # 比對最新一天
    python3 scripts/detect.py --date 2026-09-05
"""
import argparse
import json
import pathlib
import statistics
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "jobs"
MARKET = ROOT / "data" / "market"
OUT = ROOT / "data" / "anomalies"
TW = timezone(timedelta(hours=8))

MIN_BASELINE_DAYS = 7    # 少於這個天數不下任何判斷
MIN_COUNT = 8            # 絕對數量低於這個不看，避免小數字的百分比假象
RATIO_UP = 1.5           # 相對基線 +50% 以上算跳增
RATIO_DOWN = 0.6         # 相對基線 -40% 以下算縮編（抽單的先行訊號）
MIN_DELTA = 5            # 同時要求絕對變化量，擋掉 9→14 這種

# 月營收不看絕對值，看「跟名單裡其他家比」。理由：8/28 第一次實跑，年增率 30%
# 以上的有 12/14 家 —— 半導體整體都在成長，絕對門檻等於沒過濾。
# 改成偏離名單中位數多少個百分點，門檻會隨產業景氣自己校準。
REV_MOM_GAP = 20.0       # 月增率超出名單中位數這麼多個百分點才算異常
REV_YOY_GAP = 50.0       # 年增率同上
PRICE_RUN = 20.0         # 近一月漲幅超過這個 → auto-flow.md 已知度 +20


def load_snapshots():
    out = []
    for p in sorted(JOBS.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"⚠️  跳過壞掉的快照 {p.name}", file=sys.stderr)
    return out


def counts_by_code(snap):
    return {r["code"]: r["count"] for r in snap["results"] if r.get("count") is not None}


def classify(latest, baseline):
    if latest < MIN_COUNT and baseline < MIN_COUNT:
        return None
    delta = latest - baseline
    if abs(delta) < MIN_DELTA:
        return None
    if baseline > 0 and latest >= baseline * RATIO_UP:
        return "跳增"
    if baseline > 0 and latest <= baseline * RATIO_DOWN:
        return "縮編"
    return None


def market_section(date):
    """證交所開放資料：月營收異常，以及餵已知度公式的近月漲幅。"""
    snaps = sorted(MARKET.glob("*.json"))
    if not snaps:
        return ["", "## 證交所開放資料", "",
                "沒有市場快照。先跑 `python3 scripts/fetch_twse.py`。"]
    snap = json.loads(snaps[-1].read_text(encoding="utf-8"))
    lines = ["", f"## 證交所開放資料（{snap['date']}）", "",
             "| 代號 | 公司 | 資料年月 | 月增率 | 年增率 | 近月漲幅 | 已知度提示 |",
             "|---|---|---|---|---|---|---|"]
    def val(r, key):
        try:
            return float((r.get("revenue") or {}).get(key))
        except (TypeError, ValueError):
            return None

    med = {}
    for key in ("上月比較增減%", "去年同月增減%"):
        vals = [v for v in (val(r, key) for r in snap["results"]) if v is not None]
        med[key] = statistics.median(vals) if vals else None
    if med["去年同月增減%"] is not None:
        lines.insert(2, f"名單中位數：月增率 {med['上月比較增減%']:.1f}%、"
                        f"年增率 {med['去年同月增減%']:.1f}%（異常＝偏離中位數，不是絕對值大）")
        lines.insert(3, "")

    notes = []
    for r in snap["results"]:
        rev = r.get("revenue") or {}
        price = r.get("price") or {}
        mom, yoy = rev.get("上月比較增減%"), rev.get("去年同月增減%")
        run = price.get("近月漲幅%")

        def f(v, suffix="%"):
            try:
                return f"{float(v):.1f}{suffix}"
            except (TypeError, ValueError):
                return "—"

        hint = ""
        if run is not None and run >= PRICE_RUN:
            hint = "**已 price in 的可能性高（+20）**"
            notes.append(f"- {r['name']} {r['code']}：近月漲幅 {run:.1f}%，"
                         "依 auto-flow.md 公式已知度 +20")
        for label, v, key, gap in (("月增率", mom, "上月比較增減%", REV_MOM_GAP),
                                   ("年增率", yoy, "去年同月增減%", REV_YOY_GAP)):
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            m = med[key]
            if m is None or abs(v - m) < gap:
                continue
            direction = "高出" if v > m else "低於"
            notes.append(f"- {r['name']} {r['code']}：{label} {v:.1f}%，"
                         f"{direction}名單中位數 {abs(v - m):.0f} 個百分點"
                         f"（{rev.get('資料年月')}）—— 硬數據，可拿來驗證既有假說")

        lines.append(f"| {r['code']} | {r['name']} | {rev.get('資料年月') or '—'} | "
                     f"{f(mom)} | {f(yoy)} | {f(run)} | {hint or '—'} |")

    failed = [r for r in snap["results"] if r.get("error")]
    if failed:
        lines += ["", "抓取失敗（**不等於沒有資料**）：",
                  *[f"- {r['code']} {r['name']}：{r['error']}" for r in failed]]
    if notes:
        lines += ["", "值得注意：", *notes]
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    args = ap.parse_args()

    snaps = load_snapshots()
    if not snaps:
        # 104 目前擋在 Cloudflare 後面（見 stage0/auto-flow.md），所以職缺快照
        # 通常是空的。這不是錯誤，照樣輸出市場那半的報告。
        date = args.date or datetime.now(TW).strftime("%Y-%m-%d")
        lines = [f"# {date} · 巡邏偵測", "",
                 "**沒有職缺資料。** 104 與 Dcard 擋在 Cloudflare 反機器人後面，",
                 "第 01 層目前只有證交所開放資料這一條腿 —— 那是驗證層，不是領先訊號層。",
                 "細節見 `stage0/auto-flow.md`。"]
        lines += market_section(date)
        lines += ["", "## 給巡邏任務的結論", "",
                  "**無職缺訊號可判斷。** 只有月營收與價量可用，"
                  "拿來驗證既有假說、以及餵已知度公式，不足以獨立開卡。", ""]
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{date}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        print(f"\n寫入 {path.relative_to(ROOT)}", file=sys.stderr)
        return 0

    if args.date:
        cur = next((s for s in snaps if s["date"] == args.date), None)
        if cur is None:
            print(f"找不到 {args.date} 的快照", file=sys.stderr)
            return 1
    else:
        cur = snaps[-1]

    history = [s for s in snaps if s["date"] < cur["date"]]
    cur_counts = counts_by_code(cur)
    meta = {r["code"]: r for r in cur["results"]}

    lines = [f"# {cur['date']} · 104 職缺數異常偵測", ""]
    baseline_days = len(history)

    if baseline_days < MIN_BASELINE_DAYS:
        lines += [
            f"**建立基線中**（{baseline_days}/{MIN_BASELINE_DAYS} 天）。",
            "",
            "基線不足，今天不做任何異常判斷 —— 沒有三個月前的比較基準就報異常，",
            "等於把常態當訊號，這正是 watchlist.md 要求「跟基線比對過」的原因。",
            "",
            "今日數字：", "",
            "| 代號 | 公司 | 開缺數 |", "|---|---|---|",
        ]
        for r in cur["results"]:
            lines.append(f"| {r['code']} | {r['name']} | {r['count'] if r['count'] is not None else '抓取失敗'} |")
        anomalies = []
    else:
        anomalies = []
        rows = []
        for code, latest in cur_counts.items():
            series = [counts_by_code(s).get(code) for s in history]
            series = [v for v in series if v is not None]
            if len(series) < MIN_BASELINE_DAYS:
                continue
            baseline = statistics.median(series)
            kind = classify(latest, baseline)
            m = meta[code]
            rows.append((code, m["name"], latest, baseline, kind, m["coverage"], m["tier"]))
            if kind:
                anomalies.append({
                    "code": code, "name": m["name"], "kind": kind,
                    "latest": latest, "baseline": baseline,
                    "coverage": m["coverage"], "tier": m["tier"],
                })

        # watchlist.md 規則：Tier B 單一公司異常可能只是個別因素，要兩家以上互相印證
        tier_b = [a for a in anomalies if a["tier"] == "B"]
        if len(tier_b) == 1:
            demoted = tier_b[0]
            anomalies = [a for a in anomalies if a is not demoted]
            lines += [f"> {demoted['name']} {demoted['code']} 單獨{demoted['kind']}，"
                      "依 watchlist.md「Tier B 需兩家以上同時異常」的規則不列入。", ""]

        lines += [f"基線：過去 {baseline_days} 天的中位數。", "",
                  "| 代號 | 公司 | 今日 | 基線 | 判定 | 券商覆蓋 |", "|---|---|---|---|---|---|"]
        for code, name, latest, baseline, kind, cov, _ in sorted(rows, key=lambda r: r[0]):
            mark = f"**{kind}**" if kind else "—"
            lines.append(f"| {code} | {name} | {latest} | {baseline:.0f} | {mark} | {cov} |")

    failed = [r for r in cur["results"] if r.get("count") is None]
    if failed:
        lines += ["", "## 抓取失敗", "",
                  "以下公司今天沒有數字，**這不等於「開缺數是 0」**，是沒查成：", ""]
        for r in failed:
            lines.append(f"- {r['code']} {r['name']}：{r['error']}")

    lines += market_section(cur["date"])

    lines += ["", "## 給巡邏任務的結論", ""]
    if anomalies:
        lines.append(f"有 **{len(anomalies)}** 家需要往下跑 03（映射）與 04（已知度）：")
        lines.append("")
        for a in anomalies:
            skip = "　⚠️ 覆蓋度高，除非有第二個獨立來源否則直接跳過" if a["coverage"] in ("高", "極高") else ""
            lines.append(f"- **{a['name']} {a['code']}** {a['kind']}："
                         f"{a['baseline']:.0f} → {a['latest']}{skip}")
    else:
        lines.append("**無異常。** 不產生決策卡，不通知。")
    lines.append("")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{cur['date']}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n寫入 {path.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
