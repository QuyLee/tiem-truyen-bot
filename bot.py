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

SYSTEM_SCRIPT = """Bạn là biên kịch chuyên nghiệp cho kênh "Tiệm Truyện Nhỏ Nhỏ".
Nhiệm vụ: viết kịch bản TTS hoàn chỉnh từ nội dung câu chuyện.

QUY TẮC BẮT BUỘC:
- Chia thành đoạn ngắn 3–5 câu, mỗi đoạn một ý chính duy nhất
- Ngôn ngữ tự nhiên như người đang kể, nhịp điệu thăng trầm, có trọng lượng
- Cấu trúc viral: Hook mạnh (câu hỏi/sự kiện gây tò mò) → Phát triển → Cao trào → Kết luận gợi suy ngẫm
- KHÔNG gạch đầu dòng, KHÔNG chú thích kỹ thuật, KHÔNG hiệu ứng âm thanh
- KHÔNG dùng: "và rồi", "thế là", "thực ra thì", "có thể nói"
- Câu ngắn, rõ ràng, dễ đọc TTS mượt
- Tông giọng tuỳ thể loại: cổ tích → ấm, huyền bí / triết lý → lạnh, kiểm soát, Machiavellian
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
- Trả về kịch bản ĐÃ CHỈNH SỬA HOÀN CHỈNH, không giải thích"""

SYSTEM_SEO = """Bạn là chuyên gia SEO YouTube cho kênh kể chuyện tiếng Việt.
Tạo gói SEO tối ưu, ngắn gọn, đúng format, không giải thích thừa."""

SYSTEM_THUMB = """Bạn là art director chuyên tạo thumbnail YouTube viral cho kênh cổ tích Việt Nam.
Tạo prompt hình ảnh AI chi tiết, đúng format, không giải thích thừa."""

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
            return text[:6000]
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

def escape_md(text: str) -> str:
    for ch in r'_*[]()~`>#+-=|{}.!':
        text = text.replace(ch, f'\\{ch}')
    return text

