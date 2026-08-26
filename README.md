# 訊號窗口 Signal Window

社交套利（Social Arbitrage）研究工具 — 台灣版。

把 Chris Camillo 的方法重寫成 2026 年可執行的系統：不賭「誰先看到」，
賭「誰真的讀懂」。差異化重點是**繁體中文社群語料**與**台股月營收驗證迴圈**。

## 先讀這個

**[PLAN.md](PLAN.md)** — 完整的專案計畫、台灣定位、五層管線、實作順序。

> Claude Code 的終端機對話不會同步到手機。任何新 session 開始前先讀 PLAN.md
> 就能接上進度。有新結論請寫回 PLAN.md，不要只留在對話裡。

## 視覺化規格書（Artifact）

https://claude.ai/code/artifact/493ae357-6dcf-4429-9123-2cb49731b98a

⚠️ 要更新這個頁面而不是產生新連結，必須把上面的 URL 當作 `url` 參數傳給
Artifact 工具。換一個 session 或換一台機器都一樣，沒有這個 URL 就會變成新的 artifact。

原始檔：[web/signal-edge.html](web/signal-edge.html)

## 手機同步

1. 這個 repo push 到 GitHub
2. 手機瀏覽器開 claude.ai/code，對這個 repo 開 session，可直接改檔、commit、開 PR
3. 電腦端 `git pull` 拿回來

## 結構

```
signal-window/
├── README.md   ← 你在這
├── PLAN.md     ← 專案的上下文載體，優先讀
└── web/
    └── signal-edge.html   ← 規格書頁面原始碼
```

## 免責

這是研究工具，不是投資建議。所有分數與門檻都需要用自己的實測資料校準。
