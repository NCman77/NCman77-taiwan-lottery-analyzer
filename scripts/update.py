#!/usr/bin/env python3
"""
台灣彩券開獎資料自動更新腳本 - 增量API修正版
版本: 7.0
資料來源: 台灣彩券官方JSON API
功能: 每日增量更新開獎資料，首次執行會建立完整歷史資料庫
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

# 各遊戲的API端點配置
GAME_API_CONFIG = {
    "大樂透": {
        "api_path": "/Lotto649Result",
        "number_count": 6,
        "has_special": True
    },
    "威力彩": {
        "api_path": "/SuperLotto638Result",
        "number_count": 6,
        "has_special": True
    },
    # "今彩539": {  # 暫時註解，等確認正確API端點
    #     "api_path": "/DailyCashResult",
    #     "number_count": 5,
    #     "has_special": False
    # }
}

# 請求標頭
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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
    """
    從API原始資料解析開獎號碼
    關鍵：從 drawNumberSize 陣列提取正確號碼
    """
    try:
        # 提取開獎號碼陣列
        draw_numbers = raw_data.get("drawNumberSize", [])
        if not draw_numbers or len(draw_numbers) < game_config["number_count"]:
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
            "numbers": sorted(normal_numbers)  # 按數字大小排序
        }
        
        # 如果有特別號，單獨記錄
        if special_number is not None:
            result["special"] = special_number
        
        return result
        
    except Exception as e:
        log(f"解析單筆開獎資料時發生錯誤: {e}", "WARNING")
        return None

def get_months_to_fetch(latest_date: datetime) -> List[Tuple[int, int]]:
    """
    計算需要抓取的月份清單
    修正邏輯：從本地最新日期的「下一個月」開始，到「上個月」為止
    """
    today = datetime.now(TAIPEI_TZ)
    months_needed = []
    
    # 如果本地沒有任何有效資料，從2025年1月開始
    if latest_date.year <= 2000 or latest_date < datetime(2025, 1, 1).replace(tzinfo=TAIPEI_TZ):
        start_date = datetime(2025, 1, 1).replace(tzinfo=TAIPEI_TZ)
        log(f"初始狀態，從2025年1月開始抓取完整歷史資料", "INFO")
    else:
        # 從本地最新日期的「下一個月」開始
        if latest_date.month == 12:
            start_date = latest_date.replace(year=latest_date.year + 1, month=1, day=1)
        else:
            start_date = latest_date.replace(month=latest_date.month + 1, day=1)
    
    # 計算到「上個月」為止
    current = start_date.replace(day=1)
    end = today.replace(day=1)  # 當月第一天
    
    # 如果當前月份是1月，需要特殊處理
    if current > end:
        log(f"無需抓取新月份", "INFO")
        return months_needed
    
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
    
    # 解析API回應結構
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

def crawl_game_incrementally(game_name: str, existing_draws: List[Dict]) -> List[Dict]:
    """增量爬取指定遊戲的新資料"""
    log(f"開始增量爬取 {game_name}...", "INFO")
    
    # 找出本地最新日期
    latest_date = datetime.min.replace(tzinfo=TAIPEI_TZ)
    if existing_draws:
        try:
            latest_date_str = existing_draws[0]['date']
            latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').replace(tzinfo=TAIPEI_TZ)
            log(f"{game_name} 本地最新日期: {latest_date_str}", "INFO")
        except Exception as e:
            log(f"解析本地最新日期失敗: {e}", "WARNING")
    
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
        os.makedirs('data', exist_ok=True)
        
        # 儲存主要資料檔案
        with open('data/lottery-data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 儲存更新資訊
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '7.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys()),
            'note': '資料來源: 台灣彩券官方API (增量爬蟲)'
        }
        
        with open('data/update-info.json', 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        # 顯示摘要
        log("=" * 60, "INFO")
        log("📊 資料庫更新摘要", "INFO")
        log("=" * 60, "INFO")
        for game_name, draws in data.items():
            if draws:
                latest = draws[0]
                log(f"  {game_name}: {len(draws)} 筆，最新: {latest['date']} {latest['numbers']}", "INFO")
            else:
                log(f"  {game_name}: 0 筆", "INFO")
        
        log(f"總計: {update_info['total_records']} 筆開獎紀錄", "SUCCESS")
        log(f"更新時間: {update_info['last_updated'][:19]}", "INFO")
        
        return True
        
    except Exception as e:
        log(f"儲存資料失敗: {e}", "ERROR")
        return False

def initialize_if_empty() -> bool:
    """如果資料庫為空，初始化歷史資料"""
    data_file = 'data/lottery-data.json'
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 檢查是否有足夠的資料
            total_records = sum(len(records) for records in data.values())
            if total_records > 10:  # 如果有超過10筆資料，視為已初始化
                return False
        except:
            pass
    
    log("檢測到資料庫為空或資料不足，開始初始化...", "WARNING")
    
    # 手動初始化：抓取2025年1-11月資料
    all_data = {}
    today = datetime.now(TAIPEI_TZ)
    
    for game_name in GAME_API_CONFIG.keys():
        log(f"初始化 {game_name} 歷史資料...", "INFO")
        game_data = []
        
        # 抓取2025年1月到11月
        for month in range(1, 12):
            month_draws = fetch_game_month_data(game_name, 2025, month)
            if month_draws:
                game_data.extend(month_draws)
            time.sleep(1)
        
        if game_data:
            game_data.sort(key=lambda x: x['date'], reverse=True)
            all_data[game_name] = game_data
            log(f"  {game_name}: 初始化 {len(game_data)} 筆", "SUCCESS")
    
    if all_data:
        save_data(all_data)
        log("✅ 資料庫初始化完成！", "SUCCESS")
        return True
    
    return False

# ========== 主程式 ==========
def main():
    """主執行流程"""
    print("=" * 70)
    print("🎯 台灣彩券開獎資料自動更新系統 - 增量API修正版 v7.0")
    print("=" * 70)
    
    success = False
    
    try:
        # 0. 檢查並初始化資料庫（如果需要）
        initialize_if_empty()
        
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
