(function () {
  const state = {
    indexChart: null,
    institutionalChart: null,
    indexSeries: [],
    dailyHistory: [],
    rankings: null,
    activeRankTab: "institutionalBuy",
  };

  const els = {};

  document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    setupCharts();
    bindEvents();
    loadDashboard();
    loadAnalysis();
    loadAiReview();
    window.setInterval(loadDashboard, 60000);
  });

  function bindElements() {
    [
      "market-status",
      "refresh-button",
      "market-time",
      "index-current",
      "index-change",
      "index-open",
      "index-high",
      "index-low",
      "index-yesterday",
      "sentiment-date",
      "sentiment-score",
      "sentiment-level",
      "sentiment-marker",
      "sentiment-interpretation",
      "sentiment-components",
      "rankings-date",
      "rankings-head",
      "rankings-body",
      "rankings-tabs",
      "institutional-date",
      "foreign-net",
      "investment-net",
      "dealer-net",
      "institutional-note",
      "quotes-time",
      "watchlist-body",
      "watchlist-count",
      "analysis-date",
      "analysis-content",
      "ai-review-card",
      "ai-review-date",
      "ai-review-text",
    ].forEach((id) => {
      els[toCamel(id)] = document.getElementById(id);
    });
  }

  function bindEvents() {
    els.refreshButton.addEventListener("click", () => {
      window.TwseApi.refresh();
      loadDashboard();
      loadAnalysis();
      loadAiReview();
    });

    if (els.rankingsTabs) {
      els.rankingsTabs.addEventListener("click", (event) => {
        const btn = event.target.closest(".rank-tab");
        if (!btn) return;
        const key = btn.getAttribute("data-rank");
        if (!key || key === state.activeRankTab) return;
        state.activeRankTab = key;
        Array.from(els.rankingsTabs.querySelectorAll(".rank-tab")).forEach((el) => {
          el.classList.toggle("is-active", el === btn);
        });
        renderRankings(state.rankings);
      });
    }
  }

  async function loadDashboard() {
    setLoading(true);

    const [indexQuote, institutional, quotes, dailyHistory, sentiment, rankings] = await Promise.all([
      window.TwseApi.getRealtimeIndex(),
      window.TwseApi.getInstitutionalInvestors(),
      window.TwseApi.getWatchlistQuotes(),
      window.TwseApi.getDailyHistory(),
      window.TwseApi.getSentiment(),
      window.TwseApi.getRankings(),
    ]);

    state.dailyHistory = Array.isArray(dailyHistory) ? dailyHistory : [];
    state.rankings = rankings;
    renderSentiment(sentiment);
    renderIndex(indexQuote);
    renderInstitutional(institutional);
    renderRankings(rankings);
    renderWatchlist(quotes);
    updateIndexChart();
    updateStatus(indexQuote, institutional, quotes);
    setLoading(false);
  }

  async function loadAnalysis() {
    try {
      const data = await window.TwseApi.getAnalysis();
      const badge = renderAnalysisBadge(data.source);
      els.analysisDate.innerHTML = `${escapeHtml(data.date || "--")} ${badge}`;
      els.analysisContent.innerHTML = markdownToHtml(data.markdown || "");
    } catch (error) {
      els.analysisDate.textContent = "範例";
      els.analysisContent.innerHTML = markdownToHtml("### 盤後分析\n目前無法讀取分析資料，請稍後再試。");
    }
  }

  async function loadAiReview() {
    const card = els.aiReviewCard;
    if (!card) return;
    try {
      const res = await fetch(`data/ai_review.json?ts=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) {
        card.hidden = true;
        return;
      }
      const data = await res.json();
      const text = (data && typeof data.text === "string") ? data.text.trim() : "";
      if (!text) {
        card.hidden = true;
        return;
      }
      if (els.aiReviewText) els.aiReviewText.textContent = text;
      if (els.aiReviewDate) els.aiReviewDate.textContent = data.date ? formatDate(data.date) : "最新盤後";
      card.hidden = false;
    } catch (error) {
      // 檔案不存在或解析失敗：靜默隱藏，不干擾其他卡片
      card.hidden = true;
    }
  }

  function renderAnalysisBadge(source) {
    if (source === "ai") {
      return '<span class="analysis-badge analysis-badge-ai" title="由 GPT 自動生成">🤖 AI 分析</span>';
    }
    if (source === "rule-based") {
      return '<span class="analysis-badge analysis-badge-rule" title="規則式自動摘要">📊 自動摘要</span>';
    }
    return "";
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderSentiment(sentiment) {
    const card = els.sentimentScore ? els.sentimentScore.closest(".sentiment-card") : null;
    if (!sentiment || !Number.isFinite(sentiment.score)) {
      if (els.sentimentScore) els.sentimentScore.textContent = "--";
      if (els.sentimentLevel) els.sentimentLevel.textContent = "暫無資料";
      if (els.sentimentInterpretation) {
        els.sentimentInterpretation.textContent = "尚未取得散戶情緒資料，等待下次盤後更新。";
      }
      if (els.sentimentComponents) els.sentimentComponents.innerHTML = "";
      if (els.sentimentDate) els.sentimentDate.textContent = "--";
      return;
    }

    const color = sentiment.color || "#ff9f43";
    const score = Math.max(0, Math.min(100, Math.round(sentiment.score)));

    els.sentimentScore.textContent = String(score);
    els.sentimentLevel.textContent = sentiment.level || "--";
    els.sentimentMarker.style.left = `${score}%`;
    els.sentimentInterpretation.textContent = sentiment.interpretation || "";

    if (card) {
      card.style.setProperty("--sentiment-color", color);
      card.style.setProperty("--sentiment-glow", hexToGlow(color));
      card.style.borderColor = hexToBorder(color);
    }

    const comps = Array.isArray(sentiment.components) ? sentiment.components : [];
    els.sentimentComponents.innerHTML = comps
      .map((c) => {
        const s = Number.isFinite(c.score) ? Math.max(0, Math.min(100, c.score)) : 0;
        const fillColor = scoreColor(s);
        const pct = Math.round(c.weight * 100);
        return `
          <li class="sentiment-comp">
            <span class="comp-label">${escapeHtml(c.label || c.key)} <span class="muted">${pct}%</span></span>
            <span class="comp-raw">${escapeHtml(c.raw || "")}</span>
            <span class="comp-track"><span class="comp-fill" style="width:${s}%;background:${fillColor}"></span></span>
            <span class="comp-score">${Math.round(s)}</span>
          </li>
        `;
      })
      .join("");

    // 資料日期（優先用 margin/dayTrade 抓到的交易日，退回 interpretation 無日期）
    if (els.sentimentDate) {
      const d = sentiment.date || "";
      els.sentimentDate.textContent = d ? formatDate(d) : "最新盤後";
    }
  }

  function scoreColor(score) {
    // 對應溫度計漸層：藍→綠→黃→橘→紅
    if (score < 20) return "#4a9eff";
    if (score < 40) return "#00d4aa";
    if (score < 60) return "#ffd166";
    if (score < 80) return "#ff9f43";
    return "#ff4757";
  }

  function hexToGlow(hex) {
    const rgb = hexToRgb(hex);
    return rgb ? `rgba(${rgb}, 0.45)` : "transparent";
  }

  function hexToBorder(hex) {
    const rgb = hexToRgb(hex);
    return rgb ? `rgba(${rgb}, 0.4)` : "var(--border)";
  }

  function hexToRgb(hex) {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(String(hex));
    if (!m) return null;
    return `${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}`;
  }

  function renderIndex(quote) {
    const changeClass = trendClass(quote.change);

    els.indexCurrent.textContent = formatNumber(quote.price, 2);
    els.indexCurrent.className = changeClass;
    els.indexChange.textContent = formatChange(quote.change, quote.changePct);
    els.indexChange.className = `quote-change ${changeClass}`;
    els.indexOpen.textContent = formatNumber(quote.open, 2);
    els.indexHigh.textContent = formatNumber(quote.high, 2);
    els.indexLow.textContent = formatNumber(quote.low, 2);
    els.indexYesterday.textContent = formatNumber(quote.yesterday, 2);
    els.marketTime.textContent = quote.time || getCurrentTime();
  }

  function renderInstitutional(institutional) {
    const data = institutional.data || {};
    const values = [
      data.外資 && data.外資.net,
      data.投信 && data.投信.net,
      data.自營商 && data.自營商.net,
    ];

    els.institutionalDate.textContent = formatDate(institutional.date);
    els.foreignNet.textContent = formatHundredMillion(values[0]);
    els.investmentNet.textContent = formatHundredMillion(values[1]);
    els.dealerNet.textContent = formatHundredMillion(values[2]);
    els.foreignNet.className = trendClass(values[0]);
    els.investmentNet.className = trendClass(values[1]);
    els.dealerNet.className = trendClass(values[2]);
    els.institutionalNote.textContent = institutional.isSample
      ? "尚未取得 TWSE 資料，目前顯示範例。等待下次 GitHub Actions 更新。"
      : institutional.note || "資料來源：TWSE 三大法人買賣超日報。";

    updateInstitutionalChart(values);
  }

  function renderRankings(rankings) {
    if (!els.rankingsBody || !els.rankingsHead) return;

    if (!rankings || typeof rankings !== "object") {
      els.rankingsHead.innerHTML = "";
      els.rankingsBody.innerHTML =
        '<tr><td colspan="4" class="loading-cell">排行榜資料尚未產生，等待下次盤後更新。</td></tr>';
      if (els.rankingsDate) els.rankingsDate.textContent = "--";
      return;
    }

    if (els.rankingsDate) els.rankingsDate.textContent = formatDate(rankings.date);

    const key = state.activeRankTab;
    const list = Array.isArray(rankings[key]) ? rankings[key] : [];
    const isTurnover = key === "turnoverTop";
    const valueHeader = isTurnover ? "成交值" : "買/賣超";

    els.rankingsHead.innerHTML = `
      <tr>
        <th scope="col">#</th>
        <th scope="col">股票</th>
        <th scope="col">${valueHeader}</th>
        <th scope="col">漲跌幅</th>
      </tr>`;

    if (!list.length) {
      els.rankingsBody.innerHTML =
        '<tr><td colspan="4" class="loading-cell">此分類今日無資料。</td></tr>';
      return;
    }

    els.rankingsBody.innerHTML = list
      .map((item, i) => {
        let valueText;
        let valueClass = "";
        if (isTurnover) {
          valueText = `${formatNumber(item.valueYi, 1)} 億`;
        } else {
          const lots = Number(item.netLots);
          valueClass = trendClass(lots);
          valueText = `${formatSigned(lots, 0)} 張`;
        }
        const pctClass = trendClass(item.changePct);
        return `
          <tr>
            <td class="rank-num">${i + 1}</td>
            <td>
              <div class="stock-name">
                ${escapeHtml(shortName(item.name))}
                <span>${escapeHtml(item.code)}</span>
              </div>
            </td>
            <td class="${valueClass}">${valueText}</td>
            <td class="${pctClass}">${formatPercent(item.changePct)}</td>
          </tr>`;
      })
      .join("");
  }

  function renderAlertBadges(alerts) {
    if (!Array.isArray(alerts) || !alerts.length) return "";
    const badges = alerts
      .map((a) => {
        const cls =
          a.type === "volume" ? "alert-volume" : a.type === "bias" ? "alert-bias" : "alert-move";
        return `<span class="alert-badge ${cls}">${escapeHtml(a.label || "")}</span>`;
      })
      .join("");
    return `<div class="stock-alerts">${badges}</div>`;
  }

  function renderWatchlist(quotes) {
    els.quotesTime.textContent = getCurrentTime();
    if (els.watchlistCount) {
      els.watchlistCount.textContent = String(quotes.length);
    }
    els.watchlistBody.innerHTML = quotes
      .map((quote) => {
        const className = trendClass(quote.change);
        const badge = quote.isSample
          ? "範例資料"
          : quote.source === "daily"
          ? "盤後資料"
          : "TWSE 即時";
        const alertBadges = renderAlertBadges(quote.alerts);

        return `
          <tr>
            <td>${escapeHtml(quote.code)}</td>
            <td>
              <div class="stock-name">
                ${escapeHtml(shortName(quote.name))}
                <span>${badge}</span>
                ${alertBadges}
              </div>
            </td>
            <td class="${className}">${formatNumber(quote.price, 2)}</td>
            <td class="${className}">${formatSigned(quote.change, 2)}</td>
            <td class="${className}">${formatPercent(quote.changePct)}</td>
            <td>${formatVolume(quote.volume)}</td>
          </tr>
        `;
      })
      .join("");
  }

  function updateStatus(indexQuote, institutional, quotes) {
    const hasSample = indexQuote.isSample || institutional.isSample || quotes.some((quote) => quote.isSample);
    if (hasSample) {
      els.marketStatus.textContent = "部分範例資料";
      return;
    }
    const usesDaily =
      indexQuote.source === "daily" ||
      institutional.source === "daily" ||
      quotes.some((q) => q.source === "daily");
    els.marketStatus.textContent = usesDaily ? "盤後資料" : "TWSE 即時";
  }

  function setupCharts() {
    const gridColor = "rgba(139, 148, 158, 0.18)";
    const textColor = "#8b949e";

    const canvas = document.getElementById("index-chart");
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, "rgba(74, 158, 255, 0.32)");
    gradient.addColorStop(1, "rgba(74, 158, 255, 0.02)");

    state.indexChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "收盤指數",
            data: [],
            borderColor: "#4a9eff",
            backgroundColor: gradient,
            borderWidth: 2,
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointBackgroundColor: "#4a9eff",
            pointBorderColor: "#0d1117",
            pointBorderWidth: 2,
          },
        ],
      },
      options: indexChartOptions(gridColor, textColor),
    });

    state.institutionalChart = new Chart(document.getElementById("institutional-chart"), {
      type: "bar",
      data: {
        labels: ["外資", "投信", "自營商"],
        datasets: [
          {
            label: "買賣超",
            data: [0, 0, 0],
            backgroundColor: ["#b7c0ca", "#b7c0ca", "#b7c0ca"],
            borderRadius: 6,
          },
        ],
      },
      options: {
        ...chartOptions(gridColor, textColor),
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (context) => `${context.parsed.y.toFixed(2)} 億元`,
            },
          },
        },
      },
    });
  }

  function indexChartOptions(gridColor, textColor) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 450 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161b22",
          borderColor: "#30363d",
          borderWidth: 1,
          titleColor: "#e6edf3",
          bodyColor: "#c9d1d9",
          padding: 10,
          callbacks: {
            title: (items) => {
              if (!items || !items.length) return "";
              const idx = items[0].dataIndex;
              const row = state.dailyHistory[idx];
              return row ? row.date : items[0].label;
            },
            label: (item) => {
              const idx = item.dataIndex;
              const row = state.dailyHistory[idx];
              const closeText = `收盤 ${formatNumber(item.parsed.y, 2)}`;
              if (!row || !Number.isFinite(row.change)) return closeText;
              const sign = row.change > 0 ? "+" : "";
              const pct = row.close && row.change !== row.close
                ? ` (${sign}${((row.change / (row.close - row.change)) * 100).toFixed(2)}%)`
                : "";
              return [closeText, `漲跌 ${sign}${formatNumber(row.change, 2)}${pct}`];
            },
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: textColor,
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 8,
          },
          grid: { color: "transparent" },
        },
        y: {
          ticks: { color: textColor },
          grid: { color: gridColor },
          beginAtZero: false,
        },
      },
    };
  }

  function chartOptions(gridColor, textColor) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 450 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161b22",
          borderColor: "#30363d",
          borderWidth: 1,
          titleColor: "#e6edf3",
          bodyColor: "#c9d1d9",
        },
      },
      scales: {
        x: {
          ticks: { color: textColor, maxRotation: 0 },
          grid: { color: "transparent" },
        },
        y: {
          ticks: { color: textColor },
          grid: { color: gridColor },
        },
      },
    };
  }

  function updateIndexChart() {
    const history = state.dailyHistory || [];
    if (!history.length) {
      state.indexChart.data.labels = [];
      state.indexChart.data.datasets[0].data = [];
      state.indexChart.update();
      return;
    }

    const labels = history.map((row) => formatShortDate(row.date));
    const values = history.map((row) => row.close);

    // 評估走勢：最後一天 vs 第一天
    const first = values[0];
    const last = values[values.length - 1];
    const isUp = Number.isFinite(first) && Number.isFinite(last) && last >= first;
    const lineColor = isUp ? "#00d4aa" : "#ff4757";

    const canvas = state.indexChart.canvas;
    const ctx = canvas.getContext("2d");
    const height = canvas.height || 260;
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    const baseRgb = isUp ? "0, 212, 170" : "255, 71, 87";
    gradient.addColorStop(0, `rgba(${baseRgb}, 0.32)`);
    gradient.addColorStop(1, `rgba(${baseRgb}, 0.02)`);

    const dataset = state.indexChart.data.datasets[0];
    dataset.borderColor = lineColor;
    dataset.backgroundColor = gradient;
    dataset.pointBackgroundColor = lineColor;

    state.indexChart.data.labels = labels;
    dataset.data = values;

    // Y 軸 padding，避免貼邊
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = Math.max((max - min) * 0.12, 50);
    state.indexChart.options.scales.y.min = Math.floor(min - pad);
    state.indexChart.options.scales.y.max = Math.ceil(max + pad);

    state.indexChart.update();
  }

  function formatShortDate(value) {
    if (!value) return "";
    const parts = String(value).split("/");
    if (parts.length === 3) return `${parts[1]}/${parts[2]}`;
    return value;
  }

  function updateInstitutionalChart(values) {
    const hundredMillionValues = values.map((value) => (Number.isFinite(value) ? round(value / 100000000, 2) : 0));
    state.institutionalChart.data.datasets[0].data = hundredMillionValues;
    state.institutionalChart.data.datasets[0].backgroundColor = values.map((value) => colorForValue(value));
    state.institutionalChart.update();
  }

  function setLoading(isLoading) {
    els.refreshButton.classList.toggle("is-loading", isLoading);
    els.refreshButton.disabled = isLoading;
    if (isLoading) {
      els.marketStatus.textContent = "更新中";
    }
  }

  function markdownToHtml(markdown) {
    const lines = markdown.split("\n");
    const html = [];
    let inList = false;

    lines.forEach((line) => {
      const text = line.trim();

      if (!text) {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        return;
      }

      if (text.startsWith("### ")) {
        if (inList) {
          html.push("</ul>");
          inList = false;
        }
        html.push(`<h3>${inlineMarkdown(text.slice(4))}</h3>`);
        return;
      }

      if (text.startsWith("- ")) {
        if (!inList) {
          html.push("<ul>");
          inList = true;
        }
        html.push(`<li>${inlineMarkdown(text.slice(2))}</li>`);
        return;
      }

      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(`<p>${inlineMarkdown(text)}</p>`);
    });

    if (inList) {
      html.push("</ul>");
    }

    return html.join("");
  }

  function inlineMarkdown(text) {
    return escapeHtml(text).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  }

  function formatNumber(value, digits = 2) {
    if (!Number.isFinite(value)) return "--";
    return new Intl.NumberFormat("zh-TW", {
      minimumFractionDigits: value % 1 === 0 ? 0 : digits,
      maximumFractionDigits: digits,
    }).format(value);
  }

  function formatSigned(value, digits = 2) {
    if (!Number.isFinite(value)) return "--";
    const prefix = value > 0 ? "+" : "";
    return `${prefix}${formatNumber(value, digits)}`;
  }

  function formatChange(change, changePct) {
    if (!Number.isFinite(change) || !Number.isFinite(changePct)) return "--";
    return `${formatSigned(change, 2)} (${formatPercent(changePct)})`;
  }

  function formatPercent(value) {
    if (!Number.isFinite(value)) return "--";
    return `${formatSigned(value, 2)}%`;
  }

  function formatHundredMillion(value) {
    if (!Number.isFinite(value)) return "--";
    return `${formatSigned(round(value / 100000000, 2), 2)} 億`;
  }

  function formatVolume(value) {
    if (!Number.isFinite(value)) return "--";
    return new Intl.NumberFormat("zh-TW").format(value);
  }

  function formatDate(value) {
    if (!value) return "--";
    const text = String(value).replace(/\D/g, "");
    if (text.length !== 8) return value;
    return `${text.slice(0, 4)}/${text.slice(4, 6)}/${text.slice(6, 8)}`;
  }

  function shortName(name) {
    return String(name || "").replace("國泰永續高股息", "00878").replace("復華台灣科技優息", "00929").replace("元大台灣價值高息", "00940");
  }

  function trendClass(value) {
    if (value > 0) return "up";
    if (value < 0) return "down";
    return "neutral";
  }

  function colorForValue(value) {
    if (value > 0) return "#ff4444";
    if (value < 0) return "#00c853";
    return "#b7c0ca";
  }

  function getCurrentTime() {
    return new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date());
  }

  function round(value, digits) {
    const factor = 10 ** digits;
    return Math.round((value + Number.EPSILON) * factor) / factor;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function toCamel(id) {
    return id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
  }
})();
