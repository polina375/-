
import asyncio
import calendar
import logging
import sqlite3

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from bot.keyboards import main_keyboard


router = Router()

DB_PATH = Path(__file__).resolve().parent.parent / "bot.sqlite3"
TIMEZONE = ZoneInfo("Europe/Moscow")

FREQUENCIES = {
    "once": "Один раз",
    "daily": "Каждый день",
    "weekly": "Каждую неделю",
    "monthly": "Каждый месяц",
}


class ReminderForm(StatesGroup):
    text = State()
    date = State()
    frequency = State()
    edit_text = State()
    edit_date = State()


def init_reminders_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
            )
        """)

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(reminders)"
            ).fetchall()
        }

        if "frequency" not in columns:
            conn.execute("""
                ALTER TABLE reminders
                ADD COLUMN frequency TEXT NOT NULL
                DEFAULT 'once'
            """)

        if "repeat_day" not in columns:
            conn.execute("""
                ALTER TABLE reminders
                ADD COLUMN repeat_day INTEGER
            """)


def keyboard(buttons):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=title,
                    callback_data=data,
                )
            ]
            for title, data in buttons
        ]
    )


def menu_keyboard():
    return keyboard([
        ("➕ Создать напоминание", "rem:new"),
        ("📋 Мои напоминания", "rem:list"),
        ("🧾 Налоговый календарь", "tax:menu"),
    ])


def frequency_keyboard(prefix="rem:frequency"):
    return keyboard([
        ("1️⃣ Один раз", f"{prefix}:once"),
        ("🔁 Каждый день", f"{prefix}:daily"),
        ("📆 Каждую неделю", f"{prefix}:weekly"),
        ("🗓 Каждый месяц", f"{prefix}:monthly"),
    ])


def get_reminder(reminder_id, user_id):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT id, text, remind_at, frequency, repeat_day
            FROM reminders
            WHERE id = ? AND user_id = ? AND sent = 0
        """, (reminder_id, user_id)).fetchone()


def parse_date(text):
    try:
        value = datetime.strptime(
            text.strip(), "%d.%m.%Y %H:%M"
        )
        return value.replace(tzinfo=TIMEZONE)
    except (ValueError, AttributeError):
        return None


def format_date(value):
    date = datetime.fromisoformat(value)
    return date.strftime("%d.%m.%Y %H:%M")


async def open_reminders(message: Message):
    await message.answer(
        "🔔 Управление напоминаниями\n\n"
        "Создавай напоминания, выбирай периодичность "
        "и получай уведомления в Telegram.\n\n"
        "🕒 Время указывается по Москве.",
        reply_markup=menu_keyboard(),
    )


@router.callback_query(F.data == "rem:menu")
async def menu_callback(callback: CallbackQuery):
    await callback.answer()

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "🔔 Управление напоминаниями\n\n"
            "Выбери действие:",
            reply_markup=menu_keyboard(),
        )


