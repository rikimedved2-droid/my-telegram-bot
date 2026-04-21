import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ---------- КОНФИГУРАЦИЯ ----------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set")

INITIAL_ADMIN_ID = 1207797393

# ---------- НАСТРОЙКИ SUPABASE ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- ФУНКЦИИ БАЗЫ ДАННЫХ ----------
def is_admin(user_id: int) -> bool:
    res = supabase.table("admins").select("user_id").eq("user_id", user_id).execute()
    return len(res.data) > 0

def get_all_admins():
    res = supabase.table("admins").select("user_id, username, name").order("name").execute()
    return [(row["user_id"], row["username"], row["name"]) for row in res.data]

def add_admin_to_db(user_id: int, username: str, name: str) -> bool:
    try:
        supabase.table("admins").insert({"user_id": user_id, "username": username, "name": name}).execute()
        return True
    except Exception:
        return False

def remove_admin_by_user_id(user_id: int) -> bool:
    res = supabase.table("admins").delete().eq("user_id", user_id).execute()
    return len(res.data) > 0

def add_task_db(task_text: str, due_date_str: str) -> int:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res = supabase.table("homework").insert({
        "task": task_text,
        "due_date": due_date_str,
        "created_at": created_at
    }).execute()
    return res.data[0]["id"]

def get_all_tasks_db():
    res = supabase.table("homework").select("id, task, due_date, created_at").order("due_date").order("created_at").execute()
    return [(row["id"], row["task"], row["due_date"], row["created_at"]) for row in res.data]

def delete_task_db(task_id: int) -> bool:
    res = supabase.table("homework").delete().eq("id", task_id).execute()
    return len(res.data) > 0

# ---------- КЛАВИАТУРЫ ----------
def format_hw_list(tasks):
    if not tasks:
        return "📭 Нет текущих домашних заданий."
    lines = ["📚 Текущие домашние задания:\n"]
    for idx, (db_id, task, due_date, _) in enumerate(tasks, start=1):
        due_str = f" (срок: {due_date})" if due_date else ""
        lines.append(f"{idx}️⃣ {task}{due_str}")
    return "\n".join(lines)

def get_main_keyboard(is_admin_user):
    keyboard = [
        [InlineKeyboardButton("📅 Замены", callback_data="zam")],
        [InlineKeyboardButton("📚 Домашка", callback_data="hw")],
        [InlineKeyboardButton("ℹ️ Инфо", callback_data="info")],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("👑 Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ Добавить ДЗ", callback_data="add_hw")],
        [InlineKeyboardButton("❌ Удалить ДЗ", callback_data="del_hw")],
        [InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")],
        [InlineKeyboardButton("➖ Удалить админа", callback_data="del_admin")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_delete_buttons(tasks):
    if not tasks:
        return None
    buttons = []
    for idx, (db_id, task, due_date, _) in enumerate(tasks, start=1):
        short_task = task[:30] + "..." if len(task) > 30 else task
        buttons.append([InlineKeyboardButton(f"{idx}. {short_task}", callback_data=f"del_{db_id}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_confirm_buttons(action_type, item_id):
    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action_type}_{item_id}")],
        [InlineKeyboardButton("❌ Нет", callback_data=f"cancel_{action_type}")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_delete_admin_buttons(admins, current_user_id):
    if not admins:
        return None
    buttons = []
    for user_id, username, name in admins:
        if user_id == INITIAL_ADMIN_ID or user_id == current_user_id:
            continue
        buttons.append([InlineKeyboardButton(f"{name} (ID {user_id})", callback_data=f"deladmin_{user_id}")])
    if not buttons:
        return None
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_back_to_main_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])

def get_cancel_button(callback_data="cancel_action"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=callback_data)]])

def get_menu_button():
    return ReplyKeyboardMarkup([[KeyboardButton("📋 Меню")]], resize_keyboard=True)

