import os
import re
import asyncio
import anthropic
import httpx
from io import BytesIO
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ─── System prompts ────────────────────────────────────────────────────────────

SYSTEM_ANALYST = """Bạn là trợ lý phân tích nội dung cho kênh YouTube "Tiệm Truyện Nhỏ Nhỏ" — kênh kể chuyện cổ tích, dân gian và triết lý Việt Nam.
Nhiệm vụ: đọc nội dung thô → tóm tắt cốt lõi câu chuyện trong 3–5 câu, xác định thể loại (cổ tích/dân gian/triết lý/tâm lý), tông giọng phù hợp (ấm áp/lạnh/triết lý), và độ dài video gợi ý.
Trả lời ngắn gọn, súc tích, bằng tiếng Việt."""

BIBI_INTRO_TEMPLATE = (
    'Tích tắc, tích tắc… Đồng hồ đã điểm giờ đi ngủ rồi! '
    'Bibi xin chào các bạn nhỏ đáng yêu của "Thế Giới Cổ Tích Của Bibi"! '
    'Hôm nay, chiếc đuôi phát sáng của Bibi đã chọn được một câu chuyện vô cùng kỳ diệu mang tên: {ten_truyen}. '
    'Các em đã nằm ngoan chưa? Chúng mình cùng bắt đầu nhé…'
)

BIBI_OUTRO_TEMPLATE = (
    'Câu chuyện hôm nay đến đây là hết rồi. '
    'Các em thấy {nhan_vat} có đáng yêu không nào? '
    'Bây giờ thì nhắm mắt lại thôi, để ánh sáng dịu dàng của Bibi canh giấc ngủ cho các em nhé. '
    'Đừng quên nhấn thích và đăng ký kênh ủng hộ Bibi nha! '
    'Chúc các bé ngủ ngon và có những giấc mơ thật đẹp! '
    'Chào tạm biệt và hẹn gặp lại các em vào tối mai! Suỵt… ngủ ngon nhé…'
)

SYSTEM_SCRIPT = """Bạn là biên kịch chuyên nghiệp cho kênh "Tiệm Truyện Nhỏ Nhỏ" / "Thế Giới Cổ Tích Của Bibi".
Nhiệm vụ: viết kịch bản TTS hoàn chỉnh từ nội dung câu chuyện.

NHÂN VẬT DẪN TRUYỆN — BIBI:
- Bibi là chú đom đóm nhỏ đáng yêu, đuôi phát sáng, là người dẫn truyện xuyên suốt video cho các bé trước giờ đi ngủ.
- MỞ ĐẦU kịch bản BẮT BUỘC dùng đúng nguyên văn mẫu lời chào sau, chỉ điền tên truyện vào chỗ {ten_truyen}:
"Tích tắc, tích tắc… Đồng hồ đã điểm giờ đi ngủ rồi! Bibi xin chào các bạn nhỏ đáng yêu của "Thế Giới Cổ Tích Của Bibi"! Hôm nay, chiếc đuôi phát sáng của Bibi đã chọn được một câu chuyện vô cùng kỳ diệu mang tên: {ten_truyen}. Các em đã nằm ngoan chưa? Chúng mình cùng bắt đầu nhé…"
- KẾT THÚC kịch bản BẮT BUỘC dùng đúng nguyên văn mẫu lời chào sau, chỉ điền tên nhân vật chính vào chỗ {nhan_vat}:
"Câu chuyện hôm nay đến đây là hết rồi. Các em thấy {nhan_vat} có đáng yêu không nào? Bây giờ thì nhắm mắt lại thôi, để ánh sáng dịu dàng của Bibi canh giấc ngủ cho các em nhé. Đừng quên nhấn thích và đăng ký kênh ủng hộ Bibi nha! Chúc các bé ngủ ngon và có những giấc mơ thật đẹp! Chào tạm biệt và hẹn gặp lại các em vào tối mai! Suỵt… ngủ ngon nhé…"
- TRONG THÂN TRUYỆN: Bibi đóng vai người dẫn truyện, xen vào những lời bình nhẹ nhàng, hỏi các bé, hoặc bày tỏ cảm xúc (ngạc nhiên, hồi hộp, ấm áp) ở những điểm chuyển cảnh quan trọng — khoảng 3-5 lần xen trong toàn bộ kịch bản, mỗi lần 1-2 câu ngắn, giọng dịu dàng dành cho trẻ nhỏ trước giờ ngủ.
- Giọng của Bibi luôn ấm áp, nhẹ nhàng, dịu dàng — phù hợp ru ngủ trẻ em, KHÔNG dùng tông lạnh/triết lý Machiavellian dù thể loại là gì.

QUY TẮC BẮT BUỘC:
- Chia thành đoạn ngắn 3–5 câu, mỗi đoạn một ý chính duy nhất
- Ngôn ngữ tự nhiên như người đang kể, nhịp điệu thăng trầm, có trọng lượng
- Cấu trúc: Lời chào Bibi (mở đầu) → Hook nội dung truyện → Phát triển → Cao trào → Kết luận gợi suy ngẫm nhẹ nhàng → Lời chào tạm biệt Bibi (kết thúc)
- KHÔNG gạch đầu dòng, KHÔNG chú thích kỹ thuật, KHÔNG hiệu ứng âm thanh
- KHÔNG dùng: "và rồi", "thế là", "thực ra thì", "có thể nói"
- Câu ngắn, rõ ràng, dễ đọc TTS mượt
- Viết lại nâng cao chất lượng, đảm bảo không vi phạm bản quyền YouTube
- Đầu ra: văn bản thuần, hạn chế xuống dòng thừa"""

