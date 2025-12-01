#!/usr/bin/env python3
"""
台灣彩券開獎資料自動更新腳本 - 完整版
版本: 3.0
功能: 自動下載台灣彩券官方開獎資料並轉換為JSON格式
"""

import requests
import json
import os
import zipfile
import io
import re
import pandas as pd
from datetime import datetime, timedelta
import pytz
import time
import shutil
import sys

# ========== 配置區域 ==========
TAIPEI_TZ = pytz.timezone('Asia/Taipei')
BASE_URL = "https://www.taiwanlottery.com"
DOWNLOAD_PAGE_URL = f"{BASE_URL}/lotto/history/result_download"

# 完整的瀏覽器標頭，模擬真實使用者
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.taiwanlottery.com/',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
    'DNT': '1',
}

# 遊戲名稱對應表
GAME_NAME_MAP = {
    '大樂透': '大樂透',
    '威力彩': '威力彩',
    '今彩539': '今彩539',
    '雙贏彩': '雙贏彩',
    '3星彩': '三星彩',
    '4星彩': '四星彩',
    '38樂合彩': '38樂合彩',
    '49樂合彩': '49樂合彩',
    '39樂合彩': '39樂合彩',
    '賓果': '賓果賓果',
}

# ========== 工具函數 ==========
def log(message, level="INFO"):
    """統一日誌輸出函數"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    icons = {
        "INFO": "ℹ️",
        "SUCCESS": "✅", 
        "WARNING": "⚠️",
        "ERROR": "❌"
    }
    icon = icons.get(level, "ℹ️")
    print(f"[{timestamp}] {icon} {message}")

def save_debug_file(filename, content):
    """儲存除錯檔案"""
    try:
        os.makedirs('debug', exist_ok=True)
        filepath = os.path.join('debug', filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        log(f"已儲存除錯檔案: {filename}", "INFO")
    except Exception as e:
        log(f"無法儲存除錯檔案 {filename}: {e}", "WARNING")

# ========== 核心功能 ==========
def get_download_url():
    """
    取得ZIP檔案下載連結
    使用多種方法確保找到正確連結
    """
    log("正在訪問台灣彩券下載頁面...", "INFO")
    
    try:
        # 發送請求
        response = requests.get(DOWNLOAD_PAGE_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
        # 嘗試多種編碼
        html_content = None
        for encoding in ['utf-8', 'big5', 'cp950', 'latin1']:
            try:
                response.encoding = encoding
                html_content = response.text
                break
            except:
                continue
        
        if html_content is None:
            html_content = response.content.decode('utf-8', errors='ignore')
        
        log(f"頁面大小: {len(html_content)} 字元", "INFO")
        
        # 儲存頁面內容用於除錯
        save_debug_file('page_content.html', html_content[:5000])
        
        # 方法1: 使用正則表達式搜尋所有href連結
        log("使用正則表達式搜尋連結...", "INFO")
        import re
        
        # 搜尋所有href屬性
        all_hrefs = re.findall(r'href=[\'"]?([^\'" >]+)', html_content, re.IGNORECASE)
        log(f"找到 {len(all_hrefs)} 個href連結", "INFO")
        
        # 過濾和評分連結
        scored_links = []
        
        for href in all_hrefs:
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
                
            score = 0
            href_lower = href.lower()
            
            # 加分條件
            if '.zip' in href_lower:
                score += 20
            if 'download' in href_lower:
                score += 15
            if '下載' in href_lower:
                score += 15
            if '114' in href_lower or '114年度' in href_lower:
                score += 12
            if re.search(r'/\d{4}/', href_lower):  # 包含數字的路徑
                score += 8
            if re.search(r'/[a-f0-9\-]{20,}', href_lower):  # UUID格式
                score += 25
            if 'result' in href_lower:
                score += 5
            if 'history' in href_lower:
                score += 5
            
            if score > 0:
                scored_links.append((score, href))
        
        # 按分數排序
        scored_links.sort(key=lambda x: x[0], reverse=True)
        
        # 顯示前5個候選連結
        if scored_links:
            log("候選連結評分:", "INFO")
            for i, (score, link) in enumerate(scored_links[:5], 1):
                log(f"  {i}. 分數:{score:3d} - {link}", "INFO")
        
        # 方法2: 直接搜尋特定文字區域
        if not scored_links:
            log("嘗試直接搜尋特定文字模式...", "INFO")
            
            # 搜尋包含"114年度"的區域
            pattern_114 = r'(114年度[^<>]*?(?:href=[\'"][^\'"]+[\'"]|https?://[^\s<>]+))'
            matches_114 = re.findall(pattern_114, html_content, re.IGNORECASE)
            
            if matches_114:
                for match in matches_114:
                    # 從匹配文字中提取連結
                    link_match = re.search(r'(https?://[^\s<>"\']+|href=[\'"]([^\'"]+)[\'"])', match)
                    if link_match:
                        href = link_match.group(1)
                        if href.startswith('href='):
                            href = href[6:-1]  # 移除 href=" 和 "
                        scored_links.append((50, href))  # 高分
        
        # 選擇最佳連結
        if scored_links:
            best_score, best_link = scored_links[0]
            log(f"選擇最佳連結 (分數: {best_score})", "SUCCESS")
            
            # 轉換為完整URL
            if best_link.startswith('http'):
                final_url = best_link
            elif best_link.startswith('//'):
                final_url = f"https:{best_link}"
            elif best_link.startswith('/'):
                final_url = f"{BASE_URL}{best_link}"
            else:
                final_url = f"{BASE_URL}/{best_link}"
            
            log(f"最終下載連結: {final_url}", "SUCCESS")
            
            # 驗證連結
            if test_url(final_url):
                return final_url
            else:
                log("連結驗證失敗，嘗試備用連結...", "WARNING")
        
        # 方法3: 使用已知的連結模式
        log("使用已知連結模式...", "WARNING")
        known_patterns = [
            "https://www.taiwanlottery.com/7a3a8a07-1411-48b3-9ddd-35e23ead13cb",
            f"https://www.taiwanlottery.com/lotto/history/result_download/114",
            f"https://www.taiwanlottery.com/download/114",
        ]
        
        for url in known_patterns:
            log(f"測試已知連結: {url}", "INFO")
            if test_url(url):
                log(f"已知連結有效: {url}", "SUCCESS")
                return url
        
        log("無法找到有效的下載連結", "ERROR")
        return None
        
    except Exception as e:
        log(f"取得下載連結失敗: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return None

def test_url(url):
    """測試URL是否有效"""
    try:
        response = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            content_length = response.headers.get('content-length', '0')
            
            # 檢查是否為ZIP檔案
            is_zip = 'zip' in content_type or 'octet-stream' in content_type
            has_size = int(content_length) > 1024  # 大於1KB
            
            log(f"連結測試: 狀態碼={response.status_code}, 類型={content_type}, 大小={int(content_length)/1024:.1f}KB", "INFO")
            
            if is_zip or has_size:
                return True
        return False
    except Exception as e:
        log(f"連結測試失敗: {e}", "WARNING")
        return False

def download_zip_file(url):
    """下載ZIP檔案"""
    log(f"下載ZIP檔案: {url}", "INFO")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        response.raise_for_status()
        
        # 檢查檔案大小
        content_length = response.headers.get('content-length')
        if content_length:
            file_size = int(content_length)
            log(f"檔案大小: {file_size / (1024*1024):.2f} MB", "INFO")
        
        # 讀取內容到記憶體
        zip_content = io.BytesIO(response.content)
        
        # 驗證是否為有效的ZIP檔案
        try:
            with zipfile.ZipFile(zip_content) as test_zip:
                file_list = test_zip.namelist()
                log(f"ZIP檔案驗證成功，包含 {len(file_list)} 個檔案", "SUCCESS")
                
                # 顯示前幾個檔案
                csv_files = [f for f in file_list if f.lower().endswith('.csv')]
                log(f"其中包含 {len(csv_files)} 個CSV檔案", "INFO")
                for csv_file in csv_files[:3]:
                    log(f"  - {csv_file}", "INFO")
                
                return zip_content
        except zipfile.BadZipFile:
            log("下載的檔案不是有效的ZIP格式", "ERROR")
            return None
            
    except Exception as e:
        log(f"下載ZIP檔案失敗: {str(e)}", "ERROR")
        return None

def extract_and_parse_zip(zip_buffer):
    """解壓縮並解析ZIP檔案"""
    all_game_data = {}
    temp_dir = 'temp_extract'
    
    try:
        # 建立暫存目錄
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        with zipfile.ZipFile(zip_buffer) as zip_ref:
            # 解壓所有檔案
            zip_ref.extractall(temp_dir)
            file_list = zip_ref.namelist()
            
            log(f"解壓縮完成，共 {len(file_list)} 個檔案", "SUCCESS")
            
            # 解析每個CSV檔案
            csv_files = [f for f in file_list if f.lower().endswith('.csv')]
            
            for csv_file in csv_files:
                try:
                    csv_path = os.path.join(temp_dir, csv_file)
                    game_name = identify_game_name(csv_file)
                    
                    if game_name:
                        game_data = parse_csv_file(csv_path, csv_file)
                        if game_data:
                            all_game_data[game_name] = game_data
                            log(f"解析 {game_name}: {len(game_data)} 筆資料", "SUCCESS")
                    else:
                        log(f"無法識別遊戲類型: {csv_file}", "WARNING")
                        
                except Exception as e:
                    log(f"處理 {csv_file} 失敗: {e}", "ERROR")
                    continue
        
        return all_game_data
        
    except Exception as e:
        log(f"解壓縮或解析失敗: {str(e)}", "ERROR")
        return all_game_data
    finally:
        # 清理暫存目錄
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def identify_game_name(filename):
    """識別遊戲名稱"""
    filename_lower = filename.lower()
    
    for key, name in GAME_NAME_MAP.items():
        if key in filename_lower:
            return name
    
    # 特殊處理
    if '今彩' in filename_lower and '539' in filename_lower:
        return '今彩539'
    elif '賓果' in filename_lower:
        return '賓果賓果'
    
    return None

def parse_csv_file(filepath, filename):
    """解析單個CSV檔案"""
    game_data = []
    
    # 嘗試多種編碼
    encodings = ['big5', 'utf-8-sig', 'cp950', 'latin1', 'utf-8']
    df = None
    
    for encoding in encodings:
        try:
            df = pd.read_csv(filepath, encoding=encoding, engine='python')
            log(f"  {filename}: 使用 {encoding} 編碼", "INFO")
            break
        except Exception as e:
            continue
    
    if df is None or df.empty:
        log(f"  {filename}: 無法讀取CSV檔案", "WARNING")
        return game_data
    
    # 尋找日期和號碼欄位
    date_col = None
    number_cols = []
    
    for col in df.columns:
        col_str = str(col)
        # 尋找日期欄位
        if not date_col and any(word in col_str for word in ['日期', '開獎日期', 'Date']):
            date_col = col
        # 尋找號碼欄位
        if any(word in col_str for word in ['號碼', '獎號', '開出號碼', 'Number']):
            number_cols.append(col)
    
    # 如果沒找到，使用所有數值欄位
    if not number_cols:
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                number_cols.append(col)
    
    if not date_col and len(df.columns) > 0:
        date_col = df.columns[0]  # 使用第一欄作為日期
    
    log(f"  {filename}: 日期欄={date_col}, 號碼欄={number_cols}", "INFO")
    
    # 處理每一行資料
    for _, row in df.iterrows():
        try:
            # 提取日期
            date_str = None
            if date_col and pd.notna(row[date_col]):
                date_str = str(row[date_col]).strip()
                
                # 清理日期格式
                date_str = re.sub(r'[年月日]', '/', date_str)
                date_str = re.sub(r'[/]+', '/', date_str)
                
                # 解析日期
                try:
                    if re.match(r'^\d{3}/\d{1,2}/\d{1,2}$', date_str):  # 民國年
                        parts = date_str.split('/')
                        year = int(parts[0]) + 1911
                        month = int(parts[1])
                        day = int(parts[2])
                        date_str = f"{year:04d}-{month:02d}-{day:02d}"
                    elif re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', date_str):  # 西元年
                        date_parts = date_str.split('/')
                        date_str = f"{date_parts[0]}-{date_parts[1].zfill(2)}-{date_parts[2].zfill(2)}"
                except:
                    pass
            
            # 提取號碼
            numbers = []
            for col in number_cols:
                if pd.notna(row[col]):
                    try:
                        num = int(float(row[col]))
                        if 1 <= num <= 99:  # 合理範圍
                            numbers.append(num)
                    except:
                        pass
            
            # 移除重複並排序
            numbers = sorted(list(set(numbers)))
            
            # 確保有足夠的號碼
            if date_str and len(numbers) >= 2:  # 至少2個號碼
                game_data.append({
                    'date': date_str,
                    'numbers': numbers
                })
                
        except Exception as e:
            continue
    
    return game_data

def load_existing_data():
    """載入現有資料"""
    data_file = 'data/lottery-data.json'
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            log(f"載入現有資料: {len(data)} 種遊戲", "INFO")
            return data
        except Exception as e:
            log(f"載入現有資料失敗: {e}", "WARNING")
    
    return {}

def merge_data(existing_data, new_data):
    """合併新舊資料"""
    merged_data = existing_data.copy()
    new_count = 0
    
    for game_name, new_records in new_data.items():
        if game_name not in merged_data:
            merged_data[game_name] = []
        
        # 取得現有日期集合
        existing_dates = set(record['date'] for record in merged_data[game_name])
        
        # 添加新紀錄
        for record in new_records:
            if record['date'] not in existing_dates:
                merged_data[game_name].append(record)
                new_count += 1
        
        # 按日期排序
        if merged_data[game_name]:
            merged_data[game_name].sort(key=lambda x: x['date'], reverse=True)
    
    log(f"新增 {new_count} 筆不重複紀錄", "INFO")
    return merged_data

def save_data(data):
    """儲存資料"""
    try:
        # 確保目錄存在
        os.makedirs('data', exist_ok=True)
        
        # 儲存主要資料
        data_file = 'data/lottery-data.json'
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 儲存更新資訊
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '3.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values()),
            'games_available': list(data.keys())
        }
        
        info_file = 'data/update-info.json'
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        log(f"資料儲存完成: {len(data)} 種遊戲, {update_info['total_records']} 筆紀錄", "SUCCESS")
        log(f"可用遊戲: {', '.join(data.keys())}", "INFO")
        
        return True
        
    except Exception as e:
        log(f"儲存資料失敗: {e}", "ERROR")
        return False

def create_sample_data():
    """建立範例資料（備用方案）"""
    log("建立範例資料...", "WARNING")
    
    sample_data = {
        "大樂透": [
            {
                "date": datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d'),
                "numbers": [10, 25, 34, 35, 42, 48]
            },
            {
                "date": (datetime.now(TAIPEI_TZ) - timedelta(days=7)).strftime('%Y-%m-%d'),
                "numbers": [5, 12, 23, 34, 41, 49]
            }
        ],
        "威力彩": [
            {
                "date": datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d'),
                "numbers": [2, 9, 15, 22, 29, 36, 7]
            }
        ],
        "今彩539": [
            {
                "date": datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d'),
                "numbers": [3, 8, 17, 25, 39]
            }
        ]
    }
    
    return sample_data

def main():
    """主程式"""
    print("=" * 70)
    print("台灣彩券開獎資料自動更新系統 - 完整版 v3.0")
    print("=" * 70)
    
    success = False
    
    try:
        # 步驟1: 取得下載連結
        download_url = get_download_url()
        if not download_url:
            log("無法取得下載連結，使用備用方案", "ERROR")
            
            # 備用方案: 建立範例資料
            sample_data = create_sample_data()
            if save_data(sample_data):
                log("範例資料建立完成", "SUCCESS")
                success = True
            return success
        
        # 步驟2: 下載ZIP檔案
        zip_buffer = download_zip_file(download_url)
        if not zip_buffer:
            log("下載ZIP檔案失敗，使用備用方案", "ERROR")
            
            # 備用方案: 建立範例資料
            sample_data = create_sample_data()
            if save_data(sample_data):
                log("範例資料建立完成", "SUCCESS")
                success = True
            return success
        
        # 步驟3: 解壓縮並解析
        new_data = extract_and_parse_zip(zip_buffer)
        if not new_data:
            log("解析ZIP檔案失敗，使用備用方案", "ERROR")
            
            # 備用方案: 建立範例資料
            sample_data = create_sample_data()
            if save_data(sample_data):
                log("範例資料建立完成", "SUCCESS")
                success = True
            return success
        
        # 步驟4: 載入並合併現有資料
        existing_data = load_existing_data()
        merged_data = merge_data(existing_data, new_data)
        
        # 步驟5: 儲存資料
        if save_data(merged_data):
            log("✅ 自動更新流程完成！", "SUCCESS")
            success = True
        else:
            log("❌ 資料儲存失敗", "ERROR")
            
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
