// ===== DOM 元素 =====
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const selectedFile = document.getElementById('selectedFile');
const fileName = document.getElementById('fileName');
const removeFile = document.getElementById('removeFile');
const uploadBtn = document.getElementById('uploadBtn');
const statusCard = document.getElementById('statusCard');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const statusMessage = document.getElementById('statusMessage');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const resultsContainer = document.getElementById('resultsContainer');

// ===== 狀態變數 =====
let selectedVideoFile = null;
let statusPollInterval = null;
let isSearchEnabled = false;

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    initUploadEvents();
    initSearchEvents();
    checkExistingDatabase();
});

// ===== 上傳功能 =====
function initUploadEvents() {
    // 點擊上傳區域
    uploadArea.addEventListener('click', () => fileInput.click());

    // 拖放事件
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });

    // 檔案選擇
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    // 移除檔案
    removeFile.addEventListener('click', () => {
        selectedVideoFile = null;
        selectedFile.style.display = 'none';
        uploadArea.style.display = 'block';
        uploadBtn.disabled = true;
        fileInput.value = '';
    });

    // 上傳按鈕
    uploadBtn.addEventListener('click', uploadVideo);
}

function handleFileSelect(file) {
    const allowedExtensions = ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v'];
    const ext = file.name.split('.').pop().toLowerCase();

    if (!allowedExtensions.includes(ext)) {
        alert('不支援的檔案格式，請上傳 MP4, MKV, AVI, MOV 等影片格式');
        return;
    }

    selectedVideoFile = file;
    fileName.textContent = file.name;
    selectedFile.style.display = 'flex';
    uploadArea.style.display = 'none';
    uploadBtn.disabled = false;
}

async function uploadVideo() {
    if (!selectedVideoFile) return;

    uploadBtn.disabled = true;
    uploadBtn.textContent = '上傳中...';

    const formData = new FormData();
    formData.append('video', selectedVideoFile);

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            showStatusCard();
            startStatusPolling();
        } else {
            alert(data.error || '上傳失敗');
            resetUploadButton();
        }
    } catch (error) {
        console.error('上傳錯誤:', error);
        alert('上傳失敗，請檢查伺服器是否正常運作');
        resetUploadButton();
    }
}

function resetUploadButton() {
    uploadBtn.disabled = false;
    uploadBtn.textContent = '開始處理';
}

// ===== 狀態輪詢 =====
function showStatusCard() {
    statusCard.style.display = 'block';
    updateStages(null);
}

function startStatusPolling() {
    statusPollInterval = setInterval(pollStatus, 1000);
    pollStatus(); // 立即執行一次
}

function stopStatusPolling() {
    if (statusPollInterval) {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
    }
}

async function pollStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();

        updateProgress(status.progress);
        updateStages(status.current_stage);
        updateStatusMessage(status.message, status.error);

        if (!status.is_processing && status.current_stage === 'complete') {
            stopStatusPolling();
            enableSearch();
            showSuccessMessage();
        } else if (status.error) {
            stopStatusPolling();
            resetUploadButton();
        }
    } catch (error) {
        console.error('狀態查詢錯誤:', error);
    }
}

function updateProgress(progress) {
    progressFill.style.width = `${progress}%`;
    progressText.textContent = `${progress}%`;
}

function updateStages(currentStage) {
    const stages = ['transcribe', 'screenshots', 'rag'];
    const stageOrder = { 'transcribe': 0, 'screenshots': 1, 'rag': 2, 'complete': 3 };
    const currentIndex = stageOrder[currentStage] ?? -1;

    stages.forEach((stage, index) => {
        const element = document.getElementById(`stage-${stage}`);
        element.classList.remove('active', 'completed');

        if (index < currentIndex) {
            element.classList.add('completed');
        } else if (index === currentIndex) {
            element.classList.add('active');
        }
    });

    // 如果完成，所有都標記為完成
    if (currentStage === 'complete') {
        stages.forEach(stage => {
            const element = document.getElementById(`stage-${stage}`);
            element.classList.remove('active');
            element.classList.add('completed');
        });
    }
}

