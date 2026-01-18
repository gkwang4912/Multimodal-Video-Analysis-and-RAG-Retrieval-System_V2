import os
import sys
import sqlite3
import numpy as np
import faiss
import torch
from transformers import CLIPProcessor, CLIPModel

# --- Configuration ---
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
TOP_K = 5

# 取得腳本所在目錄，使用上層目錄的共用 input/output 資料夾
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # 上層目錄 (new/)

# 資料都在上層 output 資料夾
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, 'screenshots')
DB_PATH = os.path.join(OUTPUT_DIR, 'rag_mm.db')
INDEX_PATH = os.path.join(OUTPUT_DIR, 'transcript.index')

# --- Globals for Models (Lazy loading) ---
clip_model = None
clip_processor = None

def load_models():
    global clip_model, clip_processor
    if clip_model is None:
        print("Loading CLIP model...")
        clip_model = CLIPModel.from_pretrained(CLIP_MODEL_NAME)
        clip_processor = CLIPProcessor.from_pretrained(CLIP_MODEL_NAME)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_text_embedding(text):
    """取得文字的向量嵌入"""
    load_models()
    inputs = clip_processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        outputs = clip_model.get_text_features(**inputs)
        embedding = outputs / outputs.norm(p=2, dim=-1, keepdim=True)
        return embedding.numpy()

def search(query_text, top_k=None):
    """
    搜尋與查詢文字最相關的逐字稿片段。
    
    Args:
        query_text: 查詢文字
        top_k: 返回的結果數量（預設為 TOP_K）
    
    Returns:
        list: 包含搜尋結果的列表，每個結果包含：
            - score: 相似度分數
            - video_file: 影片檔名
            - start_time: 開始時間
            - end_time: 結束時間
            - speaker: 講者
            - content: 逐字稿內容
            - start_image: 開始圖片的完整路徑
            - end_image: 結束圖片的完整路徑
    """
    if top_k is None:
        top_k = TOP_K
        
    if not os.path.exists(DB_PATH):
        return {"error": "Database not found. Please run rag_ingest.py first."}
    
    if not os.path.exists(INDEX_PATH):
        return {"error": "Index not found. Please run rag_ingest.py first."}

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Embed Query
    query_vec = get_text_embedding(query_text)
    
    # Search FAISS Index
    results = []
    try:
        # 解決 FAISS 在 Windows 上讀取中文路徑的問題
        # 先切換當前工作目錄到索引檔所在資料夾
        original_cwd = os.getcwd()
        index_dir = os.path.dirname(INDEX_PATH)
        index_filename = os.path.basename(INDEX_PATH)
        
        try:
            os.chdir(index_dir)
            index = faiss.read_index(index_filename)
        finally:
            os.chdir(original_cwd)
            
        D, I = index.search(query_vec, top_k)
        
        for idx, score in zip(I[0], D[0]):
            if idx != -1:
                row = cursor.execute(
                    "SELECT * FROM transcripts WHERE faiss_id=?", 
                    (int(idx),)
                ).fetchone()
                
                if row:
                    # Build full image paths
                    start_image_path = None
                    end_image_path = None
                    
                    if row['start_image']:
                        start_image_path = os.path.join(SCREENSHOTS_DIR, row['start_image'])
                        if not os.path.exists(start_image_path):
                            start_image_path = None
                    
                    if row['end_image']:
                        end_image_path = os.path.join(SCREENSHOTS_DIR, row['end_image'])
                        if not os.path.exists(end_image_path):
                            end_image_path = None
                    
                    results.append({
                        "score": float(score),
                        "video_file": row['video_file'],
                        "start_time": row['start_time'],
                        "end_time": row['end_time'],
                        "speaker": row['speaker'],
                        "content": row['content'],
                        "start_image": start_image_path,
                        "end_image": end_image_path
                    })
    except Exception as e:
        print(f"Error searching index: {e}")
        return {"error": str(e)}

    conn.close()
    return results

def print_results(results):
    """將搜尋結果印出到終端機"""
    if isinstance(results, dict) and "error" in results:
        print(results["error"])
        return
    
    print(f"\n=== Found {len(results)} results ===\n")
    
    for i, item in enumerate(results, 1):
        print(f"--- Result {i} (Score: {item['score']:.4f}) ---")
        print(f"Video: {item['video_file']}")
        print(f"Time: {item['start_time']} - {item['end_time']}")
        print(f"Speaker: {item['speaker']}")
        print(f"Content: {item['content']}")
        print(f"Start Image: {item['start_image']}")
        print(f"End Image: {item['end_image']}")
        print()

def main():
    if len(sys.argv) > 1:
        query_text = " ".join(sys.argv[1:])
        results = search(query_text)
        print_results(results)
    else:
        print("進入互動模式。請輸入查詢文字，或輸入 'exit' 離開。")
        while True:
            try:
                user_input = input("\n請輸入查詢: ")
                if user_input.strip().lower() in ['exit', 'quit']:
                    break
                if user_input.strip():
                    results = search(user_input.strip())
                    print_results(results)
            except KeyboardInterrupt:
                print("\nBye!")
                break
            except EOFError:
                break

if __name__ == "__main__":
    main()