async def send_script_as_file(target, script: str, version: int, story: dict, caption: str = ""):
    """
    Gửi kịch bản dưới dạng file .txt đính kèm trong Telegram.
    target: update.message hoặc query.message
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    # Tên file: tiem_truyen_v1_20250613_1430.txt
    filename = f"tiem_truyen_v{version}_{timestamp}.txt"

    # Nội dung file — thuần text, sẵn sàng đưa vào TTS tool
    header = (
        f"TIỆM TRUYỆN NHỎ NHỎ — KỊCH BẢN TTS\n"
        f"{'=' * 50}\n"
        f"Phiên bản  : {version}\n"
        f"Thể loại   : {story.get('genre', '')}\n"
        f"Tông giọng : {story.get('tone', '')}\n"
        f"Độ dài     : {story.get('duration', '')}\n"
        f"Tạo lúc    : {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"{'=' * 50}\n\n"
    )
    full_content = header + script + "\n"

    # Encode UTF-8 → BytesIO (Telegram nhận file dạng bytes)
    file_bytes = BytesIO(full_content.encode("utf-8"))
    file_bytes.name = filename  # Telegram dùng thuộc tính .name để đặt tên file

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
        "raw":      raw[:5000]
    }

# ─── Sinh kịch bản ────────────────────────────────────────────────────────────

def gen_script(story: dict) -> str:
    tone_note = (
        "Tông giọng: lạnh, kiểm soát, Machiavellian — câu ngắn, trọng lượng, triết lý sắc bén."
        if "lạnh" in story["tone"] or "triết" in story["tone"]
        else "Tông giọng: ấm, huyền bí, cuốn hút — như người kể chuyện bên lửa trại."
    )
    return call(
        SYSTEM_SCRIPT,
        f"Viết kịch bản TTS hoàn chỉnh cho câu chuyện sau.\n\n"
        f"THỂ LOẠI: {story['genre']}\n{tone_note}\n"
        f"ĐỘ DÀI MỤC TIÊU: {story['duration']}\n\n"
        f"NỘI DUNG GỐC:\n{story['raw']}\n\n"
        "Cấu trúc: Hook → Phát triển → Cao trào → Kết luận. "
        "Văn bản thuần, không gạch đầu dòng, không chú thích, không hiệu ứng.",
        model="claude-sonnet-4-6", tokens=2000
    )

def revise_script(history: list, feedback: str) -> str:
    """Chỉnh sửa kịch bản dựa trên góp ý, giữ toàn bộ lịch sử hội thoại"""
    messages = history + [{"role": "user", "content": f"Góp ý của tôi: {feedback}\n\nHãy chỉnh sửa kịch bản theo góp ý trên và trả về kịch bản hoàn chỉnh đã được cải thiện."}]
    return call_with_history(SYSTEM_REVISE, messages, model="claude-sonnet-4-6", tokens=2000)

def gen_seo(story: dict) -> str:
    return call(
        SYSTEM_SEO,
        f"Tạo SEO package cho video YouTube.\nTHỂ LOẠI: {story['genre']}\nTÓM TẮT: {story['summary']}\n\n"
        "TITLE_1: [max 60 ký tự, có emoji, gây tò mò]\n"
        "TITLE_2: [biến thể tập trung keyword]\n"
        "TITLE_3: [biến thể cảm xúc]\n---\n"
        "DESCRIPTION:\n[200-250 từ, 3 dòng đầu hook, có timestamps 00:00, keywords tự nhiên]\n---\n"
        "TAGS: [tag1, tag2, ... 22 tags tiếng Việt]\n"
        "HASHTAGS: #tag1 #tag2 ... 10 hashtags",
        model="claude-haiku-4-5", tokens=700
    )

def gen_thumbnail(story: dict) -> str:
    return call(
        SYSTEM_THUMB,
        f"Tạo prompt thumbnail AI viral cho video YouTube.\n"
        f"THỂ LOẠI: {story['genre']} | TÔNG: {story['tone']}\nTÓM TẮT: {story['summary']}\n\n"
        "CONCEPT: [1-2 câu mô tả ý tưởng hình ảnh]\n"
        "PROMPT_EN: [prompt chi tiết cho Midjourney/Flux — style, lighting, composition, mood]\n"
        "PROMPT_VI: [prompt tiếng Việt]\n"
        "TEXT_OVERLAY: [2-5 chữ in đậm]\n"
        "FONT_STYLE: [bold / serif dramatic / handwritten]\n"
        "COLOR_PALETTE: [3 màu hex]",
        model="claude-haiku-4-5", tokens=500
    )

# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kịch bản TTS", callback_data="script"),
         InlineKeyboardButton("🔍 SEO", callback_data="seo")],
        [InlineKeyboardButton("🖼 Prompt Thumbnail", callback_data="thumbnail"),
         InlineKeyboardButton("✨ Tất cả", callback_data="all")],
    ])

def script_action_menu():
    """Menu sau khi xuất kịch bản — có nút góp ý và các nút khác"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Góp ý chỉnh sửa kịch bản", callback_data="revise_prompt")],
        [InlineKeyboardButton("🔍 Tạo SEO", callback_data="seo"),
         InlineKeyboardButton("🖼 Tạo Thumbnail", callback_data="thumbnail")],
        [InlineKeyboardButton("📖 Truyện mới", callback_data="new_story")],
    ])

