import asyncio
import logging
import random
import re
import sys

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS, BOT_TOKEN
from database import (
    FACTIONS,
    add_xp_gold,
    complete_quest,
    create_quest,
    get_active_quests_for_faction,
    get_active_quests_for_user,
    get_all_active_quests,
    get_all_users,
    get_quest,
    get_user,
    get_users_by_faction,
    init_db,
    register_user,
    set_user_faction,
)

logging.basicConfig(level=logging.INFO)

if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
    raise SystemExit(
        "Ошибка: вставь реальный токен бота в config.py или задай переменную окружения BOT_TOKEN."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class AdminQuest(StatesGroup):
    waiting_title = State()
    waiting_xp = State()
    waiting_gold = State()
    confirming = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def escape_md(text: str) -> str:
    """Экранирует спецсимволы legacy Markdown (_ * ` [), чтобы произвольный текст
    (username, название квеста) не ломал парсинг разметки Telegram."""
    return re.sub(r"([_*`\[])", r"\\\1", str(text))


async def deny(callback: types.CallbackQuery):
    await callback.answer("⛔ У тебя нет доступа к этому разделу.", show_alert=True)


def get_main_menu(is_admin_user: bool = False):
    keyboard = [
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="📜 Доступные квесты", callback_data="quests")],
        [InlineKeyboardButton(text="⚔️ Задания фракции", callback_data="faction_quests")],
    ]
    if is_admin_user:
        keyboard.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Составы фракций", callback_data="admin_rosters")],
            [InlineKeyboardButton(text="✏️ Сменить фракцию игрока", callback_data="admin_change_faction")],
            [InlineKeyboardButton(text="⚔️ Квест фракции", callback_data="admin_new_faction_quest")],
            [InlineKeyboardButton(text="🎯 Индивидуальный квест", callback_data="admin_new_user_quest")],
            [InlineKeyboardButton(text="✅ Подтвердить выполнение", callback_data="admin_complete_list")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_menu")],
        ]
    )


def back_kb(callback_data: str = "back_menu"):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=callback_data)]]
    )


async def quest_target_label(target_type: str, target_value: str) -> str:
    if target_type == "faction":
        return target_value
    user = await get_user(int(target_value))
    username = user[1] if user else target_value
    return f"@{username}"


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user:
        await message.answer(
            "С возвращением, бойцовский дух при тебе! Выбери раздел меню:",
            reply_markup=get_main_menu(is_admin(user_id)),
        )
        return

    chosen_faction = random.choice(FACTIONS)
    await register_user(
        user_id,
        message.from_user.username or "Неизвестный",
        chosen_faction,
    )

    await message.answer(
        "🎉 Добро пожаловать на платформу!\n\n"
        f"Священный жребий брошен... Твоя фракция: **{chosen_faction}** 🛡️\n\n"
        "Теперь тебе доступны профиль, личные и командные квесты.",
        reply_markup=get_main_menu(is_admin(user_id)),
        parse_mode="Markdown",
    )


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к админ-панели.")
        return
    await message.answer("🛠 Админ-панель:", reply_markup=get_admin_menu())


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Отменено.")


@dp.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    if user:
        _, username, faction, xp, gold = user
        text = (
            f"👤 **Твой профиль:**\n\n"
            f"▪️ Имя: @{escape_md(username)}\n"
            f"▪️ Фракция: {faction}\n"
            f"▪️ XP (Опыт): {xp}\n"
            f"▪️ Gold (Золото): {gold}"
        )
        await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "quests")
async def show_quests(callback: types.CallbackQuery):
    personal_quests = await get_active_quests_for_user(callback.from_user.id)

    text = (
        "📜 **Индивидуальные квесты:**\n\n"
        "1. Написать пост в соцсетях (+50 XP, +10 Gold)\n"
        "2. Пригласить друга (+100 XP, +25 Gold)\n\n"
        "*(В будущем здесь можно будет нажимать кнопку «Взять квест»)*"
    )

    if personal_quests:
        text += "\n\n**🎯 Личные задания от админа:**\n"
        for _, title, rxp, rgold, *_ in personal_quests:
            text += f"• {escape_md(title)} (+{rxp} XP, +{rgold} Gold)\n"

    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "faction_quests")
