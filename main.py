# main.py
import os
import re
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.types import CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.filters import StateFilter
# main.py (импортируй)
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

import tempfile
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from aiogram.types import FSInputFile

from db import init_db, add_entry, recent_summary, last_n_entries, timeseries_daily, add_body_params, last_n_body_params

# --- Шаблонные категории и упражнения ---
CATEGORIES = {
    "arms": "💪 Руки",
    "legs": "🦵 Ноги",
    "core": "🧩 Пресс",
    "backm": "🦴 Спина",
    "cardio": "🏃 Кардио",
}

# Для компактного callback_data используем короткие ID
# Для компактного callback_data используем короткие ID
EXERCISES_BY_CAT = {
    "legs": [
        ("leg_press", "Жим ногами"),
        ("abductor", "Сведение бедер"),
        ("adductor", "Разведение бедер"),
        ("leg_curl", "Сгибание ног"),
        ("leg_ext", "Разгибание ног"),
        ("multi_hip", "Отведение назад"),
    ],
    "arms": [
        ("hammer_curl", "Молотковый подъём на бицепс"),
        ("overhead_ext", "Разгибание рук из-за головы"),
        ("db_press", "Жим гантелей стоя"),
        ("db_fly", "Разведение гантелей"),
        ("db_row", "Тяга гантели к поясу в наклоне"),
    ],
    "backm": [
        ("gravitron", "Гравитрон"),
        ("seated_row", "Горизонтальная тяга в рычажном тренажёре"),
    ],
    "cardio": [
        ("run", "Бег"),
        ("stair", "Лестница"),
    ],
    "core": [
        ("crunch", "Скручивания"),
        ("bicycle", "Велосипед"),
        ("knee_crunch", "Скрутка к колену"),
        ("russian_twist", "Русские скручивания"),
    ],
}

# Быстрый индекс id -> название
EX_INDEX = {eid: title for pairs in EXERCISES_BY_CAT.values() for eid, title in pairs}


def kb_categories_inline() -> InlineKeyboardMarkup:
    # Кнопки категорий + «Другое»
    rows = []
    row = []
    for cid, label in CATEGORIES.items():
        row.append(InlineKeyboardButton(text=label, callback_data=f"cat:{cid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✍️ Другое", callback_data="ex:other")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_exercises_inline(cat_id: str) -> InlineKeyboardMarkup:
    pairs = EXERCISES_BY_CAT.get(cat_id, [])
    rows = []
    row = []
    for eid, title in pairs:
        row.append(InlineKeyboardButton(text=title, callback_data=f"ex:{eid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="cat:back"),
        InlineKeyboardButton(text="✍️ Другое", callback_data="ex:other"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class AddEntry(StatesGroup):
    waiting_for_exercise = State()
    waiting_for_reps = State()
    waiting_for_weight = State()


class ProgressInput(StatesGroup):
    waiting = State()


class ChartInput(StatesGroup):
    waiting = State()


router = Router()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить подход", callback_data="add")],
        [InlineKeyboardButton(text="📈 Прогресс", callback_data="progress")],
        [InlineKeyboardButton(text="🖼️ График", callback_data="chart")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])


def reply_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить подход")],
            [KeyboardButton(text="📈 Прогресс"), KeyboardButton(text="🖼️ График")],
            [KeyboardButton(text="📏 Параметры тела")],  # ← новая кнопка
            [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="🔽 Скрыть меню")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или введите команду…"
    )


def kb_body_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 Рост/вес", callback_data="body:metrics")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="body:stats")],
    ])


class BodyInput(StatesGroup):
    waiting = State()


@router.message(F.text == "📏 Параметры тела")
async def kb_body(message: Message):
    await message.answer(
        "Выбери действие:",
        reply_markup=kb_body_menu()
    )


@router.callback_query(F.data == "body:stats")
async def cb_body_stats(call: CallbackQuery):
    user_id = call.from_user.id
    rows = await last_n_body_params(user_id, n=10)

    if not rows:
        await call.message.answer("Замеров пока нет. Добавь через 📐 Рост/вес.", reply_markup=reply_main_kb())
        await call.answer()
        return

    lines = ["📊 История замеров (последние 10):"]
    for ts, h, w in rows:
        when = ts.split("T")[0] + " " + ts.split("T")[1][:5]
        h_txt = f"{h:g} см" if h is not None else "—"
        w_txt = f"{w:g} кг" if w is not None else "—"
        lines.append(f"• {when}: {h_txt}, {w_txt}")

    await call.message.answer("\n".join(lines), reply_markup=reply_main_kb())
    await call.answer()


