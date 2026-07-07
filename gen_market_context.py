#!/usr/bin/env python3
"""
SmartMoney 台股 Dashboard — 盤前環境模組資料生成器

彙整開盤前的外部參考數據：
  - 美股前一交易日收盤：S&P 500 / NASDAQ / 道瓊 / 費半 (Yahoo Finance v8 chart API)
  - 台指期近月 (TX)：一般時段 + 盤後(夜盤) 行情 (TAIFEX OpenAPI)
  - 加權指數 MA5 / MA10 / MA20，並標記目前指數站上或跌破各均線 (TWSE FMTQIK)
  - 綜合環境燈號 (green / yellow / red) 與一句參考提示

輸出 → data/market_context.json
可獨立執行，或由 twse_daily.py 主流程尾端自動帶動。

⚠️ 所有文字皆為公開數據彙整，僅供參考，不構成投資建議。
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "data", "market_context.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SmartMoneyTW/1.0; +https://github.com/fintools-tw/smartmoney-tw)",
    "Accept": "application/json,text/plain,*/*",
}

DISCLAIMER = "本區塊為美股、台指期與均線等公開數據彙整，僅供參考，不構成投資建議。市場有風險，進出請自負盈虧。"

# Yahoo Finance 指數代碼 → 顯示名稱
US_INDICES = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "NASDAQ"),
    ("^DJI", "道瓊工業"),
    ("^SOX", "費城半導體"),
]


# ============================================================================
# Utility
# ============================================================================

def log(msg: str) -> None:
    print(f"[market_context] {msg}", file=sys.stderr, flush=True)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def fetch_json(url: str, retries: int = 2, timeout: int = 20):
    """Fetch JSON with retries; return None on failure (never raises)."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError, OSError) as exc:
            if attempt < retries:
                time.sleep(1 + attempt)
            else:
                log(f"fetch failed ({url[:70]}...): {exc}")
                return None
        except Exception as exc:  # noqa: BLE001
            log(f"unexpected error ({url[:70]}...): {exc}")
            return None
    return None


def to_number(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in ("", "-", "--", "NULL", "null"):
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
# a. 美股前一交易日 (Yahoo Finance v8 chart API)
# ============================================================================

def get_us_indices():
    """回傳美股四大指數前一交易日收盤與漲跌%。任一失敗不影響其他。"""
    out = []
    for symbol, name in US_INDICES:
        entry = {"key": symbol, "name": name, "price": None, "change": None,
                 "changePct": None, "date": None}
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(symbol)}?range=5d&interval=1d"
        )
        data = fetch_json(url)
        try:
            res = data["chart"]["result"][0]
            quote = res["indicators"]["quote"][0]
            timestamps = res.get("timestamp") or []
            raw_closes = quote.get("close") or []
            # 過濾 None，配對 (timestamp, close)
            pairs = [
                (timestamps[i], c)
                for i, c in enumerate(raw_closes)
                if c is not None and i < len(timestamps)
            ]
            if len(pairs) >= 2:
                last_ts, last_close = pairs[-1]
                _, prev_close = pairs[-2]
                change = last_close - prev_close
                change_pct = (change / prev_close * 100) if prev_close else None
                entry["price"] = round2(last_close)
                entry["change"] = round2(change)
                entry["changePct"] = round2(change_pct)
                entry["date"] = datetime.fromtimestamp(last_ts, TAIPEI_TZ).strftime("%Y-%m-%d")
            elif len(pairs) == 1:
                entry["price"] = round2(pairs[-1][1])
        except (KeyError, IndexError, TypeError):
            log(f"US index parse miss: {symbol}")
        out.append(entry)
        time.sleep(0.3)
    return out


# ============================================================================
# b. 台指期近月 (TAIFEX OpenAPI) — 一般時段 + 盤後(夜盤)
# ============================================================================

