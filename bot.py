import os
import asyncio
import anthropic
import httpx
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

async def fetch_url_content(url: str) -> str:
    """Lấy nội dung text từ URL"""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            # Lấy text thô, bỏ tag HTML đơn giản
            import re
            text = re.sub(r'<style[^>]*>.*?</style>', '', r.text, flags=re.DOTALL)
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:6000]  # giới hạn để tiết kiệm token
    except Exception as e:
        return f"ERROR: {e}"

def extract_url(text: str):
    import re
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

# ─── Phân tích đầu vào ────────────────────────────────────────────────────────

async def analyze_story(raw: str) -> dict:
    """Phân tích câu chuyện, trả về dict với summary, genre, tone"""
    result = call(
        SYSTEM_ANALYST,
        f"Phân tích nội dung sau:\n\n{raw}\n\n"
        "Trả về ĐÚNG format:\n"
        "TÓM TẮT: [3-5 câu]\n"
        "THỂ LOẠI: [cổ tích / dân gian / triết lý / tâm lý]\n"
        "TÔNG GIỌNG: [ấm áp / lạnh-triết lý / huyền bí]\n"
        "ĐỘ DÀI GỢI Ý: [5-7 phút / 8-12 phút / 12-18 phút]",
        model="claude-haiku-4-5", tokens=300
    )
    lines = {l.split(":")[0].strip(): ":".join(l.split(":")[1:]).strip()
             for l in result.splitlines() if ":" in l}
    return {
        "summary":  lines.get("TÓM TẮT", ""),
        "genre":    lines.get("THỂ LOẠI", "cổ tích"),
        "tone":     lines.get("TÔNG GIỌNG", "ấm áp"),
        "duration": lines.get("ĐỘ DÀI GỢI Ý", "8-12 phút"),
        "raw":      raw
    }

# ─── Các output task ──────────────────────────────────────────────────────────

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
        "Viết lại thành kịch bản TTS hoàn chỉnh. "
        "Văn bản thuần, đoạn 3-5 câu, cấu trúc: Hook → Phát triển → Cao trào → Kết luận. "
        "Không gạch đầu dòng, không chú thích, không hiệu ứng.",
        model="claude-sonnet-4-6", tokens=2000
    )

def gen_seo(story: dict) -> str:
    return call(
        SYSTEM_SEO,
        f"Tạo SEO package cho video YouTube.\nTHỂ LOẠI: {story['genre']}\nTÓM TẮT: {story['summary']}\n\n"
        "TITLE_1: [max 60 ký tự, có emoji, gây tò mò]\n"
        "TITLE_2: [biến thể tập trung keyword]\n"
        "TITLE_3: [biến thể cảm xúc]\n"
        "---\n"
        "DESCRIPTION:\n[200-250 từ, 3 dòng đầu hook, có timestamps 00:00, keywords tự nhiên, link kênh]\n"
        "---\n"
        "TAGS: [tag1, tag2, ... 22 tags tiếng Việt]\n"
        "HASHTAGS: #tag1 #tag2 ... 10 hashtags",
        model="claude-haiku-4-5", tokens=700
    )

def gen_thumbnail(story: dict) -> str:
    return call(
        SYSTEM_THUMB,
        f"Tạo prompt thumbnail AI viral cho video YouTube.\n"
        f"THỂ LOẠI: {story['genre']} | TÔNG: {story['tone']}\nTÓM TẮT: {story['summary']}\n\n"
        "CONCEPT: [1-2 câu mô tả ý tưởng hình ảnh gây tò mò]\n"
        "PROMPT_EN: [prompt chi tiết cho Midjourney/Flux/DALL-E — style, lighting, composition, mood, ultra-detailed]\n"
        "PROMPT_VI: [prompt tương đương tiếng Việt]\n"
        "TEXT_OVERLAY: [2-5 chữ in đậm, gây tò mò]\n"
        "FONT_STYLE: [bold / serif dramatic / handwritten]\n"
        "COLOR_PALETTE: [3 màu hex chủ đạo]",
        model="claude-haiku-4-5", tokens=500
    )

# ─── Telegram handlers ────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Tiệm Truyện Agent* đã sẵn sàng\\!\n\n"
        "Gửi cho mình:\n"
        "• Nội dung câu chuyện \\(dán text trực tiếp\\)\n"
        "• Hoặc link bài viết có câu chuyện\n\n"
        "Mình sẽ phân tích và cho bạn chọn output muốn tạo\\.",
        parse_mode="MarkdownV2"
    )

