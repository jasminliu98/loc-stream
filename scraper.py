import requests
import json
import hashlib
import re
import os
import time
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

FILTER_KEYWORDS = ["chuối chiên", "chuoi chien", "chuối chiên tv"]

CATE_DISPLAY = {
    "football": "⚽ Bóng Đá", 
    "volleyball": "🏐 Bóng Chuyền"
}

# Danh sách các quốc gia VNL / Bóng chuyền
VNL_COUNTRIES = {
    "vietnam", "japan", "slovakia", "poland", "usa", "brazil", "italy", 
    "serbia", "turkey", "thailand", "china", "dominican republic", "canada", 
    "netherlands", "france", "germany", "bulgaria", "slovenia", "belgium",
    "philippines", "indonesia", "south korea", "croatia", "mexico"
}

COUNTRY_TO_FLAG = {
    "vietnam": "vn", "japan": "jp", "slovakia": "sk", "poland": "pl",
    "usa": "us", "brazil": "br", "italy": "it", "serbia": "rs",
    "turkey": "tr", "china": "cn", "dominican republic": "do", "canada": "ca",
    "netherlands": "nl", "france": "fr", "germany": "de", "thailand": "th",
    "bulgaria": "bg", "slovenia": "si", "belgium": "be", "philippines": "ph", 
    "indonesia": "id", "south korea": "kr", "croatia": "hr", "mexico": "mx"
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def now_vn():
    return datetime.now(tz=VN_TZ)

def make_id(text, prefix):
    return f"{prefix}-{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"

# ─────────────────────────────────────────────────────────────────────────────
# LOGIC TRA CỨU WEB (DUCKDUCKGO FALLBACK)
# ─────────────────────────────────────────────────────────────────────────────

def check_sport_via_web(team_a, team_b):
    """
    Tra cứu nhanh trên DuckDuckGo HTML để xác định môn thể thao.
    Không bị chặn, không cần API key.
    """
    query = f"{team_a} vs {team_b} bóng chuyền OR volleyball OR bóng đá OR football match"
    url = f"https://html.duckduckgo.com/html?q={urllib.parse.quote(query)}"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            text = res.text.lower()
            
            # Tìm vị trí xuất hiện của các từ khóa
            pos_vb = min(
                text.find("volleyball") if "volleyball" in text else 9999,
                text.find("bóng chuyền") if "bóng chuyền" in text else 9999,
                text.find("vnl") if "vnl" in text else 9999
            )
            pos_fb = min(
                text.find("football") if "football" in text else 9999,
                text.find("bóng đá") if "bóng đá" in text else 9999,
                text.find("soccer") if "soccer" in text else 9999
            )
            
            # Nếu từ khóa bóng chuyền xuất hiện TRƯỚC bóng đá, hoặc bóng đá không tồn tại
            if pos_vb < pos_fb and pos_vb != 9999:
                print(f"  🌐 Web Check: {team_a} vs {team_b} -> Volleyball")
                return "volleyball"
            elif pos_fb != 9999:
                print(f"  🌐 Web Check: {team_a} vs {team_b} -> Football")
                return "football"
    except Exception as e:
        print(f"  ⚠️ Web check failed: {e}")
        
    return "football" # Fallback an toàn

def determine_sport_smart(team_a, team_b, channel_name, group_title):
    """
    Logic phân loại 3 lớp:
    1. Từ khóa rõ ràng trong M3U.
    2. Kiểm tra danh sách quốc gia VNL.
    3. Nếu vẫn nghi ngờ, hỏi DuckDuckGo.
    """
    text = f"{channel_name} {group_title}".lower()
    
    # Lớp 1: Từ khóa cứng
    if any(kw in text for kw in ["vnl", "fivb", "bóng chuyền", "bong chuyen", "volleyball"]):
        return "volleyball"
    
    team_a_lower = team_a.lower()
    team_b_lower = team_b.lower()
    
    # Lớp 2: Kiểm tra quốc gia VNL
    is_a_vnl = team_a_lower in VNL_COUNTRIES or any(c in team_a_lower for c in VNL_COUNTRIES)
    is_b_vnl = team_b_lower in VNL_COUNTRIES or any(c in team_b_lower for c in VNL_COUNTRIES)
    
    if is_a_vnl and is_b_vnl:
        return "volleyball"
        
    if (" w " in team_a_lower or team_a_lower.endswith(" w")) and is_a_vnl:
        return "volleyball"
    if (" w " in team_b_lower or team_b_lower.endswith(" w")) and is_b_vnl:
        return "volleyball"
        
    # Lớp 3: Nếu là 2 tên ngắn (có thể là quốc gia) nhưng không nằm trong list, hỏi Web
    if len(team_a.split()) <= 2 and len(team_b.split()) <= 2:
        return check_sport_via_web(team_a, team_b)
        
    # Mặc định: CLB = Bóng đá
    return "football"

# ─────────────────────────────────────────────────────────────────────────────
# CÁC HÀM XỬ LÝ M3U & LOGO (Giữ nguyên như bản trước)
# ─────────────────────────────────────────────────────────────────────────────

def clean_team_name(raw_name):
    if not raw_name: return ""
    name = re.sub(r'\s*\([^)]*\)', '', raw_name)
    name = re.sub(r'\s*\[[^\]]*\]', '', name)
    return re.sub(r'\s+', ' ', name).strip().title()

def is_match_relevant(time_str, date_str):
    if not time_str or not date_str: return True
    now = now_vn()
    try:
        day, month = map(int, date_str.split('/'))
        hour, minute = map(int, time_str.split(':'))
        match_dt = datetime(now.year, month, day, hour, minute, tzinfo=VN_TZ)
        if match_dt < now and (now - match_dt).days > 20:
            match_dt = match_dt.replace(year=now.year + 1)
        diff_minutes = (match_dt - now).total_seconds() / 60
        return -150 <= diff_minutes <= 15 
    except:
        return True

def parse_logos_from_m3u(extinf_line):
    logo_match = re.search(r'tvg-logo="([^"]*)"', extinf_line)
    if not logo_match: return None, None
    logo_url = logo_match.group(1)
    if "merge_logos.php" in logo_url:
        try:
            parsed = urllib.parse.urlparse(logo_url)
            params = urllib.parse.parse_qs(parsed.query)
            home = urllib.parse.unquote(params.get('home', [None])[0])
            away = urllib.parse.unquote(params.get('away', [None])[0])
            return home, away
        except: pass
    return logo_url, None

def get_fallback_logo(team_name):
    team_lower = team_name.lower()
    for country, code in COUNTRY_TO_FLAG.items():
        if country in team_lower or team_lower in country:
            return f"https://flagcdn.com/w320/{code}.png"
    return None

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
                
                time_match = re.match(r'(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2})\s+(.*)', channel_name)
                if time_match:
                    time_str, date_str, rest = time_match.group(1), time_match.group(2), time_match.group(3).strip()
                    
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

                # Phân loại thông minh có hỏi Web nếu cần
                cate = determine_sport_smart(team_a, team_b, channel_name, "")
                
                logo_a_url, logo_b_url = parse_logos_from_m3u(current_extinf)
                if not logo_a_url: logo_a_url = get_fallback_logo(team_a)
                if not logo_b_url: logo_b_url = get_fallback_logo(team_b)

                match_key = f"{time_str}_{date_str}_{team_a.lower()}_{team_b.lower()}"
                
                if match_key not in matches_dict:
                    matches_dict[match_key] = {
                        "match_id": make_id(match_key, "match"),
                        "time": time_str, "date": date_str,
                        "team_a": team_a, "team_b": team_b,
                        "cate": cate,
                        "streams": [], 
                        "logo_a": logo_a_url, "logo_b": logo_b_url,
                        "logo_a_local": None, "logo_b_local": None
                    }
                matches_dict[match_key]["streams"].append({"url": line, "blv": "Stream"})
            current_extinf = None

    print(f"▶ Đang tải logo cho {len(matches_dict)} trận...")
    final_matches = []
    for match in matches_dict.values():
        if match["logo_a"]:
            path = f"{THUMBS_DIR}/la_{make_id(match['team_a'], 't')}.png"
            if download_logo(match["logo_a"], path): match["logo_a_local"] = path
            
        if match["logo_b"]:
            path = f"{THUMBS_DIR}/lb_{make_id(match['team_b'], 't')}.png"
            if download_logo(match["logo_b"], path): match["logo_b_local"] = path
            
        match["final_logo_a"] = match["logo_a_local"] or match["logo_a"]
        match["final_logo_b"] = match["logo_b_local"] or match["logo_b"]
        final_matches.append(match)
        time.sleep(0.1)
        
    return final_matches

# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL & JSON BUILD (Giữ nguyên chuẩn format)
# ─────────────────────────────────────────────────────────────────────────────
# (Đoạn code make_thumbnail, cleanup_old_thumbs, build_channel giữ nguyên như các bản trước)

def make_thumbnail(match, match_id_safe):
    cache_key = (match.get("team_a") or "") + (match.get("team_b") or "") + "v13"
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

    for logo_src, x_pos in [(match.get("final_logo_a"), W // 4 - logo_size // 2), (match.get("final_logo_b"), W * 3 // 4 - logo_size // 2)]:
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

    grouped = {"volleyball": [], "football": []}
    for ch in channels:
        cate = ch["org_metadata"]["cate_type"]
        if cate in grouped: 
            grouped[cate].append(ch)
        else: 
            grouped["football"].append(ch)

    output_groups = []
    for cate in ["volleyball", "football"]:
        ch_list = grouped[cate]
        if not ch_list: continue
        live_cnt = sum(1 for ch in ch_list if ch["org_metadata"].get("is_live"))
        cate_name = f"{CATE_DISPLAY.get(cate)} ({live_cnt} LIVE)" if live_cnt > 0 else CATE_DISPLAY.get(cate)
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
