#!/usr/bin/env python3
"""
SmartMoney 台股 Dashboard — 每日資料抓取器

從 TWSE 公開資料 API 抓取：
  - 大盤加權指數（即時 + 歷史收盤）
  - 三大法人買賣超
  - 追蹤個股即時報價
  - AI 盤後分析（規則式模板，可自行擴充）

輸出 → data/daily.json
由 GitHub Actions 每日盤後自動執行並 commit 回 repo。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# ============================================================================
# 設定
# ============================================================================

TAIPEI_TZ = timezone(timedelta(hours=8))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "data", "daily.json")

# 預設追蹤清單（向後相容：config.json 不存在或損毀時使用）
DEFAULT_WATCHLIST = [
    ("2330", "台積電", "tse"),
    ("2317", "鴻海", "tse"),
    ("2454", "聯發科", "tse"),
    ("2382", "廣達", "tse"),
    ("3443", "創意", "tse"),
    ("2603", "長榮", "tse"),
    ("6770", "力積電", "tse"),
    ("3661", "世芯-KY", "tse"),
    ("2615", "萬海", "tse"),
    ("2881", "富邦金", "tse"),
    ("2882", "國泰金", "tse"),
    ("2891", "中信金", "tse"),
    ("2886", "兆豐金", "tse"),
    ("00878", "國泰永續高股息", "tse"),
    ("00929", "復華台灣科技優息", "tse"),
    ("00940", "元大台灣價值高息", "tse"),
]

DEFAULT_SETTINGS = {
    "ai_analysis": True,
    "ai_model": "gpt-4o-mini",
    "language": "zh-TW",
}


def load_config():
    """讀取 config.json；缺檔/格式錯誤時回退到預設值（向後相容）。

    回傳 (watchlist, settings)：
      - watchlist: List[Tuple[code, name, market]]
      - settings: Dict (ai_analysis, ai_model, language)
    """
    if not os.path.exists(CONFIG_PATH):
        log("config.json not found, using defaults")
        return list(DEFAULT_WATCHLIST), dict(DEFAULT_SETTINGS)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log(f"failed to read config.json ({exc}); using defaults")
        return list(DEFAULT_WATCHLIST), dict(DEFAULT_SETTINGS)

    # Parse watchlist
    raw_list = cfg.get("watchlist")
    watchlist = []
    if isinstance(raw_list, list):
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            market = str(item.get("market", "tse")).strip().lower() or "tse"
            if market not in ("tse", "otc"):
                log(f"unknown market '{market}' for {code}, defaulting to tse")
                market = "tse"
            if code and name:
                watchlist.append((code, name, market))
    if not watchlist:
        log("config.json watchlist empty/invalid, using defaults")
        watchlist = list(DEFAULT_WATCHLIST)

    # Parse settings
    settings = dict(DEFAULT_SETTINGS)
    raw_settings = cfg.get("settings")
    if isinstance(raw_settings, dict):
        for key in ("ai_analysis", "ai_model", "language"):
            if key in raw_settings:
                settings[key] = raw_settings[key]

    log(f"loaded config: {len(watchlist)} stocks, ai_model={settings.get('ai_model')}")
    return watchlist, settings


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SmartMoneyTW/1.0; +https://github.com/fintools-tw/smartmoney-tw)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.twse.com.tw/",
}


# ============================================================================
# Utility
# ============================================================================

def log(msg: str) -> None:
    print(f"[twse_daily] {msg}", file=sys.stderr, flush=True)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def fetch_json(url: str, retries: int = 2, timeout: int = 15):
    """Fetch JSON from URL with retries. Returns None on failure."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            if attempt < retries:
                time.sleep(1 + attempt)
            else:
                log(f"fetch failed ({url[:80]}...): {exc}")
                return None
        except Exception as exc:  # noqa: BLE001
            log(f"unexpected error ({url[:80]}...): {exc}")
            return None
    return None


