import requests
import json
import hashlib
import re
import os
import time
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

FILTER_KEYWORDS = ["chuối chiên", "chuoi chien", "chuối chiên tv"]

CATE_MAP = {
    "football": "⚽ Bóng Đá", "basketball": "🏀 Bóng Rổ", "tennis": "🎾 Tennis",
    "bongchuyen": " Bóng Chuyền", "esport": " Esport", "caulong": "🏸 Cầu Lông",
    "vothuat": "🥊 Võ Thuật", "bongchay": "⚾ Bóng Chày", "duaxe": "🏎️ Đua Xe", 
    "Billiards": "🎱 Billiards", "other": "🏅 Thể Thao Khác"
}
CATE_ORDER = ["football", "basketball", "tennis", "bongchuyen", "esport", "caulong", "vothuat", "bongchay", "duaxe", "Billiards", "other"]

SOFASCORE_SPORT_MAP = {
    "Football": "football", "Basketball": "basketball", "Tennis": "tennis",
    "Volleyball": "bongchuyen", "Badminton": "caulong", "Cricket": "caulong",
    "Motorsport": "duaxe", "Esports": "esport", "Table Tennis": "tennis",
    "Rugby": "football", "Handball": "bongchuyen", "Baseball": "bongchay",
    "Ice Hockey": "other", "American Football": "other"
}

HEADERS_SOFASCORE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.sofascore.com/"
}

TEAM_CACHE = {}

def now_vn():
    return datetime.now(tz=VN_TZ)

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

# ─────────────────────────────────────────────────────────────────────────────
# PARSE MATCH INFO (FIXED - Parse robust hơn)
# ─────────────────────────────────────────────────────────────────────────────

def parse_match_info(channel_name):
    """
    Parse tên kênh format: "HH:MM DD/MM TeamA vs TeamB (BLV) [Quality]"
    Fix: Dùng split thay vì regex lazy để tránh bug cắt tên đội
    """
    if not channel_name:
        return None, None, "Unknown", "", "Stream"
    
    # Extract time và date
    time_match = re.match(r'(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2})\s+(.*)', channel_name)
    if not time_match:
        return None, None, channel_name, "", "Stream"
    
    time_str = time_match.group(1)
    date_str = time_match.group(2)
    rest = time_match.group(3).strip()
    
    # Split by " vs " (case-insensitive)
    vs_match = re.split(r'\s+vs\s+', rest, flags=re.IGNORECASE, maxsplit=1)
    
    if len(vs_match) == 2:
        team_a_raw = vs_match[0].strip()
        team_b_raw = vs_match[1].strip()
        
        # Remove (BLV) và [Quality] khỏi team_b
        team_b_clean = re.sub(r'\s*\([^)]*\)\s*$', '', team_b_raw)
        team_b_clean = re.sub(r'\s*\[[^\]]*\]\s*$', '', team_b_clean).strip()
        
        # Remove (BLV) và [Quality] khỏi team_a (nếu có)
        team_a_clean = re.sub(r'\s*\([^)]*\)\s*$', '', team_a_raw)
        team_a_clean = re.sub(r'\s*\[[^\]]*\]\s*$', '', team_a_clean).strip()
        
        # Extract BLV info từ team_b_raw
        blv_match = re.search(r'\(([^)]+)\)', team_b_raw)
        blv_info = blv_match.group(1).strip() if blv_match else "Stream"
        
        return time_str, date_str, team_a_clean, team_b_clean, blv_info
    
    # Fallback: không có "vs"
    return time_str, date_str, rest, "", "Stream"

# ─────────────────────────────────────────────────────────────────────────────
# SOFASCORE API (FIXED - Logo URL đúng + Debug log)
# ────────────────────────────────────────────────────────────────────────────

