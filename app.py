import os
import asyncio
import logging
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import re
import requests

# --- НАСТРОЙКИ ---
# Я уже вставил сюда твой токен!
TOKEN = "8612501783:AAGeBjR2_LP5DtfTPwzgg55nIjACKrH6hA0"
# Адрес сайта с расписанием
URL = "https://menu.sttec.yar.ru/timetable/rasp_first.html"
# Название твоей группы
GROUP = "ИБ1-21"
# -----------------

# --- Функции для парсинга расписания (твой код, перенесенный сюда) ---
def split_subject_and_teacher(text: str):
    text = text.strip()
    if not text or text == "Снято":
        return text, "—"
    match = re.search(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.(?:[А-ЯЁ]\.)?)$', text)
    if match:
        teacher = match.group(1)
        subject = text[:match.start()].strip()
        return subject, teacher
    else:
        return text, "—"

def parse_zameny_from_text(text: str):
    lines = text.splitlines()
    results = []
    for line in lines:
        if GROUP not in line:
            continue
        group_idx = line.find(GROUP)
        after_group = line[group_idx + len(GROUP):].lstrip()
        pair_match = re.match(r'(\d+)', after_group)
        if not pair_match:
            continue
        pair_num = pair_match.group(1)
        rest = after_group[len(pair_num):].lstrip()
        parts = re.split(r'\s{2,}', rest)
        if len(parts) == 3:
            original = parts[0].strip() if parts[0].strip() else "—"
            replacement_full = parts[1].strip()
            room = parts[2].strip()
        elif len(parts) == 2:
            second = parts[1].strip()
            if re.match(r'[А-Я]?\d{2,3}|Сп\.\w+|ДОТ|Экскурсия', second):
                original = "—"
                replacement_full = parts[0].strip()
                room = second
            else:
                original = parts[0].strip() if parts[0].strip() else "—"
                replacement_full = parts[1].strip()
                room = "—"
        else:
            original = "—"
            replacement_full = parts[0].strip()
            room = "—"
        replacement_subj, replacement_teacher = split_subject_and_teacher(replacement_full)
        results.append({
            "pair": pair_num,
            "original": original,
            "replacement": replacement_subj,
            "teacher": replacement_teacher,
            "room": room
        })
    return results

def extract_date_from_file(text: str):
    match = re.search(r'(\d+)\s+([а-я]+)\s+(\d{4})\s+года', text)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)} года"
    return None

# --- Обработчик команды /zameny ---
async def get_zameny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Загружаю страницу с заменами...")
    try:
        response = requests.get(URL, timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            await update.message.reply_text(f"Ошибка: сайт вернул код {response.status_code}.")
            return
        file_content = response.text
        replacements = parse_zameny_from_text(file_content)
        date_str = extract_date_from_file(file_content)
        if not date_str:
            date_str = "указанную дату"
        if replacements:
            message = f"ЗАМЕНЫ НА {date_str}\n\n"
            for r in replacements:
                message += f"НОМЕР ПАРЫ: {r['pair']}\n"
                message += f"ИСХОД ПАРА: {r['original']}\n"
                message += f"ЗАМЕНА: {r['replacement']}\n"
                message += f"ПРЕПОД: {r['teacher']}\n"
                message += f"АУДИТОРИЯ: {r['room']}\n\n"
        else:
            message = f"✅ Замен для группы {GROUP} на {date_str} нет."
        await update.message.reply_text(message)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")
        
# --- Обработчик команды /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Привет! Я бот замен для группы {GROUP}.\nКоманда /zameny — показать замены.")

# --- Часть для работы на Render через веб-хуки ---
async def main():
    # Настраиваем логирование
    logging.basicConfig(level=logging.INFO)
    
    # Создаем приложение бота
    application = Application.builder().token(TOKEN).updater(None).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("zameny", get_zameny))
    
    # Инициализируем приложение
    await application.initialize()
    
    # Устанавливаем веб-хук. Render сам предоставит переменную окружения RENDER_EXTERNAL_URL
    # Это и есть адрес, по которому будет "висеть" наш бот в интернете.
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        await application.bot.set_webhook(f"{render_url}/telegram")
        logging.info(f"Webhook set to {render_url}/telegram")
    else:
        logging.error("RENDER_EXTERNAL_URL not set. Webhook cannot be configured.")
        return
    
    # Создаем Starlette приложение для обработки веб-хуков и проверки здоровья
    async def telegram_webhook(request: Request) -> Response:
        # Это функция, которая принимает запрос от Telegram и передает его боту
        await application.update_queue.put(Update.de_json(await request.json(), application.bot))
        return Response()
        
    async def health_check(request: Request) -> PlainTextResponse:
        # Это эндпоинт, который Render будет проверять, чтобы убедиться, что наш бот жив
        return PlainTextResponse("OK")
    
    starlette_app = Starlette(routes=[
        Route("/telegram", telegram_webhook, methods=["POST"]),
        Route("/healthcheck", health_check, methods=["GET"]),
    ])
    
    # Настраиваем и запускаем веб-сервер
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    # Запускаем бота и веб-сервер параллельно
    async with application:
        await application.start()
        await server.serve()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())