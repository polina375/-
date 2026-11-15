
import asyncio
import logging
import os
from contextlib import suppress

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from dotenv import load_dotenv

from bot.keyboards import main_keyboard

from bot.profile import (
    router as profile_router,
    init_db,
    get_profile,
    open_profile,
    get_history,
    save_history,
    clear_history,
)

from bot.reminders import (
    router as reminders_router,
    init_reminders_db,
    open_reminders,
    reminder_worker,
)

from rag.assistant import answer
from rag.schemas import Status, UserProfile


load_dotenv(".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()

user_locks: dict[int, asyncio.Lock] = {}


@dp.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "Привет! 👋 Я АльфаБро — твой помощник "
        "в мире предпринимательства!\n\n"
        "Помогу разобраться в бизнес-вопросах, "
        "найти полезные материалы и не забыть "
        "о важных делах.\n\n"
        "Выбирай, с чего начнём 👇",
        reply_markup=main_keyboard,
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "📚 Чем я могу помочь?\n\n"
        "💬 Задать вопрос — помощь с бизнес-вопросами\n"
        "📚 Материалы — статьи и курсы\n"
        "👤 Мой профиль — информация о бизнесе\n"
        "🔔 Напоминания — важные задачи и сроки\n\n"
        "Доступные команды:\n"
        "/start — главное меню\n"
        "/help — помощь\n"
        "/clear — очистить историю диалога\n"
        "/newreminder — создать напоминание\n"
        "/myreminders — мои напоминания\n"
        "/cancel — отменить текущее действие",
        reply_markup=main_keyboard,
    )


@dp.message(Command("clear"))
async def clear_handler(message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    lock = user_locks.get(user_id)

    if lock and lock.locked():
        await message.answer(
            "⏳ Дождись завершения текущего ответа, "
            "а затем очисти историю."
        )
        return

    try:
        clear_history(user_id)
    except Exception:
        logging.exception(
            "Ошибка очистки истории пользователя %s",
            user_id,
        )
        await message.answer(
            "😔 Не удалось очистить историю. "
            "Попробуй ещё раз."
        )
        return

    await message.answer(
        "🧹 История диалога очищена.\n"
        "Можешь задать новый вопрос."
    )


@dp.message(Command("cancel"))
@dp.message(F.text == "❌ Отмена")
async def cancel_handler(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "Действие отменено.\n"
        "Возвращаемся в главное меню 👇",
        reply_markup=main_keyboard,
    )


@dp.message(
    F.text == "💬 Задать вопрос",
    StateFilter(None),
)
async def question_handler(message: Message):
    await message.answer(
        "💬 Задай мне любой вопрос о бизнесе!\n\n"
        "Например:\n"
        "• Как открыть ИП?\n"
        "• Чем УСН отличается от патента?\n"
        "• Как привлечь первых клиентов?"
    )


@dp.message(
    F.text == "📚 Материалы",
    StateFilter(None),
)
async def materials_handler(message: Message):
    await message.answer(
        "📚 Я помогу подобрать материалы "
        "Альфа-Курса под твои задачи.\n\n"
        "Напиши, какая тема тебя интересует.\n\n"
        "Например:\n"
        "«Хочу разобраться в маркетинге "
        "для малого бизнеса».\n\n"
        "Я найду информацию и предложу "
        "подходящие статьи и курсы."
    )


@dp.message(
    F.text == "👤 Мой профиль",
    StateFilter(None),
)
async def profile_handler(
    message: Message,
    state: FSMContext,
):
    await open_profile(message, state)


@dp.message(
    F.text == "🔔 Напоминания",
    StateFilter(None),
)
async def reminders_handler(message: Message):
    await open_reminders(message)


@dp.message(
    F.text,
    StateFilter(None),
    ~F.text.startswith("/"),
)
async def ai_handler(message: Message):
    if not message.from_user or not message.text:
        return

    user_id = message.from_user.id
    question = message.text.strip()

    if not question:
        return

    lock = user_locks.setdefault(
        user_id,
        asyncio.Lock(),
    )

    if lock.locked():
        await message.answer(
            "⏳ Я ещё обрабатываю твой предыдущий вопрос.\n"
            "Подожди немного и отправь новый вопрос."
        )
        return

    async with lock:
        try:
            history = get_history(user_id)
            profile = get_profile(user_id) or UserProfile()

            await message.answer(
                "🔎 Ищу информацию в Альфа-Курсе..."
            )

            response = await asyncio.to_thread(
                answer,
                str(user_id),
                question,
                profile,
                history,
            )

            updated_history = history + [
                {
                    "role": "user",
                    "text": question,
                },
                {
                    "role": "assistant",
                    "text": response.text,
                },
            ]

            try:
                save_history(user_id, updated_history)
            except Exception:
                logging.exception(
                    "Ошибка сохранения истории пользователя %s",
                    user_id,
                )

            if response.status == Status.CLARIFY:
                prefix = "🤔 "
            elif response.status == Status.NO_ANSWER:
                prefix = "🔍 "
            else:
                prefix = "💡 "

            await message.answer(
                prefix + response.text[:4000]
            )

            if response.materials:
                lines = [
                    "📚 Рекомендую посмотреть:\n"
                ]

                for index, material in enumerate(
                    response.materials[:5],
                    start=1,
                ):
                    access = (
                        "💳 Платный"
                        if material.is_paid
                        else "🆓 Бесплатный"
                    )

                    lines.append(
                        f"{index}. {material.title}\n"
                        f"{access}\n"
                    )

                    if material.why:
                        lines.append(
                            f"💬 {material.why}\n"
                        )

                    if material.url:
                        lines.append(
                            f"🔗 {material.url}\n"
                        )

                    lines.append("")

                recommendations = "\n".join(lines)

                await message.answer(
                    recommendations[:4000]
                )

            if response.sources:
                sources_text = "\n".join(
                    f"• {source}"
                    for source in response.sources[:5]
                )

                await message.answer(
                    "📖 Источники из базы знаний:\n"
                    + sources_text[:3800]
                )

        except Exception:
            logging.exception(
                "Ошибка обработки вопроса пользователя %s",
                user_id,
            )

            with suppress(Exception):
                await message.answer(
                    "😔 Не удалось обработать запрос.\n\n"
                    "Возможно, сервис временно недоступен. "
                    "Попробуй повторить вопрос чуть позже."
                )


dp.include_router(profile_router)
dp.include_router(reminders_router)


async def main():
    if not TOKEN:
        raise RuntimeError(
            "Не найден TELEGRAM_BOT_TOKEN в .env"
        )

    init_db()
    init_reminders_db()

    bot = Bot(token=TOKEN)

    print("АльфаБро запускается без SOCKS5-прокси...")
    print("База данных SQLite подключена.")
    print("История диалогов сохраняется в SQLite.")
    print("Система напоминаний запускается...")

    reminder_task = asyncio.create_task(
        reminder_worker(bot)
    )

    try:
        await dp.start_polling(bot)

    finally:
        reminder_task.cancel()

        with suppress(asyncio.CancelledError):
            await reminder_task

        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