function updateStatusMessage(message, error) {
    statusMessage.textContent = message;
    statusMessage.classList.remove('error', 'success');

    if (error) {
        statusMessage.classList.add('error');
    }
}

function showSuccessMessage() {
    statusMessage.textContent = '處理完成！現在可以開始搜尋影片內容。';
    statusMessage.classList.add('success');

    // 隱藏上傳區塊
    selectedFile.style.display = 'none';
    uploadArea.style.display = 'block';
    uploadBtn.textContent = '上傳新影片';
    uploadBtn.disabled = true;
    selectedVideoFile = null;
    fileInput.value = '';
}

// ===== 搜尋功能 =====
function initSearchEvents() {
    searchBtn.addEventListener('click', performSearch);

    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && isSearchEnabled) {
            performSearch();
        }
    });
}

function enableSearch() {
    isSearchEnabled = true;
    searchInput.disabled = false;
    searchBtn.disabled = false;
    searchInput.placeholder = '輸入關鍵字或問句進行搜尋...';

    resultsContainer.innerHTML = `
        <div class="card placeholder-card">
            <p class="placeholder-text">輸入關鍵字開始搜尋影片內容</p>
        </div>
    `;
}

async function checkExistingDatabase() {
    try {
        // 嘗試一個簡單的搜尋來檢查資料庫是否存在
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: 'test', top_k: 1 })
        });

        if (response.ok) {
            enableSearch();
        }
    } catch (error) {
        // 資料庫不存在，保持禁用狀態
    }
}

async function performSearch() {
    const query = searchInput.value.trim();
    if (!query) return;

    searchBtn.disabled = true;
    resultsContainer.innerHTML = `
        <div class="loading">
            <div class="loading-spinner"></div>
            <span>搜尋中...</span>
        </div>
    `;

    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, top_k: 5 })
        });

        const data = await response.json();

        if (response.ok) {
            displayResults(data.results);
        } else {
            resultsContainer.innerHTML = `
                <div class="card placeholder-card">
                    <p class="placeholder-text" style="color: var(--danger);">
                        ${data.error || '搜尋失敗'}
                    </p>
                </div>
            `;
        }
    } catch (error) {
        console.error('搜尋錯誤:', error);
        resultsContainer.innerHTML = `
            <div class="card placeholder-card">
                <p class="placeholder-text" style="color: var(--danger);">搜尋失敗，請稍後再試</p>
            </div>
        `;
    } finally {
        searchBtn.disabled = false;
    }
}

function displayResults(results) {
    if (!results || results.length === 0) {
        resultsContainer.innerHTML = `
            <div class="card placeholder-card">
                <p class="placeholder-text">未找到相關內容</p>
            </div>
        `;
        return;
    }

    resultsContainer.innerHTML = results.map((item, index) => `
        <div class="card result-card">
            <div class="result-header">
                <span class="result-score">相似度 ${(item.score * 100).toFixed(1)}%</span>
                <span class="result-time">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <polyline points="12 6 12 12 16 14"/>
                    </svg>
                    ${item.start_time} - ${item.end_time}
                </span>
            </div>
            
            <div class="result-content">
                ${item.speaker ? `<span class="result-speaker">[${item.speaker}]</span>` : ''}
                ${escapeHtml(item.content)}
            </div>
            
            ${item.start_image_url || item.end_image_url ? `
                <div class="result-images">
                    ${item.start_image_url ? `
                        <div class="result-image-container">
                            <img src="${item.start_image_url}" alt="開始畫面" loading="lazy">
                            <div class="image-label">開始 ${item.start_time}</div>
                        </div>
                    ` : ''}
                    ${item.end_image_url ? `
                        <div class="result-image-container">
                            <img src="${item.end_image_url}" alt="結束畫面" loading="lazy">
                            <div class="image-label">結束 ${item.end_time}</div>
                        </div>
                    ` : ''}
                </div>
            ` : ''}
        </div>
    `).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
