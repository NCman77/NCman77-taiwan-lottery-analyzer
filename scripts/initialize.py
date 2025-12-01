#!/usr/bin/env python3
"""
台灣彩券開獎資料自動更新系統 - 手動+API混合版
版本: 1.0
功能: 
1. 支援手動匯入歷史資料(2025年1月-9月)
2. 使用API抓取最新資料(9月23日以後)
3. 自動增量更新未來開獎資料
"""

import requests
import json
import os
import sys
import time
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
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
    "今彩539": {
        "api_path": "/DailyCashResult",
        "number_count": 5,
        "has_special": False
    }
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
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌", "IMPORT": "📥"}
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

# ========== 資料轉換函數 ==========
def convert_csv_to_json_format(csv_file_path: str, game_type: str) -> List[Dict]:
    """
    將CSV格式的歷史資料轉換為標準JSON格式
    支援多種可能的CSV格式
    """
    standard_data = []
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8-sig') as f:
            # 嘗試檢測CSV分隔符號
            sample = f.read(1024)
            f.seek(0)
            
            if ',' in sample:
                delimiter = ','
            elif ';' in sample:
                delimiter = ';'
            elif '\t' in sample:
                delimiter = '\t'
            else:
                delimiter = ','
            
            # 讀取CSV
            reader = csv.DictReader(f, delimiter=delimiter)
            rows = list(reader)
            
            if not rows:
                log(f"CSV檔案為空: {csv_file_path}", "WARNING")
                return []
            
            log(f"CSV欄位: {reader.fieldnames}", "INFO")
            
            # 根據不同CSV格式處理
            for row in rows:
                try:
                    # 嘗試解析日期 (支援多種日期格式)
                    date_str = None
                    if "開獎日期" in row and row["開獎日期"]:
                        date_str = row["開獎日期"].strip()
                    elif "日期" in row and row["日期"]:
                        date_str = row["日期"].strip()
                    elif "date" in row and row["date"]:
                        date_str = row["date"].strip()
                    
                    if not date_str:
                        continue
                    
                    # 轉換日期格式為 YYYY-MM-DD
                    date_formats = [
                        "%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日",
                        "%m/%d/%Y", "%d/%m/%Y"
                    ]
                    
                    parsed_date = None
                    for fmt in date_formats:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
                    
                    if not parsed_date:
                        log(f"無法解析日期: {date_str}", "WARNING")
                        continue
                    
                    formatted_date = parsed_date.strftime("%Y-%m-%d")
                    
                    # 檢查是否為2025年的資料
                    if parsed_date.year != 2025:
                        log(f"忽略非2025年資料: {formatted_date}", "INFO")
                        continue
                    
                    # 解析期號
                    period = ""
                    if "期別" in row and row["期別"]:
                        period = row["期別"].strip()
                    elif "期號" in row and row["期號"]:
                        period = row["期號"].strip()
                    elif "period" in row and row["period"]:
                        period = row["period"].strip()
                    elif "期數" in row and row["期數"]:
                        period = row["期數"].strip()
                    
                    # 解析號碼
                    numbers = []
                    special = None
                    
                    if game_type == "大樂透":
                        # 大樂透: 6個普通號 + 1個特別號
                        for i in range(1, 7):
                            col_name = f"號碼{i}" if f"號碼{i}" in row else f"num{i}"
                            if col_name in row and row[col_name]:
                                try:
                                    num = int(float(row[col_name]))
                                    if 1 <= num <= 49:
                                        numbers.append(num)
                                except:
                                    pass
                        
                        # 特別號
                        special_cols = ["特別號", "特別", "special", "特別獎"]
                        for col in special_cols:
                            if col in row and row[col]:
                                try:
                                    special = int(float(row[col]))
                                    break
                                except:
                                    pass
                    
                    elif game_type == "威力彩":
                        # 威力彩: 6個普通號 + 1個特別號
                        for i in range(1, 7):
                            col_name = f"號碼{i}" if f"號碼{i}" in row else f"num{i}"
                            if col_name in row and row[col_name]:
                                try:
                                    num = int(float(row[col_name]))
                                    if 1 <= num <= 38:
                                        numbers.append(num)
                                except:
                                    pass
                        
                        # 特別號
                        special_cols = ["特別號", "特別", "special", "第二區"]
                        for col in special_cols:
                            if col in row and row[col]:
                                try:
                                    special = int(float(row[col]))
                                    break
                                except:
                                    pass
                    
                    elif game_type == "今彩539":
                        # 今彩539: 5個普通號，無特別號
                        for i in range(1, 6):
                            col_name = f"號碼{i}" if f"號碼{i}" in row else f"num{i}"
                            if col_name in row and row[col_name]:
                                try:
                                    num = int(float(row[col_name]))
                                    if 1 <= num <= 39:
                                        numbers.append(num)
                                except:
                                    pass
                    
                    # 確保號碼數量正確
                    expected_count = GAME_API_CONFIG[game_type]["number_count"]
                    if len(numbers) != expected_count:
                        log(f"號碼數量不正確 {len(numbers)}/{expected_count}: {formatted_date}", "WARNING")
                        continue
                    
                    # 排序號碼
                    numbers.sort()
                    
                    # 建立標準格式
                    draw_data = {
                        "date": formatted_date,
                        "period": period,
                        "numbers": numbers
                    }
                    
                    if special is not None:
                        draw_data["special"] = special
                    
                    standard_data.append(draw_data)
                    
                except Exception as e:
                    log(f"解析CSV行時發生錯誤: {e}", "WARNING")
                    continue
            
            if standard_data:
                # 按日期排序 (從舊到新)
                standard_data.sort(key=lambda x: x['date'])
                log(f"成功轉換 {len(standard_data)} 筆 {game_type} 資料", "SUCCESS")
            
            return standard_data
            
    except Exception as e:
        log(f"讀取CSV檔案失敗: {e}", "ERROR")
        return []

