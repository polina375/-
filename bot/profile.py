
import json
import sqlite3
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from bot.keyboards import main_keyboard
from rag.schemas import UserProfile


router = Router()

DB_PATH = Path(__file__).resolve().parent.parent / "bot.sqlite3"


def init_db():
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                business_stage TEXT,
                industry TEXT,
                tax_regime TEXT,
                experience TEXT,
                goal TEXT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                user_id INTEGER PRIMARY KEY,
                messages TEXT NOT NULL DEFAULT '[]'
            )
        """)


def get_profile(user_id: int) -> UserProfile | None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row

        row = connection.execute(
            "SELECT * FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    return UserProfile(
        business_stage=row["business_stage"],
        industry=row["industry"],
        tax_regime=row["tax_regime"],
        experience=row["experience"],
        goal=row["goal"],
    )


def save_profile(user_id: int, profile: UserProfile):
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO profiles (
                user_id, business_stage, industry,
                tax_regime, experience, goal
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                business_stage = excluded.business_stage,
                industry = excluded.industry,
                tax_regime = excluded.tax_regime,
                experience = excluded.experience,
                goal = excluded.goal
            """,
            (
                user_id,
                profile.business_stage,
                profile.industry,
                profile.tax_regime,
                profile.experience,
                profile.goal,
            ),
        )


def get_history(user_id: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT messages FROM chat_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return []

    try:
        messages = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(messages, list):
        return []

    return [
        item for item in messages
        if isinstance(item, dict)
        and item.get("role") in ("user", "assistant")
        and isinstance(item.get("text"), str)
    ][-12:]


def save_history(user_id: int, history: list[dict]):
    messages = history[-12:]

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO chat_history (user_id, messages)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                messages = excluded.messages
            """,
            (
                user_id,
                json.dumps(messages, ensure_ascii=False),
            ),
        )


def clear_history(user_id: int):
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "DELETE FROM chat_history WHERE user_id = ?",
            (user_id,),
        )


class ProfileForm(StatesGroup):
    stage = State()
    industry = State()
    tax = State()
    experience = State()
    goal = State()


def make_keyboard(options: list[str]):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=option)]
            for option in options
        ] + [[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


STAGES = {
    "💡 Только идея": "idea",
    "🚀 Бизнес уже запущен": "launched",
    "📈 Развиваю бизнес": "growing",
}

EXPERIENCE = {
    "🌱 Новичок": "novice",
    "📚 Есть небольшой опыт": "some",
    "🏆 Опытный предприниматель": "experienced",
}

TAXES = {
    "УСН": "УСН",
    "ПСН (патент)": "ПСН",
    "НПД (самозанятость)": "НПД",
    "ОСНО": "ОСНО",
    "ЕСХН": "ЕСХН",
    "🤷 Пока не знаю": None,
}


async def begin_profile(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ProfileForm.stage)

    await message.answer(
        "👤 Давай познакомимся с твоим бизнесом!\n\n"
        "1/5. На какой стадии находится твой бизнес?",
        reply_markup=make_keyboard(list(STAGES)),
    )


async def open_profile(message: Message, state: FSMContext):
    if not message.from_user:
        return

    profile = get_profile(message.from_user.id)

    if profile is None:
        await begin_profile(message, state)
        return

    stages = {
        "idea": "Только идея",
        "launched": "Бизнес запущен",
        "growing": "Развивающийся бизнес",
    }

    experience_labels = {
        "novice": "Новичок",
        "some": "Есть небольшой опыт",
        "experienced": "Опытный предприниматель",
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить профиль",
                    callback_data="profile:edit",
                )
            ]
        ]
    )

    await message.answer(
        "👤 Твой бизнес-профиль\n\n"
        f"🚀 Стадия: {stages.get(profile.business_stage, 'Не указана')}\n"
        f"🏢 Сфера: {profile.industry or 'Не указана'}\n"
        f"💰 Налоги: {profile.tax_regime or 'Пока не знаю'}\n"
        f"📚 Опыт: {experience_labels.get(profile.experience, 'Не указан')}\n"
        f"🎯 Цель: {profile.goal or 'Не указана'}\n\n"
        "Эту информацию я учитываю при подборе материалов.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "profile:edit")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if isinstance(callback.message, Message):
        await begin_profile(callback.message, state)


@router.message(ProfileForm.stage)
async def process_stage(message: Message, state: FSMContext):
    if message.text not in STAGES:
        await message.answer("Выбери один из вариантов на кнопках 👇")
        return

    await state.update_data(
        business_stage=STAGES[message.text]
    )
    await state.set_state(ProfileForm.industry)

    await message.answer(
        "2/5. В какой сфере твой бизнес?\n\n"
        "Например: кофейня, магазин одежды, IT, "
        "салон красоты или онлайн-образование.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ProfileForm.industry)
async def process_industry(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("Напиши название сферы бизнеса.")
        return

    await state.update_data(
        industry=message.text.strip()[:150]
    )
    await state.set_state(ProfileForm.tax)

    await message.answer(
        "3/5. Какую систему налогообложения используешь?",
        reply_markup=make_keyboard(list(TAXES)),
    )


@router.message(ProfileForm.tax)
async def process_tax(message: Message, state: FSMContext):
    if message.text not in TAXES:
        await message.answer("Выбери вариант на кнопках 👇")
        return

    await state.update_data(
        tax_regime=TAXES[message.text]
    )
    await state.set_state(ProfileForm.experience)

    await message.answer(
        "4/5. Какой у тебя опыт в предпринимательстве?",
        reply_markup=make_keyboard(list(EXPERIENCE)),
    )


@router.message(ProfileForm.experience)
async def process_experience(message: Message, state: FSMContext):
    if message.text not in EXPERIENCE:
        await message.answer("Выбери вариант на кнопках 👇")
        return

    await state.update_data(
        experience=EXPERIENCE[message.text]
    )
    await state.set_state(ProfileForm.goal)

    await message.answer(
        "5/5. Какая у тебя главная бизнес-цель сейчас?\n\n"
        "Например:\n"
        "• Открыть первую кофейню\n"
        "• Найти первых клиентов\n"
        "• Увеличить продажи\n"
        "• Разобраться с налогами",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ProfileForm.goal)
async def process_goal(message: Message, state: FSMContext):
    if not message.from_user:
        return

    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Опиши свою цель чуть подробнее.")
        return

    await state.update_data(
        goal=message.text.strip()[:500]
    )

    data = await state.get_data()

    profile = UserProfile(
        business_stage=data["business_stage"],
        industry=data["industry"],
        tax_regime=data["tax_regime"],
        experience=data["experience"],
        goal=data["goal"],
    )

    save_profile(message.from_user.id, profile)

    await state.clear()

    await message.answer(
        "🎉 Готово! Твой бизнес-профиль сохранён.\n\n"
        "Теперь я буду учитывать его при ответах "
        "и подборе материалов.\n\n"
        "Попробуй задать вопрос о своём бизнесе! 💬",
        reply_markup=main_keyboard,
    )
