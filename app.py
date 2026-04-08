import os
import requests
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import uvicorn
import asyncio
from datetime import datetime, timedelta

# === НАСТРОЙКИ ===
TOKEN = "8612501783:AAGeBjR2_LP5DtfTPwzgg55nIjACKrH6hA0"
URL = "https://menu.sttec.yar.ru/timetable/rasp_first.html"
GROUP = "ИБ1-21"
# =================

# ----- Базовое расписание (числитель) -----
SCHEDULE_NUM = {
    "понедельник": [
        "1 пара: Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - Б302",
        "2 пара: МДК.04.01 (Тимощук М.В., Егорова Ю.С.) - Б309",
        "3 пара: Русский язык и культура речи (Грибанова Е.Н.) - Б401",
        "4 пара: Русский язык и культура речи (Грибанова Е.Н.) - Б401"
    ],
    "вторник": [
        "0 пара: УП.04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308",
        "1 пара: УП.04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308",
        "2 пара: МДК.01.01 Операционные системы и среды (Егорова Ю.С., Андреева Е.И.) - Б407",
        "3 пара: Дополнительная профессия п/гр.1 (Панасюк А.Д.) - Б304"
    ],
    "среда": [
        "0 пара: МДК.01.02 Базы данных (Бадина Ю.А.) - Б302",
        "1 пара: Технологии физического уровня передачи данных (Груздев В.В., Серова А.М.) - Б304, Б204",
        "2 пара: Технологии физического уровня передачи данных (Груздев В.В.) - Б501"
    ],
    "четверг": [
        "0 пара: МДК.04.01 (Тимощук М.В.) - ДОТ",
        "1 пара: МДК.04 Учебная практика (Тимощук М.В.) - ДОТ",
        "2 пара: Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - ДОТ"
    ],
    "пятница": [
        "0 пара: Электроника и схемотехника п/гр.1 (Леонидова Н.А.) - Б509",
        "1 пара: Электроника и схемотехника п/гр.1 (Леонидова Н.А.) - Б509",
        "2 пара: Организационно-правовое обеспечение информационной безопасности (Воробьева Н.Е.) - Б502",
        "3 пара: Математика (Холманова В.М.) - М102"
    ],
    "суббота": [
        "1 пара: Дополнительная профессия п/гр.2 (Юров А.А.) - Б305",
        "2 пара: Физическая культура (Куликова А.А.) - Спорт Зал",
        "3 пара: Иностранный язык в профессиональной деятельности (Зубковская Е.А., Смирнова Е.Ф.) - А413, А412"
    ]
}

# ----- Базовое расписание (знаменатель) -----
SCHEDULE_DEN = {
    "понедельник": [
        "1 пара: Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - Б302",
        "2 пара: МДК.04.01 (Тимощук М.В., Егорова Ю.С.) - Б309",
        "3 пара: Электроника и схемотехника (Леонидова Н.А.) - М202"
    ],
    "вторник": [
        "0 пара: МДК 04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308/Б309",
        "1 пара: УП.04.02 (Хожайнова М.Г., Тимощук М.В.) - Б308/Б309",
        "2 пара: МДК.01.01 Операционные системы и среды (Егорова Ю.С., Андреева Е.И.) - Б407",
        "3 пара: Дополнительная профессия п/гр 1 (Панасюк А.Д.) - Б304"
    ],
    "среда": [
        "0 пара: МДК.01.02 Базы данных (Байдина Ю.А.) - Б302",
        "1 пара: Технологии физического уровня передачи данных (Груздев В.В., Серова А.М.) - Б304, Б204",
        "2 пара: Технологии физического уровня передачи данных (Груздев В.В.) - Б501"
    ],
    "четверг": [
        "0 пара: МДК.04.02 (Тимощук М.В.) - ДОТ",
        "1 пара: МДК.04 Учебная практика (Тимощук М.В.) - ДОТ",
        "2 пара: Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - ДОТ",
        "3 пара: Математика (Холманова В.М.) - ДОТ"
    ],
    "пятница": [
        "0 пара: Электроника и схемотехника п/гр.2 (Леонидова Н.А.) - Б509",
        "1 пара: Электроника и схемотехника п/гр.2 (Леонидова Н.А.) - Б509",
        "2 пара: МДК 01.01 Операционные системы и среды (Егорова Ю.С.) - А401",
        "3 пара: Организационно-правовое обеспечение информационной безопасности (Воробьева Н.Е.) - Б502"
    ],
    "суббота": [
        "1 пара: Дополнительная профессия п/гр.2 (Юров А.А.) - Б305",
        "2 пара: Физическая культура (Куликова А.А.) - спорт зал",
        "3 пара: Иностранный язык в профессиональной деятельности (Зубковская Е.А., Смирнова Е.Ф.) - А413, А412"
    ]
}

# ---------- Функции парсинга замен (исправленная) ----------
def expand_pair_numbers(pair_str: str):
    """Преобразует строку с номерами пар вида '0,1', '0-3', '0,1,2' в список отдельных номеров"""
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