def get_team_info_from_sofascore(team_name):
    """
    Returns: (cate_type, logo_url)
    Logo URL dùng img.sofascore.com (CDN) thay vì api.sofascore.com
    """
    if not team_name or len(team_name) < 3:
        return "football", None
        
    if team_name in TEAM_CACHE:
        return TEAM_CACHE[team_name]

    try:
        url = f"https://api.sofascore.com/api/v1/search/multi?query={requests.utils.quote(team_name)}"
        res = requests.get(url, headers=HEADERS_SOFASCORE, timeout=10)
        
        if res.status_code != 200:
            print(f"  ⚠️ SofaScore API trả về {res.status_code} cho '{team_name}'")
            TEAM_CACHE[team_name] = ("football", None)
            return "football", None
            
        data = res.json()
        
        # Tìm team khớp tên chính xác
        best_match = None
        for item in data.get('results', []):
            entity = item.get('entity', {})
            if item.get('type') == 'team':
                entity_name = entity.get('name', '').lower()
                if entity_name == team_name.lower():
                    best_match = entity
                    break
                # Fallback: chứa tên
                if team_name.lower() in entity_name or entity_name in team_name.lower():
                    if not best_match:
                        best_match = entity
        
        if best_match:
            sport_name = best_match.get('sport', {}).get('name', 'Football')
            team_id = best_match.get('id')
            
            cate_type = SOFASCORE_SPORT_MAP.get(sport_name, "football")
            
            # Logo URL: dùng CDN img.sofascore.com (ổn định hơn)
            logo_url = f"https://img.sofascore.com/api/v1/team/{team_id}/image" if team_id else None
            
            print(f"  ✅ SofaScore: '{team_name}' → {sport_name} (logo: {logo_url})")
            TEAM_CACHE[team_name] = (cate_type, logo_url)
            return cate_type, logo_url
        else:
            print(f"  ⚠️ SofaScore: Không tìm thấy team '{team_name}'")
            
    except Exception as e:
        print(f"  ❌ SofaScore error cho '{team_name}': {e}")
        
    TEAM_CACHE[team_name] = ("football", None)
    return "football", None

