(function () {
  const TWSE_REALTIME_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp";
  const TWSE_INSTITUTIONAL_URL = "https://www.twse.com.tw/fund/BFI82U";

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
    date: "20260601",
  };

  const SAMPLE_INSTITUTIONAL = {
    date: "20260601",
    note: "目前顯示靜態範例；TWSE 公布後會自動更新。",
    data: {
      外資: { net: 13256000000 },
      投信: { net: 2860000000 },
      自營商: { net: -1740000000 },
    },
  };

  const SAMPLE_QUOTES = WATCHLIST.map((item, index) => {
    const base = [1180, 182.5, 1385, 296, 1085, 201, 23.4, 2685, 83.8, 86.3, 69.8, 43.1, 39.2, 21.75, 18.44, 9.73][index];
    const change = [15, -1.5, 20, 3.5, -30, 4, -0.25, 65, -1.1, 0.6, 0.1, -0.25, 0.2, 0.05, -0.03, 0.01][index];
    const yesterday = base - change;

    return normalizeQuote({
      c: item.code,
      n: item.name,
      z: String(base),
      y: String(yesterday),
      o: String(yesterday),
      h: String(base + Math.abs(change) * 0.8),
      l: String(base - Math.abs(change) * 0.9),
      v: String([28450, 36812, 7210, 42866, 5122, 69540, 52883, 2980, 31766, 19122, 22015, 56108, 16840, 43788, 78210, 112504][index]),
      t: "13:30:00",
      d: "20260601",
    }, item);
  });

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

  function buildInstitutionalUrl(dateText) {
    const params = new URLSearchParams({
      response: "json",
      dayDate: dateText,
      type: "day",
      _: String(Date.now()),
    });

    return `${TWSE_INSTITUTIONAL_URL}?${params.toString()}`;
  }

  function proxyUrls(url) {
    return [
      url,
      `https://cors-proxy.htmldriven.com/?url=${encodeURIComponent(url)}`,
      `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`,
    ];
  }

  async function fetchJsonWithFallback(url) {
    let lastError = null;

    for (const candidate of proxyUrls(url)) {
      try {
        const response = await fetch(candidate, {
          cache: "no-store",
          headers: { Accept: "application/json,text/plain,*/*" },
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const text = await response.text();
        return JSON.parse(text);
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError || new Error("資料讀取失敗");
  }

  function toNumber(value) {
    if (value === null || value === undefined || value === "" || value === "-") {
      return null;
    }

    const parsed = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizeQuote(raw, fallback = {}) {
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

  function round(value, digits) {
    const factor = 10 ** digits;
    return Math.round((value + Number.EPSILON) * factor) / factor;
  }

  function todayTaipei() {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    const data = Object.fromEntries(parts.map((part) => [part.type, part.value]));

    return `${data.year}${data.month}${data.day}`;
  }

  function extractInstitutional(data) {
    if (!data || data.stat !== "OK" || !Array.isArray(data.data)) {
      return null;
    }

    const result = {};
    data.data.forEach((row) => {
      const label = String(row[0] || "").trim();
      const net = toNumber(row[3]);

      if (label.includes("外資")) result.外資 = { net };
      if (label.includes("投信")) result.投信 = { net };
      if (label.includes("自營商")) result.自營商 = { net };
    });

    return result;
  }

  async function getRealtimeIndex() {
    try {
      const data = await fetchJsonWithFallback(buildRealtimeUrl([{ code: "t00", name: "加權指數", market: "tse" }]));
      const raw = data && Array.isArray(data.msgArray) ? data.msgArray[0] : null;

      return raw ? normalizeQuote(raw, { code: "t00", name: "發行量加權股價指數" }) : SAMPLE_INDEX;
    } catch (error) {
      return { ...SAMPLE_INDEX, isSample: true };
    }
  }

  async function getWatchlistQuotes() {
    try {
      const data = await fetchJsonWithFallback(buildRealtimeUrl(WATCHLIST));
      const rows = data && Array.isArray(data.msgArray) ? data.msgArray : [];
      const quoteMap = new Map(rows.map((row) => [row.c, normalizeQuote(row)]));

      return WATCHLIST.map((item, index) => quoteMap.get(item.code) || SAMPLE_QUOTES[index]);
    } catch (error) {
      return SAMPLE_QUOTES.map((quote) => ({ ...quote, isSample: true }));
    }
  }

  async function getInstitutionalInvestors(dateText = todayTaipei()) {
    try {
      const data = await fetchJsonWithFallback(buildInstitutionalUrl(dateText));
      const extracted = extractInstitutional(data);

      if (!extracted) {
        return { ...SAMPLE_INSTITUTIONAL, isSample: true };
      }

      return {
        date: data.date || dateText,
        data: extracted,
        note: data.notes && data.notes.length ? data.notes[0] : "",
      };
    } catch (error) {
      return { ...SAMPLE_INSTITUTIONAL, isSample: true };
    }
  }

  window.TwseApi = {
    WATCHLIST,
    getRealtimeIndex,
    getWatchlistQuotes,
    getInstitutionalInvestors,
  };
})();
