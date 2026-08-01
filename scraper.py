import requests
import json
import hashlib
import re
import os
import urllib.parse
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

M3U_URL = "https://tinhlagi.pro/s.m3u"
RAW_FILE = "raw_playlist.m3u"
OUTPUT_FILE = "output.json"
THUMBS_DIR = "thumbs"
VN_TZ = timezone(timedelta(hours=7))
REPO_RAW = os.environ.get("REPO_RAW", "")

FILTER_KEYWORDS = ["chuối chiên", "chuoi chien", "🔴 chuối chiên tv"]

def now_vn():
    return datetime.now(tz=VN_TZ)

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

def fetch_image(url):
    if not url:
        return None
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        res.raise_for_status()
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except:
        return None

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
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def parse_match_info(channel_name):
    """
    Parse thông tin trận từ tên kênh
    Ví dụ: "01:00 02/08 Girona vs Arsenal (A Ngao) [FHD1]"
    """
    match = re.match(r'(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2})\s+(.+?)\s+vs\s+(.+?)(?:\s+\(([^)]+)\))?(?:\s+\[([^\]]+)\])?', channel_name)
    if match:
        time_str = match.group(1)
        date_str = match.group(2)
        team_a = match.group(3).strip()
        team_b = match.group(4).strip()
        blv = match.group(5).strip() if match.group(5) else "Unknown"
        quality = match.group(6).strip() if match.group(6) else ""
        blv_info = f"{blv} {quality}".strip()
        return time_str, date_str, team_a, team_b, blv_info
    return None, None, channel_name, "", "Stream"

def group_matches(lines):
    """
    Group các stream cùng trận vào 1 match
    """
    print("▶ BƯỚC 2: Đang lọc và nhóm các trận đấu...")
    os.makedirs(THUMBS_DIR, exist_ok=True)
    
    matches_dict = {}
    current_extinf = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF'):
            current_extinf = line
        elif current_extinf and not line.startswith('#'):
            if any(kw in current_extinf.lower() for kw in FILTER_KEYWORDS):
                name_match = re.search(r',(.*?)$', current_extinf)
                channel_name = name_match.group(1).strip() if name_match else "Unknown"
                
                group_match = re.search(r'group-title="([^"]*)"', current_extinf)
                group_title = group_match.group(1).strip() if group_match else "Kênh"
                
                logo_match = re.search(r'tvg-logo="([^"]*)"', current_extinf)
                logo = logo_match.group(1) if logo_match else ""
                
                time_str, date_str, team_a, team_b, blv_info = parse_match_info(channel_name)
                
                match_key = f"{time_str}_{date_str}_{team_a.lower()}_{team_b.lower()}"
                
                if match_key not in matches_dict:
                    matches_dict[match_key] = {
                        "match_id": make_id(match_key, "match"),
                        "time": time_str,
                        "date": date_str,
                        "team_a": team_a,
                        "team_b": team_b,
                        "group": group_title,
                        "logo_a": "",
                        "logo_b": "",
                        "streams": []
                    }
                
                matches_dict[match_key]["streams"].append({
                    "url": line,
                    "blv": blv_info,
                    "logo": logo
                })
                
                if logo and not matches_dict[match_key]["logo_a"]:
                    if "merge_logos.php" in logo:
                        home_match = re.search(r'home=([^&]+)', logo)
                        away_match = re.search(r'away=([^&]+)', logo)
                        if home_match:
                            matches_dict[match_key]["logo_a"] = urllib.parse.unquote(home_match.group(1))
                        if away_match:
                            matches_dict[match_key]["logo_b"] = urllib.parse.unquote(away_match.group(1))
                    else:
                        matches_dict[match_key]["logo_a"] = logo
            
            current_extinf = None
    
    return list(matches_dict.values())

# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, match_id_safe):
    """
    Tạo thumbnail format đẹp giống giovang
    """
    cache_key = match.get("logo_a", "") + match.get("logo_b", "") + "v2"
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

    for y in range(HEADER_H, H - FOOTER_H):
        ratio = (y - HEADER_H) / (H - FOOTER_H - HEADER_H)
        gray = int(248 - ratio * 18)
        draw.line([(0, y), (W, y)], fill=(gray, gray, gray + 4))

    draw.rectangle([(0, 0), (W, HEADER_H)], fill=(13, 20, 40))
    draw.rectangle([(0, H - FOOTER_H), (W, H)], fill=(13, 20, 40))

    ACCENT = (255, 140, 0)
    draw.rectangle([(0, HEADER_H), (W, HEADER_H + 5)], fill=ACCENT)
    draw.rectangle([(0, H - FOOTER_H - 5), (W, H - FOOTER_H)], fill=ACCENT)

    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs = ImageFont.truetype(FONT_BOLD, 160)
        font_time = ImageFont.truetype(FONT_BOLD, 100)
        font_team = ImageFont.truetype(FONT_BOLD, 58)
    except:
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
            except:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= max_width:
                break
            font_size -= 3
        draw.text((cx, name_center), text, fill=(20, 20, 20), font=f, anchor="mm")

    if match.get("logo_a"):
        img = fetch_image(match["logo_a"])
        if img:
            try:
                resized_img = img.resize((logo_size, logo_size), Image.LANCZOS)
                x = W // 4 - logo_size // 2
                bg.paste(resized_img, (x, logo_y), resized_img)
            except:
                pass

    if match.get("logo_b"):
        img = fetch_image(match["logo_b"])
        if img:
            try:
                resized_img = img.resize((logo_size, logo_size), Image.LANCZOS)
                x = W * 3 // 4 - logo_size // 2
                bg.paste(resized_img, (x, logo_y), resized_img)
            except:
                pass

    draw.text((W // 2, logo_y + logo_size // 2), "VS", fill=ACCENT, font=font_vs, anchor="mm")

    if match.get("team_a"):
        draw_team_name(match["team_a"], W // 4)
    if match.get("team_b"):
        draw_team_name(match["team_b"], W * 3 // 4)

    time_fmt = match.get("time", "")
    date_fmt = match.get("date", "")
    time_display = f"{time_fmt} {date_fmt}" if time_fmt and date_fmt else "LIVE"
    
    if time_display:
        font_size = 100
        f_time = font_time
        while font_size >= 40:
            try:
                f_time = ImageFont.truetype(FONT_BOLD, font_size)
            except:
                f_time = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), time_display, font=f_time)
            if (bbox[2] - bbox[0]) <= W - 100:
                break
            font_size -= 4
        draw.text((W // 2 + 4, time_y + 4), time_display, fill=ACCENT, font=f_time, anchor="mm")
        draw.text((W // 2, time_y), time_display, fill=(15, 15, 15), font=f_time, anchor="mm")

    if match.get("group"):
        league_text = match["group"].upper()
        font_size = 62
        f = None
        while font_size >= 28:
            try:
                f = ImageFont.truetype(FONT_BOLD, font_size)
            except:
                f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), league_text, font=f)
            if (bbox[2] - bbox[0]) <= W - 60:
                break
            font_size -= 3
        draw.text((W // 2, HEADER_H // 2), league_text, fill=(255, 255, 255), font=f, anchor="mm")

    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(180, 180, 180), width=3)
    bg.save(out_path, "PNG", optimize=True)
    return out_path

def cleanup_old_thumbs(days: int = 3):
    """Xóa thumbnail cũ hơn số ngày quy định"""
    if not os.path.exists(THUMBS_DIR):
        return
    
    cutoff = now_vn() - timedelta(days=days)
    deleted_count = 0
    
    for fname in os.listdir(THUMBS_DIR):
        if not fname.endswith(".png"):
            continue
        
        m = re.search(r'_(\d{8})\.png$', fname)
        if m:
            try:
                file_date = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=VN_TZ)
                if file_date < cutoff:
                    os.remove(os.path.join(THUMBS_DIR, fname))
                    deleted_count += 1
            except Exception:
                pass
    
    if deleted_count > 0:
        print(f"️  Đã xóa {deleted_count} thumbnail cũ")

# ─────────────────────────────────────────────────────────────────────────────
# BUILD CHANNEL JSON
# ────────────────────────────────────────────────────────────────────────────

def build_channel(match, match_id_safe, thumb_url):
    """
    Build channel object với nhiều stream links
    """
    uid = make_id(match_id_safe, "ch")
    src_id = make_id(match_id_safe, "src")
    ct_id = make_id(match_id_safe, "ct")
    
    stream_links = []
    for idx, stream in enumerate(match["streams"]):
        stream_links.append({
            "id": make_id(stream["url"] + str(idx), "lnk"),
            "name": stream["blv"],
            "type": "hls",
            "default": idx == 0,
            "url": stream["url"],
            "request_headers": [
                {"key": "User-Agent", "value": "Mozilla/5.0"},
                {"key": "Referer", "value": "https://live.chuoichien.tv/"}
            ]
        })

    display_name = f"{match['team_a']} vs {match['team_b']} | {match['time']} {match['date']}"
    stream_count = len(stream_links)
    label_text = f"● LIVE ({stream_count} links)" if stream_count > 1 else "● LIVE"

    channel = {
        "id": uid,
        "name": display_name,
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": label_text, "position": "top-left", "color": "#00000080", "text_color": "#ff4444"}],
        "sources": [{
            "id": src_id,
            "name": match.get("group", "TinhLagi"),
            "contents": [{
                "id": ct_id,
                "name": f"{match['team_a']} vs {match['team_b']}",
                "streams": [{
                    "id": make_id(match_id_safe, "st"),
                    "name": "Streams",
                    "stream_links": stream_links
                }]
            }]
        }],
        "org_metadata": {
            "league": match.get("group", ""),
            "team_a": match["team_a"],
            "team_b": match["team_b"],
            "logo_a": match.get("logo_a", ""),
            "logo_b": match.get("logo_b", ""),
            "time": match["time"],
            "date": match["date"],
            "blv": ", ".join([s["blv"] for s in match["streams"]]),
            "is_live": True,
            "cate_type": "football",
            "stream_count": stream_count
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
    print(f" Thời gian VN: {now_vn().strftime('%H:%M %d/%m/%Y')}")
    
    # Cleanup thumbnail cũ
    cleanup_old_thumbs(days=3)
    
    raw_lines = download_raw_m3u()
    
    if not raw_lines:
        return
    
    matches = group_matches(raw_lines)
    
    if not matches:
        print("⚠️  Không tìm thấy trận nào phù hợp!")
        return

    print(f"✅ Tìm thấy {len(matches)} trận đấu. Đang tạo thumbnail...\n")
    
    channels = []
    for i, match in enumerate(matches):
        match_id_safe = match["match_id"].replace(":", "-")
        stream_count = len(match["streams"])
        
        print(f"[{i+1}/{len(matches)}] {match['team_a']} vs {match['team_b']} ({match['time']} {match['date']}) - {stream_count} streams")
        
        thumb_path = make_thumbnail(match, match_id_safe)
        cache_key = match.get("logo_a", "") + "v2"
        logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        
        if REPO_RAW:
            thumb_url = f"{REPO_RAW}/{thumb_path}?v={logo_hash}"
        else:
            thumb_url = f"file://{os.path.abspath(thumb_path)}"
        
        channel = build_channel(match, match_id_safe, thumb_url)
        channels.append(channel)

    output = {
        "id": "tinhlagi_filtered",
        "url": "https://tinhlagi.pro",
        "name": "Chuối Chiên TV",
        "color": "#e63946",
        "grid_number": 3,
        "groups": [{
            "id": "grp_filtered",
            "name": f"🍌 {matches[0]['group']} ({len(channels)} trận)",
            "display": "vertical",
            "grid_number": 2,
            "channels": channels
        }]
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    total_streams = sum(len(m["streams"]) for m in matches)
    print(f"\n🎉 HOÀN TẤT!")
    print(f"   - {len(channels)} trận đấu")
    print(f"   - {total_streams} stream links")
    print(f"   - Đã lưu vào {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