def fetch_image(url):
    """Tải ảnh với retry và debug log"""
    if not url:
        return None
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if res.status_code != 200:
            print(f"  ⚠️ Fetch image {res.status_code}: {url[:50]}...")
            return None
        img = Image.open(BytesIO(res.content)).convert("RGBA")
        return img
    except Exception as e:
        print(f"  ❌ Fetch image error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# M3U PARSER & GROUPING
# ─────────────────────────────────────────────────────────────────────────────

def process_m3u_data(lines):
    print("▶ Đang lọc và nhóm các trận đấu...")
    os.makedirs(THUMBS_DIR, exist_ok=True)
    
    matches_dict = {}
    current_extinf = None
    
    for line in lines:
        line = line.strip()
        if not line: continue
            
        if line.startswith('#EXTINF'):
            current_extinf = line
        elif current_extinf and not line.startswith('#'):
            if any(kw in current_extinf.lower() for kw in FILTER_KEYWORDS):
                name_match = re.search(r',(.*?)$', current_extinf)
                channel_name = name_match.group(1).strip() if name_match else "Unknown"
                
                group_match = re.search(r'group-title="([^"]*)"', current_extinf)
                group_title = group_match.group(1).strip() if group_match else "Kênh"
                
                time_str, date_str, team_a, team_b, blv_info = parse_match_info(channel_name)
                
                print(f"   Parse: '{channel_name}' → {team_a} vs {team_b} ({time_str} {date_str})")
                
                match_key = f"{time_str}_{date_str}_{team_a.lower()}_{team_b.lower()}"
                
                if match_key not in matches_dict:
                    matches_dict[match_key] = {
                        "match_id": make_id(match_key, "match"),
                        "time": time_str, "date": date_str,
                        "team_a": team_a, "team_b": team_b,
                        "group": group_title, "streams": []
                    }
                
                matches_dict[match_key]["streams"].append({"url": line, "blv": blv_info})
            current_extinf = None

    if not matches_dict:
        print("️ Không tìm thấy trận nào!")
        return []

    # Gọi SofaScore API
    print(f"\n▶ Đang tra cứu {len(matches_dict)} trận từ SofaScore...")
    final_matches = []
    
    for key, match in matches_dict.items():
        print(f"\n  🔍 Tra cứu: {match['team_a']} vs {match['team_b']}")
        cate_a, logo_a = get_team_info_from_sofascore(match["team_a"])
        cate_b, logo_b = get_team_info_from_sofascore(match["team_b"])
        
        # Ưu tiên category giống nhau, nếu khác thì dùng football
        final_cate = cate_a if cate_a == cate_b else "football"
        
        match["cate_type"] = final_cate
        match["logo_a"] = logo_a
        match["logo_b"] = logo_b
        final_matches.append(match)
        
        time.sleep(0.3) # Tránh rate limit
    
    return final_matches

# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL GENERATOR (FIXED - Logo paste đúng cách)
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, match_id_safe):
    cache_key = (match.get("logo_a") or "") + (match.get("logo_b") or "") + "v4"
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    date_str = now_vn().strftime("%Y%m%d")
    
    out_path = f"{THUMBS_DIR}/{match_id_safe}_{logo_hash}_{date_str}.png"
    if os.path.exists(out_path):
        print(f"  ♻️ Cache thumbnail: {out_path}")
        return out_path

    W, H = 1600, 1200
    HEADER_H, FOOTER_H = 180, 160

    bg = Image.new("RGB", (W, H), (245, 245, 248))
    draw = ImageDraw.Draw(bg)

    # Gradient background
    for y in range(HEADER_H, H - FOOTER_H):
        ratio = (y - HEADER_H) / (H - FOOTER_H - HEADER_H)
        gray = int(248 - ratio * 18)
        draw.line([(0, y), (W, y)], fill=(gray, gray, gray + 4))

    # Header & Footer
    draw.rectangle([(0, 0), (W, HEADER_H)], fill=(13, 20, 40))
    draw.rectangle([(0, H - FOOTER_H), (W, H)], fill=(13, 20, 40))

    ACCENT = (220, 30, 40)
    draw.rectangle([(0, HEADER_H), (W, HEADER_H + 5)], fill=ACCENT)
    draw.rectangle([(0, H - FOOTER_H - 5), (W, H - FOOTER_H)], fill=ACCENT)

    # Font
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs = ImageFont.truetype(FONT_BOLD, 160)
        font_time = ImageFont.truetype(FONT_BOLD, 100)
        font_team = ImageFont.truetype(FONT_BOLD, 58)
    except:
        font_vs = font_time = font_team = ImageFont.load_default()

    content_top, content_bot = HEADER_H + 5, H - FOOTER_H - 5
    logo_size = 360
    name_h, time_h = 120, 110
    gap_logo_name, gap_name_time = 40, 60

    total_block_h = logo_size + gap_logo_name + name_h + gap_name_time + time_h
    block_top = content_top + (content_bot - content_top - total_block_h) // 2

    logo_y = block_top
    name_block_y = logo_y + logo_size + gap_logo_name
    name_center = name_block_y + name_h // 2
    time_y = name_block_y + name_h + gap_name_time + time_h // 2

    def draw_team_name(text, cx):
        max_width = W // 2 - 60
        font_size = 58
        f = font_team
        while font_size >= 28:
            try: f = ImageFont.truetype(FONT_BOLD, font_size)
            except: f = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= max_width: break
            font_size -= 3
        draw.text((cx, name_center), text, fill=(20, 20, 20), font=f, anchor="mm")

    # Draw Logos (FIXED: Paste với mask đúng)
    for logo_url, x_pos in [(match.get("logo_a"), W // 4 - logo_size // 2), 
                             (match.get("logo_b"), W * 3 // 4 - logo_size // 2)]:
        if logo_url:
            print(f"  🖼️ Fetching logo: {logo_url}")
            img = fetch_image(logo_url)
            if img:
                try:
                    # Resize và convert sang RGB để paste an toàn
                    img_resized = img.resize((logo_size, logo_size), Image.LANCZOS)
                    # Tạo mask từ alpha channel
                    mask = img_resized.split()[3] if img_resized.mode == 'RGBA' else None
                    bg.paste(img_resized, (x_pos, logo_y), mask)
                    print(f"  ✅ Logo pasted at ({x_pos}, {logo_y})")
                except Exception as e:
                    print(f"  ❌ Paste logo error: {e}")
            else:
                print(f"  ️ Logo fetch failed: {logo_url}")

    # VS text
    draw.text((W // 2, logo_y + logo_size // 2), "VS", fill=ACCENT, font=font_vs, anchor="mm")
    
    # Team names
    draw_team_name(match["team_a"], W // 4)
    draw_team_name(match["team_b"], W * 3 // 4)

    # Time
    time_display = f"{match['time']} {match['date']}" if match['time'] else "LIVE"
    draw.text((W // 2 + 4, time_y + 4), time_display, fill=ACCENT, font=font_time, anchor="mm")
    draw.text((W // 2, time_y), time_display, fill=(15, 15, 15), font=font_time, anchor="mm")

    # Border
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(180, 180, 180), width=3)
    bg.save(out_path, "PNG", optimize=True)
    print(f"  💾 Saved thumbnail: {out_path}")
    return out_path

def cleanup_old_thumbs(days: int = 3):
    if not os.path.exists(THUMBS_DIR): return
    cutoff = now_vn() - timedelta(days=days)
    deleted = 0
    for fname in os.listdir(THUMBS_DIR):
        if fname.endswith(".png"):
            m = re.search(r'_(\d{8})\.png$', fname)
            if m:
                try:
                    if datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=VN_TZ) < cutoff:
                        os.remove(os.path.join(THUMBS_DIR, fname))
                        deleted += 1
                except: pass
    if deleted: print(f"🗑️ Deleted {deleted} old thumbnails")

# ─────────────────────────────────────────────────────────────────────────────
# BUILD JSON
# ─────────────────────────────────────────────────────────────────────────────

def build_channel(match, match_id_safe, thumb_url):
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
    
    return {
        "id": make_id(match_id_safe, "ch"),
        "name": display_name,
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": f"● LIVE ({stream_count})", "position": "top-left", "color": "#00000080", "text_color": "#ff4444"}],
        "sources": [{
            "id": make_id(match_id_safe, "src"),
            "name": match["group"],
            "contents": [{
                "id": make_id(match_id_safe, "ct"),
                "name": f"{match['team_a']} vs {match['team_b']}",
                "streams": [{
                    "id": make_id(match_id_safe, "st"),
                    "name": "Streams",
                    "stream_links": stream_links
                }]
            }]
        }],
        "org_metadata": {
            "league": match["group"], "team_a": match["team_a"], "team_b": match["team_b"],
            "logo_a": match.get("logo_a", ""), "logo_b": match.get("logo_b", ""),
            "time": match["time"], "date": match["date"],
            "blv": ", ".join([s["blv"] for s in match["streams"]]),
            "is_live": True, "cate_type": match["cate_type"], "stream_count": stream_count
        },
        "image": {
            "padding": 1, "background_color": "#ffffff", "display": "contain",
            "url": thumb_url, "width": 1600, "height": 1200
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"⏰ Thời gian VN: {now_vn().strftime('%H:%M %d/%m/%Y')}")
    cleanup_old_thumbs(days=3)
    
    # 1. Tải M3U
    print(f"\n▶ BƯỚC 1: Tải M3U từ {M3U_URL}")
    try:
        res = requests.get(M3U_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        res.raise_for_status()
        with open(RAW_FILE, "w", encoding="utf-8") as f: f.write(res.text)
        lines = res.text.split('\n')
        print(f"✅ Đã tải {len(lines)} dòng")
    except Exception as e:
        print(f"❌ Lỗi tải M3U: {e}"); return

    # 2. Parse & SofaScore
    matches = process_m3u_data(lines)
    if not matches: return

    # 3. Tạo thumbnail & build JSON
    print(f"\n▶ BƯỚC 3: Tạo thumbnail và build JSON...")
    channels = []
    
    for i, match in enumerate(matches):
        match_id_safe = match["match_id"].replace(":", "-")
        print(f"\n[{i+1}/{len(matches)}] {match['team_a']} vs {match['team_b']}")
        
        thumb_path = make_thumbnail(match, match_id_safe)
        
        logo_hash = hashlib.md5((match.get("logo_a") or "").encode()).hexdigest()[:8]
        thumb_url = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else f"file://{os.path.abspath(thumb_path)}"
        
        channels.append(build_channel(match, match_id_safe, thumb_url))
        time.sleep(0.1)

    # 4. Gom nhóm theo Category
    grouped_channels = {cate: [] for cate in CATE_ORDER}
    for ch in channels:
        cate = ch["org_metadata"]["cate_type"]
        if cate not in grouped_channels: grouped_channels[cate] = []
        grouped_channels[cate].append(ch)

    output_groups = []
    for cate in CATE_ORDER:
        ch_list = grouped_channels.get(cate, [])
        if not ch_list: continue
        live_cnt = sum(1 for ch in ch_list if ch["org_metadata"].get("is_live"))
        cate_name = f"{CATE_MAP.get(cate, ' Thể Thao')} ({live_cnt} LIVE)" if live_cnt > 0 else CATE_MAP.get(cate, '🏅 Thể Thao')
        
        output_groups.append({
            "id": f"cate_{cate}", "name": cate_name, "display": "vertical",
            "grid_number": 2, "enable_detail": False, "channels": ch_list
        })

    output = {
        "id": "tinhlagi_filtered", "url": "https://tinhlagi.pro", "name": "TinhLagi Filtered",
        "color": "#e63946", "grid_number": 3,
        "image": {"type": "cover", "url": "https://tinhlagi.pro/favicon.ico"},
        "groups": output_groups
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n🎉 HOÀN TẤT! {len(channels)} trận → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
