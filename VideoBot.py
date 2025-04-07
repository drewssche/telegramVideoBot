# VideoBot.py (обновлённый)
import sys
import shutil
import subprocess
import webbrowser
import os
import logging
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel, QProgressBar, QPushButton, QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

# Настройка логирования
logging.basicConfig(
    filename="loader.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

class LoadingWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Video Bot - Загрузка")
        self.setFixedSize(400, 300)
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

        # Установка иконки
        icon_path = "icons/256.ico"
        icon = QIcon(icon_path)
        if icon.isNull():
            logging.warning(f"Не удалось загрузить иконку из {icon_path}")
        else:
            logging.info(f"Иконка успешно загружена из {icon_path}")
            self.setWindowIcon(icon)

        # Основной виджет и layout
        widget = QWidget()
        self.setCentralWidget(widget)
        layout = QVBoxLayout(widget)

        # Метка статуса
        self.status_label = QLabel("Проверка Python 3.7+...", alignment=Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #FFFFFF;")  # Явно задаём белый цвет
        layout.addWidget(self.status_label)

        # Прогресс-бар
        self.progress_bar = QProgressBar(maximum=100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")  # Устанавливаем формат как в UpdateDialog
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

        # Кнопка "Установить Python" (появляется, если Python отсутствует)
        self.install_python_button = QPushButton("Установить Python 3.10")
        self.install_python_button.clicked.connect(self.install_python)
        self.install_python_button.setVisible(False)
        layout.addWidget(self.install_python_button)

        # Кнопка "Повторить" (появляется при ошибке)
        self.retry_button = QPushButton("Повторить")
        self.retry_button.clicked.connect(self.start_checks)
        self.retry_button.setVisible(False)
        layout.addWidget(self.retry_button)

        # Кнопка "Отмена"
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.close)
        layout.addWidget(self.cancel_button)

        # Запускаем проверки
        QTimer.singleShot(100, self.start_checks)

    def update_status(self, message, color="#FFFFFF", progress=None):
        """Обновляем статус с белым цветом по умолчанию."""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color}")
        if progress is not None:
            self.progress_bar.setValue(progress)
        QApplication.processEvents()

    def is_valid_python(self, python_path):
        """Проверяет, является ли путь рабочим интерпретатором Python."""
        try:
            result = subprocess.run([python_path, "--version"], capture_output=True, text=True, check=True)
            if result.stdout.startswith("Python"):
                version_parts = result.stdout.strip().split(" ")[1].split(".")
                major, minor = int(version_parts[0]), int(version_parts[1])
                if major == 3 and minor >= 7:
                    logging.info(f"Рабочий интерпретатор Python {major}.{minor} найден: {python_path}")
                    return True
            return False
        except Exception as e:
            logging.debug(f"Путь {python_path} не является рабочим интерпретатором: {str(e)}")
            return False

    def find_python_in_path(self):
        """Ищет Python в переменной PATH и стандартных директориях."""
        # Сначала проверяем через shutil.which
        for python_name in ["python3", "python"]:
            python_path = shutil.which(python_name)
            if python_path:
                logging.info(f"Путь найден через shutil.which({python_name}): {python_path}")
                if self.is_valid_python(python_path):
                    return python_path
                else:
                    logging.warning(f"Путь {python_path} (из shutil.which) не является рабочим интерпретатором")

        # Если не нашли через shutil.which, проверяем стандартные пути из PATH
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        common_python_dirs = [
            r"C:\Users\scheg\AppData\Local\Programs\Python\Python310",  # Ваш путь
            r"C:\Users\scheg\AppData\Local\Programs\Python\Python310\Scripts",
            r"C:\Python310",
            r"C:\Python39",
            r"C:\Python38",
            r"C:\Python37",
            r"C:\Program Files\Python310",
            r"C:\Program Files\Python39",
            r"C:\Program Files\Python38",
            r"C:\Program Files\Python37",
            r"C:\Users\scheg\AppData\Local\Microsoft\WindowsApps",  # Проблемный путь
        ]
        path_dirs.extend(common_python_dirs)

        for directory in path_dirs:
            if not directory:
                continue
            for python_name in ["python.exe", "python3.exe"]:
                possible_path = os.path.join(directory, python_name)
                if os.path.isfile(possible_path):
                    logging.info(f"Проверяем путь: {possible_path}")
                    if self.is_valid_python(possible_path):
                        return possible_path
        logging.warning("Рабочий интерпретатор Python не найден")
        return None

    def check_python_version(self, python_path):
        """Проверяет, является ли версия Python 3.7 или выше."""
        try:
            result = subprocess.run([python_path, "--version"], capture_output=True, text=True, check=True)
            version_str = result.stdout.strip()
            version_parts = version_str.split(" ")[1].split(".")
            major, minor = int(version_parts[0]), int(version_parts[1])
            if major == 3 and minor >= 7:
                return True, f"Python {major}.{minor} ✅"
            return False, f"Python {major}.{minor} ❌ (требуется 3.7+)"
        except Exception as e:
            logging.error(f"Ошибка проверки версии Python: {str(e)}")
            return False, "Python не найден ❌"

    def check_module(self, python_path, module_name):
        """Проверяет, установлен ли модуль."""
        try:
            result = subprocess.run([python_path, "-c", f"import {module_name}"], capture_output=True, text=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def start_checks(self):
        self.retry_button.setVisible(False)
        self.install_python_button.setVisible(False)
        self.cancel_button.setEnabled(True)

        # Шаг 1: Проверка Python 3.7+
        self.update_status("Проверка Python 3.7+...", progress=0)
        # Если запущен как скрипт, используем sys.executable, иначе ищем в PATH
        if getattr(sys, "frozen", False):  # Проверяем, скомпилировано ли приложение
            python_path = self.find_python_in_path()  # Используем расширенный поиск
        else:
            python_path = sys.executable  # Используем текущий интерпретатор

        if not python_path:
            logging.warning("Python не найден")
            self.update_status("Python не найден ❌", color="red", progress=25)
            self.install_python_button.setVisible(True)
            self.cancel_button.setEnabled(True)
            return

        # Проверяем версию Python
        is_valid, version_message = self.check_python_version(python_path)
        if not is_valid:
            logging.warning("Версия Python ниже 3.7")
            self.update_status(version_message, color="red", progress=25)
            self.install_python_button.setVisible(True)
            self.cancel_button.setEnabled(True)
            return
        logging.info(f"Python 3.7+ найден: {python_path}")
        self.update_status(version_message, color="#4CAF50", progress=25)

        # Шаг 2: Проверка pip
        self.update_status("Проверка pip...", progress=25)
        pip_path = shutil.which("pip")
        if not pip_path:
            logging.warning("pip не найден, пытаемся установить")
            self.update_status("Установка pip... ⏳", progress=30)
            try:
                subprocess.run([python_path, "-m", "ensurepip", "--upgrade"], check=True)
                subprocess.run([python_path, "-m", "pip", "install", "--upgrade", "pip"], check=True)
                pip_path = shutil.which("pip")
                if not pip_path:
                    raise Exception("Не удалось установить pip")
                logging.info("pip успешно установлен")
                self.update_status("pip установлен ✅", color="#4CAF50", progress=50)
            except Exception as e:
                logging.error(f"Ошибка установки pip: {str(e)}")
                self.update_status(f"Ошибка установки pip ❌", color="red", progress=50)
                self.retry_button.setVisible(True)
                return

        # Шаг 3: Установка зависимостей
        self.update_status("Установка зависимостей... ⏳", progress=50)
        try:
            if not os.path.exists("requirements.txt"):
                raise FileNotFoundError("Файл requirements.txt не найден")
            # Используем python_path для вызова pip
            result = subprocess.run([python_path, "-m", "pip", "install", "-r", "requirements.txt"], capture_output=True, text=True, check=True)
            logging.info("Зависимости успешно установлены")
            logging.debug(f"Вывод pip: {result.stdout}")
            self.update_status("Зависимости установлены ✅", color="#4CAF50", progress=75)
        except subprocess.CalledProcessError as e:
            logging.error(f"Ошибка установки зависимостей: {e.stderr}")
            self.update_status("Ошибка установки зависимостей ❌", color="red", progress=75)
            self.retry_button.setVisible(True)
            return
        except FileNotFoundError as e:
            logging.error(str(e))
            self.update_status(f"{str(e)} ❌", color="red", progress=75)
            self.retry_button.setVisible(True)
            return

        # Шаг 3.5: Проверка наличия ключевых модулей
        self.update_status("Проверка установленных модулей...", progress=75)
        required_modules = ["telethon", "PySide6", "yt_dlp"]
        missing_modules = []
        for module in required_modules:
            if not self.check_module(python_path, module):
                missing_modules.append(module)
        if missing_modules:
            logging.error(f"Отсутствуют модули: {', '.join(missing_modules)}")
            self.update_status(f"Отсутствуют модули: {', '.join(missing_modules)} ❌", color="red", progress=75)
            self.update_status("Попробуйте установить вручную: pip install -r requirements.txt", color="red", progress=75)
            self.retry_button.setVisible(True)
            return

        # Шаг 4: Проверка FFmpeg
        self.update_status("Проверка FFmpeg...", progress=75)
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logging.warning("FFmpeg не найден, пытаемся установить")
            self.update_status("Установка FFmpeg... ⏳", progress=80)
            try:
                subprocess.run(["winget", "install", "ffmpeg"], check=True)
                ffmpeg_path = shutil.which("ffmpeg")
                if not ffmpeg_path:
                    raise Exception("Не удалось установить FFmpeg")
                logging.info("FFmpeg успешно установлен")
                self.update_status("FFmpeg установлен ✅", color="#4CAF50", progress=100)
            except Exception as e:
                logging.error(f"Ошибка установки FFmpeg: {str(e)}")
                self.update_status("FFmpeg не установлен ❌", color="red", progress=100)
                self.retry_button.setVisible(True)
                return
        else:
            self.update_status("FFmpeg найден ✅", color="#4CAF50", progress=100)

        # Шаг 5: Запуск bot.py без консольного окна
        self.update_status(f"Все проверки пройдены ✅.\nЗапуск Telegram Video Bot...", color="#4CAF50", progress=100)
        try:
            # Проверяем, существует ли pythonw.exe в той же директории, что и python_path
            python_dir = os.path.dirname(python_path)
            pythonw_path = os.path.join(python_dir, "pythonw.exe")
            if os.path.isfile(pythonw_path):
                logging.info(f"Используем pythonw.exe для запуска bot.py: {pythonw_path}")
                subprocess.Popen([pythonw_path, "bot.py"])
            else:
                logging.warning(f"pythonw.exe не найден в {python_dir}, используем python.exe с CREATE_NO_WINDOW")
                CREATE_NO_WINDOW = 0x08000000  # Флаг для Windows, чтобы не создавать окно
                subprocess.Popen([python_path, "bot.py"], creationflags=CREATE_NO_WINDOW)
            logging.info("bot.py успешно запущен без консольного окна")
            QTimer.singleShot(500, self.close)
        except Exception as e:
            logging.error(f"Ошибка запуска bot.py: {str(e)}")
            self.update_status(f"Ошибка запуска Telegram Video Bot ❌", color="red", progress=100)
            self.retry_button.setVisible(True)

    def install_python(self):
        self.update_status("Установка Python 3.10... ⏳", progress=10)
        self.install_python_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        try:
            subprocess.run(["winget", "install", "python3.10"], check=True)
            logging.info("Python 3.10 успешно установлен")
            self.update_status("Python 3.10 установлен ✅. Перезапустите программу.", color="#4CAF50", progress=25)
            QTimer.singleShot(2000, self.close)
        except Exception as e:
            logging.error(f"Ошибка установки Python 3.10: {str(e)}")
            self.update_status("Не удалось установить Python ❌", color="red", progress=25)
            webbrowser.open("https://www.python.org/downloads/release/python-3100/")
            self.update_status("Скачайте Python 3.10 вручную", color="red", progress=25)
            QTimer.singleShot(2000, self.close)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Применяем стили в стиле основной программы
    app.setStyleSheet("""
        QWidget { 
            background-color: #2E2E2E; 
            color: #FFFFFF;
        }
        QLabel { 
            color: #FFFFFF;
        }
        QProgressBar { 
            background-color: #2E2E2E; 
            border: 1px solid #505050; 
            color: #FFFFFF;
            border-radius: 4px;
        }
        QProgressBar::chunk { 
            background-color: #00FF00; 
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
    """)

    window = LoadingWindow()
    window.show()
    sys.exit(app.exec())