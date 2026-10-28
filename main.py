# -*- coding: utf-8 -*-
# Кодировка файла. Нужна, чтобы русские буквы в сообщениях бота читались правильно.

"""Небольшой тестовый бот магазина воланов.

Запуск: python bot.py
Проверка без Telegram: python bot.py --check
"""

# Подсказки типов (list[Product] и т.п.) остаются текстом для человека и редактора.
# При запуске Python их не проверяет.
from __future__ import annotations

import os  # читаем настройки, которые лежат в переменных окружения
import sys  # аргументы командной строки и вывод ошибок
from pathlib import Path  # путь к папке проекта, чтобы найти файл .env

# Если библиотеки не стоят, не падаем непонятной ошибкой, а пишем, что установить.
try:
    from dotenv import load_dotenv  # читает файл .env и кладёт значения в окружение
    from telegram import (  # куски сообщения, которые видит человек в чате
        InlineKeyboardButton,  # кнопка под сообщением
        InlineKeyboardMarkup,  # набор таких кнопок
        KeyboardButton,  # обычная кнопка клавиатуры, умеет отдать контакт
        ReplyKeyboardMarkup,  # клавиатура снизу, вместо обычной
        ReplyKeyboardRemove,  # команда убрать эту клавиатуру
        Update,  # всё, что пришло от Telegram: сообщение, нажатие, контакт
    )
    from telegram.error import InvalidToken  # Telegram отверг токен бота
    from telegram.ext import (  # обвязка: «если пришло то-то, вызови такую функцию»
        Application,  # сам бот: токен, обработчики, запуск
        CallbackQueryHandler,  # нажатие кнопки под сообщением
        CommandHandler,  # команды вида /start
        ContextTypes,  # тип служебного аргумента context
        MessageHandler,  # обычные сообщения
        filters,  # условия: текст, контакт, не команда
    )
except ImportError:
    sys.stderr.write("Сначала выполните: python -m pip install -r requirements.txt\n")
    raise SystemExit(1)  # выходим с кодом ошибки, бот дальше не запускаем


# Папка, в которой лежит этот файл. Рядом с ней должен быть .env.
BASE_DIR = Path(__file__).resolve().parent
# Забираем из .env токен и прочие настройки. Без этого os.getenv их не увидит.
load_dotenv(BASE_DIR / ".env")
# Верхняя граница: больше 20 туб за один заказ не принимаем.
MAX_QTY = 20


class Product:
    """Один товар: короткий код, название и цена в гривнах."""

    def __init__(self, code: str, name: str, price: int):
        self.code = code  # короткий id, его прячем в кнопку, например as50
        self.name = name  # то, что видит покупатель
        self.price = price  # цена одной тубы, целое число гривен

    def button_text(self) -> str:
        # Надпись на кнопке каталога: название и цена.
        return f"{self.name} — {self._money(self.price)}"

    @staticmethod
    def _money(value: int) -> str:
        # 4990 -> "4 990 ₴". Запятые от формата меняем на пробелы, чтобы было по-русски.
        return f"{value:,}".replace(",", " ") + " ₴"


class Catalog:
    """Список товаров и кнопки, которыми его показывают."""

    def __init__(self, products: list[Product]):
        self.products = products

    @classmethod
    def demo(cls) -> Catalog:
        # Готовый тестовый ассортимент. Код, название, цена.
        return cls(
            [
                Product("as50", "Yonex Aerosensa 50", 4990),
                Product("as30", "Yonex Aerosensa 30", 2890),
                Product("m350", "Yonex Mavis 350", 890),
                Product("train", "Учебные пластиковые", 390),
            ]
        )

    def get(self, code: str) -> Product | None:
        # Ищем товар по коду из кнопки. Если кода нет — вернём None.
        for product in self.products:
            if product.code == code:
                return product
        return None

    def keyboard(self) -> InlineKeyboardMarkup:
        # По одной кнопке в ряд. В callback_data кладём "buy:код",
        # Telegram пришлёт эту строку обратно, когда человек нажмёт кнопку.
        rows = [
            [InlineKeyboardButton(product.button_text(), callback_data=f"buy:{product.code}")]
            for product in self.products
        ]
        return InlineKeyboardMarkup(rows)


class Draft:
    """Незаконченный заказ одного человека. Живёт в памяти, пока бот запущен."""

    def __init__(self, product: Product):
        self.product = product  # что выбрали
        self.qty: int | None = None  # сколько туб; пока не написали — пусто

    def ask_qty(self) -> str:
        # Текст после выбора товара: цена и просьба написать количество.
        return (
            f"{self.product.name}\n"
            f"{Product._money(self.product.price)} за тубу.\n\n"
            "Сколько туб? Напишите число от 1 до 20."
        )

    def ask_phone(self) -> str:
        # Текст после количества: сумма и просьба дать телефон.
        total = self.product.price * (self.qty or 0)
        return (
            f"{self.product.name} × {self.qty} = {Product._money(total)}\n\n"
            "Напишите телефон или нажмите кнопку ниже."
        )