@router.callback_query(F.data == "body:metrics")
async def cb_body_metrics(call: CallbackQuery, state: FSMContext):
    # Входим в режим ожидания ввода роста/веса
    await state.set_state(BodyInput.waiting)

    # Покажем последний замер, если есть
    rows = await last_n_body_params(call.from_user.id, n=1)
    hint = ""
    if rows:
        ts, h, w = rows[0]
        when = ts.split("T")[0] + " " + ts.split("T")[1][:5]
        h_txt = f"{h:g} см" if h is not None else "—"
        w_txt = f"{w:g} кг" if w is not None else "—"
        hint = f"\nПоследний замер: {when}: {h_txt}, {w_txt}"

    await call.message.answer(
        "Введи рост и вес через пробел (например: 170 65). "
        "Можно писать «170см 65кг», «170, 65» и т.п." + hint
    )
    await call.answer()


@router.message(BodyInput.waiting)
async def body_metrics_input(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    # вытащим первые ДВА числа из строки
    nums = re.findall(r"[-+]?\d+(?:[.,]\d+)?", text)
    if len(nums) < 2:
        await message.answer("Нужно два числа: рост (см) и вес (кг). Пример: 170 65")
        return
    try:
        height = float(nums[0].replace(",", "."))
        weight = float(nums[1].replace(",", "."))
    except ValueError:
        await message.answer("Не получилось распознать числа. Пример: 170 65")
        return

    await add_body_params(message.from_user.id, height, weight)
    await state.clear()
    await message.answer(f"Записал: рост {height:g} см, вес {weight:g} кг ✅", reply_markup=reply_main_kb())


# main.py — где-нибудь рядом с main_menu()
async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="menu", description="Открыть меню"),
        BotCommand(command="faq", description="Помощь"),
        BotCommand(command="add", description="Добавить подход"),
        BotCommand(command="progress", description="Сводка по прогрессу"),
        BotCommand(command="chart", description="График упражнения"),
        BotCommand(command="help", description="Подсказки по использованию"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я бот для учёта тренировок.\nВыбери действие 👇",
        reply_markup=reply_main_kb()  # показываем клавиатуру с кнопками
    )
    # при желании можно дополнительно прислать инлайн-меню:
    await message.answer("Или воспользуйся инлайн-меню:", reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Меню открыто 👇", reply_markup=reply_main_kb())


@router.message(Command("faq"))
async def cmd_faq(message: Message):
    await cmd_help(message)


# Нажали "➕ Добавить подход"
@router.message(F.text == "➕ Добавить подход")
async def kb_add(message: Message, state: FSMContext):
    await cmd_add(message, state)


# Нажали "📈 Прогресс" — подскажем формат и оставим клавиатуру открытой
# Нажали "📈 Прогресс" — переходим в состояние ожидания аргументов (без /)
@router.message(F.text == "📈 Прогресс")
async def kb_progress(message: Message, state: FSMContext):
    await state.set_state(ProgressInput.waiting)
    await message.answer(
        "Введи: <упражнение> [дней]\nНапример: приседания 7\n(Напиши «отмена» чтобы выйти)",
        reply_markup=reply_main_kb()
    )


# Нажали "🖼️ График" — переходим в состояние ожидания аргументов (без /)
@router.message(F.text == "🖼️ График")
async def kb_chart(message: Message, state: FSMContext):
    await state.set_state(ChartInput.waiting)
    await message.answer(
        "Введи: <упражнение> [дней]\nНапример: приседания 30\n(Напиши «отмена» чтобы выйти)",
        reply_markup=reply_main_kb()
    )


# Пользователь отвечает после "📈 Прогресс"
@router.message(ProgressInput.waiting)
async def progress_input(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in {"отмена", "cancel", "назад"}:
        await state.clear()
        await message.answer("Окей, вышли из режима прогресса.", reply_markup=reply_main_kb())
        return

    # парсим "<упражнение> [дней]"
    parts = text.split()
    days = 7
    if parts and parts[-1].isdigit():
        days = int(parts[-1])
        exercise = " ".join(parts[:-1]).strip() or None
    else:
        exercise = " ".join(parts).strip() or None

    rows = await recent_summary(message.from_user.id, exercise, days)
    await state.clear()

    if not rows:
        await message.answer("Данных пока нет. Добавь подход через /add или кнопку «➕ Добавить подход».",
                             reply_markup=reply_main_kb())
        return

    lines = [f"Итог за {days} дн.:"]
    for ex, total_reps, sets in rows:
        lines.append(f"• {ex}: {total_reps} повторений в {sets} подходах")

    if exercise:
        last = await last_n_entries(message.from_user.id, exercise, n=10)
        if last:
            lines.append("\nПоследние подходы:")
            for ts, reps, weight in last:
                when = ts.split('T')[0] + " " + ts.split('T')[1][:5]
                wt = f", {weight} кг" if weight is not None else ""
                lines.append(f"• {when}: {reps} повт{wt}")

    await message.answer("\n".join(lines), reply_markup=reply_main_kb())


# Пользователь отвечает после "🖼️ График"
@router.message(ChartInput.waiting)
async def chart_input(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in {"отмена", "cancel", "назад"}:
        await state.clear()
        await message.answer("Окей, вышли из режима графика.", reply_markup=reply_main_kb())
        return

    parts = text.split()
    days = 30
    if parts and parts[-1].isdigit():
        days = int(parts[-1])
        exercise = " ".join(parts[:-1]).strip()
    else:
        exercise = " ".join(parts).strip()

    if not exercise:
        await message.answer("Нужно указать упражнение, например: приседания 30",
                             reply_markup=reply_main_kb())
        return

    rows = await timeseries_daily(message.from_user.id, exercise, days)
    await state.clear()

    if not rows:
        await message.answer("Данных пока нет для этого упражнения за выбранный период.",
                             reply_markup=reply_main_kb())
        return

    # — ниже твоя же логика построения графика —
    import tempfile, os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from aiogram.types import FSInputFile

    dates = [r[0] for r in rows]
    reps = [int(r[1]) if r[1] is not None else 0 for r in rows]
    volume = [float(r[2]) if r[2] is not None else 0.0 for r in rows]
    has_volume = any(v > 0 for v in volume)

    fig = plt.figure(figsize=(8, 4.5), dpi=150)
    ax1 = plt.gca()
    ax1.plot(dates, reps, marker="o", label="Повторы/день")
    ax1.set_xlabel("Дата")
    ax1.set_ylabel("Повторы")
    if has_volume:
        ax2 = ax1.twinx()
        ax2.plot(dates, volume, marker="s", linestyle="--", label="Объём (повт×вес)")
        ax2.set_ylabel("Объём")
    plt.title(f"{exercise.title()}: прогресс за {days} дн.")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    tmp_path = os.path.join(tempfile.gettempdir(), f"chart_{message.from_user.id}.png")
    plt.savefig(tmp_path)
    plt.close(fig)

    await message.answer_photo(
        FSInputFile(tmp_path),
        caption=f"{exercise.title()} — {days} дн.\n"
                f"Линия 1: повторы/день" + (", линия 2: объём (повт×вес)" if has_volume else ""),
        reply_markup=reply_main_kb()
    )


# Нажали "❓ Помощь"
@router.message(F.text == "❓ Помощь")
async def kb_help(message: Message):
    await cmd_help(message)


# Скрыть клавиатуру
@router.message(F.text == "🔽 Скрыть меню")
async def kb_hide(message: Message):
    await message.answer("Меню скрыто. Напиши /menu чтобы вернуть.", reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == "add")
async def cb_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddEntry.waiting_for_exercise)
    await call.message.answer(
        "Выбери категорию упражнения или нажми «Другое» и введи название вручную:",
        reply_markup=kb_categories_inline()
    )
    await call.answer()


# Нажали на категорию: cat:<id> или cat:back
@router.callback_query(F.data.startswith("cat:"))
async def cb_choose_category(call: CallbackQuery, state: FSMContext):
    _, cat_id = call.data.split(":", 1)

    if cat_id == "back":
        # Вернуться к списку категорий
        await call.message.edit_text(
            "Выбери категорию упражнения или нажми «Другое»:",
            reply_markup=kb_categories_inline()
        )
        await call.answer()
        return

    if cat_id not in CATEGORIES:
        await call.answer("Неизвестная категория", show_alert=False)
        return

    # Показать упражнения выбранной категории
    await call.message.edit_text(
        f"Категория: {CATEGORIES[cat_id]}\nВыбери упражнение:",
        reply_markup=kb_exercises_inline(cat_id)
    )
    await call.answer()


# Нажали на упражнение: ex:<id> или ex:other
@router.callback_query(F.data.startswith("ex:"))
async def cb_choose_exercise(call: CallbackQuery, state: FSMContext):
    _, ex_id = call.data.split(":", 1)

    if ex_id == "other":
        # Оставляем состояние ожидания упражнения — ждём текст от пользователя
        await call.message.answer("Введи название упражнения текстом (например: отжимания).")
        await call.answer()
        return

    title = EX_INDEX.get(ex_id)
    if not title:
        await call.answer("Неизвестное упражнение", show_alert=False)
        return

    # Сохраняем выбранное упражнение и переходим к повторам
    await state.update_data(exercise=title)
    await state.set_state(AddEntry.waiting_for_reps)
    await call.message.answer(f"Выбрано упражнение: {title}\nСколько повторений? (целое число)")
    await call.answer()


@router.callback_query(F.data == "progress")
async def cb_progress(call: CallbackQuery, state: FSMContext):
    await state.set_state(ProgressInput.waiting)
    await call.message.answer(
        "Введи: <упражнение> [дней]\nНапример: приседания 7\n(Напиши «отмена» чтобы выйти)",
        reply_markup=reply_main_kb()
    )
    await call.answer()


@router.callback_query(F.data == "chart")
async def cb_chart(call: CallbackQuery, state: FSMContext):
    await state.set_state(ChartInput.waiting)
    await call.message.answer(
        "Введи: <упражнение> [дней]\nНапример: приседания 30\n(Напиши «отмена» чтобы выйти)",
        reply_markup=reply_main_kb()
    )
    await call.answer()


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await cmd_help(call.message)  # переиспользуем существующий хэндлер
    await call.answer()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Как пользоваться:\n"
        "• /add — пошагово: упражнение → повторы → (опц.) вес.\n"
        "• Быстрый ввод: отправь 'отжимания 15' или 'жим лёжа 8 40'.\n"
        "• /progress [упражнение] [дней] — напр.: /progress отжимания 30.\n"
        "• /chart <упражнение> [дней] — PNG-график повторов и объёма. Пример: /chart приседания 30."
    )


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddEntry.waiting_for_exercise)
    await message.answer(
        "Выбери категорию упражнения или нажми «Другое» и введи название вручную:",
        reply_markup=kb_categories_inline()
    )
    # Можно дополнительно подсказать про быстрый ввод:
    await message.answer("Лайфхак: можно сразу прислать, например: «приседания 20 60» — я всё запишу.")


