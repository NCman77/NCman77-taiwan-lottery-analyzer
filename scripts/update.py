#!/usr/bin/env python3
"""
台灣彩券開獎資料自動更新腳本 - 增量API爬蟲版
版本: 5.0
資料來源: 台灣彩券官方 JSON API (https://api.taiwanlottery.com)
核心邏輯：透過官方API，只抓取本地資料庫缺少的最新月份資料。
"""

import requests
import json
import os
import re
from datetime import datetime, timedelta
import pytz
import time
import sys
from typing import Dict, List, Optional, Tuple

# ========== 配置區域 ==========
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
API_BASE_URL = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"

# 各遊戲的 API 端點路徑映射
GAME_API_MAP = {
    "大樂透": "/Lotto649Result",
    "威力彩": "/SuperLotto638Result",
    "今彩539": "/DailyCashResult",
    # 注意：其他遊戲的 API 路徑可能需要稍後確認
}

# 請求標頭，模擬瀏覽器
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

def parse_roc_date(date_str: str) -> Optional[datetime]:
    """解析民國日期字串 (例如：114/01/01) 為 datetime 物件"""
    try:
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3:
                year_roc = int(parts[0])
                year_ad = year_roc + 1911
                month = int(parts[1])
                day = int(parts[2])
                return datetime(year_ad, month, day).replace(tzinfo=TAIPEI_TZ)
    except Exception as e:
        log(f"日期解析失敗 '{date_str}': {e}", "WARNING")
    return None

def get_month_range(start_date: datetime, end_date: datetime) -> List[Tuple[int, int]]:
    """取得兩個日期之間的所有 (西元年, 月) 組合"""
    months = []
    current = start_date.replace(day=1)
    end = end_date.replace(day=1)
    
    while current <= end:
        months.append((current.year, current.month))
        # 下個月
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    return months

