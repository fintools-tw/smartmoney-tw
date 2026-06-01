# SmartMoney 台股 Dashboard

> Fork → 開 Pages → 隔天就有資料。一個零維護、零成本的台股盤後追蹤面板。

![dashboard preview](docs/screenshot.png)

<!-- 把上線後的截圖放到 docs/screenshot.png 就會顯示在這裡 -->

## ✨ 功能

- **大盤加權指數**：開、高、低、昨收、漲跌幅，附即時走勢圖
- **三大法人買賣超**：外資 / 投信 / 自營商 (億元)
- **16 檔追蹤個股**：權值股、AI / 半導體、金融、高股息 ETF
- **AI 盤後分析**：自動產生每日重點摘要 (規則式，可自行擴充 LLM)
- **完全靜態**：GitHub Pages 直接部署，免伺服器、免費託管
- **自動更新**：GitHub Actions 每天兩次抓 TWSE 公開資料，commit 回 repo

## 🚀 三步驟上手

### 1. Fork

點右上角 **Fork** 把這個 repo 複製到你自己的帳號。

### 2. 開啟 GitHub Pages

進到你 fork 出來的 repo：

1. **Settings → Pages**
2. **Source** 選 `Deploy from a branch`
3. **Branch** 選 `main`，目錄選 `/ (root)`
4. **Save**

幾分鐘後，網站會出現在 `https://<你的帳號>.github.io/smartmoney-tw/`。

### 3. 啟用 GitHub Actions

進到你 fork 出來的 repo：

1. **Settings → Actions → General**
2. **Workflow permissions** 選 **Read and write permissions**
3. **Save**
4. 回到 **Actions** 分頁 → 第一次需要按 **I understand my workflows, go ahead and enable them**
5. 點 **Update TWSE daily data** → **Run workflow** 手動跑一次

之後每個交易日 14:30 與 15:30（台灣時間）會自動更新 `data/daily.json`，網站隨之刷新。

## ⏰ 資料更新時程

| 台北時間 | UTC | 資料內容 |
| --- | --- | --- |
| 14:30 | 06:30 | 個股、大盤收盤 |
| 15:30 | 07:30 | 三大法人買賣超 (TWSE 通常 15:00 後公布) |

非交易日（六日、國定假日）不會排程。

## 🧰 客製化

### 換追蹤個股

編輯 [`twse_daily.py`](twse_daily.py) 與 [`js/twse-api.js`](js/twse-api.js) 的 `WATCHLIST` 變數，保持兩邊一致即可。

### 換配色 / 排版

樣式集中在 [`css/style.css`](css/style.css)，深色金融風為基底，可自行調整。

### 加強 AI 分析

`twse_daily.py` 內 `build_analysis()` 目前是規則式摘要。如果要接 LLM (OpenAI / Anthropic 等)：

1. 把 API key 放到 GitHub Secrets
2. 在 workflow 把 secret 傳給 Python：`env: OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}`
3. 在 `build_analysis()` 用真正的模型呼叫取代規則式邏輯

## 🛠 本地開發

```bash
git clone https://github.com/<你的帳號>/smartmoney-tw.git
cd smartmoney-tw

# 抓最新資料
python3 twse_daily.py

# 啟一個本地 HTTP server
python3 -m http.server 8080
# 開 http://localhost:8080
```

## 📦 檔案結構

```
.
├── .github/workflows/update-data.yml  ← GitHub Actions (每日抓資料)
├── twse_daily.py                      ← 資料抓取器
├── data/daily.json                    ← 自動產生的快照
├── index.html                         ← 入口頁
├── css/style.css                      ← 深色金融風樣式
├── js/twse-api.js                     ← 資料層 (daily.json 優先)
└── js/app.js                          ← UI 渲染 + 圖表
```

## ⚠️ 免責聲明

本專案僅供教育與研究參考，**不構成任何投資建議**。資料來源為 [TWSE 公開資訊](https://www.twse.com.tw/)，準確性以官方為準。請自行判斷投資風險。

## 📄 License

MIT — 自由使用、修改、商用。
