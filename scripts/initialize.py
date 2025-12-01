#!/usr/bin/env python3
"""
台灣彩券開獎資料自動更新系統 - ZIP檔案自動解析版
版本: 2.0
功能: 
1. 自動解析官網下載的ZIP檔案（110年-114年）
2. 整合所有歷史開獎資料
3. 使用API抓取最新資料
4. 自動增量更新未來開獎資料
"""

import requests
import json
import os
import sys
import time
import csv
import zipfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import pytz
from pathlib import Path

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
    },
    "3星彩": {
        "api_path": None,  # 暫時沒有API
        "number_count": 3,
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

# 民國年轉西元年對照表（110年-114年）
ROCN_YEAR_MAP = {
    110: 2021,
    111: 2022,
    112: 2023,
    113: 2024,
    114: 2025,
    115: 2026
}

# ========== 工具函數 ==========
def log(message: str, level: str = "INFO"):
    """統一日誌輸出函數"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌", "IMPORT": "📥", "ZIP": "📦"}
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

# ========== ZIP檔案處理函數 ==========
def extract_zip_file(zip_path: str, extract_to: str) -> List[str]:
    """解壓縮ZIP檔案，返回解壓縮的檔案列表"""
    extracted_files = []
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # 列出所有檔案
            file_list = zip_ref.namelist()
            
            # 過濾出CSV檔案
            csv_files = [f for f in file_list if f.lower().endswith('.csv')]
            
            if not csv_files:
                log(f"ZIP檔案中沒有CSV檔案: {zip_path}", "WARNING")
                return []
            
            # 解壓縮所有CSV檔案
            for csv_file in csv_files:
                try:
                    zip_ref.extract(csv_file, extract_to)
                    extracted_path = os.path.join(extract_to, csv_file)
                    extracted_files.append(extracted_path)
                    log(f"解壓縮檔案: {csv_file}", "INFO")
                except Exception as e:
                    log(f"解壓縮失敗 {csv_file}: {e}", "WARNING")
            
            log(f"成功解壓縮 {len(extracted_files)} 個CSV檔案", "SUCCESS")
            return extracted_files
            
    except zipfile.BadZipFile:
        log(f"ZIP檔案損壞: {zip_path}", "ERROR")
    except Exception as e:
        log(f"處理ZIP檔案失敗: {e}", "ERROR")
    
    return []

def find_zip_files(directory: str) -> List[str]:
    """在指定目錄中尋找所有ZIP檔案"""
    zip_files = []
    
    try:
        for file in os.listdir(directory):
            if file.lower().endswith('.zip'):
                zip_path = os.path.join(directory, file)
                zip_files.append(zip_path)
    except Exception as e:
        log(f"掃描目錄失敗: {e}", "ERROR")
    
    return sorted(zip_files)  # 按名稱排序

def detect_year_from_zip_filename(filename: str) -> Optional[int]:
    """從ZIP檔案名稱檢測年份"""
    # 移除副檔名和路徑
    basename = os.path.basename(filename).replace('.zip', '').replace('.ZIP', '')
    
    # 嘗試解析數字
    try:
        # 嘗試直接轉整數
        year = int(basename)
        
        # 檢查是否為西元年
        if 2000 <= year <= 2100:
            return year
        
        # 檢查是否為民國年（需要轉換）
        if 100 <= year <= 200:  # 民國100年-200年
            roc_year = year
            if roc_year in ROCN_YEAR_MAP:
                return ROCN_YEAR_MAP[roc_year]
            
            # 如果不在對照表中，使用公式計算
            return roc_year + 1911
            
    except ValueError:
        # 嘗試從字串中提取數字
        import re
        numbers = re.findall(r'\d+', basename)
        if numbers:
            try:
                year = int(numbers[0])
                if len(numbers[0]) == 4:  # 4位數，假設是西元年
                    if 2000 <= year <= 2100:
                        return year
                elif len(numbers[0]) == 3:  # 3位數，假設是民國年
                    roc_year = year
                    if roc_year in ROCN_YEAR_MAP:
                        return ROCN_YEAR_MAP[roc_year]
                    return roc_year + 1911
            except:
                pass
    
    log(f"無法從檔案名稱檢測年份: {filename}", "WARNING")
    return None

# ========== CSV檔案處理函數 ==========
def parse_taiwan_lottery_csv(csv_path: str, default_year: Optional[int] = None) -> List[Dict]:
    """
    解析台灣彩券官方CSV格式
    格式: 遊戲名稱,期別,開獎日期,銷售總額,銷售注數,總獎金,獎號1,獎號2,獎號3,獎號4,獎號5,獎號6,特別號
    """
    draws = []
    
    try:
        # 嘗試不同編碼
        encodings = ['utf-8', 'utf-8-sig', 'big5', 'cp950']
        
        for encoding in encodings:
            try:
                with open(csv_path, 'r', encoding=encoding) as f:
                    # 讀取CSV
                    reader = csv.reader(f)
                    rows = list(reader)
                    
                    if not rows:
                        log(f"CSV檔案為空: {csv_path}", "WARNING")
                        return []
                    
                    # 檢查檔案格式
                    if len(rows[0]) < 10:
                        log(f"CSV格式不符合預期: {csv_path}", "WARNING")
                        return []
                    
                    # 處理每一行（跳過可能的標頭）
                    start_row = 0
                    if "遊戲名稱" in rows[0][0] or "期別" in rows[0][1]:
                        start_row = 1  # 跳過標頭行
                    
                    for i in range(start_row, len(rows)):
                        try:
                            row = rows[i]
                            if len(row) < 7:  # 至少要有遊戲名稱、期別、日期和幾個號碼
                                continue
                            
                            # 解析遊戲名稱
                            game_name = row[0].strip()
                            
                            # 只處理我們支援的遊戲
                            if game_name not in ["大樂透", "威力彩", "今彩539", "3星彩"]:
                                continue
                            
                            # 解析期別
                            period = row[1].strip()
                            
                            # 解析開獎日期
                            date_str = row[2].strip()
                            
                            # 日期格式處理
                            try:
                                # 嘗試解析日期
                                date_formats = [
                                    "%Y/%m/%d", "%Y-%m-%d", 
                                    "%Y年%m月%d日", "%Y.%m.%d",
                                    "%m/%d/%Y", "%d/%m/%Y"
                                ]
                                
                                parsed_date = None
                                for fmt in date_formats:
                                    try:
                                        parsed_date = datetime.strptime(date_str, fmt)
                                        break
                                    except ValueError:
                                        continue
                                
                                if not parsed_date and default_year:
                                    # 如果無法解析日期，使用預設年份
                                    try:
                                        # 嘗試解析月日
                                        month_day = date_str.replace('月', '/').replace('日', '')
                                        parsed_date = datetime.strptime(f"{default_year}/{month_day}", "%Y/%m/%d")
                                    except:
                                        pass
                                
                                if not parsed_date:
                                    log(f"無法解析日期: {date_str}，跳過此筆", "WARNING")
                                    continue
                                
                                formatted_date = parsed_date.strftime("%Y-%m-%d")
                                
                            except Exception as e:
                                log(f"日期解析失敗 {date_str}: {e}", "WARNING")
                                continue
                            
                            # 解析開獎號碼
                            numbers = []
                            special = None
                            
                            if game_name == "大樂透":
                                # 大樂透: 6個普通號 + 1個特別號
                                for col_idx in range(6, 12):  # 獎號1-6
                                    if col_idx < len(row) and row[col_idx].strip():
                                        try:
                                            num = int(row[col_idx].strip())
                                            if 1 <= num <= 49:
                                                numbers.append(num)
                                        except:
                                            pass
                                
                                # 特別號
                                if len(row) > 12 and row[12].strip():
                                    try:
                                        special = int(row[12].strip())
                                    except:
                                        pass
                            
                            elif game_name == "威力彩":
                                # 威力彩: 6個普通號 + 1個特別號
                                for col_idx in range(6, 12):  # 獎號1-6
                                    if col_idx < len(row) and row[col_idx].strip():
                                        try:
                                            num = int(row[col_idx].strip())
                                            if 1 <= num <= 38:
                                                numbers.append(num)
                                        except:
                                            pass
                                
                                # 特別號
                                if len(row) > 12 and row[12].strip():
                                    try:
                                        special = int(row[12].strip())
                                    except:
                                        pass
                            
                            elif game_name == "今彩539":
                                # 今彩539: 5個普通號，無特別號
                                for col_idx in range(6, 11):  # 獎號1-5
                                    if col_idx < len(row) and row[col_idx].strip():
                                        try:
                                            num = int(row[col_idx].strip())
                                            if 1 <= num <= 39:
                                                numbers.append(num)
                                        except:
                                            pass
                            
                            elif game_name == "3星彩":
                                # 3星彩: 3個普通號
                                for col_idx in range(6, 9):  # 獎號1-3
                                    if col_idx < len(row) and row[col_idx].strip():
                                        try:
                                            num = int(row[col_idx].strip())
                                            if 0 <= num <= 9:
                                                numbers.append(num)
                                        except:
                                            pass
                            
                            # 檢查號碼數量
                            expected_count = GAME_API_CONFIG.get(game_name, {}).get("number_count", 0)
                            if expected_count > 0 and len(numbers) != expected_count:
                                log(f"{game_name} 號碼數量不正確 {len(numbers)}/{expected_count}: {formatted_date}", "WARNING")
                                continue
                            
                            # 排序號碼（除了3星彩，因為3星彩是有順序的）
                            if game_name != "3星彩":
                                numbers.sort()
                            
                            # 建立標準格式
                            draw_data = {
                                "date": formatted_date,
                                "period": period,
                                "numbers": numbers
                            }
                            
                            if special is not None:
                                draw_data["special"] = special
                            
                            draws.append(draw_data)
                            
                        except Exception as e:
                            log(f"解析第{i+1}行失敗: {e}", "WARNING")
                            continue
                    
                    # 成功讀取，跳出編碼迴圈
                    break
                    
            except UnicodeDecodeError:
                continue  # 嘗試下一個編碼
            except Exception as e:
                log(f"讀取CSV失敗 {csv_path}: {e}", "ERROR")
                return []
        
        if draws:
            # 按日期排序（從舊到新）
            draws.sort(key=lambda x: x['date'])
            log(f"成功解析 {len(draws)} 筆開獎資料: {csv_path}", "SUCCESS")
        
        return draws
        
    except Exception as e:
        log(f"處理CSV檔案失敗 {csv_path}: {e}", "ERROR")
        return []

# ========== 批次處理ZIP檔案函數 ==========
def batch_process_zip_files(zip_dir: str = "zip_files") -> Dict:
    """
    批次處理ZIP檔案目錄中的所有ZIP檔案
    返回整合後的資料庫
    """
    log(f"開始批次處理ZIP檔案目錄: {zip_dir}", "ZIP")
    
    # 建立暫存目錄
    temp_dir = "temp_extract"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 最終資料庫
    all_data = {game: [] for game in GAME_API_CONFIG.keys()}
    
    # 尋找所有ZIP檔案
    zip_files = find_zip_files(zip_dir)
    
    if not zip_files:
        log(f"在 '{zip_dir}' 目錄中找不到ZIP檔案", "WARNING")
        log(f"請將台灣彩券官方下載的ZIP檔案放入 '{zip_dir}' 目錄中", "INFO")
        log(f"ZIP檔案命名建議: 2021.zip, 2022.zip, ..., 2025.zip", "INFO")
        return all_data
    
    log(f"找到 {len(zip_files)} 個ZIP檔案", "INFO")
    
    # 處理每個ZIP檔案
    for zip_path in zip_files:
        zip_filename = os.path.basename(zip_path)
        log(f"處理ZIP檔案: {zip_filename}", "ZIP")
        
        # 從檔案名稱檢測年份
        default_year = detect_year_from_zip_filename(zip_filename)
        if default_year:
            log(f"檢測到年份: {default_year}", "INFO")
        
        # 解壓縮ZIP檔案
        extracted_files = extract_zip_file(zip_path, temp_dir)
        
        if not extracted_files:
            log(f"ZIP檔案解壓縮失敗或沒有CSV檔案: {zip_filename}", "WARNING")
            continue
        
        # 處理每個CSV檔案
        for csv_path in extracted_files:
            csv_filename = os.path.basename(csv_path)
            
            # 解析CSV檔案
            draws = parse_taiwan_lottery_csv(csv_path, default_year)
            
            if draws:
                # 將資料按遊戲分類
                for draw in draws:
                    # 從draw中取得遊戲名稱（CSV解析時已經包含）
                    # 注意：parse_taiwan_lottery_csv返回的draw中不包含game_name
                    # 我們需要從CSV檔案名稱判斷
                    game_name = None
                    
                    # 從CSV檔案名稱判斷遊戲類型
                    csv_lower = csv_filename.lower()
                    if "大樂透" in csv_lower or "lotto" in csv_lower or "649" in csv_lower:
                        game_name = "大樂透"
                    elif "威力彩" in csv_lower or "super" in csv_lower or "638" in csv_lower:
                        game_name = "威力彩"
                    elif "今彩539" in csv_lower or "daily" in csv_lower or "539" in csv_lower:
                        game_name = "今彩539"
                    elif "3星彩" in csv_lower or "3星" in csv_lower:
                        game_name = "3星彩"
                    
                    if game_name and game_name in all_data:
                        all_data[game_name].append(draw)
                    else:
                        log(f"無法識別遊戲類型或遊戲未支援: {csv_filename}", "WARNING")
            
            # 刪除暫存CSV檔案
            try:
                os.remove(csv_path)
            except:
                pass
        
        log(f"完成處理 {zip_filename}", "SUCCESS")
    
    # 清理暫存目錄
    try:
        os.rmdir(temp_dir)
    except:
        pass
    
    # 對每個遊戲的資料進行去重和排序
    for game_name, draws in all_data.items():
        if draws:
            # 去重（基於期別）
            unique_draws = {}
            for draw in draws:
                period = draw.get("period", "")
                if period:
                    unique_draws[period] = draw
            
            # 轉回列表並按日期排序
            all_data[game_name] = list(unique_draws.values())
            all_data[game_name].sort(key=lambda x: x['date'])
            
            log(f"{game_name}: {len(all_data[game_name])} 筆唯一資料", "SUCCESS")
    
    total_records = sum(len(draws) for draws in all_data.values())
    log(f"批次處理完成！總共 {total_records} 筆開獎資料", "SUCCESS")
    
    return all_data

def manual_import_from_zip():
    """手動從ZIP檔案匯入歷史資料"""
    print("=" * 60)
    print("📦 ZIP檔案歷史資料批次匯入工具")
    print("=" * 60)
    
    zip_dir = "zip_files"
    
    # 檢查zip_files目錄是否存在
    if not os.path.exists(zip_dir):
        os.makedirs(zip_dir)
        log(f"建立ZIP檔案目錄: {zip_dir}", "INFO")
        print(f"請將台灣彩券官方下載的ZIP檔案放入 '{zip_dir}' 目錄中")
        print(f"ZIP檔案命名建議: 2021.zip, 2022.zip, ..., 2025.zip")
        print(f"然後重新執行此功能")
        return False
    
    # 批次處理所有ZIP檔案
    imported_data = batch_process_zip_files(zip_dir)
    
    if not any(len(draws) > 0 for draws in imported_data.values()):
        log("沒有成功匯入任何資料", "WARNING")
        return False
    
    # 載入現有資料庫
    existing_data = load_existing_data()
    
    # 合併資料
    merged_data, total_added = merge_and_deduplicate(existing_data, imported_data)
    
    if total_added > 0:
        # 儲存資料
        if save_data(merged_data):
            log(f"✅ 成功匯入 {total_added} 筆歷史資料", "SUCCESS")
            
            # 顯示統計資訊
            check_data_coverage(merged_data)
            
            return True
        else:
            log("❌ 資料儲存失敗", "ERROR")
            return False
    else:
        log("ℹ️ 沒有新資料可匯入（可能已存在）", "INFO")
        return True

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
            'data_version': '2.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys()),
            'note': '資料來源: 台灣彩券官方ZIP檔案 + API'
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
    current_year = today.year
    
    for game_name, draws in data.items():
        if not draws:
            log(f"{game_name}: 無資料", "WARNING")
            continue
        
        earliest_date = datetime.strptime(draws[0]['date'], '%Y-%m-%d')
        latest_date = datetime.strptime(draws[-1]['date'], '%Y-%m-%d')
        
        log(f"{game_name}:", "INFO")
        log(f"  資料範圍: {draws[0]['date']} 到 {draws[-1]['date']}", "INFO")
        log(f"  總期數: {len(draws)}", "INFO")
        
        # 檢查年份覆蓋
        years = set()
        for draw in draws:
            year = datetime.strptime(draw['date'], '%Y-%m-%d').year
            years.add(year)
        
        if years:
            sorted_years = sorted(years)
            log(f"  涵蓋年份: {sorted_years}", "INFO")
        
        # 檢查是否有缺失
        expected_dates = []
        current = earliest_date
        while current <= latest_date:
            # 只計算週二、四、六（大樂透開獎日）或其他遊戲的開獎日
            # 這裡簡單檢查，實際應該根據遊戲規則
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
            log(f"  資料完整: 是", "SUCCESS")

# ========== 主程式 ==========
def main():
    """主執行流程"""
    print("=" * 70)
    print("🎯 台灣彩券開獎資料自動更新系統 - ZIP檔案自動解析版")
    print("📅 功能: 1. 自動解析ZIP檔案（110年-114年歷史資料）")
    print("        2. 自動抓取9月23日以後API資料")
    print("        3. 持續增量更新未來開獎")
    print("=" * 70)
    
    success = False
    
    try:
        # 檢查是否需要手動匯入
        if not os.path.exists('data/lottery-data.json'):
            log("資料庫不存在，建議先進行歷史資料匯入", "INFO")
            choice = input("是否現在從ZIP檔案匯入歷史資料？(y/N): ").strip().lower()
            if choice == 'y':
                if not manual_import_from_zip():
                    log("ZIP檔案匯入失敗或取消", "WARNING")
                else:
                    log("歷史資料匯入完成，繼續執行增量更新", "SUCCESS")
        
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
    # 檢查命令列參數
    if len(sys.argv) > 1:
        if sys.argv[1] == "--import":
            # 執行手動匯入模式
            manual_import_from_zip()
        elif sys.argv[1] == "--check":
            # 檢查資料庫狀態
            data = load_existing_data()
            check_data_coverage(data)
        elif sys.argv[1] == "--help":
            print("使用說明:")
            print("  python lottery_crawler.py           # 正常執行（包含增量更新）")
            print("  python lottery_crawler.py --import  # 僅執行ZIP檔案歷史資料匯入")
            print("  python lottery_crawler.py --check   # 檢查資料庫狀態")
            print("  python lottery_crawler.py --help    # 顯示此說明")
            sys.exit(0)
    else:
        # 正常執行模式
        success = main()
        sys.exit(0 if success else 1)
