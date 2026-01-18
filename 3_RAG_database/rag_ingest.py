import os
import sys
import sqlite3
import csv
import numpy as np
import faiss
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

# --- Configuration ---
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"

# 取得腳本所在目錄，使用上層目錄的共用 input/output 資料夾
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # 上層目錄 (new/)

# 輸入從 output 讀取（因為截圖和 CSV 都是前面階段產生的）
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')
TRANSCRIPTS_FILE = os.path.join(OUTPUT_DIR, 'transcripts.csv')
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, 'screenshots')

# RAG 資料庫也輸出到 output
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

def init_db(drop=False):
    conn = get_db_connection()
    if drop:
        conn.execute('DROP TABLE IF EXISTS transcripts')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faiss_id INTEGER,
            video_file TEXT,
            start_time TEXT,
            end_time TEXT,
            speaker TEXT,
            content TEXT,
            language TEXT,
            process_time TEXT,
            start_image TEXT,
            end_image TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_text_embedding(text):
    """取得單一文字的向量嵌入"""
    load_models()
    inputs = clip_processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        outputs = clip_model.get_text_features(**inputs)
        embedding = outputs / outputs.norm(p=2, dim=-1, keepdim=True)
        return embedding.numpy()

def get_batch_embeddings(texts):
    """批次取得文字的向量嵌入"""
    load_models()
    embeddings = []
    batch_size = 32
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        inputs = clip_processor(text=batch, return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            outputs = clip_model.get_text_features(**inputs)
            batch_emb = outputs / outputs.norm(p=2, dim=-1, keepdim=True)
            embeddings.append(batch_emb.numpy())
    
    return np.vstack(embeddings) if embeddings else None

def ingest():
    """從 transcripts.csv 建立向量索引"""
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Check if transcripts file exists
    if not os.path.exists(TRANSCRIPTS_FILE):
        print(f"Error: {TRANSCRIPTS_FILE} not found.")
        sys.exit(1)
    
    # Initialize/Reset DB
    init_db(drop=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Read transcripts CSV
    transcripts = []
    with open(TRANSCRIPTS_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip empty rows
            if not row.get('內容', '').strip():
                continue
            transcripts.append(row)
    
    print(f"Found {len(transcripts)} transcript entries.")
    
    if not transcripts:
        print("No transcripts found.")
        return
    
    # Extract content for embedding
    contents = [t['內容'] for t in transcripts]
    
    # Get embeddings
    print("Generating embeddings...")
    embeddings = get_batch_embeddings(contents)
    
    if embeddings is None or len(embeddings) == 0:
        print("Failed to generate embeddings.")
        return
    
    # Build FAISS index
    d = embeddings.shape[1]
    index = faiss.IndexFlatIP(d)
    index.add(embeddings)
    
    # 解決 FAISS 在 Windows 上寫入中文路徑的問題
    original_cwd = os.getcwd()
    index_dir = os.path.dirname(INDEX_PATH)
    index_filename = os.path.basename(INDEX_PATH)
    
    try:
        os.chdir(index_dir)
        faiss.write_index(index, index_filename)
    finally:
        os.chdir(original_cwd)
        
    print(f"FAISS index saved to {INDEX_PATH}")
    
    # Insert metadata into database
    for i, t in enumerate(transcripts):
        cursor.execute('''
            INSERT INTO transcripts 
            (faiss_id, video_file, start_time, end_time, speaker, content, language, process_time, start_image, end_image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            i,
            t.get('檔案名稱', ''),
            t.get('開始時間', ''),
            t.get('結束時間', ''),
            t.get('講者', ''),
            t.get('內容', ''),
            t.get('偵測語言', ''),
            t.get('處理時間', ''),
            t.get('開始照片檔名', ''),
            t.get('結束照片檔名', '')
        ))
    
    conn.commit()
    conn.close()
    
    print(f"Database saved to {DB_PATH}")
    print("Ingestion complete.")

if __name__ == "__main__":
    ingest()