def to_number(value):
    """Try to convert TWSE field to a number; return None when not parseable."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in ("", "-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def round2(value):
    if value is None:
        return None
    return round(float(value) + 1e-9, 2)


# ============================================================================
# Data sources
# ============================================================================

def get_realtime_index():
    """大盤加權指數即時報價 (mis.twse.com.tw)。"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0"
    data = fetch_json(url)
    if not data or not data.get("msgArray"):
        return None

    raw = data["msgArray"][0]
    price = to_number(raw.get("z"))
    yesterday = to_number(raw.get("y"))
    change = round2(price - yesterday) if price is not None and yesterday is not None else None
    change_pct = round2((change / yesterday) * 100) if change is not None and yesterday else None

    return {
        "code": raw.get("c", "t00"),
        "name": raw.get("n", "發行量加權股價指數"),
        "price": price,
        "yesterday": yesterday,
        "open": to_number(raw.get("o")),
        "high": to_number(raw.get("h")),
        "low": to_number(raw.get("l")),
        "change": change,
        "changePct": change_pct,
        "time": raw.get("t", ""),
        "date": raw.get("d", ""),
    }


def get_historical_index():
    """從 FMTQIK 月統計取出最近一個有資料的交易日收盤。"""
    today = now_taipei()
    for offset in range(0, 6):  # 最多回溯 6 個月
        ref = (today.replace(day=1) - timedelta(days=offset * 28)).replace(day=1)
        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
            f"?response=json&date={ref.strftime('%Y%m%d')}"
        )
        data = fetch_json(url)
        if not data:
            # 舊路徑備援
            url = f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={ref.strftime('%Y%m01')}"
            data = fetch_json(url)
        if data and data.get("stat") == "OK" and data.get("data"):
            rows = data["data"]
            if rows:
                last = rows[-1]
                # 民國年 e.g. "115/05/30"
                date_str = last[0]
                close = to_number(last[4]) if len(last) > 4 else None
                change = to_number(last[5]) if len(last) > 5 else None
                return {
                    "date_roc": date_str,
                    "volume_shares": to_number(last[1]),
                    "volume_amount": to_number(last[2]),
                    "transactions": to_number(last[3]),
                    "close": close,
                    "change": change,
                }
    return None


def get_daily_history(days: int = 30):
    """抓取最近 N 個交易日的大盤每日收盤資料。

    回溯最近 3 個月的 FMTQIK 月統計，組成由舊到新的清單。
    每筆：{date: 'YYYY/MM/DD', close, change, volume, transactions}
    """
    today = now_taipei()
    rows_acc = []
    seen_dates = set()

    # 從最舊往最新走（3 個月前 → 當月），確保最後 slice 取得最近的
    for offset in range(3, -1, -1):
        # 取得 offset 個月前的第一天
        ref = today.replace(day=1)
        for _ in range(offset):
            ref = (ref - timedelta(days=1)).replace(day=1)

        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
            f"?response=json&date={ref.strftime('%Y%m%d')}"
        )
        data = fetch_json(url)
        if not data:
            # 舊路徑備援
            url = f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={ref.strftime('%Y%m01')}"
            data = fetch_json(url)

        if not data or data.get("stat") != "OK":
            log(f"FMTQIK miss for {ref.strftime('%Y-%m')}")
            time.sleep(0.8)
            continue
        if isinstance(data.get("data"), list):
            log(f"FMTQIK {ref.strftime('%Y-%m')}: {len(data['data'])} rows")
            for row in data["data"]:
                if not row or len(row) < 6:
                    continue
                roc_date = str(row[0]).strip()
                # 民國年轉西元年："115/05/30" → "2026/05/30"
                gregorian = roc_to_gregorian(roc_date)
                if not gregorian or gregorian in seen_dates:
                    continue
                close = to_number(row[4])
                if close is None:
                    continue
                change = to_number(row[5])
                volume_shares = to_number(row[1])
                transactions = to_number(row[3])
                seen_dates.add(gregorian)
                rows_acc.append({
                    "date": gregorian,
                    "close": close,
                    "change": change,
                    "volume": volume_shares,
                    "transactions": transactions,
                })
        time.sleep(0.8)  # 避免被限速

    if not rows_acc:
        return []

    # 排序（由舊到新）並取最後 N 筆
    rows_acc.sort(key=lambda r: r["date"])
    return rows_acc[-days:]


