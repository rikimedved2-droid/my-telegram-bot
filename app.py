import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse
import requests
from bs4 import BeautifulSoup

# ---------- КОНФИГУРАЦИЯ (из переменных окружения) ----------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set")

ADMIN_IDS = []
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------- БАЗА ДАННЫХ ДЛЯ ДОМАШКИ ----------
DB_PATH = "homework.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS homework (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    due_date TEXT,
                    created_at TEXT NOT NULL
                )''')
    c.execute("PRAGMA table_info(homework)")
    columns = [col[1] for col in c.fetchall()]
    if "due_date" not in columns:
        c.execute("ALTER TABLE homework ADD COLUMN due_date TEXT")
    conn.commit()
    conn.close()

def add_task_db(task_text, due_date_str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO homework (task, due_date, created_at) VALUES (?, ?, ?)",
              (task_text, due_date_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    return new_id

def get_all_tasks_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, task, due_date, created_at FROM homework ORDER BY due_date, created_at")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_task_db(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM homework WHERE id = ?", (task_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def format_hw_list(tasks):
    if not tasks:
        return "📭 Нет текущих домашних заданий."
    lines = ["📚 Текущие домашние задания:\n"]
    for idx, (db_id, task, due_date, created_at) in enumerate(tasks, start=1):
        due_str = f" (срок: {due_date})" if due_date else ""
        lines.append(f"{idx}️⃣ {task}{due_str}")
    return "\n".join(lines)

# ---------- ПАРСЕР ДАТ ----------
def parse_due_date(date_str: str) -> str | None:
    date_str = date_str.strip().lower()
    today = datetime.now().date()
    if date_str == "сегодня":
        return today.strftime("%Y-%m-%d")
    if date_str == "завтра":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    match = re.match(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', date_str)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            parsed = datetime(year, month, day).date()
            return parsed.strftime("%Y-%m-%d")
        except:
            return None
    match = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if match:
        year, month, day = map(int, match.groups())
        try:
            parsed = datetime(year, month, day).date()
            return parsed.strftime("%Y-%m-%d")
        except:
            return None
    return None

# ---------- СОСТОЯНИЯ ДЛЯ ДИАЛОГА /add ----------
TASK_TEXT, DUE_DATE_STATE = range(2)

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ У вас нет прав.")
        return ConversationHandler.END
    await update.message.reply_text("📝 Введите текст задания:")
    return TASK_TEXT

async def add_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_text'] = update.message.text
    await update.message.reply_text("📅 Введите срок сдачи (например: завтра, 15.04, 2025-05-01) или '-' без срока:")
    return DUE_DATE_STATE

async def add_due_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    due_input = update.message.text.strip()
    due_date_str = None
    if due_input != "-":
        parsed = parse_due_date(due_input)
        if parsed is None:
            await update.message.reply_text("❌ Не распознано. Попробуйте ещё раз:")
            return DUE_DATE_STATE
        due_date_str = parsed
    task_text = context.user_data['task_text']
    new_id = add_task_db(task_text, due_date_str)
    due_display = f"срок {due_date_str}" if due_date_str else "без срока"
    await update.message.reply_text(f"✅ Добавлено задание №{new_id}:\n{task_text}\n{due_display}")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    context.user_data.clear()
    return ConversationHandler.END

# ---------- ОБРАБОТЧИКИ КОМАНД ДОМАШКИ ----------
async def del_hw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет прав.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Использование: /del <номер> (номер из /hw)")
        return
    temp_num = int(context.args[0])
    tasks = get_all_tasks_db()
    if temp_num < 1 or temp_num > len(tasks):
        await update.message.reply_text("❌ Неверный номер.")
        return
    real_id, task_text, _, _ = tasks[temp_num - 1]
    if delete_task_db(real_id):
        await update.message.reply_text(f"🗑 Удалено: {task_text}")
    else:
        await update.message.reply_text("Ошибка удаления.")

async def show_hw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_all_tasks_db()
    await update.message.reply_text(format_hw_list(tasks))

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет прав.")
        return
    await update.message.reply_text(
        "👑 <b>Админ-команды:</b>\n"
        "/add — добавить задание (диалог)\n"
        "/del &lt;номер&gt; — удалить задание\n"
        "/admin — эта справка\n\n"
        "Все команды работают в личке с ботом.",
        parse_mode='HTML'
    )

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Ваш ID: `{update.effective_user.id}`", parse_mode='Markdown')

# ---------- ФУНКЦИИ ДЛЯ РАСПИСАНИЯ И ЗАМЕН (старые, без изменений) ----------
def format_date_russian(date: datetime) -> str:
    months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
    return f"{date.day} {months[date.month-1]} {date.year}"

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
    if not text or text.lower() == "снято":
        return text, "—"
    match = re.search(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.(?:[А-ЯЁ]\.)?)$', text)
    if match:
        teacher = match.group(1)
        subject = text[:match.start()].strip()
        if not subject:
            subject = "—"
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
        if group_cell != "ИБ1-21":
            continue
        pair_numbers_str = cells[2].get_text(strip=True)
        if not pair_numbers_str:
            continue
        replacement_full = cells[4].get_text(strip=True)
        room = cells[5].get_text(strip=True)
        pair_list = expand_pair_numbers(pair_numbers_str)
        if "снято" in replacement_full.lower():
            for pair_num in pair_list:
                results.append({"pair": pair_num, "type": "remove"})
            continue
        is_dist = (replacement_full == "" or replacement_full == "—" or "по расписанию" in replacement_full.lower())
        if is_dist:
            for pair_num in pair_list:
                results.append({"pair": pair_num, "type": "dist", "room": room})
        else:
            replacement_subj, replacement_teacher = split_subject_and_teacher(replacement_full)
            for pair_num in pair_list:
                results.append({"pair": pair_num, "type": "replace", "replacement": replacement_subj, "teacher": replacement_teacher, "room": room})
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
    months = {"января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,"июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12}
    month = months.get(month_str.lower(), 1)
    try:
        file_date = datetime(year, month, day)
    except:
        file_date = None
    type_match = re.search(r'\((Числитель|Знаменатель)\)', header_text)
    week_type = type_match.group(1) if type_match else None
    return file_date, week_type

SCHEDULE_NUM_FULL = {
    "понедельник": {"1": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - Б302","2": "МДК.04.01 (Тимощук М.В., Егорова Ю.С.) - Б309","3": "Русский язык и культура речи (Грибанова Е.Н.) - Б401","4": "Русский язык и культура речи (Грибанова Е.Н.) - Б401"},
    "вторник": {"0": "УП.04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308","1": "УП.04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308","2": "МДК.01.01 Операционные системы и среды (Егорова Ю.С., Андреева Е.И.) - Б407","3": "Дополнительная профессия п/гр.1 (Панасюк А.Д.) - Б304"},
    "среда": {"0": "МДК.01.02 Базы данных (Бадина Ю.А.) - Б302","1": "Технологии физического уровня передачи данных (Груздев В.В., Серова А.М.) - Б304, Б204","2": "Технологии физического уровня передачи данных (Груздев В.В.) - Б501"},
    "четверг": {"0": "МДК.04.01 (Тимощук М.В.) - ДОТ","1": "МДК.04 Учебная практика (Тимощук М.В.) - ДОТ","2": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - ДОТ"},
    "пятница": {"0": "Электроника и схемотехника п/гр.1 (Леонидова Н.А.) - Б509","1": "Электроника и схемотехника п/гр.1 (Леонидова Н.А.) - Б509","2": "Организационно-правовое обеспечение информационной безопасности (Воробьева Н.Е.) - Б502","3": "Математика (Холманова В.М.) - М102"},
    "суббота": {"1": "Дополнительная профессия п/гр.2 (Юров А.А.) - Б305","2": "Физическая культура (Куликова А.А.) - Спорт Зал","3": "Иностранный язык в профессиональной деятельности (Зубковская Е.А., Смирнова Е.Ф.) - А413, А412"},
}
SCHEDULE_DEN_FULL = {
    "понедельник": {"1": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - Б302","2": "МДК.04.01 (Тимощук М.В., Егорова Ю.С.) - Б309","3": "Электроника и схемотехника (Леонидова Н.А.) - М202"},
    "вторник": {"0": "МДК 04 Учебная практика (Хожайнова М.Г., Тимощук М.В.) - Б308/Б309","1": "УП.04.02 (Хожайнова М.Г., Тимощук М.В.) - Б308/Б309","2": "МДК.01.01 Операционные системы и среды (Егорова Ю.С., Андреева Е.И.) - Б407","3": "Дополнительная профессия п/гр 1 (Панасюк А.Д.) - Б304"},
    "среда": {"0": "МДК.01.02 Базы данных (Байдина Ю.А.) - Б302","1": "Технологии физического уровня передачи данных (Груздев В.В., Серова А.М.) - Б304, Б204","2": "Технологии физического уровня передачи данных (Груздев В.В.) - Б501"},
    "четверг": {"0": "МДК.04.02 (Тимощук М.В.) - ДОТ","1": "МДК.04 Учебная практика (Тимощук М.В.) - ДОТ","2": "Основы алгоритмизации и программирования (Вершинина Н.А., Панасюк А.Д.) - ДОТ","3": "Математика (Холманова В.М.) - ДОТ"},
    "пятница": {"0": "Электроника и схемотехника п/гр.2 (Леонидова Н.А.) - Б509","1": "Электроника и схемотехника п/гр.2 (Леонидова Н.А.) - Б509","2": "МДК 01.01 Операционные системы и среды (Егорова Ю.С.) - А401","3": "Организационно-правовое обеспечение информационной безопасности (Воробьева Н.Е.) - Б502"},
    "суббота": {"1": "Дополнительная профессия п/гр.2 (Юров А.А.) - Б305","2": "Физическая культура (Куликова А.А.) - спорт зал","3": "Иностранный язык в профессиональной деятельности (Зубковская Е.А., Смирнова Е.Ф.) - А413, А412"},
}

def build_final_schedule(week_type, target_weekday, replacements):
    if week_type == "Числитель":
        base = SCHEDULE_NUM_FULL.get(target_weekday, {})
    else:
        base = SCHEDULE_DEN_FULL.get(target_weekday, {})
    repl_dict = {}
    for r in replacements:
        pair = r['pair']
        if r['type'] == 'remove':
            repl_dict[pair] = ('remove', None)
        elif r['type'] == 'replace':
            repl_dict[pair] = ('replace', f"{r['replacement']} ({r['teacher']})", r['room'])
        elif r['type'] == 'dist':
            if pair in base:
                original_line = base[pair]
                base_part = re.sub(r'\s*\-.*$', '', original_line)
                new_line = base_part
            else:
                new_line = "Занятие"
            repl_dict[pair] = ('dist', new_line, r['room'])
    all_pair_nums = set(base.keys())
    for pair_num, (typ, *_) in repl_dict.items():
        if typ != 'remove':
            all_pair_nums.add(pair_num)
    number_emojis = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣"]
    result = []
    for pair_num in sorted(all_pair_nums, key=int):
        num = int(pair_num)
        pair_emoji = number_emojis[num] if 0 <= num <= 9 else f"{num}️⃣"
        if pair_num in repl_dict:
            typ = repl_dict[pair_num][0]
            if typ == 'remove':
                continue
            elif typ == 'replace':
                _, line, room = repl_dict[pair_num]
                result.append(f"{pair_emoji}_🔁 → {line}\nКаб: {room}")
            elif typ == 'dist':
                _, line, room = repl_dict[pair_num]
                result.append(f"{pair_emoji} → {line}\nКаб: {room}")
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
        response = requests.get("https://menu.sttec.yar.ru/timetable/rasp_first.html", timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            await update.message.reply_text("Не удалось загрузить страницу.")
            return
        html_text = response.text
        file_date, week_type = extract_metadata_from_html(html_text)
        if not file_date:
            await update.message.reply_text("Не удалось определить дату.")
            return
        if not week_type:
            await update.message.reply_text("Не удалось определить тип недели.")
            return
        weekdays_ru = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
        target_weekday = weekdays_ru[file_date.weekday()]
        if target_weekday == "воскресенье":
            await update.message.reply_text("В этот день пар нет.")
            return
        replacements = parse_zameny_from_html(html_text)
        final_schedule = build_final_schedule(week_type, target_weekday, replacements)
        date_str = format_date_russian(file_date)
        message = f"📅 Расписание на {date_str} ({target_weekday}, {week_type})\n\n"
        message += "\n\n".join(final_schedule)
        message += "\n\n🔗 <a href='https://menu.sttec.yar.ru/timetable/rasp_first.html'>Проверить замены</a>"
        await update.message.reply_text(message, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

async def ib_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Бот замен и домашки для ИБ1-21</b>\n\n"
        "📌 <b>Команды:</b>\n"
        "• /zam — расписание с заменами\n"
        "• /hw — список домашних заданий\n"
        "• /add — добавить задание (только админ, диалог)\n"
        "• /del &lt;номер&gt; — удалить задание (админ)\n"
        "• /admin — справка для админа\n\n"
        "Успехов! 📚",
        parse_mode='HTML'
    )

# ---------- MAIN ----------
async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    application = Application.builder().token(TOKEN).updater(None).build()

    # Старые команды
    application.add_handler(CommandHandler("zam", get_schedule))
    application.add_handler(CommandHandler("ib", ib_command))
    application.add_handler(CommandHandler("start", ib_command))

    # Команды домашки
    application.add_handler(CommandHandler("hw", show_hw))
    application.add_handler(CommandHandler("del", del_hw))
    application.add_handler(CommandHandler("admin", admin_help))
    application.add_handler(CommandHandler("myid", my_id))

    # Диалог добавления
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_text)],
            DUE_DATE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_due_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )
    application.add_handler(conv_handler)

    await application.initialize()
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        await application.bot.set_webhook(f"{render_url}/telegram")
        logging.info(f"Webhook set to {render_url}/telegram")
    else:
        logging.error("RENDER_EXTERNAL_URL not set")
        return

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
