"""
影片逐字稿理解系統 - 後端 API
提供影片上傳、處理狀態查詢、語意搜尋等功能
"""

import os
import sys
import json
import time
import threading
import traceback
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

# 設定路徑
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
INPUT_DIR = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
SCREENSHOTS_DIR = OUTPUT_DIR / 'screenshots'

# 將各模組的路徑加入 sys.path
sys.path.insert(0, str(ROOT_DIR / '1_逐字稿擷取'))
sys.path.insert(0, str(ROOT_DIR / '2_逐字稿圖片擷取'))
sys.path.insert(0, str(ROOT_DIR / '3_RAG_database'))

# 設定 Flask
app = Flask(__name__, static_folder=str(ROOT_DIR / '5_frontend'))
CORS(app)

# 允許的影片格式
ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v'}

# 處理狀態
processing_status = {
    'is_processing': False,
    'current_stage': None,
    'progress': 0,
    'message': '',
    'error': None
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_status(stage, progress, message, error=None):
    global processing_status
    processing_status['current_stage'] = stage
    processing_status['progress'] = progress
    processing_status['message'] = message
    processing_status['error'] = error
    print(f"[{stage}] {progress}% - {message}")

def process_video(video_filename):
    """在背景處理影片的完整流程"""
    global processing_status
    
    processing_status['is_processing'] = True
    processing_status['error'] = None
    
    try:
        # 階段 1: 逐字稿擷取
        update_status('transcribe', 10, '開始轉錄影片...')
        
        # 動態引入模組
        transcribe_path = ROOT_DIR / '1_逐字稿擷取' / 'transcribe.py'
        api_key_path = ROOT_DIR / '1_逐字稿擷取' / 'api_key.json'
        
        # 載入 API 金鑰
        with open(api_key_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        api_key = config['openai']['api_key']
        
        # 執行轉錄
        import importlib.util
        spec = importlib.util.spec_from_file_location("transcribe", transcribe_path)
        transcribe_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transcribe_module)
        
        video_path = INPUT_DIR / video_filename
        temp_dir = ROOT_DIR / 'temp'
        temp_dir.mkdir(exist_ok=True)
        OUTPUT_DIR.mkdir(exist_ok=True)
        
        # 提取音訊
        update_status('transcribe', 20, '提取音訊中...')
        audio_path = transcribe_module.extract_audio_from_video(video_path, temp_dir)
        
        if audio_path is None:
            raise Exception("無法提取音訊")
        
        # 轉錄
        update_status('transcribe', 30, '使用 GPT-4o 轉錄中（這可能需要幾分鐘）...')
        transcript_result = transcribe_module.transcribe_audio_gpt4o(audio_path, api_key)
        
        if not transcript_result['success']:
            raise Exception(f"轉錄失敗: {transcript_result.get('error')}")
        
        # 儲存結果
        update_status('transcribe', 40, '儲存逐字稿...')
        from datetime import datetime
        result = {
            'filename': video_filename,
            'text': transcript_result['text'],
            'segments': transcript_result.get('segments', []),
            'language': transcript_result.get('language', 'zh'),
            'duration': transcript_result.get('duration', 0),
            'processed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 儲存 CSV
        transcribe_module.save_to_csv([result], OUTPUT_DIR / 'transcripts.csv')
        
        # 儲存詳細逐字稿
        detail_path = OUTPUT_DIR / f"{video_path.stem}_transcript.md"
        transcribe_module.save_detailed_transcript(result, detail_path)
        
        # 清理暫存
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        
        # 階段 2: 截圖擷取
        update_status('screenshots', 50, '開始擷取截圖...')
        
        extract_path = ROOT_DIR / '2_逐字稿圖片擷取' / 'extract_screenshots.py'
        spec = importlib.util.spec_from_file_location("extract_screenshots", extract_path)
        extract_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(extract_module)
        
        update_status('screenshots', 60, '擷取影片畫面中...')
        extract_module.extract_frames()
        
        # 階段 3: RAG 資料庫
        update_status('rag', 70, '建立向量索引...')
        
        ingest_path = ROOT_DIR / '3_RAG_database' / 'rag_ingest.py'
        spec = importlib.util.spec_from_file_location("rag_ingest", ingest_path)
        ingest_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ingest_module)
        
        update_status('rag', 80, '載入 CLIP 模型並產生嵌入向量...')
        ingest_module.ingest()
        
        update_status('complete', 100, '處理完成！')
        
    except Exception as e:
        error_msg = str(e)
        traceback.print_exc()
        update_status('error', 0, f'處理失敗: {error_msg}', error_msg)
    
    finally:
        processing_status['is_processing'] = False

# ===== API 路由 =====

@app.route('/')
def index():
    """提供前端頁面"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """提供靜態檔案"""
    return send_from_directory(app.static_folder, filename)

@app.route('/api/upload', methods=['POST'])
def upload_video():
    """上傳影片並開始處理"""
    global processing_status
    
    if processing_status['is_processing']:
        return jsonify({'error': '目前有影片正在處理中，請稍候'}), 400
    
    if 'video' not in request.files:
        return jsonify({'error': '未選擇檔案'}), 400
    
    file = request.files['video']
    
    if file.filename == '':
        return jsonify({'error': '未選擇檔案'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': f'不支援的檔案格式，請上傳 {", ".join(ALLOWED_EXTENSIONS)} 格式'}), 400
    
    # 儲存檔案
    INPUT_DIR.mkdir(exist_ok=True)
    filename = secure_filename(file.filename)
    file_path = INPUT_DIR / filename
    file.save(str(file_path))
    
    # 在背景執行處理
    thread = threading.Thread(target=process_video, args=(filename,))
    thread.start()
    
    return jsonify({
        'success': True,
        'message': '檔案上傳成功，開始處理...',
        'filename': filename
    })

@app.route('/api/status')
def get_status():
    """取得處理狀態"""
    return jsonify(processing_status)

@app.route('/api/search', methods=['POST'])
def search():
    """語意搜尋"""
    data = request.get_json()
    query = data.get('query', '')
    top_k = data.get('top_k', 5)
    
    if not query:
        return jsonify({'error': '請輸入查詢文字'}), 400
    
    # 檢查 RAG 資料庫是否存在
    db_path = OUTPUT_DIR / 'rag_mm.db'
    index_path = OUTPUT_DIR / 'transcript.index'
    
    if not db_path.exists() or not index_path.exists():
        return jsonify({'error': '尚未建立資料庫，請先上傳並處理影片'}), 400
    
    try:
        # 動態引入搜尋模組
        query_path = ROOT_DIR / '3_RAG_database' / 'rag_query.py'
        import importlib.util
        spec = importlib.util.spec_from_file_location("rag_query", query_path)
        query_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(query_module)
        
        results = query_module.search(query, top_k=top_k)
        
        if isinstance(results, dict) and 'error' in results:
            return jsonify(results), 400
        
        # 轉換圖片路徑為 API URL
        for item in results:
            if item.get('start_image'):
                img_name = os.path.basename(item['start_image'])
                item['start_image_url'] = f'/api/image/{img_name}'
            else:
                item['start_image_url'] = None
                
            if item.get('end_image'):
                img_name = os.path.basename(item['end_image'])
                item['end_image_url'] = f'/api/image/{img_name}'
            else:
                item['end_image_url'] = None
        
        return jsonify({'results': results})
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/image/<filename>')
def get_image(filename):
    """取得截圖"""
    return send_from_directory(str(SCREENSHOTS_DIR), filename)

if __name__ == '__main__':
    print("=" * 50)
    print("影片逐字稿理解系統 - 後端伺服器")
    print("=" * 50)
    print(f"根目錄: {ROOT_DIR}")
    print(f"輸入目錄: {INPUT_DIR}")
    print(f"輸出目錄: {OUTPUT_DIR}")
    print(f"前端目錄: {app.static_folder}")
    print("=" * 50)
    print("啟動伺服器: http://localhost:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