def manual_import_historical_data():
    """
    手動匯入歷史資料功能
    讓使用者選擇匯入方式
    """
    print("=" * 60)
    print("📥 手動匯入歷史資料工具")
    print("=" * 60)
    
    data_dir = "historical_data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        log(f"建立歷史資料目錄: {data_dir}", "INFO")
        print(f"請將您的歷史資料檔案放入 '{data_dir}' 目錄中")
        print("支援格式: CSV, JSON")
        print("檔案命名建議:")
        print("  - 大樂透: lotto649_2025.csv")
        print("  - 威力彩: superlotto_2025.csv")  
        print("  - 今彩539: dailycash_2025.csv")
        return False
    
    # 檢查目錄中的檔案
    files = os.listdir(data_dir)
    if not files:
        log(f"'{data_dir}' 目錄中沒有檔案", "WARNING")
        print(f"請將您的歷史資料檔案放入 '{data_dir}' 目錄中")
        return False
    
    print(f"找到 {len(files)} 個檔案:")
    for i, file in enumerate(files, 1):
        print(f"  {i}. {file}")
    
    # 詢問使用者要處理哪些遊戲
    print("\n請選擇要匯入的遊戲 (可多選，用逗號分隔):")
    print("1. 大樂透")
    print("2. 威力彩")
    print("3. 今彩539")
    print("4. 全部遊戲")
    print("0. 跳過手動匯入")
    
    try:
        choice = input("請輸入選擇: ").strip()
        if choice == "0":
            return True  # 使用者選擇跳過
        
        games_to_import = []
        if choice == "4":
            games_to_import = ["大樂透", "威力彩", "今彩539"]
        else:
            choices = [c.strip() for c in choice.split(",")]
            for c in choices:
                if c == "1":
                    games_to_import.append("大樂透")
                elif c == "2":
                    games_to_import.append("威力彩")
                elif c == "3":
                    games_to_import.append("今彩539")
        
        if not games_to_import:
            log("未選擇任何遊戲", "WARNING")
            return True
        
        # 載入現有資料庫（如果存在）
        existing_data = load_existing_data()
        
        # 處理每個遊戲
        for game_name in games_to_import:
            log(f"處理 {game_name} 歷史資料...", "IMPORT")
            
            # 尋找對應的檔案
            matching_files = []
            for file in files:
                file_lower = file.lower()
                if game_name == "大樂透" and ("lotto" in file_lower or "649" in file_lower or "大樂透" in file):
                    matching_files.append(file)
                elif game_name == "威力彩" and ("super" in file_lower or "威力" in file_lower or "638" in file_lower):
                    matching_files.append(file)
                elif game_name == "今彩539" and ("daily" in file_lower or "今彩" in file_lower or "539" in file_lower):
                    matching_files.append(file)
            
            if not matching_files:
                log(f"找不到 {game_name} 的歷史資料檔案", "WARNING")
                continue
            
            # 如果有多個檔案，讓使用者選擇
            selected_file = None
            if len(matching_files) == 1:
                selected_file = matching_files[0]
                log(f"使用檔案: {selected_file}", "INFO")
            else:
                print(f"\n找到多個 {game_name} 檔案:")
                for i, file in enumerate(matching_files, 1):
                    print(f"  {i}. {file}")
                file_choice = input("請選擇檔案 (輸入編號): ").strip()
                try:
                    idx = int(file_choice) - 1
                    if 0 <= idx < len(matching_files):
                        selected_file = matching_files[idx]
                    else:
                        log("無效的選擇", "WARNING")
                        continue
                except:
                    log("無效的輸入", "WARNING")
                    continue
            
            # 處理檔案
            file_path = os.path.join(data_dir, selected_file)
            if selected_file.lower().endswith('.csv'):
                # CSV格式
                historical_data = convert_csv_to_json_format(file_path, game_name)
            elif selected_file.lower().endswith('.json'):
                # JSON格式
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        historical_data = json.load(f)
                    log(f"從JSON載入 {len(historical_data)} 筆資料", "INFO")
                except Exception as e:
                    log(f"讀取JSON檔案失敗: {e}", "ERROR")
                    continue
            else:
                log(f"不支援的檔案格式: {selected_file}", "ERROR")
                continue
            
            if historical_data:
                # 過濾出9月23日之前的資料
                manual_data = []
                for draw in historical_data:
                    try:
                        draw_date = datetime.strptime(draw['date'], '%Y-%m-%d')
                        # 只保留9月23日之前的資料（API從9月23日開始）
                        if draw_date < datetime(2025, 9, 23):
                            manual_data.append(draw)
                    except:
                        continue
                
                if manual_data:
                    # 合併到現有資料
                    if game_name not in existing_data:
                        existing_data[game_name] = []
                    
                    # 建立現有期號集合
                    existing_periods = set(draw.get('period', '') for draw in existing_data[game_name])
                    
                    # 加入新資料
                    added_count = 0
                    for draw in manual_data:
                        if draw.get('period', '') not in existing_periods:
                            existing_data[game_name].append(draw)
                            existing_periods.add(draw.get('period', ''))
                            added_count += 1
                    
                    if added_count > 0:
                        # 按日期排序
                        existing_data[game_name].sort(key=lambda x: x['date'])
                        log(f"成功匯入 {added_count} 筆 {game_name} 歷史資料 (9月23日前)", "SUCCESS")
                    else:
                        log(f"{game_name} 無新資料可匯入", "INFO")
                else:
                    log(f"{game_name} 沒有9月23日前的歷史資料", "INFO")
        
        # 儲存合併後的資料
        if existing_data:
            save_data(existing_data)
            return True
        else:
            log("沒有成功匯入任何資料", "WARNING")
            return False
            
    except Exception as e:
        log(f"手動匯入過程中發生錯誤: {e}", "ERROR")
        return False

