import os
import requests
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import uvicorn
import asyncio
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

TOKEN = "8612501783:AAGeBjR2_LP5DtfTPwzgg55nIjACKrH6hA0"
URL = "https://menu.sttec.yar.ru/timetable/rasp_first.html"
GROUP = "ИБ1-21"

# ---------- Базовое расписание (числитель) ----------
SCHEDULE_NUM_FULL = {
    "понедельник": {
        "1": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - Б302",
        "2": "МДК.04.01 (Тимощук М.В., Егорова Ю.С.) - Б309",
        "3": "Русский язык и культура речи (Грибанова Е.Н.) - Б401",
        "4": "Русский язык и культура речи (Грибанова Е.Н.) - Б401",
    },
    "вторник": {
        "0": "УП.04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308",
        "1": "УП.04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308",
        "2": "МДК.01.01 Операционные системы и среды (Егорова Ю.С., Андреева Е.И.) - Б407",
        "3": "Дополнительная профессия п/гр.1 (Панасюк А.Д.) - Б304",
    },
    "среда": {
        "0": "МДК.01.02 Базы данных (Бадина Ю.А.) - Б302",
        "1": "Технологии физического уровня передачи данных (Груздев В.В., Серова А.М.) - Б304, Б204",
        "2": "Технологии физического уровня передачи данных (Груздев В.В.) - Б501",
    },
    "четверг": {
        "0": "МДК.04.01 (Тимощук М.В.) - ДОТ",
        "1": "МДК.04 Учебная практика (Тимощук М.В.) - ДОТ",
        "2": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - ДОТ",
    },
    "пятница": {
        "0": "Электроника и схемотехника п/гр.1 (Леонидова Н.А.) - Б509",
        "1": "Электроника и схемотехника п/гр.1 (Леонидова Н.А.) - Б509",
        "2": "Организационно-правовое обеспечение информационной безопасности (Воробьева Н.Е.) - Б502",
        "3": "Математика (Холманова В.М.) - М102",
    },
    "суббота": {
        "1": "Дополнительная профессия п/гр.2 (Юров А.А.) - Б305",
        "2": "Физическая культура (Куликова А.А.) - Спорт Зал",
        "3": "Иностранный язык в профессиональной деятельности (Зубковская Е.А., Смирнова Е.Ф.) - А413, А412",
    },
}

# ---------- Базовое расписание (знаменатель) ----------
SCHEDULE_DEN_FULL = {
    "понедельник": {
        "1": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - Б302",
        "2": "МДК.04.01 (Тимощук М.В., Егорова Ю.С.) - Б309",
        "3": "Электроника и схемотехника (Леонидова Н.А.) - М202",
    },
    "вторник": {
        "0": "МДК 04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308/Б309",
        "1": "УП.04.02 (Хожайнова М.Г., Тимощук М.В.) - Б308/Б309",
        "2": "МДК.01.01 Операционные системы и среды (Егорова Ю.С., Андреева Е.И.) - Б407",
        "3": "Дополнительная профессия п/гр 1 (Панасюк А.Д.) - Б304",
    },
    "среда": {
        "0": "МДК.01.02 Базы данных (Байдина Ю.А.) - Б302",
        "1": "Технологии физического уровня передачи данных (Груздев В.В., Серова А.М.) - Б304, Б204",
        "2": "Технологии физического уровня передачи данных (Груздев В.В.) - Б501",
    },
    "четверг": {
        "0": "МДК.04.02 (Тимощук М.В.) - ДОТ",
        "1": "МДК.04 Учебная практика (Тимощук М.В.) - ДОТ",
        "2": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - ДОТ",
        "3": "Математика (Холманова В.М.) - ДОТ",
    },
    "пятница": {
        "0": "Электроника и схемотехника п/гр.2 (Леонидова Н.А.) - Б509",
        "1": "Электроника и схемотехника п/гр.2 (Леонидова Н.А.) - Б509",
        "2": "МДК 01.01 Операционные системы и среды (Егорова Ю.С.) - А401",
        "3": "Организационно-правовое обеспечение информационной безопасности (Воробьева Н.Е.) - Б502",
    },
    "суббота": {
        "1": "Дополнительная профессия п/гр.2 (Юров А.А.) - Б305",
        "2": "Физическая культура (Куликова А.А.) - спорт зал",
        "3": "Иностранный язык в профессиональной деятельности (Зубковская Е.А., Смирнова Е.Ф.) - А413, А412",
    },
}

# ---------- Функции ----------
def format_date_russian(date: datetime) -> str:
    months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    return f"{date.day} {months[date.month - 1]} {date.year}"

def expand_pair_numbers(pair_str: str):
    if ',' in pair_str:
        parts = pair_str.split(',')
        result = []
        for p in parts:
            if '-' in p:
                start, end = map(int, p.split('-'))
                result.extend(str(i) for i in range(start, end+1))
            else:
                result.append(p.strip())
        return result
    elif '-' in pair_str:
        start, end = map(int, pair_str.split('-'))
        return [str(i) for i in range(start, end+1)]
    else:
        return [pair_str.strip()]

def split_subject_and_teacher(text: str):
    text = text.strip()
    if not text or text == "Снято" or text == "снято":
        return text, "—"
    match = re.search(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.(?:[А-ЯЁ]\.)?)$', text)
    if match:
        teacher = match.group(1)
        subject = text[:match.start()].strip()
        return subject, teacher
    else:
        return text, "—"