# ---------- ДИАЛОГИ ----------
async def add_hw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("⛔ Нет прав.", show_alert=True)
        return
    await query.message.delete()
    context.user_data['waiting_for_task'] = True
    await query.message.reply_text(
        "📝 Введите текст задания:",
        reply_markup=get_cancel_button("cancel_add_hw")
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "📋 Меню":
        await start(update, context)
        return

    if context.user_data.get('waiting_for_admin_id'):
        if not text.isdigit():
            await update.message.reply_text(
                "❌ ID должен быть числом. Попробуйте ещё раз.\nОтправьте ID:",
                reply_markup=get_cancel_button("cancel_add_admin")
            )
            return
        user_id_new = int(text)
        username_new = f"id{user_id_new}"
        context.user_data['new_admin_user_id'] = user_id_new
        context.user_data['new_admin_username'] = username_new
        context.user_data.pop('waiting_for_admin_id', None)
        context.user_data['waiting_for_admin_name'] = True
        await update.message.reply_text(
            "Теперь введите имя для этого админа (как он будет отображаться в списке):",
            reply_markup=get_cancel_button("cancel_add_admin")
        )
        return

    if context.user_data.get('waiting_for_admin_name'):
        name = text
        user_id_new = context.user_data.get('new_admin_user_id')
        username_new = context.user_data.get('new_admin_username')
        if add_admin_to_db(user_id_new, username_new, name):
            await update.message.reply_text(f"✅ Админ {name} (ID {user_id_new}) добавлен.")
        else:
            await update.message.reply_text("❌ Ошибка: возможно, уже админ.")
        context.user_data.pop('waiting_for_admin_name', None)
        context.user_data.pop('new_admin_user_id', None)
        context.user_data.pop('new_admin_username', None)
        await update.message.reply_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        return

    if context.user_data.get('waiting_for_task'):
        context.user_data['task_text'] = text
        context.user_data['waiting_for_task'] = False
        context.user_data['waiting_for_due'] = True
        await update.message.reply_text(
            "📅 Введите срок сдачи (свободная форма):",
            reply_markup=get_cancel_button("cancel_add_hw")
        )
        return

    if context.user_data.get('waiting_for_due'):
        due_date_str = None if text == "-" else text
        task_text = context.user_data.get('task_text')
        if task_text:
            new_id = add_task_db(task_text, due_date_str)
            due_display = f"срок: {due_date_str}" if due_date_str else "без срока"
            await update.message.reply_text(f"✅ Добавлено задание:\n{task_text}\n{due_display}")
        else:
            await update.message.reply_text("❌ Ошибка: текст задания потерян.")
        context.user_data.pop('waiting_for_task', None)
        context.user_data.pop('waiting_for_due', None)
        context.user_data.pop('task_text', None)
        await update.message.reply_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        return

# ---------- ОТОБРАЖЕНИЕ ЗАМЕН ----------
async def send_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    await query.edit_message_text("Загружаю замены...")
    try:
        response = requests.get("https://menu.sttec.yar.ru/timetable/rasp_first.html", timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            await query.edit_message_text("Не удалось загрузить страницу с заменами.")
            await query.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin(user_id)))
            return
        html_text = response.text
        file_date, week_type = extract_metadata_from_html(html_text)
        if not file_date or not week_type:
            await query.edit_message_text("Не удалось определить дату или тип недели.")
            await query.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin(user_id)))
            return
        weekdays_ru = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
        target_weekday = weekdays_ru[file_date.weekday()]
        if target_weekday == "воскресенье":
            await query.edit_message_text("В этот день пар нет.")
            await query.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin(user_id)))
            return
        replacements = parse_zameny_from_html(html_text)
        final_schedule = build_final_schedule(week_type, target_weekday, replacements)
        date_str = format_date_russian(file_date)
        text = f"📅 Замены на {date_str} ({target_weekday}, {week_type})\n\n"
        text += "\n\n".join(final_schedule)
        text += "\n\n🔗 <a href='https://menu.sttec.yar.ru/timetable/rasp_first.html'>Проверить замены на сайте</a>"
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_back_to_main_button())
    except Exception as e:
        await query.edit_message_text(f"Ошибка: {str(e)}")
        await query.message.reply_text("Главное меню:", reply_markup=get_main_keyboard(is_admin(user_id)))

# ---------- ОТОБРАЖЕНИЕ ДОМАШКИ ----------
async def show_hw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tasks = get_all_tasks_db()
    text = format_hw_list(tasks)
    await query.edit_message_text(text, reply_markup=get_back_to_main_button())

# ---------- ИНФО ----------
async def show_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🤖 Бот замен и домашних заданий для группы ИБ1-21\n\n"
        "📌 Как пользоваться:\n"
        "• Управляй ботом с помощью кнопок под сообщениями.\n\n"
        "📅 Замены:\n"
        "Показывает замены на день, указанный на сайте колледжа.\n"
        "Бот сам определяет числитель/знаменатель и подставляет замены.\n\n"
        "🔍 Обозначения в заменах:\n"
        "• <code>0️⃣_🔁</code> → пара с заменой\n"
        "• <code>0️⃣</code> → обычная пара\n"
        "• <b>Каб:</b> — аудитория (ДОТ, Сп.зал, номер кабинета)\n\n"
        "📚 Домашка:\n"
        "Показывает список АКТУАЛЬНЫХ домашних заданий.\n\n"
        "💡 Кнопка «Инфо» — снова покажет это сообщение.\n\n"
        "Успехов в учёбе! 📚"
    )
    await query.edit_message_text(text, reply_markup=get_back_to_main_button(), parse_mode='HTML')

