"""
影片/音訊轉逐字稿程式
使用 OpenAI GPT-4o-transcribe-diarize API（非 Whisper）進行轉錄
支援時間戳記輸出：幾分幾秒講哪句話
"""

import os
import json
import subprocess
import sys
from pathlib import Path
import requests
import csv
from datetime import datetime

# 支援的影片格式
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
# 支援的音訊格式
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma'}
# OpenAI API 支援的音訊格式
OPENAI_SUPPORTED_FORMATS = {'.flac', '.m4a', '.mp3', '.mp4', '.mpeg', '.mpga', '.oga', '.ogg', '.wav', '.webm'}


def load_api_key(config_path: str) -> str:
    """從設定檔載入 OpenAI API 金鑰"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config['openai']['api_key']


def get_media_files(input_dir: str) -> list:
    """取得 input 資料夾內所有影片和音訊檔案"""
    media_files = []
    input_path = Path(input_dir)
    
    if not input_path.exists():
        print(f"錯誤：找不到 input 資料夾: {input_dir}")
        return media_files
    
    for file in input_path.iterdir():
        if file.is_file():
            ext = file.suffix.lower()
            if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS:
                media_files.append(file)
    
    return media_files


def extract_audio_from_video(video_path: Path, output_dir: Path) -> Path:
    """使用 ffmpeg 從影片中提取音訊"""
    # 輸出為 m4a 格式，使用 Windows 內建的 aac 編碼器
    audio_path = output_dir / f"{video_path.stem}_audio.m4a"
    
    if audio_path.exists():
        print(f"  音訊檔案已存在，跳過提取: {audio_path.name}")
        return audio_path
    
    print(f"  從影片提取音訊...")
    
    try:
        # 使用 ffmpeg 提取音訊（使用 Windows MediaFoundation AAC 編碼器）
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-vn',  # 不處理影片
            '-acodec', 'aac',  # 使用 aac 編碼
            '-b:a', '128k',  # 位元率
            '-ar', '16000',  # 取樣率（OpenAI 建議 16kHz）
            '-ac', '1',  # 單聲道
            '-y',  # 覆蓋輸出檔案
            str(audio_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        if result.returncode != 0:
            print(f"  ffmpeg 錯誤: {result.stderr}")
            return None
            
        print(f"  音訊提取成功: {audio_path.name}")
        return audio_path
        
    except FileNotFoundError:
        print("  錯誤：找不到 ffmpeg，請先安裝 ffmpeg")
        print("  安裝方式：")
        print("    Windows: winget install ffmpeg")
        print("    或從 https://ffmpeg.org/download.html 下載")
        return None
    except Exception as e:
        print(f"  提取音訊時發生錯誤: {e}")
        return None


def format_time(seconds: float) -> str:
    """將秒數格式化為 MM:SS 格式"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def transcribe_audio_gpt4o(audio_path: Path, api_key: str) -> dict:
    """
    使用 OpenAI GPT-4o-transcribe-diarize API 進行轉錄
    注意：這使用的是 gpt-4o-transcribe-diarize 模型，不是 Whisper
    此模型支援時間戳記和語者分離功能
    """
    url = "https://api.openai.com/v1/audio/transcriptions"
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    # 檢查檔案大小（OpenAI 限制 25MB）
    file_size = audio_path.stat().st_size
    max_size = 25 * 1024 * 1024  # 25MB
    
    if file_size > max_size:
        print(f"  警告：檔案大小 ({file_size / 1024 / 1024:.2f}MB) 超過 25MB 限制")
        print(f"  需要分割檔案處理...")
        return transcribe_large_audio(audio_path, api_key)
    
    try:
        with open(audio_path, 'rb') as audio_file:
            files = {
                'file': (audio_path.name, audio_file, 'audio/mp4')
            }
            data = {
                'model': 'gpt-4o-transcribe-diarize',  # 使用 GPT-4o 語者分離轉錄模型，非 Whisper
                'response_format': 'diarized_json',  # 使用帶時間戳記的 JSON 格式
                'chunking_strategy': 'auto'  # 語者分離模型必須的參數
                # 不指定 language，讓 API 自動偵測語言
            }
            
            print(f"  正在使用 GPT-4o-transcribe-diarize API 轉錄（含時間戳記）...")
            
            response = requests.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=600  # 10 分鐘超時
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # 解析 diarized_json 格式的回應
                segments = []
                full_text_parts = []
                max_end_time = 0
                
                # diarized_json 格式會回傳 segments 陣列
                raw_segments = result.get('segments', [])
                
                for seg in raw_segments:
                    start = seg.get('start', 0)
                    end = seg.get('end', 0)
                    speaker = seg.get('speaker', 'Speaker')
                    text = seg.get('transcript', seg.get('text', ''))
                    
                    segments.append({
                        'start': start,
                        'end': end,
                        'speaker': speaker,
                        'text': text
                    })
                    
                    full_text_parts.append(text)
                    max_end_time = max(max_end_time, end)
                
                # 如果沒有 segments，嘗試取得純文字
                if not segments and result.get('text'):
                    full_text = result.get('text', '')
                else:
                    full_text = ' '.join(full_text_parts)
                
                # 取得偵測到的語言
                detected_language = result.get('language', 'unknown')
                
                return {
                    'success': True,
                    'text': full_text,
                    'segments': segments,
                    'language': detected_language,
                    'duration': max_end_time
                }
            else:
                error_msg = response.json().get('error', {}).get('message', response.text)
                print(f"  API 錯誤 ({response.status_code}): {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
    except requests.exceptions.Timeout:
        print("  錯誤：API 請求超時")
        return {'success': False, 'error': '請求超時'}
    except Exception as e:
        print(f"  轉錄時發生錯誤: {e}")
        return {'success': False, 'error': str(e)}


def split_audio(audio_path: Path, output_dir: Path, segment_duration: int = 600) -> list:
    """將大型音訊檔案分割成較小的片段（預設每段 10 分鐘）"""
    segments = []
    
    # 先取得音訊總長度
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(audio_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        total_duration = float(result.stdout.strip())
    except:
        print("  無法取得音訊長度，使用預設分割")
        total_duration = 3600  # 假設 1 小時
    
    # 計算需要幾個片段
    num_segments = int(total_duration / segment_duration) + 1
    
    print(f"  音訊總長度: {total_duration:.1f} 秒，將分割為 {num_segments} 個片段")
    
    for i in range(num_segments):
        start_time = i * segment_duration
        segment_path = output_dir / f"{audio_path.stem}_segment_{i:03d}.m4a"
        
        cmd = [
            'ffmpeg',
            '-i', str(audio_path),
            '-ss', str(start_time),
            '-t', str(segment_duration),
            '-acodec', 'aac',
            '-b:a', '128k',
            '-ar', '16000',
            '-ac', '1',
            '-y',
            str(segment_path)
        ]
        
        subprocess.run(cmd, capture_output=True)
        
        if segment_path.exists() and segment_path.stat().st_size > 0:
            segments.append({
                'path': segment_path,
                'start_time': start_time
            })
    
    return segments


def transcribe_large_audio(audio_path: Path, api_key: str) -> dict:
    """處理超過 25MB 限制的大型音訊檔案"""
    temp_dir = audio_path.parent / 'temp_segments'
    temp_dir.mkdir(exist_ok=True)
    
    try:
        # 分割音訊
        segments = split_audio(audio_path, temp_dir)
        
        all_text = []
        all_segments = []
        total_duration = 0
        
        for i, segment_info in enumerate(segments):
            print(f"  轉錄片段 {i + 1}/{len(segments)}...")
            result = transcribe_audio_gpt4o(segment_info['path'], api_key)
            
            if result['success']:
                all_text.append(result['text'])
                
                # 調整時間戳記
                for seg in result.get('segments', []):
                    seg['start'] += segment_info['start_time']
                    seg['end'] += segment_info['start_time']
                    all_segments.append(seg)
                
                total_duration += result.get('duration', 0)
            else:
                print(f"  片段 {i + 1} 轉錄失敗: {result.get('error')}")
        
        return {
            'success': True,
            'text': ' '.join(all_text),
            'segments': all_segments,
            'language': 'auto',  # 多片段合併時語言標記為 auto
            'duration': total_duration
        }
        
    finally:
        # 清理暫存檔案
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def save_to_csv(results: list, output_path: Path):
    """將轉錄結果儲存為 CSV 檔案（包含時間戳記）"""
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        # 標題列：包含檔案名、時間、講者、內容
        writer.writerow(['檔案名稱', '開始時間', '結束時間', '講者', '內容', '偵測語言', '處理時間'])
        
        for result in results:
            filename = result['filename']
            language = result['language']
            processed_at = result['processed_at']
            
            # 如果有時間戳記片段，每個片段寫一行
            if result.get('segments'):
                for seg in result['segments']:
                    start = seg.get('start', 0)
                    end = seg.get('end', 0)
                    speaker = seg.get('speaker', '')
                    text = seg.get('text', '')
                    
                    # 格式化時間
                    start_str = format_time(start)
                    end_str = format_time(end)
                    
                    writer.writerow([
                        filename,
                        start_str,
                        end_str,
                        speaker,
                        text,
                        language,
                        processed_at
                    ])
            else:
                # 如果沒有時間戳記，寫入完整文字
                duration_str = format_time(result['duration']) if result['duration'] > 0 else '00:00'
                writer.writerow([
                    filename,
                    '00:00',
                    duration_str,
                    '',
                    result['text'],
                    language,
                    processed_at
                ])
    
    print(f"\nCSV 結果已儲存至: {output_path}")


def save_detailed_transcript(result: dict, output_path: Path):
    """儲存包含時間戳記的詳細逐字稿"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# {result['filename']} 逐字稿\n\n")
        f.write(f"處理時間: {result['processed_at']}\n")
        f.write(f"語言: {result['language']}\n")
        
        # 格式化時長
        duration = result['duration']
        if duration > 0:
            duration_str = format_time(duration)
            f.write(f"時長: {duration_str} ({duration:.2f} 秒)\n\n")
        else:
            f.write(f"時長: 未知\n\n")
        
        f.write("---\n\n")
        
        # 如果有時間戳記片段，輸出詳細版本
        if result.get('segments'):
            f.write("## 時間戳記版本\n\n")
            f.write("| 時間 | 講者 | 內容 |\n")
            f.write("|------|------|------|\n")
            
            for seg in result['segments']:
                start = seg.get('start', 0)
                end = seg.get('end', 0)
                speaker = seg.get('speaker', '')
                text = seg.get('text', '')
                
                # 格式化時間
                start_str = format_time(start)
                end_str = format_time(end)
                
                # 處理文字中的換行和特殊字元
                text_clean = text.replace('\n', ' ').replace('|', '\\|')
                
                f.write(f"| {start_str} - {end_str} | {speaker} | {text_clean} |\n")
            
            f.write("\n---\n\n")
            
            # 也輸出純文字格式（方便複製）
            f.write("## 純文字時間戳記版本\n\n")
            for seg in result['segments']:
                start = seg.get('start', 0)
                speaker = seg.get('speaker', '')
                text = seg.get('text', '')
                start_str = format_time(start)
                
                if speaker:
                    f.write(f"[{start_str}] {speaker}: {text}\n")
                else:
                    f.write(f"[{start_str}] {text}\n")
            
            f.write("\n---\n\n")
        
        f.write("## 完整文字\n\n")
        f.write(result['text'])


def main():
    # 取得腳本所在目錄，使用上層目錄的共用 input/output 資料夾
    script_dir = Path(__file__).parent
    root_dir = script_dir.parent  # 上層目錄 (new/)
    input_dir = root_dir / 'input'
    output_dir = root_dir / 'output'
    temp_dir = root_dir / 'temp'
    
    # 建立輸出和暫存目錄
    output_dir.mkdir(exist_ok=True)
    temp_dir.mkdir(exist_ok=True)
    
    # 載入 API 金鑰
    config_path = script_dir / 'api_key.json'
    if not config_path.exists():
        print(f"錯誤：找不到設定檔: {config_path}")
        sys.exit(1)
    
    api_key = load_api_key(str(config_path))
    print("API 金鑰載入成功")
    
    # 取得所有媒體檔案
    media_files = get_media_files(str(input_dir))
    
    if not media_files:
        print(f"在 {input_dir} 中找不到任何影片或音訊檔案")
        sys.exit(0)
    
    print(f"\n找到 {len(media_files)} 個媒體檔案:")
    for f in media_files:
        print(f"  - {f.name}")
    
    print("\n" + "=" * 50)
    
    results = []
    
    for media_file in media_files:
        print(f"\n處理: {media_file.name}")
        
        ext = media_file.suffix.lower()
        audio_path = None
        
        # 判斷是影片還是音訊
        if ext in VIDEO_EXTENSIONS:
            print("  偵測到影片檔案，提取音訊中...")
            audio_path = extract_audio_from_video(media_file, temp_dir)
        elif ext in AUDIO_EXTENSIONS:
            print("  偵測到音訊檔案")
            # 如果音訊格式不被 OpenAI 支援，轉換為 mp3
            if ext not in OPENAI_SUPPORTED_FORMATS:
                print(f"  格式 {ext} 不被 OpenAI 直接支援，轉換中...")
                audio_path = extract_audio_from_video(media_file, temp_dir)
            else:
                audio_path = media_file
        
        if audio_path is None:
            print(f"  無法處理檔案: {media_file.name}")
            continue
        
        # 轉錄
        transcript_result = transcribe_audio_gpt4o(audio_path, api_key)
        
        if transcript_result['success']:
            result = {
                'filename': media_file.name,
                'text': transcript_result['text'],
                'segments': transcript_result.get('segments', []),
                'language': transcript_result.get('language', 'zh'),
                'duration': transcript_result.get('duration', 0),
                'processed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            results.append(result)
            
            # 儲存個別詳細逐字稿
            detail_path = output_dir / f"{media_file.stem}_transcript.md"
            save_detailed_transcript(result, detail_path)
            print(f"  轉錄成功! 詳細逐字稿已儲存至: {detail_path.name}")
        else:
            print(f"  轉錄失敗: {transcript_result.get('error')}")
    
    # 儲存彙整的 CSV
    if results:
        csv_path = output_dir / 'transcripts.csv'
        save_to_csv(results, csv_path)
    
    # 清理暫存目錄
    print("\n清理暫存檔案...")
    import shutil
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    
    print("\n處理完成!")
    print(f"成功處理 {len(results)}/{len(media_files)} 個檔案")


if __name__ == '__main__':
    main()
