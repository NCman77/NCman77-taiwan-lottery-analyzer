#!/usr/bin/env python3
"""
台灣彩券自動更新腳本 - 強化版
目標：穩定抓取官網開獎資料並轉換為JSON格式
"""

import requests
import json
import os
import zipfile
import io
import re
import pandas as pd
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
import time
import shutil

# ========== 配置區域 ==========
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
BASE_URL = "https://www.taiwanlottery.com"
DOWNLOAD_PAGE_URL = f"{BASE_URL}/lotto/history/result_download"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# 遊戲名稱正規化對應表 (根據常見CSV檔名)
GAME_NAME_MAP = {
    # 關鍵字: 顯示名稱
    '大樂透': '大樂透',
    '威力彩': '威力彩',
    '今彩539': '今彩539',
    '雙贏彩': '雙贏彩',
    '3星彩': '三星彩',
    '4星彩': '四星彩',
    '38樂合彩': '38樂合彩',
    '49樂合彩': '49樂合彩',
    '39樂合彩': '39樂合彩',
    '賓果': '賓果賓果',  # 注意：官方年度ZIP可能不包含賓果賓果的日開獎CSV
}

def log_info(message):
    """輸出資訊日誌"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] ℹ️ {message}")

def log_success(message):
    """輸出成功日誌"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] ✅ {message}")

def log_warning(message):
    """輸出警告日誌"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] ⚠️ {message}")

def log_error(message):
    """輸出錯誤日誌"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] ❌ {message}")

def get_download_url():
    """
    從下載頁面獲取最新年度ZIP檔的下載連結。
    這是關鍵步驟，必須成功。
    """
    log_info("正在訪問台灣彩券下載頁面...")
    try:
        headers = {'User-Agent': USER_AGENT}
        # 增加請求重試和超時設定
        for attempt in range(3):
            try:
                response = requests.get(DOWNLOAD_PAGE_URL, headers=headers, timeout=15)
                response.raise_for_status()
                break
            except requests.exceptions.Timeout:
                if attempt == 2:
                    raise
                log_warning(f"請求超時，第 {attempt+1} 次重試...")
                time.sleep(2)
        
        soup = BeautifulSoup(response.content, 'html.parser')
        log_info("下載頁面解析成功")
        
        # 方法1: 尋找包含當前民國年度的連結
        current_year_roc = datetime.now(TAIPEI_TZ).year - 1911
        target_year_text = f"{current_year_roc}年度"
        
        log_info(f"尋找目標年度連結: '{target_year_text}'")
        download_link = None
        
        # 搜尋所有連結元素
        all_links = soup.find_all('a', href=True)
        for link in all_links:
            link_text = link.get_text(strip=True)
            href = link['href']
            
            # 優先匹配目標年度文字
            if target_year_text in link_text:
                download_link = href
                log_info(f"找到目標年度連結: {link_text}")
                break
            
            # 其次匹配包含'下載'或'ZIP'的連結
            if not download_link and ('下載' in link_text or 'ZIP' in link_text.upper()):
                download_link = href
                log_info(f"找到備用下載連結: {link_text}")
        
        if not download_link and all_links:
            # 最後嘗試第一個有效的連結
            first_link = all_links[0]['href']
            if first_link and first_link != '#':
                download_link = first_link
                log_warning(f"使用第一個找到的連結: {first_link}")
        
        if download_link:
            # 構建完整URL
            if download_link.startswith('http'):
                final_url = download_link
            elif download_link.startswith('/'):
                final_url = f"{BASE_URL}{download_link}"
            else:
                final_url = f"{BASE_URL}/{download_link}"
            
            log_success(f"獲得下載連結: {final_url}")
            return final_url
        else:
            log_error("無法在頁面上找到下載連結")
            return None
            
    except Exception as e:
        log_error(f"獲取下載連結失敗: {str(e)}")
        return None

def download_zip_file(url):
    """下載ZIP檔案到記憶體"""
    log_info(f"開始下載ZIP檔案: {url}")
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=30, stream=True)
        response.raise_for_status()
        
        # 檢查檔案大小
        file_size = int(response.headers.get('content-length', 0))
        if file_size == 0:
            log_warning("下載的檔案大小為0，可能異常")
        
        log_success(f"ZIP檔案下載成功，大小: {file_size / (1024*1024):.2f} MB")
        return io.BytesIO(response.content)
        
    except Exception as e:
        log_error(f"下載ZIP檔案失敗: {str(e)}")
        return None

