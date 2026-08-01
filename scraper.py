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

CATE_DISPLAY = {
    "football": "⚽ Bóng Đá", 
    "volleyball": "🏐 Bóng Chuyền", 
    "other": "🏅 Thể Thao Khác"
}

VOLLEYBALL_COUNTRIES = [
    "vietnam", "japan", "slovakia", "poland", "usa", "brazil", "italy", 
    "serbia", "turkey", "thailand", "china", "dominican republic", "canada", 
    "netherlands", "france", "germany", "bulgaria", "slovenia", "belgium",
    "philippines", "indonesia"
]

COUNTRY_TO_FLAG = {
    "vietnam": "vn", "japan": "jp", "slovakia": "sk", "poland": "pl",
    "usa": "us", "brazil": "br", "italy": "it", "serbia": "rs",
    "turkey": "tr", "china": "cn", "dominican republic": "do", "canada": "ca",
    "netherlands": "nl", "france": "fr", "germany": "de", "thailand": "th",
    "bulgaria": "bg", "slovenia": "si", "belgium": "be", "philippines": "ph", "indonesia": "id"
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def now_vn():
    return datetime.now(tz=VN_TZ)

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

# ─────────────────────────────────────────────────────────────────────────────
# LOGIC XỬ LÝ
# ─────────────────────────────────────────────────────────────────────────────

def clean_team_name(raw_name):
    if not raw_name: return ""
    name = re.sub(r'\s*\([^)]*\)', '', raw_name)
    name = re.sub(r'\s*\[[^\]]*\]', '', name)
    return re.sub(r'\s+', ' ', name).strip().title()

def is_match_relevant(time_str, date_str):
    """
    Chỉ giữ lại trận: Đang diễn ra (trong vòng 2.5 tiếng qua) HOẶC sắp bắt đầu (<= 15 phút)
    """
    if not time_str or not date_str:
        return True # Nếu không có giờ, giữ lại để an toàn
    
    now = now_vn()
    try:
        day, month = map(int, date_str.split('/'))
        hour, minute = map(int, time_str.split(':'))
        
        # Tạo datetime của trận đấu (giả sử cùng năm)
        match_dt = datetime(now.year, month, day, hour, minute, tzinfo=VN_TZ)
        
        # Xử lý trường hợp qua năm mới (ví dụ: giờ là 31/12, trận là 01/01)
        if match_dt < now and (now - match_dt).days > 20:
            match_dt = match_dt.replace(year=now.year + 1)
            
        diff_minutes = (match_dt - now).total_seconds() / 60
        
        # Giữ nếu: Đã bắt đầu tối đa 150 phút (2.5 tiếng) trước, hoặc sắp bắt đầu trong 15 phút tới
        if -150 <= diff_minutes <= 15:
            return True
        return False
    except Exception:
        return True

def search_sportsdb(team_name, sport_filter):
    try:
        url = f"https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={requests.utils.quote(team_name)}"
        res = requests.get(url, headers=HEADERS, timeout=10)
        teams = res.json().get('teams', [])
        
        for team in teams:
            if team.get('strSport', '').lower() == sport_filter.lower():
                db_name = team.get('strTeam', '').lower()
                search_name = team_name.lower()
                if search_name in db_name or db_name in search_name:
                    return team
        return None
    except:
        return None

def get_flag_url(team_name):
    team_lower = team_name.lower()
    for country, code in COUNTRY_TO_FLAG.items():
        if country in team_lower or team_lower in country:
            return f"https://flagcdn.com/w320/{code}.png"
    return None

def resolve_team_data(team_name, is_volleyball_context):
    """
    Logic phân loại: Ưu tiên Bóng Đá. Chỉ chuyển Bóng Chuyền nếu có ngữ cảnh rõ ràng.
    KHÔNG BAO GIỜ trả về 'other' cho các trận có tên đội rõ ràng.
    """
    if not team_name or len(team_name) < 2:
        return "football", None
        
    # 1. Thử tìm trên TheSportsDB
    sport_to_search = "Volleyball" if is_volleyball_context else "Football"
    db_data = search_sportsdb(team_name, sport_to_search)
    
    if db_data and db_data.get('strBadge'):
        cate = "volleyball" if sport_to_search == "Volleyball" else "football"
        return cate, db_data.get('strBadge')
        
    # 2. Fallback: Nếu không tìm thấy, dùng Cờ quốc gia (nếu là nước)
    flag_url = get_flag_url(team_name)
    
    # 3. Quyết định category: Nếu là ngữ cảnh bóng chuyền HOẶC là tên quốc gia -> Volleyball. Ngược lại -> Football
    if is_volleyball_context or flag_url:
        return "volleyball", flag_url
    
    # Mặc định là Bóng Đá cho các CLB (Girona, Arsenal, Porto...)
    return "football", flag_url

def download_logo(logo_url, save_path):
    if not logo_url: return False
    try:
        res = requests.get(logo_url, headers=HEADERS, timeout=10)
        if res.status_code == 200 and len(res.content) > 500:
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
# MAIN PROCESS
# ─────────────────────────────────────────────────────────────────────────────

def process_m3u():
    print("▶ Đang tải và xử lý M3U...")
    try:
        res = requests.get(M3U_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        with open(RAW_FILE, "w", encoding="utf-8") as f: f.write(res.text)
        lines = res.text.split('\n')
    except Exception as e:
        print(f"❌ Lỗi tải M3U: {e}"); return []

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
                
                # Parse time và đội
                time_match = re.match(r'(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2})\s+(.*)', channel_name)
                if time_match:
                    time_str, date_str, rest = time_match.group(1), time_match.group(2), time_match.group(3).strip()
                    
                    # LỌC THỜI GIAN: Chỉ giữ trận trong vòng 15 phút hoặc đang live
                    if not is_match_relevant(time_str, date_str):
                        current_extinf = None
                        continue 
                        
                    vs_match = re.split(r'\s+vs\s+', rest, flags=re.IGNORECASE, maxsplit=1)
                    if len(vs_match) == 2:
                        team_a = clean_team_name(vs_match[0])
                        team_b = clean_team_name(vs_match[1])
                    else:
                        team_a, team_b = clean_team_name(rest), "Unknown"
                else:
                    time_str, date_str, team_a, team_b = "", "", channel_name, ""

                # Kiểm tra ngữ cảnh Bóng chuyền
                is_vb = any(kw in current_extinf.lower() for kw in ["vnl", "fivb", "bóng chuyền", "bong chuyen", "volleyball"])
                # Hoặc nếu cả 2 đội đều là quốc gia nổi tiếng về bóng chuyền
                if not is_vb and team_a.lower() in VOLLEYBALL_COUNTRIES and team_b.lower() in VOLLEYBALL_COUNTRIES:
                    is_vb = True

                match_key = f"{time_str}_{date_str}_{team_a.lower()}_{team_b.lower()}"
                
                if match_key not in matches_dict:
                    matches_dict[match_key] = {
                        "match_id": make_id(match_key, "match"),
                        "time": time_str, "date": date_str,
                        "team_a": team_a, "team_b": team_b,
                        "is_vb_context": is_vb,
                        "streams": [], "logo_a": None, "logo_b": None, "cate": "football"
                    }
                matches_dict[match_key]["streams"].append({"url": line, "blv": "Stream"})
            current_extinf = None

    print(f"▶ Đang phân giải dữ liệu và tải logo cho {len(matches_dict)} trận phù hợp...")
    final_matches = []
    for match in matches_dict.values():
        print(f"\n  🔍 {match['team_a']} vs {match['team_b']}")
        
        cate_a, logo_a = resolve_team_data(match['team_a'], match['is_vb_context'])
        cate_b, logo_b = resolve_team_data(match['team_b'], match['is_vb_context'])
        
        # Nếu 1 trong 2 đội được nhận diện là bóng chuyền, cả trận là bóng chuyền
        final_cate = "volleyball" if "volleyball" in [cate_a, cate_b] else "football"
        
        if logo_a:
            path = f"{THUMBS_DIR}/la_{make_id(match['team_a'], 't')}.png"
            if download_logo(logo_a, path): match["logo_a"] = path
            
        if logo_b:
            path = f"{THUMBS_DIR}/lb_{make_id(match['team_b'], 't')}.png"
            if download_logo(logo_b, path): match["logo_b"] = path
            
        match["cate"] = final_cate
        final_matches.append(match)
        time.sleep(0.2)
        
    return final_matches

# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL & JSON BUILD
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, match_id_safe):
    cache_key = (match.get("team_a") or "") + (match.get("team_b") or "") + "v10"
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

def build_channel(match, match_id_safe, thumb_url):
    stream_links = []
    for idx, stream in enumerate(match["streams"]):
        stream_links.append({
            "id": make_id(stream["url"] + str(idx), "lnk"),
            "name": stream["blv"],
            "type": "hls",
            "default": idx == 0,
            "url": stream["url"],
            "request_headers": [{"key": "User-Agent", "value": "Mozilla/5.0"}, {"key": "Referer", "value": "https://live.chuoichien.tv/"}]
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
            "name": "Chuối Chiên TV",
            "contents": [{
                "id": make_id(match_id_safe, "ct"),
                "name": f"{match['team_a']} vs {match['team_b']}",
                "streams": [{"id": make_id(match_id_safe, "st"), "name": "Streams", "stream_links": stream_links}]
            }]
        }],
        "org_metadata": {
            "league": "Trực Tiếp", "team_a": match["team_a"], "team_b": match["team_b"],
            "time": match["time"], "date": match["date"],
            "blv": ", ".join([s["blv"] for s in match["streams"]]),
            "is_live": True, "cate_type": match["cate"]
        },
        "image": {
            "padding": 1, "background_color": "#ffffff", "display": "contain",
            "url": thumb_url, "width": 1600, "height": 1200
        }
    }

def main():
    print(f"⏰ Thời gian VN: {now_vn().strftime('%H:%M %d/%m/%Y')}")
    cleanup_old_thumbs(days=3)

    matches = process_m3u()
    if not matches:
        print("⚠️ Không tìm thấy trận nào trong khung giờ hợp lệ!")
        return
    
    print(f"\n▶ Đang tạo thumbnail và build JSON...")
    channels = []
    for i, match in enumerate(matches):
        match_id_safe = match["match_id"].replace(":", "-")
        thumb_path = make_thumbnail(match, match_id_safe)
        logo_hash = hashlib.md5((match.get("team_a") or "").encode()).hexdigest()[:8]
        thumb_url = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else f"file://{os.path.abspath(thumb_path)}"
        channels.append(build_channel(match, match_id_safe, thumb_url))
        time.sleep(0.1)

    # Group by category
    grouped = {"volleyball": [], "football": [], "other": []}
    for ch in channels:
        cate = ch["org_metadata"]["cate_type"]
        if cate in grouped: grouped[cate].append(ch)
        else: grouped["other"].append(ch)

    output_groups = []
    for cate in ["volleyball", "football", "other"]:
        ch_list = grouped[cate]
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
