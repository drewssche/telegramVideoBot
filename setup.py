import os
import sys
from cx_Freeze import setup, Executable

# Проверка наличия PySide6
try:
    import PySide6
except ImportError:
    print("Error: PySide6 is not installed. Please install it using 'pip install PySide6'.")
    sys.exit(1)

# Читаем версию из version.json
with open("version.json", "r", encoding="utf-8") as f:
    import json
    version_data = json.load(f)
    version = version_data["version"]
    print(f"Version from version.json: {version}")

# Базовые настройки
base = "Win32GUI" if sys.platform == "win32" else None
executables = [
    Executable(
        script="VideoBot.py",
        base=base,
        target_name="VideoBot.exe",
        icon="icons/256.ico",
        uac_admin=True  # Требование прав администратора
    )
]

# Минимальный набор пакетов
packages = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "sys",
    "shutil",
    "subprocess",
    "webbrowser",
    "os",
    "logging"
]
includes = []
excludes = []

# Находим PySide6 и Qt зависимости
pyside6_path = os.path.dirname(sys.modules["PySide6"].__file__)
print(f"PySide6 path: {pyside6_path}")

# Включаем только необходимые Qt плагины
necessary_plugins = ["platforms", "imageformats/qico.dll"]
qt_plugins_includes = []
for plugin in necessary_plugins:
    plugin_path = os.path.join(pyside6_path, "plugins", plugin)
    if os.path.exists(plugin_path):
        qt_plugins_includes.append((plugin_path, f"PySide6/plugins/{plugin}"))
        print(f"Including Qt plugin: {plugin_path}")
    else:
        print(f"Warning: Qt plugin {plugin} not found at {plugin_path}")

# Минимальный набор Qt DLLs
qt_dlls = ["Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"]
qt_dll_includes = []
for dll in qt_dlls:
    dll_path = os.path.join(pyside6_path, dll)
    if not os.path.exists(dll_path):
        dll_path = os.path.join(pyside6_path, "Qt", "bin", dll)
    if os.path.exists(dll_path):
        qt_dll_includes.append((dll_path, dll))
        print(f"Including Qt DLL: {dll_path}")
    else:
        print(f"Warning: {dll} not found at {dll_path}")

# MinGW зависимости
mingw_dlls = ["libstdc++-6.dll", "libgcc_s_seh-1.dll", "libwinpthread-1.dll"]
qt_system_dll_includes = []
for dll in mingw_dlls:
    dll_path = os.path.join(pyside6_path, dll)
    if not os.path.exists(dll_path):
        dll_path = os.path.join(os.path.dirname(sys.executable), dll)
    if os.path.exists(dll_path):
        qt_system_dll_includes.append((dll_path, dll))
        print(f"Including MinGW DLL: {dll_path}")
    else:
        print(f"Warning: {dll} not found at {dll_path}")

# Добавляем манифест в include_files
manifest_file = "VideoBot.exe.manifest"
if not os.path.exists(manifest_file):
    print(f"Warning: {manifest_file} not found. It should be created before building.")

# Добавляем папку byedpi с ciadpi.exe
byedpi_dir = "byedpi"
if os.path.exists(byedpi_dir):
    print(f"Including byedpi directory: {byedpi_dir}")
else:
    print(f"Warning: {byedpi_dir} not found. Ensure it exists with ciadpi.exe before building.")

# Настройки сборки
build_options = {
    "packages": packages,
    "includes": includes,
    "excludes": excludes,
    "include_files": [
        ("version.json", "version.json"),
        ("help_content.json", "help_content.json"),
        ("icons", "icons"),
        ("bot.py", "bot.py"),
        ("requirements.txt", "requirements.txt"),
        (manifest_file, manifest_file),
        (byedpi_dir, "byedpi"),  # Добавляем папку byedpi
    ] + qt_plugins_includes + qt_dll_includes + qt_system_dll_includes,
    "build_exe": "VideoBot",
    "replace_paths": []
}

# Настройка
setup(
    name="VideoBotLoader",
    version=version,
    description="VideoBot Loader",
    options={"build_exe": build_options},
    executables=executables
)
print("Setup completed")