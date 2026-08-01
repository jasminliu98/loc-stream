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
    "Soccer": "football", "Football": "football", "Basketball": "basketball", 
    "Tennis": "tennis", "Volleyball": "bongchuyen", "Badminton": "caulong", 
    "Motorsport": "duaxe", "Esports": "esport", "Rugby": "football", 
    "Baseball": "bongchay", "Ice Hockey": "other", "American Football": "other"
}

CATE_DISPLAY = {
    "football": "⚽ Bóng Đá", "basketball": "🏀 Bóng Rổ", "tennis": "🎾 Tennis",
    "bongchuyen": "🏐 Bóng Chuyền", "esport": "🎮 Esport", "caulong": "🏸 Cầu Lông",
    "vothuat": "🥊 Võ Thuật", "bongchay": "⚾ Bóng Chày", "duaxe": "🏎️ Đua Xe", 
    "Billiards": " Billiards", "other": "🏅 Thể Thao Khác"
}
CATE_ORDER = ["football", "basketball", "tennis", "bongchuyen", "esport", "caulong", "vothuat", "bongchay", "duaxe", "Billiards", "other"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TEAM_CACHE = {}

def now_vn():
    return datetime.now(tz=VN_TZ)

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

# ─────────────────────────────────────────────────────────────────────────────
# CLEAN TEAM NAME
# ─────────────────────────────────────────────────────────────────────────────

def clean_team_name(raw_name):
    if not raw_name: return ""
    name = raw_name.strip()
    name = re.sub(r'\s*\([^)]*\)', '', name) # Bỏ (BLV)
    name = re.sub(r'\s*\[[^\]]*\]', '', name) # Bỏ [FHD]
    name = re.sub(r'\s+', ' ', name).strip()
    return name.title()

# ─────────────────────────────────────────────────────────────────────────────
# PARSE MATCH INFO
# ─────────────────────────────────────────────────────────────────────────────

def parse_match_info(channel_name):
    if not channel_name: return None, None, "Unknown", "", "Stream"
    time_match = re.match(r'(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2})\s+(.*)', channel_name)
    if not time_match: return None, None, channel_name, "", "Stream"
    
    time_str, date_str, rest = time_match.group(1), time_match.group(2), time_match.group(3).strip()
    vs_match = re.split(r'\s+vs\s+', rest, flags=re.IGNORECASE, maxsplit=1)
    
    if len(vs_match) == 2:
        team_a_raw, team_b_raw = vs_match[0].strip(), vs_match[1].strip()
        blv_match = re.search(r'\(([^)]+)\)', team_b_raw)
        blv_info = blv_match.group(1).strip() if blv_match else "Stream"
        return time_str, date_str, clean_team_name(team_a_raw), clean_team_name(team_b_raw), blv_info
    
    return time_str, date_str, clean_team_name(rest), "", "Stream"

# ────────────────────────────────────────────────────────────────────────────
# THESPORTSDB API (THAY THẾ SOFASCORE)
# ─────────────────────────────────────────────────────────────────────────────

def get_team_info_from_sportsdb(team_name):
    """
    Lấy Category và Logo từ TheSportsDB.
    API này KHÔNG CHẶN bot từ GitHub Actions.
    """
    if not team_name or len(team_name) < 3:
        return "football", None
        
    if team_name in TEAM_CACHE:
        return TEAM_CACHE[team_name]

    try:
        # Endpoint miễn phí, không cần API key cho 100 req/ngày
        url = f"https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={requests.utils.quote(team_name)}"
        print(f"  🔍 TheSportsDB: {team_name}")
        
        res = requests.get(url, headers=HEADERS, timeout=10)
        data = res.json()
        
        teams = data.get('teams', [])
        if teams:
            # Lấy kết quả đầu tiên (thường là chính xác nhất)
            best_match = teams[0]
            
            # Map category
            sport_name = best_match.get('strSport', 'Soccer')
            cate_type = CATE_MAP.get(sport_name, "football")
            
            # Lấy logo
            logo_url = best_match.get('strBadge')
            
            print(f"  ✅ Match: {team_name} → {sport_name} | Logo: {logo_url}")
            TEAM_CACHE[team_name] = (cate_type, logo_url)
            return cate_type, logo_url
        else:
            print(f"  ⚠️ Không tìm thấy: {team_name}")
            
    except Exception as e:
        print(f"  ❌ Lỗi API: {e}")
        
    TEAM_CACHE[team_name] = ("football", None)
    return "football", None

def download_logo(logo_url, save_path):
    if not logo_url: return False
    try:
        res = requests.get(logo_url, headers=HEADERS, timeout=10)
        if res.status_code == 200 and len(res.content) > 1000:
            with open(save_path, 'wb') as f: f.write(res.content)
            return True
    except: pass
    return False

def fetch_image(url_or_path):
    if not url_or_path: return None
    try:
        if url_or_path.startswith('http'):
            res = requests.get(url_or_path, headers=HEADERS, timeout=10)
            if res.status_code == 200: return Image.open(BytesIO(res.content)).convert("RGBA")
        else:
            if os.path.exists(url_or_path): return Image.open(url_or_path).convert("RGBA")
    except: pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS M3U DATA
# ────────────────────────────────────────────────────────────────────────────

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
                match_key = f"{time_str}_{date_str}_{team_a.lower()}_{team_b.lower()}"
                
                if match_key not in matches_dict:
                    matches_dict[match_key] = {
                        "match_id": make_id(match_key, "match"),
                        "time": time_str, "date": date_str,
                        "team_a": team_a, "team_b": team_b,
                        "group": group_title, "streams": [],
                        "logo_a_local": None, "logo_b_local": None
                    }
                matches_dict[match_key]["streams"].append({"url": line, "blv": blv_info})
            current_extinf = None

    if not matches_dict:
        print("⚠️ Không tìm thấy trận nào!"); return []

    print(f"\n▶ Đang tra cứu {len(matches_dict)} trận từ TheSportsDB...")
    final_matches = []
    
    for key, match in matches_dict.items():
        print(f"\n  🔍 {match['team_a']} vs {match['team_b']}")
        cate_a, logo_a_url = get_team_info_from_sportsdb(match["team_a"])
        cate_b, logo_b_url = get_team_info_from_sportsdb(match["team_b"])
        
        if logo_a_url:
            path = f"{THUMBS_DIR}/logo_a_{match['team_a'].replace(' ', '_')}.png"
            if download_logo(logo_a_url, path): match["logo_a_local"] = path
        if logo_b_url:
            path = f"{THUMBS_DIR}/logo_b_{match['team_b'].replace(' ', '_')}.png"
            if download_logo(logo_b_url, path): match["logo_b_local"] = path
        
        match["cate_type"] = cate_a if cate_a == cate_b else "football"
        match["logo_a"] = match["logo_a_local"] or logo_a_url
        match["logo_b"] = match["logo_b_local"] or logo_b_url
        final_matches.append(match)
        time.sleep(0.2)
    
    return final_matches

# ────────────────────────────────────────────────────────────────────────────
# THUMBNAIL GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, match_id_safe):
    cache_key = (match.get("team_a") or "") + (match.get("team_b") or "") + "v6"
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    date_str = now_vn().strftime("%Y%m%d")
    out_path = f"{THUMBS_DIR}/{match_id_safe}_{logo_hash}_{date_str}.png"
    if os.path.exists(out_path): return out_path

    W, H = 1600, 1200
    HEADER_H, FOOTER_H = 180, 160
    bg = Image.new("RGB", (W, H), (245, 245, 248))
    draw = ImageDraw.Draw(bg)

    for y in range(HEADER_H, H - FOOTER_H):
        ratio = (y - HEADER_H) / (H - FOOTER_H - HEADER_H)
        gray = int(248 - ratio * 18)
        draw.line([(0, y), (W, y)], fill=(gray, gray, gray + 4))

    draw.rectangle([(0, 0), (W, HEADER_H)], fill=(13, 20, 40))
    draw.rectangle([(0, H - FOOTER_H), (W, H)], fill=(13, 20, 40))
    ACCENT = (220, 30, 40)
    draw.rectangle([(0, HEADER_H), (W, HEADER_H + 5)], fill=ACCENT)
    draw.rectangle([(0, H - FOOTER_H - 5), (W, H - FOOTER_H)], fill=ACCENT)

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

    for logo_src, x_pos in [(match.get("logo_a"), W // 4 - logo_size // 2), (match.get("logo_b"), W * 3 // 4 - logo_size // 2)]:
        if logo_src:
            img = fetch_image(logo_src)
            if img:
                try:
                    img_resized = img.resize((logo_size, logo_size), Image.LANCZOS)
                    bg.paste(img_resized, (x_pos, logo_y), img_resized if img_resized.mode == 'RGBA' else None)
                except: pass

    draw.text((W // 2, logo_y + logo_size // 2), "VS", fill=ACCENT, font=font_vs, anchor="mm")
    draw_team_name(match["team_a"], W // 4)
    draw_team_name(match["team_b"], W * 3 // 4)

    time_display = f"{match['time']} {match['date']}" if match['time'] else "LIVE"
    draw.text((W // 2 + 4, time_y + 4), time_display, fill=ACCENT, font=font_time, anchor="mm")
    draw.text((W // 2, time_y), time_display, fill=(15, 15, 15), font=font_time, anchor="mm")
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(180, 180, 180), width=3)
    bg.save(out_path, "PNG", optimize=True)
    return out_path

def cleanup_old_thumbs(days: int = 3):
    if not os.path.exists(THUMBS_DIR): return
    cutoff = now_vn() - timedelta(days=days)
    for fname in os.listdir(THUMBS_DIR):
        if fname.endswith(".png"):
            m = re.search(r'_(\d{8})\.png$', fname)
            if m:
                try:
                    if datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=VN_TZ) < cutoff:
                        os.remove(os.path.join(THUMBS_DIR, fname))
                except: pass

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
    return {
        "id": make_id(match_id_safe, "ch"),
        "name": display_name,
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": f"● LIVE ({len(stream_links)})", "position": "top-left", "color": "#00000080", "text_color": "#ff4444"}],
        "sources": [{
            "id": make_id(match_id_safe, "src"),
            "name": match["group"],
            "contents": [{
                "id": make_id(match_id_safe, "ct"),
                "name": f"{match['team_a']} vs {match['team_b']}",
                "streams": [{"id": make_id(match_id_safe, "st"), "name": "Streams", "stream_links": stream_links}]
            }]
        }],
        "org_metadata": {
            "league": match["group"], "team_a": match["team_a"], "team_b": match["team_b"],
            "logo_a": match.get("logo_a", ""), "logo_b": match.get("logo_b", ""),
            "time": match["time"], "date": match["date"],
            "blv": ", ".join([s["blv"] for s in match["streams"]]),
            "is_live": True, "cate_type": match["cate_type"]
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
    
    print(f"\n▶ BƯỚC 1: Tải M3U từ {M3U_URL}")
    try:
        res = requests.get(M3U_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        with open(RAW_FILE, "w", encoding="utf-8") as f: f.write(res.text)
        lines = res.text.split('\n')
    except Exception as e:
        print(f"❌ Lỗi tải M3U: {e}"); return

    matches = process_m3u_data(lines)
    if not matches: return

    print(f"\n▶ BƯỚC 3: Tạo thumbnail và build JSON...")
    channels = []
    for i, match in enumerate(matches):
        match_id_safe = match["match_id"].replace(":", "-")
        thumb_path = make_thumbnail(match, match_id_safe)
        logo_hash = hashlib.md5((match.get("team_a") or "").encode()).hexdigest()[:8]
        thumb_url = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else f"file://{os.path.abspath(thumb_path)}"
        channels.append(build_channel(match, match_id_safe, thumb_url))
        time.sleep(0.1)

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
        cate_name = f"{CATE_DISPLAY.get(cate, '🏅 Thể Thao')} ({live_cnt} LIVE)" if live_cnt > 0 else CATE_DISPLAY.get(cate, '🏅 Thể Thao')
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