async def start_creation(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ReminderForm.text)

    await message.answer(
        "✏️ Что тебе нужно напомнить?\n\n"
        "Например: Оплатить аренду.\n\n"
        "Для отмены отправь /cancel.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Command("newreminder"))
async def new_command(message: Message, state: FSMContext):
    await start_creation(message, state)


@router.callback_query(F.data == "rem:new")
async def new_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    if isinstance(callback.message, Message):
        await start_creation(callback.message, state)


@router.message(ReminderForm.text)
async def receive_text(message: Message, state: FSMContext):
    if not message.text or not message.text.strip():
        await message.answer("Напиши текст напоминания.")
        return

    await state.update_data(
        text=message.text.strip()[:500]
    )
    await state.set_state(ReminderForm.date)

    await message.answer(
        "📅 Укажи дату и время первого уведомления.\n\n"
        "Формат: 20.11.2026 15:30\n"
        "Часовой пояс: Москва (МСК)."
    )


@router.message(ReminderForm.date)
async def receive_date(message: Message, state: FSMContext):
    date = parse_date(message.text or "")

    if date is None:
        await message.answer(
            "❌ Неверный формат.\n"
            "Пример: 20.11.2026 15:30"
        )
        return

    if date <= datetime.now(TIMEZONE):
        await message.answer(
            "❌ Укажи дату и время в будущем."
        )
        return

    await state.update_data(
        remind_at=date.isoformat()
    )
    await state.set_state(ReminderForm.frequency)

    await message.answer(
        "🔁 Как часто повторять напоминание?",
        reply_markup=frequency_keyboard(),
    )


@router.callback_query(F.data.startswith("rem:frequency:"))
async def receive_frequency(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    if await state.get_state() != ReminderForm.frequency.state:
        await callback.answer(
            "Это действие уже неактуально.",
            show_alert=True,
        )
        return

    frequency = callback.data.split(":")[-1]

    if frequency not in FREQUENCIES:
        return

    data = await state.get_data()
    date = datetime.fromisoformat(data["remind_at"])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO reminders (
                user_id, text, remind_at,
                frequency, repeat_day
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            callback.from_user.id,
            data["text"],
            data["remind_at"],
            frequency,
            date.day if frequency == "monthly" else None,
        ))

    await state.clear()

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "✅ Периодичность выбрана!"
        )

        await callback.message.answer(
            "🎉 Напоминание создано!\n\n"
            f"📝 {data['text']}\n"
            f"📅 {format_date(data['remind_at'])} МСК\n"
            f"🔁 {FREQUENCIES[frequency]}",
            reply_markup=main_keyboard,
        )

        await callback.message.answer(
            "Что делаем дальше?",
            reply_markup=menu_keyboard(),
        )


