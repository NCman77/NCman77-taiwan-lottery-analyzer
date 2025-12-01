#!/usr/bin/env python3
"""
台灣彩券歷史資料初始化腳本
一次性抓取2025年1月到11月的完整歷史資料
"""

import requests
import json
import os
import time
from datetime import datetime
import pytz

TAIPEI_TZ = pytz.timezone('Asia/Taipei')

# API配置
API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"
GAMES = {
    "大樂透": "/Lotto649Result",
    "威力彩": "/SuperLotto638Result",
    # "今彩539": "/DailyCashResult"  # 暫時註解，等確認正確端點
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json'
}

def log(msg):
    print(f"[{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def fetch_month_data(game_name, api_path, year, month):
    """抓取單個月份的資料"""
    url = f"{API_BASE}{api_path}"
    params = {
        'month': f"{year}-{month:02d}",
        'pageNum': 1,
        'pageSize': 50
    }
    
    try:
        log(f"抓取 {game_name} {year}/{month:02d}...")
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("rtCode") == 0:
                # 尋找包含開獎資料的列表
                content = data.get("content", {})
                for key in content:
                    if isinstance(content[key], list):
                        return content[key]
        elif response.status_code == 404:
            log(f"  {game_name} {year}/{month:02d} 無資料")
        else:
            log(f"  {game_name} {year}/{month:02d} HTTP {response.status_code}")
            
    except Exception as e:
        log(f"  {game_name} {year}/{month:02d} 錯誤: {e}")
    
    return []

def parse_draw_data(raw_draw, game_name):
    """解析單筆開獎資料 - 使用正確的欄位"""
    try:
        # 正確的號碼欄位是 drawNumberSize
        numbers = raw_draw.get("drawNumberSize", [])
        if not numbers:
            return None
        
        # 根據遊戲類型提取正確數量的號碼
        if game_name == "大樂透":
            if len(numbers) >= 7:
                normal_numbers = sorted(numbers[:6])  # 前6個是普通號
                special_number = numbers[6]           # 第7個是特別號
                return {
                    "date": raw_draw.get("lotteryDate", "").split("T")[0],
                    "period": raw_draw.get("period", ""),
                    "numbers": normal_numbers,
                    "special": special_number
                }
        elif game_name == "威力彩":
            if len(numbers) >= 7:
                normal_numbers = sorted(numbers[:6])
                special_number = numbers[6]
                return {
                    "date": raw_draw.get("lotteryDate", "").split("T")[0],
                    "period": raw_draw.get("period", ""),
                    "numbers": normal_numbers,
                    "special": special_number
                }
        
    except Exception as e:
        log(f"解析錯誤: {e}")
    
    return None

def main():
    log("開始初始化台灣彩券歷史資料庫")
    
    all_data = {}
    
    # 抓取2025年1月到11月的資料
    for game_name, api_path in GAMES.items():
        log(f"處理遊戲: {game_name}")
        game_data = []
        
        for month in range(1, 12):  # 1月到11月
            raw_month_data = fetch_month_data(game_name, api_path, 2025, month)
            
            for raw_draw in raw_month_data:
                parsed = parse_draw_data(raw_draw, game_name)
                if parsed:
                    game_data.append(parsed)
            
            time.sleep(1)  # 尊重伺服器
        
        # 按日期排序（最新的在前面）
        game_data.sort(key=lambda x: x["date"], reverse=True)
        all_data[game_name] = game_data
        log(f"  {game_name}: 共 {len(game_data)} 筆")
    
    # 儲存資料
    os.makedirs("data", exist_ok=True)
    
    with open("data/lottery-data.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    # 儲存更新資訊
    update_info = {
        "last_updated": datetime.now(TAIPEI_TZ).isoformat(),
        "data_version": "1.0",
        "total_games": len(all_data),
        "total_records": sum(len(records) for records in all_data.values()),
        "note": "初始化資料：2025年1月-11月"
    }
    
    with open("data/update-info.json", "w", encoding="utf-8") as f:
        json.dump(update_info, f, ensure_ascii=False, indent=2)
    
    log("初始化完成！")
    log(f"總計: {update_info['total_records']} 筆開獎紀錄")
    
    # 顯示摘要
    for game_name, records in all_data.items():
        if records:
            latest = records[0]
            log(f"{game_name} 最新一期: {latest['date']} 號碼: {latest['numbers']}")

if __name__ == "__main__":
    main()
