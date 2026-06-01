/**
 * SmartMoney 台股 Dashboard — 前端資料層
 *
 * 資料來源優先順序：
 *   1. data/daily.json (GitHub Actions 每日盤後自動更新；主要來源)
 *   2. TWSE 即時 API (盤中盡力嘗試；CORS 可能阻擋)
 *   3. 內建 SAMPLE 資料 (Fork 後第一次開啟、API 全掛時 fallback)
 */
(function () {
  const DAILY_JSON_URL = "data/daily.json";

  const TWSE_REALTIME_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp";

  const WATCHLIST = [
    { code: "2330", name: "台積電", market: "tse" },
    { code: "2317", name: "鴻海", market: "tse" },
    { code: "2454", name: "聯發科", market: "tse" },
    { code: "2382", name: "廣達", market: "tse" },
    { code: "3443", name: "創意", market: "tse" },
    { code: "2603", name: "長榮", market: "tse" },
    { code: "6770", name: "力積電", market: "tse" },
    { code: "3661", name: "世芯-KY", market: "tse" },
    { code: "2615", name: "萬海", market: "tse" },
    { code: "2881", name: "富邦金", market: "tse" },
    { code: "2882", name: "國泰金", market: "tse" },
    { code: "2891", name: "中信金", market: "tse" },
    { code: "2886", name: "兆豐金", market: "tse" },
    { code: "00878", name: "國泰永續高股息", market: "tse" },
    { code: "00929", name: "復華台灣科技優息", market: "tse" },
    { code: "00940", name: "元大台灣價值高息", market: "tse" },
  ];

  // ---------------------------------------------------------------------------
  // SAMPLE fallback (showed only if everything else fails)
  // ---------------------------------------------------------------------------

  const SAMPLE_INDEX = {
    code: "t00",
    name: "發行量加權股價指數",
    price: 21432.76,
    yesterday: 21318.42,
    change: 114.34,
    changePct: 0.54,
    open: 21366.12,
    high: 21488.02,
    low: 21290.45,
    time: "13:30:00",
    date: "",
  };

  const SAMPLE_INSTITUTIONAL = {
    date: "",
    note: "顯示靜態範例資料；資料就緒後將自動覆蓋。",
    data: {
      外資: { net: 13256000000 },
      投信: { net: 2860000000 },
      自營商: { net: -1740000000 },
    },
  };

  const SAMPLE_QUOTES = WATCHLIST.map((item, index) => {
    const bases = [1180, 182.5, 1385, 296, 1085, 201, 23.4, 2685, 83.8, 86.3, 69.8, 43.1, 39.2, 21.75, 18.44, 9.73];
    const changes = [15, -1.5, 20, 3.5, -30, 4, -0.25, 65, -1.1, 0.6, 0.1, -0.25, 0.2, 0.05, -0.03, 0.01];
    const base = bases[index];
    const change = changes[index];
    const yesterday = base - change;
    const changePct = round((change / yesterday) * 100, 2);

    return {
      code: item.code,
      name: item.name,
      price: base,
      yesterday,
      open: yesterday,
      high: round(base + Math.abs(change) * 0.8, 2),
      low: round(base - Math.abs(change) * 0.9, 2),
      volume: [28450, 36812, 7210, 42866, 5122, 69540, 52883, 2980, 31766, 19122, 22015, 56108, 16840, 43788, 78210, 112504][index],
      change,
      changePct,
      time: "13:30:00",
      date: "",
    };
  });

  const SAMPLE_ANALYSIS = {
    date: "範例",
    markdown:
      "### 範例分析\n資料尚未產生。GitHub Actions 將在台灣時間 14:30 與 15:30 自動更新 `data/daily.json`。\n\n- 也可在 GitHub Actions 頁面手動觸發 `Update TWSE daily data`。\n- 本地測試請執行 `python3 twse_daily.py`。",
  };

  // ---------------------------------------------------------------------------
  // Daily snapshot loader
  // ---------------------------------------------------------------------------

  let cachedSnapshot = null;
  let snapshotPromise = null;

  function loadSnapshot() {
    if (cachedSnapshot) return Promise.resolve(cachedSnapshot);
    if (snapshotPromise) return snapshotPromise;

    snapshotPromise = fetch(`${DAILY_JSON_URL}?ts=${Date.now()}`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        cachedSnapshot = data;
        return data;
      })
      .catch((error) => {
        console.warn("[twse-api] daily.json unavailable:", error.message);
        cachedSnapshot = null;
        return null;
      })
      .finally(() => {
        snapshotPromise = null;
      });

    return snapshotPromise;
  }

  function clearSnapshotCache() {
    cachedSnapshot = null;
  }

  // ---------------------------------------------------------------------------
  // Optional realtime fetch (best-effort; usually blocked by CORS on Pages)
  // ---------------------------------------------------------------------------

  function buildRealtimeUrl(symbols) {
    const exCh = symbols.map((item) => `${item.market}_${item.code}.tw`).join("|");
    const params = new URLSearchParams({
      ex_ch: exCh,
      json: "1",
      delay: "0",
      _: String(Date.now()),
    });
    return `${TWSE_REALTIME_URL}?${params.toString()}`;
  }

  async function tryRealtime(symbols) {
    try {
      const response = await fetch(buildRealtimeUrl(symbols), {
        cache: "no-store",
        headers: { Accept: "application/json,text/plain,*/*" },
      });
      if (!response.ok) return null;
      const data = await response.json();
      if (!data || !Array.isArray(data.msgArray)) return null;
      return data.msgArray;
    } catch (_error) {
      return null;
    }
  }

  function normalizeRealtimeRow(raw, fallback = {}) {
    const price = toNumber(raw.z);
    const yesterday = toNumber(raw.y);
    const change = price !== null && yesterday !== null ? round(price - yesterday, 2) : null;
    const changePct = change !== null && yesterday ? round((change / yesterday) * 100, 2) : null;

    return {
      code: raw.c || fallback.code || "",
      name: raw.n || fallback.name || "",
      price,
      yesterday,
      open: toNumber(raw.o),
      high: toNumber(raw.h),
      low: toNumber(raw.l),
      volume: toNumber(raw.v),
      change,
      changePct,
      time: raw.t || "",
      date: raw.d || "",
    };
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  async function getRealtimeIndex() {
    // Try realtime first when market is plausibly open
    if (isMarketLikelyOpen()) {
      const rows = await tryRealtime([{ code: "t00", name: "加權指數", market: "tse" }]);
      if (rows && rows[0]) {
        return normalizeRealtimeRow(rows[0], { code: "t00", name: "發行量加權股價指數" });
      }
    }

    const snapshot = await loadSnapshot();
    if (snapshot && snapshot.index && snapshot.index.price !== null && snapshot.index.price !== undefined) {
      return { ...snapshot.index, source: "daily" };
    }
    return { ...SAMPLE_INDEX, isSample: true };
  }

  async function getWatchlistQuotes() {
    if (isMarketLikelyOpen()) {
      const rows = await tryRealtime(WATCHLIST);
      if (rows && rows.length) {
        const map = new Map(rows.map((row) => [row.c, normalizeRealtimeRow(row)]));
        const merged = WATCHLIST.map((item) => map.get(item.code)).filter(Boolean);
        if (merged.length === WATCHLIST.length) return merged;
      }
    }

    const snapshot = await loadSnapshot();
    if (snapshot && Array.isArray(snapshot.watchlist) && snapshot.watchlist.length) {
      // Ensure stable ordering vs WATCHLIST
      const map = new Map(snapshot.watchlist.map((row) => [row.code, row]));
      return WATCHLIST.map((item, index) => {
        const row = map.get(item.code);
        if (row && row.price !== null && row.price !== undefined) {
          return { ...row, source: "daily" };
        }
        return { ...SAMPLE_QUOTES[index], isSample: true };
      });
    }
    return SAMPLE_QUOTES.map((quote) => ({ ...quote, isSample: true }));
  }

  async function getInstitutionalInvestors() {
    const snapshot = await loadSnapshot();
    if (snapshot && snapshot.institutional && snapshot.institutional.data) {
      return { ...snapshot.institutional, source: "daily" };
    }
    return { ...SAMPLE_INSTITUTIONAL, isSample: true };
  }

  async function getAnalysis() {
    const snapshot = await loadSnapshot();
    if (snapshot && snapshot.analysis && snapshot.analysis.markdown) {
      return { ...snapshot.analysis, source: "daily" };
    }
    return { ...SAMPLE_ANALYSIS, isSample: true };
  }

  async function getGeneratedAt() {
    const snapshot = await loadSnapshot();
    return snapshot ? snapshot.generatedAt || null : null;
  }

  function refresh() {
    clearSnapshotCache();
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function toNumber(value) {
    if (value === null || value === undefined || value === "" || value === "-") return null;
    const parsed = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function round(value, digits) {
    const factor = 10 ** digits;
    return Math.round((value + Number.EPSILON) * factor) / factor;
  }

  function isMarketLikelyOpen() {
    const now = new Date();
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Taipei",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(now);
    const obj = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    const weekday = obj.weekday; // Mon..Sun
    if (weekday === "Sat" || weekday === "Sun") return false;
    const minutes = Number(obj.hour) * 60 + Number(obj.minute);
    // 09:00 - 13:35 Taiwan time
    return minutes >= 9 * 60 && minutes <= 13 * 60 + 35;
  }

  window.TwseApi = {
    WATCHLIST,
    getRealtimeIndex,
    getWatchlistQuotes,
    getInstitutionalInvestors,
    getAnalysis,
    getGeneratedAt,
    refresh,
  };
})();
