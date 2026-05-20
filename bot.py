import re
import json
import fitz
import os
import base64
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CHANNEL_ID = os.environ.get("CHANNEL_ID")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, *args):
        pass

Thread(target=lambda: HTTPServer(("0.0.0.0", 8080), Handler).serve_forever(), daemon=True).start()

def extract_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def parse_questions_via_gemini(text: str) -> list:
    prompt = f"""You are given a text containing MCQ questions with options and answers.
Extract ALL questions and return them as a JSON array.
Each object must have:
- "question": the question text
- "options": array of exactly 4 option strings (without A) B) C) D) prefix)
- "correct_index": 0-based index of correct answer (0=A, 1=B, 2=C, 3=D)
- "explanation": why this answer is correct (1-2 lines in Hindi)
Return ONLY valid JSON array. No explanation. No markdown.
Text:
{text}"""
    response = model.generate_content(prompt)
    raw = response.text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)

async def post_polls_to_channel(questions: list, context, status_msg):
    total = len(questions)
    for i, q in enumerate(questions):
        try:
            await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=f"Q{i+1}. {q['question']}",
                options=q["options"],
                type="quiz",
                correct_option_id=q["correct_index"],
                is_anonymous=True,
                explanation=f"✅ सही जवाब: {q['options'][q['correct_index']]}\n\n📚 {q.get('explanation', '')}"
            )
            await status_msg.edit_text(f"⏳ Posting... {i+1}/{total} done")
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Q{i+1} failed: {str(e)}")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await update.message.reply_text("📄 PDF मिली! Questions extract हो रहे हैं...")
    try:
        file = await context.bot.get_file(update.message.document.file_id)
        pdf_bytes = bytes(await file.download_as_bytearray())
        text = extract_text(pdf_bytes)
        if not text.strip():
            await status.edit_text("❌ PDF से text नहीं निकला। Text वाली PDF भेजें!")
            return
        await status.edit_text("🤖 Gemini questions parse कर रहा है...")
        questions = parse_questions_via_gemini(text)
        if not questions:
            await status.edit_text("❌ कोई question नहीं मिला।")
            return
        await status.edit_text(f"✅ {len(questions)} questions मिले! Channel पर post हो रहे हैं...")
        await post_polls_to_channel(questions, context, status)
        await status.edit_text(f"🎉 Done! {len(questions)} Quiz Polls post हो गए!")
    except Exception as e:
        await status.edit_text(f"⚠️ Error: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text and len(text) > 50:
        status = await update.message.reply_text("🤖 Gemini questions parse कर रहा है...")
        try:
            questions = parse_questions_via_gemini(text)
            if not questions:
                await status.edit_text("❌ कोई question नहीं मिला।")
                return
            await status.edit_text(f"✅ {len(questions)} questions मिले! Channel पर post हो रहे हैं...")
            await post_polls_to_channel(questions, context, status)
            await status.edit_text(f"🎉 Done! {len(questions)} Quiz Polls post हो गए!")
        except Exception as e:
            await status.edit_text(f"⚠️ Error: {str(e)}")
    else:
        await update.message.reply_text("👋 नमस्ते! मुझे MCQ वाली PDF या Text भेजें! 🎯")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot चालू है...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