async def show_faction_quests(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    faction = user[2] if user else "Неизвестно"
    faction_quests = await get_active_quests_for_faction(faction) if user else []

    text = (
        f"⚔️ **Глобальные задания фракции ({faction}):**\n\n"
        "• Захватить лидерство по активности за неделю (Цель всей фракции)\n"
        "• Набрать общими усилиями 1000 XP\n\n"
        "Общий вклад фракции учитывается автоматически!"
    )

    if faction_quests:
        text += "\n\n**📜 Задания от админа:**\n"
        for _, title, rxp, rgold, *_ in faction_quests:
            text += f"• {escape_md(title)} (+{rxp} XP, +{rgold} Gold каждому)\n"

    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Главное меню платформы:", reply_markup=get_main_menu(is_admin(callback.from_user.id))
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Админ-панель
# ---------------------------------------------------------------------------


@dp.callback_query(F.data == "admin_panel")
async def open_admin_panel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return
    await callback.message.edit_text("🛠 Админ-панель:", reply_markup=get_admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_rosters")
async def admin_rosters(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    users = await get_all_users()
    if not users:
        text = "Пока никто не зарегистрирован."
    else:
        by_faction = {}
        for uid, username, faction, xp, gold in users:
            by_faction.setdefault(faction, []).append(f"• @{escape_md(username)} — {xp} XP, {gold} Gold")

        parts = [f"👥 **Составы фракций** (всего игроков: {len(users)}):"]
        for faction in FACTIONS:
            members = by_faction.get(faction, [])
            parts.append(f"\n**{faction}** ({len(members)}):")
            parts.extend(members if members else ["  (пусто)"])
        text = "\n".join(parts)

    await callback.message.edit_text(text, reply_markup=back_kb("admin_panel"), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "admin_change_faction")
async def admin_change_faction(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    users = await get_all_users()
    if not users:
        await callback.answer("Нет зарегистрированных игроков.", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text=f"{username} ({faction})", callback_data=f"admin_cf_user:{uid}")]
        for uid, username, faction, xp, gold in users
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
    await callback.message.edit_text(
        "Выбери игрока, чью фракцию нужно изменить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_cf_user:"))
async def admin_cf_pick_user(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    target_id = callback.data.split(":", 1)[1]
    user = await get_user(int(target_id))
    if not user:
        await callback.answer("Игрок не найден.", show_alert=True)
        return

    _, username, current_faction, xp, gold = user
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if faction == current_faction else ''}{faction}",
                callback_data=f"admin_cf_set:{target_id}:{faction}",
            )
        ]
        for faction in FACTIONS
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_change_faction")])
    await callback.message.edit_text(
        f"@{username}\nТекущая фракция: {current_faction}\n\nВыбери новую фракцию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_cf_set:"))
