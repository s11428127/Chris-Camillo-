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
OUT = ROOT / "data" / "anomalies"
TW = timezone(timedelta(hours=8))

MIN_BASELINE_DAYS = 7    # 少於這個天數不下任何判斷
MIN_COUNT = 8            # 絕對數量低於這個不看，避免小數字的百分比假象
RATIO_UP = 1.5           # 相對基線 +50% 以上算跳增
RATIO_DOWN = 0.6         # 相對基線 -40% 以下算縮編（抽單的先行訊號）
MIN_DELTA = 5            # 同時要求絕對變化量，擋掉 9→14 這種


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    args = ap.parse_args()

    snaps = load_snapshots()
    if not snaps:
        print("沒有任何快照，先跑 fetch_104.py", file=sys.stderr)
        return 1

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
