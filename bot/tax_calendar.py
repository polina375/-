
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.profile import get_profile


router = Router()

DB_PATH = Path(__file__).resolve().parent.parent / "bot.sqlite3"
TIMEZONE = ZoneInfo("Europe/Moscow")

FNS_URLS = {
    "usn": "https://www.nalog.gov.ru/rn77/ip/ip_pay_taxes/usn/",
    "npd": "https://www.nalog.gov.ru/rn77/taxation/princtax/",
    "psn": "https://www.nalog.gov.ru/rn77/ip/ip_pay_taxes/patent/",
    "eshn": "https://www.nalog.gov.ru/",
    "osno": "https://www.nalog.gov.ru/",
}

REGIME_NAMES = {
    "usn": "УСН",
    "npd": "НПД",
    "psn": "Патент (ПСН)",
    "eshn": "ЕСХН",
    "osno": "ОСНО",
}


def detect_regime(user_id):
    profile = get_profile(user_id)

    if not profile or not profile.tax_regime:
        return None

    value = profile.tax_regime.upper()

    if "УСН" in value:
        return "usn"
    if "НПД" in value or "САМОЗАН" in value:
        return "npd"
    if "ПСН" in value or "ПАТЕНТ" in value:
        return "psn"
    if "ЕСХН" in value:
        return "eshn"
    if "ОСНО" in value:
        return "osno"

    return None


def select_regime_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=name,
                    callback_data=f"tax:show:{code}",
                )
            ]
            for code, name in REGIME_NAMES.items()
        ]
    )


def build_events(regime):
    now = datetime.now(TIMEZONE)
    events = []

    for year in range(now.year, now.year + 3):

        if regime == "usn":
            events.extend([
                (
                    datetime(year, 4, 28, tzinfo=TIMEZONE),
                    "УСН — аванс за I квартал",
                ),
                (
                    datetime(year, 7, 28, tzinfo=TIMEZONE),
                    "УСН — аванс за полугодие",
                ),
                (
                    datetime(year, 10, 28, tzinfo=TIMEZONE),
                    "УСН — аванс за 9 месяцев",
                ),
            ])

        elif regime == "npd":
            for month in range(1, 13):
                events.append((
                    datetime(year, month, 28, tzinfo=TIMEZONE),
                    "НПД — ежемесячная уплата налога",
                ))

        elif regime == "eshn":
            events.extend([
                (
                    datetime(year, 3, 28, tzinfo=TIMEZONE),
                    "ЕСХН — годовой платёж",
                ),
                (
                    datetime(year, 7, 28, tzinfo=TIMEZONE),
                    "ЕСХН — аванс за полугодие",
                ),
            ])

    # Показываем только будущие базовые даты.
    events = [
        event for event in events
        if event[0].date() >= now.date()
    ]

    return sorted(events, key=lambda item: item[0])


