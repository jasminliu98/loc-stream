import requests
import os

# --- CẤU HÌNH ---
URL_M3U = "https://tinhlagi.pro/s.m3u"
RAW_OUTPUT_FILE = "raw_playlist.m3u"
FILTERED_OUTPUT_FILE = "filtered_playlist.m3u"
# Từ khóa cần lọc. Bạn có thể đổi thành "chuoi chien", "chiến", hoặc "chuoichien tv"
KEYWORD = "chuoichien" 
# ----------------

def download_m3u(url, output_file):
    """Tải file M3U từ URL và lưu vào máy"""
    print(f"Đang tải dữ liệu từ: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Kiểm tra lỗi HTTP
        
        # Lưu file gốc
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"✅ Đã lưu file gốc thành công: {output_file}")
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi tải dữ liệu: {e}")
        return None

def filter_m3u(content, keyword, output_file):
    """Lọc nội dung M3U theo từ khóa và lưu vào file mới"""
    print(f"Đang lọc các kênh chứa từ khóa: '{keyword}'")
    
    lines = content.split('\n')
    filtered_channels = []
    
    # Luôn giữ lại dòng header #EXTM3U nếu có
    if lines and lines[0].strip().startswith("#EXTM3U"):
        filtered_channels.append(lines[0].strip())
    
    for i in range(len(lines)):
        line = lines[i].strip()
        
        # Chỉ xử lý các dòng khai báo thông tin kênh
        if line.startswith("#EXTINF"):
            # Lấy dòng URL ngay phía dưới (nếu có)
            url_line = lines[i+1].strip() if (i + 1) < len(lines) else ""
            
            # Kiểm tra từ khóa trong cả tên kênh (EXTINF) và đường dẫn (URL)
            if keyword.lower() in line.lower() or keyword.lower() in url_line.lower():
                filtered_channels.append(line)
                if url_line and not url_line.startswith("#"):
                    filtered_channels.append(url_line)
                    
    # Lưu kết quả đã lọc
    if len(filtered_channels) > 1: # Lớn hơn 1 vì có dòng #EXTM3U
        with open(output_file, "w", encoding="utf-8") as f:
            f.write('\n'.join(filtered_channels))
        print(f"✅ Đã lọc và lưu thành công {len(filtered_channels) // 2} kênh vào: {output_file}")
    else:
        print("⚠️ Không tìm thấy kênh nào phù hợp với từ khóa.")

def main():
    print("="*50)
    print("Bắt đầu quy trình scraper M3U")
    print("="*50)
    
    # 1. Tải và lưu file gốc
    raw_content = download_m3u(URL_M3U, RAW_OUTPUT_FILE)
    
    if raw_content:
        # 2. Lọc và lưu file kết quả
        filter_m3u(raw_content, KEYWORD, FILTERED_OUTPUT_FILE)
        
    print("="*50)
    print("Hoàn tất!")

if __name__ == "__main__":
    main()