def get_taifex_tx():
    """台指期 TX 近月，一般時段 + 盤後(夜盤)。夜盤缺失時 night=None（優雅降級）。"""
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    data = fetch_json(url)
    result = {"contractMonth": None, "date": None, "day": None, "night": None}
    if not isinstance(data, list):
        log("TAIFEX DailyMarketReportFut unavailable")
        return result

    tx_rows = [r for r in data if str(r.get("Contract", "")).strip() == "TX"]
    if not tx_rows:
        log("TAIFEX: no TX rows")
        return result

    # 近月 = 最小的 ContractMonth(Week)（排除價差/週選，取純數字最小者）
    def month_key(row):
        raw = str(row.get("ContractMonth(Week)", "")).strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else 999999

    near_month = min(month_key(r) for r in tx_rows)
    near_rows = [r for r in tx_rows if month_key(r) == near_month]

    def parse_session(row):
        return {
            "last": to_number(row.get("Last")),
            "change": to_number(row.get("Change")),
            "changePct": to_number(row.get("%")),
            "session": str(row.get("TradingSession", "")).strip(),
        }

    for row in near_rows:
        session = str(row.get("TradingSession", "")).strip()
        result["contractMonth"] = str(row.get("ContractMonth(Week)", "")).strip()
        result["date"] = str(row.get("Date", "")).strip()
        if "一般" in session and result["day"] is None:
            result["day"] = parse_session(row)
        elif "盤後" in session and result["night"] is None:
            result["night"] = parse_session(row)

    if result["night"] is None:
        log("TAIFEX: after-hours (夜盤) session not present → graceful degrade")
    return result


# ============================================================================
# c. 加權指數 MA5 / MA10 / MA20 (TWSE FMTQIK)
# ============================================================================

def get_taiex_ma():
    """抓近兩個月 FMTQIK 收盤指數，算 MA5/10/20，並標記站上/跌破。"""
    today = now_taipei()
    closes = []  # (date_str, close) ascending
    seen = set()
    # 由舊到新：上個月 → 當月
    for offset in (1, 0):
        ref = today.replace(day=1)
        for _ in range(offset):
            ref = (ref - timedelta(days=1)).replace(day=1)
        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
            f"?date={ref.strftime('%Y%m%d')}&response=json"
        )
        data = fetch_json(url)
        if not data or data.get("stat") != "OK" or not isinstance(data.get("data"), list):
            log(f"FMTQIK miss for {ref.strftime('%Y-%m')}")
            time.sleep(0.6)
            continue
        for row in data["data"]:
            if not row or len(row) < 5:
                continue
            date_str = str(row[0]).strip()
            close = to_number(row[4])
            if close is None or date_str in seen:
                continue
            seen.add(date_str)
            closes.append((date_str, close))
        time.sleep(0.6)

    if not closes:
        log("FMTQIK: no close data → MA unavailable")
        return None

    closes.sort(key=lambda x: x[0])  # 民國年字串排序即可（年月日等長）
    values = [c for _, c in closes]
    current = values[-1]
    current_date = closes[-1][0]

    def ma(n):
        if len(values) < n:
            return None
        return round2(sum(values[-n:]) / n)

    ma5, ma10, ma20 = ma(5), ma(10), ma(20)
    return {
        "current": round2(current),
        "date": current_date,  # 民國年格式 e.g. 115/07/07
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "above_ma5": (current >= ma5) if ma5 is not None else None,
        "above_ma10": (current >= ma10) if ma10 is not None else None,
        "above_ma20": (current >= ma20) if ma20 is not None else None,
        "samples": len(values),
    }


# ============================================================================
# d. 綜合燈號
# ============================================================================