def roc_to_gregorian(roc_date: str):
    """民國年日期轉西元年。"""
    try:
        parts = roc_date.split("/")
        if len(parts) != 3:
            return None
        roc_year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])
        gregorian_year = roc_year + 1911
        return f"{gregorian_year:04d}/{month:02d}/{day:02d}"
    except (ValueError, AttributeError):
        return None


def get_institutional_investors():
    """三大法人買賣超：回溯最近 7 個自然日，找最近一筆有資料的。"""
    today = now_taipei()
    for offset in range(0, 8):
        ref = today - timedelta(days=offset)
        date_str = ref.strftime("%Y%m%d")
        url = (
            "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
            f"?response=json&dayDate={date_str}&type=day"
        )
        data = fetch_json(url)
        if not data:
            url = f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day"
            data = fetch_json(url)
        if data and data.get("stat") == "OK" and data.get("data"):
            result = {}
            for row in data["data"]:
                label = str(row[0]).strip()
                buy = to_number(row[1])
                sell = to_number(row[2])
                net = to_number(row[3])
                key = None
                if "外" in label:
                    key = "外資"
                elif "投信" in label:
                    key = "投信"
                elif "自營" in label:
                    key = "自營商"
                if key and key not in result:
                    result[key] = {"buy": buy, "sell": sell, "net": net}
            if result:
                note = ""
                if isinstance(data.get("notes"), list) and data["notes"]:
                    note = str(data["notes"][0])
                return {"date": date_str, "data": result, "note": note}
    return None


def get_margin_balance():
    """全市場融資融券餘額（信用交易統計）。

    來源：TWSE rwd/marginTrading/MI_MARGN?selectType=MS（市場彙總表 MS）。
    回溯最近 8 個自然日找最近一筆有資料的交易日。

    回傳 dict：
      date, marginToday (融資今日餘額/仟元), marginPrev (融資前日餘額/仟元),
      marginChange (仟元), marginChangePct (%),
      shortToday, shortPrev（融券今日/前日餘額，交易單位）
    任一步驟失敗回傳 None。
    """
    today = now_taipei()
    for offset in range(0, 8):
        ref = today - timedelta(days=offset)
        date_str = ref.strftime("%Y%m%d")
        url = (
            "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
            f"?response=json&date={date_str}&selectType=MS"
        )
        data = fetch_json(url)
        if not (data and data.get("stat") == "OK" and data.get("tables")):
            continue
        rows = data["tables"][0].get("data") or []
        if not rows:
            continue
        margin_today = margin_prev = short_today = short_prev = None
        for row in rows:
            label = str(row[0])
            # 融資金額(仟元)：前日餘額 = row[4], 今日餘額 = row[5]
            if "融資金額" in label and len(row) > 5:
                margin_prev = to_number(row[4])
                margin_today = to_number(row[5])
            # 融券(交易單位)：前日餘額 = row[4], 今日餘額 = row[5]
            elif label.startswith("融券(") and len(row) > 5:
                short_prev = to_number(row[4])
                short_today = to_number(row[5])
        if margin_today is None or margin_prev is None:
            continue
        change = round2(margin_today - margin_prev)
        change_pct = round2((change / margin_prev) * 100) if margin_prev else None
        return {
            "date": date_str,
            "marginToday": margin_today,
            "marginPrev": margin_prev,
            "marginChange": change,
            "marginChangePct": change_pct,
            "shortToday": short_today,
            "shortPrev": short_prev,
        }
    return None