@router.message(AddEntry.waiting_for_exercise)
async def add_exercise(message: Message, state: FSMContext):
    text = message.text.strip()

    # Попробовать "быстрый ввод": "<exercise> <reps> [weight]"
    m = re.match(r"^([^\d\n]+?)\s+(\d+)(?:\s+([\d.,]+))?$", text)
    if m:
        exercise = m.group(1).strip()
        reps = int(m.group(2))
        weight = None
        if m.group(3):
            try:
                weight = float(m.group(3).replace(",", "."))
            except ValueError:
                weight = None

        await add_entry(message.from_user.id, exercise, reps, weight)
        await state.clear()
        await message.answer(
            f"Записал как быстрый ввод ✅\n"
            f"Посмотреть прогресс: /progress или /progress {exercise} 7",
            reply_markup=reply_main_kb()
        )

        return

    # Обычный пошаговый сценарий
    if len(text) < 2:
        await message.answer("Название слишком короткое. Попробуй ещё раз.")
        return
    await state.update_data(exercise=text)
    await state.set_state(AddEntry.waiting_for_reps)
    await message.answer("Сколько повторений? (целое число)")


@router.message(AddEntry.waiting_for_reps, F.text.regexp(r"^\d+$"))
async def add_reps(message: Message, state: FSMContext):
    reps = int(message.text)
    await state.update_data(reps=reps)
    await state.set_state(AddEntry.waiting_for_weight)
    await message.answer("Вес? (кг, можно 0 или напиши 'пропустить')")