def build_signal(us_indices, taifex_tx, taiex_ma):
    """
    綜合判定 green / yellow / red。

    採計偏多訊號（各 1 票）：
      - S&P 500 上漲
      - 費半 (SOX) 上漲
      - 台指期夜盤(盤後)上漲（夜盤缺失時不採計）
      - 加權指數站上 MA5
      - 加權指數站上 MA10
    可用訊號中偏多比例：
      - ratio >= 0.70 → 綠燈（環境偏多）
      - ratio <= 0.35 → 紅燈（環境偏空）
      - 其餘        → 黃燈（訊號分歧）
    保險：同時跌破 MA5 與 MA10 時，最高只給黃燈。
    """
    us_map = {x["key"]: x for x in us_indices}
    signals = []  # list of bools (True = 偏多)

    for key in ("^GSPC", "^SOX"):
        item = us_map.get(key)
        if item and item.get("changePct") is not None:
            signals.append(item["changePct"] > 0)

    night = (taifex_tx or {}).get("night")
    if night and night.get("changePct") is not None:
        signals.append(night["changePct"] > 0)

    above5 = above10 = None
    if taiex_ma:
        above5 = taiex_ma.get("above_ma5")
        above10 = taiex_ma.get("above_ma10")
        if above5 is not None:
            signals.append(bool(above5))
        if above10 is not None:
            signals.append(bool(above10))

    total = len(signals)
    bull = sum(1 for s in signals if s)
    ratio = (bull / total) if total else None

    if ratio is None:
        light = "yellow"
    elif ratio >= 0.70:
        light = "green"
    elif ratio <= 0.35:
        light = "red"
    else:
        light = "yellow"

    # 保險：同時跌破 MA5 與 MA10 → 不給綠燈
    if light == "green" and above5 is False and above10 is False:
        light = "yellow"

    labels = {
        "green": "環境偏多",
        "yellow": "訊號分歧",
        "red": "環境偏空",
    }
    messages = {
        "green": "多數參考訊號偏多，環境偏多；仍建議分批進場、嚴控部位。",
        "yellow": "參考訊號分歧，進場宜少量分批、控制部位並留意變盤。",
        "red": "多數參考訊號偏空，進場宜少量分批、控制部位並嚴設停損。",
    }
    return {
        "light": light,
        "label": labels[light],
        "message": messages[light],
        "bull": bull,
        "total": total,
    }


# ============================================================================
# 組裝 + 輸出
# ============================================================================

def build_market_context():
    log("building market context (盤前環境)")

    us_indices = []
    try:
        us_indices = get_us_indices()
        ok = sum(1 for x in us_indices if x.get("price") is not None)
        log(f"US indices: {ok}/{len(US_INDICES)}")
    except Exception as exc:  # noqa: BLE001
        log(f"US indices error: {exc}")

    taifex_tx = None
    try:
        taifex_tx = get_taifex_tx()
        log(f"TAIFEX TX: month={taifex_tx.get('contractMonth')}, "
            f"day={'ok' if taifex_tx.get('day') else 'miss'}, "
            f"night={'ok' if taifex_tx.get('night') else 'miss'}")
    except Exception as exc:  # noqa: BLE001
        log(f"TAIFEX error: {exc}")

    taiex_ma = None
    try:
        taiex_ma = get_taiex_ma()
        if taiex_ma:
            log(f"TAIEX MA: current={taiex_ma.get('current')}, "
                f"ma5={taiex_ma.get('ma5')}, ma10={taiex_ma.get('ma10')}, "
                f"ma20={taiex_ma.get('ma20')}, samples={taiex_ma.get('samples')}")
    except Exception as exc:  # noqa: BLE001
        log(f"TAIEX MA error: {exc}")

    signal = build_signal(us_indices, taifex_tx, taiex_ma)
    log(f"signal: {signal['light']} ({signal['label']}), bull={signal['bull']}/{signal['total']}")

    return {
        "schemaVersion": 1,
        "generatedAt": now_taipei().strftime("%Y-%m-%d %H:%M:%S %z"),
        "timezone": "Asia/Taipei",
        "usIndices": us_indices,
        "taifexTX": taifex_tx,
        "taiexMA": taiex_ma,
        "signal": signal,
        "disclaimer": DISCLAIMER,
    }


def write_market_context():
    payload = build_market_context()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    log(f"wrote {OUTPUT_PATH}")
    return payload


def main() -> int:
    try:
        write_market_context()
        return 0
    except Exception as exc:  # noqa: BLE001
        log(f"fatal: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