def get_day_trade_stats():
    """全市場當日沖銷交易統計（投機熱度）。

    來源：TWSE exchangeReport/TWTB4U（市場彙總，stockNo 空字串）。
    回溯最近 8 個自然日。

    回傳 dict：
      date, volumeRatio (當沖股數占市場比重%),
      buyValueRatio (%), sellValueRatio (%)
    失敗回傳 None。
    """
    today = now_taipei()
    for offset in range(0, 8):
        ref = today - timedelta(days=offset)
        date_str = ref.strftime("%Y%m%d")
        url = (
            "https://www.twse.com.tw/exchangeReport/TWTB4U"
            f"?response=json&date={date_str}&stockNo="
        )
        data = fetch_json(url)
        if not (data and data.get("stat") == "OK" and data.get("tables")):
            continue
        table_rows = data["tables"][0].get("data") or []
        if not table_rows:
            continue
        row = table_rows[0]
        # fields: 股數, 股數占比%, 買金額, 買金額占比%, 賣金額, 賣金額占比%
        vol_ratio = to_number(row[1]) if len(row) > 1 else None
        buy_ratio = to_number(row[3]) if len(row) > 3 else None
        sell_ratio = to_number(row[5]) if len(row) > 5 else None
        if vol_ratio is None:
            continue
        return {
            "date": date_str,
            "volumeRatio": vol_ratio,
            "buyValueRatio": buy_ratio,
            "sellValueRatio": sell_ratio,
        }
    return None


def get_stock_quotes(watchlist):
    """批量即時報價。"""
    ex_ch = "|".join(f"{m}_{c}.tw" for c, _n, m in watchlist)
    url = (
        "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        f"?ex_ch={ex_ch}&json=1&delay=0&_={int(time.time() * 1000)}"
    )
    data = fetch_json(url)
    if not data or not data.get("msgArray"):
        return []

    by_code = {row.get("c"): row for row in data["msgArray"]}
    quotes = []
    for code, name, _market in watchlist:
        raw = by_code.get(code, {})
        price = to_number(raw.get("z"))
        yesterday = to_number(raw.get("y"))
        change = round2(price - yesterday) if price is not None and yesterday is not None else None
        change_pct = round2((change / yesterday) * 100) if change is not None and yesterday else None

        quotes.append({
            "code": code,
            "name": name,
            "price": price,
            "yesterday": yesterday,
            "open": to_number(raw.get("o")),
            "high": to_number(raw.get("h")),
            "low": to_number(raw.get("l")),
            "volume": to_number(raw.get("v")),
            "change": change,
            "changePct": change_pct,
            "time": raw.get("t", ""),
            "date": raw.get("d", ""),
        })
    return quotes


# ============================================================================
# 韭菜溫度計 (Retail Sentiment Index) — 散戶情緒指數 0-100
# ============================================================================
#
# 合成公式（一句話版）：
#   散戶槓桿升溫(融資) + 當沖投機熱 + 散戶追高而法人倒貨(背離) + 大盤漲劢助燃
#   → 加權平均成 0-100，分五檔：冰凍/觀望/溫熱/過熱/沸騰。
#
# 詳細公式（各成分先各自映射到 0-100，再依權重加權平均）：
#
#   總分 = Σ(wᵢ · scoreᵢ) / Σ(wᵢ)   —— 只對「有資料」的成分加總
#           （任一 API 掛掉 → 該成分跳過，剩餘權重重新歸一化，不讓整個流程掛）
#
#   成分與權重：
#     1. 融資餘額日變化 (margin)      權重 0.35
#        散戶槓桿；融資餘額上升 = 散戶加碼追高 = 升溫
#        score = clamp(50 + 日變化% × 25, 0, 100)   (+2%→100, 0%→50, -2%→0)
#     2. 當沖成交占比 (daytrade)       權重 0.30
#        投機熱度；當沖股數占大盤比重越高越投機
#        score = clamp((占比% - 15) / (40 - 15) × 100, 0, 100)   (15%→0, 40%→100)
#     3. 散戶 vs 法人方向背離 (divergence) 權重 0.20
#        散戶方向(融資增減) 對比 三大法人買賣超方向：
#          散戶買 + 法人賣 → 90 (韭菜接刀，最過熱)
#          散戶買 + 法人買 → 65 (齊漲，偏熱)
#          散戶賣 + 法人買 → 40 (法人吸籌、散戶逃，偏冷)
#          散戶賣 + 法人賣 → 20 (雙殺，冰冷)
#     4. 大盤漲跌幅 (index)             權重 0.15
#        助燃；上漲會助長散戶 FOMO
#        score = clamp(50 + 漲跌% × 20, 0, 100)   (+2.5%→100, 0%→50, -2.5%→0)
#
#   檔位：0-20 冰凍 / 20-40 觀望 / 40-60 溫熱 / 60-80 過熱 / 80-100 沸騰(韭菜收割區)
# ============================================================================