SYSTEM_REVISE = """Bạn là biên kịch chuyên nghiệp cho kênh "Tiệm Truyện Nhỏ Nhỏ".
Nhiệm vụ: chỉnh sửa kịch bản TTS dựa trên góp ý của chủ kênh.

QUY TẮC:
- Giữ nguyên phần không bị góp ý, chỉ chỉnh phần được yêu cầu
- Nếu góp ý chung chung (hay hơn, mạnh hơn...) → nâng toàn bộ chất lượng
- Nếu góp ý cụ thể (đoạn X, câu Y) → chỉ sửa đúng chỗ đó
- Giữ đúng format TTS: đoạn 3-5 câu, văn bản thuần, không ký hiệu thừa
- Giữ tông giọng gốc (ấm áp/triết lý) trừ khi được yêu cầu đổi
- Giữ nguyên lời chào mở đầu và lời tạm biệt kết thúc của Bibi trừ khi được yêu cầu đổi
- Trả về kịch bản ĐÃ CHỈNH SỬA HOÀN CHỈNH, không giải thích"""

SYSTEM_SEO = """Bạn là chuyên gia SEO YouTube cho kênh kể chuyện tiếng Việt "Tiệm Truyện Nhỏ Nhỏ".
Tạo gói SEO tối ưu, ngắn gọn, đúng format, không giải thích thừa.
Chỉ trả về đúng format được yêu cầu, không thêm lời mở đầu hay kết thúc."""