def extract_and_parse_zip(zip_buffer):
    """解壓縮ZIP並解析其中的CSV檔案"""
    all_game_data = {}
    
    # 建立暫存目錄
    temp_dir = 'temp_extract'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    try:
        with zipfile.ZipFile(zip_buffer) as zip_ref:
            # 列出所有檔案
            file_list = zip_ref.namelist()
            csv_files = [f for f in file_list if f.lower().endswith('.csv')]
            
            log_info(f"ZIP內含 {len(file_list)} 個檔案，其中 {len(csv_files)} 個CSV檔案")
            
            if not csv_files:
                log_error("ZIP檔案中沒有找到CSV檔案")
                return all_game_data
            
            # 解壓所有CSV檔案
            for csv_file in csv_files:
                zip_ref.extract(csv_file, temp_dir)
            
            # 解析每個CSV檔案
            for csv_filename in csv_files:
                try:
                    csv_path = os.path.join(temp_dir, csv_filename)
                    game_data = parse_single_csv(csv_path, csv_filename)
                    
                    if game_data:
                        # 確定遊戲名稱
                        game_name = identify_game_name(csv_filename)
                        if game_name:
                            if game_name not in all_game_data:
                                all_game_data[game_name] = []
                            all_game_data[game_name].extend(game_data)
                            log_success(f"  已解析 {game_name} 的 {len(game_data)} 筆紀錄")
                        else:
                            log_warning(f"  無法識別遊戲類型，跳過檔案: {csv_filename}")
                    
                except Exception as e:
                    log_error(f"  處理檔案 {csv_filename} 時發生錯誤: {str(e)}")
                    continue
        
        log_info(f"總共解析了 {len(all_game_data)} 種遊戲的資料")
        return all_game_data
        
    except Exception as e:
        log_error(f"解壓縮或解析ZIP失敗: {str(e)}")
        return all_game_data
    finally:
        # 清理暫存目錄
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def identify_game_name(filename):
    """根據檔名識別遊戲名稱"""
    filename_lower = filename.lower()
    
    for key_word, display_name in GAME_NAME_MAP.items():
        if key_word in filename_lower:
            return display_name
    
    # 特殊處理：今彩539有時簡寫
    if '今彩' in filename_lower and '539' in filename_lower:
        return '今彩539'
    
    return None

def parse_single_csv(filepath, filename):
    """解析單個CSV檔案"""
    game_records = []
    
    # 嘗試多種編碼
    encodings_to_try = ['big5', 'utf-8-sig', 'cp950', 'latin1']
    df = None
    
    for encoding in encodings_to_try:
        try:
            df = pd.read_csv(filepath, encoding=encoding, engine='python')
            log_info(f"  使用編碼 {encoding} 成功讀取 {filename}")
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            continue
    
    if df is None or df.empty:
        log_warning(f"  無法讀取或檔案為空: {filename}")
        return game_records
    
    # 顯示欄位資訊用於除錯
    log_info(f"  檔案欄位: {list(df.columns)}")
    log_info(f"  資料形狀: {df.shape}")
    
    # 尋找日期和號碼欄位
    date_column = None
    number_columns = []
    
    for col in df.columns:
        col_str = str(col)
        # 尋找日期欄位
        if not date_column and any(word in col_str for word in ['日期', '開獎日期', 'Date', 'DATE']):
            date_column = col
        # 尋找號碼欄位
        if any(word in col_str for word in ['號碼', '獎號', '開出號碼', 'Number', 'NUM']):
            number_columns.append(col)
    
    # 如果沒找到明確的號碼欄位，假設所有數值欄位都是號碼
    if not number_columns:
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                number_columns.append(col)
            # 檢查前幾行數據是否為數字
            elif df[col].dropna().head(5).apply(lambda x: str(x).isdigit()).all():
                number_columns.append(col)
    
    if not date_column and df.shape[1] > 0:
        # 嘗試第一個欄位作為日期
        date_column = df.columns[0]
    
    log_info(f"  使用日期欄位: {date_column}")
    log_info(f"  使用號碼欄位: {number_columns}")
    
    # 處理每一行數據
    for _, row in df.iterrows():
        try:
            # 提取日期
            date_str = None
            if date_column and pd.notna(row[date_column]):
                date_str = str(row[date_column]).strip()
                # 清理日期格式：將年月日轉換為標準格式
                date_str = re.sub(r'[年月日]', '/', date_str)
                date_str = re.sub(r'[/]+', '/', date_str)
                
                # 嘗試解析日期
                try:
                    if re.match(r'^\d{3}/\d{1,2}/\d{1,2}$', date_str):  # 民國年
                        parts = date_str.split('/')
                        year = int(parts[0]) + 1911
                        month = int(parts[1])
                        day = int(parts[2])
                        date_obj = datetime(year, month, day)
                        date_str = date_obj.strftime('%Y-%m-%d')
                    elif re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', date_str):  # 西元年
                        date_obj = datetime.strptime(date_str, '%Y/%m/%d')
                        date_str = date_obj.strftime('%Y-%m-%d')
                except:
                    # 如果日期解析失敗，保留原始字串
                    pass
            
            # 提取號碼
            numbers = []
            for col in number_columns:
                if pd.notna(row[col]):
                    cell_value = str(row[col]).strip()
                    # 嘗試轉換為數字
                    try:
                        num = float(cell_value)
                        if num.is_integer():
                            num_int = int(num)
                            if 1 <= num_int <= 99:  # 常見樂透號碼範圍
                                numbers.append(num_int)
                    except ValueError:
                        # 如果不是數字，跳過
                        pass
            
            # 過濾重複號碼並排序
            if numbers:
                numbers = sorted(list(set(numbers)))
            
            # 確保有日期和號碼才加入
            if date_str and numbers:
                game_records.append({
                    'date': date_str,
                    'numbers': numbers
                })
                
        except Exception as e:
            # 跳過單行錯誤，繼續處理其他行
            continue
    
    return game_records