def build_list(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT id, text, remind_at, frequency
            FROM reminders
            WHERE user_id = ? AND sent = 0
            ORDER BY remind_at
            LIMIT 15
        """, (user_id,)).fetchall()

    if not rows:
        return (
            "📭 Активных напоминаний пока нет.",
            keyboard([
                ("➕ Создать", "rem:new"),
                ("⬅️ Назад", "rem:menu"),
            ]),
        )

    lines = ["📋 Твои активные напоминания:\n"]
    buttons = []

    for reminder_id, text, date, frequency in rows:
        lines.append(
            f"🔔 №{reminder_id}: {text[:100]}\n"
            f"📅 {format_date(date)} МСК\n"
            f"🔁 {FREQUENCIES.get(frequency, 'Один раз')}\n"
        )

        buttons.append((
            f"⚙️ Управлять №{reminder_id}",
            f"rem:edit:{reminder_id}",
        ))

    buttons.append(("➕ Создать", "rem:new"))
    buttons.append(("⬅️ Назад", "rem:menu"))

    return "\n".join(lines)[:4000], keyboard(buttons)


@router.message(Command("myreminders"))
async def list_command(message: Message):
    if not message.from_user:
        return

    text, markup = build_list(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "rem:list")
async def list_callback(callback: CallbackQuery):
    await callback.answer()

    text, markup = build_list(callback.from_user.id)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=markup,
        )


@router.callback_query(F.data.startswith("rem:edit:"))
async def edit_menu(callback: CallbackQuery):
    await callback.answer()

    reminder_id = int(callback.data.split(":")[-1])
    reminder = get_reminder(
        reminder_id, callback.from_user.id
    )

    if not isinstance(callback.message, Message):
        return

    if reminder is None:
        await callback.message.edit_text(
            "Напоминание не найдено.",
            reply_markup=keyboard([
                ("⬅️ К списку", "rem:list"),
            ]),
        )
        return

    _, text, date, frequency, _ = reminder

    await callback.message.edit_text(
        f"⚙️ Напоминание №{reminder_id}\n\n"
        f"📝 {text}\n"
        f"📅 {format_date(date)} МСК\n"
        f"🔁 {FREQUENCIES.get(frequency, 'Один раз')}",
        reply_markup=keyboard([
            ("✏️ Изменить текст", f"rem:field:text:{reminder_id}"),
            ("📅 Изменить дату", f"rem:field:date:{reminder_id}"),
            ("🔁 Изменить повтор", f"rem:field:freq:{reminder_id}"),
            ("🗑 Удалить", f"rem:delete:{reminder_id}"),
            ("⬅️ К списку", "rem:list"),
        ]),
    )


@router.callback_query(F.data.startswith("rem:field:"))
async def choose_edit_field(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    parts = callback.data.split(":")
    field = parts[2]
    reminder_id = int(parts[3])

    reminder = get_reminder(
        reminder_id, callback.from_user.id
    )

    if reminder is None:
        await callback.answer(
            "Напоминание не найдено.",
            show_alert=True,
        )
        return

    if field == "freq":
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                "🔁 Выбери новую периодичность:",
                reply_markup=frequency_keyboard(
                    f"rem:setfreq:{reminder_id}"
                ),
            )
        return

    await state.clear()
    await state.update_data(reminder_id=reminder_id)

    if field == "text":
        await state.set_state(ReminderForm.edit_text)
        prompt = "✏️ Напиши новый текст напоминания:"
    else:
        await state.set_state(ReminderForm.edit_date)
        prompt = (
            "📅 Введи новую дату и время:\n"
            "20.11.2026 15:30\n\n"
            "Часовой пояс: Москва (МСК)."
        )

    if isinstance(callback.message, Message):
        await callback.message.answer(prompt)


@router.message(ReminderForm.edit_text)
async def save_edited_text(
    message: Message,
    state: FSMContext,
):
    if not message.from_user:
        return

    if not message.text or not message.text.strip():
        await message.answer("Напиши новый текст.")
        return

    data = await state.get_data()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE reminders
            SET text = ?
            WHERE id = ? AND user_id = ? AND sent = 0
        """, (
            message.text.strip()[:500],
            data["reminder_id"],
            message.from_user.id,
        ))

    await state.clear()

    await message.answer(
        "✅ Текст обновлён!",
        reply_markup=main_keyboard,
    )

    await message.answer(
        "Вернуться к напоминаниям:",
        reply_markup=keyboard([
            ("📋 Мои напоминания", "rem:list"),
        ]),
    )


@router.message(ReminderForm.edit_date)
async def save_edited_date(
    message: Message,
    state: FSMContext,
):
    if not message.from_user:
        return

    date = parse_date(message.text or "")

    if date is None or date <= datetime.now(TIMEZONE):
        await message.answer(
            "❌ Введи будущую дату в формате:\n"
            "20.11.2026 15:30"
        )
        return

    data = await state.get_data()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE reminders
            SET remind_at = ?, repeat_day = ?
            WHERE id = ? AND user_id = ? AND sent = 0
        """, (
            date.isoformat(),
            date.day,
            data["reminder_id"],
            message.from_user.id,
        ))

    await state.clear()

    await message.answer(
        "✅ Дата обновлена!",
        reply_markup=main_keyboard,
    )

    await message.answer(
        "Вернуться к напоминаниям:",
        reply_markup=keyboard([
            ("📋 Мои напоминания", "rem:list"),
        ]),
    )


@router.callback_query(F.data.startswith("rem:setfreq:"))
async def save_edited_frequency(callback: CallbackQuery):
    await callback.answer()

    parts = callback.data.split(":")
    reminder_id = int(parts[2])
    frequency = parts[3]

    if frequency not in FREQUENCIES:
        return

    reminder = get_reminder(
        reminder_id, callback.from_user.id
    )

    if reminder is None:
        return

    date = datetime.fromisoformat(reminder[2])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE reminders
            SET frequency = ?, repeat_day = ?
            WHERE id = ? AND user_id = ? AND sent = 0
        """, (
            frequency,
            date.day if frequency == "monthly" else None,
            reminder_id,
            callback.from_user.id,
        ))

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "✅ Периодичность обновлена!\n\n"
            f"🔁 {FREQUENCIES[frequency]}",
            reply_markup=keyboard([
                ("📋 К списку", "rem:list"),
            ]),
        )


