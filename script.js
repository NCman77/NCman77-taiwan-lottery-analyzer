// 台灣彩券自動分析系統 - 主邏輯
document.addEventListener('DOMContentLoaded', async () => {
    // 設定資料來源
    const DATA_URL = 'data/lottery-data.json';
    const UPDATE_INFO_URL = 'data/update-info.json';
    
    let lotteryData = {};
    let gameList = [];
    
    // 初始化
    await init();
    
    // 初始化函數
    async function init() {
        try {
            updateStatus('正在載入最新開獎資料...');
            
            // 載入資料
            await loadData();
            
            // 初始化遊戲選擇
            initGameSelect();
            
            // 顯示系統資訊
            showSystemInfo();
            
            // 預設顯示第一個遊戲
            if (gameList.length > 0) {
                document.getElementById('game-select').value = gameList[0];
                updateGameDisplay(gameList[0]);
            }
            
            updateStatus('資料載入完成！', 'success');
            document.getElementById('data-area').classList.remove('hidden');
            
        } catch (error) {
            console.error('初始化失敗:', error);
            showError('無法載入開獎資料，請稍後再試或檢查系統狀態。');
            updateStatus('資料載入失敗', 'error');
        }
    }
    
    // 載入資料
    async function loadData() {
        try {
            const response = await fetch(`${DATA_URL}?t=${Date.now()}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            lotteryData = data.data || data;
            
            // 取得遊戲列表
            gameList = Object.keys(lotteryData).filter(key => 
                lotteryData[key] && Array.isArray(lotteryData[key])
            );
            
            console.log(`成功載入 ${gameList.length} 種遊戲資料`);
            
        } catch (error) {
            console.error('載入資料失敗:', error);
            throw error;
        }
    }
    
    // 初始化遊戲選擇下拉
    function initGameSelect() {
        const select = document.getElementById('game-select');
        select.innerHTML = '<option value="">請選擇遊戲</option>';
        
        gameList.forEach(game => {
            const option = document.createElement('option');
            option.value = game;
            option.textContent = game;
            select.appendChild(option);
        });
        
        // 綁定變更事件
        select.addEventListener('change', (e) => {
            if (e.target.value) {
                updateGameDisplay(e.target.value);
            }
        });
    }
    
    // 更新遊戲顯示
    function updateGameDisplay(gameName) {
        const gameData = lotteryData[gameName];
        if (!gameData || gameData.length === 0) return;
        
        // 顯示最新開獎
        const latest = gameData[0];
        displayLatestDraw(latest, gameName);
        
        // 顯示本月熱門
        displayMonthHot(gameData, gameName);
        
        // 顯示年度統計
        displayYearStats(gameData);
        
        // 顯示歷史紀錄
        displayHistory(gameData);
    }
    
    // 顯示最新開獎
    function displayLatestDraw(draw, gameName) {
        const container = document.getElementById('latest-draw');
        container.innerHTML = `
            <div class="mb-1"><strong>${draw.date || '最新開獎'}</strong></div>
            <div class="flex flex-wrap gap-1">
                ${draw.numbers.map(num => 
                    `<div class="ball bg-blue-500 text-white">${num}</div>`
                ).join('')}
            </div>
        `;
    }
    
    // 顯示本月熱門
    function displayMonthHot(gameData, gameName) {
        const now = new Date();
        const currentMonth = now.getMonth();
        const currentYear = now.getFullYear();
        
        const monthData = gameData.filter(draw => {
            const drawDate = new Date(draw.date);
            return drawDate.getMonth() === currentMonth && 
                   drawDate.getFullYear() === currentYear;
        });
        
        // 計算熱門號碼
        const freq = {};
        monthData.forEach(draw => {
            draw.numbers.forEach(num => {
                freq[num] = (freq[num] || 0) + 1;
            });
        });
        
        const hotNumbers = Object.entries(freq)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 6);
        
        const container = document.getElementById('month-hot');
        if (hotNumbers.length > 0) {
            container.innerHTML = hotNumbers.map(([num, count]) => `
                <div class="inline-flex flex-col items-center mx-1">
                    <div class="ball bg-red-500 text-white">${num}</div>
                    <span class="text-xs mt-1">${count}次</span>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="text-gray-500">本月尚無資料</p>';
        }
    }
    
    // 顯示年度統計
    function displayYearStats(gameData) {
        const container = document.getElementById('year-stats');
        const totalDraws = gameData.length;
        
        // 計算平均開獎間隔
        let avgInterval = 'N/A';
        if (gameData.length >= 2) {
            const dates = gameData.map(d => new Date(d.date));
            const intervals = [];
            for (let i = 1; i < dates.length; i++) {
                intervals.push(dates[i-1] - dates[i]);
            }
            const avgMs = intervals.reduce((a, b) => a + b, 0) / intervals.length;
            avgInterval = Math.round(avgMs / (1000 * 60 * 60 * 24)) + '天';
        }
        
        container.innerHTML = `
            <p>總開獎期數: ${totalDraws}</p>
            <p>資料期間: ${gameData[gameData.length-1]?.date || ''} ~ ${gameData[0]?.date || ''}</p>
            <p>平均間隔: ${avgInterval}</p>
        `;
    }
    
    // 顯示歷史紀錄
    function displayHistory(gameData) {
        const tbody = document.getElementById('history-table');
        const recentData = gameData.slice(0, 20); // 顯示最近20期
        
        tbody.innerHTML = recentData.map(draw => `
            <tr class="border-b hover:bg-gray-50">
                <td class="p-3">${draw.drawNo || ''}<br><span class="text-sm text-gray-500">${draw.date}</span></td>
                <td class="p-3">
                    <div class="flex flex-wrap gap-1">
                        ${draw.numbers.map(num => 
                            `<div class="ball bg-blue-100 text-blue-700">${num}</div>`
                        ).join('')}
                    </div>
                </td>
            </tr>
        `).join('');
    }
    
    // 顯示系統資訊
    async function showSystemInfo() {
        try {
            const response = await fetch(UPDATE_INFO_URL);
            if (response.ok) {
                const info = await response.json();
                const container = document.getElementById('sys-info');
                const lastUpdate = new Date(info.last_updated).toLocaleString('zh-TW');
                container.innerHTML = `
                    <p>最後更新: ${lastUpdate}</p>
                    <p>資料版本: ${info.data_version || '1.0'}</p>
                    <p>自動更新: 已啟用</p>
                `;
                
                // 更新頁面上的最後更新時間
                document.getElementById('last-update').textContent = 
                    `最後更新時間：${lastUpdate}`;
            }
        } catch (error) {
            console.error('無法載入更新資訊:', error);
        }
    }
    
    // 更新狀態顯示
    function updateStatus(message, type = 'loading') {
        const statusEl = document.getElementById('status');
        if (type === 'success') {
            statusEl.innerHTML = `<span class="text-green-600">✅ ${message}</span>`;
        } else if (type === 'error') {
            statusEl.innerHTML = `<span class="text-red-600">❌ ${message}</span>`;
        } else {
            statusEl.innerHTML = `
                <div class="loader"></div>
                <span>${message}</span>
            `;
        }
    }
    
    // 顯示錯誤訊息
    function showError(message) {
        const errorEl = document.getElementById('error-message');
        const errorText = document.getElementById('error-text');
        errorText.textContent = message;
        errorEl.classList.remove('hidden');
    }
});