def merge_with_existing_data(new_data):
    """將新資料與現有資料合併"""
    existing_data = {}
    data_file_path = 'data/lottery-data.json'
    
    # 讀取現有資料
    if os.path.exists(data_file_path):
        try:
            with open(data_file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            log_info(f"讀取到現有資料，包含 {len(existing_data)} 種遊戲")
        except:
            log_warning("現有資料檔案讀取失敗，將建立新資料")
    
    # 合併資料
    merged_data = existing_data.copy()
    new_records_count = 0
    
    for game_name, new_records in new_data.items():
        if game_name not in merged_data:
            merged_data[game_name] = []
        
        # 取得現有資料的日期集合
        existing_dates = set(record['date'] for record in merged_data[game_name])
        
        # 只添加不重複的新資料
        for record in new_records:
            if record['date'] not in existing_dates:
                merged_data[game_name].append(record)
                new_records_count += 1
        
        # 按日期排序 (最新的在前)
        if merged_data[game_name]:
            merged_data[game_name].sort(key=lambda x: x['date'], reverse=True)
    
    log_info(f"本次合併新增了 {new_records_count} 筆不重複的紀錄")
    return merged_data

def save_data_to_repository(data):
    """將資料儲存到倉庫的data/目錄"""
    try:
        # 確保目錄存在
        os.makedirs('data', exist_ok=True)
        
        # 1. 儲存主要資料檔案
        data_file_path = 'data/lottery-data.json'
        with open(data_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        
        # 2. 儲存更新資訊檔案
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '2.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys()),
            'note': '資料來源: 台灣彩券官方網站歷史開獎結果'
        }
        
        info_file_path = 'data/update-info.json'
        with open(info_file_path, 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        log_success(f"資料儲存完成！")
        log_info(f"  遊戲種類: {len(data)} 種")
        log_info(f"  總紀錄數: {update_info['total_records']} 筆")
        log_info(f"  可用遊戲: {', '.join(data.keys())}")
        
        return True
        
    except Exception as e:
        log_error(f"儲存資料失敗: {str(e)}")
        return False

def main():
    """主執行函數"""
    print("=" * 60)
    print("台灣彩券開獎資料自動更新系統 - 強化版")
    print("=" * 60)
    
    overall_success = False
    
    try:
        # 步驟1: 取得下載連結
        download_url = get_download_url()
        if not download_url:
            log_error("無法取得下載連結，程式終止")
            return False
        
        # 步驟2: 下載ZIP檔案
        zip_buffer = download_zip_file(download_url)
        if not zip_buffer:
            log_error("無法下載ZIP檔案，程式終止")
            return False
        
        # 步驟3: 解壓縮並解析
        log_info("開始解析ZIP檔案內容...")
        new_data = extract_and_parse_zip(zip_buffer)
        
        if not new_data:
            log_error("解析後未獲得任何有效資料")
            return False
        
        # 步驟4: 合併資料
        log_info("正在合併新資料與現有資料...")
        merged_data = merge_with_existing_data(new_data)
        
        # 步驟5: 儲存資料
        log_info("正在儲存資料至倉庫...")
        if save_data_to_repository(merged_data):
            overall_success = True
            log_success("✅ 自動更新流程完成！")
        else:
            log_error("❌ 資料儲存階段失敗")
            
    except KeyboardInterrupt:
        log_warning("程式被使用者中斷")
    except Exception as e:
        log_error(f"程式執行發生未預期錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("=" * 60)
    return overall_success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
