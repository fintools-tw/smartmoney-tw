#!/usr/bin/env python3
"""
台股每日追蹤器 — 自動抓取大盤、三大法人、熱門個股資料
輸出 JSON 供 AI 解讀用
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import time

# 熱門追蹤個股（代碼, 名稱, 市場）
WATCHLIST = [
    ("2330", "台積電", "tse"),
    ("2317", "鴻海", "tse"),
    ("2454", "聯發科", "tse"),
    ("2382", "廣達", "tse"),
    ("3443", "創意", "tse"),
    ("2603", "長榮", "tse"),
    ("00878", "國泰永續高股息", "tse"),
    ("00929", "復華台灣科技優息", "tse"),
    ("00940", "元大台灣價值高息", "tse"),
    ("6770", "力積電", "tse"),
    ("3661", "世芯-KY", "tse"),
    ("2615", "萬海", "tse"),
    ("2881", "富邦金", "tse"),
    ("2882", "國泰金", "tse"),
    ("2891", "中信金", "tse"),
    ("2886", "兆豐金", "tse"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
    "Referer": "https://www.twse.com.tw/",
}


def fetch_json(url, retries=2):
    """Fetch JSON from URL with retries."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt < retries:
                time.sleep(1)
            else:
                print(f"[WARN] Failed to fetch {url}: {e}", file=sys.stderr)
                return None


def get_market_index():
    """取得大盤加權指數（月統計裡抓最後一天）"""
    now = datetime.now()
    url = f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={now.strftime('%Y%m01')}"
    data = fetch_json(url)
    if not data or data.get("stat") != "OK" or not data.get("data"):
        # 試上個月
        prev = now.replace(day=1) - timedelta(days=1)
        url = f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={prev.strftime('%Y%m01')}"
        data = fetch_json(url)
    
    if data and data.get("stat") == "OK" and data.get("data"):
        last = data["data"][-1]
        # 民國年轉西元年
        date_str = last[0]  # e.g. "115/05/29"
        return {
            "date": date_str,
            "volume_shares": last[1],       # 成交股數
            "volume_amount": last[2],       # 成交金額
            "transactions": last[3],        # 成交筆數
            "index": last[4],              # 收盤指數
            "change": last[5],             # 漲跌
        }
    return None


def get_realtime_index():
    """取得即時大盤指數"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
    data = fetch_json(url)
    if data and data.get("msgArray"):
        d = data["msgArray"][0]
        return {
            "current": d.get("z", "-"),
            "yesterday_close": d.get("y", "-"),
            "open": d.get("o", "-"),
            "high": d.get("h", "-"),
            "low": d.get("l", "-"),
            "time": d.get("t", "-"),
            "date": d.get("d", "-"),
        }
    return None


def get_institutional_investors(date_str=None):
    """取得三大法人買賣超（只抓當天，不回溯舊資料）"""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    
    url = f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day"
    data = fetch_json(url)
    if data and data.get("stat") == "OK" and data.get("data"):
        result = {}
        for row in data["data"]:
            name = row[0].strip()
            buy = row[1].replace(",", "")
            sell = row[2].replace(",", "")
            net = row[3].replace(",", "")
            result[name] = {
                "buy": int(buy) if buy.lstrip("-").isdigit() else buy,
                "sell": int(sell) if sell.lstrip("-").isdigit() else sell,
                "net": int(net) if net.lstrip("-").isdigit() else net,
            }
        return {"date": date_str, "data": result}
    
    # 當天資料還沒出
    return {"date": date_str, "data": None, "note": "尚未公布，通常收盤後15:00更新"}


def get_stock_quotes(watchlist):
    """批量取得個股即時報價"""
    # 一次最多查 20 檔
    ex_ch = "|".join([f"{s[2]}_{s[0]}.tw" for s in watchlist])
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}"
    data = fetch_json(url)
    
    results = []
    if data and data.get("msgArray"):
        for d in data["msgArray"]:
            code = d.get("c", "")
            name = d.get("n", "")
            current = d.get("z", "-")
            yesterday = d.get("y", "-")
            open_p = d.get("o", "-")
            high = d.get("h", "-")
            low = d.get("l", "-")
            volume = d.get("v", "-")
            
            # 計算漲跌幅
            change_pct = "-"
            change_val = "-"
            if current not in ("-", "") and yesterday not in ("-", ""):
                try:
                    c = float(current)
                    y = float(yesterday)
                    change_val = round(c - y, 2)
                    change_pct = round((c - y) / y * 100, 2)
                except:
                    pass
            
            results.append({
                "code": code,
                "name": name,
                "price": current,
                "yesterday": yesterday,
                "open": open_p,
                "high": high,
                "low": low,
                "volume": volume,
                "change": change_val,
                "change_pct": change_pct,
            })
    
    return results


def get_top_volume(date_str=None):
    """取得成交量 Top 20（每日收盤）"""
    if not date_str:
        now = datetime.now()
        for i in range(7):
            d = now - timedelta(days=i)
            ds = d.strftime("%Y%m%d")
            url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={ds}&type=ALLBUT0999"
            data = fetch_json(url)
            if data and data.get("stat") == "OK":
                date_str = ds
                break
        else:
            return None
    
    # data1 欄位較多，先嘗試解析
    if data and "data1" in data:
        stocks = []
        for row in data["data1"][:30]:
            try:
                code = row[0].strip()
                name = row[1].strip()
                volume = int(row[2].replace(",", ""))
                close = row[8].strip() if len(row) > 8 else "-"
                change = row[9].strip() if len(row) > 9 else "-"
                change_val = row[10].strip() if len(row) > 10 else "-"
                stocks.append({
                    "code": code,
                    "name": name,
                    "volume": volume,
                    "close": close,
                    "change_dir": change,
                    "change_val": change_val,
                })
            except:
                continue
        # 按成交量排序
        stocks.sort(key=lambda x: x["volume"], reverse=True)
        return {"date": date_str, "top20": stocks[:20]}
    
    return None


def main():
    print("📊 台股每日追蹤器啟動...", file=sys.stderr)
    
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_index": None,
        "realtime_index": None,
        "institutional": None,
        "watchlist_quotes": None,
    }
    
    # 1. 大盤月統計（最近交易日收盤）
    print("  抓取大盤指數...", file=sys.stderr)
    result["market_index"] = get_market_index()
    
    # 2. 即時指數
    print("  抓取即時指數...", file=sys.stderr)
    result["realtime_index"] = get_realtime_index()
    
    # 3. 三大法人
    print("  抓取三大法人...", file=sys.stderr)
    result["institutional"] = get_institutional_investors()
    time.sleep(0.5)  # 禮貌延遲
    
    # 4. 追蹤個股報價
    print("  抓取個股報價...", file=sys.stderr)
    result["watchlist_quotes"] = get_stock_quotes(WATCHLIST)
    
    # 輸出 JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("✅ 完成", file=sys.stderr)


if __name__ == "__main__":
    main()