SENTIMENT_WEIGHTS = {
    "margin": 0.35,
    "daytrade": 0.30,
    "divergence": 0.20,
    "index": 0.15,
}

SENTIMENT_LEVELS = [
    (0, 20, "冰凍", "#4a9eff"),      # 藍
    (20, 40, "觀望", "#00d4aa"),     # 綠
    (40, 60, "溫熱", "#ffd166"),     # 黃
    (60, 80, "過熱", "#ff9f43"),     # 橘
    (80, 100.01, "沸騰", "#ff4757"),  # 紅
]


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))


def _sentiment_level(score):
    for lo, hi, name, color in SENTIMENT_LEVELS:
        if lo <= score < hi:
            return name, color
    return SENTIMENT_LEVELS[-1][2], SENTIMENT_LEVELS[-1][3]


def _institutional_total_net(institutional):
    """三大法人合計淨額（外資+投信+自營商，元）；無資料回 None。"""
    if not (institutional and institutional.get("data")):
        return None
    total = 0.0
    seen = False
    for key in ("外資", "投信", "自營商"):
        row = institutional["data"].get(key)
        if row and row.get("net") is not None:
            total += row["net"]
            seen = True
    return total if seen else None


def build_sentiment(index_change_pct, institutional, margin, day_trade):
    """計算韭菜溫度計。各成分獨立計算，缺資料則剔除並重新歸一化權重。

    回傳 dict（若完全無任何成分可算則回 None）：
      score (0-100 int), level, color, components[], interpretation
    """
    components = []  # 每項：{key, label, weight, score, raw}

    # 1. 融資餘額日變化
    margin_pct = margin.get("marginChangePct") if margin else None
    if margin_pct is not None:
        s = _clamp(50 + margin_pct * 25)
        components.append({
            "key": "margin",
            "label": "融資槓桿",
            "weight": SENTIMENT_WEIGHTS["margin"],
            "score": round2(s),
            "raw": f"融資餘額日變 {margin_pct:+.2f}%",
            "rawValue": margin_pct,
        })

    # 2. 當沖成交占比
    dt_ratio = day_trade.get("volumeRatio") if day_trade else None
    if dt_ratio is not None:
        s = _clamp((dt_ratio - 15.0) / (40.0 - 15.0) * 100.0)
        components.append({
            "key": "daytrade",
            "label": "當沖投機",
            "weight": SENTIMENT_WEIGHTS["daytrade"],
            "score": round2(s),
            "raw": f"當沖成交占比 {dt_ratio:.2f}%",
            "rawValue": dt_ratio,
        })

    # 3. 散戶 vs 法人背離（需 margin 方向 + 法人方向兩者都有）
    inst_net = _institutional_total_net(institutional)
    if margin_pct is not None and inst_net is not None:
        retail_buy = margin_pct >= 0     # 融資增 = 散戶偏買
        inst_buy = inst_net >= 0         # 法人淨額正 = 買超
        if retail_buy and not inst_buy:
            s, desc = 90.0, "散戶追高、法人倒貨（接刀）"
        elif retail_buy and inst_buy:
            s, desc = 65.0, "散戶法人齊買（齊漲）"
        elif not retail_buy and inst_buy:
            s, desc = 40.0, "法人吸籌、散戶逃（偏冷）"
        else:
            s, desc = 20.0, "散戶法人齊賣（雙殺）"
        components.append({
            "key": "divergence",
            "label": "散戶反法人",
            "weight": SENTIMENT_WEIGHTS["divergence"],
            "score": round2(s),
            "raw": desc + f"（法人 {inst_net/1e8:+.0f} 億）",
            "rawValue": round2(inst_net / 1e8),
        })

    # 4. 大盤漲跌幅
    if index_change_pct is not None:
        s = _clamp(50 + index_change_pct * 20)
        components.append({
            "key": "index",
            "label": "大盤助燃",
            "weight": SENTIMENT_WEIGHTS["index"],
            "score": round2(s),
            "raw": f"大盤 {index_change_pct:+.2f}%",
            "rawValue": index_change_pct,
        })

    if not components:
        return None

    total_weight = sum(c["weight"] for c in components)
    weighted = sum(c["weight"] * c["score"] for c in components)
    score = int(round(weighted / total_weight)) if total_weight else 0
    score = int(_clamp(score))
    level, color = _sentiment_level(score)

    interpretation = _sentiment_interpretation(score, level, components)

    return {
        "score": score,
        "level": level,
        "color": color,
        "components": components,
        "interpretation": interpretation,
        "degraded": len(components) < len(SENTIMENT_WEIGHTS),
    }