class Order:
    """Уже собранный заказ: кто, что, сколько и телефон."""

    def __init__(self, user_id: int, full_name: str, username: str | None, product: Product, qty: int, phone: str):
        self.user_id = user_id  # числовой id Telegram, он не меняется
        self.full_name = full_name  # имя из профиля
        self.username = username  # @ник, его может не быть
        self.product = product
        self.qty = qty
        self.phone = phone

    @property
    def total(self) -> int:
        # Сумма считается каждый раз из цены и количества, отдельно её не храним.
        return self.product.price * self.qty

    def for_client(self) -> str:
        # Короткое подтверждение, которое уходит покупателю в чат.
        return (
            "Заказ принят.\n"
            f"{self.product.name} × {self.qty}\n"
            f"Итого: {Product._money(self.total)}\n"
            f"Телефон: {self.phone}\n\n"
            "Оплата при получении. Новый заказ — /start"
        )

    def for_admin(self) -> str:
        # Тот же заказ для консоли: кто заказал и как его найти.
        login = f"@{self.username}" if self.username else "без username"
        return (
            "Новый заказ\n"
            f"{self.full_name} ({login}), id {self.user_id}\n"
            f"{self.product.name} × {self.qty}\n"
            f"Итого: {Product._money(self.total)}\n"
            f"Телефон: {self.phone}"
        )


