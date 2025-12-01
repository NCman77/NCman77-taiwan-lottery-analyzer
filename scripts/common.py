#!/usr/bin/env python3
"""
台灣彩券開獎資料系統 - 共用函數模組
版本: 2.0
"""

import json
import os
import csv
import zipfile
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import pytz

# ========== 配置區域 ==========
TAIPEI_TZ = pytz.timezone('Asia/Taipei')

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

# 民國年轉西元年對照表（110年-114年）
ROCN_YEAR_MAP = {
    110: 2021,
    111: 2022,
    112: 2023,
    113: 2024,
    114: 2025,
    115: 2026
}

# ========== 共用工具函數 ==========
def log(message: str, level: str = "INFO"):
    """統一日誌輸出函數"""
    timestamp = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌", "IMPORT": "📥", "ZIP": "📦"}
    icon = icons.get(level, "ℹ️")
    print(f"[{timestamp}] {icon} {message}")

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
