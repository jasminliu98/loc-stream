import requests
import json
import hashlib
import re
import os
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

M3U_URL = "https://tinhlagi.pro/s.m3u"
RAW_FILE = "raw_playlist.m3u"
OUTPUT_FILE = "output.json"
THUMBS_DIR = "thumbs"

# Cập nhật từ khóa chính xác (bao gồm cả có dấu, không dấu và emoji)
FILTER_KEYWORDS = ["chuối chiên", "chuoi chien", "chuỗi chiên", "chuoi chien tv"]

REPO_RAW = os.environ.get("REPO_RAW", "")
VN_TZ = timezone(timedelta(hours=7))

def now_vn():
    return datetime.now(tz=VN_TZ)

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 1: TẢI FILE RAW
# ─────────────────────────────────────────────────────────────────────────────

def download_raw_m3u():
    print(f"▶ BƯỚC 1: Đang tải M3U từ: {M3U_URL}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        res = requests.get(M3U_URL, headers=headers, timeout=15)
        res.raise_for_status()
        
        with open(RAW_FILE, "w", encoding="utf-8") as f:
            f.write(res.text)
            
        print(f"✅ Đã lưu file raw thành công: {RAW_FILE}")
        return res.text.split('\n')
    except Exception as e:
        print(f"❌ Lỗi tải M3U: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# BƯỚC 2: LỌC, TẠO THUMBNAIL & BUILD JSON
# ─────────────────────────────────────────────────────────────────────────────

def process_and_build(lines):
    print("▶ BƯỚC 2: Đang lọc dữ liệu và tạo thumbnail...")
    os.makedirs(THUMBS_DIR, exist_ok=True)
    
    filtered_channels = []
    current_extinf = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF'):
            current_extinf = line
        elif current_extinf and not line.startswith('#'):
            # Đây là dòng URL. 
            # QUAN TRỌNG: Kiểm tra từ khóa trên TOÀN BỘ dòng #EXTINF (để bắt được cả group-title)
            if any(kw in current_extinf.lower() for kw in FILTER_KEYWORDS):
                
                # 1. Lấy tên kênh (phần sau dấu phẩy cuối cùng)
                name_match = re.search(r',(.*?)$', current_extinf)
                channel_name = name_match.group(1).strip() if name_match else "Unknown"
                
                # 2. Lấy group-title (ví dụ: "🔴 CHUỐI CHIÊN TV")
                group_match = re.search(r'group-title="([^"]*)"', current_extinf)
                group_title = group_match.group(1).strip() if group_match else "Kênh Lẻ"
                
                # 3. Lấy logo
                logo_match = re.search(r'tvg-logo="([^"]*)"', current_extinf)
                logo = logo_match.group(1) if logo_match else ""
                
                # 4. Lấy giờ (ví dụ: 01:00 từ "01:00 02/08 Girona vs Arsenal")
                time_match = re.search(r'(\d{1,2}:\d{2})', channel_name)
                time_str = time_match.group(1) if time_match else ""

                filtered_channels.append({
                    "id": make_id(channel_name + line, "ch"),
                    "name": channel_name,
                    "group": group_title,
                    "url": line,
                    "logo": logo,
                    "time": time_str
                })
            current_extinf = None

    if not filtered_channels:
        print("⚠️ Không tìm thấy kênh nào phù hợp với từ khóa lọc!")
        return

    print(f"✅ Tìm thấy {len(filtered_channels)} kênh phù hợp. Đang tạo thumbnail...")
    
    channels_json = []
    for ch in filtered_channels:
        thumb_path = create_simple_thumbnail(ch)
        
        if REPO_RAW:
            thumb_url = f"{REPO_RAW}/{thumb_path}"
        else:
            thumb_url = f"file://{os.path.abspath(thumb_path)}"
            
        channels_json.append(build_channel_object(ch, thumb_url))

    # Ghi ra file output.json
    output_data = {
        "id": "tinhlagi_filtered",
        "url": "https://tinhlagi.pro",
        "name": "TinhLagi Filtered",
        "color": "#e63946",
        "grid_number": 3,
        "groups": [{
            "id": "grp_filtered",
            "name": f"🍌 {filtered_channels[0]['group']} ({len(channels_json)} kênh)",
            "display": "vertical",
            "grid_number": 2,
            "channels": channels_json
        }]
    }
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    print(f"🎉 HOÀN TẤT! Đã lưu {len(channels_json)} kênh vào {OUTPUT_FILE}")

def create_simple_thumbnail(ch):
    mid_safe = ch['id'].replace(":", "-")
    content_hash = hashlib.md5(ch['name'].encode('utf-8')).hexdigest()[:6]
    out_path = f"{THUMBS_DIR}/{mid_safe}_{content_hash}.png"
    
    if os.path.exists(out_path):
        return out_path

    W, H = 1600, 1200
    # Nền tối sang trọng
    bg = Image.new("RGB", (W, H), (15, 15, 20))
    draw = ImageDraw.Draw(bg)

    # Cố gắng load font, fallback về default nếu không có
    try:
        font_large = ImageFont.truetype("arial.ttf", 70)
        font_small = ImageFont.truetype("arial.ttf", 50)
    except:
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 70)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        except:
            font_large = font_small = ImageFont.load_default()

    # Vẽ khung viền màu cam/đỏ đặc trưng
    draw.rectangle([0, 0, W-1, H-1], outline=(255, 140, 0), width=15)
    
    # Vẽ tên nhóm kênh ở trên cùng (ví dụ: 🔴 CHUỐI CHIÊN TV)
    group_text = ch.get('group', 'LIVE')
    bbox_g = draw.textbbox((0, 0), group_text, font=font_small)
    draw.text(((W - (bbox_g[2] - bbox_g[0])) // 2, 80), group_text, fill=(255, 140, 0), font=font_small)

    # Vẽ tên trận đấu/kênh (ví dụ: 01:00 02/08 Girona vs Arsenal)
    name = ch['name']
    if len(name) > 45:
        name = name[:42] + "..."
        
    bbox = draw.textbbox((0, 0), name, font=font_large)
    x = (W - (bbox[2] - bbox[0])) // 2
    y = (H - (bbox[3] - bbox[1])) // 2
    
    draw.text((x, y), name, fill=(255, 255, 255), font=font_large)
    
    # Vẽ giờ nếu có tách được
    if ch['time']:
        time_text = f"⏰ Giờ: {ch['time']}"
        bbox_t = draw.textbbox((0, 0), time_text, font=font_small)
        xt = (W - (bbox_t[2] - bbox_t[0])) // 2
        draw.text((xt, y + 90), time_text, fill=(200, 200, 200), font=font_small)

    bg.save(out_path, "PNG", optimize=True)
    return out_path

def build_channel_object(ch, thumb_url):
    return {
        "id": ch['id'],
        "name": ch['name'],
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": "● LIVE", "position": "top-left", "color": "#00000080", "text_color": "#ff4444"}],
        "sources": [{
            "id": make_id(ch['url'], "src"),
            "name": ch['group'], # Tên source là tên nhóm kênh
            "contents": [{
                "id": make_id(ch['url'], "ct"),
                "name": ch['name'],
                "streams": [{
                    "id": make_id(ch['url'], "st"), 
                    "name": "Stream", 
                    "stream_links": [{
                        "id": make_id(ch['url'], "lnk"),
                        "name": "Link Chính",
                        "type": "hls",
                        "default": True,
                        "url": ch['url'],
                        "request_headers": [
                            {"key": "User-Agent", "value": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                            {"key": "Referer", "value": "https://live.chuoichien.tv/"} # Thêm referer cụ thể cho chuối chiên
                        ]
                    }]
                }]
            }]
        }],
        "org_metadata": {
            "team_a": ch['name'],
            "logo_a": ch['logo'],
            "time": ch['time'],
            "group": ch['group'],
            "is_live": True,
            "cate_type": "football"
        },
        "image": {
            "padding": 1, 
            "background_color": "#0f0f14", 
            "display": "contain",
            "url": thumb_url, 
            "width": 1600, 
            "height": 1200
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"⏰ Thời gian VN: {now_vn().strftime('%H:%M %d/%m/%Y')}")
    raw_lines = download_raw_m3u()
    if raw_lines:
        process_and_build(raw_lines)