# ---------- УДАЛЕНИЕ ДЗ ----------
async def delete_task_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    tasks = get_all_tasks_db()
    task_text = None
    for db_id, task, due_date, _ in tasks:
        if db_id == task_id:
            task_text = task
            break
    if task_text:
        context.user_data['pending_delete_task'] = task_id
        await query.edit_message_text(
            f"⚠️ Точно удалить задание?\n\n{task_text}",
            reply_markup=get_confirm_buttons("del_task", task_id)
        )
    else:
        await query.edit_message_text("❌ Задание не найдено.", reply_markup=get_admin_keyboard())

async def confirm_delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = context.user_data.get('pending_delete_task')
    if task_id is None:
        await query.edit_message_text("❌ Ошибка: задание не найдено.", reply_markup=get_admin_keyboard())
        return
    if delete_task_db(task_id):
        tasks = get_all_tasks_db()
        if not tasks:
            await query.edit_message_text("📭 Нет текущих домашних заданий.", reply_markup=get_admin_keyboard())
        else:
            await query.edit_message_text(format_hw_list(tasks), reply_markup=get_delete_buttons(tasks))
    else:
        await query.edit_message_text("❌ Ошибка удаления.", reply_markup=get_admin_keyboard())
    context.user_data.pop('pending_delete_task', None)

# ---------- УПРАВЛЕНИЕ АДМИНАМИ ----------
async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("⛔ Нет прав.", show_alert=True)
        return
    await query.edit_message_text(
        "Отправьте числовой ID пользователя, которого хотите сделать админом.\n"
        "ID можно узнать, если пользователь напишет /myid в личку с ботом.\n\n"
        "Для отмены нажмите кнопку ниже.",
        reply_markup=get_cancel_button("cancel_add_admin")
    )
    context.user_data['waiting_for_admin_id'] = True

async def del_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("⛔ Нет прав.", show_alert=True)
        return
    admins = get_all_admins()
    if not admins:
        await query.edit_message_text("📭 Нет админов для удаления.", reply_markup=get_admin_keyboard())
        return
    admin_buttons = get_delete_admin_buttons(admins, user_id)
    if not admin_buttons:
        await query.edit_message_text("Нет доступных для удаления админов.", reply_markup=get_admin_keyboard())
        return
    await query.edit_message_text(
        "Выберите админа для удаления:",
        reply_markup=admin_buttons
    )

async def delete_admin_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("⛔ Нет прав.", show_alert=True)
        return
    admin_to_delete = int(query.data.split("_")[1])
    if admin_to_delete == INITIAL_ADMIN_ID:
        await query.answer("❌ Нельзя удалить создателя бота.", show_alert=True)
        return
    if admin_to_delete == user_id:
        await query.answer("❌ Нельзя удалить самого себя.", show_alert=True)
        return
    admins = get_all_admins()
    admin_name = None
    for uid, username, name in admins:
        if uid == admin_to_delete:
            admin_name = name
            break
    context.user_data['pending_delete_admin'] = admin_to_delete
    await query.edit_message_text(
        f"⚠️ Точно удалить админа {admin_name} (ID {admin_to_delete})?",
        reply_markup=get_confirm_buttons("del_admin", admin_to_delete)
    )

async def confirm_delete_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = context.user_data.get('pending_delete_admin')
    if admin_id is None:
        await query.edit_message_text("❌ Ошибка: админ не найден.", reply_markup=get_admin_keyboard())
        return
    if remove_admin_by_user_id(admin_id):
        await query.edit_message_text("✅ Админ удалён.", reply_markup=get_admin_keyboard())
    else:
        await query.edit_message_text("❌ Ошибка при удалении.", reply_markup=get_admin_keyboard())
    context.user_data.pop('pending_delete_admin', None)

# ---------- ОТМЕНА ДИАЛОГОВ ----------
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("👑 Админ-панель", reply_markup=get_admin_keyboard())

# ---------- КОМАНДЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "🤖 Бот замен и домашних заданий для группы ИБ1-21\n\nГлавное меню:",
        reply_markup=get_main_keyboard(is_admin(user_id))
    )
    await update.message.reply_text("\u200b", reply_markup=get_menu_button())

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Ваш ID: `{update.effective_user.id}`", parse_mode='Markdown')