# ========== API資料處理函數 ==========
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

# ========== 資料管理函數 ==========
def load_existing_data() -> Dict:
    """載入現有的JSON資料庫"""
    data_file = 'data/lottery-data.json'
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 確保資料按日期正序排列（舊到新）
            for game in data.values():
                if game:
                    game.sort(key=lambda x: x['date'])
            
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
            # 按日期重新排序（舊到新）
            merged[game_name].sort(key=lambda x: x['date'])
            total_added += added_count
            log(f"遊戲 {game_name} 合併 {added_count} 筆新資料", "SUCCESS")
    
    return merged, total_added

def save_data(data: Dict) -> bool:
    """儲存資料到檔案系統"""
    try:
        os.makedirs('data', exist_ok=True)
        
        # 建立備份
        backup_file = 'data/lottery-data-backup.json'
        if os.path.exists('data/lottery-data.json'):
            import shutil
            shutil.copy2('data/lottery-data.json', backup_file)
            log(f"建立備份: {backup_file}", "INFO")
        
        # 儲存主要資料檔案
        with open('data/lottery-data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 儲存更新資訊
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '1.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys()),
            'note': '資料來源: 手動歷史資料 + 台灣彩券官方API'
        }
        
        with open('data/update-info.json', 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        # 顯示摘要
        log("=" * 60, "INFO")
        log("📊 資料庫更新摘要", "INFO")
        log("=" * 60, "INFO")
        
        for game_name, draws in data.items():
            if draws:
                # 顯示最早和最晚日期
                earliest = draws[0]['date']
                latest = draws[-1]['date']
                log(f"  {game_name}: {len(draws)} 筆", "INFO")
                log(f"    時間範圍: {earliest} 到 {latest}", "INFO")
                
                # 顯示最新一期
                latest_draw = draws[-1]
                numbers_str = str(latest_draw['numbers'])
                if 'special' in latest_draw:
                    numbers_str += f" 特別號: {latest_draw['special']}"
                log(f"    最新一期: {latest_draw['date']} {numbers_str}", "INFO")
            else:
                log(f"  {game_name}: 0 筆", "INFO")
        
        log(f"總計: {update_info['total_records']} 筆開獎紀錄", "SUCCESS")
        log(f"更新時間: {update_info['last_updated'][:19]}", "INFO")
        
        return True
        
    except Exception as e:
        log(f"儲存資料失敗: {e}", "ERROR")
        return False

def check_data_coverage(data: Dict) -> None:
    """檢查資料覆蓋範圍"""
    log("=" * 60, "INFO")
    log("📅 資料覆蓋範圍檢查", "INFO")
    log("=" * 60, "INFO")
    
    today = datetime.now(TAIPEI_TZ)
    
    for game_name, draws in data.items():
        if not draws:
            log(f"{game_name}: 無資料", "WARNING")
            continue
        
        earliest_date = datetime.strptime(draws[0]['date'], '%Y-%m-%d')
        latest_date = datetime.strptime(draws[-1]['date'], '%Y-%m-%d')
        
        log(f"{game_name}:", "INFO")
        log(f"  資料範圍: {draws[0]['date']} 到 {draws[-1]['date']}", "INFO")
        log(f"  總期數: {len(draws)}", "INFO")
        
        # 檢查是否有9月23日前的資料
        sep23 = datetime(2025, 9, 23)
        if earliest_date < sep23:
            manual_count = sum(1 for d in draws 
                             if datetime.strptime(d['date'], '%Y-%m-%d') < sep23)
            log(f"  手動資料(9/23前): {manual_count} 期", "SUCCESS")
        
        # 檢查是否有9月23日後的資料
        api_count = sum(1 for d in draws 
                       if datetime.strptime(d['date'], '%Y-%m-%d') >= sep23)
        if api_count > 0:
            log(f"  API資料(9/23後): {api_count} 期", "SUCCESS")
        
        # 檢查是否有缺失
        expected_dates = []
        current = earliest_date
        while current <= latest_date:
            expected_dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        actual_dates = set(d['date'] for d in draws)
        missing_dates = [d for d in expected_dates if d not in actual_dates]
        
        if missing_dates:
            log(f"  缺失期數: {len(missing_dates)}", "WARNING")
            if len(missing_dates) <= 5:
                for date in missing_dates:
                    log(f"    - {date}", "WARNING")
            else:
                log(f"    前5筆缺失: {missing_dates[:5]}", "WARNING")
        else:
            log(f"  資料完整: 是", "SUCCESS")

# ========== 主程式 ==========
def main():
    """主執行流程"""
    print("=" * 70)
    print("🎯 台灣彩券開獎資料自動更新系統 - 手動+API混合版")
    print("📅 功能: 1. 手動匯入2025年1月-9月22日歷史資料")
    print("        2. 自動抓取9月23日以後API資料")
    print("        3. 持續增量更新未來開獎")
    print("=" * 70)
    
    success = False
    
    try:
        # 檢查是否需要手動匯入
        if not os.path.exists('data/lottery-data.json'):
            log("資料庫不存在，建議先進行手動匯入", "INFO")
            choice = input("是否現在進行手動歷史資料匯入？(y/N): ").strip().lower()
            if choice == 'y':
                if not manual_import_historical_data():
                    log("手動匯入失敗或取消", "WARNING")
                else:
                    log("手動匯入完成，繼續執行增量更新", "SUCCESS")
        
        # 載入現有資料庫
        existing_data = load_existing_data()
        
        # 檢查資料覆蓋範圍
        check_data_coverage(existing_data)
        
        # 增量爬取各遊戲新資料
        all_new_data = {}
        
        for game_name in GAME_API_CONFIG.keys():
            existing_draws = existing_data.get(game_name, [])
            new_draws = crawl_game_incrementally(game_name, existing_draws)
            
            if new_draws:
                all_new_data[game_name] = new_draws
        
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
    # 檢查命令列參數
    if len(sys.argv) > 1:
        if sys.argv[1] == "--import":
            # 執行手動匯入模式
            manual_import_historical_data()
        elif sys.argv[1] == "--help":
            print("使用說明:")
            print("  python lottery_crawler.py           # 正常執行（包含增量更新）")
            print("  python lottery_crawler.py --import  # 僅執行手動歷史資料匯入")
            print("  python lottery_crawler.py --help    # 顯示此說明")
            sys.exit(0)
    else:
        # 正常執行模式
        success = main()
        sys.exit(0 if success else 1)
