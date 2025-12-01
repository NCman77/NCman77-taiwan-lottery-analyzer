#!/usr/bin/env python3
"""
台灣彩券開獎資料自動更新腳本 - 增量API正式版
版本: 6.0
資料來源: 台灣彩券官方JSON API (https://api.taiwanlottery.com)
核心功能：透過官方API按月查詢，只增量抓取本地缺少的最新月份開獎資料。
"""

import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pytz

# ========== 配置區域 ==========
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
API_BASE_URL = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"

# 各遊戲的API端點配置 (根據您提供的網址格式)
GAME_API_CONFIG = {
    "大樂透": {
        "api_path": "/Lotto649Result",
        "number_count": 6,  # 普通號數量
        "has_special": True  # 是否有特別號
    },
    "威力彩": {
        "api_path": "/SuperLotto638Result",
        "number_count": 6,
        "has_special": True
    },
    "今彩539": {
        "api_path": "/DailyCashResult", 
        "number_count": 5,
        "has_special": False
    }
}

# 請求標頭 (模擬瀏覽器行為，避免被阻擋)
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Origin': 'https://www.taiwanlottery.com',
    'Referer': 'https://www.taiwanlottery.com/',
}

# ========== 工具函數 ==========
def log(message: str, level: str = "INFO"):
    """統一日誌輸出函數"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}
    icon = icons.get(level, "ℹ️")
    print(f"[{timestamp}] {icon} {message}")

def safe_request(url: str, params: Dict, max_retries: int = 3) -> Optional[Dict]:
    """安全的API請求函數，包含重試機制"""
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, 
                headers=REQUEST_HEADERS, 
                params=params, 
                timeout=15
            )
            
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
            time.sleep(2 ** attempt)  # 指數退避
    
    log(f"API請求最終失敗: {url}", "ERROR")
    return None

def parse_draw_numbers(raw_data: Dict, game_config: Dict) -> Optional[Dict]:
    """
    從API原始資料解析開獎號碼
    關鍵邏輯：從 drawNumberSize 陣列提取正確的號碼
    """
    try:
        # 提取開獎號碼陣列 (根據您提供的真實資料結構)
        draw_numbers = raw_data.get("drawNumberSize", [])
        if not draw_numbers or len(draw_numbers) < game_config["number_count"]:
            log(f"號碼數據異常: {raw_data.get('period', '未知期別')}", "WARNING")
            return None
        
        # 提取普通號碼 (前N個數字)
        normal_numbers = draw_numbers[:game_config["number_count"]]
        
        # 提取特別號 (如果該遊戲有)
        special_number = None
        if game_config["has_special"] and len(draw_numbers) > game_config["number_count"]:
            special_number = draw_numbers[game_config["number_count"]]
        
        # 解析開獎日期
        lottery_date = raw_data.get("lotteryDate", "")
        if not lottery_date:
            log(f"缺少開獎日期: {raw_data.get('period', '未知期別')}", "WARNING")
            return None
        
        # 轉換日期格式: ISO格式 -> YYYY-MM-DD
        try:
            date_obj = datetime.fromisoformat(lottery_date.replace('Z', '+00:00'))
            formatted_date = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            log(f"日期格式異常: {lottery_date}", "WARNING")
            return None
        
        # 建構標準化資料
        result = {
            "date": formatted_date,
            "period": raw_data.get("period", ""),
            "numbers": sorted(normal_numbers)  # 按數字大小排序
        }
        
        # 如果有特別號，單獨記錄
        if special_number is not None:
            result["special"] = special_number
        
        return result
        
    except Exception as e:
        log(f"解析單筆開獎資料時發生錯誤: {e}", "ERROR")
        return None

def get_months_to_fetch(latest_date: datetime, months_back: int = 3) -> List[Tuple[int, int]]:
    """
    計算需要抓取的月份清單
    :param latest_date: 本地最新資料的日期
    :param months_back: 最多往回抓幾個月 (預設3個月)
    :return: 西元年、月的元組列表 [(2025, 11), (2025, 12), ...]
    """
    today = datetime.now(TAIPEI_TZ)
    months_needed = []
    
    # 如果沒有任何本地資料，從指定月數前開始
    if latest_date.year == 1:  # datetime.min
        start_date = today - timedelta(days=30 * months_back)
    else:
        start_date = latest_date
    
    # 從start_date的月份開始，到當月為止
    current = start_date.replace(day=1)
    end = today.replace(day=1)
    
    while current <= end:
        months_needed.append((current.year, current.month))
        
        # 計算下個月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    return months_needed

# ========== 核心爬蟲函數 ==========
def fetch_game_month_data(game_name: str, year: int, month: int) -> List[Dict]:
    """抓取指定遊戲、年份、月份的開獎資料"""
    if game_name not in GAME_API_CONFIG:
        log(f"遊戲 '{game_name}' 未配置API", "ERROR")
        return []
    
    config = GAME_API_CONFIG[game_name]
    api_url = f"{API_BASE_URL}{config['api_path']}"
    
    # API查詢參數 (根據您提供的網址格式)
    params = {
        'month': f"{year}-{month:02d}",
        'pageNum': 1,
        'pageSize': 50  # 單月期數不會超過50
    }
    
    log(f"抓取 {game_name} {year}/{month:02d} 資料...", "INFO")
    
    # 發送API請求
    response_data = safe_request(api_url, params)
    if not response_data:
        return []
    
    # 解析API回應結構 (根據真實資料格式)
    try:
        if response_data.get("rtCode") != 0:
            log(f"API回傳錯誤: {response_data.get('rtMsg', '未知錯誤')}", "WARNING")
            return []
        
        # 提取開獎列表 (不同遊戲的欄位名稱可能不同)
        content = response_data.get("content", {})
        draws_key = None
        
        # 尋找包含開獎資料的欄位
        for key in content:
            if isinstance(content[key], list):
                draws_key = key
                break
        
        if not draws_key:
            log(f"找不到開獎資料列表欄位", "WARNING")
            return []
        
        draw_list = content[draws_key]
        
        # 解析每一期開獎資料
        parsed_draws = []
        for raw_draw in draw_list:
            parsed = parse_draw_numbers(raw_draw, config)
            if parsed:
                parsed_draws.append(parsed)
        
        log(f"{game_name} {year}/{month:02d} 成功解析 {len(parsed_draws)} 筆資料", "SUCCESS")
        return parsed_draws
        
    except Exception as e:
        log(f"解析API回應時發生錯誤: {e}", "ERROR")
        return []

def crawl_game_incrementally(game_name: str, existing_draws: List[Dict]) -> List[Dict]:
    """增量爬取指定遊戲的新資料"""
    log(f"開始增量爬取 {game_name}...", "INFO")
    
    # 找出本地最新日期
    latest_date = datetime.min.replace(tzinfo=TAIPEI_TZ)
    if existing_draws:
        try:
            latest_date_str = existing_draws[0]['date']  # 資料已按日期倒序排列
            latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').replace(tzinfo=TAIPEI_TZ)
            log(f"{game_name} 本地最新日期: {latest_date_str}", "INFO")
        except Exception as e:
            log(f"解析本地最新日期失敗: {e}", "WARNING")
    
    # 計算需要抓取的月份
    months_to_fetch = get_months_to_fetch(latest_date)
    
    if not months_to_fetch:
        log(f"{game_name} 無需抓取新月份", "INFO")
        return []
    
    log(f"{game_name} 需要抓取 {len(months_to_fetch)} 個月份", "INFO")
    
    # 抓取每個月份的資料
    all_new_draws = []
    for year, month in months_to_fetch:
        month_draws = fetch_game_month_data(game_name, year, month)
        
        # 過濾掉日期早於或等於最新日期的資料
        new_in_month = []
        for draw in month_draws:
            draw_date = datetime.strptime(draw['date'], '%Y-%m-%d').replace(tzinfo=TAIPEI_TZ)
            if draw_date > latest_date:
                new_in_month.append(draw)
        
        if new_in_month:
            all_new_draws.extend(new_in_month)
            log(f"{game_name} {year}/{month:02d} 新增 {len(new_in_month)} 筆", "SUCCESS")
        
        # 避免請求過於頻繁 (尊重伺服器)
        time.sleep(1)
    
    return all_new_draws

# ========== 資料管理函數 ==========
def load_existing_data() -> Dict:
    """載入現有的JSON資料庫"""
    data_file = 'data/lottery-data.json'
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 確保資料按日期倒序排列
            for game in data.values():
                if game:
                    game.sort(key=lambda x: x['date'], reverse=True)
            
            total_records = sum(len(records) for records in data.values())
            log(f"載入現有資料庫: {len(data)} 種遊戲, {total_records} 筆紀錄", "INFO")
            return data
        except Exception as e:
            log(f"載入現有資料失敗: {e}", "WARNING")
    
    log("無現有資料庫，將建立新的", "INFO")
    return {game_name: [] for game_name in GAME_API_CONFIG}

def merge_and_deduplicate(existing: Dict, new_data: Dict) -> Tuple[Dict, int]:
    """合併新舊資料並去除重複"""
    merged = {game: draws.copy() for game, draws in existing.items()}
    total_added = 0
    
    for game_name, new_draws in new_data.items():
        if not new_draws:
            continue
        
        if game_name not in merged:
            merged[game_name] = []
        
        # 建立現有期別集合以供快速查重
        existing_periods = set(draw.get('period', '') for draw in merged[game_name])
        
        # 只加入不重複的新資料
        added_count = 0
        for draw in new_draws:
            if draw.get('period', '') not in existing_periods:
                merged[game_name].append(draw)
                existing_periods.add(draw.get('period', ''))
                added_count += 1
        
        if added_count:
            # 按日期重新排序
            merged[game_name].sort(key=lambda x: x['date'], reverse=True)
            total_added += added_count
            log(f"遊戲 {game_name} 合併 {added_count} 筆新資料", "SUCCESS")
    
    return merged, total_added

def save_data(data: Dict) -> bool:
    """儲存資料到檔案系統"""
    try:
        # 確保資料目錄存在
        os.makedirs('data', exist_ok=True)
        
        # 儲存主要資料檔案
        data_file = 'data/lottery-data.json'
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 儲存更新資訊
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '6.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys()),
            'data_source': '台灣彩券官方API (https://api.taiwanlottery.com)',
            'note': '此資料僅供個人研究參考，請以台灣彩券官方公布為準'
        }
        
        info_file = 'data/update-info.json'
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        # 顯示摘要
        log("=" * 60, "INFO")
        log("📊 資料庫更新摘要", "INFO")
        log("=" * 60, "INFO")
        for game_name, draws in data.items():
            log(f"  {game_name}: {len(draws)} 筆", "INFO")
        log(f"總計: {update_info['total_records']} 筆開獎紀錄", "SUCCESS")
        log(f"更新時間: {update_info['last_updated']}", "INFO")
        
        return True
        
    except Exception as e:
        log(f"儲存資料失敗: {e}", "ERROR")
        return False

# ========== 主程式 ==========
def main():
    """主執行流程"""
    print("=" * 70)
    print("🎯 台灣彩券開獎資料自動更新系統 - 增量API正式版 v6.0")
    print("=" * 70)
    
    success = False
    
    try:
        # 1. 載入現有資料庫
        existing_data = load_existing_data()
        
        # 2. 增量爬取各遊戲新資料
        all_new_data = {}
        
        for game_name in GAME_API_CONFIG.keys():
            existing_draws = existing_data.get(game_name, [])
            new_draws = crawl_game_incrementally(game_name, existing_draws)
            
            if new_draws:
                all_new_data[game_name] = new_draws
        
        # 3. 合併與儲存
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
