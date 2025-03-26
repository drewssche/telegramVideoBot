import os
import sys
import asyncio
from functools import partial
import sqlite3
import logging
import time
import re
import random
import shutil
import subprocess
import contextlib
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import User, Chat, Channel
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QProgressDialog,
                               QLabel, QLineEdit, QPushButton, QDialog, QProgressBar, QMessageBox, QFileDialog,
                               QListWidget, QListWidgetItem, QRadioButton, QGroupBox, QTabWidget, QFrame, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QTimer, QRegularExpression, Signal, QPropertyAnimation, QRect, QUrl, QThread
from PySide6.QtGui import QRegularExpressionValidator, QColor, QDesktopServices, QCursor, QIcon
from qasync import QEventLoop, asyncSlot
import yt_dlp
import json
import base64
import requests
import zipfile
import hashlib
import ctypes

# Настройка логирования
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8',
    filemode='a'
)

# Устанавливаем QT_PLUGIN_PATH
if getattr(sys, 'frozen', False):  # Проверяем, что приложение заморожено (собрано cx_Freeze)
    base_path = os.path.dirname(sys.executable)
    qt_plugin_path = os.path.join(base_path, "PySide6", "plugins")
    os.environ["QT_PLUGIN_PATH"] = qt_plugin_path

# Константы
# Чтение версии из version.json
def get_current_version():
    try:
        with open("version.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("version", "0.0.0")  # Возвращаем 0.0.0, если версия не указана
    except Exception as e:
        logging.error(f"Не удалось прочитать версию из version.json: {str(e)}")
        return "0.0.0"  # Резервная версия для новой установки

CURRENT_VERSION = get_current_version()
VIDEO_URL_PATTERNS = {
    'youtube_shorts': re.compile(r'(?:https?://)?(?:www\.)?(?:youtube\.com/shorts/|youtu\.be/)([\w-]{11})'),
    'instagram': re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/reel[s]?/([\w-]+)'),
    'tiktok': re.compile(r'(?:https?://)?(?:www\.)?(?:tiktok\.com/@[\w\.-]+/video/|vm\.tiktok\.com/)([\w-]+)'),
    'twitter': re.compile(r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[\w-]+/status/(\d+)')
}
VIDEO_SEND_DELAY = 1
TEMP_DIR = "temp-files"
os.makedirs(TEMP_DIR, exist_ok=True)

# Инициализация SQLite
def init_db():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS auth_data (
                        api_id INTEGER,
                        api_hash TEXT,
                        phone TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS selected_chats (
                        chat_id INTEGER PRIMARY KEY,
                        title TEXT,
                        type TEXT,
                        date_added TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS platform_settings (
                        platform TEXT PRIMARY KEY,
                        enabled INTEGER
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS responses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT
                      )''')
    conn.commit()
    conn.close()

# Функции работы с БД
def get_auth_data():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT api_id, api_hash, phone FROM auth_data")
    data = cursor.fetchone()
    conn.close()
    return data

def save_auth_data(api_id, api_hash, phone):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auth_data")
    cursor.execute("INSERT INTO auth_data (api_id, api_hash, phone) VALUES (?, ?, ?)", (api_id, api_hash, phone))
    conn.commit()
    conn.close()

async def clear_auth_data():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auth_data")
    conn.commit()
    conn.close()
    await state.ensure_client_disconnected()  # Отключаем клиент
    # Добавляем небольшую задержку, чтобы убедиться, что клиент полностью отключён
    await asyncio.sleep(1)
    if os.path.exists('bot.session'):
        for attempt in range(3):
            try:
                os.remove('bot.session')
                logging.info("Файл сессии bot.session успешно удалён")
                break
            except PermissionError as e:
                if "[WinError 32]" in str(e):
                    logging.warning(f"Файл bot.session занят, повторная попытка {attempt + 1}/3...")
                    await asyncio.sleep(1)  # Используем await для асинхронной задержки
                else:
                    logging.error(f"Не удалось удалить файл сессии: {str(e)}")
                    break
            except Exception as e:
                logging.error(f"Не удалось удалить файл сессии: {str(e)}")
                break
        else:
            logging.error("Не удалось удалить файл сессии после нескольких попыток")
            return False
    return True

def save_selected_chat(chat_id, title, chat_type):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO selected_chats (chat_id, title, type, date_added) VALUES (?, ?, ?, ?)",
                   (chat_id, title, chat_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_selected_chat(chat_id):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM selected_chats WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def get_selected_chats():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, title, type FROM selected_chats")
    data = cursor.fetchall()
    conn.close()
    return data

def save_platform_setting(platform, enabled):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO platform_settings (platform, enabled) VALUES (?, ?)", (platform, 1 if enabled else 0))
    conn.commit()
    conn.close()

def get_platform_settings():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT platform, enabled FROM platform_settings")
    data = cursor.fetchall()
    conn.close()
    return {platform: bool(enabled) for platform, enabled in data}

def save_response(text):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO responses (text) VALUES (?)", (text,))
    conn.commit()
    conn.close()

def get_responses():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, text FROM responses ORDER BY id")
    data = cursor.fetchall()
    conn.close()
    return data

def delete_response(response_id):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM responses WHERE id = ?", (response_id,))
    conn.commit()
    conn.close()

def clear_responses():
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM responses")
    conn.commit()
    conn.close()

def update_response(response_id, text):
    conn = sqlite3.connect('telegram_bot_data.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE responses SET text = ? WHERE id = ?", (text, response_id))
    conn.commit()
    conn.close()

class DownloadThread(QThread):
    progress = Signal(int)
    downloadedBytes = Signal(int)  # Новый сигнал для количества загруженных байтов
    finished = Signal(bool, str)

    def __init__(self, url, output_path):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.max_retries = 3  # Максимальное количество попыток

    def run(self):
        response = None
        for attempt in range(self.max_retries):
            try:
                response = requests.get(self.url, stream=True, timeout=10)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded_size = 0
                chunk_size = 8192

                with open(self.output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if self.isInterruptionRequested():  # Проверка на отмену
                            self.finished.emit(False, "Скачивание отменено пользователем.")
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            self.downloadedBytes.emit(downloaded_size)  # Испускаем сигнал с количеством байтов
                            if total_size > 0:
                                progress = int((downloaded_size / total_size) * 100)
                                self.progress.emit(progress)

                # Проверяем, что файл доступен для чтения
                if not os.path.exists(self.output_path):
                    raise FileNotFoundError(f"Файл {self.output_path} не был создан после скачивания")
                if not os.access(self.output_path, os.R_OK):
                    raise PermissionError(f"Нет прав на чтение файла {self.output_path} после скачивания")

                self.finished.emit(True, "")
                return

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    logging.warning(f"Ошибка скачивания (попытка {attempt + 1}/{self.max_retries}): {str(e)}. Повторная попытка...")
                    time.sleep(2)  # Задержка перед повторной попыткой
                    continue
                else:
                    self.finished.emit(False, f"Не удалось скачать обновление после {self.max_retries} попыток: {str(e)}.")
                    return
            except (PermissionError, IOError) as e:
                self.finished.emit(False, f"Ошибка при записи файла {self.output_path}: {str(e)}.")
                return
            except Exception as e:
                self.finished.emit(False, f"Неожиданная ошибка при скачивании: {str(e)}.")
                return
            finally:
                if response is not None:
                    response.close()  # Явно закрываем соединение

# Класс состояния программы
class AppState:
    def __init__(self):
        self.client = None
        self.auth_data = None
        self.session_exists = os.path.exists('bot.session')
        self.chat_cache = {}
        self.participants_cache = {}
        self.switch_is_on = False
        self.active_tasks = []
        self.flood_wait_until = 0
        self.flood_wait_lock = asyncio.Lock()
        self.links_processed_per_chat = {}  # Статистика обработанных ссылок за сессию: {chat_id: count}
        self.errors_per_chat = {}  # Статистика ошибок за сессию: {chat_id: count}
        self.responses_enabled = True
        self.current_user_id = None  # Добавляем поле для ID текущего пользователя

    async def ensure_client_disconnected(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
                logging.info("Клиент Telegram успешно отключён")
            except Exception as e:
                logging.error(f"Ошибка при отключении клиента Telegram: {str(e)}")
            finally:
                self.client = None

state = AppState()

# Функции обработки видео (адаптированные под Telethon)
async def update_progress_bar_video(chat_id, message_id, url, platform, downloaded, total, last_percentage, last_update_time, last_message_text=None):
    if last_message_text is None:
        last_message_text = [f"Обрабатываю ссылку {url}\n{platform}\n[{' ' * 10}] 0%"]  # Инициализация последнего текста

    current_time = time.time()

    # Проверяем, не находимся ли мы в режиме ожидания FLOOD_WAIT
    async with state.flood_wait_lock:
        if current_time < state.flood_wait_until:
            logging.info(f"Пропускаем обновление прогресс-бара: FLOOD_WAIT до {state.flood_wait_until}")
            return False

    if total <= 0:
        return True  # Ничего не делаем, если total не определён

    percentage = min(int((downloaded / total) * 100), 100)  # Ограничиваем процент до 100
    # Обновляем прогресс-бар только если процент изменился на 5% или достиг 100%,
    # и прошло не менее 5 секунд с последнего обновления
    if (percentage >= last_percentage[0] + 5 or percentage == 100) and (current_time - last_update_time[0] >= 5):
        bar_length = 10
        progress = bar_length * percentage / 100
        filled = int(progress)
        half = '▌' if progress - filled >= 0.5 else ''
        bar = '█' * filled + half + ' ' * (bar_length - filled - (1 if half else 0))
        new_text = f"Обрабатываю ссылку {url}\n{platform}\n[{bar}] {percentage}%"

        # Пропускаем обновление, если текст не изменился
        if new_text == last_message_text[0]:
            logging.debug(f"Текст прогресс-бара не изменился, пропускаем обновление: {new_text}")
            return True

        try:
            # Проверяем, существует ли сообщение
            try:
                await state.client.get_messages(chat_id, ids=message_id)
            except Exception as e:
                logging.warning(f"Сообщение с ID {message_id} недоступно: {e}")
                return False

            await state.client.edit_message(chat_id, message_id, new_text)
            last_percentage[0] = percentage
            last_update_time[0] = current_time
            last_message_text[0] = new_text  # Обновляем последний текст
        except Exception as e:
            if "message is not modified" in str(e):
                # Игнорируем ошибку "message is not modified" без логирования
                return True
            elif "FLOOD_WAIT" in str(e):
                # Если поймали FLOOD_WAIT, извлекаем время ожидания
                wait_time = int(re.search(r"FLOOD_WAIT_(\d+)", str(e)).group(1)) if re.search(r"FLOOD_WAIT_(\d+)", str(e)) else 10
                async with state.flood_wait_lock:
                    state.flood_wait_until = current_time + wait_time
                logging.warning(f"FLOOD_WAIT на {wait_time} секунд при обновлении прогресс-бара, ждём до {state.flood_wait_until}")
                await asyncio.sleep(wait_time)
                return False
            elif "message ID is invalid" in str(e):
                logging.warning(f"Сообщение с ID {message_id} недействительно: {e}")
                return False
            else:
                logging.warning(f"Ошибка обновления прогресс-бара: {e}")
                return False
    return True

async def process_video(chat_id, message_id, url, platform, max_duration, message, sender_info):
    progress_msg = await state.client.send_message(chat_id, f"Обрабатываю ссылку {url}\n{platform}\n[{' ' * 10}] 0%", reply_to=message_id)
    last_percentage = [0]
    last_update_time = [time.time()]
    last_message_text = [f"Обрабатываю ссылку {url}\n{platform}\n[{' ' * 10}] 0%"]  # Инициализация последнего текста
    temp_file = None
    final_file = None

    # Переменная для отслеживания, можно ли продолжать обновление прогресс-бара
    can_update_progress = [True]
    last_hook_call = [0]  # Время последнего вызова progress_hook

    # Получаем информацию о чате для логирования
    try:
        chat_entity = await state.client.get_entity(chat_id)
        chat_title = chat_entity.title if hasattr(chat_entity, 'title') else f"{chat_entity.first_name or ''} {chat_entity.last_name or ''}".strip()
        chat_type = "Личный" if isinstance(chat_entity, User) else "Группа" if isinstance(chat_entity, Chat) else "Супергруппа" if isinstance(chat_entity, Channel) and chat_entity.megagroup else "Канал"
    except Exception as e:
        logging.error(f"Не удалось получить информацию о чате {chat_id} для логирования: {str(e)}")
        chat_title = "Неизвестный чат"
        chat_type = "Неизвестно"

    # Создаём уникальный суффикс для файлов, чтобы избежать конфликтов
    unique_suffix = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    temp_file_base = f"temp-files/temp_{unique_suffix}"
    temp_file = f"{temp_file_base}.%(ext)s"
    final_file = f"{temp_file_base}_telegram.mp4"

    # Создаём синхронную функцию progress_hook
    def progress_hook(d):
        nonlocal can_update_progress, last_hook_call
        current_time = time.time()

        # Проверяем глобальное состояние FLOOD_WAIT
        if current_time < state.flood_wait_until:
            logging.info(f"Пропускаем вызов progress_hook: FLOOD_WAIT до {state.flood_wait_until}")
            return

        # Ограничиваем частоту вызовов progress_hook (не чаще, чем раз в 5 секунд)
        if current_time - last_hook_call[0] < 5:
            return

        if d['status'] == 'downloading' and can_update_progress[0]:
            total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            # Вызываем асинхронную функцию update_progress_bar_video через event loop
            loop = asyncio.get_event_loop()
            task = loop.create_task(update_progress_bar_video(
                chat_id, progress_msg.id, url, platform, downloaded, total, last_percentage, last_update_time, last_message_text
            ))
            # Добавляем callback для обработки результата
            task.add_done_callback(
                lambda t: can_update_progress.__setitem__(0, False) if not t.result() else None
            )
            last_hook_call[0] = current_time
        elif d['status'] == 'finished' and can_update_progress[0]:
            # Финальное обновление прогресс-бара до 100%
            loop = asyncio.get_event_loop()
            task = loop.create_task(update_progress_bar_video(
                chat_id, progress_msg.id, url, platform, 100, 100, last_percentage, last_update_time, last_message_text
            ))
            task.add_done_callback(
                lambda t: can_update_progress.__setitem__(0, False) if not t.result() else None
            )
            last_hook_call[0] = current_time

    # Ограничиваем экстракторы только теми, которые нам нужны
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': temp_file,  # Используем уникальное имя файла
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
        'extractor_list': ['youtube', 'twitter'],  # Ограничиваем экстракторы
    }

    try:
        if not shutil.which('ffmpeg'):
            raise FileNotFoundError("ffmpeg не установлен или не найден в PATH")
        
        # Проверяем длительность видео
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extractor_list': ['youtube', 'twitter']}) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get('duration', 0)
            if max_duration and duration > max_duration:
                await state.client.delete_messages(chat_id, progress_msg.id)
                logging.info(f"Видео {url} отклонено: длительность {duration} сек превышает лимит {max_duration} сек {sender_info} в чат '{chat_title}' (тип: {chat_type})")
                if state.responses_enabled:  # Проверяем состояние переключателя
                    responses = get_responses()
                    if responses:
                        response_text = random.choice([r[1] for r in responses])
                        await state.client.send_message(chat_id, response_text, reply_to=message_id)
                        logging.info(f"Отправлен ответ '{response_text}' {sender_info} в чат '{chat_title}' (тип: {chat_type})")
                return False

        # Скачиваем видео
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            temp_file = ydl.prepare_filename(info)
            final_file = temp_file.rsplit('.', 1)[0] + '_telegram.mp4'
            ffmpeg_cmd = [
                'ffmpeg', '-i', temp_file,
                '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.0',
                '-b:v', '1M',  # Битрейт 1 Мбит/с
                '-c:a', 'aac', '-ar', '44100', '-b:a', '96k',
                '-vf', 'scale=480:-2,format=yuv420p',
                '-preset', 'fast',
                '-movflags', 'frag_keyframe+empty_moov+faststart',
                '-y', final_file
            ]
            subprocess.run(ffmpeg_cmd, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

            # Получаем информацию о видео для атрибутов
            width = info.get('width', 480)  # По умолчанию 480, если не указано
            height = info.get('height', 854)  # По умолчанию 854, если не указано
            duration = info.get('duration', 0)  # Длительность видео в секундах

            # Отправляем видео с атрибутами для стриминга
            from telethon.tl.types import DocumentAttributeVideo
            attributes = [
                DocumentAttributeVideo(
                    duration=int(duration),
                    w=width,
                    h=height,
                    supports_streaming=True
                )
            ]
            with open(final_file, 'rb') as video:
                logging.info(f"Отправка видео {url} ({platform}) {sender_info} в чат '{chat_title}' (тип: {chat_type})")
                await state.client.send_file(
                    chat_id,
                    video,
                    reply_to=message_id,
                    caption=platform,
                    attributes=attributes,
                    force_document=False
                )
            await state.client.delete_messages(chat_id, progress_msg.id)
            logging.info(f"Успешно отправлено видео {url} ({platform}) {sender_info} в чат '{chat_title}' (тип: {chat_type})")
            return True

    except Exception as e:
        # Проверяем, можно ли удалить сообщение с прогресс-баром
        try:
            await state.client.delete_messages(chat_id, progress_msg.id)
        except Exception as delete_error:
            logging.warning(f"Не удалось удалить сообщение с прогресс-баром в чате '{chat_title}': {delete_error}")
        logging.error(f"Ошибка отправки видео {url} ({platform}) {sender_info} в чат '{chat_title}' (тип: {chat_type}): {str(e)}")
        return False
    finally:
        # Удаляем временные файлы с повторными попытками
        for f in [temp_file, final_file]:
            if f and os.path.exists(f):
                for attempt in range(3):
                    try:
                        os.remove(f)
                        break
                    except PermissionError as e:
                        if "[WinError 32]" in str(e):
                            logging.warning(f"Файл {f} занят, повторная попытка {attempt + 1}/3...")
                            await asyncio.sleep(1)  # Задержка 1 секунда перед следующей попыткой
                        else:
                            logging.error(f"Не удалось удалить файл {f}: {str(e)}")
                            break
                    except Exception as e:
                        logging.error(f"Не удалось удалить файл {f}: {str(e)}")
                        break
                else:
                    logging.error(f"Не удалось удалить файл {f} после нескольких попыток")

async def process_video_link(chat_id, message_id, text, message):
    platform_settings = get_platform_settings()

    # Получаем информацию о чате для логирования
    try:
        chat_entity = await state.client.get_entity(chat_id)
        chat_title = chat_entity.title if hasattr(chat_entity, 'title') else f"{chat_entity.first_name or ''} {chat_entity.last_name or ''}".strip()
        chat_type = "Личный" if isinstance(chat_entity, User) else "Группа" if isinstance(chat_entity, Chat) else "Супергруппа" if isinstance(chat_entity, Channel) and chat_entity.megagroup else "Канал"
    except Exception as e:
        logging.error(f"Не удалось получить информацию о чате {chat_id} для логирования: {str(e)}")
        chat_title = "Неизвестный чат"
        chat_type = "Неизвестно"

    # Получаем информацию об отправителе
    try:
        sender = await message.get_sender()
        sender_info = f"для @{sender.username or 'нет_юзернейма'} {sender.first_name or ''} {sender.last_name or ''}".strip()
    except Exception as e:
        logging.error(f"Не удалось получить информацию об отправителе сообщения {message_id} в чате {chat_id}: {str(e)}")
        sender_info = "для неизвестного пользователя"

    for pattern_name, pattern in VIDEO_URL_PATTERNS.items():
        match = pattern.search(text)
        if not match or not platform_settings.get(pattern_name, False):
            continue
        video_id = match.group(1)

        if pattern_name == 'instagram':
            dd_url = f"https://www.ddinstagram.com/reel/{video_id}/"
            try:
                logging.info(f"Отправка ссылки Instagram Reels: {dd_url} {sender_info} в чат '{chat_title}' (тип: {chat_type})")
                await state.client.send_message(chat_id, f"{dd_url}\nInstagram Reels 📸", reply_to=message_id)
                logging.info(f"Успешно отправлена ссылка Instagram Reels: {dd_url} {sender_info} в чат '{chat_title}' (тип: {chat_type})")
            except Exception as e:
                logging.error(f"Ошибка отправки ссылки Instagram Reels: {dd_url} {sender_info} в чат '{chat_title}' (тип: {chat_type}): {str(e)}")

        elif pattern_name == 'tiktok':
            url = f"https://vm.tiktok.com/{video_id}"
            dd_url = f"https://vm.vxtiktok.com/{video_id}"
            temp_msg = None
            try:
                temp_msg = await state.client.send_message(chat_id, "Обрабатываю TikTok...", reply_to=message_id)
                # Ограничиваем экстракторы только TikTok
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extractor_list': ['tiktok'],  # Ограничиваем экстракторы
                }
                with contextlib.redirect_stderr(open(os.devnull, 'w')):
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        has_video = 'formats' in info and any(
                            f.get('vcodec') != 'none' and f.get('acodec') != 'none' 
                            for f in info.get('formats', [])) or info.get('is_live', False)
                if has_video:
                    logging.info(f"Отправка ссылки TikTok: {dd_url} {sender_info} в чат '{chat_title}' (тип: {chat_type})")
                    await state.client.edit_message(chat_id, temp_msg.id, f"{dd_url}\nTikTok 🎵")
                    logging.info(f"Успешно отправлена ссылка TikTok: {dd_url} {sender_info} в чат '{chat_title}' (тип: {chat_type})")
                else:
                    await state.client.delete_messages(chat_id, temp_msg.id)
                    logging.info(f"Ссылка TikTok отклонена: {dd_url} (нет видео-контента) {sender_info} в чат '{chat_title}' (тип: {chat_type})")
            except Exception as e:
                if temp_msg:
                    await state.client.delete_messages(chat_id, temp_msg.id)
                logging.error(f"Ошибка отправки ссылки TikTok: {dd_url} {sender_info} в чат '{chat_title}' (тип: {chat_type}): {str(e)}")

        elif pattern_name == 'youtube_shorts':
            url = f"https://youtube.com/shorts/{video_id}"
            await process_video(chat_id, message_id, url, "YouTube Shorts 📺", 300, message, sender_info)

        elif pattern_name == 'twitter':
            url = f"https://x.com/i/status/{video_id}"
            await process_video(chat_id, message_id, url, "Twitter (X) 🐦", 300, message, sender_info)

async def clean_temp_files():
    check_interval = 300  # 5 минут
    min_age = 600  # 10 минут (файлы старше 10 минут считаются устаревшими)
    # Папка temp-files (существующая)
    TEMP_FILES_DIR = TEMP_DIR  # Предполагается, что TEMP_DIR уже определён как temp-files
    # Папка temp для архивов обновлений
    UPDATE_TEMP_DIR = os.path.join(os.getcwd(), "temp")  # D:\VideoBot\temp
    # Корневая директория программы
    ROOT_DIR = os.getcwd()  # D:\VideoBot

    logging.info("Запущена фоновая очистка временных файлов")

    # Однократная очистка при запуске функции
    logging.info("Выполняется однократная очистка при запуске...")

    # 1. Очистка папки temp-files при запуске
    if os.path.exists(TEMP_FILES_DIR):
        for filename in os.listdir(TEMP_FILES_DIR):
            file_path = os.path.join(TEMP_FILES_DIR, filename)
            if os.path.isfile(file_path):
                for attempt in range(3):
                    try:
                        os.remove(file_path)
                        logging.info(f"Удалён файл в temp-files при запуске: {file_path}")
                        break
                    except PermissionError as e:
                        if "[WinError 32]" in str(e):
                            logging.warning(f"Файл {file_path} занят, повторная попытка {attempt + 1}/3...")
                            await asyncio.sleep(5)
                        else:
                            logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                            break
                    except Exception as e:
                        logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                        break

    # 2. Очистка папки temp при запуске
    if os.path.exists(UPDATE_TEMP_DIR):
        for filename in os.listdir(UPDATE_TEMP_DIR):
            file_path = os.path.join(UPDATE_TEMP_DIR, filename)
            if os.path.isfile(file_path):
                for attempt in range(3):
                    try:
                        os.remove(file_path)
                        logging.info(f"Удалён файл в temp при запуске: {file_path}")
                        break
                    except PermissionError as e:
                        if "[WinError 32]" in str(e):
                            logging.warning(f"Файл {file_path} занят, повторная попытка {attempt + 1}/3...")
                            await asyncio.sleep(5)
                        else:
                            logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                            break
                    except Exception as e:
                        logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                        break

    # 3. Удаление update.bat при запуске
    bat_path = os.path.join(ROOT_DIR, "update.bat")
    if os.path.exists(bat_path):
        for attempt in range(3):
            try:
                os.remove(bat_path)
                logging.info(f"Удалён update.bat при запуске: {bat_path}")
                break
            except PermissionError as e:
                if "[WinError 32]" in str(e):
                    logging.warning(f"Файл {bat_path} занят, повторная попытка {attempt + 1}/3...")
                    await asyncio.sleep(5)
                else:
                    logging.error(f"Не удалось удалить файл {bat_path}: {str(e)}")
                    break
            except Exception as e:
                logging.error(f"Не удалось удалить файл {bat_path}: {str(e)}")
                break

    # Основной цикл очистки
    while True:
        # 1. Очистка папки temp-files (существующая логика)
        if state.switch_is_on and os.path.exists(TEMP_FILES_DIR):
            for filename in os.listdir(TEMP_FILES_DIR):
                file_path = os.path.join(TEMP_FILES_DIR, filename)
                if os.path.isfile(file_path):
                    # Проверяем возраст файла
                    file_age = time.time() - os.path.getmtime(file_path)
                    if file_age < min_age:
                        logging.debug(f"Файл {file_path} слишком новый (возраст: {file_age:.2f} сек), пропускаем")
                        continue
                    for attempt in range(3):
                        try:
                            os.remove(file_path)
                            logging.info(f"Удалён устаревший файл в temp-files: {file_path}")
                            break
                        except PermissionError as e:
                            if "[WinError 32]" in str(e):
                                logging.warning(f"Файл {file_path} занят, повторная попытка {attempt + 1}/3...")
                                await asyncio.sleep(5)
                            else:
                                logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                                break
                        except Exception as e:
                            logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                            break

        # 2. Очистка папки temp (обновлённая логика с учётом возраста)
        if state.switch_is_on and os.path.exists(UPDATE_TEMP_DIR):
            for filename in os.listdir(UPDATE_TEMP_DIR):
                file_path = os.path.join(UPDATE_TEMP_DIR, filename)
                if os.path.isfile(file_path):
                    # Проверяем возраст файла
                    file_age = time.time() - os.path.getmtime(file_path)
                    if file_age < min_age:
                        logging.debug(f"Файл {file_path} слишком новый (возраст: {file_age:.2f} сек), пропускаем")
                        continue
                    for attempt in range(3):
                        try:
                            os.remove(file_path)
                            logging.info(f"Удалён устаревший файл в temp: {file_path}")
                            break
                        except PermissionError as e:
                            if "[WinError 32]" in str(e):
                                logging.warning(f"Файл {file_path} занят, повторная попытка {attempt + 1}/3...")
                                await asyncio.sleep(5)
                            else:
                                logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                                break
                        except Exception as e:
                            logging.error(f"Не удалось удалить файл {file_path}: {str(e)}")
                            break

        # 3. Очистка update.bat в корне программы
        if state.switch_is_on and os.path.exists(bat_path):
            # Проверяем возраст файла
            file_age = time.time() - os.path.getmtime(bat_path)
            if file_age < min_age:
                logging.debug(f"Файл {bat_path} слишком новый (возраст: {file_age:.2f} сек), пропускаем")
                continue
            for attempt in range(3):
                try:
                    os.remove(bat_path)
                    logging.info(f"Удалён устаревший update.bat: {bat_path}")
                    break
                except PermissionError as e:
                    if "[WinError 32]" in str(e):
                        logging.warning(f"Файл {bat_path} занят, повторная попытка {attempt + 1}/3...")
                        await asyncio.sleep(5)
                    else:
                        logging.error(f"Не удалось удалить файл {bat_path}: {str(e)}")
                        break
                except Exception as e:
                    logging.error(f"Не удалось удалить файл {bat_path}: {str(e)}")
                    break

        await asyncio.sleep(check_interval)

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setFixedSize(400, 300)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        self.setStyleSheet("background-color: #2F2F2F; color: #FFFFFF;")

        # Установка иконки для окна
        icon_path = "icons/256.ico"
        self.setWindowIcon(QIcon(icon_path))

        layout = QVBoxLayout(self)

        # Информация о программе
        info_label = QLabel(
            "<b>VideoBot</b><br><br>"
            f"Версия: {CURRENT_VERSION}<br>"
            "Разработчик: Drews<br><br>"
            # "Поддержите проект: <a href='https://donate.example.com' style='color: #FFFFFF'>Донат</a><br>"
            "Ссылка на исходную версию: <a href='https://github.com/drewssche/telegramVideoBot/releases/download/v1.0.0/VideoBot.zip' style='color: #FFFFFF'>Здесь</a><br><br>"
            "Связь:<br>"
            "<a href='https://t.me/muscle_junkie' style='color: #FFFFFF'>Telegram</a><br>"
            "<a href='mailto:schegolev.andrey.sergeevich@gmail.com' style='color: #FFFFFF'>Email</a>"
        )
        info_label.setOpenExternalLinks(True)
        info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(info_label)

        # Кнопка "Чейнджлог"
        changelog_button = QPushButton("Чейнджлог")
        changelog_button.setFixedWidth(180)  # Фиксированная ширина, как в AuthWindow
        changelog_button.setStyleSheet("""
            QPushButton {
                background-color: #505050;
                color: #FFFFFF;
                padding: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #606060;
            }
        """)
        changelog_button.clicked.connect(self.show_changelog)
        layout.addWidget(changelog_button, alignment=Qt.AlignCenter)

        self.setLayout(layout)

    def show_changelog(self):
        try:
            # Запрашиваем последний релиз через GitHub Releases API
            response = requests.get("https://api.github.com/repos/drewssche/telegramVideoBot/releases/latest")
            response.raise_for_status()
            release_data = response.json()
            version = release_data["tag_name"].lstrip("v")  # Например, "1.0.2"
            changelog = release_data.get("body", "Чейнджлог отсутствует")

            # Показываем чейнджлог
            changelog_dialog = ChangelogDialog(changelog, version, self)
            changelog_dialog.exec()
        except requests.exceptions.ConnectionError:
            logging.error("Ошибка подключения к интернету при запросе чейнджлога")
            QMessageBox.critical(self, "Ошибка", "Не удалось показать чейнджлог: проверьте подключение к интернету.")
        except requests.exceptions.HTTPError as http_err:
            logging.error(f"HTTP ошибка при запросе чейнджлога: {str(http_err)}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось показать чейнджлог: HTTP ошибка ({str(http_err)}).")
        except Exception as e:
            logging.error(f"Неизвестная ошибка при показе чейнджлога: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось показать чейнджлог: {str(e)}.")

class ChangelogDialog(QDialog):
    def __init__(self, changelog, version, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Что нового в версии {version}")
        self.setFixedSize(400, 300)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        self.setStyleSheet("background-color: #2F2F2F; color: #FFFFFF;")

        # Установка иконки для окна
        icon_path = "icons/256.ico"
        self.setWindowIcon(QIcon(icon_path))

        layout = QVBoxLayout(self)

        # Создаём QListWidget для отображения чейнджлога
        self.changelog_list = QListWidget()
        self.changelog_list.setStyleSheet("""
            QListWidget {
                background-color: #404040;
                color: #FFFFFF;
                border: 1px solid #505050;
            }
            QListWidget::item {
                padding: 5px;
            }
        """)
        self.changelog_list.setWordWrap(True)  # Включаем перенос текста
        layout.addWidget(self.changelog_list)

        # Обрабатываем чейнджлог
        self.populate_changelog(changelog)

        self.setLayout(layout)

    def populate_changelog(self, changelog):
        # Если changelog — это список (например, из version.json)
        if isinstance(changelog, list):
            for item in changelog:
                if item.strip():  # Пропускаем пустые строки
                    list_item = QListWidgetItem(f"• {item}")
                    self.changelog_list.addItem(list_item)
        # Если changelog — это строка (например, из GitHub API)
        elif isinstance(changelog, str):
            # Разделяем строку на строки и убираем пустые
            lines = [line.strip() for line in changelog.split("\n") if line.strip()]
            for line in lines:
                # Убираем возможные символы начала строки (например, "-", "*", "#") и лишние пробелы
                cleaned_line = re.sub(r'^[-*#\s]+', '', line).strip()
                if cleaned_line:  # Пропускаем пустые строки после очистки
                    list_item = QListWidgetItem(f"• {cleaned_line}")
                    self.changelog_list.addItem(list_item)
        # Если changelog пустой или некорректный
        if self.changelog_list.count() == 0:
            self.changelog_list.addItem("Чейнджлог отсутствует")

class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Обновление")
        self.setFixedSize(450, 180)
        self.setStyleSheet("background-color: #2F2F2F; color: #FFFFFF;")

        # Создаём layout
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        # Заголовок
        self.title_label = QLabel("Скачивание обновления...")
        self.title_label.setStyleSheet("""
            font-family: 'Segoe UI';
            font-size: 14px;
            font-weight: bold;
            color: #FFFFFF;
        """)
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #404040;
                color: #FFFFFF;
                text-align: center;
                font-family: 'Segoe UI';
                font-size: 12px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #00CC00;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Информация о размере
        self.size_label = QLabel("Загружено: 0.0 / 0.0 Мб")
        self.size_label.setStyleSheet("""
            font-family: 'Segoe UI';
            font-size: 12px;
            color: #D3D3D3;
        """)
        self.size_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.size_label)

        # Информация о скорости
        self.speed_label = QLabel("Скорость: 0.0 MiB/s")
        self.speed_label.setStyleSheet("""
            font-family: 'Segoe UI';
            font-size: 12px;
            color: #D3D3D3;
        """)
        self.speed_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.speed_label)

        # Кнопка "Отмена"
        self.cancel_button = QPushButton("🚫 Отмена")
        self.cancel_button.setFixedWidth(180)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #505050;
                color: #FFFFFF;
                font-family: 'Segoe UI';
                font-size: 12px;
                padding: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #606060;
            }
        """)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignCenter)

# Главное окно авторизации
class AuthWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Bot - Авторизация")
        self.setFixedSize(400, 300)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        # Установка иконки для окна
        icon_path = "icons/256.ico"
        self.setWindowIcon(QIcon(icon_path))

        widget = QWidget()
        self.setCentralWidget(widget)
        layout = QVBoxLayout(widget)

        self.phone_input = QLineEdit(self, placeholderText="Введите номер с +")
        phone_validator = QRegularExpressionValidator(QRegularExpression(r"^\+[0-9]*$"), self.phone_input)
        self.phone_input.setValidator(phone_validator)
        self.phone_input.textChanged.connect(self.update_phone_style)

        self.api_id_input = QLineEdit(self, placeholderText="Введите ваш API ID")
        self.api_hash_input = QLineEdit(self, placeholderText="Введите ваш API Hash")

        self.status_indicator = QLabel()
        self.update_status_indicator()

        self.progress_bar = QProgressBar(self, maximum=0, visible=False)

        button_layout = QHBoxLayout()
        self.connect_button = QPushButton("🔗 Подключиться", enabled=False)
        self.connect_button.setFixedWidth(180)
        self.connect_button.clicked.connect(self.on_connect)
        self.clear_button = QPushButton("🗑️ Удалить авторизацию")
        self.clear_button.setFixedWidth(180)
        self.clear_button.clicked.connect(self.start_clear_auth)
        button_layout.addWidget(self.connect_button)
        button_layout.addSpacing(10)
        button_layout.addWidget(self.clear_button)

        extra_button_layout = QHBoxLayout()
        self.help_button = QPushButton("ℹ️ Помощь")
        self.help_button.setFixedWidth(180)
        self.help_button.clicked.connect(self.show_help_dialog)
        self.update_button = QPushButton("🔄 Обновить")
        self.update_button.setFixedWidth(180)
        self.update_button.clicked.connect(self.on_update)
        self.update_button.setVisible(False)
        extra_button_layout.addWidget(self.help_button)
        extra_button_layout.addSpacing(10)
        extra_button_layout.addWidget(self.update_button)

        self.status_label = QLabel("", alignment=Qt.AlignCenter)

        layout.addWidget(QLabel("Телефон"))
        layout.addWidget(self.phone_input)
        layout.addWidget(QLabel("API ID"))
        layout.addWidget(self.api_id_input)
        layout.addWidget(QLabel("API Hash"))
        layout.addWidget(self.api_hash_input)
        layout.addWidget(self.status_indicator, alignment=Qt.AlignCenter)
        layout.addWidget(self.progress_bar)
        layout.addLayout(button_layout)
        layout.addLayout(extra_button_layout)
        layout.addWidget(self.status_label)

        self.version_label = QLabel(f"v {CURRENT_VERSION}")
        self.version_label.setStyleSheet("""
            color: #A0A0A0;
            font-size: 12px;
            text-decoration: underline;
        """)
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.version_label.mousePressEvent = self.show_about_dialog
        layout.addWidget(self.version_label)

        self.phone_input.textChanged.connect(self.update_connect_button)
        self.api_id_input.textChanged.connect(self.update_connect_button)
        self.api_hash_input.textChanged.connect(self.update_connect_button)

        auth_data = get_auth_data()
        if auth_data:
            self.phone_input.setText(auth_data[2])
            self.api_id_input.setText(str(auth_data[0]))
            self.api_hash_input.setText(auth_data[1])
        self.update_clear_button()

        self.check_for_updates()

    def update_phone_style(self):
        self.phone_input.setStyleSheet("background-color: #505050; color: #FFFFFF;" if self.phone_input.text().startswith("+") else "background-color: #404040; color: #FFFFFF;")

    def update_connect_button(self):
        self.connect_button.setEnabled(bool(self.phone_input.text() and self.api_id_input.text() and self.api_hash_input.text()))

    def update_clear_button(self):
        self.clear_button.setEnabled(get_auth_data() is not None or state.session_exists)

    def update_status_indicator(self):
        auth_data = get_auth_data()
        if state.session_exists:
            self.status_indicator.setText("Статус: Авторизован ✓")
            self.status_indicator.setStyleSheet("color: #00FF00;")
        elif auth_data:
            self.status_indicator.setText("Статус: Требуется вход ⚠")
            self.status_indicator.setStyleSheet("color: #FFFF00;")
        else:
            self.status_indicator.setText("Статус: Не авторизован ✗")
            self.status_indicator.setStyleSheet("color: #FF0000;")
        self.status_indicator.setVisible(False)
        QTimer.singleShot(50, lambda: self.status_indicator.setVisible(True))

    def validate_phone(self, phone):
        return phone.startswith("+") and phone[1:].isdigit()

    @asyncSlot()
    async def on_connect(self):
        phone, api_id, api_hash = self.phone_input.text(), self.api_id_input.text(), self.api_hash_input.text()
        if not self.validate_phone(phone):
            self.status_label.setText("Телефон должен начинаться с + и содержать только цифры")
            self.status_label.setStyleSheet("color: #FF0000")
            return

        self.status_label.setText("Подключение...")
        self.progress_bar.setVisible(True)
        self.connect_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        state.auth_data = (int(api_id), api_hash, phone)
        save_auth_data(int(api_id), api_hash, phone)
        state.client = TelegramClient('bot', int(api_id), api_hash)
        await state.client.connect()
        if not await state.client.is_user_authorized():
            await state.client.send_code_request(phone)
            self.status_label.setText("Ожидание кода...")
            self.progress_bar.setVisible(False)
            code_dialog = CodeDialog(self)
            code_dialog.code_submitted.connect(self.handle_code_submission)
            code_dialog.show()
        else:
            logging.info("Успешная авторизация с существующей сессией")
            self.on_successful_login()

    @asyncSlot(str)
    async def handle_code_submission(self, code):
        self.status_label.setText("Проверка кода...")
        self.progress_bar.setVisible(True)
        try:
            await state.client.sign_in(state.auth_data[2], code)
            logging.info("Успешная авторизация с кодом")
            self.on_successful_login()
        except Exception as e:
            self.progress_bar.setVisible(False)
            if "Two-step" in str(e):
                self.status_label.setText("Требуется пароль 2FA")
                two_fa_dialog = TwoFADialog(self)
                two_fa_dialog.password_submitted.connect(self.handle_2fa_submission)
                two_fa_dialog.show()
            else:
                self.status_label.setText(f"Ошибка: {str(e)}")
                self.status_label.setStyleSheet("color: #FF0000")
                self.connect_button.setEnabled(True)
                self.update_clear_button()

    @asyncSlot(str)
    async def handle_2fa_submission(self, password):
        self.status_label.setText("Проверка пароля...")
        self.progress_bar.setVisible(True)
        try:
            await state.client.sign_in(password=password)
            logging.info("Успешная авторизация с 2FA")
            self.on_successful_login()
        except Exception as e:
            self.progress_bar.setVisible(False)
            self.status_label.setText(f"Ошибка: {str(e)}")
            self.status_label.setStyleSheet("color: #FF0000")
            self.connect_button.setEnabled(True)
            self.update_clear_button()

    def start_clear_auth(self):
        asyncio.ensure_future(self.on_clear_auth())

    async def on_clear_auth(self):
        success = await clear_auth_data()
        state.session_exists = False
        self.phone_input.clear()
        self.api_id_input.clear()
        self.api_hash_input.clear()
        if success:
            self.status_label.setText("Авторизация удалена")
            self.status_label.setStyleSheet("color: #D3D3D3")
        else:
            self.status_label.setText("Авторизация удалена, но файл сессии не удалён")
            self.status_label.setStyleSheet("color: #FFFF00")
        self.update_clear_button()
        self.update_status_indicator()

    @asyncSlot()
    async def on_successful_login(self):
        self.status_label.setText("Авторизация успешна")
        self.progress_bar.setVisible(False)
        state.session_exists = os.path.exists('bot.session')
        # Кэшируем ID текущего пользователя
        try:
            me = await state.client.get_me()
            state.current_user_id = me.id
            logging.info(f"ID текущего пользователя сохранён: {state.current_user_id}")
        except Exception as e:
            logging.error(f"Не удалось получить ID текущего пользователя: {str(e)}")
            state.current_user_id = None
        self.update_status_indicator()
        QTimer.singleShot(1000, self.show_settings_window)

    def show_settings_window(self):
        self.close()
        self.settings_window = ChatSettingsWindow()
        self.settings_window.show()

    def show_help_dialog(self):
        help_dialog = HelpDialog(self)
        help_dialog.show()
        logging.info("Открыто окно помощи")

    def show_about_dialog(self, event):
        about_dialog = AboutDialog(self)
        about_dialog.show()
        logging.info("Открыто окно 'О программе'")

    def check_for_updates(self):
        logging.info("Начало проверки обновлений")
        try:
            api_url = "https://api.github.com/repos/drewssche/telegramVideoBot/releases/latest"
            logging.info(f"Запрос к GitHub API: {api_url}")
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()

            release_data = response.json()
            latest_version = release_data["tag_name"].lstrip("v")
            logging.info(f"Последняя версия на GitHub: {latest_version}")
            logging.info(f"Текущая версия программы: {CURRENT_VERSION}")

            if self.compare_versions(latest_version, CURRENT_VERSION) > 0:
                self.is_major_release = self.is_major_version(latest_version)

                # Ищем архив VideoBot_vX.Y.Z.zip
                asset = None
                asset_hash = None
                for asset in release_data["assets"]:
                    if asset["name"] == f"VideoBot_v{latest_version}.zip":
                        for hash_asset in release_data["assets"]:
                            if hash_asset["name"] == f"VideoBot_v{latest_version}.zip.sha256":
                                hash_response = requests.get(hash_asset["browser_download_url"])
                                hash_response.raise_for_status()
                                hash_text = hash_response.text.strip()
                                hash_lines = hash_text.splitlines()
                                for line in hash_lines:
                                    line = line.strip()
                                    if len(line) == 64 and all(c in "0123456789abcdefABCDEF" for c in line):
                                        asset_hash = line
                                        break
                                if not asset_hash:
                                    logging.error("Не удалось извлечь хэш из файла")
                                    self.status_label.setText("Не удалось проверить хэш релиза")
                                    self.status_label.setStyleSheet("color: #FFFF00")
                                    return
                                break
                        break

                if asset:
                    self.download_url = asset["browser_download_url"]
                    self.download_hash = asset_hash
                    self.is_full_update = True  # Всегда полное обновление
                    logging.info(f"URL для скачивания: {self.download_url}")
                    logging.info(f"Хэш архива: {self.download_hash}")
                else:
                    logging.error(f"Архив VideoBot_v{latest_version}.zip не найден")
                    self.status_label.setText(f"Архив для версии {latest_version} не найден")
                    self.status_label.setStyleSheet("color: #FFFF00")
                    return

                self.changelog = release_data.get("body", "Чейнджлог отсутствует")
                self.new_version = latest_version
                self.update_button.setVisible(True)
                self.status_label.setText(f"Доступна новая версия: {latest_version}")
                self.status_label.setStyleSheet("color: #00FF00")
            else:
                logging.info("Установлена последняя версия")
                self.status_label.setText("У вас последняя версия")
                self.status_label.setStyleSheet("color: #D3D3D3")
        except requests.exceptions.ConnectionError:
            logging.error("Ошибка подключения к интернету при проверке обновлений")
            self.status_label.setText("Не удалось проверить обновления: нет интернета")
            self.status_label.setStyleSheet("color: #FFFF00")
        except requests.exceptions.HTTPError as http_err:
            logging.error(f"HTTP ошибка при проверке обновлений: {str(http_err)}")
            self.status_label.setText("Не удалось проверить обновления: ошибка HTTP")
            self.status_label.setStyleSheet("color: #FFFF00")
        except Exception as e:
            logging.error(f"Ошибка проверки обновлений: {str(e)}")
            self.status_label.setText("Не удалось проверить обновления")
            self.status_label.setStyleSheet("color: #FFFF00")

    def compare_versions(self, version1, version2):
        v1_parts = list(map(int, version1.split(".")))
        v2_parts = list(map(int, version2.split(".")))
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1 = v1_parts[i] if i < len(v1_parts) else 0
            v2 = v2_parts[i] if i < len(v2_parts) else 0
            if v1 > v2:
                return 1
            elif v1 < v2:
                return -1
        return 0

    def is_major_version(self, version):
        parts = list(map(int, version.split(".")))
        return parts[1] == 0 and parts[2] == 0

    def on_update(self):
        # Останавливаем все активные задачи
        for task in state.active_tasks:
            task.cancel()
        state.active_tasks.clear()
        logging.info("Все активные задачи завершены перед началом обновления")

        # Проверка прав доступа в текущую директорию
        if not self.check_write_permissions():
            logging.error("Недостаточно прав на запись в текущую директорию")
            QMessageBox.critical(
                self,
                "Ошибка",
                "Недостаточно прав для обновления. Пожалуйста, запустите программу от имени администратора."
            )
            return

        # Логируем информацию об обновлении
        logging.info(f"Начало обновления до версии {self.new_version}")
        logging.info(f"URL для скачивания: {self.download_url}")
        logging.info(f"Ожидаемый хэш: {self.download_hash}")

        # Создаём кастомный диалог
        progress = UpdateDialog(self)

        # Переменные для отслеживания размера и скорости
        total_size_mb = 0
        downloaded_size_mb = 0
        last_downloaded_mb = 0
        last_update_time = time.time()

        # Получаем информацию о последнем релизе через GitHub API
        try:
            # Запрос к API для получения последнего релиза
            api_url = "https://api.github.com/repos/drewssche/telegramVideoBot/releases/latest"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            release_data = response.json()

            # Извлекаем URL для скачивания и размер файла
            for asset in release_data.get("assets", []):
                if asset["name"].endswith(".zip"):  # Предполагаем, что это ZIP-файл
                    self.download_url = asset["browser_download_url"]
                    total_size_bytes = asset["size"]
                    total_size_mb = total_size_bytes / (1024 * 1024)  # Переводим в Мб
                    progress.size_label.setText(f"Загружено: 0.0 / {total_size_mb:.1f} Мб")
                    break
            else:
                logging.warning("Не удалось найти подходящий актив в последнем релизе")
                progress.size_label.setText("Загружено: 0.0 / Неизвестно")
        except Exception as e:
            logging.error(f"Не удалось получить информацию о релизе через GitHub API: {str(e)}")
            progress.size_label.setText("Загружено: 0.0 / Неизвестно")

        # Функция для обновления информации о загрузке
        def update_download_info(value):
            nonlocal downloaded_size_mb
            # Обновляем процент и цвет текста
            progress.progress_bar.setValue(value)
            if value < 50:
                progress.progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: none;
                        background-color: #404040;
                        color: #FFFFFF;
                        text-align: center;
                        font-family: 'Segoe UI';
                        font-size: 12px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #00CC00;
                    }
                """)
            else:
                progress.progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: none;
                        background-color: #404040;
                        color: #000000;
                        text-align: center;
                        font-family: 'Segoe UI';
                        font-size: 12px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #00CC00;
                    }
                """)

            # Обновляем информацию о размере
            if total_size_mb > 0:
                downloaded_size_mb = (value / 100) * total_size_mb
                progress.size_label.setText(f"Загружено: {downloaded_size_mb:.1f} / {total_size_mb:.1f} Мб")
            else:
                progress.size_label.setText(f"Загружено: {downloaded_size_mb:.1f} / Неизвестно")

        # Функция для расчёта скорости на основе загруженных байтов
        def update_download_speed(downloaded_bytes):
            nonlocal downloaded_size_mb, last_downloaded_mb, last_update_time
            downloaded_size_mb = downloaded_bytes / (1024 * 1024)  # Переводим байты в Мб
            if total_size_mb == 0:  # Если размер неизвестен, обновляем только загруженное
                progress.size_label.setText(f"Загружено: {downloaded_size_mb:.1f} / Неизвестно")

            # Обновляем скорость
            current_time = time.time()
            time_diff = current_time - last_update_time
            if time_diff >= 1.0:  # Обновляем скорость каждую секунду
                downloaded_diff = downloaded_size_mb - last_downloaded_mb
                speed_mib_s = downloaded_diff / time_diff
                progress.speed_label.setText(f"Скорость: {speed_mib_s:.1f} MiB/s")
                last_downloaded_mb = downloaded_size_mb
                last_update_time = current_time

        # Создаём директорию temp, если её нет
        os.makedirs("temp", exist_ok=True)
        zip_path = os.path.join("temp", f"VideoBot_update_{self.new_version}.zip")
        logging.info(f"Скачивание обновления в {zip_path} с URL: {self.download_url}")

        # Запускаем поток скачивания
        self.download_thread = DownloadThread(self.download_url, zip_path)
        self.download_thread.progress.connect(update_download_info)
        self.download_thread.downloadedBytes.connect(update_download_speed)  # Подключаем новый сигнал
        self.download_thread.finished.connect(lambda success, error: self.on_download_finished(success, error, progress, zip_path))
        self.download_thread.finished.connect(progress.close)  # Закрываем диалог после завершения
        self.download_thread.start()

        # Подключаем кнопку "Отмена"
        progress.cancel_button.clicked.connect(self.download_thread.terminate)
        progress.cancel_button.clicked.connect(progress.close)

        progress.exec_()

    def on_download_finished(self, success, error, progress, zip_path):
        # Функция проверки прав администратора
        def is_admin():
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except:
                return False

        # Закрываем окно прогресса
        progress.close()
        if not success:
            logging.error(f"Ошибка скачивания: {error}")
            self.show_notification(error, "error")
            return

        # Проверяем, запущена ли программа с правами администратора
        if not is_admin():
            logging.error("Программа не запущена с правами администратора")
            self.show_notification(
                "Программа должна быть запущена от имени администратора для выполнения обновления.",
                "error"
            )
            return

        # Добавляем задержку, чтобы дать системе время обработать файл
        logging.info("Ожидание завершения записи файла на диск...")
        time.sleep(2)

        # Проверяем хэш архива
        logging.info("Скачивание завершено успешно, проверка хэша архива")
        if not self.validate_archive(zip_path, self.download_hash):
            logging.error("Валидация архива не пройдена")
            return

        # Проверяем текущую директорию
        current_dir = os.getcwd()
        if not os.path.exists(os.path.join(current_dir, "version.json")):
            logging.error("Файл version.json не найден в текущей директории. Убедитесь, что программа запущена из правильной папки.")
            self.show_notification(
                "Файл version.json не найден. Убедитесь, что программа запущена из папки VideoBot.",
                "error"
            )
            return

        # Проверяем, что архив существует
        if not os.path.exists(zip_path):
            logging.error(f"Архив не найден: {zip_path}")
            self.show_notification(f"Архив не найден: {zip_path}", "error")
            return

        # Проверяем содержимое архива
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                exe_in_zip = None
                for f in zip_ref.namelist():
                    if os.path.basename(f) == "VideoBot.exe":
                        exe_in_zip = f
                        break
                if not exe_in_zip:
                    logging.error("Архив не содержит VideoBot.exe")
                    self.show_notification("Архив не содержит VideoBot.exe. Обновление невозможно.", "error")
                    return
        except zipfile.BadZipFile as e:
            logging.error(f"Не удалось проверить содержимое архива: {str(e)}")
            self.show_notification(f"Не удалось проверить содержимое архива: {str(e)}.", "error")
            return

        try:
            bat_path = os.path.join(current_dir, "update.bat")

            # Проверяем наличие 7z.exe
            use_7z = False
            possible_7z_paths = [
                "C:\\Program Files\\7-Zip\\7z.exe",
                "C:\\Program Files (x86)\\7-Zip\\7z.exe",
            ]

            for path in possible_7z_paths:
                if os.path.exists(path):
                    try:
                        result = subprocess.run([path, "--help"], capture_output=True, text=True)
                        if result.returncode == 0:
                            logging.info(f"7z.exe найден по пути: {path}")
                            use_7z = True
                            self._7z_path = path
                            break
                    except Exception as e:
                        logging.warning(f"Не удалось проверить 7z.exe по пути {path}: {str(e)}")
                else:
                    logging.debug(f"7z.exe не найден по пути: {path}")

            # Формируем содержимое update.bat
            if not use_7z:
                logging.warning("7z.exe не найден. Используем powershell для извлечения архива.")
                bat_content = f"""@echo off
                    chcp 65001 >nul
                    echo [%date% %time%] Начало выполнения update.bat >> update.log 2>&1

                    :: Принудительное завершение VideoBot.exe
                    echo [%date% %time%] Завершение процесса VideoBot.exe >> update.log 2>&1
                    taskkill /F /IM VideoBot.exe >> update.log 2>&1
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Предупреждение: Процесс VideoBot.exe не найден или уже завершён >> update.log 2>&1
                    )

                    :: Задержка 3 секунды перед началом обновления
                    timeout /t 3 /nobreak >nul
                    echo [%date% %time%] Задержка перед началом распаковки завершена >> update.log 2>&1

                    :: Проверка текущей директории
                    echo [%date% %time%] Текущая директория: %CD% >> update.log 2>&1

                    :: Распаковка архива в текущую директорию
                    echo [%date% %time%] Распаковка архива {zip_path} >> update.log 2>&1
                    powershell -Command "Expand-Archive -Path '{zip_path}' -DestinationPath '.' -Force" >> update.log 2>&1
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Ошибка: Не удалось распаковать архив >> update.log 2>&1
                        exit /b 1
                    )
                    echo [%date% %time%] Архив успешно распакован >> update.log 2>&1

                    :: Обновление version.json
                    echo [%date% %time%] Обновление version.json >> update.log 2>&1
                    echo {{"version": "{self.new_version}"}} > "version.json" 2>> update.log
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Ошибка: Не удалось обновить version.json >> update.log 2>&1
                        exit /b 1
                    )
                    echo [%date% %time%] Файл version.json обновлён >> update.log 2>&1

                    :: Задержка перед запуском новой версии
                    timeout /t 2 /nobreak >nul

                    :: Запуск новой версии
                    echo [%date% %time%] Запуск новой версии VideoBot.exe >> update.log 2>&1
                    start /B "" "VideoBot.exe" >> update.log 2>&1
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Ошибка: Не удалось запустить новую версию >> update.log 2>&1
                        exit /b 1
                    )
                    echo [%date% %time%] Новая версия запущена >> update.log 2>&1
                    """
            else:
                # Используем 7z.exe для извлечения архива
                bat_content = f"""@echo off
                    chcp 65001 >nul
                    echo [%date% %time%] Начало выполнения update.bat >> update.log 2>&1

                    :: Принудительное завершение VideoBot.exe
                    echo [%date% %time%] Завершение процесса VideoBot.exe >> update.log 2>&1
                    taskkill /F /IM VideoBot.exe >> update.log 2>&1
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Предупреждение: Процесс VideoBot.exe не найден или уже завершён >> update.log 2>&1
                    )

                    :: Задержка 3 секунды перед началом обновления
                    timeout /t 3 /nobreak >nul
                    echo [%date% %time%] Задержка перед началом распаковки завершена >> update.log 2>&1

                    :: Проверка текущей директории
                    echo [%date% %time%] Текущая директория: %CD% >> update.log 2>&1

                    :: Распаковка архива с помощью 7z.exe
                    echo [%date% %time%] Распаковка архива {zip_path} >> update.log 2>&1
                    "{self._7z_path}" x "{zip_path}" -o"." -y >> update.log 2>&1
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Ошибка: Не удалось распаковать архив с помощью 7z.exe >> update.log 2>&1
                        exit /b 1
                    )
                    echo [%date% %time%] Архив успешно распакован >> update.log 2>&1

                    :: Обновление version.json
                    echo [%date% %time%] Обновление version.json >> update.log 2>&1
                    echo {{"version": "{self.new_version}"}} > "version.json" 2>> update.log
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Ошибка: Не удалось обновить version.json >> update.log 2>&1
                        exit /b 1
                    )
                    echo [%date% %time%] Файл version.json обновлён >> update.log 2>&1

                    :: Задержка перед запуском новой версии
                    timeout /t 2 /nobreak >nul

                    :: Запуск новой версии
                    echo [%date% %time%] Запуск новой версии VideoBot.exe >> update.log 2>&1
                    start /B "" "VideoBot.exe" >> update.log 2>&1
                    if %ERRORLEVEL% neq 0 (
                        echo [%date% %time%] Ошибка: Не удалось запустить новую версию >> update.log 2>&1
                        exit /b 1
                    )
                    echo [%date% %time%] Новая версия запущена >> update.log 2>&1
                    """

            # Создаём update.bat
            logging.info(f"Создание скрипта обновления: {bat_path}")
            with open(bat_path, "w", encoding="utf-8") as bat_file:
                bat_file.write(bat_content)

            # Останавливаем все активные задачи и отключаем Telegram-клиент
            for task in state.active_tasks:
                task.cancel()
            state.active_tasks.clear()
            logging.info("Все активные задачи завершены")

            if state.client is not None:
                try:
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(state.client.disconnect())
                    logging.info("Клиент Telegram успешно отключён перед обновлением")
                except Exception as e:
                    logging.error(f"Ошибка при отключении клиента Telegram: {str(e)}")
                finally:
                    state.client = None

            # Запускаем update.bat через команду start с задержкой
            logging.info("Запуск скрипта обновления через команду start")
            try:
                # Используем команду start с ping для создания задержки 3 секунды
                command = f'start "" cmd /c "ping 127.0.0.1 -n 4 > nul & "{bat_path}""'
                os.system(command)
                logging.info("Скрипт обновления успешно запущен через команду start")
            except Exception as e:
                logging.error(f"Не удалось запустить update.bat через команду start: {str(e)}")
                self.show_notification(
                    f"Не удалось запустить скрипт обновления: {str(e)}",
                    "error"
                )
                return

            # Закрываем приложение сразу после запуска update.bat
            logging.info("Закрытие приложения")
            self.close()  # Закрываем текущее окно
            QApplication.quit()
            logging.info("Принудительное завершение программы")
            sys.exit(0)

        except Exception as e:
            logging.error(f"Ошибка при выполнении обновления: {str(e)}")
            self.show_notification(f"Ошибка при выполнении обновления: {str(e)}.", "error")

    def handle_update_error(self, error_message):
        try:
            with open("version.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                full_release_url = data.get("last_full_release_url", "")
        except Exception as e:
            logging.error(f"Не удалось прочитать last_full_release_url из version.json: {str(e)}")
            full_release_url = ""

        if full_release_url:
            message = (
                f"Не удалось установить обновление: {error_message}\n\n"
                "Попробуйте скачать полный релиз:\n"
                f"<a href='{full_release_url}' style='color: #FFFFFF'>{full_release_url}</a>"
            )
        else:
            message = (
                f"Не удалось установить обновление: {error_message}\n\n"
                "Пожалуйста, скачайте последний полный релиз вручную с GitHub:\n"
                "<a href='https://github.com/drewssche/telegramVideoBot/releases' style='color: #FFFFFF'>GitHub Releases</a>"
            )

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Ошибка обновления")
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

        if os.path.exists("temp"):
            shutil.rmtree("temp", ignore_errors=True)

    def show_changelog_if_needed(self):
        try:
            if hasattr(self, "changelog") and hasattr(self, "new_version"):
                if self.compare_versions(self.new_version, CURRENT_VERSION) > 0:
                    changelog_dialog = ChangelogDialog(self.changelog, self.new_version, self)
                    changelog_dialog.exec()
        except Exception as e:
            logging.error(f"Неизвестная ошибка при показе чейнджлога: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось показать чейнджлог: {str(e)}.")

    def check_write_permissions(self):
        """Проверяет права на запись в текущую директорию."""
        try:
            test_file = os.path.join(os.getcwd(), "test_write.txt")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            logging.info("Права на запись в текущую директорию подтверждены")
            return True
        except (PermissionError, OSError) as e:
            logging.error(f"Ошибка проверки прав на запись: {str(e)}")
            self.show_notification(
                "Нет прав на запись в текущую директорию. Запустите программу от имени администратора.",
                "error"
            )
            return False

    def handle_permission_error(self):
        """Обрабатывает отсутствие прав на запись, показывая диалог с опциями."""
        msg = QMessageBox()
        msg.setWindowTitle("Ошибка прав доступа")
        msg.setText(
            "Программе требуются права на запись в текущую директорию для установки обновления.\n"
            "Пожалуйста, выберите действие:"
        )
        msg.setIcon(QMessageBox.Warning)
        run_as_admin = msg.addButton("Запустить с правами администратора", QMessageBox.ActionRole)
        choose_dir = msg.addButton("Выбрать другую директорию", QMessageBox.ActionRole)
        cancel = msg.addButton("Отменить", QMessageBox.RejectRole)
        msg.exec()

        if msg.clickedButton() == run_as_admin:
            # Перезапуск с правами администратора
            try:
                subprocess.run(
                    ["powershell", "Start-Process", sys.executable, "-Verb", "runAs"],
                    check=True
                )
                sys.exit(0)  # Закрываем текущий процесс
            except subprocess.CalledProcessError:
                self.status_label.setText("Не удалось перезапустить с правами администратора")
                self.status_label.setStyleSheet("color: #FF0000")
                return False
        elif msg.clickedButton() == choose_dir:
            # Выбор другой директории
            new_dir = QFileDialog.getExistingDirectory(
                None, "Выберите директорию для установки", os.path.expanduser("~")
            )
            if new_dir:
                try:
                    # Копируем программу в новую директорию
                    shutil.copytree(os.getcwd(), new_dir, dirs_exist_ok=True)
                    os.chdir(new_dir)  # Меняем текущую директорию
                    self.status_label.setText(f"Программа перемещена в {new_dir}. Повторите обновление")
                    self.status_label.setStyleSheet("color: #00FF00")
                    return True
                except (shutil.Error, OSError) as e:
                    self.status_label.setText(f"Не удалось скопировать программу: {str(e)}")
                    self.status_label.setStyleSheet("color: #FF0000")
                    return False
            else:
                self.status_label.setText("Директория не выбрана")
                self.status_label.setStyleSheet("color: #FFFF00")
                return False
        else:
            # Отмена обновления
            self.status_label.setText("Обновление отменено")
            self.status_label.setStyleSheet("color: #FFFF00")
            return False

    def compute_file_hash(self, file_path, hash_algorithm=hashlib.sha256):
        """Вычисляет хэш-сумму файла."""
        try:
            hash_obj = hash_algorithm()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except PermissionError as e:
            logging.error(f"Нет прав на чтение файла для вычисления хэша: {file_path}, ошибка: {str(e)}")
            raise
        except IOError as e:
            logging.error(f"Ошибка ввода-вывода при чтении файла для вычисления хэша: {file_path}, ошибка: {str(e)}")
            raise
        except Exception as e:
            logging.error(f"Неожиданная ошибка при вычислении хэша файла {file_path}: {str(e)}")
            raise

    def show_notification(self, message, type_="info"):
        """Показывает уведомление пользователю."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Уведомление")
        msg_box.setText(message)
        if type_ == "error":
            msg_box.setIcon(QMessageBox.Critical)
        elif type_ == "warning":
            msg_box.setIcon(QMessageBox.Warning)
        else:
            msg_box.setIcon(QMessageBox.Information)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    def validate_archive(self, zip_path, expected_hash=None):
        """Проверяет целостность и содержимое архива."""
        # Проверка хэш-суммы, если она предоставлена
        if expected_hash:
            try:
                computed_hash = self.compute_file_hash(zip_path)
                if computed_hash.lower() != expected_hash.lower():
                    logging.error(f"Хэш-сумма не совпадает: ожидалось {expected_hash}, вычислено {computed_hash}")
                    self.show_notification(
                        "Скачанный архив повреждён: хэш-сумма не совпадает.",
                        "error"
                    )
                    return False
            except Exception as e:
                logging.error(f"Ошибка при вычислении хэша архива {zip_path}: {str(e)}")
                self.show_notification(
                    f"Не удалось проверить хэш-сумму архива: {str(e)}.",
                    "error"
                )
                return False

        # Проверка содержимого архива
        expected_files = ["VideoBot.exe", "version.json"]
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_contents = zip_ref.namelist()
                # Логируем содержимое архива для диагностики
                for expected_file in expected_files:
                    # Проверяем, есть ли файл в архиве (включая подпапки)
                    found = any(expected_file == os.path.basename(f) for f in zip_contents)
                    if not found:
                        logging.error(f"Архив не содержит файл: {expected_file}")
                        self.show_notification(
                            f"Архив не содержит необходимый файл: {expected_file}.",
                            "error"
                        )
                        return False
                return True
        except zipfile.BadZipFile as e:
            logging.error(f"Архив повреждён или не является ZIP-файлом: {str(e)}")
            self.show_notification("Архив повреждён или не является ZIP-файлом.", "error")
            return False
        except Exception as e:
            logging.error(f"Неожиданная ошибка при проверке содержимого архива {zip_path}: {str(e)}")
            self.show_notification(
                f"Не удалось проверить содержимое архива: {str(e)}.",
                "error"
            )
            return False

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Помощь")
        self.setFixedSize(600, 500)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        self.setModal(False)

        layout = QVBoxLayout(self)
        tab_widget = QTabWidget()

        # Применяем stylesheet для QTabWidget
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                background-color: #2F2F2F;  /* Цвет фона вкладок */
                border: none;
            }
            QTabBar::tab {
                background-color: #2F2F2F;  /* Цвет фона неактивной вкладки */
                color: #FFFFFF;             /* Цвет текста вкладок */
                padding: 5px;
                border: none;
            }
            QTabBar::tab:hover {
                background-color: #606060;  /* Цвет при наведении */
            }
            QTabBar::tab:selected {
                background-color: #505050;  /* Цвет фона активной вкладки */
                color: #FFFFFF;             /* Цвет текста активной вкладки */
            }
        """)

        # Загрузка содержимого
        try:
            help_content = self.load_help_content()
        except Exception as e:
            # Если не удалось загрузить содержимое, показываем сообщение об ошибке
            error_label = QLabel(f"Не удалось загрузить содержимое справки: {str(e)}")
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: #FF0000;")  # Красный цвет для ошибки
            layout.addWidget(error_label)
            self.setLayout(layout)
            return

        # Вкладки
        for tab_data in help_content.values():
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            content = tab_data.get("content", "Нет данных")
            # Добавляем стиль для отступов между <li>
            content = content.replace("<li>", "<li style='margin-bottom: 15px;'>")
            label = QLabel(content)
            label.setWordWrap(True)
            label.setOpenExternalLinks(True)  # Для кликабельных ссылок
            # Применяем стили к QLabel
            label.setStyleSheet("""
                color: #FFFFFF;  /* Цвет текста (кроме ссылок) */
                font-size: 16px;  /* Размер текста */
                line-height: 1.8;  /* Расстояние между строками */
            """)
            # Дополнительно увеличиваем размер заголовков (<b>)
            label.setTextFormat(Qt.RichText)
            label.setText(content.replace("<b>", "<b style='font-size: 18px;'>"))
            tab_layout.addWidget(label)

            # Извлекаем название вкладки из содержимого (из <b>Название</b>)
            import re
            match = re.search(r"<b>(.*?)</b>", content)
            tab_name = match.group(1) if match else "Без названия"

            # Получаем иконку
            icon = tab_data.get("icon", "")

            # Добавляем вкладку
            tab_widget.addTab(tab, f"{icon} {tab_name}")

        layout.addWidget(tab_widget)
        self.setLayout(layout)

    def load_help_content(self):
        with open("help_content.json", "r", encoding="utf-8") as f:
            return json.load(f)

class CodeDialog(QDialog):
    code_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Введите код")
        self.setFixedSize(300, 200)  # Устанавливаем фиксированный размер
        # Центрируем окно
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        # Остальной код остаётся без изменений
        layout = QVBoxLayout()
        self.code_input = QLineEdit(self, placeholderText="Введите код из Telegram")
        self.submit_button = QPushButton("Подтвердить")
        self.submit_button.clicked.connect(self.on_submit)
        self.error_label = QLabel("", styleSheet="color: #FF0000")
        self.status_label = QLabel("")
        layout.addWidget(QLabel("Код"))
        layout.addWidget(self.code_input)
        layout.addWidget(self.submit_button)
        layout.addWidget(self.error_label)
        layout.addWidget(self.status_label)
        self.setLayout(layout)
        self.code_input.textChanged.connect(self.update_submit_button)

    def update_submit_button(self):
        self.submit_button.setEnabled(bool(self.code_input.text()))

    def on_submit(self):
        self.code_submitted.emit(self.code_input.text())
        self.close()

class TwoFADialog(QDialog):
    password_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Введите пароль 2FA")
        self.setFixedSize(300, 200)  # Устанавливаем фиксированный размер
        # Центрируем окно
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        # Остальной код остаётся без изменений
        layout = QVBoxLayout()
        self.password_input = QLineEdit(self, placeholderText="Введите пароль 2FA (если есть)")
        self.submit_button = QPushButton("Подтвердить")
        self.submit_button.clicked.connect(self.on_submit)
        self.error_label = QLabel("", styleSheet="color: #FF0000")
        self.status_label = QLabel("")
        layout.addWidget(QLabel("Пароль"))
        layout.addWidget(self.password_input)
        layout.addWidget(self.submit_button)
        layout.addWidget(self.error_label)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

    def on_submit(self):
        self.password_submitted.emit(self.password_input.text())
        self.close()

class ChatSettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Bot - Настройка чатов")
        self.setFixedSize(800, 600)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        # Установка иконки для окна
        icon_path = "icons/256.ico"
        self.setWindowIcon(QIcon(icon_path))

        widget = QWidget()
        self.setCentralWidget(widget)
        main_layout = QHBoxLayout(widget)

        left_layout = QVBoxLayout()
        # Общие чаты: метка и эмодзи
        all_chats_header_layout = QHBoxLayout()
        self.all_chats_label = QLabel("Общие чаты: 0")
        self.all_chats_spinner = QLabel("⏳")
        self.all_chats_spinner.setFixedSize(16, 16)
        self.all_chats_spinner.setVisible(False)
        all_chats_header_layout.addWidget(self.all_chats_label)
        all_chats_header_layout.addWidget(self.all_chats_spinner)
        left_layout.addLayout(all_chats_header_layout)

        self.all_chats_search = QLineEdit(placeholderText="Поиск по чатам")
        self.all_chats_search.textChanged.connect(self.filter_all_chats)
        left_layout.addWidget(self.all_chats_search)

        all_chats_filter_group = QGroupBox()
        all_chats_filter_layout = QHBoxLayout()
        self.all_chats_all = QRadioButton("Все", checked=True)
        self.all_chats_groups = QRadioButton("Групповые")
        self.all_chats_channels = QRadioButton("Каналы")
        self.all_chats_private = QRadioButton("Лички")
        all_chats_filter_layout.addWidget(self.all_chats_all)
        all_chats_filter_layout.addWidget(self.all_chats_groups)
        all_chats_filter_layout.addWidget(self.all_chats_channels)
        all_chats_filter_layout.addWidget(self.all_chats_private)
        all_chats_filter_group.setLayout(all_chats_filter_layout)
        left_layout.addWidget(all_chats_filter_group)

        self.all_chats_list = QListWidget(maximumHeight=15 * 20)
        self.all_chats_list.itemSelectionChanged.connect(self.update_buttons_and_info)
        left_layout.addWidget(self.all_chats_list)

        all_chats_buttons = QHBoxLayout()
        self.add_all_button = QPushButton("Добавить все")
        self.add_button = QPushButton("Добавить", enabled=False)
        self.refresh_all_button = QPushButton("Обновить")
        self.refresh_all_button.setToolTip("Обновить список всех доступных чатов")  # Подсказка
        all_chats_buttons.addWidget(self.add_all_button)
        all_chats_buttons.addWidget(self.add_button)
        all_chats_buttons.addWidget(self.refresh_all_button)
        left_layout.addLayout(all_chats_buttons)

        # Добавленные чаты: метка и эмодзи
        selected_chats_header_layout = QHBoxLayout()
        self.selected_chats_label = QLabel("Добавленные чаты: 0")
        self.selected_chats_spinner = QLabel("⏳")
        self.selected_chats_spinner.setFixedSize(16, 16)
        self.selected_chats_spinner.setVisible(False)
        selected_chats_header_layout.addWidget(self.selected_chats_label)
        selected_chats_header_layout.addWidget(self.selected_chats_spinner)
        left_layout.addLayout(selected_chats_header_layout)

        self.selected_chats_search = QLineEdit(placeholderText="Поиск по добавленным чатам")
        self.selected_chats_search.textChanged.connect(self.filter_selected_chats)
        left_layout.addWidget(self.selected_chats_search)

        selected_chats_filter_group = QGroupBox()
        selected_chats_filter_layout = QHBoxLayout()
        self.selected_all = QRadioButton("Все", checked=True)
        self.selected_groups = QRadioButton("Групповые")
        self.selected_channels = QRadioButton("Каналы")
        self.selected_private = QRadioButton("Лички")
        selected_chats_filter_layout.addWidget(self.selected_all)
        selected_chats_filter_layout.addWidget(self.selected_groups)
        selected_chats_filter_layout.addWidget(self.selected_channels)
        selected_chats_filter_layout.addWidget(self.selected_private)
        selected_chats_filter_group.setLayout(selected_chats_filter_layout)
        left_layout.addWidget(selected_chats_filter_group)

        self.selected_chats_list = QListWidget(maximumHeight=10 * 20)
        self.selected_chats_list.itemSelectionChanged.connect(self.update_buttons_and_info)
        left_layout.addWidget(self.selected_chats_list)

        selected_chats_buttons = QHBoxLayout()
        self.remove_all_button = QPushButton("Удалить все")
        self.remove_button = QPushButton("Удалить", enabled=False)
        self.refresh_selected_button = QPushButton("Обновить")
        self.refresh_selected_button.setToolTip("Обновить список добавленных чатов, удалить недоступные")  # Подсказка
        selected_chats_buttons.addWidget(self.remove_all_button)
        selected_chats_buttons.addWidget(self.remove_button)
        selected_chats_buttons.addWidget(self.refresh_selected_button)
        left_layout.addLayout(selected_chats_buttons)

        navigation_buttons = QHBoxLayout()
        self.next_button = QPushButton("Далее ➡️")
        self.next_button.setObjectName("next_button")
        self.next_button.setFixedSize(125, 40)
        self.back_button = QPushButton("⬅️ Назад")
        self.back_button.setObjectName("back_button")
        self.back_button.setFixedSize(125, 40)
        navigation_buttons.addWidget(self.back_button)
        navigation_buttons.addStretch()
        navigation_buttons.addWidget(self.next_button)
        left_layout.addLayout(navigation_buttons)

        # Уведомление "Данные обновлены!"
        self.update_notification = QLabel("Данные обновлены!", alignment=Qt.AlignCenter)
        self.update_notification.setStyleSheet("color: #00FF00;")
        self.update_notification.setVisible(False)
        left_layout.addWidget(self.update_notification)

        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()
        self.chat_info_group = QGroupBox("Информация о чате")
        chat_info_layout = QVBoxLayout()
        self.chat_avatar = QLabel()
        self.chat_avatar.setFixedSize(16, 16)
        self.chat_title = QLabel("Название: -")
        self.chat_id = QLabel("ID: -")
        self.chat_type = QLabel("Тип: -")
        self.chat_participants_count = QLabel("Участников: -")
        self.chat_link = QLabel("Ссылка: -")
        self.open_telegram_button = QPushButton("Открыть в Telegram", visible=False)
        chat_info_layout.addWidget(self.chat_avatar)
        chat_info_layout.addWidget(self.chat_title)
        chat_info_layout.addWidget(self.chat_id)
        chat_info_layout.addWidget(self.chat_type)
        chat_info_layout.addWidget(self.chat_participants_count)
        chat_info_layout.addWidget(self.chat_link)
        chat_info_layout.addWidget(self.open_telegram_button)
        self.chat_info_group.setLayout(chat_info_layout)
        right_layout.addWidget(self.chat_info_group)

        self.participants_list = QListWidget(maximumHeight=20 * 20)
        right_layout.addWidget(self.participants_list)

        self.clear_cache_button = QPushButton("Очистить кэш")
        right_layout.addWidget(self.clear_cache_button)

        self.right_progress_bar = QProgressBar(maximum=0, visible=False)
        right_layout.addWidget(self.right_progress_bar)
        main_layout.addLayout(right_layout)

        self.add_all_button.clicked.connect(self.add_all_chats)
        self.add_button.clicked.connect(self.add_chat)
        self.refresh_all_button.clicked.connect(self.refresh_all_chats)
        self.remove_all_button.clicked.connect(self.remove_all_chats)
        self.remove_button.clicked.connect(self.remove_chat)
        self.refresh_selected_button.clicked.connect(self.refresh_selected_chats)
        self.next_button.clicked.connect(self.show_control_panel)
        self.back_button.clicked.connect(self.show_auth_window)
        self.clear_cache_button.clicked.connect(self.clear_cache)
        self.open_telegram_button.clicked.connect(self.open_chat_in_telegram)

        self.all_chats_all.toggled.connect(self.filter_all_chats)
        self.all_chats_groups.toggled.connect(self.filter_all_chats)
        self.all_chats_channels.toggled.connect(self.filter_all_chats)
        self.all_chats_private.toggled.connect(self.filter_all_chats)
        self.selected_all.toggled.connect(self.filter_selected_chats)
        self.selected_groups.toggled.connect(self.filter_selected_chats)
        self.selected_channels.toggled.connect(self.filter_selected_chats)
        self.selected_private.toggled.connect(self.filter_selected_chats)

        self.load_selected_chats()

        # Автоматическое обновление списков с задержкой
        QTimer.singleShot(500, self.refresh_all_chats)
        QTimer.singleShot(500, self.refresh_selected_chats)

    def get_chat_type(self, entity):
        if isinstance(entity, User):
            return "Личный"
        elif isinstance(entity, Chat):
            return "Группа"
        elif isinstance(entity, Channel):
            return "Супергруппа" if entity.megagroup else "Канал"
        return "Неизвестно"

    @asyncSlot()
    async def filter_all_chats(self):
        search_text = self.all_chats_search.text().lower()
        filter_type = "all" if self.all_chats_all.isChecked() else (
            "group" if self.all_chats_groups.isChecked() else 
            "channel" if self.all_chats_channels.isChecked() else 
            "private"
        )
        self.all_chats_list.clear()
        selected_chat_ids = {chat_id for chat_id, _, _ in get_selected_chats()}

        # Если ID текущего пользователя ещё не установлен, пытаемся его получить
        if state.current_user_id is None and state.client is not None:
            try:
                me = await state.client.get_me()
                state.current_user_id = me.id
                logging.info(f"ID текущего пользователя сохранён в filter_all_chats: {state.current_user_id}")
            except Exception as e:
                logging.error(f"Не удалось получить ID текущего пользователя в filter_all_chats: {str(e)}")
                state.current_user_id = None

        my_id = state.current_user_id

        for chat_id, entity in state.chat_cache.items():
            if chat_id in selected_chat_ids:
                continue
            # Проверяем, является ли чат "Избранным"
            is_saved_messages = my_id is not None and chat_id == my_id
            # Определяем заголовок
            if is_saved_messages:
                title = "Избранное"
            else:
                if isinstance(entity, User):
                    title = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                elif isinstance(entity, (Chat, Channel)):
                    title = entity.title or ""
                else:
                    title = ""
            # Если заголовок пустой, используем заглушку
            if not title.strip():
                title = f"Без названия (ID: {chat_id})"
            chat_type = self.get_chat_type(entity)
            # Добавляем иконку в зависимости от типа чата
            icon = "⭐" if is_saved_messages else "👤" if chat_type == "Личный" else "📷" if chat_type in ["Группа", "Супергруппа"] else "📢"
            display_text = f"{icon} {title}"
            if (filter_type == "all" or 
                (filter_type == "group" and chat_type in ["Группа", "Супергруппа"]) or
                (filter_type == "channel" and chat_type == "Канал") or
                (filter_type == "private" and chat_type == "Личный")) and search_text in title.lower():
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, chat_id)
                if chat_id in selected_chat_ids:
                    item.setForeground(Qt.gray)
                self.all_chats_list.addItem(item)
        self.all_chats_label.setText(f"Общие чаты: {self.all_chats_list.count()}")

    @asyncSlot()
    async def filter_selected_chats(self):
        search_text = self.selected_chats_search.text().lower()
        filter_type = "all" if self.selected_all.isChecked() else (
            "group" if self.selected_groups.isChecked() else 
            "channel" if self.selected_channels.isChecked() else 
            "private"
        )
        self.selected_chats_list.clear()

        # Если ID текущего пользователя ещё не установлен, пытаемся его получить
        if state.current_user_id is None and state.client is not None:
            try:
                me = await state.client.get_me()
                state.current_user_id = me.id
                logging.info(f"ID текущего пользователя сохранён в filter_selected_chats: {state.current_user_id}")
            except Exception as e:
                logging.error(f"Не удалось получить ID текущего пользователя в filter_selected_chats: {str(e)}")
                state.current_user_id = None

        my_id = state.current_user_id

        for chat_id, title, chat_type in get_selected_chats():
            # Проверяем, является ли чат "Избранным"
            is_saved_messages = my_id is not None and chat_id == my_id
            if is_saved_messages:
                title = "Избранное"
            # Если заголовок пустой, используем заглушку
            if not title.strip():
                title = f"Без названия (ID: {chat_id})"
            # Добавляем иконку в зависимости от типа чата
            icon = "⭐" if is_saved_messages else "👤" if chat_type == "Личный" else "📷" if chat_type in ["Группа", "Супергруппа"] else "📢"
            display_text = f"{icon} {title}"
            if (filter_type == "all" or 
                (filter_type == "group" and chat_type in ["Группа", "Супергруппа"]) or
                (filter_type == "channel" and chat_type == "Канал") or
                (filter_type == "private" and chat_type == "Личный")) and search_text in title.lower():
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, chat_id)
                self.selected_chats_list.addItem(item)
        self.selected_chats_label.setText(f"Добавленные чаты: {self.selected_chats_list.count()}")
        self.next_button.setEnabled(self.selected_chats_list.count() > 0)

    def update_buttons_and_info(self):
        self.add_button.setEnabled(bool(self.all_chats_list.selectedItems()))
        self.remove_button.setEnabled(bool(self.selected_chats_list.selectedItems()))
        self.update_chat_info()

    @asyncSlot()
    async def refresh_all_chats(self):
        # Проверяем, подключён ли клиент
        if state.client is None:
            auth_data = get_auth_data()
            if not auth_data:
                self.all_chats_label.setText("Ошибка: данные авторизации отсутствуют")
                self.right_progress_bar.setVisible(False)
                logging.error("Данные авторизации отсутствуют при попытке обновить общий список чатов")
                return

            api_id, api_hash, phone = auth_data
            state.client = TelegramClient('bot', api_id, api_hash)
            try:
                await state.client.connect()
                if not await state.client.is_user_authorized():
                    self.all_chats_label.setText("Ошибка: требуется повторная авторизация")
                    self.right_progress_bar.setVisible(False)
                    logging.error("Клиент Telegram не авторизован, требуется повторная авторизация")
                    return
                logging.info("Клиент Telegram успешно переподключён для обновления общего списка чатов")
            except Exception as e:
                self.all_chats_label.setText(f"Ошибка подключения: {str(e)}")
                self.right_progress_bar.setVisible(False)
                logging.error(f"Не удалось переподключить клиента Telegram: {str(e)}")
                state.client = None
                return

        if not await state.client.is_user_authorized():
            self.all_chats_label.setText("Ошибка: клиент Telegram не авторизован")
            self.right_progress_bar.setVisible(False)
            logging.error("Клиент Telegram не авторизован при попытке обновить общий список чатов")
            return

        self.all_chats_label.setText("Инициализация данных...")
        self.all_chats_spinner.setVisible(True)
        self.right_progress_bar.setVisible(True)
        self.refresh_all_button.setText("Обновление...")
        self.refresh_all_button.setEnabled(False)
        try:
            async for dialog in state.client.iter_dialogs():
                state.chat_cache[dialog.entity.id] = dialog.entity
            self.filter_all_chats()
            # Показываем уведомление
            self.update_notification.setVisible(True)
            QTimer.singleShot(3000, lambda: self.update_notification.setVisible(False))
        except Exception as e:
            self.all_chats_label.setText(f"Ошибка: {str(e)}")
            logging.error(f"Ошибка при обновлении общего списка чатов: {str(e)}")
        finally:
            self.all_chats_spinner.setVisible(False)
            self.right_progress_bar.setVisible(False)
            self.refresh_all_button.setText("Обновить")
            self.refresh_all_button.setEnabled(True)

    @asyncSlot()
    async def refresh_selected_chats(self):
        if state.client is None or not await state.client.is_user_authorized():
            auth_data = get_auth_data()
            if not auth_data:
                self.selected_chats_label.setText("Ошибка: данные авторизации отсутствуют")
                self.right_progress_bar.setVisible(False)
                logging.error("Данные авторизации отсутствуют при попытке обновить добавленные чаты")
                return

            api_id, api_hash, phone = auth_data
            state.client = TelegramClient('bot', api_id, api_hash)
            try:
                await state.client.connect()
                if not await state.client.is_user_authorized():
                    self.selected_chats_label.setText("Ошибка: требуется повторная авторизация")
                    self.right_progress_bar.setVisible(False)
                    logging.error("Клиент Telegram не авторизован, требуется повторная авторизация")
                    return
                logging.info("Клиент Telegram успешно переподключён для обновления добавленных чатов")
            except Exception as e:
                self.selected_chats_label.setText(f"Ошибка подключения: {str(e)}")
                self.right_progress_bar.setVisible(False)
                logging.error(f"Не удалось переподключить клиента Telegram: {str(e)}")
                state.client = None
                return

        self.selected_chats_label.setText("Инициализация данных...")
        self.selected_chats_spinner.setVisible(True)
        self.right_progress_bar.setVisible(True)
        self.refresh_selected_button.setText("Обновление...")
        self.refresh_selected_button.setEnabled(False)
        try:
            for chat_id, title, chat_type in get_selected_chats()[:]:
                try:
                    entity = await state.client.get_entity(chat_id)
                    state.chat_cache[chat_id] = entity
                except Exception as e:
                    logging.warning(f"Чат {chat_id} ({title}) недоступен, удаляем из списка: {str(e)}")
                    remove_selected_chat(chat_id)
            self.filter_selected_chats()
            await self.update_participants()
            # Показываем уведомление
            self.update_notification.setVisible(True)
            QTimer.singleShot(3000, lambda: self.update_notification.setVisible(False))
        except Exception as e:
            self.selected_chats_label.setText(f"Ошибка: {str(e)}")
            logging.error(f"Ошибка при обновлении добавленных чатов: {str(e)}")
        finally:
            self.selected_chats_spinner.setVisible(False)
            self.right_progress_bar.setVisible(False)
            self.refresh_selected_button.setText("Обновить")
            self.refresh_selected_button.setEnabled(True)

    def add_all_chats(self):
        for i in range(self.all_chats_list.count()):
            item = self.all_chats_list.item(i)
            chat_id = item.data(Qt.UserRole)
            entity = state.chat_cache.get(chat_id)
            if entity:
                # Определяем заголовок в зависимости от типа сущности
                if isinstance(entity, User):
                    title = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                elif isinstance(entity, (Chat, Channel)):
                    title = entity.title or "Без названия"
                else:
                    title = "Неизвестный чат"
                chat_type = self.get_chat_type(entity)
                save_selected_chat(chat_id, title, chat_type)
        self.filter_all_chats()
        self.filter_selected_chats()

    def add_chat(self):
        if selected := self.all_chats_list.selectedItems():
            chat_id = selected[0].data(Qt.UserRole)
            entity = state.chat_cache.get(chat_id)
            if entity:
                # Определяем заголовок в зависимости от типа сущности
                if isinstance(entity, User):
                    title = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                elif isinstance(entity, (Chat, Channel)):
                    title = entity.title or "Без названия"
                else:
                    title = "Неизвестный чат"
                chat_type = self.get_chat_type(entity)
                save_selected_chat(chat_id, title, chat_type)
                self.filter_all_chats()
                self.filter_selected_chats()

    def remove_all_chats(self):
        conn = sqlite3.connect('telegram_bot_data.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM selected_chats")
        conn.commit()
        conn.close()
        self.filter_all_chats()
        self.filter_selected_chats()

    def remove_chat(self):
        if selected := self.selected_chats_list.selectedItems():
            remove_selected_chat(selected[0].data(Qt.UserRole))
            self.filter_all_chats()
            self.filter_selected_chats()

    @asyncSlot()
    async def update_chat_info(self):
        self.participants_list.clear()
        selected = self.all_chats_list.selectedItems() or self.selected_chats_list.selectedItems()
        if not selected:
            self.chat_title.setText("Название: -")
            self.chat_id.setText("ID: -")
            self.chat_type.setText("Тип: -")
            self.chat_participants_count.setText("Участников: -")
            self.chat_link.setText("Ссылка: -")
            self.open_telegram_button.setVisible(False)
            return

        chat_id = selected[0].data(Qt.UserRole)
        entity = state.chat_cache.get(chat_id)
        if entity:
            # Определяем заголовок в зависимости от типа сущности
            if isinstance(entity, User):
                title = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
            elif isinstance(entity, (Chat, Channel)):
                title = entity.title or "Без названия"
            else:
                title = "Неизвестный чат"
            chat_type = self.get_chat_type(entity)
            participants_count = getattr(entity, 'participants_count', "-")
            link = f"t.me/{entity.username}" if getattr(entity, 'username', None) else "Нет ссылки"

            self.chat_title.setText(f"Название: {title}")
            self.chat_id.setText(f"ID: {chat_id}")
            self.chat_type.setText(f"Тип: {chat_type}")
            self.chat_participants_count.setText(f"Участников: {participants_count}")
            self.chat_link.setText(f"Ссылка: {link}")
            self.open_telegram_button.setVisible(link != "Нет ссылки")
            self.chat_avatar.setText("📷" if chat_type != "Личный" else "👤")
            await self.update_participants(chat_id)

    @asyncSlot()
    async def update_participants(self, chat_id=None):
        if not chat_id:
            selected = self.selected_chats_list.selectedItems() or self.all_chats_list.selectedItems()
            if not selected:
                return
            chat_id = selected[0].data(Qt.UserRole)

        entity = state.chat_cache.get(chat_id)
        if not entity:
            return

        self.participants_list.clear()
        self.right_progress_bar.setVisible(True)
        try:
            if isinstance(entity, User):
                me = await state.client.get_me()
                for user in [me, entity]:
                    username = f"@{user.username}" if user.username else ""
                    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                    item = QListWidgetItem(f"{username} {name} {user.id}")
                    item.setData(Qt.UserRole, user.id)
                    if user.status:
                        item.setForeground(Qt.green)
                    self.participants_list.addItem(item)
            else:
                async for participant in state.client.iter_participants(entity, limit=20):
                    username = f"@{participant.username}" if participant.username else ""
                    name = f"{participant.first_name or ''} {participant.last_name or ''}".strip()
                    item = QListWidgetItem(f"{username} {name} {participant.id}")
                    item.setData(Qt.UserRole, participant.id)
                    if participant.status:
                        item.setForeground(Qt.green)
                    self.participants_list.addItem(item)
            state.participants_cache[chat_id] = self.participants_list.count()
        except Exception as e:
            self.participants_list.addItem(f"Ошибка: {str(e)}")
        finally:
            self.right_progress_bar.setVisible(False)

    def open_chat_in_telegram(self):
        link_text = self.chat_link.text()  # Получаем текст из QLabel (например, "Ссылка: t.me/username")
        if link_text.startswith("Ссылка: "):
            url = link_text[len("Ссылка: "):]  # Извлекаем чистую ссылку (например, "t.me/username")
            if url.startswith("t.me/"):
                full_url = f"https://{url}"  # Добавляем протокол для корректного открытия
                QDesktopServices.openUrl(QUrl(full_url))
                logging.info(f"Открыта ссылка в Telegram: {full_url}")
            else:
                logging.warning(f"Некорректная ссылка для открытия в Telegram: {url}")
        else:
            logging.warning(f"Не удалось извлечь ссылку из текста: {link_text}")

    def clear_cache(self):
        state.chat_cache.clear()
        state.participants_cache.clear()
        self.participants_list.clear()
        self.filter_all_chats()
        self.filter_selected_chats()

    def load_selected_chats(self):
        for chat_id, title, _ in get_selected_chats():
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, chat_id)
            self.selected_chats_list.addItem(item)
        self.selected_chats_label.setText(f"Добавленные чаты: {self.selected_chats_list.count()}")
        self.next_button.setEnabled(self.selected_chats_list.count() > 0)

    def show_control_panel(self):
        self.close()
        self.control_panel = ControlPanelWindow()
        self.control_panel.show()

    def show_auth_window(self):
        # Отключаем клиент Telegram, если он активен
        if state.client is not None:
            try:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(state.client.disconnect())
                logging.info("Клиент Telegram успешно отключён перед возвращением в окно авторизации")
            except Exception as e:
                logging.error(f"Ошибка при отключении клиента Telegram: {str(e)}")
            finally:
                state.client = None  # Сбрасываем клиент

        self.close()
        self.auth_window = AuthWindow()
        self.auth_window.show()

class ResponsesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка ответов")
        self.setFixedSize(500, 400)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        # Установка иконки для окна
        icon_path = "icons/256.ico"
        self.setWindowIcon(QIcon(icon_path))

        layout = QVBoxLayout()

        # Поле ввода и кнопка "Добавить"
        input_layout = QHBoxLayout()
        self.response_input = QLineEdit()
        self.response_input.setMaxLength(4096)
        self.add_button = QPushButton("Добавить", enabled=False)
        input_layout.addWidget(self.response_input)
        input_layout.addWidget(self.add_button)
        layout.addLayout(input_layout)

        # Переключатель в стиле iOS (уменьшенный)
        switch_layout = QHBoxLayout()
        self.off_label = QLabel("Выкл")
        self.switch_container = QWidget()
        self.switch_container.setObjectName("switch_container")
        self.switch_container.setFixedSize(50, 28)  # Уменьшенный размер
        self.switch_button = QPushButton("", checkable=True, parent=self.switch_container)
        self.switch_button.setObjectName("switch")
        self.switch_button.setGeometry(0, 0, 50, 28)
        self.slider = QWidget(parent=self.switch_container)
        self.slider.setObjectName("slider")
        self.slider.setFixedSize(24, 24)  # Уменьшенный ползунок
        self.slider.setStyleSheet("background-color: white; border-radius: 12px; border: 1px solid #CCCCCC;")
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(3)
        shadow.setXOffset(0)
        shadow.setYOffset(1)
        shadow.setColor(QColor(0, 0, 0, 76))
        self.slider.setGraphicsEffect(shadow)
        self.slider.move(2, 2)  # Начальная позиция (выключено)
        self.on_label = QLabel("Вкл")
        switch_layout.addStretch()
        switch_layout.addWidget(self.off_label, alignment=Qt.AlignRight)
        switch_layout.addWidget(self.switch_container)
        switch_layout.addWidget(self.on_label, alignment=Qt.AlignLeft)
        switch_layout.addStretch()
        layout.addLayout(switch_layout)

        # Список ответов
        self.responses_list = QListWidget()
        layout.addWidget(self.responses_list)

        # Кнопки управления
        buttons_layout = QHBoxLayout()
        self.delete_button = QPushButton("Удалить", enabled=False)
        self.delete_all_button = QPushButton("Удалить всё")
        self.edit_button = QPushButton("Редактировать", enabled=False)
        buttons_layout.addWidget(self.delete_button)
        buttons_layout.addWidget(self.delete_all_button)
        buttons_layout.addWidget(self.edit_button)
        layout.addLayout(buttons_layout)

        # Кнопка "Ок"
        self.ok_button = QPushButton("Ок")
        self.ok_button.setFixedSize(120, 40)
        layout.addWidget(self.ok_button, alignment=Qt.AlignCenter)

        self.setLayout(layout)

        # Анимация для ползунка
        self.slider_animation = QPropertyAnimation(self.slider, b"geometry")
        self.slider_animation.setDuration(200)
        self.previous_switch_state = False

        # Подключение сигналов
        self.response_input.textChanged.connect(self.update_add_button)
        self.add_button.clicked.connect(self.add_response)
        self.responses_list.itemSelectionChanged.connect(self.update_buttons)
        self.delete_button.clicked.connect(self.delete_response)
        self.delete_all_button.clicked.connect(self.delete_all_responses)
        self.edit_button.clicked.connect(self.edit_response)
        self.ok_button.clicked.connect(self.accept)
        self.switch_button.clicked.connect(self.toggle_switch)

        # Инициализация состояния
        self.load_responses()
        self.switch_button.setChecked(state.responses_enabled)
        self.update_switch_state()

    def update_add_button(self):
        self.add_button.setEnabled(bool(self.response_input.text()) and state.responses_enabled)

    def update_buttons(self):
        selected = bool(self.responses_list.selectedItems())
        self.delete_button.setEnabled(selected and state.responses_enabled)
        self.edit_button.setEnabled(selected and state.responses_enabled)
        self.delete_all_button.setEnabled(state.responses_enabled)
        self.response_input.setEnabled(state.responses_enabled)
        self.responses_list.setEnabled(state.responses_enabled)

    def load_responses(self):
        self.responses_list.clear()
        for response_id, text in get_responses():
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, response_id)
            self.responses_list.addItem(item)

    def add_response(self):
        text = self.response_input.text()
        if text and state.responses_enabled:
            save_response(text)
            self.response_input.clear()
            self.load_responses()

    def delete_response(self):
        if selected := self.responses_list.selectedItems():
            delete_response(selected[0].data(Qt.UserRole))
            self.load_responses()

    def delete_all_responses(self):
        clear_responses()
        self.load_responses()

    def edit_response(self):
        if selected := self.responses_list.selectedItems():
            text = self.response_input.text() or selected[0].text()
            update_response(selected[0].data(Qt.UserRole), text)
            self.response_input.clear()
            self.load_responses()

    def toggle_switch(self):
        state.responses_enabled = self.switch_button.isChecked()
        self.update_switch_state()
        self.update_buttons()
        self.update_add_button()

    def update_switch_state(self):
        self.off_label.setStyleSheet(f"color: {'#A9A9A9' if not self.switch_button.isChecked() else '#D3D3D3'};")
        self.on_label.setStyleSheet(f"color: {'#00FF00' if self.switch_button.isChecked() else '#D3D3D3'};")
        if self.switch_button.isChecked():
            self.switch_container.setStyleSheet("background-color: #34C759; border: 1px solid #2E2E2E; border-radius: 14px;")
        else:
            self.switch_container.setStyleSheet("background-color: #E0E0E0; border: 1px solid #2E2E2E; border-radius: 14px;")
        if self.previous_switch_state != self.switch_button.isChecked():
            self.animate_slider()
            self.previous_switch_state = self.switch_button.isChecked()

    def animate_slider(self):
        if self.switch_button.isChecked():
            self.slider_animation.setStartValue(QRect(2, 2, 24, 24))
            self.slider_animation.setEndValue(QRect(24, 2, 24, 24))
        else:
            self.slider_animation.setStartValue(QRect(24, 2, 24, 24))
            self.slider_animation.setEndValue(QRect(2, 2, 24, 24))
        self.slider_animation.start()

class ControlPanelWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Bot - Панель управления")
        self.setFixedSize(600, 600)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)
        widget = QWidget()
        self.setCentralWidget(widget)
        layout = QVBoxLayout(widget)

        # Установка иконки для окна
        icon_path = "icons/256.ico"
        self.setWindowIcon(QIcon(icon_path))

        self.uptime_label = QLabel("Время работы: ⏰ 00:00:00")
        layout.addWidget(self.uptime_label)

        # Платформы с переключателями
        layout.addSpacing(25)
        platforms_container = QHBoxLayout()  # Контейнер для центрирования платформ
        platforms_layout = QVBoxLayout()  # Вертикальный layout для платформ
        platforms_layout.setSpacing(10)  # Расстояние между платформами

        # YouTube Shorts
        youtube_layout = QHBoxLayout()
        youtube_layout.setSpacing(10)  # Фиксированное расстояние между надписью и переключателем
        self.youtube_label = QLabel("YouTube Shorts (<5 мин) 📺")
        self.youtube_switch_container = QWidget()
        self.youtube_switch_container.setObjectName("switch_container")
        self.youtube_switch_container.setFixedSize(50, 28)
        self.youtube_switch = QPushButton("", checkable=True, parent=self.youtube_switch_container)
        self.youtube_switch.setObjectName("switch")
        self.youtube_switch.setGeometry(0, 0, 50, 28)
        self.youtube_slider = QWidget(parent=self.youtube_switch_container)
        self.youtube_slider.setObjectName("slider")
        self.youtube_slider.setFixedSize(24, 24)
        self.youtube_slider.setStyleSheet("background-color: white; border-radius: 12px; border: 1px solid #CCCCCC;")
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(3)
        shadow.setXOffset(0)
        shadow.setYOffset(1)
        shadow.setColor(QColor(0, 0, 0, 76))
        self.youtube_slider.setGraphicsEffect(shadow)
        self.youtube_slider.move(2, 2)
        youtube_layout.addWidget(self.youtube_label)
        youtube_layout.addWidget(self.youtube_switch_container)
        platforms_layout.addLayout(youtube_layout)

        # Instagram Reels
        instagram_layout = QHBoxLayout()
        instagram_layout.setSpacing(10)
        self.instagram_label = QLabel("Instagram Reels 📸")
        self.instagram_switch_container = QWidget()
        self.instagram_switch_container.setObjectName("switch_container")
        self.instagram_switch_container.setFixedSize(50, 28)
        self.instagram_switch = QPushButton("", checkable=True, parent=self.instagram_switch_container)
        self.instagram_switch.setObjectName("switch")
        self.instagram_switch.setGeometry(0, 0, 50, 28)
        self.instagram_slider = QWidget(parent=self.instagram_switch_container)
        self.instagram_slider.setObjectName("slider")
        self.instagram_slider.setFixedSize(24, 24)
        self.instagram_slider.setStyleSheet("background-color: white; border-radius: 12px; border: 1px solid #CCCCCC;")
        self.instagram_slider.setGraphicsEffect(shadow)
        self.instagram_slider.move(2, 2)
        instagram_layout.addWidget(self.instagram_label)
        instagram_layout.addWidget(self.instagram_switch_container)
        platforms_layout.addLayout(instagram_layout)

        # TikTok
        tiktok_layout = QHBoxLayout()
        tiktok_layout.setSpacing(10)
        self.tiktok_label = QLabel("TikTok 🎵")
        self.tiktok_switch_container = QWidget()
        self.tiktok_switch_container.setObjectName("switch_container")
        self.tiktok_switch_container.setFixedSize(50, 28)
        self.tiktok_switch = QPushButton("", checkable=True, parent=self.tiktok_switch_container)
        self.tiktok_switch.setObjectName("switch")
        self.tiktok_switch.setGeometry(0, 0, 50, 28)
        self.tiktok_slider = QWidget(parent=self.tiktok_switch_container)
        self.tiktok_slider.setObjectName("slider")
        self.tiktok_slider.setFixedSize(24, 24)
        self.tiktok_slider.setStyleSheet("background-color: white; border-radius: 12px; border: 1px solid #CCCCCC;")
        self.tiktok_slider.setGraphicsEffect(shadow)
        self.tiktok_slider.move(2, 2)
        tiktok_layout.addWidget(self.tiktok_label)
        tiktok_layout.addWidget(self.tiktok_switch_container)
        platforms_layout.addLayout(tiktok_layout)

        # Twitter
        twitter_layout = QHBoxLayout()
        twitter_layout.setSpacing(10)
        self.twitter_label = QLabel("Twitter (<5 мин) 🐦")
        self.twitter_switch_container = QWidget()
        self.twitter_switch_container.setObjectName("switch_container")
        self.twitter_switch_container.setFixedSize(50, 28)
        self.twitter_switch = QPushButton("", checkable=True, parent=self.twitter_switch_container)
        self.twitter_switch.setObjectName("switch")
        self.twitter_switch.setGeometry(0, 0, 50, 28)
        self.twitter_slider = QWidget(parent=self.twitter_switch_container)
        self.twitter_slider.setObjectName("slider")
        self.twitter_slider.setFixedSize(24, 24)
        self.twitter_slider.setStyleSheet("background-color: white; border-radius: 12px; border: 1px solid #CCCCCC;")
        self.twitter_slider.setGraphicsEffect(shadow)
        self.twitter_slider.move(2, 2)
        twitter_layout.addWidget(self.twitter_label)
        twitter_layout.addWidget(self.twitter_switch_container)
        platforms_layout.addLayout(twitter_layout)

        platforms_container.addStretch()  # Левый отступ для центрирования
        platforms_container.addLayout(platforms_layout)
        platforms_container.addStretch()  # Правый отступ для центрирования
        layout.addLayout(platforms_container)

        # Основной переключатель
        layout.addSpacing(25)
        switch_layout = QHBoxLayout()
        self.off_label = QLabel("Выкл")
        self.switch_container = QWidget()
        self.switch_container.setObjectName("switch_container")
        self.switch_container.setFixedSize(60, 34)
        self.switch_button = QPushButton("", checkable=True, parent=self.switch_container)
        self.switch_button.setObjectName("switch")
        self.switch_button.setGeometry(0, 0, 60, 34)
        self.slider = QWidget(parent=self.switch_container)
        self.slider.setObjectName("slider")
        self.slider.setFixedSize(30, 30)
        self.slider.setStyleSheet("background-color: white; border-radius: 15px; border: 1px solid #CCCCCC;")
        self.slider.setGraphicsEffect(shadow)
        self.slider.move(2, 2)
        self.on_label = QLabel("Вкл")
        switch_layout.addWidget(self.off_label, alignment=Qt.AlignRight)
        switch_layout.addWidget(self.switch_container)
        switch_layout.addWidget(self.on_label, alignment=Qt.AlignLeft)
        layout.addLayout(switch_layout)

        layout.addSpacing(25)

        # Списки логов и статистики
        lists_layout = QHBoxLayout()
        lists_layout.setAlignment(Qt.AlignTop)
        self.log_list = QListWidget()
        self.log_list.setFixedHeight(250)
        self.chats_stats_list = QListWidget()
        self.chats_stats_list.setFixedHeight(250)
        lists_layout.addWidget(self.log_list)
        lists_layout.addWidget(self.chats_stats_list)
        layout.addLayout(lists_layout)

        # Кнопки
        buttons_layout = QHBoxLayout()
        self.configure_responses_button = QPushButton("Настроить ответы")
        self.configure_responses_button.setFixedSize(120, 40)
        self.back_button = QPushButton("Назад")
        self.back_button.setObjectName("back_button_control")
        self.back_button.setFixedSize(120, 40)
        buttons_layout.addWidget(self.configure_responses_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.back_button)
        layout.addLayout(buttons_layout)

        # Таймер и анимации
        self.uptime_timer = QTimer()
        self.uptime_timer.timeout.connect(self.update_uptime)
        self.uptime_seconds = 0

        self.slider_animation = QPropertyAnimation(self.slider, b"geometry")
        self.slider_animation.setDuration(200)
        self.youtube_animation = QPropertyAnimation(self.youtube_slider, b"geometry")
        self.youtube_animation.setDuration(200)
        self.instagram_animation = QPropertyAnimation(self.instagram_slider, b"geometry")
        self.instagram_animation.setDuration(200)
        self.tiktok_animation = QPropertyAnimation(self.tiktok_slider, b"geometry")
        self.tiktok_animation.setDuration(200)
        self.twitter_animation = QPropertyAnimation(self.twitter_slider, b"geometry")
        self.twitter_animation.setDuration(200)
        self.previous_switch_state = False
        self.previous_youtube_state = False
        self.previous_instagram_state = False
        self.previous_tiktok_state = False
        self.previous_twitter_state = False

        # Подключение сигналов
        self.youtube_switch.clicked.connect(lambda: self.update_platform("youtube_shorts", self.youtube_switch.isChecked()))
        self.instagram_switch.clicked.connect(lambda: self.update_platform("instagram", self.instagram_switch.isChecked()))
        self.tiktok_switch.clicked.connect(lambda: self.update_platform("tiktok", self.tiktok_switch.isChecked()))
        self.twitter_switch.clicked.connect(lambda: self.update_platform("twitter", self.twitter_switch.isChecked()))
        self.switch_button.clicked.connect(self.toggle_switch)
        self.configure_responses_button.clicked.connect(self.show_responses_dialog)
        self.back_button.clicked.connect(self.show_settings_window)

        # Инициализация состояния
        self.load_platform_settings()
        self.update_switch_state()
        self.update_platform_switches()
        self.setup_logging()
        self.load_chats_stats()

    # Остальные методы остаются без изменений
    def load_platform_settings(self):
        settings = get_platform_settings()
        self.youtube_switch.setChecked(settings.get("youtube_shorts", False))
        self.instagram_switch.setChecked(settings.get("instagram", False))
        self.tiktok_switch.setChecked(settings.get("tiktok", False))
        self.twitter_switch.setChecked(settings.get("twitter", False))
        self.update_platform_switches()

    def update_platform(self, platform, enabled):
        save_platform_setting(platform, enabled)
        self.update_platform_switches()
        self.update_switch_state()

    def update_platform_switches(self):
        for switch, container, animation, prev_state_attr, label in [
            (self.youtube_switch, self.youtube_switch_container, self.youtube_animation, "previous_youtube_state", self.youtube_label),
            (self.instagram_switch, self.instagram_switch_container, self.instagram_animation, "previous_instagram_state", self.instagram_label),
            (self.tiktok_switch, self.tiktok_switch_container, self.tiktok_animation, "previous_tiktok_state", self.tiktok_label),
            (self.twitter_switch, self.twitter_switch_container, self.twitter_animation, "previous_twitter_state", self.twitter_label),
        ]:
            if switch.isChecked():
                container.setStyleSheet("background-color: #34C759; border: 1px solid #2E2E2E; border-radius: 14px;")
                label.setStyleSheet("color: #00FF00;")
            else:
                container.setStyleSheet("background-color: #E0E0E0; border: 1px solid #2E2E2E; border-radius: 14px;")
                label.setStyleSheet("color: #D3D3D3;")
            prev_state = getattr(self, prev_state_attr)
            if prev_state != switch.isChecked():
                if switch.isChecked():
                    animation.setStartValue(QRect(2, 2, 24, 24))
                    animation.setEndValue(QRect(24, 2, 24, 24))
                else:
                    animation.setStartValue(QRect(24, 2, 24, 24))
                    animation.setEndValue(QRect(2, 2, 24, 24))
                animation.start()
                setattr(self, prev_state_attr, switch.isChecked())

    def update_switch_state(self):
        any_checked = any([self.youtube_switch.isChecked(), self.instagram_switch.isChecked(),
                           self.tiktok_switch.isChecked(), self.twitter_switch.isChecked()])
        self.switch_button.setEnabled(any_checked)
        self.off_label.setStyleSheet(f"color: {'#A9A9A9' if not self.switch_button.isChecked() else '#D3D3D3'};")
        self.on_label.setStyleSheet(f"color: {'#00FF00' if self.switch_button.isChecked() else '#D3D3D3'};")
        if self.switch_button.isChecked():
            self.switch_container.setStyleSheet("background-color: #34C759; border: 1px solid #2E2E2E; border-radius: 17px;")
        else:
            self.switch_container.setStyleSheet("background-color: #E0E0E0; border: 1px solid #2E2E2E; border-radius: 17px;")
        if self.previous_switch_state != self.switch_button.isChecked():
            self.animate_slider()
            self.previous_switch_state = self.switch_button.isChecked()

    def animate_slider(self):
        if self.switch_button.isChecked():
            self.slider_animation.setStartValue(QRect(2, 2, 30, 30))
            self.slider_animation.setEndValue(QRect(28, 2, 30, 30))
        else:
            self.slider_animation.setStartValue(QRect(28, 2, 30, 30))
            self.slider_animation.setEndValue(QRect(2, 2, 30, 30))
        self.slider_animation.start()

    def toggle_switch(self):
        state.switch_is_on = self.switch_button.isChecked()
        self.configure_responses_button.setEnabled(not state.switch_is_on)
        self.back_button.setEnabled(not state.switch_is_on)
        self.update_switch_state()
        if state.switch_is_on:
            self.uptime_seconds = 0
            self.uptime_timer.start(1000)
            self.log_list.clear()
            state.links_processed_per_chat.clear()
            state.errors_per_chat.clear()
            for chat_id, _, _ in get_selected_chats():
                state.links_processed_per_chat[chat_id] = 0
                state.errors_per_chat[chat_id] = 0
            self.update_chats_stats()
            selected_chats = [chat_id for chat_id, _, _ in get_selected_chats()]
            state.client.add_event_handler(self.message_handler, events.NewMessage(chats=selected_chats))
        else:
            self.uptime_timer.stop()
            for task in state.active_tasks:
                task.cancel()
            state.active_tasks.clear()
            state.client.remove_event_handler(self.message_handler)

    def update_uptime(self):
        self.uptime_seconds += 1
        hours, remainder = divmod(self.uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.uptime_label.setText(f"Время работы: ⏰ {hours:02d}:{minutes:02d}:{seconds:02d}")

    async def message_handler(self, event):
        if event.message.text:
            if len(state.active_tasks) >= 5:
                logging.warning("Достигнут лимит одновременно выполняемых задач, пропускаем обработку")
                return
            task = asyncio.create_task(process_video_link(event.chat_id, event.id, event.message.text, event.message))
            state.active_tasks.append(task)
            try:
                success = await task
                chat_id = event.chat_id
                if success:
                    if chat_id in state.links_processed_per_chat:
                        state.links_processed_per_chat[chat_id] += 1
                    else:
                        state.links_processed_per_chat[chat_id] = 1
                else:
                    if chat_id in state.errors_per_chat:
                        state.errors_per_chat[chat_id] += 1
                    else:
                        state.errors_per_chat[chat_id] = 1
                self.update_chats_stats()
            finally:
                state.active_tasks.remove(task)

    def setup_logging(self):
        handler = QListWidgetHandler(self.log_list)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(handler)

    def load_chats_stats(self):
        self.chats_stats_list.clear()
        total_links = sum(state.links_processed_per_chat.values())
        total_errors = sum(state.errors_per_chat.values())
        self.chats_stats_list.addItem(QListWidgetItem(f"Сумма обработанных ссылок за сессию: {total_links}"))
        self.chats_stats_list.addItem(QListWidgetItem(f"Сумма ошибок за сессию: {total_errors}"))
        self.chats_stats_list.addItem(QListWidgetItem(""))
        for chat_id, title, _ in get_selected_chats():
            links_count = state.links_processed_per_chat.get(chat_id, 0)
            errors_count = state.errors_per_chat.get(chat_id, 0)
            item = QListWidgetItem(f"{title}: {links_count} ссылок, {errors_count} ошибок")
            item.setData(Qt.UserRole, chat_id)
            self.chats_stats_list.addItem(item)

    def update_chats_stats(self):
        self.chats_stats_list.clear()
        total_links = sum(state.links_processed_per_chat.values())
        total_errors = sum(state.errors_per_chat.values())
        self.chats_stats_list.addItem(QListWidgetItem(f"Сумма обработанных ссылок за сессию: {total_links}"))
        self.chats_stats_list.addItem(QListWidgetItem(f"Сумма ошибок за сессию: {total_errors}"))
        self.chats_stats_list.addItem(QListWidgetItem(""))
        for chat_id, title, _ in get_selected_chats():
            links_count = state.links_processed_per_chat.get(chat_id, 0)
            errors_count = state.errors_per_chat.get(chat_id, 0)
            item = QListWidgetItem(f"{title}: {links_count} ссылок, {errors_count} ошибок")
            item.setData(Qt.UserRole, chat_id)
            self.chats_stats_list.addItem(item)

    def show_responses_dialog(self):
        dialog = ResponsesDialog(self)
        dialog.exec()

    def show_settings_window(self):
        if state.switch_is_on:
            self.switch_button.setChecked(False)
            state.switch_is_on = False
            self.configure_responses_button.setEnabled(True)
            self.back_button.setEnabled(True)
            self.update_switch_state()
            self.uptime_timer.stop()
            for task in state.active_tasks:
                task.cancel()
            state.active_tasks.clear()
            state.client.remove_event_handler(self.message_handler)
            logging.info("Все задачи остановлены, обработчик событий удалён")

        self.close()
        self.settings_window = ChatSettingsWindow()
        self.settings_window.show()

class QListWidgetHandler(logging.Handler):
    def __init__(self, list_widget):
        super().__init__()
        self.list_widget = list_widget

    def emit(self, record):
        msg = self.format(record)
        item = QListWidgetItem(msg)
        item.setToolTip(msg)
        self.list_widget.addItem(item)
        if self.list_widget.count() > 1000:
            self.list_widget.takeItem(0)
        self.list_widget.scrollToBottom()

def main():
    init_db()
    logging.info("Программа запущена")
    app = QApplication(sys.argv)

    # Установка иконки для приложения
    icon_path = "icons/256.ico"
    icon = QIcon(icon_path)
    if icon.isNull():
        logging.error(f"Не удалось загрузить иконку из {icon_path}")
    else:
        logging.info(f"Иконка успешно загружена из {icon_path}")
    app.setWindowIcon(icon)

    # Создание основного окна
    window = AuthWindow()
    window.show()

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    app.setStyleSheet("""
        QWidget { 
            background-color: #2E2E2E; 
            color: #D3D3D3; 
        }
        QLineEdit { 
            background-color: #404040; 
            color: #FFFFFF; 
            border: 1px solid #505050; 
        }
        QLineEdit:disabled { 
            background-color: #333333; 
            color: #A9A9A9; 
        }
        QLineEdit::placeholder { 
            color: #A9A9A9; 
        }
        QPushButton { 
            background-color: #505050; 
            color: #FFFFFF; 
            border: none; 
            padding: 5px; 
        }
        QPushButton:hover { 
            background-color: #606060; 
        }
        QPushButton:disabled { 
            background-color: #404040; 
            color: #A9A9A9; 
        }
        QPushButton#next_button, QPushButton#back_button, QPushButton#configure_responses_button, QPushButton#back_button_control { 
            padding: 10px; 
            border: 2px solid #FFFFFF;
        }
        QPushButton#next_button:hover, QPushButton#back_button:hover, QPushButton#configure_responses_button:hover, QPushButton#back_button_control:hover { 
            border: 2px solid #D3D3D3;
        }
        QPushButton#update_button { 
            background-color: #00CC00; 
            color: #FFFFFF; 
        }
        QPushButton#update_button:hover { 
            background-color: #00FF00; 
        }
        QWidget#switch_container { 
            background-color: #E0E0E0; 
            border: 1px solid #2E2E2E; 
            border-radius: 17px;
        }
        QWidget#switch_container[minimumWidth="50"] { 
            border-radius: 14px;
        }
        QPushButton#switch { 
            background-color: transparent; 
            border: none; 
        }
        QLabel { 
            color: #D3D3D3; 
        }
        QProgressBar { 
            background-color: #404040; 
            border: 1px solid #505050; 
            color: #D3D3D3; 
        }
        QProgressBar::chunk { 
            background-color: #00FF00; 
        }
        QListWidget { 
            background-color: #404040; 
            color: #FFFFFF; 
            border: 1px solid #505050; 
        }
        QListWidget::item { 
            border-bottom: 1px solid #505050;
            padding: 2px;
        }
        QListWidget::item:selected { 
            background-color: #606060; 
        }
        QGroupBox { 
            color: #D3D3D3; 
        }
        QCheckBox { 
            color: #D3D3D3; 
        }
    """)

    QTimer.singleShot(0, lambda: asyncio.ensure_future(clean_temp_files()))

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()