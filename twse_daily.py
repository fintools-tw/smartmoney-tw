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

# 追蹤個股（代碼、名稱、市場）
WATCHLIST = [
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SmartMoneyTW/1.0; +https://github.com/fintools-tw/smartmoney-tw)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.twse.com.tw/",
}

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily.json")


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
# Analysis (rule-based; placeholder for future LLM upgrade)
# ============================================================================

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

    return {"date": today, "markdown": markdown}


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    log("starting daily snapshot")

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

    try:
        log("fetching institutional investors")
        institutional = get_institutional_investors()
        time.sleep(0.5)
    except Exception as exc:  # noqa: BLE001
        log(f"institutional error: {exc}")

    try:
        log("fetching watchlist quotes")
        quotes = get_stock_quotes(WATCHLIST)
    except Exception as exc:  # noqa: BLE001
        log(f"watchlist error: {exc}")

    analysis = build_analysis(index_quote, historical, institutional, quotes)

    payload = {
        "schemaVersion": 1,
        "generatedAt": now_taipei().strftime("%Y-%m-%d %H:%M:%S %z"),
        "timezone": "Asia/Taipei",
        "index": index_quote,
        "historicalIndex": historical,
        "institutional": institutional,
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
        f"institutional={'ok' if institutional and institutional.get('data') else 'miss'}, "
        f"watchlist={sum(1 for q in quotes if q.get('price') is not None)}/{len(WATCHLIST)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