def parse_zameny_from_html(html_text: str):
    soup = BeautifulSoup(html_text, 'lxml')
    table = soup.find('table')
    if not table:
        return []
    rows = table.find_all('tr')
    results = []
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 6:
            continue
        group_cell = cells[1].get_text(strip=True)
        if group_cell != GROUP:
            continue
        pair_numbers_str = cells[2].get_text(strip=True)
        if not pair_numbers_str:
            continue
        replacement_full = cells[4].get_text(strip=True)
        room = cells[5].get_text(strip=True)
        is_dist = (replacement_full == "" or replacement_full == "—" or "по расписанию" in replacement_full.lower())
        pair_list = expand_pair_numbers(pair_numbers_str)
        for pair_num in pair_list:
            if is_dist:
                results.append({
                    "pair": pair_num,
                    "type": "dist",
                    "room": room,
                })
            else:
                replacement_subj, replacement_teacher = split_subject_and_teacher(replacement_full)
                results.append({
                    "pair": pair_num,
                    "type": "replace",
                    "replacement": replacement_subj,
                    "teacher": replacement_teacher,
                    "room": room,
                })
    return results

def extract_metadata_from_html(html_text: str):
    soup = BeautifulSoup(html_text, 'lxml')
    header_text = soup.get_text()
    date_match = re.search(r'(\d+)\s+([а-я]+)\s+(\d{4})\s+года', header_text)
    if not date_match:
        return None, None
    day = int(date_match.group(1))
    month_str = date_match.group(2)
    year = int(date_match.group(3))
    months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
        "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12
    }
    month = months.get(month_str.lower(), 1)
    try:
        file_date = datetime(year, month, day)
    except:
        file_date = None
    type_match = re.search(r'\((Числитель|Знаменатель)\)', header_text)
    week_type = type_match.group(1) if type_match else None
    return file_date, week_type

def build_final_schedule(week_type, target_weekday, replacements):
    if week_type == "Числитель":
        base = SCHEDULE_NUM_FULL.get(target_weekday, {})
    else:
        base = SCHEDULE_DEN_FULL.get(target_weekday, {})
    repl_dict = {}
    for r in replacements:
        pair = r['pair']
        if r['type'] == 'replace':
            repl_dict[pair] = ('replace', f"{r['replacement']} ({r['teacher']})", r['room'])
        elif r['type'] == 'dist':
            if pair in base:
                original_line = base[pair]
                base_part = re.sub(r'\s*\-.*$', '', original_line)
                new_line = base_part
            else:
                new_line = "Занятие"
            repl_dict[pair] = ('dist', new_line, r['room'])
    all_pair_nums = set(base.keys()) | set(repl_dict.keys())
    number_emojis = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    result = []
    for pair_num in sorted(all_pair_nums, key=int):
        num = int(pair_num)
        if 0 <= num <= 9:
            pair_emoji = number_emojis[num]
        else:
            pair_emoji = f"{num}️⃣"
        if pair_num in repl_dict:
            typ, line, room = repl_dict[pair_num]
            if typ == 'replace':
                result.append(f"{pair_emoji}🔁 → {line}\nКаб: {room}")
            else:  # dist
                result.append(f"{pair_emoji}💻 → {line}\nКаб: {room}")
        else:
            base_line = base[pair_num]
            match = re.match(r'^(.*?)\s*-\s*(.*?)$', base_line)
            if match:
                subject_part = match.group(1).strip()
                room = match.group(2).strip()
            else:
                subject_part = base_line
                room = "?"
            result.append(f"{pair_emoji} → {subject_part}\nКаб: {room}")
    return result

async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Загружаю расписание...")
    try:
        response = requests.get(URL, timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            await update.message.reply_text("Не удалось загрузить страницу с заменами.")
            return
        html_text = response.text
        file_date, week_type = extract_metadata_from_html(html_text)
        if not file_date:
            await update.message.reply_text("Не удалось определить дату в файле замен.")
            return
        if not week_type:
            await update.message.reply_text("Не удалось определить тип недели (числитель/знаменатель).")
            return
        weekdays_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        target_weekday = weekdays_ru[file_date.weekday()]
        if target_weekday == "воскресенье":
            await update.message.reply_text("В этот день пар нет.")
            return
        replacements = parse_zameny_from_html(html_text)
        final_schedule = build_final_schedule(week_type, target_weekday, replacements)
        date_str = format_date_russian(file_date)
        message = f"📅 Расписание на {date_str} ({target_weekday}, {week_type})\n\n"
        message += "\n\n".join(final_schedule)
        message += f"\n\n🔗 <a href='{URL}'>Проверить замены</a>"
        await update.message.reply_text(message, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

async def ib_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот замен для группы ИБ1-21📝\n\n"
        "Команда /zam — показать актуальное расписание с учетом всех замен.\n"
        "Команда /ib — чтобы снова увидеть это сообщение.\n\n"
        "Успехов в использовании!",
        parse_mode='HTML'
    )

async def main():
    import logging
    logging.basicConfig(level=logging.INFO)
    application = Application.builder().token(TOKEN).updater(None).build()
    application.add_handler(CommandHandler("zam", get_schedule))
    application.add_handler(CommandHandler("ib", ib_command))
    application.add_handler(CommandHandler("start", ib_command))
    await application.initialize()
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        await application.bot.set_webhook(f"{render_url}/telegram")
        logging.info(f"Webhook set to {render_url}/telegram")
    else:
        logging.error("RENDER_EXTERNAL_URL not set.")
        return
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import Response, PlainTextResponse
    async def telegram_webhook(request: Request) -> Response:
        await application.update_queue.put(Update.de_json(await request.json(), application.bot))
        return Response()
    async def health_check(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")
    starlette_app = Starlette(routes=[
        Route("/telegram", telegram_webhook, methods=["POST"]),
        Route("/healthcheck", health_check, methods=["GET"]),
    ])
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    async with application:
        await application.start()
        await server.serve()
        await application.stop()

if __name__ == "__main__":
    asyncio.run(main())
