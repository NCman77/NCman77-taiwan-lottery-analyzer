#!/usr/bin/env python3
"""
台灣彩券開獎資料初始化腳本 - ZIP檔案版本
版本: 2.0
功能: 從台灣彩券官方ZIP檔案匯入歷史資料
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.common import (
    log, load_existing_data, merge_and_deduplicate, 
    save_data, check_data_coverage, GAME_API_CONFIG,
    ROCN_YEAR_MAP
)
import zipfile
import csv
from datetime import datetime
from typing import Dict, List, Optional
import re

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

def batch_process_zip_files(zip_dir: str = "../zip_files") -> Dict:
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
                    else:
                        # 嘗試從資料中的遊戲名稱判斷
                        continue
                    
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
    
    zip_dir = "../zip_files"
    
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

def main():
    """主執行流程"""
    print("=" * 70)
    print("🎯 台灣彩券開獎資料初始化系統 - ZIP檔案自動解析版")
    print("📅 功能: 自動解析ZIP檔案（110年-114年歷史資料）")
    print("=" * 70)
    
    success = False
    
    try:
        success = manual_import_from_zip()
            
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