def split_original_disciplines(orig_str: str, num_pairs: int):
    """Если в исходной дисциплине перечислено несколько предметов (через пробел или запятую), разделить на список"""
    # Упрощённо: если num_pairs > 1, пытаемся разбить по пробелам? Но в примере "МДК 04.01 УП 04" - это два предмета.
    # Пока вернём один и тот же для всех пар (как временное решение)
    # Для более точного разбора нужно знать структуру. Сейчас просто вернём один предмет для всех пар.
    return [orig_str] * num_pairs

def parse_zameny_from_text(text: str):
    lines = text.splitlines()
    results = []
    for line in lines:
        if GROUP not in line:
            continue
        # Ищем группу
        group_idx = line.find(GROUP)
        after_group = line[group_idx + len(GROUP):].lstrip()
        # Извлекаем номер пары (может быть "0,1" или "0-3")
        pair_match = re.match(r'([\d,\-]+)', after_group)
        if not pair_match:
            continue
        pair_numbers_str = pair_match.group(1)
        rest = after_group[len(pair_numbers_str):].lstrip()
        # Разделяем по двум и более пробелам
        parts = re.split(r'\s{2,}', rest)
        if len(parts) < 2:
            continue
        # Первая часть - исходная дисциплина (может быть несколько)
        original_part = parts[0].strip()
        # Вторая часть - дисциплина по замене
        replacement_full = parts[1].strip() if len(parts) > 1 else ""
        # Аудитория - третья часть, если есть
        room = parts[2].strip() if len(parts) > 2 else "—"
        # Разворачиваем номера пар
        pair_list = expand_pair_numbers(pair_numbers_str)
        # Для каждого номера пары создаём запись о замене
        for pair_num in pair_list:
            # Если исходная дисциплина пустая - ставим "—"
            original = original_part if original_part else "—"
            # Разделяем замену на предмет и преподавателя
            replacement_subj, replacement_teacher = split_subject_and_teacher(replacement_full)
            results.append({
                "pair": pair_num,
                "original": original,
                "replacement": replacement_subj,
                "teacher": replacement_teacher,
                "room": room
            })
    return results

def split_subject_and_teacher(text: str):
    text = text.strip()
    if not text or text == "Снято":
        return text, "—"
    # Ищем в конце фамилию с инициалами
    match = re.search(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.(?:[А-ЯЁ]\.)?)$', text)
    if match:
        teacher = match.group(1)
        subject = text[:match.start()].strip()
        return subject, teacher
    else:
        return text, "—"

def extract_metadata_from_file(text: str):
    date_match = re.search(r'(\d+)\s+([а-я]+)\s+(\d{4})\s+года', text)
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
    type_match = re.search(r'\((Числитель|Знаменатель)\)', text)
    week_type = type_match.group(1) if type_match else None
    return file_date, week_type

def apply_replacements(schedule_list, replacements):
    repl_dict = {}
    for r in replacements:
        pair_num = r['pair']
        if r['replacement'] == "Снято":
            repl_dict[pair_num] = None
        else:
            room = r['room']
            teacher = r['teacher']
            subject = r['replacement']
            if room and room != "—":
                new_line = f"{subject} ({teacher}) - <b>{room}</b>"
            else:
                new_line = f"{subject} ({teacher})"
            repl_dict[pair_num] = new_line
    result = []
    for line in schedule_list:
        pair_match = re.match(r'(\d+)\s+пара:', line)
        if pair_match:
            pair_num = pair_match.group(1)
            if pair_num in repl_dict:
                if repl_dict[pair_num] is None:
                    continue
                else:
                    result.append(f"{pair_num} пара: {repl_dict[pair_num]} <i>[ЗАМЕНА]</i>")
            else:
                new_line = re.sub(r' - (.*?)$', r' - <b>\1</b>', line)
                result.append(new_line)
        else:
            result.append(line)
    return result

# ---------- Основная команда /zam ----------
async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Загружаю расписание...")
    try:
        response = requests.get(URL, timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            await update.message.reply_text("Не удалось загрузить страницу с заменами.")
            return

        file_text = response.text
        file_date, week_type = extract_metadata_from_file(file_text)

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

        if week_type == "Числитель":
            base_schedule = SCHEDULE_NUM.get(target_weekday, [])
        else:
            base_schedule = SCHEDULE_DEN.get(target_weekday, [])

        if not base_schedule:
            await update.message.reply_text(f"Расписание на {target_weekday} не найдено.")
            return

        replacements = parse_zameny_from_text(file_text)
        final_schedule = apply_replacements(base_schedule, replacements)

        date_str = file_date.strftime("%d.%m.%Y")
        message = f"📅 Расписание на {date_str} ({target_weekday}, {week_type}):\n\n"
        for line in final_schedule:
            message += f"• {line}\n"
        if not replacements:
            message += f"\n✅ Замен на {date_str} нет."
        await update.message.reply_text(message, parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

async def ib_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 Бот расписания и замен для группы {GROUP}\n"
        "Команда /zam — показать итоговое расписание на дату, указанную в файле замен.\n"
        "Бот сам применяет замены и помечает их.",
        parse_mode='HTML'
    )

# ---------- Веб-хук и запуск ----------
async def main():
    import logging
    logging.basicConfig(level=logging.INFO)
    application = Application.builder().token(TOKEN).updater(None).build()
    application.add_handler(CommandHandler("zam", get_schedule))
    application.add_handler(CommandHandler("ib", ib_command))
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