SYSTEM_THUMB = """Bạn là art director chuyên tạo thumbnail YouTube viral cho kênh cổ tích Việt Nam "Tiệm Truyện Nhỏ Nhỏ".
Mascot của kênh là BiBi — chú đom đóm nhỏ chibi 3D, phát sáng vàng/xanh, luôn xuất hiện trong mọi thumbnail.
Chỉ trả về đúng format được yêu cầu, không thêm lời mở đầu hay kết thúc."""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def call(system: str, prompt: str, model: str = "claude-haiku-4-5", tokens: int = 800) -> str:
    r = client.messages.create(
        model=model, max_tokens=tokens, system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    return r.content[0].text.strip()

def call_with_history(system: str, messages: list, model: str = "claude-sonnet-4-6", tokens: int = 2000) -> str:
    """Gọi API với lịch sử hội thoại — dùng cho vòng lặp chỉnh sửa kịch bản"""
    r = client.messages.create(
        model=model, max_tokens=tokens, system=system,
        messages=messages
    )
    return r.content[0].text.strip()

async def fetch_url_content(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            text = re.sub(r'<style[^>]*>.*?</style>', '', r.text, flags=re.DOTALL)
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:25000]
    except Exception as e:
        return f"ERROR: {e}"

def extract_url(text: str):
    urls = re.findall(r'https?://[^\s]+', text)
    return urls[0] if urls else None

def split_message(text: str, limit: int = 4000):
    parts = []
    while len(text) > limit:
        cut = text.rfind('\n', 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts

async def send_long_text(target, header: str, text: str, reply_markup=None):
    """
    Gửi văn bản dài an toàn: KHÔNG dùng parse_mode để tránh lỗi ký tự đặc biệt.
    Tự động cắt nếu vượt 4000 ký tự.
    """
    full = f"{header}\n\n{text}" if header else text
    parts = split_message(full, limit=4000)
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        await target.reply_text(part, reply_markup=markup)

def clean_script_text(text: str) -> str:
    """
    Làm sạch kịch bản trước khi ghi file:
    - Bỏ các ký tự markdown: #, *, _, ---, ===
    - Bỏ dòng trống thừa (giữ tối đa 1 dòng trống giữa các đoạn)
    - Giữ nguyên bản văn xuôi thuần
    """
    lines = text.splitlines()
    cleaned = []
    prev_blank = False
    for line in lines:
        # Bỏ các heading markdown (# ## ###)
        line = re.sub(r'^#{1,6}\s*', '', line)
        # Bỏ bold/italic markdown (* ** _ __)
        line = re.sub(r'\*{1,3}|_{1,2}', '', line)
        # Bỏ dòng chỉ có dấu --- hoặc === hoặc ___
        if re.match(r'^[-=_]{2,}\s*$', line.strip()):
            continue
        # Kiểm soát dòng trống: tối đa 1 dòng trống liên tiếp
        if line.strip() == "":
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False
    return "\n".join(cleaned).strip()

async def send_script_as_file(target, script: str, version: int, story: dict, caption: str = ""):
    """
    Gửi kịch bản dưới dạng file .txt đính kèm trong Telegram.
    File chỉ chứa văn bản thuần — không header, không ký tự đặc biệt.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"tiem_truyen_v{version}_{timestamp}.txt"

    # Chỉ ghi nội dung kịch bản thuần, không có header metadata
    full_content = clean_script_text(script) + "\n"

    file_bytes = BytesIO(full_content.encode("utf-8"))
    file_bytes.name = filename

    caption_text = caption or f"🎬 Kịch bản TTS v{version} — sẵn sàng đưa vào tool đọc!"
    await target.reply_document(
        document=file_bytes,
        filename=filename,
        caption=caption_text
    )

def _analyze_sync(raw: str) -> dict:
    result = call(
        SYSTEM_ANALYST,
        f"Phân tích nội dung sau:\n\n{raw[:4000]}\n\n"
        "Trả về ĐÚNG format:\n"
        "TÓM TẮT: [3-5 câu]\n"
        "THỂ LOẠI: [cổ tích / dân gian / triết lý / tâm lý]\n"
        "TÔNG GIỌNG: [ấm áp / lạnh-triết lý / huyền bí]\n"
        "ĐỘ DÀI GỢI Ý: [5-7 phút / 8-12 phút / 12-18 phút]",
        model="claude-haiku-4-5", tokens=300
    )
    lines = {}
    for l in result.splitlines():
        if ":" in l:
            k, v = l.split(":", 1)
            lines[k.strip()] = v.strip()
    return {
        "summary":  lines.get("TÓM TẮT", "Câu chuyện thú vị"),
        "genre":    lines.get("THỂ LOẠI", "cổ tích"),
        "tone":     lines.get("TÔNG GIỌNG", "ấm áp"),
        "duration": lines.get("ĐỘ DÀI GỢI Ý", "8-12 phút"),
        "raw":      raw[:25000]
    }

# ─── Sinh kịch bản ────────────────────────────────────────────────────────────

CHUNK_SIZE = 4000

def _chunk_raw(raw: str) -> list[str]:
    if len(raw) <= CHUNK_SIZE:
        return [raw]
    chunks = []
    while raw:
        if len(raw) <= CHUNK_SIZE:
            chunks.append(raw)
            break
        cut = raw.rfind('\n', CHUNK_SIZE // 2, CHUNK_SIZE)
        if cut == -1:
            cut = raw.rfind('. ', CHUNK_SIZE // 2, CHUNK_SIZE)
        if cut == -1:
            cut = CHUNK_SIZE
        chunks.append(raw[:cut].strip())
        raw = raw[cut:].strip()
    return chunks

def gen_script(story: dict) -> str:
    tone_note = (
        "Tông giọng: ấm áp, dịu dàng, ru ngủ — Bibi kể chuyện cho các bé trước giờ đi ngủ, "
        "ngay cả những đoạn cao trào cũng giữ nhịp nhẹ nhàng, không gây sợ hãi quá mức."
    )
    base_instruction = (
        f"THỂ LOẠI: {story['genre']}\n{tone_note}\n"
        "Quy tắc: đoạn 3-5 câu, văn bản thuần TTS, không gạch đầu dòng, không chú thích, không hiệu ứng.\n"
        "BẮT BUỘC: mở đầu bằng lời chào của Bibi (theo mẫu cố định trong system prompt, điền tên truyện phù hợp), "
        "kết thúc bằng lời tạm biệt của Bibi (theo mẫu cố định, điền tên nhân vật chính của truyện), "
        "và xen 3-5 lời bình ngắn của Bibi trong thân truyện ở các điểm chuyển cảnh."
    )

    chunks = _chunk_raw(story["raw"])
    total = len(chunks)

    if total == 1:
        return call(
            SYSTEM_SCRIPT,
            f"Viết kịch bản TTS HOÀN CHỈNH cho câu chuyện sau.\n\n"
            f"{base_instruction}\n"
            f"ĐỘ DÀI MỤC TIÊU: {story['duration']}\n\n"
            f"NỘI DUNG GỐC:\n{chunks[0]}\n\n"
            "Cấu trúc bắt buộc: Lời chào Bibi → Hook mạnh → Phát triển đầy đủ → Cao trào → Kết luận gợi suy ngẫm → Lời tạm biệt Bibi.\n"
            "Viết ĐỦ toàn bộ câu chuyện, không bỏ sót chi tiết nào.",
            model="claude-sonnet-4-6", tokens=8000
        )

    parts_text = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            prompt = (
                f"Bạn đang viết kịch bản TTS cho một câu chuyện dài ({total} phần).\n"
                f"{base_instruction}\n\n"
                f"ĐÂY LÀ PHẦN 1/{total} — PHẦN MỞ ĐẦU.\n"
                "Bắt buộc mở đầu bằng lời chào của Bibi theo mẫu cố định (điền tên truyện).\n"
                "Yêu cầu: sau lời chào Bibi, viết Hook cực mạnh (15 giây đầu gây tò mò) rồi khai triển nội dung phần này.\n"
                "Kết thúc phần bằng câu dẫn dắt sang phần tiếp theo (không kết thúc câu chuyện, KHÔNG dùng lời tạm biệt của Bibi ở phần này).\n\n"
                f"NỘI DUNG PHẦN NÀY:\n{chunk}"
            )
        elif i == total - 1:
            prompt = (
                f"Bạn đang viết kịch bản TTS cho một câu chuyện dài ({total} phần).\n"
                f"{base_instruction}\n\n"
                f"ĐÂY LÀ PHẦN {i+1}/{total} — PHẦN KẾT.\n"
                "Yêu cầu: khai triển đầy đủ nội dung phần này, dẫn đến Cao trào rõ ràng,\n"
                "kết thúc bằng Kết luận triết lý gợi suy ngẫm nhẹ nhàng.\n"
                "Bắt buộc kết thúc bằng lời tạm biệt của Bibi theo mẫu cố định (điền tên nhân vật chính).\n\n"
                f"NỘI DUNG PHẦN NÀY:\n{chunk}"
            )
        else:
            prompt = (
                f"Bạn đang viết kịch bản TTS cho một câu chuyện dài ({total} phần).\n"
                f"{base_instruction}\n\n"
                f"ĐÂY LÀ PHẦN {i+1}/{total} — PHẦN THÂN.\n"
                "Yêu cầu: khai triển đầy đủ nội dung phần này, giữ mạch truyện liên tục.\n"
                "Không mở đầu lại từ đầu, không kết thúc câu chuyện, KHÔNG dùng lời chào/tạm biệt cố định của Bibi ở phần này "
                "(chỉ xen 1-2 lời bình ngắn của Bibi nếu phù hợp).\n\n"
                f"NỘI DUNG PHẦN NÀY:\n{chunk}"
            )
        part = call(SYSTEM_SCRIPT, prompt, model="claude-sonnet-4-6", tokens=4000)
        parts_text.append(part)

    return "\n\n".join(parts_text)

def revise_script(history: list, feedback: str) -> str:
    messages = history + [{"role": "user", "content": (
        f"Góp ý của tôi: {feedback}\n\n"
        "Hãy chỉnh sửa kịch bản theo góp ý trên và trả về TOÀN BỘ kịch bản hoàn chỉnh đã được cải thiện. "
        "Không được cắt ngắn hay bỏ sót đoạn nào."
    )}]
    return call_with_history(SYSTEM_REVISE, messages, model="claude-sonnet-4-6", tokens=8000)

# ─── gen_seo — prompt đầy đủ, 5 tiêu đề viral + phân tích + tags ──────────────

def gen_seo(story: dict) -> str:
    """
    Tạo SEO package đầy đủ:
    - 5 tiêu đề YouTube viral theo công thức storytelling
    - Phân tích + gợi ý tiêu đề tốt nhất
    - Tags dựa trên kịch bản đã chốt
    """
    # Lấy kịch bản nếu có (lưu ở story["script"]), fallback về summary
    script_context = story.get("script", story.get("summary", ""))

    return call(
        SYSTEM_SEO,
        f"""Tạo SEO package cho video YouTube kênh "Tiệm Truyện Nhỏ Nhỏ".

THỂ LOẠI: {story['genre']}
TÔNG GIỌNG: {story['tone']}
TÓM TẮT CÂU CHUYỆN: {story['summary']}
NỘI DUNG KỊCH BẢN (tham khảo để lấy từ khóa):
{script_context[:1500]}

=== YÊU CẦU 5 TIÊU ĐỀ YOUTUBE VIRAL ===

Mỗi tiêu đề PHẢI:
- Dưới 100 ký tự
- Phong cách storytelling, đánh vào cảm xúc tò mò
- Chứa ít nhất 1 con số
- Từ khóa chính nằm trong 65 ký tự đầu
- Từ "ngòi nổ" viết HOA nhưng chiếm dưới 30% tiêu đề
- KHÔNG viết hoa toàn bộ tiêu đề

Xoay vòng cấu trúc:
- Tiêu đề 1: Vấn đề + Đối tượng + Ngòi nổ
- Tiêu đề 2: Đối tượng + Vấn đề + Ngòi nổ
- Tiêu đề 3: Ngòi nổ + Vấn đề
- Tiêu đề 4-5: công thức tự chọn tốt nhất

=== FORMAT TRẢ VỀ (giữ đúng, không thêm gì khác) ===

TIÊU ĐỀ 1: [tiêu đề]
TIÊU ĐỀ 2: [tiêu đề]
TIÊU ĐỀ 3: [tiêu đề]
TIÊU ĐỀ 4: [tiêu đề]
TIÊU ĐỀ 5: [tiêu đề]

PHÂN TÍCH & GỢI Ý CHỌN:
Nên chọn tiêu đề số [X] vì [lý do SEO + thumbnail + cảm xúc, 3-5 câu]

TAGS (20 tags, phân cách bằng dấu phẩy, không đánh số):
[tag1, tag2, tag3, ...]""",
        model="claude-sonnet-4-6",
        tokens=1200
    )

# ─── gen_thumbnail — prompt đầy đủ, có BiBi + bầu trời đêm + chibi 3D ─────────

def gen_thumbnail(story: dict, chosen_title: str = "") -> str:
    """
    Tạo prompt thumbnail AI với:
    - BiBi (mascot đom đóm chibi 3D) xuyên suốt
    - Bầu trời đêm + ánh trăng
    - Phong cách cinematic, god rays, emotional
    - Dựa trên tiêu đề đã chọn từ SEO (nếu có)
    """
    title_context = (
        f"TIÊU ĐỀ ĐÃ CHỌN: {chosen_title}" if chosen_title
        else f"TÓM TẮT CÂU CHUYỆN: {story['summary']}"
    )
    script_context = story.get("script", story.get("summary", ""))

    return call(
        SYSTEM_THUMB,
        f"""Tạo prompt thumbnail YouTube cho video kênh "Tiệm Truyện Nhỏ Nhỏ".

THỂ LOẠI: {story['genre']} | TÔNG: {story['tone']}
{title_context}
NỘI DUNG KỊCH BẢN (tham khảo cảnh/nhân vật chính):
{script_context[:1000]}

=== YÊU CẦU BẮT BUỘC ===

MASCOT BiBi (LUÔN CÓ MẶT — nhân vật xuyên suốt thương hiệu kênh):
- BiBi là chú đom đóm nhỏ dễ thương, phong cách chibi 3D render
- Cơ thể trong suốt phát sáng lung linh màu vàng/xanh lá nhẹ
- Đôi cánh nhỏ mỏng manh, mắt tròn to biểu cảm
- Biểu cảm phù hợp nội dung: ngạc nhiên/xúc động/tò mò/buồn bã
- Vị trí: góc dưới trái hoặc bay gần nhân vật chính — nổi bật nhưng không che khuất
- Xung quanh BiBi có các đốm sáng nhỏ như đom đóm lập lòe

BỐI CẢNH BẮT BUỘC (bầu trời đêm huyền ảo):
- Bầu trời đêm sâu thẳm màu xanh tím than/indigo
- Ánh trăng rằm tròn sáng rõ, tạo god rays chiếu xuống
- Có sao lấp lánh, mây mỏng huyền ảo hoặc bokeh ánh sáng
- Không khí mờ ảo như khói mỏng, tăng chiều sâu

KỸ THUẬT HÌNH ẢNH:
- Tỷ lệ: 16:9, ultra-high resolution, 4K quality
- Phong cách: cinematic, dramatic god rays, high contrast, emotionally charged
- Ánh sáng: chiaroscuro mạnh — vùng sáng và tối tương phản rõ
- Không có chữ/text trong ảnh
- Nhân vật chính chibi 3D render, chiếm 60-70% frame, rule of thirds
- Màu chủ đạo: tím than, xanh đêm, vàng ánh trăng, điểm xuyết đỏ/cam nếu cần cảm xúc mạnh

=== FORMAT TRẢ VỀ (giữ đúng, không thêm gì khác) ===

CONCEPT: [1-2 câu mô tả ý tưởng hình ảnh tổng thể]

PROMPT_EN:
[prompt tiếng Anh chi tiết 80-120 từ cho Midjourney/Flux/DALL-E — mô tả scene, BiBi, bầu trời đêm, nhân vật chính, lighting, mood, style]

NEGATIVE_PROMPT:
[những gì cần loại bỏ: text, watermark, blurry, ugly proportions, daytime...]

TOOL_GỢI Ý: [Midjourney v6 / Flux Pro / DALL-E 3] — lý do ngắn gọn

TEXT_OVERLAY: [2-5 chữ ngắn in đậm đặt trên ảnh sau khi gen]
FONT_STYLE: [bold impact / serif dramatic / handwritten brush]
COLOR_PALETTE: [3 màu hex chủ đạo]""",
        model="claude-sonnet-4-6",
        tokens=1000
    )


# ─── Module: Ảnh minh hoạ ────────────────────────────────────────────────────

SYSTEM_ILLUS = """Bạn là art director chuyên tạo prompt ảnh minh hoạ cho video kể chuyện YouTube.
Phong cách nhất quán: chibi 3D render, dễ thương, cinematic lighting, màu sắc ấm áp huyền bí.
Chỉ trả về đúng format được yêu cầu, không thêm lời mở đầu hay kết thúc."""

def gen_illustration(story: dict) -> str:
    """
    Phân tích kịch bản xác định số ảnh phù hợp rồi sinh prompt cho từng ảnh.
    Mỗi ảnh dùng được cho 10 giây đến 1 phút trên video.
    Số lượng ảnh bằng số tình tiết đáng chú ý trong kịch bản.
    """
    script = story.get("script", story.get("summary", ""))
    script_context = script[:12000]

    return call(
        SYSTEM_ILLUS,
        f"""Tạo bộ prompt ảnh minh hoạ cho video YouTube kênh "Tiệm Truyện Nhỏ Nhỏ".

THỂ LOẠI: {story['genre']} | TÔNG: {story['tone']}
TÓM TẮT: {story['summary']}

KỊCH BẢN ĐÃ CHỐT:
{script_context}

NHIỆM VỤ:
Bước 1: Phân tích kịch bản, xác định các TÌNH TIẾT ĐÁNG CHÚ Ý bao gồm cảnh có cảm xúc mạnh, bước ngoặt, hành động quan trọng, cảnh mở đầu, cảnh kết. Mỗi tình tiết tương ứng 1 ảnh dùng được cho 10 giây đến 1 phút trên video. Số lượng ảnh tối thiểu 6, tối đa 20.
Bước 2: Với mỗi tình tiết, viết 1 prompt ảnh minh hoạ theo format bên dưới.

YÊU CẦU PHONG CÁCH áp dụng cho TẤT CẢ ảnh để đảm bảo nhất quán:

NHÂN VẬT:
Phong cách chibi 3D render, tỷ lệ đầu to thân nhỏ, dễ thương, biểu cảm rõ ràng.
Màu sắc nhân vật ấm, đường nét mềm mại, bóng đổ mềm.
Quần áo và trang phục phù hợp thời đại và bối cảnh câu chuyện.

BỐI CẢNH VÀ ÁNH SÁNG:
Cinematic lighting với ánh sáng có hướng rõ, tương phản nhẹ, không quá tối.
Màu nền hài hoà theo tông đất, nâu gỗ, xanh rừng, vàng ánh nến.
Có chiều sâu không gian với background blur nhẹ.
Không có chữ hoặc text trong ảnh.

KỸ THUẬT:
Tỷ lệ 16:9, ultra-detailed, 4K quality, soft cel-shading 3D style.
Nhân vật chiếm 50-70% frame theo rule of thirds.

FORMAT TRẢ VỀ cho mỗi ảnh:

ANH [số] - [tên tình tiết ngắn gọn tiếng Việt]
THOI LUONG: [10s / 20s / 30s / 45s / 1 phut]
PROMPT_EN: [prompt tiếng Anh 50-80 từ mô tả scene, nhân vật, cảm xúc, ánh sáng, bối cảnh]
NEGATIVE: blurry, text, watermark, realistic photo, adult proportions, dark horror

Phân cách mỗi block ảnh bằng 1 dòng trống. Sau tất cả ảnh thêm:
TONG SO ANH: [số]
TONG THOI LUONG: [tổng thời lượng ước tính]
TOOL GỢI Ý: Midjourney v6 hoặc Flux Pro, dùng ảnh đầu tiên làm style reference cho các ảnh sau để nhân vật nhất quán.""",
        model="claude-sonnet-4-6",
        tokens=6500
    )

# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kịch bản TTS", callback_data="script"),
         InlineKeyboardButton("🔍 SEO", callback_data="seo")],
        [InlineKeyboardButton("🖼 Prompt Thumbnail", callback_data="thumbnail"),
         InlineKeyboardButton("🎨 Ảnh minh hoạ", callback_data="illustration")],
        [InlineKeyboardButton("✨ Tất cả", callback_data="all")],
    ])

def script_action_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Góp ý chỉnh sửa kịch bản", callback_data="revise_prompt")],
        [InlineKeyboardButton("🔍 Tạo SEO", callback_data="seo"),
         InlineKeyboardButton("🖼 Tạo Thumbnail", callback_data="thumbnail")],
        [InlineKeyboardButton("🎨 Ảnh minh hoạ", callback_data="illustration")],
        [InlineKeyboardButton("📖 Truyện mới", callback_data="new_story")],
    ])

def after_revise_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Góp ý tiếp theo", callback_data="revise_prompt")],
        [InlineKeyboardButton("✅ Kịch bản đã ổn", callback_data="script_done")],
        [InlineKeyboardButton("🔍 Tạo SEO", callback_data="seo"),
         InlineKeyboardButton("🖼 Tạo Thumbnail", callback_data="thumbnail")],
        [InlineKeyboardButton("🎨 Ảnh minh hoạ", callback_data="illustration")],
    ])

def other_output_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kịch bản TTS", callback_data="script"),
         InlineKeyboardButton("🔍 SEO", callback_data="seo")],
        [InlineKeyboardButton("🖼 Thumbnail", callback_data="thumbnail"),
         InlineKeyboardButton("🎨 Ảnh minh hoạ", callback_data="illustration")],
        [InlineKeyboardButton("📖 Truyện mới", callback_data="new_story")],
    ])

# ─── Handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "📖 Tiệm Truyện Agent đã sẵn sàng!\n\n"
        "Gửi cho mình:\n"
        "• Nội dung câu chuyện (dán text trực tiếp)\n"
        "• Hoặc link bài viết có câu chuyện\n\n"
        "Mình sẽ phân tích và cho bạn chọn output muốn tạo 👇"
    )

async def handle_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ── Chế độ đang chờ góp ý kịch bản ──────────────────────────────────────
    if ctx.user_data.get("waiting_for_feedback"):
        ctx.user_data["waiting_for_feedback"] = False
        await process_revision(update, ctx, text)
        return

    # ── Nhập truyện mới ───────────────────────────────────────────────────────
    url = extract_url(text)
    if not url and len(text) < 50:
        await update.message.reply_text(
            "⚠️ Nội dung quá ngắn!\n\n"
            "Hãy gửi:\n• Đoạn văn câu chuyện (tối thiểu 50 ký tự)\n• Hoặc link bài viết"
        )
        return

    msg = await update.message.reply_text("⏳ Đang đọc & phân tích nội dung...")
    raw = text

    if url:
        await msg.edit_text("🔗 Đang tải nội dung từ link...")
        content = await fetch_url_content(url)
        if content.startswith("ERROR"):
            await msg.edit_text(f"❌ Không tải được link:\n{content}\n\nBạn thử dán text trực tiếp nhé.")
            return
        raw = content

    await msg.edit_text("🔍 Đang phân tích câu chuyện...")
    loop = asyncio.get_event_loop()
    story = await loop.run_in_executor(None, lambda: _analyze_sync(raw))

    ctx.user_data.clear()
    ctx.user_data["story"] = story

    summary_text = (
        f"✅ Đã phân tích xong!\n\n"
        f"📌 Tóm tắt: {story['summary']}\n"
        f"🎭 Thể loại: {story['genre']}\n"
        f"🎙 Tông giọng: {story['tone']}\n"
        f"⏱ Độ dài gợi ý: {story['duration']}\n\n"
        f"Bạn muốn tạo output nào?"
    )
    await msg.edit_text(summary_text, reply_markup=main_menu())

async def process_revision(update: Update, ctx: ContextTypes.DEFAULT_TYPE, feedback: str):
    story = ctx.user_data.get("story")
    history = ctx.user_data.get("script_history", [])

    if not story or not history:
        await update.message.reply_text("⚠️ Không tìm thấy kịch bản. Hãy tạo kịch bản trước nhé!")
        return

    revision_count = ctx.user_data.get("revision_count", 0) + 1
    ctx.user_data["revision_count"] = revision_count

    msg = await update.message.reply_text(f"✏️ Đang chỉnh sửa lần {revision_count}... (~20 giây)")

    loop = asyncio.get_event_loop()
    revised = await loop.run_in_executor(None, lambda: revise_script(history, feedback))

    ctx.user_data["script_history"] = history + [
        {"role": "user", "content": f"Góp ý: {feedback}\nHãy chỉnh sửa kịch bản theo góp ý và trả về hoàn chỉnh."},
        {"role": "assistant", "content": revised}
    ]
    # cập nhật script mới nhất vào story để SEO/thumbnail dùng
    ctx.user_data["story"]["script"] = revised

    await msg.delete()

    version = revision_count + 1
    caption = f"🎬 Kịch bản v{version} — đã chỉnh theo: \"{feedback[:60]}{'...' if len(feedback)>60 else ''}\""
    await send_script_as_file(update.message, revised, version=version, story=story, caption=caption)
    await update.message.reply_text(
        f"✅ Đã chỉnh sửa xong lần {revision_count}!\nBạn muốn làm gì tiếp theo?",
        reply_markup=after_revise_menu()
    )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    story = ctx.user_data.get("story")
    loop = asyncio.get_event_loop()

    # ── Truyện mới ────────────────────────────────────────────────────────────
    if action == "new_story":
        ctx.user_data.clear()
        await query.edit_message_text(
            "📖 Sẵn sàng cho câu chuyện mới!\n\nGửi nội dung hoặc link bài viết nhé."
        )
        return

    if not story:
        await query.edit_message_text("⚠️ Phiên làm việc đã hết. Hãy gửi lại câu chuyện nhé!")
        return

    # ── Kịch bản ──────────────────────────────────────────────────────────────
    if action == "script":
        raw_len = len(story.get("raw", ""))
        num_chunks = max(1, (raw_len + CHUNK_SIZE - 1) // CHUNK_SIZE)
        wait_secs = num_chunks * 30
        wait_msg = (
            "⏳ Đang viết kịch bản TTS...\n\n"
            f"📄 Độ dài truyện: {raw_len:,} ký tự\n"
            f"🔀 Chia thành {num_chunks} phần, viết tuần tự\n"
            f"⏱ Ước tính: ~{wait_secs} giây\n\n"
            "Vui lòng chờ, đang xử lý từng phần..."
        )
        await query.edit_message_text(wait_msg)
        result = await loop.run_in_executor(None, lambda: gen_script(story))

        # Lưu kịch bản vào story để SEO/thumbnail có thể dùng
        ctx.user_data["story"]["script"] = result

        ctx.user_data["script_history"] = [
            {"role": "user", "content": (
                f"Viết kịch bản TTS cho câu chuyện:\nTHỂ LOẠI: {story['genre']}\n"
                f"TÔNG: {story['tone']}\nNỘI DUNG: {story['raw']}"
            )},
            {"role": "assistant", "content": result}
        ]
        ctx.user_data["revision_count"] = 0

        await send_script_as_file(query.message, result, version=1, story=story)
        await query.message.reply_text(
            "✅ Kịch bản v1 đã xuất ra file!\nBạn muốn chỉnh sửa hay tạo output khác?",
            reply_markup=script_action_menu()
        )

    # ── Góp ý ─────────────────────────────────────────────────────────────────
    elif action == "revise_prompt":
        if not ctx.user_data.get("script_history"):
            await query.edit_message_text("⚠️ Chưa có kịch bản! Hãy tạo kịch bản trước.")
            return
        ctx.user_data["waiting_for_feedback"] = True
        revision_count = ctx.user_data.get("revision_count", 0)
        await query.edit_message_text(
            f"✏️ Góp ý chỉnh sửa kịch bản (lần {revision_count + 1})\n\n"
            "Nhắn góp ý của bạn vào đây. Ví dụ:\n"
            "• \"Hook đầu chưa đủ mạnh, cần gây tò mò hơn\"\n"
            "• \"Đoạn giữa hơi dài, rút ngắn lại\"\n"
            "• \"Kết luận cần sâu sắc và triết lý hơn\"\n"
            "• \"Toàn bộ cần mạnh mẽ và lạnh hơn\"\n\n"
            "👇 Nhắn góp ý ngay bên dưới:"
        )

    # ── Kịch bản đã ổn ────────────────────────────────────────────────────────
    elif action == "script_done":
        revision_count = ctx.user_data.get("revision_count", 0)
        await query.edit_message_text(
            f"🎉 Hoàn tất kịch bản sau {revision_count} lần chỉnh sửa!\n\n"
            "Bạn muốn tạo thêm gì?",
            reply_markup=other_output_menu()
        )

    # ── SEO — không dùng parse_mode, gửi plain text ──────────────────────────
    elif action == "seo":
        await query.edit_message_text("⏳ Đang tối ưu SEO... (~20 giây)")
        result = await loop.run_in_executor(None, lambda: gen_seo(story))

        # Lưu tiêu đề được gợi ý để thumbnail dùng (parse từ kết quả)
        ctx.user_data["seo_result"] = result

        # Gửi plain text — KHÔNG dùng parse_mode để tránh crash ký tự đặc biệt
        await send_long_text(
            query.message,
            "🔍 SEO PACKAGE",
            result,
            reply_markup=other_output_menu()
        )

    # ── Thumbnail — không dùng parse_mode, prompt đầy đủ ─────────────────────
    elif action == "thumbnail":
        await query.edit_message_text("⏳ Đang tạo prompt thumbnail... (~20 giây)")

        # Lấy tiêu đề đã chọn từ SEO nếu có
        seo_result = ctx.user_data.get("seo_result", "")
        chosen_title = ""
        if seo_result:
            # Tìm dòng "PHÂN TÍCH & GỢI Ý CHỌN" để lấy tiêu đề được gợi ý
            match = re.search(r'TIÊU ĐỀ (\d):', seo_result)
            if "Nên chọn tiêu đề số" in seo_result:
                num_match = re.search(r'Nên chọn tiêu đề số\s*(\d)', seo_result)
                if num_match:
                    num = num_match.group(1)
                    title_match = re.search(rf'TIÊU ĐỀ {num}:\s*(.+)', seo_result)
                    if title_match:
                        chosen_title = title_match.group(1).strip()

        result = await loop.run_in_executor(
            None, lambda: gen_thumbnail(story, chosen_title)
        )

        # Gửi plain text — KHÔNG dùng parse_mode
        await send_long_text(
            query.message,
            "🖼 THUMBNAIL PROMPT",
            result,
            reply_markup=other_output_menu()
        )

    # ── Ảnh minh hoạ ──────────────────────────────────────────────────────────
    elif action == "illustration":
        if not story.get("script"):
            await query.edit_message_text(
                "⚠️ Cần có kịch bản trước!\n\nHãy tạo kịch bản rồi quay lại tạo ảnh minh hoạ."
            )
            return
        script_len = len(story.get("script", ""))
        est_images = max(6, min(20, script_len // 400))
        await query.edit_message_text(
            f"⏳ Đang phân tích kịch bản và tạo prompt ảnh minh hoạ...\n\n"
            f"📄 Kịch bản: {script_len:,} ký tự\n"
            f"🎨 Ước tính: {est_images} ảnh\n"
            f"⏱ Khoảng ~30 giây..."
        )
        result = await loop.run_in_executor(None, lambda: gen_illustration(story))
        await send_long_text(
            query.message,
            "🎨 PROMPT ẢNH MINH HOẠ",
            result,
            reply_markup=other_output_menu()
        )

    # ── Tất cả ────────────────────────────────────────────────────────────────
    elif action == "all":
        raw_len = len(story.get("raw", ""))
        num_chunks = max(1, (raw_len + CHUNK_SIZE - 1) // CHUNK_SIZE)
        wait_secs = num_chunks * 30 + 30
        await query.edit_message_text(
            "⏳ Đang tạo toàn bộ gói sản xuất...\n\n"
            f"📄 Truyện: {raw_len:,} ký tự — {num_chunks} phần kịch bản\n"
            f"⏱ Ước tính: ~{wait_secs} giây\n"
            "Bao gồm: Kịch bản + SEO + Thumbnail + Ảnh minh hoạ\n\nVui lòng chờ..."
        )

        # Chạy song song: script + seo + thumbnail
        script_result = await loop.run_in_executor(None, lambda: gen_script(story))

        # Lưu script vào story trước khi gen SEO/thumbnail (dùng script làm context)
        ctx.user_data["story"]["script"] = script_result

        seo_result, thumb_result, illus_result = await asyncio.gather(
            loop.run_in_executor(None, lambda: gen_seo(ctx.user_data["story"])),
            loop.run_in_executor(None, lambda: gen_thumbnail(ctx.user_data["story"])),
            loop.run_in_executor(None, lambda: gen_illustration(ctx.user_data["story"])),
        )

        ctx.user_data["script_history"] = [
            {"role": "user", "content": f"Viết kịch bản TTS cho câu chuyện:\nTHỂ LOẠI: {story['genre']}\nTÔNG: {story['tone']}\nNỘI DUNG: {story['raw']}"},
            {"role": "assistant", "content": script_result}
        ]
        ctx.user_data["revision_count"] = 0
        ctx.user_data["seo_result"] = seo_result

        await send_script_as_file(query.message, script_result, version=1, story=story)

        await send_long_text(query.message, "🔍 SEO PACKAGE", seo_result)
        await send_long_text(query.message, "🖼 THUMBNAIL PROMPT", thumb_result)
        await send_long_text(query.message, "🎨 PROMPT ẢNH MINH HOẠ", illus_result)

        await query.message.reply_text(
            "✅ Gói sản xuất hoàn tất!\nBạn muốn chỉnh sửa kịch bản không?",
            reply_markup=script_action_menu()
        )

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))
    print("✅ Tiệm Truyện Bot đang chạy...")
    app.run_polling()
