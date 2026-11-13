<div align="center">

# 🏃 VK Running Bot

### Беговое сообщество, события и результаты — в одном месте

Бот для VK помогает организовывать спортивные события, регистрировать участников,
принимать отчёты о пробежках и собирать статистику.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![VK Bot](https://img.shields.io/badge/VK-bot-0077FF?logo=vk&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00?logo=sqlalchemy&logoColor=white)

</div>

---

## 🧭 Навигация

- [✨ Возможности](#features)
- [🧰 Технологии](#technologies)
- [🚀 Быстрый старт](#quick-start)
- [💬 Команды бота](#commands)
- [🗺️ Как это работает](#workflow)
- [🖥️ Запуск на сервере](#server)
- [🛟 Если что-то пошло не так](#troubleshooting)
- [🔐 Безопасность](#security)

<a id="features"></a>
## ✨ Возможности

### Для участников

- 📅 Смотреть активные события и регистрироваться на них.
- 🏷️ Выбирать категорию и минимальную дистанцию.
- 📸 Отправлять отчёт о пробежке вместе с фото.
- 📊 Смотреть личную статистику тренировок и участий.

### Для администраторов

- 🛠️ Создавать события и управлять регистрацией.
- 🗂️ Настраивать категории и целевые дистанции.
- 🧾 Получать сводные отчёты по участникам и тренировкам.

<a id="technologies"></a>
## 🧰 Технологии

| Компонент | Технология |
|---|---|
| Язык | Python 3.11+ |
| VK API | VKBottle |
| База данных | PostgreSQL 16, SQLAlchemy 2.x, asyncpg |
| Миграции | Alembic |
| Настройки | Pydantic Settings |

### Структура проекта

```text
app/
├── bot/                  # обработчики команд и сценарии диалогов
├── database/
│   ├── models.py         # SQLAlchemy-модели
│   └── service.py        # логика работы с базой данных
├── main.py               # точка запуска
├── service.py            # утилиты и сериализация событий
└── settings.py           # настройки приложения
alembic/                  # миграции базы данных
docker-compose.yml        # PostgreSQL для локальной разработки
```

<a id="quick-start"></a>
## 🚀 Быстрый старт

### Что понадобится

- Linux / Ubuntu / Debian;
- Python 3.11 или новее;
- PostgreSQL 16 (локально, в Docker или на отдельном сервере);
- токен сообщества VK.

### 1. Склонируйте проект и создайте виртуальное окружение

```bash
git clone <адрес_репозитория> vk-running-bot
cd vk-running-bot

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Настройте переменные окружения

Создайте `.env` на основе шаблона:

```bash
cp .env.example .env
```

Откройте `.env` и укажите параметры подключения к базе и токен сообщества:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=vk_running_bot
DB_USER=postgres
DB_PASSWORD=замените_надежным_паролем
TIMEZONE=Europe/Moscow
VK_TOKEN=токен_сообщества_vk
```

> 🔒 Не публикуйте `.env` и не добавляйте реальные секреты в Git.

### 3. Запустите PostgreSQL

Для локальной разработки можно использовать Docker Compose:

```bash
docker compose up -d postgres
docker compose ps
```

По умолчанию база должна быть доступна на `localhost:5432`. Если параметры
PostgreSQL отличаются, обновите их в `.env`.

### 4. Примените миграции и запустите бота

```bash
alembic upgrade head
python app/main.py
```

Готово! 🎉 Если настройки верны, бот подключится к VK и начнёт обрабатывать
сообщения.

### 🧪 Запуск тестов

Установите инструменты тестирования и запустите тесты из корня проекта:

```bash
python -m pip install -e ".[test]"
python -m pytest
```

<a id="commands"></a>
## 💬 Команды бота

### 👟 Для участников

| Команда | Что делает |
|---|---|
| `/help` | Показывает доступные команды |
| `/events` | Показывает активные события |
| `/reg` | Запускает регистрацию на событие |
| `/my_regs` | Показывает ваши регистрации |
| `/stats` | Показывает личную статистику |
| `#отчет 10,5` + фото | Отправляет отчёт о пробежке на 10,5 км |

### 🧑‍💼 Для администраторов

| Команда | Что делает |
|---|---|
| `/create_event` | Создаёт событие |
| `/open` | Открывает регистрацию |
| `/close` | Закрывает регистрацию |
| `/event_report` | Формирует отчёт по событию и категории |
| `/cancel` | Отменяет текущий диалоговый сценарий |

<a id="workflow"></a>
## 🗺️ Как это работает

1. **Администратор создаёт событие** — задаёт название, даты, тип события и
   категории с минимальными или целевыми дистанциями.
2. **Участник регистрируется** — выбирает событие и подходящую категорию.
3. **Участник отправляет отчёт** — пишет, например, `#отчет 10,5` и прикладывает
   фото.
4. **Бот проверяет и сохраняет результат** — учитывает активность события и
   минимальную дистанцию категории.
5. **Администратор смотрит сводку** — бот показывает участников, категории,
   количество тренировок и суммарную дистанцию.

<a id="server"></a>
## 🖥️ Запуск на сервере

Ниже — пример настройки на Ubuntu/Debian с `systemd`.

### 1. Установите системные пакеты

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git postgresql-client ca-certificates curl
```

### 2. Установите проект

```bash
cd /opt
git clone <адрес_репозитория> vk-running-bot
cd vk-running-bot

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
nano .env
```

Заполните `VK_TOKEN` и параметры `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`. Затем примените миграции:

```bash
source .venv/bin/activate
alembic upgrade head
```

Если база находится на этом же сервере и используется Docker:

```bash
docker compose up -d postgres
```

### 3. Создайте systemd-сервис

Создайте файл `/etc/systemd/system/vk-running-bot.service`:

```ini
[Unit]
Description=VK Running Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/vk-running-bot
ExecStart=/opt/vk-running-bot/.venv/bin/python /opt/vk-running-bot/app/main.py
Restart=always
RestartSec=5
Environment=PYTHONPATH=/opt/vk-running-bot
EnvironmentFile=/opt/vk-running-bot/.env

[Install]
WantedBy=multi-user.target
```

Включите и запустите сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vk-running-bot
sudo systemctl status vk-running-bot
```

Логи в реальном времени:

```bash
journalctl -u vk-running-bot -f
```

<a id="troubleshooting"></a>
## 🛟 Если что-то пошло не так

<details>
<summary>🚫 Бот не запускается</summary>

- Проверьте, что файл `.env` существует и `VK_TOKEN` указан верно.
- Убедитесь, что PostgreSQL доступен.
- Запустите `alembic upgrade head` и проверьте, что миграции применились.
- Посмотрите логи: `journalctl -u vk-running-bot -f`.

</details>

<details>
<summary>🔌 Не удаётся подключиться к базе данных</summary>

Проверьте `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` и `DB_PASSWORD` в `.env`,
а также доступность базы и права пользователя PostgreSQL.

</details>

<details>
<summary>💬 Команды не срабатывают</summary>

- Проверьте, что нужный обработчик подключён в `app/main.py`.
- Убедитесь, что бот запущен с актуальной версией кода.
- Проверьте логи приложения на ошибки и конфликты состояний диалога.

</details>

<a id="security"></a>
## 🔐 Безопасность и эксплуатация

- Храните токен VK и пароль базы только в `.env` или защищённом менеджере секретов.
- Не добавляйте `.env` с реальными значениями в Git.
- Для production используйте `systemd`, а не ручной запуск в терминале.
- Регулярно проверяйте логи и создавайте резервные копии PostgreSQL.

## 🔗 Полезные ссылки

- [VKBottle](https://github.com/benja/SDK/blob/master/vkbottle)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Alembic](https://alembic.sqlalchemy.org/)
- [PostgreSQL](https://www.postgresql.org/)

---

<div align="center">

### 📬 Контакты

✉️ [cylonn@yandex.ru](mailto:cylonn@yandex.ru) · 💬 [@cyllonn](https://t.me/cyllonn)

Сделано для тех, кто любит бегать 🏃‍♀️🏃‍♂️

</div>
