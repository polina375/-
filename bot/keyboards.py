
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="💬 Задать вопрос"),
            KeyboardButton(text="📚 Материалы"),
        ],
        [
            KeyboardButton(text="👤 Мой профиль"),
            KeyboardButton(text="🔔 Напоминания"),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие 👇",
)