def _sentiment_interpretation(score, level, components):
    """一句白話解讀。"""
    parts = []
    by_key = {c["key"]: c for c in components}
    if "margin" in by_key:
        parts.append(by_key["margin"]["raw"])
    if "daytrade" in by_key:
        parts.append(by_key["daytrade"]["raw"])
    if "divergence" in by_key:
        parts.append(by_key["divergence"]["raw"])
    facts = "、".join(parts) if parts else "部分指標缺失"

    tail = {
        "冰凍": "市場情緒冰凍，散戶觀望、風險偏低。",
        "觀望": "情緒偏冷，散戶點火不旺。",
        "溫熱": "情緒溫熱，多空互搖。",
        "過熱": "散戶情緒偏過熱，追高需小心回吐。",
        "沸騰": "情緒沸騰、進入韭菜收割區，注意高檔風險。",
    }.get(level, "")
    return f"溫度 {score} 分（{level}）：{facts}。{tail}"


# ============================================================================
# Analysis — AI-powered (GPT) with rule-based fallback
# ============================================================================

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DISCLAIMER = "本分析由 AI 自動生成，僅供參考，不構成投資建議。"


def _summarise_inputs_for_prompt(index_quote, historical, institutional, quotes):
    """把今日資料壓成精簡文字，餵給 GPT。"""
    lines = []

    if index_quote and index_quote.get("price") is not None:
        lines.append(
            f"加權指數：收盤 {index_quote['price']:.2f}，漲跌 {index_quote.get('change')}, "
            f"漲跌幅 {index_quote.get('changePct')}%，開盤 {index_quote.get('open')}，"
            f"最高 {index_quote.get('high')}，最低 {index_quote.get('low')}，昨收 {index_quote.get('yesterday')}"
        )
    elif historical and historical.get("close") is not None:
        lines.append(f"上一交易日加權指數收盤 {historical['close']:.2f}")
    else:
        lines.append("加權指數資料尚未公布")

    if institutional and institutional.get("data"):
        inst_parts = []
        for key in ("外資", "投信", "自營商"):
            row = institutional["data"].get(key)
            if row and row.get("net") is not None:
                net_yi = row["net"] / 100_000_000.0
                inst_parts.append(f"{key} 淨額 {net_yi:+.2f} 億元")
        if inst_parts:
            lines.append("三大法人：" + "；".join(inst_parts))
    else:
        lines.append("三大法人：資料尚未公布")

    valid_quotes = [q for q in (quotes or []) if q.get("changePct") is not None]
    if valid_quotes:
        valid_quotes.sort(key=lambda q: q["changePct"], reverse=True)
        stock_parts = []
        for q in valid_quotes:
            stock_parts.append(f"{q['name']}({q['code']}) {q['changePct']:+.2f}%")
        lines.append("追蹤個股漲跌幅：" + "、".join(stock_parts))

    return "\n".join(lines)