# ---------- ОСНОВНОЙ ОБРАБОТЧИК КНОПОК ----------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "zam":
        await send_schedule(update, context)
    elif data == "hw":
        await show_hw(update, context)
    elif data == "info":
        await show_info(update, context)
    elif data == "admin_panel":
        if is_admin(user_id):
            await query.edit_message_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
        else:
            await query.answer("⛔ У вас нет прав.", show_alert=True)
    elif data == "add_hw":
        if is_admin(user_id):
            await add_hw_callback(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data == "del_hw":
        if is_admin(user_id):
            tasks = get_all_tasks_db()
            if not tasks:
                await query.edit_message_text("📭 Нет заданий для удаления.", reply_markup=get_admin_keyboard())
            else:
                await query.edit_message_text("Выберите задание для удаления:", reply_markup=get_delete_buttons(tasks))
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data == "add_admin":
        if is_admin(user_id):
            await add_admin_prompt(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data == "del_admin":
        if is_admin(user_id):
            await del_admin_prompt(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data == "main_menu":
        await query.edit_message_text("Главное меню:", reply_markup=get_main_keyboard(is_admin(user_id)))
        await query.message.reply_text("\u200b", reply_markup=get_menu_button())
    elif data == "cancel_add_hw" or data == "cancel_add_admin" or data == "cancel_action":
        await cancel_action(update, context)
    elif data.startswith("del_"):
        if is_admin(user_id):
            await delete_task_by_id(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data.startswith("confirm_del_task_"):
        if is_admin(user_id):
            await confirm_delete_task(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data.startswith("deladmin_"):
        if is_admin(user_id):
            await delete_admin_by_id(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data.startswith("confirm_del_admin_"):
        if is_admin(user_id):
            await confirm_delete_admin(update, context)
        else:
            await query.answer("⛔ Нет прав.", show_alert=True)
    elif data.startswith("cancel_del_task") or data.startswith("cancel_del_admin"):
        await query.edit_message_text("👑 Админ-панель", reply_markup=get_admin_keyboard())

# ---------- ПАРСИНГ ЗАМЕН ----------
def format_date_russian(date):
    months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
    return f"{date.day} {months[date.month-1]} {date.year}"

def expand_pair_numbers(pair_str):
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

def parse_zameny_from_html(html_text):
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
        repl_stripped = replacement_full.strip()
        if repl_stripped == "" or repl_stripped == "—" or repl_stripped.lower() == "по расписанию":
            if room and room.strip() and room != "?":
                for pair_num in pair_list:
                    results.append({
                        "pair": pair_num,
                        "type": "dist",
                        "room": room,
                    })
            continue
        if repl_stripped.lower() == "снято":
            for pair_num in pair_list:
                results.append({
                    "pair": pair_num,
                    "type": "remove",
                })
            continue
        for pair_num in pair_list:
            results.append({
                "pair": pair_num,
                "type": "replace",
                "replacement": replacement_full,
                "room": room,
            })
    return results

def extract_metadata_from_html(html_text):
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
            repl_dict[pair] = ('replace', r['replacement'], r['room'])
        elif r['type'] == 'dist':
            if pair in base:
                original_line = base[pair]
                base_part = re.sub(r'\s*\-.*$', '', original_line)
                repl_dict[pair] = ('dist', base_part, r['room'])
            else:
                repl_dict[pair] = ('dist', "Занятие", r['room'])
    all_pair_nums = set(base.keys())
    for pair_num, (typ, *_) in repl_dict.items():
        if typ != 'remove':
            all_pair_nums.add(pair_num)
    number_emojis = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣"]
    result = []
    for pair_num in sorted(all_pair_nums, key=int):
        num = int(pair_num)
        if 0 <= num <= 9:
            pair_emoji = number_emojis[num]
        else:
            pair_emoji = f"{num}️⃣"
        if pair_num in repl_dict:
            typ = repl_dict[pair_num][0]
            if typ == 'remove':
                continue
            elif typ == 'replace':
                _, text, room = repl_dict[pair_num]
                if room and room != "?":
                    result.append(f"{pair_emoji}_🔁 → {text}\nКаб: {room}")
                else:
                    result.append(f"{pair_emoji}_🔁 → {text}")
            elif typ == 'dist':
                _, line, room = repl_dict[pair_num]
                if room and room != "?":
                    result.append(f"{pair_emoji} → {line}\nКаб: {room}")
                else:
                    result.append(f"{pair_emoji} → {line}")
        else:
            base_line = base[pair_num]
            match = re.match(r'^(.*?)\s*-\s*(.*?)$', base_line)
            if match:
                subject_part = match.group(1).strip()
                room = match.group(2).strip()
            else:
                subject_part = base_line
                room = "?"
            if room and room != "?":
                result.append(f"{pair_emoji} → {subject_part}\nКаб: {room}")
            else:
                result.append(f"{pair_emoji} → {subject_part}")
    return result

# ---------- MAIN (синхронный, без ручного asyncio) ----------
def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", my_id))

    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен с Supabase. Данные сохраняются в облаке.")
    application.run_polling()

if __name__ == "__main__":
    main()