async def admin_cf_set(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    _, target_id, new_faction = callback.data.split(":", 2)
    user = await get_user(int(target_id))
    if not user:
        await callback.answer("Игрок не найден.", show_alert=True)
        return

    _, username, old_faction, xp, gold = user
    if old_faction == new_faction:
        await callback.answer(f"@{username} уже во фракции «{new_faction}».", show_alert=True)
        return

    await set_user_faction(int(target_id), new_faction)
    try:
        await bot.send_message(
            int(target_id),
            f"🔄 Администратор перевёл тебя из фракции «{old_faction}» в «{new_faction}».",
        )
    except Exception:
        logging.warning("Не удалось уведомить игрока %s о смене фракции", target_id)

    await callback.message.edit_text(
        f"✅ @{username} переведён(а) из «{old_faction}» в «{new_faction}».",
        reply_markup=get_admin_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_new_faction_quest")
async def admin_new_faction_quest(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    buttons = [
        [InlineKeyboardButton(text=faction, callback_data=f"admin_ffaction:{faction}")]
        for faction in FACTIONS
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
    await callback.message.edit_text(
        "Выбери фракцию, для которой создаём квест:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_ffaction:"))
async def admin_pick_faction(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    faction = callback.data.split(":", 1)[1]
    await state.update_data(target_type="faction", target_value=faction)
    await state.set_state(AdminQuest.waiting_title)
    await callback.message.edit_text(f"Фракция: {faction}\n\nВведи название квеста (текстом):")
    await callback.answer()


@dp.callback_query(F.data == "admin_new_user_quest")
async def admin_new_user_quest(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    users = await get_all_users()
    if not users:
        await callback.answer("Нет зарегистрированных игроков.", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text=f"{username} ({faction})", callback_data=f"admin_fuser:{uid}")]
        for uid, username, faction, xp, gold in users
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
    await callback.message.edit_text(
        "Выбери игрока для индивидуального квеста:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_fuser:"))
async def admin_pick_user(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    target_user_id = callback.data.split(":", 1)[1]
    await state.update_data(target_type="user", target_value=target_user_id)
    await state.set_state(AdminQuest.waiting_title)
    await callback.message.edit_text("Введи название квеста (текстом):")
    await callback.answer()


@dp.message(AdminQuest.waiting_title)
async def admin_quest_title(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(title=message.text)
    await state.set_state(AdminQuest.waiting_xp)
    await message.answer("Сколько XP дать за выполнение? (введи число)")


@dp.message(AdminQuest.waiting_xp)
async def admin_quest_xp(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("Нужно целое число. Попробуй ещё раз:")
        return
    await state.update_data(reward_xp=int(message.text))
    await state.set_state(AdminQuest.waiting_gold)
    await message.answer("Сколько Gold дать за выполнение? (введи число)")


@dp.message(AdminQuest.waiting_gold)
async def admin_quest_gold(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("Нужно целое число. Попробуй ещё раз:")
        return

    reward_gold = int(message.text)
    await state.update_data(reward_gold=reward_gold)
    data = await state.get_data()

    target_label = await quest_target_label(data["target_type"], data["target_value"])
    text = (
        "Проверь квест перед созданием:\n\n"
        f"📜 {data['title']}\n"
        f"🎯 Цель: {target_label}\n"
        f"Награда: +{data['reward_xp']} XP, +{reward_gold} Gold\n\n"
        "Создать и отправить?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Создать", callback_data="admin_confirm_yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_confirm_no"),
            ]
        ]
    )
    await state.set_state(AdminQuest.confirming)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "admin_confirm_no", AdminQuest.confirming)
async def admin_cancel_quest(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание квеста отменено.", reply_markup=get_admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_confirm_yes", AdminQuest.confirming)
async def admin_confirm_quest(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    data = await state.get_data()
    await state.clear()

    title = data["title"]
    reward_xp = data["reward_xp"]
    reward_gold = data["reward_gold"]
    target_type = data["target_type"]
    target_value = data["target_value"]

    await create_quest(title, reward_xp, reward_gold, target_type, target_value)

    if target_type == "faction":
        members = await get_users_by_faction(target_value)
        for uid, *_ in members:
            try:
                await bot.send_message(
                    uid,
                    f"📜 Новый квест фракции «{target_value}»!\n\n{title}\n\n"
                    f"Награда: +{reward_xp} XP, +{reward_gold} Gold",
                )
            except Exception:
                logging.warning("Не удалось отправить квест игроку %s", uid)
        result_text = f"✅ Квест создан и разослан фракции «{target_value}» ({len(members)} игроков)."
    else:
        target_id = int(target_value)
        try:
            await bot.send_message(
                target_id,
                f"🎯 Тебе выдан новый квест!\n\n{title}\n\n"
                f"Награда: +{reward_xp} XP, +{reward_gold} Gold",
            )
        except Exception:
            logging.warning("Не удалось отправить квест игроку %s", target_id)
        result_text = "✅ Квест создан и отправлен игроку."

    await callback.message.edit_text(result_text, reply_markup=get_admin_menu())
    await callback.answer()


@dp.callback_query(F.data == "admin_complete_list")
async def admin_complete_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    quests = await get_all_active_quests()
    if not quests:
        await callback.answer("Нет активных квестов.", show_alert=True)
        return

    buttons = []
    for qid, title, rxp, rgold, ttype, tval, status, created in quests:
        label = await quest_target_label(ttype, tval)
        buttons.append(
            [InlineKeyboardButton(text=f"#{qid} {title[:20]} → {label}", callback_data=f"admin_complete:{qid}")]
        )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])

    await callback.message.edit_text(
        "Активные квесты. Нажми, чтобы подтвердить выполнение и начислить награду:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_complete:"))
async def admin_complete_quest(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await deny(callback)
        return

    quest_id = int(callback.data.split(":", 1)[1])
    quest = await get_quest(quest_id)
    if not quest:
        await callback.answer("Квест не найден.", show_alert=True)
        return

    qid, title, rxp, rgold, ttype, tval, status, created = quest
    if status != "active":
        await callback.answer("Этот квест уже завершён.", show_alert=True)
        return

    if ttype == "faction":
        members = await get_users_by_faction(tval)
        for uid, *_ in members:
            await add_xp_gold(uid, rxp, rgold)
            try:
                await bot.send_message(uid, f"🎉 Квест фракции выполнен: {title}\n+{rxp} XP, +{rgold} Gold")
            except Exception:
                logging.warning("Не удалось уведомить игрока %s", uid)
        result_text = f"✅ Награда начислена всей фракции «{tval}» ({len(members)} игроков)."
    else:
        target_id = int(tval)
        await add_xp_gold(target_id, rxp, rgold)
        try:
            await bot.send_message(target_id, f"🎉 Квест выполнен: {title}\n+{rxp} XP, +{rgold} Gold")
        except Exception:
            logging.warning("Не удалось уведомить игрока %s", target_id)
        result_text = "✅ Награда начислена игроку."

    await complete_quest(quest_id)
    await callback.message.edit_text(result_text, reply_markup=get_admin_menu())
    await callback.answer()


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit(
            "Ошибка: вставь реальный токен бота в config.py или задай переменную окружения BOT_TOKEN."
        )

    restart_delay = 10
    while True:
        try:
            await init_db()
            logging.info("Бот запущен и готов к работе...")
            await dp.start_polling(bot)
            break
        except KeyboardInterrupt:
            logging.info("Остановка бота по команде пользователя.")
            break
        except TelegramNetworkError as e:
            logging.warning(
                "Ошибка подключения к Telegram. Перезапуск через %s секунд. Причина: %s",
                restart_delay,
                e,
            )
            await asyncio.sleep(restart_delay)
        except Exception as e:
            logging.exception("Неожиданная ошибка в работе бота. Перезапуск через %s секунд.", restart_delay)
            await asyncio.sleep(restart_delay)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception:
        logging.exception("Критическая ошибка запуска бота.")
        sys.exit(1)
