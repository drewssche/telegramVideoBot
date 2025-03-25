import os
import json
import sys
import hashlib
from cx_Freeze import setup, Executable

# Явно импортируем PySide6
try:
    import PySide6
except ImportError:
    print("Error: PySide6 is not installed. Please install it using 'pip install PySide6'.")
    sys.exit(1)

# Логируем хэш bot.py перед сборкой
with open("bot.py", "rb") as f:
    bot_content = f.read()
    bot_hash = hashlib.sha256(bot_content).hexdigest()
    print(f"SHA256 hash of bot.py before build: {bot_hash}")

# Создаём папку temp-files, если она не существует
if not os.path.exists("temp-files"):
    os.makedirs("temp-files")
    print("Created temp-files directory")

# Читаем версию из version.json
with open("version.json", "r", encoding="utf-8") as f:
    version_data = json.load(f)
    version = version_data["version"]

# Определяем, является ли это крупным релизом
def is_major_release(version):
    parts = list(map(int, version.split(".")))
    return parts[1] == 0 and parts[2] == 0

# Базовые настройки
base = "Win32GUI" if sys.platform == "win32" else None
executables = [
    Executable(
        script="bot.py",
        base=base,
        target_name="VideoBot.exe",
        icon="icons/256.ico"
    )
]

# Пакеты и модули
packages = [
    "os", "sys", "asyncio", "sqlite3", "logging", "time", "re", "random", "shutil", "subprocess",
    "telethon", "PySide6", "qasync", "yt_dlp", "json", "requests", "hashlib", "zipfile",
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "yt_dlp.extractor.youtube",
    "yt_dlp.extractor.twitter",
    "yt_dlp.extractor.tiktok",
    "yt_dlp.utils",
    "win32api", "win32con",
]
includes = []
excludes = [
    "yt_dlp.extractor.instagram",
    "yt_dlp.extractor.facebook",
    "yt_dlp.extractor.vimeo",
]

# Находим PySide6 и Qt зависимости
pyside6_path = os.path.dirname(sys.modules["PySide6"].__file__)

# Включаем только необходимые Qt плагины
necessary_plugins = [
    "platforms",
    "imageformats/qico.dll"
]
qt_plugins_includes = []
for plugin in necessary_plugins:
    plugin_path = os.path.join(pyside6_path, "plugins", plugin)
    if os.path.exists(plugin_path):
        qt_plugins_includes.append((plugin_path, f"PySide6/plugins/{plugin}"))
    else:
        print(f"Warning: Qt plugin {plugin} not found at {plugin_path}")

# Минимальный набор Qt DLLs
qt_dlls = ["Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"]
qt_dll_includes = []
for dll in qt_dlls:
    dll_path = os.path.join(pyside6_path, dll)  # Проверяем корень PySide6
    if not os.path.exists(dll_path):
        dll_path = os.path.join(pyside6_path, "Qt", "bin", dll)  # Проверяем Qt/bin
    if os.path.exists(dll_path):
        qt_dll_includes.append((dll_path, dll))
    else:
        print(f"Warning: {dll} not found at {dll_path}")

# MinGW зависимости
mingw_dlls = ["libstdc++-6.dll", "libgcc_s_seh-1.dll", "libwinpthread-1.dll"]
qt_system_dll_includes = []
for dll in mingw_dlls:
    dll_path = os.path.join(pyside6_path, dll)
    if not os.path.exists(dll_path):
        # Пробуем найти в системных путях или рядом с Python
        dll_path = os.path.join(os.path.dirname(sys.executable), dll)
    if os.path.exists(dll_path):
        qt_system_dll_includes.append((dll_path, dll))
    else:
        print(f"Warning: {dll} not found at {dll_path}")

# Полный релиз
full_build_options = {
    "packages": packages,
    "includes": includes,
    "excludes": excludes,
    "include_files": [
        ("version.json", "version.json"),
        ("help_content.json", "help_content.json"),
        ("temp-files", "temp-files"),
        ("icons", "icons"),
    ] + qt_plugins_includes + qt_dll_includes + qt_system_dll_includes,
    "build_exe": "VideoBot",
    "replace_paths": []  # Отключаем кэширование путей
}

# Инкрементальный релиз
incremental_build_options = {
    "packages": packages,
    "includes": includes,
    "excludes": excludes,
    "include_files": [
        ("version.json", "version.json"),
        ("help_content.json", "help_content.json"),
        ("icons", "icons"),
    ] + qt_plugins_includes + qt_dll_includes + qt_system_dll_includes,
    "build_exe": "VideoBot",
    "replace_paths": []  # Отключаем кэширование путей
}

# Определяем тип сборки из переменной окружения
build_type = os.getenv("BUILD_TYPE", "full")
build_options = full_build_options if build_type == "full" else incremental_build_options

# Настройка
setup(
    name="VideoBot",
    version=version,
    description="Telegram Video Bot",
    options={"build_exe": build_options},  # Все опции для build_exe здесь
    executables=executables
)