def build_calendar(regime):
    title = REGIME_NAMES[regime]

    lines = [
        f"🧾 Налоговый календарь: {title}\n",
    ]

    buttons = []

    if regime == "psn":
        lines.append(
            "📌 Сроки оплаты патента зависят "
            "от даты начала и окончания его действия.\n\n"
            "Для патента менее 6 месяцев налог обычно "
            "уплачивается до окончания патента.\n\n"
            "Для патента от 6 месяцев предусмотрены "
            "платежи в размере 1/3 и 2/3 стоимости.\n\n"
            "Создай персональное напоминание "
            "по датам своего патента."
        )

    elif regime == "osno":
        lines.append(
            "На ОСНО несколько видов налогов "
            "и отчётности.\n\n"
            "Конкретные сроки зависят от того, "
            "ИП это или организация, наличия "
            "сотрудников и других условий.\n\n"
            "Для точного календаря нужны "
            "дополнительные данные."
        )

    else:
        events = build_events(regime)[:5]

        if not events:
            lines.append(
                "Ближайшие события пока не найдены."
            )

        for index, (date, event_title) in enumerate(
            events, start=1
        ):
            lines.append(
                f"{index}. {event_title}\n"
                f"📅 {date.strftime('%d.%m.%Y')}\n"
            )

            buttons.append([
                InlineKeyboardButton(
                    text=f"🔔 Напомнить о событии №{index}",
                    callback_data=(
                        f"tax:add:{regime}:"
                        f"{date.strftime('%Y%m%d')}"
                    ),
                )
            ])

        if regime == "usn":
            lines.append(
                "ℹ️ Здесь показаны авансовые платежи. "
                "Годовые сроки декларации и налога "
                "различаются для ИП и организаций."
            )

        lines.append(
            "\n⚠️ Указаны базовые даты. "
            "Если срок выпадает на выходной или "
            "праздник, он может переноситься. "
            "Проверяй окончательную дату на сайте ФНС."
        )

    buttons.append([
        InlineKeyboardButton(
            text="🌐 Проверить сроки на сайте ФНС",
            url=FNS_URLS[regime],
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="🔄 Другой налоговый режим",
            callback_data="tax:choose",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ К напоминаниям",
            callback_data="rem:menu",
        )
    ])

    return (
        "\n".join(lines),
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def show_tax_calendar(message, user_id):
    regime = detect_regime(user_id)

    if regime is None:
        await message.answer(
            "🧾 Налоговый календарь\n\n"
            "Выбери налоговый режим.\n"
            "Для автоматического выбора "
            "заполни бизнес-профиль.",
            reply_markup=select_regime_keyboard(),
        )
        return

    text, markup = build_calendar(regime)

    await message.answer(
        text,
        reply_markup=markup,
    )


@router.message(Command("taxcalendar"))
async def tax_calendar_command(message: Message):
    if message.from_user:
        await show_tax_calendar(
            message,
            message.from_user.id,
        )


@router.callback_query(F.data == "tax:menu")
async def tax_calendar_menu(callback: CallbackQuery):
    await callback.answer()

    if isinstance(callback.message, Message):
        await show_tax_calendar(
            callback.message,
            callback.from_user.id,
        )


@router.callback_query(F.data == "tax:choose")
async def choose_tax_regime(callback: CallbackQuery):
    await callback.answer()

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "🧾 Выбери налоговый режим.\n\n"
            "Это не изменит твой бизнес-профиль.",
            reply_markup=select_regime_keyboard(),
        )


@router.callback_query(F.data.startswith("tax:show:"))
async def show_selected_regime(callback: CallbackQuery):
    await callback.answer()

    regime = callback.data.split(":")[-1]

    if regime not in REGIME_NAMES:
        return

    text, markup = build_calendar(regime)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=markup,
        )


@router.callback_query(F.data.startswith("tax:add:"))
async def add_tax_reminder(callback: CallbackQuery):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    try:
        _, _, regime, date_string = callback.data.split(":")
        event_date = datetime.strptime(
            date_string, "%Y%m%d"
        ).replace(tzinfo=TIMEZONE)
    except (ValueError, AttributeError):
        await callback.answer(
            "Некорректная дата.",
            show_alert=True,
        )
        return

    if regime not in REGIME_NAMES:
        await callback.answer()
        return

    # Проверяем, что событие действительно
    # существует в нашем календаре.
    matching = [
        (date, title)
        for date, title in build_events(regime)
        if date.date() == event_date.date()
    ]

    if not matching:
        await callback.answer(
            "Событие уже неактуально.",
            show_alert=True,
        )
        return

    event_title = matching[0][1]

    now = datetime.now(TIMEZONE)

    # По умолчанию напоминаем за 3 дня, в 10:00.
    remind_at = (
        event_date - timedelta(days=3)
    ).replace(hour=10, minute=0)

    if remind_at <= now:
        # Если до события меньше трёх дней,
        # отправим напоминание через минуту.
        remind_at = now + timedelta(minutes=1)

    reminder_text = (
        f"Налоговый календарь: {event_title}. "
        f"Базовая дата — "
        f"{event_date.strftime('%d.%m.%Y')}. "
        "Проверь перенос срока на сайте ФНС."
    )

    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute(
            """
            SELECT id FROM reminders
            WHERE user_id = ?
              AND text = ?
              AND sent = 0
            """,
            (
                callback.from_user.id,
                reminder_text,
            ),
        ).fetchone()

        if existing:
            await callback.answer(
                "Напоминание уже создано!",
                show_alert=True,
            )
            return

        conn.execute(
            """
            INSERT INTO reminders (
                user_id, text, remind_at,
                frequency, repeat_day
            )
            VALUES (?, ?, ?, 'once', NULL)
            """,
            (
                callback.from_user.id,
                reminder_text,
                remind_at.isoformat(),
            ),
        )

    await callback.answer(
        "Напоминание добавлено!",
        show_alert=True,
    )

    await callback.message.answer(
        "✅ Налоговое напоминание создано!\n\n"
        f"🧾 {event_title}\n"
        f"🔔 Уведомление: "
        f"{remind_at.strftime('%d.%m.%Y %H:%M')} МСК\n\n"
        "Посмотреть его можно в разделе "
        "«📋 Мои напоминания»."
    )
