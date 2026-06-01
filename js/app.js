(function () {
  const state = {
    indexChart: null,
    institutionalChart: null,
    indexSeries: loadIndexSeries(),
  };

  const els = {};

  document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    setupCharts();
    bindEvents();
    loadDashboard();
    loadAnalysis();
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
    ].forEach((id) => {
      els[toCamel(id)] = document.getElementById(id);
    });
  }

  function bindEvents() {
    els.refreshButton.addEventListener("click", () => {
      window.TwseApi.refresh();
      loadDashboard();
      loadAnalysis();
    });
  }

  async function loadDashboard() {
    setLoading(true);

    const [indexQuote, institutional, quotes] = await Promise.all([
      window.TwseApi.getRealtimeIndex(),
      window.TwseApi.getInstitutionalInvestors(),
      window.TwseApi.getWatchlistQuotes(),
    ]);

    renderIndex(indexQuote);
    renderInstitutional(institutional);
    renderWatchlist(quotes);
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

    if (quote.price !== null) {
      pushIndexPoint(quote.price, quote.time || getCurrentTime());
      updateIndexChart();
    }
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

        return `
          <tr>
            <td>${escapeHtml(quote.code)}</td>
            <td>
              <div class="stock-name">
                ${escapeHtml(shortName(quote.name))}
                <span>${badge}</span>
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

    state.indexChart = new Chart(document.getElementById("index-chart"), {
      type: "line",
      data: {
        labels: state.indexSeries.map((point) => point.label),
        datasets: [
          {
            label: "加權指數",
            data: state.indexSeries.map((point) => point.value),
            borderColor: "#58a6ff",
            backgroundColor: "rgba(88, 166, 255, 0.16)",
            borderWidth: 2,
            fill: true,
            tension: 0.35,
            pointRadius: 2,
          },
        ],
      },
      options: chartOptions(gridColor, textColor),
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
    state.indexChart.data.labels = state.indexSeries.map((point) => point.label);
    state.indexChart.data.datasets[0].data = state.indexSeries.map((point) => point.value);
    state.indexChart.update();
  }

  function updateInstitutionalChart(values) {
    const hundredMillionValues = values.map((value) => (Number.isFinite(value) ? round(value / 100000000, 2) : 0));
    state.institutionalChart.data.datasets[0].data = hundredMillionValues;
    state.institutionalChart.data.datasets[0].backgroundColor = values.map((value) => colorForValue(value));
    state.institutionalChart.update();
  }

  function pushIndexPoint(price, label) {
    const last = state.indexSeries[state.indexSeries.length - 1];

    if (!last || last.label !== label || last.value !== price) {
      state.indexSeries.push({ label, value: price });
      state.indexSeries = state.indexSeries.slice(-20);
      localStorage.setItem("smartmoney:indexSeries", JSON.stringify(state.indexSeries));
    }
  }

  function loadIndexSeries() {
    try {
      const stored = JSON.parse(localStorage.getItem("smartmoney:indexSeries") || "[]");

      if (Array.isArray(stored) && stored.length) {
        return stored;
      }
    } catch (error) {
      localStorage.removeItem("smartmoney:indexSeries");
    }

    return [];
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