@router.message(AddEntry.waiting_for_reps)
async def add_reps_invalid(message: Message, state: FSMContext):
    await message.answer("Нужно целое число повторений, например 12.")


@router.message(AddEntry.waiting_for_weight)
async def add_weight_skip_or_value(message: Message, state: FSMContext):
    text_raw = message.text.strip()
    text = text_raw.lower()

    # быстрые варианты пропуска
    if text in {"пропустить", "skip"}:
        data = await state.get_data()
        await add_entry(message.from_user.id, data["exercise"], data["reps"], None)
        await state.clear()
        await message.answer("Готово! Записал подход ✅", reply_markup=reply_main_kb())
        return

    # Разрешим «0» как валидный вес
    if text == "0":
        data = await state.get_data()
        await add_entry(message.from_user.id, data["exercise"], data["reps"], 0.0)
        await state.clear()
        await message.answer("Готово! Записал подход ✅", reply_markup=reply_main_kb())
        return

    # Пытаемся вытащить первое число из строки: 7, 7.5, 7,5, "+7", "~7", "7 кг", "7 -", "7-10" и т.п.
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not m:
        await message.answer("Вес должен быть числом (например 42.5) или напиши 'пропустить'.")
        return

    try:
        weight = float(m.group(0).replace(",", "."))
    except ValueError:
        await message.answer("Вес должен быть числом (например 42.5) или напиши 'пропустить'.")
        return

    data = await state.get_data()
    await add_entry(message.from_user.id, data["exercise"], data["reps"], weight)
    await state.clear()
    await message.answer("Готово! Записал подход ✅", reply_markup=reply_main_kb())


