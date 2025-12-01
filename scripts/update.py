#!/usr/bin/env python3
"""
台灣彩券自動更新腳本
自動下載官方資料並轉換為 JSON 格式
"""

import requests
import json
import os
import zipfile
import io
import re
from datetime import datetime, timedelta
import pandas as pd
import pytz
from bs4 import BeautifulSoup
import time

# 設定時區
TAIPEI_TZ = pytz.timezone('Asia/Taipei')

def get_current_year_roc():
    """取得民國年度"""
    now = datetime.now(TAIPEI_TZ)
    roc_year = now.year - 1911
    return roc_year

def get_download_url():
    """取得台灣彩券下載連結"""
    base_url = "https://www.taiwanlottery.com/lotto/history/result_download"
    
    try:
        print("正在訪問台灣彩券網站...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(base_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 尋找最新年度的下載連結
        current_roc_year = get_current_year_roc()
        
        # 嘗試不同可能的連結模式
        download_link = None
        
        # 模式1: 直接尋找包含年度數字的連結
        for year in range(current_roc_year, current_roc_year - 2, -1):
            year_str = f"{year}年度"
            link = soup.find('a', string=re.compile(year_str))
            if link and link.get('href'):
                download_link = link['href']
                print(f"找到 {year_str} 的下載連結")
                break
        
        # 模式2: 尋找所有可能的連結
        if not download_link:
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link['href']
                if 'download' in href.lower() or 'zip' in href.lower():
                    download_link = href
                    break
        
        if download_link:
            # 確保連結是完整的 URL
            if download_link.startswith('http'):
                return download_link
            elif download_link.startswith('/'):
                return f"https://www.taiwanlottery.com{download_link}"
            else:
                return f"https://www.taiwanlottery.com/{download_link}"
        
        return None
        
    except Exception as e:
        print(f"取得下載連結失敗: {e}")
        return None

def download_and_extract_zip(download_url):
    """下載並解壓縮 ZIP 檔案"""
    try:
        print(f"正在下載: {download_url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(download_url, headers=headers, timeout=60)
        response.raise_for_status()
        
        print("下載完成，開始解壓縮...")
        
        # 解壓縮 ZIP
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            # 建立暫存目錄
            temp_dir = 'temp_data'
            os.makedirs(temp_dir, exist_ok=True)
            
            # 解壓所有檔案
            zip_file.extractall(temp_dir)
            
            print(f"解壓縮完成，共 {len(zip_file.namelist())} 個檔案")
            
            return temp_dir
            
    except Exception as e:
        print(f"下載或解壓縮失敗: {e}")
        return None

def parse_csv_files(temp_dir):
    """解析 CSV 檔案並轉換為 JSON 格式"""
    all_data = {}
    
    try:
        # 檢查暫存目錄
        if not os.path.exists(temp_dir):
            print("暫存目錄不存在")
            return all_data
        
        # 尋找所有 CSV 檔案
        csv_files = [f for f in os.listdir(temp_dir) if f.lower().endswith('.csv')]
        print(f"找到 {len(csv_files)} 個 CSV 檔案")
        
        for csv_file in csv_files:
            try:
                file_path = os.path.join(temp_dir, csv_file)
                
                # 從檔名判斷遊戲類型
                game_name = None
                if '大樂透' in csv_file:
                    game_name = '大樂透'
                elif '威力彩' in csv_file:
                    game_name = '威力彩'
                elif '今彩539' in csv_file:
                    game_name = '今彩539'
                elif '雙贏彩' in csv_file:
                    game_name = '雙贏彩'
                elif '3星彩' in csv_file:
                    game_name = '三星彩'
                elif '4星彩' in csv_file:
                    game_name = '四星彩'
                elif '38樂合彩' in csv_file:
                    game_name = '38樂合彩'
                elif '49樂合彩' in csv_file:
                    game_name = '49樂合彩'
                elif '39樂合彩' in csv_file:
                    game_name = '39樂合彩'
                
                if game_name:
                    print(f"處理 {game_name} 資料...")
                    
                    # 讀取 CSV 檔案（嘗試不同編碼）
                    encodings = ['big5', 'utf-8', 'cp950']
                    df = None
                    
                    for encoding in encodings:
                        try:
                            # 使用 pandas 讀取 CSV
                            df = pd.read_csv(file_path, encoding=encoding)
                            print(f"  使用 {encoding} 編碼成功讀取")
                            break
                        except UnicodeDecodeError:
                            continue
                    
                    if df is None:
                        print(f"  無法讀取 {csv_file}，跳過")
                        continue
                    
                    # 轉換為 JSON 格式
                    game_data = []
                    
                    # 根據遊戲類型處理不同欄位
                    for _, row in df.iterrows():
                        # 嘗試找出日期欄位
                        date_col = None
                        for col in df.columns:
                            if '日期' in str(col) or 'date' in str(col).lower():
                                date_col = col
                                break
                        
                        # 嘗試找出號碼欄位
                        number_cols = []
                        for col in df.columns:
                            if any(word in str(col).lower() for word in ['號碼', 'number', 'num', '開出']):
                                number_cols.append(col)
                        
                        # 如果找不到特定欄位，嘗試所有數值欄位
                        if not number_cols:
                            for col in df.columns:
                                try:
                                    # 檢查是否為數值欄位
                                    pd.to_numeric(row[col])
                                    number_cols.append(col)
                                except:
                                    pass
                        
                        # 提取日期
                        date_str = None
                        if date_col and pd.notna(row[date_col]):
                            date_str = str(row[date_col])
                            # 清理日期格式
                            date_str = re.sub(r'[年月日]', '/', date_str)
                            date_str = re.sub(r'[/]+', '/', date_str)
                        
                        # 提取號碼
                        numbers = []
                        for col in number_cols:
                            if pd.notna(row[col]):
                                try:
                                    num = int(float(row[col]))
                                    if 0 <= num <= 99:  # 樂透號碼範圍
                                        numbers.append(num)
                                except:
                                    pass
                        
                        # 移除重複並排序
                        numbers = sorted(list(set(numbers)))
                        
                        if date_str and numbers:
                            # 檢查是否為有效日期
                            try:
                                # 嘗試解析日期
                                if len(date_str.split('/')) == 3:
                                    parts = date_str.split('/')
                                    if len(parts[0]) == 3:  # 民國年
                                        year = int(parts[0]) + 1911
                                        date_obj = datetime(year, int(parts[1]), int(parts[2]))
                                    else:
                                        date_obj = datetime.strptime(date_str, '%Y/%m/%d')
                                    
                                    game_data.append({
                                        'date': date_obj.strftime('%Y-%m-%d'),
                                        'numbers': numbers
                                    })
                            except:
                                # 如果日期解析失敗，仍保留資料
                                game_data.append({
                                    'date': date_str,
                                    'numbers': numbers
                                })
                    
                    if game_data:
                        # 按日期排序（最新的在前面）
                        game_data.sort(key=lambda x: x['date'], reverse=True)
                        all_data[game_name] = game_data
                        print(f"  成功解析 {len(game_data)} 筆資料")
                        
            except Exception as e:
                print(f"處理 {csv_file} 時發生錯誤: {e}")
                continue
        
        return all_data
        
    except Exception as e:
        print(f"解析 CSV 檔案失敗: {e}")
        return all_data
    finally:
        # 清理暫存目錄
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def load_existing_data():
    """載入現有的資料"""
    data_file = 'data/lottery-data.json'
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def merge_data(existing_data, new_data):
    """合併新舊資料"""
    merged_data = existing_data.copy()
    
    for game_name, new_records in new_data.items():
        if game_name not in merged_data:
            merged_data[game_name] = []
        
        # 取得現有資料的日期集合
        existing_dates = set(record['date'] for record in merged_data[game_name])
        
        # 添加新資料（避免重複）
        added_count = 0
        for new_record in new_records:
            if new_record['date'] not in existing_dates:
                merged_data[game_name].append(new_record)
                added_count += 1
        
        if added_count > 0:
            # 重新排序
            merged_data[game_name].sort(key=lambda x: x['date'], reverse=True)
            print(f"為 {game_name} 新增了 {added_count} 筆資料")
    
    return merged_data

def save_data(data):
    """儲存資料到檔案"""
    try:
        # 確保 data 目錄存在
        os.makedirs('data', exist_ok=True)
        
        # 儲存主要資料
        data_file = 'data/lottery-data.json'
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 儲存更新資訊
        update_info = {
            'last_updated': datetime.now(TAIPEI_TZ).isoformat(),
            'data_version': '1.0',
            'total_games': len(data),
            'total_records': sum(len(records) for records in data.values())
        }
        
        info_file = 'data/update-info.json'
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(update_info, f, ensure_ascii=False, indent=2)
        
        print(f"資料儲存完成，共 {len(data)} 種遊戲，總計 {update_info['total_records']} 筆紀錄")
        return True
        
    except Exception as e:
        print(f"儲存資料失敗: {e}")
        return False

def main():
    """主程式"""
    print("=" * 50)
    print("台灣彩券自動更新程式啟動")
    print("=" * 50)
    
    # 載入現有資料
    existing_data = load_existing_data()
    print(f"已載入現有資料: {len(existing_data)} 種遊戲")
    
    # 取得下載連結
    download_url = get_download_url()
    if not download_url:
        print("無法取得下載連結，將保留現有資料")
        return False
    
    # 下載並解壓縮
    temp_dir = download_and_extract_zip(download_url)
    if not temp_dir:
        print("下載失敗，將保留現有資料")
        return False
    
    # 解析 CSV 檔案
    new_data = parse_csv_files(temp_dir)
    if not new_data:
        print("解析失敗，將保留現有資料")
        return False
    
    # 合併新舊資料
    merged_data = merge_data(existing_data, new_data)
    
    # 儲存資料
    if save_data(merged_data):
        print("✅ 資料更新完成！")
        return True
    else:
        print("❌ 資料更新失敗")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        print("程式執行完成，但沒有新資料被更新")
    print("=" * 50)