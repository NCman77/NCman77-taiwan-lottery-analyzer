#!/usr/bin/env python3
"""
台灣彩券開獎資料更新腳本 - API增量更新版本
版本: 2.1
功能: 從台灣彩券官方API抓取最新開獎資料
"""

import requests
import os
import sys
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from common import (
    log, load_existing_data, merge_and_deduplicate, 
    save_data, check_data_coverage, GAME_API_CONFIG,
    TAIPEI_TZ
)
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ========== 配置區域 ==========
API_BASE_URL = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"

# 請求標頭
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Origin': 'https://www.taiwanlottery.com',
    'Referer': 'https://www.taiwanlottery.com/',
}

# ========== API相關函數 ==========
def safe_api_request(url: str, params: Dict, max_retries: int = 3) -> Optional[Dict]:
    """安全的API請求函數，包含重試機制"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, params=params, timeout=15)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                log(f"API資源不存在: {url}", "WARNING")
                return None
            else:
                log(f"API請求失敗 (狀態碼 {response.status_code})，第 {attempt+1} 次重試", "WARNING")
                
        except requests.exceptions.RequestException as e:
            log(f"網路請求異常: {e}，第 {attempt+1} 次重試", "WARNING")
        
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)
    
    log(f"API請求最終失敗: {url}", "ERROR")
    return None

def parse_draw_numbers(raw_data: Dict, game_config: Dict) -> Optional[Dict]:
    """從API原始資料解析開獎號碼"""
    try:
        # 提取開獎號碼陣列
        draw_numbers = raw_data.get("drawNumberSize", [])
        if not draw_numbers or len(draw_numbers) < game_config["number_count"]:
            return None
        
        # 提取普通號碼
        normal_numbers = draw_numbers[:game_config["number_count"]]
        
        # 提取特別號
        special_number = None
        if game_config["has_special"] and len(draw_numbers) > game_config["number_count"]:
            special_number = draw_numbers[game_config["number_count"]]
        
        # 解析開獎日期
        lottery_date = raw_data.get("lotteryDate", "")
        if not lottery_date:
            return None
        
        # 轉換日期格式
        try:
            date_obj = datetime.fromisoformat(lottery_date.replace('Z', '+00:00'))
            formatted_date = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            return None
        
        # 建構標準化資料
        result = {
            "date": formatted_date,
            "period": raw_data.get("period", ""),
            "numbers": sorted(normal_numbers)
        }
        
        if special_number is not None:
            result["special"] = special_number
        
        return result
        
    except Exception as e:
        log(f"解析單筆開獎資料時發生錯誤: {e}", "WARNING")
        return None

def fetch_game_month_data(game_name: str, year: int, month: int) -> List[Dict]:
    """抓取指定遊戲、年份、月份的開獎資料"""
    if game_name not in GAME_API_CONFIG:
        log(f"遊戲 '{game_name}' 未配置API", "ERROR")
        return []
    
    config = GAME_API_CONFIG[game_name]
    
    # 檢查是否有API端點
    if not config.get("api_path"):
        log(f"遊戲 '{game_name}' 沒有API端點", "INFO")
        return []
    
    api_url = f"{API_BASE_URL}{config['api_path']}"
    
    params = {
        'month': f"{year}-{month:02d}",
        'pageNum': 1,
        'pageSize': 50
    }
    
    log(f"抓取 {game_name} {year}/{month:02d} 資料...", "INFO")
    
    # 發送API請求
    response_data = safe_api_request(api_url, params)
    if not response_data:
        return []
    
    # 解析API回應
    try:
        if response_data.get("rtCode") != 0:
            return []
        
        content = response_data.get("content", {})
        draws_key = None
        
        # 尋找包含開獎資料的欄位
        for key in content:
            if isinstance(content[key], list):
                draws_key = key
                break
        
        if not draws_key:
            return []
        
        draw_list = content[draws_key]
        
        # 解析每一期開獎資料
        parsed_draws = []
        for raw_draw in draw_list:
            parsed = parse_draw_numbers(raw_draw, config)
            if parsed:
                parsed_draws.append(parsed)
        
        if parsed_draws:
            log(f"{game_name} {year}/{month:02d} 成功解析 {len(parsed_draws)} 筆資料", "SUCCESS")
        
        return parsed_draws
        
    except Exception as e:
        log(f"解析API回應時發生錯誤: {e}", "ERROR")
        return []

def get_months_to_fetch(latest_date: datetime) -> List[Tuple[int, int]]:
    """
    計算需要抓取的月份清單
    從本地最新日期的「下一個月」開始，到「當前月份」為止
    """
    today = datetime.now(TAIPEI_TZ)
    months_needed = []
    
    # 如果本地沒有任何有效資料，從2025年9月開始（API可用的起始月份）
    if latest_date.year <= 2000:
        # API從2025年9月23日開始有資料
        start_date = datetime(2025, 9, 1).replace(tzinfo=TAIPEI_TZ)
        log(f"本地無有效資料，從2025年9月開始抓取", "INFO")
    else:
        # 從本地最新日期的「下一個月」開始
        if latest_date.month == 12:
            start_date = latest_date.replace(year=latest_date.year + 1, month=1, day=1)
        else:
            start_date = latest_date.replace(month=latest_date.month + 1, day=1)
    
    # 計算到「當前月份」為止
    current = start_date.replace(day=1)
    end = today.replace(day=1)  # 當前月份的第一天
    
    # 如果起始月份已經在結束月份之後，則無需抓取
    if current > end:
        log(f"無需抓取新月份（本地已是最新）", "INFO")
        return months_needed
    
    while current <= end:
        months_needed.append((current.year, current.month))
        
        # 計算下個月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    return months_needed

def crawl_game_incrementally(game_name: str, existing_draws: List[Dict]) -> List[Dict]:
    """增量爬取指定遊戲的新資料"""
    log(f"開始增量爬取 {game_name}...", "INFO")
    
    # 找出本地最新日期
    latest_date = datetime.min.replace(tzinfo=TAIPEI_TZ)
    if existing_draws:
        try:
            # 假設資料是按日期倒序排列的，最新的一筆在第一個
            latest_date_str = existing_draws[-1]['date']  # 因為是正序，最新在最後
            latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').replace(tzinfo=TAIPEI_TZ)
            log(f"{game_name} 本地最新日期: {latest_date_str}", "INFO")
        except Exception as e:
            log(f"解析本地最新日期失敗: {e}，將從頭抓取", "WARNING")
            latest_date = datetime.min.replace(tzinfo=TAIPEI_TZ)
    
    # 計算需要抓取的月份
    months_to_fetch = get_months_to_fetch(latest_date)
    
    if not months_to_fetch:
        log(f"{game_name} 無需抓取新月份", "INFO")
        return []
    
    log(f"{game_name} 需要抓取 {len(months_to_fetch)} 個月份: {months_to_fetch}", "INFO")
    
    # 抓取每個月份的資料
    all_new_draws = []
    for year, month in months_to_fetch:
        month_draws = fetch_game_month_data(game_name, year, month)
        
        # 過濾掉可能重複的資料
        existing_dates = set(d['date'] for d in existing_draws)
        new_in_month = []
        
        for draw in month_draws:
            if draw['date'] not in existing_dates:
                new_in_month.append(draw)
        
        if new_in_month:
            all_new_draws.extend(new_in_month)
            log(f"{game_name} {year}/{month:02d} 新增 {len(new_in_month)} 筆", "SUCCESS")
        elif month_draws:
            log(f"{game_name} {year}/{month:02d} 無新資料（已存在）", "INFO")
        else:
            log(f"{game_name} {year}/{month:02d} 無資料", "INFO")
        
        # 尊重伺服器，避免請求過於頻繁
        time.sleep(1)
    
    return all_new_draws

def main():
    """主執行流程"""
    print("=" * 70)
    print("🎯 台灣彩券開獎資料增量更新系統")
    print("📅 功能: 從API自動抓取最新開獎資料")
    print("=" * 70)
    
    success = False
    
    try:
        # 載入現有資料庫
        existing_data = load_existing_data()
        
        # 檢查資料覆蓋範圍
        check_data_coverage(existing_data)
        
        # 增量爬取各遊戲新資料
        all_new_data = {}
        
        for game_name in GAME_API_CONFIG.keys():
            # 只處理有API的遊戲
            if GAME_API_CONFIG[game_name].get("api_path"):
                existing_draws = existing_data.get(game_name, [])
                new_draws = crawl_game_incrementally(game_name, existing_draws)
                
                if new_draws:
                    all_new_data[game_name] = new_draws
            else:
                log(f"{game_name} 沒有API端點，跳過增量更新", "INFO")
        
        # 合併與儲存
        if all_new_data:
            merged_data, total_added = merge_and_deduplicate(existing_data, all_new_data)
            
            if save_data(merged_data):
                log(f"✅ 增量更新成功完成！本次新增 {total_added} 筆開獎紀錄。", "SUCCESS")
                success = True
            else:
                log("❌ 資料儲存失敗，但新資料已抓取完成", "ERROR")
        else:
            log("ℹ️ 所有遊戲均無新資料，資料庫已是最新狀態。", "INFO")
            # 即使無新資料，也更新時間戳記
            if save_data(existing_data):
                success = True
            
    except KeyboardInterrupt:
        log("程式被使用者中斷", "WARNING")
    except Exception as e:
        log(f"程式執行發生未預期錯誤: {e}", "ERROR")
        import traceback
        traceback.print_exc()
    
    print("=" * 70)
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