@router.message(Command("progress"))
async def cmd_progress(message: Message):
    args = message.text.split()[1:]
    exercise = None
    days = 7
    if args:
        if args[-1].isdigit():
            days = int(args[-1])
            if len(args) > 1:
                exercise = " ".join(args[:-1])
        else:
            exercise = " ".join(args)
    rows = await recent_summary(message.from_user.id, exercise, days)
    if not rows:
        await message.answer("Данных пока нет. Добавь подход через /add.")
        return
    lines = [f"Итог за {days} дн.:"]
    for ex, total_reps, sets in rows:
        lines.append(f"• {ex}: {total_reps} повторений в {sets} подходах")
    if exercise:
        last = await last_n_entries(message.from_user.id, exercise, n=10)
        if last:
            lines.append("\nПоследние подходы:")
            for ts, reps, weight in last:
                when = ts.split('T')[0] + " " + ts.split('T')[1][:5]
                wt = f", {weight} кг" if weight is not None else ""
                lines.append(f"• {when}: {reps} повт{wt}")
    await message.answer("\n".join(lines))


@router.message(Command("chart"))
async def cmd_chart(message: Message):
    # Разбор аргументов: /chart <упражнение> [дней]
    args = message.text.split()[1:]
    if not args:
        await message.answer("Использование: /chart <упражнение> [дней]\nНапример: /chart приседания 30")
        return

    days = 30
    if args[-1].isdigit():
        days = int(args[-1])
        exercise = " ".join(args[:-1]).strip()
    else:
        exercise = " ".join(args).strip()

    if not exercise:
        await message.answer("Нужно указать упражнение. Пример: /chart приседания 30")
        return

    rows = await timeseries_daily(message.from_user.id, exercise, days)
    if not rows:
        await message.answer("Данных пока нет для этого упражнения за выбранный период.")
        return

    dates = [r[0] for r in rows]  # 'YYYY-MM-DD'
    reps = [int(r[1]) if r[1] is not None else 0 for r in rows]
    volume = [float(r[2]) if r[2] is not None else 0.0 for r in rows]
    has_volume = any(v > 0 for v in volume)

    # Рисуем график
    fig = plt.figure(figsize=(8, 4.5), dpi=150)
    ax1 = plt.gca()
    ax1.plot(dates, reps, marker="o", label="Повторы/день")
    ax1.set_xlabel("Дата")
    ax1.set_ylabel("Повторы")

    if has_volume:
        ax2 = ax1.twinx()
        ax2.plot(dates, volume, marker="s", linestyle="--", label="Объём (повт×вес)")
        ax2.set_ylabel("Объём")

    plt.title(f"{exercise.title()}: прогресс за {days} дн.")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    tmp_path = os.path.join(tempfile.gettempdir(), f"chart_{message.from_user.id}.png")
    plt.savefig(tmp_path)
    plt.close(fig)

    await message.answer_photo(FSInputFile(tmp_path),
                               caption=f"{exercise.title()} — {days} дн.\n"
                                       f"Линия 1: повторы/день"
                                       + (", линия 2: объём (повт×вес)" if has_volume else ""))


@router.message(
    StateFilter(None),  # ← быстрый ввод только когда нет активного состояния
    F.text.regexp(r"^(?!/)([^\d\n]+?)\s+(\d+)(?:\s+([\d.,]+))?$")
)
async def quick_add(message: Message):
    text = message.text.strip()
    if text.startswith("/"):  # дополнительная страховка
        return

    m = re.match(r"^(?!/)([^\d\n]+?)\s+(\d+)(?:\s+([\d.,]+))?$", text)
    exercise = m.group(1).strip()
    reps = int(m.group(2))
    weight = None
    if m.group(3):
        try:
            weight = float(m.group(3).replace(",", "."))
        except ValueError:
            weight = None
    await add_entry(message.from_user.id, exercise, reps, weight)
    await message.answer("Записал! Используй /progress чтобы посмотреть динамику.", reply_markup=reply_main_kb())


async def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не найден в .env")
    logging.basicConfig(level=logging.INFO)
    await init_db()
    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # <— ВАЖНО: регистрируем команды
    await setup_bot_commands(bot)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