async def handle_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Kiểm tra độ dài tối thiểu
    url = extract_url(text)
    if not url and len(text) < 50:
        await update.message.reply_text(
            "⚠️ Nội dung quá ngắn!\n\n"
            "Hãy gửi:\n• Đoạn văn câu chuyện (tối thiểu 50 ký tự)\n• Hoặc link bài viết"
        )
        return

    msg = await update.message.reply_text("⏳ Đang đọc & phân tích nội dung...")

    # Lấy nội dung nếu là URL
    raw = text
    if url:
        await msg.edit_text("🔗 Đang tải nội dung từ link...")
        content = await fetch_url_content(url)
        if content.startswith("ERROR"):
            await msg.edit_text(f"❌ Không tải được link:\n{content}\n\nBạn thử dán text trực tiếp nhé.")
            return
        raw = content

    # Phân tích câu chuyện
    await msg.edit_text("🔍 Đang phân tích câu chuyện...")
    story = await asyncio.get_event_loop().run_in_executor(None, lambda: analyze_story.__wrapped__(raw) if hasattr(analyze_story, '__wrapped__') else None)

    # Chạy analyze_story sync trong executor
    loop = asyncio.get_event_loop()
    story = await loop.run_in_executor(None, lambda: _analyze_sync(raw))

    # Lưu story vào context để dùng sau
    ctx.user_data["story"] = story

    # Gửi tóm tắt + menu lựa chọn
    summary_text = (
        f"✅ *Đã phân tích xong\\!*\n\n"
        f"📌 *Tóm tắt:* {escape_md(story['summary'])}\n"
        f"🎭 *Thể loại:* {escape_md(story['genre'])}\n"
        f"🎙 *Tông giọng:* {escape_md(story['tone'])}\n"
        f"⏱ *Độ dài gợi ý:* {escape_md(story['duration'])}\n\n"
        f"Bạn muốn tạo output nào\\?"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kịch bản TTS", callback_data="script"),
         InlineKeyboardButton("🔍 SEO", callback_data="seo")],
        [InlineKeyboardButton("🖼 Prompt Thumbnail", callback_data="thumbnail"),
         InlineKeyboardButton("✨ Tất cả", callback_data="all")],
    ])

    await msg.edit_text(summary_text, parse_mode="MarkdownV2", reply_markup=keyboard)

def _analyze_sync(raw: str) -> dict:
    """Sync wrapper cho analyze_story"""
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

def escape_md(text: str) -> str:
    """Escape ký tự đặc biệt cho MarkdownV2"""
    for ch in r'_*[]()~`>#+-=|{}.!':
        text = text.replace(ch, f'\\{ch}')
    return text

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    story = ctx.user_data.get("story")
    if not story:
        await query.edit_message_text("⚠️ Phiên làm việc đã hết. Hãy gửi lại câu chuyện nhé!")
        return

    action = query.data
    loop = asyncio.get_event_loop()

    if action == "script":
        await query.edit_message_text("⏳ Đang viết kịch bản TTS... (~30 giây)")
        result = await loop.run_in_executor(None, lambda: gen_script(story))
        header = "🎬 *KỊCH BẢN TTS*\n\n"
        for i, part in enumerate(split_message(result)):
            text = (header + part) if i == 0 else part
            await query.message.reply_text(text, parse_mode="Markdown")

    elif action == "seo":
        await query.edit_message_text("⏳ Đang tối ưu SEO... (~15 giây)")
        result = await loop.run_in_executor(None, lambda: gen_seo(story))
        await query.message.reply_text(f"🔍 *SEO PACKAGE*\n\n{result}", parse_mode="Markdown")

    elif action == "thumbnail":
        await query.edit_message_text("⏳ Đang tạo prompt thumbnail... (~15 giây)")
        result = await loop.run_in_executor(None, lambda: gen_thumbnail(story))
        await query.message.reply_text(f"🖼 *THUMBNAIL PROMPT*\n\n{result}", parse_mode="Markdown")

    elif action == "all":
        await query.edit_message_text("⏳ Đang tạo toàn bộ gói sản xuất... (~60 giây)")
        script, seo, thumb = await asyncio.gather(
            loop.run_in_executor(None, lambda: gen_script(story)),
            loop.run_in_executor(None, lambda: gen_seo(story)),
            loop.run_in_executor(None, lambda: gen_thumbnail(story)),
        )
        # Gửi từng phần
        for part in split_message(script):
            await query.message.reply_text(f"🎬 *KỊCH BẢN TTS*\n\n{part}", parse_mode="Markdown")
        await query.message.reply_text(f"🔍 *SEO PACKAGE*\n\n{seo}", parse_mode="Markdown")
        await query.message.reply_text(f"🖼 *THUMBNAIL PROMPT*\n\n{thumb}", parse_mode="Markdown")
        await query.message.reply_text("✅ Gói sản xuất hoàn tất! Gửi câu chuyện mới để tiếp tục.")
        return

    # Menu chọn thêm sau mỗi output đơn
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kịch bản TTS", callback_data="script"),
         InlineKeyboardButton("🔍 SEO", callback_data="seo")],
        [InlineKeyboardButton("🖼 Thumbnail", callback_data="thumbnail"),
         InlineKeyboardButton("✨ Tất cả", callback_data="all")],
    ])
    await query.message.reply_text("Bạn muốn tạo thêm gì không?", reply_markup=keyboard)

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))
    print("✅ Tiệm Truyện Bot đang chạy...")
    app.run_polling()