# ========== 核心 API 爬蟲函數 ==========
def fetch_game_month_data(game_name: str, year: int, month: int) -> Optional[List[Dict]]:
    """
    從官方API抓取指定遊戲、年份、月份的開獎資料
    
    API 範例: 
    - 大樂透: https://api.taiwanlottery.com/TLCAPIWeB/Lottery/Lotto649Result?month=2025-11&pageNum=1&pageSize=50
    - 威力彩: https://api.taiwanlottery.com/TLCAPIWeB/Lottery/SuperLotto638Result?month=2025-11&pageNum=1&pageSize=50
    - 今彩539: https://api.taiwanlottery.com/TLCAPIWeB/Lottery/DailyCashResult?month=2025-11&pageNum=1&pageSize=50
    """
    if game_name not in GAME_API_MAP:
        log(f"遊戲 '{game_name}' 的 API 端點未定義", "ERROR")
        return None
    
    api_path = GAME_API_MAP[game_name]
    api_url = f"{API_BASE_URL}{api_path}"
    
    # 構建查詢參數
    params = {
        'month': f"{year}-{month:02d}",  # 格式: 2025-11
        'pageNum': 1,
        'pageSize': 50  # 單月期數不會超過50
    }
    
    log(f"請求 {game_name} {year}/{month:02d} 資料...", "INFO")
    
    try:
        response = requests.get(api_url, headers=REQUEST_HEADERS, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # 檢查 API 回應結構
        if not isinstance(data, list):
            log(f"API 回應格式異常: {type(data)}", "WARNING")
            return None
        
        log(f"收到 {len(data)} 筆 {game_name} {year}/{month:02d} 的資料", "SUCCESS")
        return data
        
    except requests.exceptions.RequestException as e:
        log(f"API 請求失敗 {game_name} {year}/{month:02d}: {e}", "ERROR")
        return None
    except json.JSONDecodeError as e:
        log(f"JSON 解析失敗 {game_name}: {e}", "ERROR")
        return None

def parse_api_data(raw_data: List[Dict], game_name: str) -> List[Dict]:
    """
    解析 API 回傳的原始資料，轉換為標準格式
    
    標準格式: {'date': 'YYYY-MM-DD', 'numbers': [1, 2, 3, ...]}
    """
    parsed_draws = []
    
    for item in raw_data:
        try:
            # 提取開獎日期 - 優先嘗試各種可能的欄位名稱
            draw_date = None
            date_fields = ['drawDate', 'drawdate', 'date', 'drawDt', 'drawingDate']
            
            for field in date_fields:
                if field in item and item[field]:
                    draw_date = parse_roc_date(str(item[field]))
                    if draw_date:
                        break
            
            if not draw_date:
                log(f"無法解析開獎日期，跳過一筆資料: {item}", "WARNING")
                continue
            
            # 提取開獎號碼
            numbers = []
            
            # 嘗試不同遊戲的號碼欄位命名
            if game_name == "大樂透":
                # 大樂透可能有6個普通號 + 1個特別號
                for i in range(1, 7):
                    num_field = f'normalNum{i}'
                    if num_field in item and item[num_field]:
                        try:
                            num = int(item[num_field])
                            if 1 <= num <= 49:
                                numbers.append(num)
                        except (ValueError, TypeError):
                            pass
                
                # 特別號 (僅記錄，不加入主號碼陣列)
                special_num = None
                if 'specialNum' in item and item['specialNum']:
                    try:
                        special_num = int(item['specialNum'])
                    except (ValueError, TypeError):
                        pass
            
            elif game_name == "威力彩":
                # 威力彩: 6個主號 + 1個第二區號碼
                for i in range(1, 7):
                    num_field = f'num{i}'
                    if num_field in item and item[num_field]:
                        try:
                            num = int(item[num_field])
                            if 1 <= num <= 38:  # 威力彩第一區範圍
                                numbers.append(num)
                        except (ValueError, TypeError):
                            pass
            
            elif game_name == "今彩539":
                # 今彩539: 5個號碼
                for i in range(1, 6):
                    num_field = f'num{i}'
                    if num_field in item and item[num_field]:
                        try:
                            num = int(item[num_field])
                            if 1 <= num <= 39:
                                numbers.append(num)
                        except (ValueError, TypeError):
                            pass
            
            # 如果以上特定邏輯沒抓到，嘗試通用方法
            if not numbers:
                # 遍歷所有欄位，尋找數值型態的號碼
                for key, value in item.items():
                    if isinstance(value, (int, float)) and 1 <= value <= 99:
                        numbers.append(int(value))
                    elif isinstance(value, str) and value.isdigit():
                        num = int(value)
                        if 1 <= num <= 99:
                            numbers.append(num)
            
            # 排序並移除重複
            numbers = sorted(list(set(numbers)))
            
            if numbers:
                parsed_draws.append({
                    'date': draw_date.strftime('%Y-%m-%d'),
                    'numbers': numbers,
                    'raw_data': item  # 保留原始資料以供除錯
                })
            else:
                log(f"無法提取有效號碼，跳過一筆: {item}", "WARNING")
                
        except Exception as e:
            log(f"解析單筆資料時發生錯誤: {e}", "WARNING")
            continue
    
    return parsed_draws

def crawl_game_data(game_name: str, latest_existing_date: datetime) -> List[Dict]:
    """
    增量爬取指定遊戲的新資料
    """
    log(f"開始增量爬取 {game_name}...", "INFO")
    
    all_new_draws = []
    today = datetime.now(TAIPEI_TZ)
    
    # 如果本地沒有任何資料，預設從3個月前開始抓取
    if latest_existing_date.year == 1:  # datetime.min 的年份
        start_date = today - timedelta(days=90)
        log(f"{game_name} 無本地資料，從 {start_date.strftime('%Y-%m')} 開始抓取", "INFO")
    else:
        start_date = latest_existing_date
        log(f"{game_name} 本地最新日期: {start_date.strftime('%Y-%m-%d')}", "INFO")
    
    # 計算需要抓取的月份範圍 (從 start_date 的月份到當月)
    months_to_fetch = get_month_range(start_date, today)
    
    if not months_to_fetch:
        log(f"{game_name} 無需抓取新月份", "INFO")
        return all_new_draws
    
    log(f"{game_name} 需要抓取 {len(months_to_fetch)} 個月份", "INFO")
    
    for year, month in months_to_fetch:
        # 從API抓取該月份資料
        raw_month_data = fetch_game_month_data(game_name, year, month)
        
        if raw_month_data:
            # 解析資料
            parsed_draws = parse_api_data(raw_month_data, game_name)
            
            # 過濾掉日期早於或等於 latest_existing_date 的資料
            new_draws = []
            for draw in parsed_draws:
                draw_date = datetime.strptime(draw['date'], '%Y-%m-%d').replace(tzinfo=TAIPEI_TZ)
                if draw_date > latest_existing_date:
                    new_draws.append(draw)
            
            if new_draws:
                all_new_draws.extend(new_draws)
                log(f"{game_name} {year}/{month:02d} 新增 {len(new_draws)} 筆資料", "SUCCESS")
            else:
                log(f"{game_name} {year}/{month:02d} 無新資料", "INFO")
        
        # 避免請求過於頻繁
        time.sleep(0.5)
    
    return all_new_draws

# ========== 資料管理函數 ==========
def load_existing_data() -> Dict:
    """載入現有的資料庫"""
    data_file = 'data/lottery-data.json'
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            log(f"成功載入現有資料: {len(data)} 種遊戲", "INFO")
            return data
        except Exception as e:
            log(f"載入現有資料失敗: {e}", "WARNING")
    
    return {}

def get_latest_date_for_game(game_data: List[Dict]) -> datetime:
    """取得某遊戲資料中最新的開獎日期"""
    if not game_data:
        return datetime.min.replace(tzinfo=TAIPEI_TZ)
    
    try:
        # 資料應該已經按日期倒序排列
        latest_date_str = game_data[0]['date']
        return datetime.strptime(latest_date_str, '%Y-%m-%d').replace(tzinfo=TAIPEI_TZ)
    except Exception as e:
        log(f"解析最新日期失敗: {e}", "WARNING")
        return datetime.min.replace(tzinfo=TAIPEI_TZ)

def merge_new_data(existing_data: Dict, new_data: Dict) -> Tuple[Dict, int]:
    """
    合併新舊資料，返回 (合併後的資料, 新增筆數)
    """
    merged = existing_data.copy()
    total_new = 0
    
    for game_name, new_draws in new_data.items():
        if not new_draws:
            continue
            
        if game_name not in merged:
            merged[game_name] = []
        
        # 建立現有資料的日期集合以供快速查詢
        existing_dates = set(draw['date'] for draw in merged[game_name])
        
        # 只加入不重複的新資料
        added_draws = []
        for draw in new_draws:
            if draw['date'] not in existing_dates:
                added_draws.append(draw)
        
        if added_draws:
            merged[game_name].extend(added_draws)
            # 按日期倒序排列
            merged[game_name].sort(key=lambda x: x['date'], reverse=True)
            total_new += len(added_draws)
            log(f"遊戲 {game_name} 新增 {len(added_draws)} 筆資料", "SUCCESS")
    
    return merged, total_new

def save_data(data: Dict) -> bool:
    """儲存資料到檔案"""
    try:
        os.makedirs('data', exist_ok=True)
        
        # 儲存主要資料
        with open('data/lottery-data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 儲存更新資訊
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '5.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys()),
            'note': '資料來源: 台灣彩券官方API (增量爬蟲)'
        }
        
        with open('data/update-info.json', 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        log(f"資料儲存完成: {len(data)} 種遊戲, {update_info['total_records']} 筆紀錄", "SUCCESS")
        
        # 顯示各遊戲資料筆數
        for game_name, records in data.items():
            log(f"  {game_name}: {len(records)} 筆", "INFO")
        
        return True
        
    except Exception as e:
        log(f"儲存資料失敗: {e}", "ERROR")
        return False

# ========== 主程式 ==========
def main():
    """主程式 - 增量爬蟲流程"""
    print("=" * 70)
    print("台灣彩券開獎資料自動更新系統 - 增量API爬蟲版 v5.0")
    print("=" * 70)
    
    success = False
    
    try:
        # 1. 載入現有資料
        existing_data = load_existing_data()
        
        # 2. 對每種遊戲進行增量爬取
        all_new_data = {}
        
        for game_name in GAME_API_MAP.keys():
            # 取得該遊戲現有最新日期
            if game_name in existing_data:
                latest_date = get_latest_date_for_game(existing_data[game_name])
            else:
                latest_date = datetime.min.replace(tzinfo=TAIPEI_TZ)
                existing_data[game_name] = []
            
            # 爬取新資料
            new_draws = crawl_game_data(game_name, latest_date)
            
            if new_draws:
                all_new_data[game_name] = new_draws
        
        # 3. 合併資料
        if all_new_data:
            merged_data, total_new = merge_new_data(existing_data, all_new_data)
            
            # 4. 儲存更新
            if save_data(merged_data):
                log(f"✅ 增量更新成功！本次共新增 {total_new} 筆開獎紀錄。", "SUCCESS")
                success = True
            else:
                log("❌ 資料儲存失敗", "ERROR")
        else:
            log("ℹ️ 所有遊戲均無新資料，資料庫已是最新狀態。", "INFO")
            success = True  # 無新資料也是成功狀態
            
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