def build_ai_analysis(index_quote, historical, institutional, quotes, model="gpt-4o-mini"):
    """用 OpenAI GPT 生成白話盤後分析。失敗時回傳 None，由呼叫端 fallback。"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log("OPENAI_API_KEY not set — skipping AI analysis")
        return None

    today = now_taipei().strftime("%Y/%m/%d")
    user_content = (
        f"以下是 {today} 台股盤後資料，請依此撰寫盤後分析：\n\n"
        + _summarise_inputs_for_prompt(index_quote, historical, institutional, quotes)
        + "\n\n請輸出 Markdown 格式（用 ### 當標題），包含：\n"
        "1. 一句話總結今天盤勢\n"
        "2. 三大法人解讀（外資、投信在幹嘛，講出觀點）\n"
        "3. 個股亮點（今天誰最強、誰最弱、可能原因）\n"
        "4. 明天觀察重點\n\n"
        "字數 300-500 字，最後一行請加上免責聲明：\n"
        f"「{DISCLAIMER}」"
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是台股分析師，用白話文為散戶寫盤後分析。語氣像 Threads 上的財經 KOL — 親切、有觀點、不廢話。",
            },
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.7,
        "max_tokens": 900,
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            OPENAI_API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        markdown = data["choices"][0]["message"]["content"].strip()
        if not markdown:
            log("AI analysis returned empty content")
            return None
        if DISCLAIMER not in markdown:
            markdown = markdown.rstrip() + f"\n\n{DISCLAIMER}\n"
        log("AI analysis generated successfully")
        return {"date": today, "markdown": markdown, "source": "ai"}
    except Exception as exc:  # noqa: BLE001
        log(f"AI analysis failed: {exc}")
        return None


def build_analysis(index_quote, historical, institutional, quotes):
    """組合一份基於今日資料的盤後摘要 (markdown)。"""
    today = now_taipei().strftime("%Y/%m/%d")

    # 指數摘要
    if index_quote and index_quote.get("price") is not None:
        change = index_quote.get("change") or 0
        change_pct = index_quote.get("changePct") or 0
        direction = "上漲" if change > 0 else ("下跌" if change < 0 else "持平")
        index_line = (
            f"加權指數收於 **{index_quote['price']:.2f}**，{direction} "
            f"{abs(change):.2f} 點 ({change_pct:+.2f}%)。"
        )
    elif historical and historical.get("close") is not None:
        index_line = f"上一交易日加權指數收於 **{historical['close']:.2f}** 點。"
    else:
        index_line = "今日大盤資料尚未公布。"

    # 三大法人
    inst_lines = []
    if institutional and institutional.get("data"):
        for key in ("外資", "投信", "自營商"):
            row = institutional["data"].get(key)
            if not row or row.get("net") is None:
                continue
            net_yi = row["net"] / 100_000_000.0  # 換算成億
            arrow = "買超" if net_yi > 0 else ("賣超" if net_yi < 0 else "持平")
            inst_lines.append(f"- **{key}**：{arrow} {abs(net_yi):.2f} 億元")
    if not inst_lines:
        inst_lines.append("- 三大法人資料尚未公布或無法取得。")

    # 個股強勢/弱勢
    valid_quotes = [q for q in (quotes or []) if q.get("changePct") is not None]
    valid_quotes.sort(key=lambda q: q["changePct"], reverse=True)
    strong = valid_quotes[:3]
    weak = list(reversed(valid_quotes[-3:])) if len(valid_quotes) >= 3 else []

    stock_lines = []
    if strong:
        names = "、".join(f"{q['name']} ({q['changePct']:+.2f}%)" for q in strong)
        stock_lines.append(f"- **強勢**：{names}")
    if weak:
        names = "、".join(f"{q['name']} ({q['changePct']:+.2f}%)" for q in weak)
        stock_lines.append(f"- **弱勢**：{names}")
    if not stock_lines:
        stock_lines.append("- 個股報價尚在更新中。")

    markdown = (
        "### 今日盤勢摘要\n"
        f"{index_line}\n\n"
        "### 三大法人動向\n"
        + "\n".join(inst_lines)
        + "\n\n"
        "### 追蹤個股觀察\n"
        + "\n".join(stock_lines)
        + "\n\n"
        "### 策略提醒\n"
        "本報告由規則式模板自動產生，僅供參考。投資決策請結合即時新聞、籌碼面與基本面，"
        "並務必設定停損。\n"
    )

    return {"date": today, "markdown": markdown, "source": "rule-based"}


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    log("starting daily snapshot")

    watchlist, settings = load_config()

    index_quote = None
    historical = None
    institutional = None
    quotes = []

    try:
        log("fetching realtime index")
        index_quote = get_realtime_index()
    except Exception as exc:  # noqa: BLE001
        log(f"realtime index error: {exc}")

    try:
        log("fetching historical index")
        historical = get_historical_index()
    except Exception as exc:  # noqa: BLE001
        log(f"historical index error: {exc}")

    daily_history = []
    try:
        log("fetching daily history (30 days)")
        daily_history = get_daily_history(days=30)
        log(f"daily history: {len(daily_history)} rows")
    except Exception as exc:  # noqa: BLE001
        log(f"daily history error: {exc}")

    try:
        log("fetching institutional investors")
        institutional = get_institutional_investors()
        time.sleep(0.5)
    except Exception as exc:  # noqa: BLE001
        log(f"institutional error: {exc}")

    # 韭菜溫度計成分：融資餘額 + 當沖統計（各自 fallback，掛了不影響主流程）
    margin = None
    try:
        log("fetching margin balance (MI_MARGN)")
        margin = get_margin_balance()
        time.sleep(0.5)
    except Exception as exc:  # noqa: BLE001
        log(f"margin error: {exc}")

    day_trade = None
    try:
        log("fetching day-trade stats (TWTB4U)")
        day_trade = get_day_trade_stats()
        time.sleep(0.5)
    except Exception as exc:  # noqa: BLE001
        log(f"day-trade error: {exc}")

    try:
        log("fetching watchlist quotes")
        quotes = get_stock_quotes(watchlist)
    except Exception as exc:  # noqa: BLE001
        log(f"watchlist error: {exc}")

    # 合成韭菜溫度計
    sentiment = None
    try:
        idx_pct = None
        if index_quote and index_quote.get("changePct") is not None:
            idx_pct = index_quote["changePct"]
        elif historical and historical.get("close") and historical.get("change") is not None:
            base = historical["close"] - historical["change"]
            if base:
                idx_pct = round2(historical["change"] / base * 100)
        sentiment = build_sentiment(idx_pct, institutional, margin, day_trade)
        if sentiment:
            # 交易日（優先 margin，其次 day_trade）供前端顯示
            sentiment["date"] = (margin or {}).get("date") or (day_trade or {}).get("date")
            log(f"sentiment: {sentiment['score']} ({sentiment['level']}), "
                f"components={len(sentiment['components'])}, degraded={sentiment['degraded']}")
        else:
            log("sentiment: no components available")
    except Exception as exc:  # noqa: BLE001
        log(f"sentiment error: {exc}")

    analysis = None
    if settings.get("ai_analysis", True):
        analysis = build_ai_analysis(
            index_quote,
            historical,
            institutional,
            quotes,
            model=settings.get("ai_model", "gpt-4o-mini"),
        )
    else:
        log("AI analysis disabled in config")
    if not analysis:
        analysis = build_analysis(index_quote, historical, institutional, quotes)
    log(f"analysis source: {analysis.get('source')}")

    payload = {
        "schemaVersion": 1,
        "generatedAt": now_taipei().strftime("%Y-%m-%d %H:%M:%S %z"),
        "timezone": "Asia/Taipei",
        "index": index_quote,
        "historicalIndex": historical,
        "dailyHistory": daily_history,
        "institutional": institutional,
        "margin": margin,
        "dayTrade": day_trade,
        "sentiment": sentiment,
        "watchlist": quotes,
        "analysis": analysis,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    log(f"wrote {OUTPUT_PATH}")
    log(
        "summary: "
        f"index={'ok' if index_quote and index_quote.get('price') is not None else 'miss'}, "
        f"historical={'ok' if historical else 'miss'}, "
        f"dailyHistory={len(daily_history)}, "
        f"institutional={'ok' if institutional and institutional.get('data') else 'miss'}, "
        f"margin={'ok' if margin else 'miss'}, "
        f"dayTrade={'ok' if day_trade else 'miss'}, "
        f"sentiment={sentiment['score'] if sentiment else 'miss'}, "
        f"watchlist={sum(1 for q in quotes if q.get('price') is not None)}/{len(watchlist)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