def after_revise_menu():
    """Menu sau mỗi lần chỉnh sửa"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Góp ý tiếp theo", callback_data="revise_prompt")],
        [InlineKeyboardButton("✅ Kịch bản đã ổn", callback_data="script_done")],
        [InlineKeyboardButton("🔍 Tạo SEO", callback_data="seo"),
         InlineKeyboardButton("🖼 Tạo Thumbnail", callback_data="thumbnail")],
    ])

def other_output_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kịch bản TTS", callback_data="script"),
         InlineKeyboardButton("🔍 SEO", callback_data="seo")],
        [InlineKeyboardButton("🖼 Thumbnail", callback_data="thumbnail"),
         InlineKeyboardButton("📖 Truyện mới", callback_data="new_story")],
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

    # Reset dữ liệu cũ, lưu story mới
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
    """Xử lý góp ý và chỉnh sửa kịch bản"""
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

    # Cập nhật lịch sử hội thoại với góp ý + kịch bản mới
    ctx.user_data["script_history"] = history + [
        {"role": "user", "content": f"Góp ý: {feedback}\nHãy chỉnh sửa kịch bản theo góp ý và trả về hoàn chỉnh."},
        {"role": "assistant", "content": revised}
    ]

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
        await query.edit_message_text("⏳ Đang viết kịch bản TTS... (~30 giây)")
        result = await loop.run_in_executor(None, lambda: gen_script(story))

        # Lưu lịch sử hội thoại để dùng cho vòng lặp chỉnh sửa
        ctx.user_data["script_history"] = [
            {"role": "user", "content": (
                f"Viết kịch bản TTS cho câu chuyện:\nTHỂ LOẠI: {story['genre']}\n"
                f"TÔNG: {story['tone']}\nNỘI DUNG: {story['raw'][:2000]}"
            )},
            {"role": "assistant", "content": result}
        ]
        ctx.user_data["revision_count"] = 0

        await send_script_as_file(query.message, result, version=1, story=story)
        await query.message.reply_text(
            "✅ Kịch bản v1 đã xuất ra file!\nBạn muốn chỉnh sửa hay tạo output khác?",
            reply_markup=script_action_menu()
        )

    # ── Góp ý — kích hoạt chế độ chờ nhập góp ý ──────────────────────────────
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

    # ── SEO ───────────────────────────────────────────────────────────────────
    elif action == "seo":
        await query.edit_message_text("⏳ Đang tối ưu SEO... (~15 giây)")
        result = await loop.run_in_executor(None, lambda: gen_seo(story))
        await query.message.reply_text(f"🔍 *SEO PACKAGE*\n\n{result}", parse_mode="Markdown")
        await query.message.reply_text("Bạn muốn tạo thêm gì?", reply_markup=other_output_menu())

    # ── Thumbnail ─────────────────────────────────────────────────────────────
    elif action == "thumbnail":
        await query.edit_message_text("⏳ Đang tạo prompt thumbnail... (~15 giây)")
        result = await loop.run_in_executor(None, lambda: gen_thumbnail(story))
        await query.message.reply_text(f"🖼 *THUMBNAIL PROMPT*\n\n{result}", parse_mode="Markdown")
        await query.message.reply_text("Bạn muốn tạo thêm gì?", reply_markup=other_output_menu())

    # ── Tất cả ────────────────────────────────────────────────────────────────
    elif action == "all":
        await query.edit_message_text("⏳ Đang tạo toàn bộ gói sản xuất... (~60 giây)")
        script, seo, thumb = await asyncio.gather(
            loop.run_in_executor(None, lambda: gen_script(story)),
            loop.run_in_executor(None, lambda: gen_seo(story)),
            loop.run_in_executor(None, lambda: gen_thumbnail(story)),
        )
        ctx.user_data["script_history"] = [
            {"role": "user", "content": f"Viết kịch bản TTS cho câu chuyện:\nTHỂ LOẠI: {story['genre']}\nTÔNG: {story['tone']}\nNỘI DUNG: {story['raw'][:2000]}"},
            {"role": "assistant", "content": script}
        ]
        ctx.user_data["revision_count"] = 0

        await send_script_as_file(query.message, script, version=1, story=story)
        await query.message.reply_text(f"🔍 *SEO PACKAGE*\n\n{seo}", parse_mode="Markdown")
        await query.message.reply_text(f"🖼 *THUMBNAIL PROMPT*\n\n{thumb}", parse_mode="Markdown")
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
