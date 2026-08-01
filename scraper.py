import requests
import json
import hashlib
import re
import time
import os
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

VN_TZ = timezone(timedelta(hours=7))

def now_vn():
    return datetime.now(tz=VN_TZ)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

M3U_URL = "https://tinhlagi.pro/s.m3u"
FILTER_KEYWORDS = ["chuoichien", "chuỗi chiến", "chuoi chien"]

THUMBS_DIR = "thumbs"
# Biến này sẽ được GitHub Actions set tự động nếu chạy trên CI
REPO_RAW = os.environ.get("REPO_RAW", "") 

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode()).hexdigest()[:10]}"

def fetch_image(url):
    if not url: return None
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        res.raise_for_status()
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL GENERATOR (SIMPLE & ROBUST)
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, match_id_safe):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    
    # Tên file duy nhất dựa trên nội dung để cache
    content_hash = hashlib.md5(str(match).encode()).hexdigest()[:8]
    out_path = f"{THUMBS_DIR}/{match_id_safe}_{content_hash}.png"
    
    if os.path.exists(out_path):
        return out_path

    W, H = 1600, 1200
    bg = Image.new("RGB", (W, H), (20, 20, 20)) # Nền tối cho dễ nhìn chữ trắng
    draw = ImageDraw.Draw(bg)

    # Dùng font mặc định của hệ thống/PIL (không cần tải file .ttf ngoài)
    # Lưu ý: Font mặc định thường nhỏ, nên ta sẽ vẽ chữ to bằng cách scale hoặc chấp nhận nó nhỏ
    # Để đảm bảo chạy được mọi nơi, ta dùng load_default()
    try:
        font_large = ImageFont.truetype("arial.ttf", 80) # Thử arial trước (có trên Windows/Mac)
    except:
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80) # Linux
        except:
            font_large = ImageFont.load_default() # Fallback cuối cùng

    # Vẽ khung viền đỏ
    draw.rectangle([0, 0, W-1, H-1], outline=(220, 30, 40), width=10)
    
    # Vẽ tên kênh ở giữa
    name = match.get("name", "Unknown Channel")
    # Cắt bớt tên nếu quá dài để tránh tràn
    if len(name) > 50:
        name = name[:47] + "..."
        
    # Tính toán vị trí căn giữa
    bbox = draw.textbbox((0, 0), name, font=font_large)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (W - text_w) // 2
    y = (H - text_h) // 2
    
    draw.text((x, y), name, fill=(255, 255, 255), font=font_large)
    
    # Vẽ thêm dòng "LIVE" hoặc giờ nếu có
    time_str = match.get("time", "")
    if time_str:
        time_text = f"⏰ {time_str}"
        bbox_t = draw.textbbox((0, 0), time_text, font=font_large)
        tw = bbox_t[2] - bbox_t[0]
        draw.text(((W - tw) // 2, y + 100), time_text, fill=(220, 30, 40), font=font_large)

    bg.save(out_path, "PNG")
    return out_path

# ─────────────────────────────────────────────────────────────────────────────
# PARSER & BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def parse_m3u(url):
    print(f"Đang tải M3U từ: {url}")
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        lines = res.text.split('\n')
    except Exception as e:
        print(f"Lỗi tải M3U: {e}")
        return []

    channels = []
    current_info = None
    
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF'):
            current_info = line
        elif current_info and line and not line.startswith('#'):
            # Xử lý thông tin kênh
            name_match = re.search(r',(.*?)$', current_info)
            channel_name = name_match.group(1).strip() if name_match else "Unknown"
            
            # Lọc từ khóa
            if any(kw in channel_name.lower() for kw in FILTER_KEYWORDS):
                logo_match = re.search(r'tvg-logo="([^"]*)"', current_info)
                logo = logo_match.group(1) if logo_match else ""
                
                # Tách giờ nếu có trong tên (ví dụ: 20:00 Kênh ABC)
                time_match = re.search(r'(\d{1,2}:\d{2})', channel_name)
                time_str = time_match.group(1) if time_match else ""

                channels.append({
                    "id": make_id(channel_name + line, "ch"),
                    "name": channel_name,
                    "url": line,
                    "logo": logo,
                    "time": time_str,
                    "is_live": True
                })
            current_info = None
    return channels

def build_channel_json(match, thumb_url):
    uid = make_id(match['url'], "src")
    
    stream_links = [{
        "id": make_id(match['url'], "lnk"),
        "name": "Link Chính",
        "type": "hls",
        "default": True,
        "url": match['url'],
        "request_headers": [
            {"key": "User-Agent", "value": "Mozilla/5.0"},
            {"key": "Referer", "value": "https://tinhlagi.pro/"}
        ]
    }]

    channel = {
        "id": match['id'],
        "name": match['name'],
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": "● LIVE", "position": "top-left", "color": "#00000080", "text_color": "#ff4444"}],
        "sources": [{
            "id": uid,
            "name": "TinhLagi",
            "contents": [{
                "id": make_id(match['url'], "ct"),
                "name": match['name'],
                "streams": [{"id": make_id(match['url'], "st"), "name": "Stream", "stream_links": stream_links}]
            }]
        }],
        "org_metadata": {
            "league": "",
            "team_a": match['name'],
            "team_b": "",
            "logo_a": match['logo'],
            "logo_b": "",
            "time": match['time'],
            "date": now_vn().strftime("%d/%m"),
            "is_live": True,
            "cate_type": "football"
        }
    }

    if thumb_url:
        channel["image"] = {
            "padding": 1, 
            "background_color": "#ffffff", 
            "display": "contain",
            "url": thumb_url, 
            "width": 1600, 
            "height": 1200
        }
    return channel

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(THUMBS_DIR, exist_ok=True)
    matches = parse_m3u(M3U_URL)
    
    if not matches:
        print("Không tìm thấy kênh nào phù hợp!")
        return

    print(f"Tìm thấy {len(matches)} kênh. Đang tạo thumbnail...")
    channels = []
    
    for m in matches:
        mid_safe = m['id'].replace(":", "-")
        thumb_path = make_thumbnail(m, mid_safe)
        
        # Nếu có REPO_RAW (từ GitHub Actions), dùng link raw. Ngược lại dùng path local
        if REPO_RAW:
            thumb_url = f"{REPO_RAW}/{thumb_path}"
        else:
            # Khi chạy local, app IPTV có thể không đọc được file://, nên tốt nhất là để trống hoặc dùng server riêng
            thumb_url = f"file://{os.path.abspath(thumb_path)}"
            
        ch = build_channel_json(m, thumb_url)
        channels.append(ch)
        time.sleep(0.1)

    output = {
        "id": "tinhlagi_filtered",
        "url": "https://tinhlagi.pro",
        "name": "TinhLagi Filtered",
        "color": "#e63946",
        "grid_number": 3,
        "groups": [{
            "id": "grp_1",
            "name": f"Kênh Đã Lọc ({len(channels)})",
            "display": "vertical",
            "grid_number": 2,
            "channels": channels
        }]
    }

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Hoàn tất! Đã lưu {len(channels)} kênh vào output.json")

if __name__ == "__main__":
    main()