@router.callback_query(F.data.startswith("rem:delete:"))
async def delete_confirmation(callback: CallbackQuery):
    await callback.answer()

    reminder_id = int(callback.data.split(":")[-1])

    reminder = get_reminder(
        reminder_id, callback.from_user.id
    )

    if not isinstance(callback.message, Message):
        return

    if reminder is None:
        await callback.message.edit_text(
            "Напоминание не найдено.",
            reply_markup=keyboard([
                ("⬅️ К списку", "rem:list"),
            ]),
        )
        return

    await callback.message.edit_text(
        "🗑 Точно удалить напоминание?\n\n"
        f"{reminder[1]}",
        reply_markup=keyboard([
            ("✅ Да, удалить", f"rem:confirm:{reminder_id}"),
            ("❌ Нет, оставить", "rem:list"),
        ]),
    )


@router.callback_query(F.data.startswith("rem:confirm:"))
async def confirm_delete(callback: CallbackQuery):
    await callback.answer()

    reminder_id = int(callback.data.split(":")[-1])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            DELETE FROM reminders
            WHERE id = ? AND user_id = ? AND sent = 0
        """, (
            reminder_id,
            callback.from_user.id,
        ))

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "✅ Напоминание удалено.",
            reply_markup=keyboard([
                ("📋 К списку", "rem:list"),
            ]),
        )


def next_occurrence(date, frequency, repeat_day=None):
    if frequency == "daily":
        return date + timedelta(days=1)

    if frequency == "weekly":
        return date + timedelta(weeks=1)

    if frequency == "monthly":
        year = date.year
        month = date.month + 1

        if month > 12:
            month = 1
            year += 1

        last_day = calendar.monthrange(year, month)[1]
        day = min(repeat_day or date.day, last_day)

        return date.replace(
            year=year,
            month=month,
            day=day,
        )

    return None


async def reminder_worker(bot: Bot):
    """Проверяет напоминания каждые 20 секунд."""

    while True:
        try:
            now = datetime.now(TIMEZONE)

            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute("""
                    SELECT
                        id, user_id, text, remind_at,
                        frequency, repeat_day
                    FROM reminders
                    WHERE sent = 0 AND remind_at <= ?
                    ORDER BY remind_at
                """, (now.isoformat(),)).fetchall()

            for (
                reminder_id,
                user_id,
                text,
                date_string,
                frequency,
                repeat_day,
            ) in rows:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=(
                            "🔔 АльфаБро напоминает!\n\n"
                            f"{text}"
                        ),
                    )

                    with sqlite3.connect(DB_PATH) as conn:
                        if frequency == "once":
                            conn.execute("""
                                UPDATE reminders
                                SET sent = 1
                                WHERE id = ? AND sent = 0
                            """, (reminder_id,))

                        else:
                            next_date = datetime.fromisoformat(
                                date_string
                            )

                            current_time = datetime.now(TIMEZONE)

                            while next_date <= current_time:
                                next_date = next_occurrence(
                                    next_date,
                                    frequency,
                                    repeat_day,
                                )

                            conn.execute("""
                                UPDATE reminders
                                SET remind_at = ?
                                WHERE id = ? AND sent = 0
                            """, (
                                next_date.isoformat(),
                                reminder_id,
                            ))

                except Exception:
                    logging.exception(
                        "Ошибка отправки напоминания %s",
                        reminder_id,
                    )

        except Exception:
            logging.exception(
                "Ошибка проверки напоминаний"
            )

        await asyncio.sleep(20)

from bot.tax_calendar import router as tax_router

router.include_router(tax_router)