class ShopBot:
    """Связывает каталог, незаконченные заказы и ответы на сообщения."""

    def __init__(self, token: str, catalog: Catalog):
        self.token = token  # ключ бота от BotFather
        self.catalog = catalog
        # Словарь «id человека -> его черновик». После перезапуска бота он пустой.
        self.drafts: dict[int, Draft] = {}

    def run(self) -> None:
        # Собираем приложение и говорим, какую функцию звать на каждое событие.
        # Порядок важен: команда проверяется раньше обычного текста.
        app = Application.builder().token(self.token).post_init(self.on_ready).build()
        app.add_handler(CommandHandler("start", self.start))  # /start — показать каталог
        app.add_handler(CommandHandler("cancel", self.cancel))  # /cancel — бросить черновик
        # Кнопки, у которых данные начинаются на "buy:".
        app.add_handler(CallbackQueryHandler(self.choose_product, pattern=r"^buy:"))
        app.add_handler(MessageHandler(filters.CONTACT, self.on_contact))  # кнопка с номером
        # Обычный текст, но не команды. Сюда попадают количество и телефон, написанные руками.
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        # Слушаем Telegram, пока окно не закроют.
        # Старые сообщения, пришедшие пока бот был выключен, пропускаем.
        app.run_polling(drop_pending_updates=True)

    async def on_ready(self, app: Application) -> None:
        # Вызывается один раз после успешного подключения. async — можно ждать ответ Telegram.
        me = await app.bot.get_me()  # спрашиваем у Telegram, под каким именем запущен бот
        print(f"Бот запущен: @{me.username}")
        print("Окно не закрывать. Остановить: Ctrl+C")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # update — что прислал человек. context библиотека передаёт всегда, здесь он не нужен.
        # Чужой чат или пустое сообщение игнорируем: бот только для лички.
        if not update.message or not self._is_private(update):
            return
        user = update.effective_user
        if user:
            # Новый /start сбрасывает прошлый недоделанный заказ этого человека.
            self.drafts.pop(user.id, None)
        await update.message.reply_text("Выберите воланы:", reply_markup=self.catalog.keyboard())

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not self._is_private(update):
            return
        user = update.effective_user
        if user:
            self.drafts.pop(user.id, None)  # черновик больше не нужен
        await update.message.reply_text(
            "Отменил. Каталог: /start",
            reply_markup=ReplyKeyboardRemove(),  # убираем кнопку «Отправить номер», если она висела
        )

    async def choose_product(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Сюда попадаем, когда нажали кнопку товара.
        query = update.callback_query
        if query is None or query.data is None:
            return
        # Нажатие надо «погасить», иначе у человека крутится часики на кнопке.
        if not self._is_private(update) or update.effective_user is None:
            await query.answer()
            return
        # "buy:as50" -> "as50", затем ищем товар.
        product = self.catalog.get(query.data.split(":", 1)[1])
        if product is None:
            await query.answer("Такого товара нет", show_alert=True)  # окошко с ошибкой
            return
        await query.answer()
        # Запоминаем выбор и сразу спрашиваем количество.
        self.drafts[update.effective_user.id] = Draft(product)
        if query.message:
            await query.message.reply_text(self.drafts[update.effective_user.id].ask_qty())

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Сюда приходит обычный текст. Сначала ждём число туб, потом телефон.
        message = update.message
        user = update.effective_user
        if message is None or user is None or not message.text or not self._is_private(update):
            return
        draft = self.drafts.get(user.id)
        if draft is None:
            # Человек пишет, но товар ещё не выбирал.
            await message.reply_text("Откройте каталог: /start")
            return
        if draft.qty is None:
            await self._read_qty(message, user.id, draft, message.text.strip())
            return
        phone = normalize_phone(message.text)
        if phone is None:
            await message.reply_text("Не похоже на номер. Пример: +79001234567")
            return
        await self._finish(message, user.id, user.full_name, user.username, draft, phone)

    async def on_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Номер пришёл кнопкой «Отправить номер», а не текстом.
        message = update.message
        user = update.effective_user
        if message is None or user is None or message.contact is None or not self._is_private(update):
            return
        draft = self.drafts.get(user.id)
        if draft is None or draft.qty is None:
            # Контакт без выбранного товара и количества заказом не считаем.
            await message.reply_text("Сначала выберите товар: /start")
            return
        # Контакт можно переслать чужой. Берём только номер самого отправителя.
        if message.contact.user_id and message.contact.user_id != user.id:
            await message.reply_text("Нужен ваш номер.")
            return
        phone = normalize_phone(message.contact.phone_number or "")
        if phone is None:
            await message.reply_text("Не получилось прочитать номер. Напишите его текстом.")
            return
        await self._finish(message, user.id, user.full_name, user.username, draft, phone)

    async def _read_qty(self, message, user_id: int, draft: Draft, text: str) -> None:
        # Количество — целое от 1 до 20. Всё остальное просим написать заново.
        if not text.isdigit() or not 1 <= int(text) <= MAX_QTY:
            await message.reply_text(f"Напишите число от 1 до {MAX_QTY}.")
            return
        draft.qty = int(text)
        self.drafts[user_id] = draft
        await message.reply_text(
            draft.ask_phone(),
            reply_markup=ReplyKeyboardMarkup(
                # request_contact=True: по нажатию Telegram сам пришлёт номер из профиля.
                [[KeyboardButton("Отправить номер", request_contact=True)]],
                resize_keyboard=True,  # кнопки поуже, не на весь экран
                one_time_keyboard=True,  # после нажатия клавиатура сама спрячется
            ),
        )

    async def _finish(self, message, user_id: int, full_name: str, username: str | None, draft: Draft, phone: str) -> None:
        # Заказ собран: печатаем его в консоль и подтверждаем покупателю.
        if draft.qty is None:
            return
        order = Order(user_id, full_name, username, draft.product, draft.qty, phone)
        self.drafts.pop(user_id, None)  # черновик больше не нужен, заказ уже готов
        print(order.for_admin())
        await message.reply_text(order.for_client(), reply_markup=ReplyKeyboardRemove())

    @staticmethod
    def _is_private(update: Update) -> bool:
        # True только для личного чата. В группе бот молчит.
        chat = update.effective_chat
        return bool(chat and chat.type == "private")


def normalize_phone(raw: str) -> str | None:
    """Приводит номер к виду +380... Если это не похоже на телефон — возвращает None."""
    digits = "".join(char for char in raw if char.isdigit())  # выкидываем пробелы, скобки, плюс
    # Российская привычка: 8 900... это тот же номер, что 7 900...
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    # Десять цифр без кода страны — дописываем 7.
    if len(digits) == 10:
        digits = "7" + digits
    # Международный номер бывает от 11 до 15 цифр. Короче или длиннее — мусор.
    if not 11 <= len(digits) <= 15:
        return None
    return "+" + digits


def token_ok(token: str) -> bool:
    """Грубая проверка токена до запроса в Telegram. Настоящий токен выглядит как 123456:секрет."""
    # Ровно одно двоеточие и никаких пробелов. Иначе это не токен.
    if token.count(":") != 1 or any(char.isspace() for char in token):
        return False
    bot_id, secret = token.split(":", 1)
    # Слева числовой id бота, справа длинный секрет. Строка из одних A — заглушка из примера.
    return bot_id.isdigit() and len(secret) >= 30 and set(secret) != {"A"}


def run_check() -> None:
    """Проверка без Telegram: каталог, сумма и разбор телефона. Запуск: python main.py --check."""
    catalog = Catalog.demo()
    product = catalog.get("as50")
    assert product is not None  # товар с этим кодом обязан найтись
    order = Order(1, "Иван", "ivan", product, 2, "+79001234567")
    assert order.total == product.price * 2
    assert normalize_phone("8 (900) 123-45-67") == "+79001234567"
    print("Каталог:")
    for item in catalog.products:
        print(f"- {item.code}: {item.button_text()}")
    print()
    print(order.for_client())
    print("CHECK OK")


def main() -> None:
    # --check не ходит в Telegram, только гоняет run_check и выходит.
    if "--check" in sys.argv:
        run_check()
        return
    # Токен из .env. Срезаем пробелы и кавычки, если их случайно оставили вокруг значения.
    token = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
    if not token_ok(token):
        sys.stderr.write(
            "В файле .env нет рабочего BOT_TOKEN.\n"
            "Скопируйте .env.example в .env и вставьте токен от @BotFather.\n"
        )
        raise SystemExit(1)
    try:
        ShopBot(token, Catalog.demo()).run()  # дальше бот висит и слушает сообщения
    except InvalidToken:
        sys.stderr.write("Telegram не принял токен. Проверьте BOT_TOKEN в .env\n")
        raise SystemExit(1)


# Этот блок выполняется только когда файл запустили напрямую, а не импортировали из другого.
if __name__ == "__main__":
    main()
