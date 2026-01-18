import cv2
import csv
import os

def time_to_msec(time_str):
    """Converts a time string MM:SS or HH:MM:SS to milliseconds."""
    try:
        if ':' not in time_str:
            return 0
        
        parts = time_str.split(':')
        
        if len(parts) == 2:
            # MM:SS format
            m, s = parts
            return int((int(m) * 60 + float(s)) * 1000)
        elif len(parts) == 3:
            # HH:MM:SS format
            h, m, s = parts
            return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
        else:
            return 0
    except ValueError:
        return 0

def extract_frames():
    # 取得腳本所在目錄，使用上層目錄的共用 input/output 資料夾
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)  # 上層目錄 (new/)
    
    input_folder = os.path.join(root_dir, 'input')
    output_folder = os.path.join(root_dir, 'output')
    # 從 output 讀取 CSV（因為是階段1的輸出）
    csv_input_path = os.path.join(output_folder, 'transcripts.csv')
    csv_output_path = os.path.join(output_folder, 'transcripts.csv')
    screenshots_folder = os.path.join(output_folder, 'screenshots')

    # Check if CSV exists
    if not os.path.exists(csv_input_path):
        print(f"錯誤：找不到 CSV 檔案 '{csv_input_path}'")
        return

    # Create output folders if they don't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    if not os.path.exists(screenshots_folder):
        os.makedirs(screenshots_folder)

    # Read CSV
    rows = []
    header = []
    try:
        with open(csv_input_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)  # Read header
            rows = list(reader)
    except UnicodeDecodeError:
        with open(csv_input_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
    except Exception as e:
        print(f"讀取 CSV 錯誤：{e}")
        return

    if not rows:
        print("CSV 檔案中沒有資料")
        return

    # Group rows by video file
    video_groups = {}
    for i, row in enumerate(rows):
        if len(row) < 5:
            continue
        video_name = row[0]
        if video_name not in video_groups:
            video_groups[video_name] = []
        video_groups[video_name].append((i, row))

    updated_rows = []
    
    for video_name, group in video_groups.items():
        video_path = os.path.join(input_folder, video_name)
        
        # Check if video exists
        if not os.path.exists(video_path):
            print(f"警告：找不到影片檔案 '{video_path}'，跳過此影片")
            for i, row in group:
                new_row = row + ['', '']
                updated_rows.append((i, new_row))
            continue

        # Open video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"錯誤：無法開啟影片 '{video_path}'")
            for i, row in group:
                new_row = row + ['', '']
                updated_rows.append((i, new_row))
            continue

        print(f"處理影片：{video_name}，共 {len(group)} 段")

        for idx, (i, row) in enumerate(group):
            start_time_str = row[1]
            end_time_str = row[2]

            start_msec = time_to_msec(start_time_str)
            end_msec = time_to_msec(end_time_str)

            # Define filenames
            start_filename = f"img_{i+1}_start.jpg"
            end_filename = f"img_{i+1}_end.jpg"
            start_filepath = os.path.join(screenshots_folder, start_filename)
            end_filepath = os.path.join(screenshots_folder, end_filename)

            # Capture Start Frame
            cap.set(cv2.CAP_PROP_POS_MSEC, start_msec)
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(start_filepath, frame)
            else:
                print(f"警告：無法擷取 {start_time_str} 時間點的畫面")
                start_filename = ''

            # Capture End Frame
            cap.set(cv2.CAP_PROP_POS_MSEC, end_msec)
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(end_filepath, frame)
            else:
                print(f"警告：無法擷取 {end_time_str} 時間點的畫面")
                end_filename = ''

            # Append new columns
            new_row = row + [start_filename, end_filename]
            updated_rows.append((i, new_row))

        cap.release()

    # Sort by original index
    updated_rows.sort(key=lambda x: x[0])
    updated_rows = [row for _, row in updated_rows]

    # Define new header
    new_header = header + ['開始照片檔名', '結束照片檔名']

    # Write to output CSV (not modifying input)
    try:
        with open(csv_output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(new_header)
            writer.writerows(updated_rows)
        print(f"成功輸出 CSV 至 {csv_output_path}")
        print(f"成功儲存截圖至 {screenshots_folder} 資料夾")
    except Exception as e:
        print(f"寫入 CSV 錯誤：{e}")

if __name__ == "__main__":
    extract_frames()
