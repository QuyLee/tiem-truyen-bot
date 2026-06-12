import os
import asyncio
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM = """Bạn là biên kịch kênh "Tiệm Truyện Nhỏ Nhỏ" — kênh cổ tích & dân gian Việt Nam, dùng narration + ảnh AI. Trả lời ngắn gọn, đúng format, không giải thích thừa."""

def call(prompt, model="claude-haiku-4-5", tokens=800):
    r = client.messages.create(
        model=model, max_tokens=tokens, system=SYSTEM,
        messages=[{"role":"user","content":prompt}]
    )
    return r.content[0].text

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Chào mừng đến Tiệm Truyện Agent!\n\n"
        "Gửi nội dung câu chuyện cho mình → mình sẽ tạo:\n"
        "✅ Kịch bản video đầy đủ\n"
        "✅ SEO: tiêu đề + tags + mô tả\n"
        "✅ Prompt thumbnail AI\n"
        "✅ Lịch đăng & chiến lược kênh\n\n"
        "Dán câu chuyện vào đây để bắt đầu! 👇"
    )

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    story = update.message.text
    if len(story) < 30:
        await update.message.reply_text("Câu chuyện quá ngắn! Bạn hãy gửi ít nhất 1 đoạn nội dung nhé.")
        return

    msg = await update.message.reply_text("⏳ Đang tạo gói sản xuất... (~30 giây)")

    loop = asyncio.get_event_loop()
    results = await asyncio.gather(
        loop.run_in_executor(None, lambda: call(
            f"Viết kịch bản YouTube cho câu chuyện:\n{story}\n\n"
            "Format:\n## HOOK (0-15s)\n[câu mở đầu mạnh]\n\n"
            "## CẢNH 1 – [tên]\nNARRATION: ...\nVISUAL: ...\nNHẠC: ...\n\n"
            "[tối đa 5 cảnh]\n\n## CALL TO ACTION\n[lời kêu gọi cuối]",
            model="claude-sonnet-4-6", tokens=1200
        )),
        loop.run_in_executor(None, lambda: call(
            f"SEO cho video cổ tích: {story[:200]}\n\n"
            "TITLE_1: [max 60 ký tự]\nTITLE_2: ...\nTITLE_3: ...\n"
            "DESCRIPTION: [200 từ có timestamps]\nTAGS: [20 tags]\nHASHTAGS: [10 hashtags]"
        )),
        loop.run_in_executor(None, lambda: call(
            f"Prompt thumbnail AI cho câu chuyện: {story[:150]}\n\n"
            "CONCEPT: [1 câu]\nPROMPT_EN: [cho Midjourney/Flux]\nPROMPT_VI: ...\n"
            "TEXT_OVERLAY: [2-4 chữ]\nCOLOR_PALETTE: [3 màu hex]"
        )),
        loop.run_in_executor(None, lambda: call(
            f"Lịch đăng & chiến lược kênh cổ tích, video: {story[:80]}\n\n"
            "SCHEDULE_4W: [lịch 4 tuần]\nNEXT_5_IDEAS: [5 ý tưởng]\nGROWTH_TIPS: [3 tips]"
        )),
    )

    await msg.delete()

    labels = ["🎬 KỊCH BẢN", "🔍 SEO", "🖼 THUMBNAIL PROMPT", "📅 LỊCH ĐĂNG"]
    for label, result in zip(labels, results):
        text = f"*{label}*\n\n{result}"
        # Telegram giới hạn 4096 ký tự/tin nhắn
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000], parse_mode="Markdown")

if __name__ == "__main__":
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Bot đang chạy...")
    app.run_polling()
