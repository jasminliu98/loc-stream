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
# TIMEZONE & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

VN_TZ = timezone(timedelta(hours=7))

def now_vn() -> datetime:
    return datetime.now(tz=VN_TZ)

def parse_kickoff(time_str: str, date_str: str = ""):
    if not time_str or not time_str.strip():
        return now_vn() # Fallback to now if no time
    t = time_str.strip()
    d = date_str.strip() if date_str else ""
    today = now_vn()
    year = today.year

    try:
        hh, mm = int(t.split(":")[0]), int(t.split(":")[1])
    except Exception:
        return now_vn()

    if d:
        m3 = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", d)
        if m3:
            try: return datetime(int(m3.group(3)), int(m3.group(2)), int(m3.group(1)), hh, mm, tzinfo=VN_TZ)
            except ValueError: pass
        m2 = re.match(r"(\d{1,2})/(\d{1,2})$", d)
        if m2:
            try: return datetime(year, int(m2.group(2)), int(m2.group(1)), hh, mm, tzinfo=VN_TZ)
            except ValueError: pass

    try:
        return datetime(today.year, today.month, today.day, hh, mm, tzinfo=VN_TZ)
    except ValueError:
        return now_vn()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Referer": "https://tinhlagi.pro/",
}

M3U_URL = "https://tinhlagi.pro/s.m3u"
# Thêm các từ khóa bạn muốn lọc vào đây (chữ thường)
FILTER_KEYWORDS = ["chuoichien", "chuỗi chiến", "chuoi chien", "chuoi chien tv"]

THUMBS_DIR = "thumbs"
REPO_RAW = os.environ.get("REPO_RAW", "") # Nếu chạy trên GitHub Actions, biến này sẽ có giá trị
THUMB_VERSION = "v2_m3u"

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode()).hexdigest()[:10]}"

def fetch_image(url):
    if not url:
        return None
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        res.raise_for_status()
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except Exception:
        return None

def format_time_hhmm(time_str: str) -> str:
    if not time_str: return ""
    parts = time_str.strip().split(":")
    return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}" if len(parts) >= 2 else time_str.strip()

def format_date_ddmm(date_str: str) -> str:
    if not date_str: return ""
    d = date_str.strip()
    m = re.match(r"(\d{1,2})[-/](\d{1,2})(?:[-/]\d{4})?", d)
    return f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}" if m else d

def get_stream_type(url: str) -> str:
    if not url: return "hls"
    clean_url = url.lower().split("?")[0]
    if clean_url.endswith(".flv"): return "httpflv"
    if clean_url.endswith(".mpd"): return "dash"
    if clean_url.endswith(".mp4"): return "mp4"
    return "hls"

# ─────────────────────────────────────────────────────────────────────────────
# M3U PARSER & FILTER
# ─────────────────────────────────────────────────────────────────────────────

def parse_and_filter_m3u(url: str, keywords: list) -> list:
    print(f"Đang tải M3U từ: {url}")
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        lines = res.text.split('\n')
    except Exception as e:
        print(f"Lỗi tải M3U: {e}")
        return []

    matches = []
    current_extinf = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF'):
            current_extinf = line
        elif current_extinf and not line.startswith('#'):
            # Đây là dòng URL
            name_match = re.search(r',(.*?)$', current_extinf)
            channel_name = name_match.group(1).strip() if name_match else "Unknown Channel"
            
            logo_match = re.search(r'tvg-logo="([^"]*)"', current_extinf)
            logo = logo_match.group(1) if logo_match else ""
            
            group_match = re.search(r'group-title="([^"]*)"', current_extinf)
            group = group_match.group(1) if group_match else "General"

            # Kiểm tra từ khóa lọc
            if any(kw in channel_name.lower() for kw in keywords):
                # Cố gắng tách thông tin trận đấu từ tên kênh
                # Ví dụ: "20:00 | Việt Nam vs Thái Lan | VTV6"
                time_match = re.search(r'(\d{1,2}:\d{2})', channel_name)
                time_str = time_match.group(1) if time_match else "20:00" # Default fallback
                
                team_match = re.search(r'(.+?)\s+(?:vs|gặp|-)\s+(.+?)(?:\||$)', channel_name, re.IGNORECASE)
                if team_match:
                    team_a = team_match.group(1).strip()
                    team_b = team_match.group(2).split('|')[0].strip()
                else:
                    team_a = channel_name
                    team_b = "LIVE" # Fallback nếu không phải tên trận đấu

                matches.append({
                    "match_id": make_id(channel_name + line, "m3u"),
                    "name": channel_name,
                    "url": line,
                    "logo_a": logo,
                    "logo_b": "", # M3U thường chỉ có 1 logo
                    "team_a": team_a,
                    "team_b": team_b,
                    "league": group,
                    "time": time_str,
                    "date": now_vn().strftime("%d/%m"),
                    "is_live": True, # Giả định kênh M3U là live
                    "cate_type": "football" # Default category
                })
            current_extinf = None
            
    return matches

# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL GENERATION (GIỮ NGUYÊN FORMAT & KÍCH THƯỚC 1600x1200)
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, match_id_safe):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    cache_key = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    date_str = now_vn().strftime("%Y%m%d")
    
    out_path = f"{THUMBS_DIR}/{match_id_safe}_{logo_hash}_{date_str}.png"
    if os.path.exists(out_path):
        return out_path

    W, H = 1600, 1200
    HEADER_H = 180
    FOOTER_H = 160

    bg = Image.new("RGB", (W, H), (245, 245, 248))
    draw = ImageDraw.Draw(bg)

    # Gradient background
    for y in range(HEADER_H, H - FOOTER_H):
        ratio = (y - HEADER_H) / (H - FOOTER_H - HEADER_H)
        gray = int(248 - ratio * 18)
        draw.line([(0, y), (W, y)], fill=(gray, gray, gray + 4))

    draw.rectangle([(0, 0), (W, HEADER_H)], fill=(13, 20, 40))
    draw.rectangle([(0, H - FOOTER_H), (W, H)], fill=(13, 20, 40))

    ACCENT = (220, 30, 40)
    draw.rectangle([(0, HEADER_H), (W, HEADER_H + 5)], fill=ACCENT)
    draw.rectangle([(0, H - FOOTER_H - 5), (W, H - FOOTER_H)], fill=ACCENT)

    # Font setup (Fallback to default if DejaVu not found)
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs = ImageFont.truetype(FONT_BOLD, 160)
        font_time = ImageFont.truetype(FONT_BOLD, 100)
        font_team = ImageFont.truetype(FONT_BOLD, 58)
    except Exception:
        font_vs = font_time = font_team = ImageFont.load_default()

    content_top = HEADER_H + 5
    content_bot = H - FOOTER_H - 5
    content_h = content_bot - content_top

    logo_size = 360
    name_h = 120
    time_h = 110
    gap_logo_name = 40
    gap_name_time = 60

    total_block_h = logo_size + gap_logo_name + name_h + gap_name_time + time_h
    block_top = content_top + (content_h - total_block_h) // 2

    logo_y = block_top
    name_block_y = logo_y + logo_size + gap_logo_name
    name_center = name_block_y + name_h // 2
    time_y = name_block_y + name_h + gap_name_time + time_h // 2

    def draw_team_name(text, cx):
        max_width = W // 2 - 60
        font_size = 58
        f = font_team
        while font_size >= 28:
            try:
                f = ImageFont.truetype(FONT_BOLD, font_size)
            except Exception:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= max_width:
                break
            font_size -= 3
        draw.text((cx, name_center), text, fill=(20, 20, 20), font=f, anchor="mm")

    # Draw Logo A
    if match.get("logo_a"):
        img = fetch_image(match["logo_a"])
        if img:
            try:
                resized_img = img.resize((logo_size, logo_size), Image.LANCZOS)
                x = W // 4 - logo_size // 2
                bg.paste(resized_img, (x, logo_y), resized_img)
            except Exception:
                pass

    # Draw Logo B (if exists, otherwise skip)
    if match.get("logo_b"):
        img = fetch_image(match["logo_b"])
        if img:
            try:
                resized_img = img.resize((logo_size, logo_size), Image.LANCZOS)
                x = W * 3 // 4 - logo_size // 2
                bg.paste(resized_img, (x, logo_y), resized_img)
            except Exception:
                pass

    # Draw VS (Only if we have two distinct teams, otherwise center the text or hide)
    if match.get("team_b") and match["team_b"].upper() != "LIVE":
        draw.text((W // 2, logo_y + logo_size // 2), "VS", fill=ACCENT, font=font_vs, anchor="mm")

    # Draw Team Names
    if match.get("team_a"):
        draw_team_name(match["team_a"], W // 4 if match.get("team_b") and match["team_b"].upper() != "LIVE" else W // 2)
    if match.get("team_b") and match["team_b"].upper() != "LIVE":
        draw_team_name(match["team_b"], W * 3 // 4)

    # Draw Time & Date
    time_fmt = format_time_hhmm(match.get("time", ""))
    date_fmt = format_date_ddmm(match.get("date", ""))
    time_display = f"{time_fmt} {date_fmt}" if time_fmt and date_fmt else (time_fmt or "LIVE NOW")
    
    if time_display:
        font_size = 100
        f_time = font_time
        while font_size >= 40:
            try:
                f_time = ImageFont.truetype(FONT_BOLD, font_size)
            except Exception:
                f_time = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), time_display, font=f_time)
            if (bbox[2] - bbox[0]) <= W - 100:
                break
            font_size -= 4
        
        # Shadow effect
        draw.text((W // 2 + 4, time_y + 4), time_display, fill=ACCENT, font=f_time, anchor="mm")
        draw.text((W // 2, time_y), time_display, fill=(15, 15, 15), font=f_time, anchor="mm")

    # Draw League / Group Name
    if match.get("league"):
        league_text = match["league"].upper()
        font_size = 62
        f = None
        while font_size >= 28:
            try:
                f = ImageFont.truetype(FONT_BOLD, font_size)
            except Exception:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), league_text, font=f)
            if (bbox[2] - bbox[0]) <= W - 60:
                break
            font_size -= 3
        draw.text((W // 2, HEADER_H // 2), league_text, fill=(255, 255, 255), font=f, anchor="mm")

    # Border
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(180, 180, 180), width=3)
    bg.save(out_path, "PNG", optimize=True)
    return out_path

def cleanup_old_thumbs(days: int = 3):
    if not os.path.exists(THUMBS_DIR): return
    cutoff = now_vn() - timedelta(days=days)
    for fname in os.listdir(THUMBS_DIR):
        if not fname.endswith(".png"): continue
        m = re.search(r'_(\d{8})\.png$', fname)
        if m:
            try:
                if datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=VN_TZ) < cutoff:
                    os.remove(os.path.join(THUMBS_DIR, fname))
            except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
# BUILD CHANNEL JSON (GIỮ NGUYÊN CẤU TRÚC OUTPUT)
# ─────────────────────────────────────────────────────────────────────────────

def build_channel(match: dict, match_id_safe: str, thumb_url: str = "") -> dict:
    uid = make_id(match_id_safe, "m3u_ch")
    src_id = make_id(match_id_safe, "m3u_src")
    ct_id = make_id(match_id_safe, "m3u_ct")
    st_id = make_id(match_id_safe, "m3u_st")

    # M3U thường chỉ có 1 link, ta đưa nó vào cấu trúc stream_links
    stream_links = [{
        "id": make_id(match["url"], "lnk"),
        "name": "Link Chính",
        "type": get_stream_type(match["url"]),
        "default": True,
        "url": match["url"],
        "request_headers": [
            {"key": "Referer", "value": "https://tinhlagi.pro/"},
            {"key": "User-Agent", "value": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ],
    }]

    label_text = "● LIVE" if match["is_live"] else "🕐 Sắp"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"

    time_fmt = format_time_hhmm(match["time"])
    date_fmt = format_date_ddmm(match["date"])
    display_name = f"{match['name']}"

    channel = {
        "id": uid,
        "name": display_name,
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": label_text, "position": "top-left", "color": "#00000080", "text_color": label_color}],
        "sources": [{
            "id": src_id,
            "name": "TinhLagi Pro",
            "contents": [{
                "id": ct_id,
                "name": match["name"],
                "streams": [{"id": st_id, "name": "Stream", "stream_links": stream_links}],
            }],
        }],
        "org_metadata": {
            "league": match.get("league", ""),
            "team_a": match.get("team_a", ""),
            "team_b": match.get("team_b", ""),
            "logo_a": match.get("logo_a", ""),
            "logo_b": match.get("logo_b", ""),
            "time": match.get("time", ""),
            "date": match.get("date", ""),
            "is_live": match["is_live"],
            "cate_type": match.get("cate_type", "football"),
        },
    }

    if thumb_url:
        channel["image"] = {
            "padding": 1, "background_color": "#ffffff", "display": "contain",
            "url": thumb_url, "width": 1600, "height": 1200,
        }

    return channel

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(THUMBS_DIR, exist_ok=True)
    cleanup_old_thumbs(days=3)
    print(f"Thời gian VN hiện tại: {now_vn().strftime('%H:%M %d/%m/%Y')}")
    print("Đang tải và lọc dữ liệu từ M3U...")

    matches_list = parse_and_filter_m3u(M3U_URL, FILTER_KEYWORDS)
    
    if not matches_list:
        print("⚠️ Không tìm thấy kênh nào phù hợp với từ khóa lọc!")
        return

    print(f"Tìm thấy {len(matches_list)} kênh phù hợp. Đang tạo thumbnail và build JSON...\n")

    channels = []
    for i, match in enumerate(matches_list):
        match_id_safe = match["match_id"].replace(":", "-").replace("/", "-")
        log_time = format_time_hhmm(match['time'])
        
        print(f"[{i+1}/{len(matches_list)}] {match['name']} ({log_time})")

        # Tạo thumbnail
        thumb_path = make_thumbnail(match, match_id_safe)
        cache_key = match.get("logo_a", "") + THUMB_VERSION
        logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        
        # Nếu có REPO_RAW (GitHub Actions), dùng link raw. Ngược lại, dùng path tương đối hoặc local server
        thumb_url = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else f"file://{os.path.abspath(thumb_path)}"

        channel = build_channel(match, match_id_safe, thumb_url)
        channels.append(channel)
        time.sleep(0.1) # Tránh spam request nếu có fetch logo

    # Gom nhóm vào 1 category duy nhất cho các kênh đã lọc
    groups = [{
        "id": "cate_filtered_m3u", 
        "name": f"📺 Kênh Đã Lọc ({len(channels)} LIVE)", 
        "display": "vertical",
        "grid_number": 2, 
        "enable_detail": False, 
        "channels": channels,
    }]

    output = {
        "id": "tinhlagi_filtered", 
        "url": "https://tinhlagi.pro", 
        "name": "TinhLagi Filtered",
        "color": "#e63946", 
        "grid_number": 3,
        "image": {"type": "cover", "url": "https://tinhlagi.pro/favicon.ico"}, # Fallback icon
        "groups": groups,
    }

    staging = "output_staging.json"
    with open(staging, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    def normalize(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.dumps(json.load(f), sort_keys=True, ensure_ascii=False)
        except Exception:
            return ""

    if normalize("output.json") != normalize(staging):
        os.replace(staging, "output.json")
        print(f"\n✅ Hoàn tất! {len(channels)} kênh đã được xử lý và lưu vào output.json")
        print(f"📁 Thumbnail được lưu trong thư mục: {os.path.abspath(THUMBS_DIR)}")
    else:
        os.remove(staging)
        print(f"\n✅ Hoàn tất! Dữ liệu không thay đổi, giữ nguyên output.json")

if __name__ == "__main__":
    main()
