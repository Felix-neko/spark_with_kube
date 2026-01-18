#!/usr/bin/env python3
"""
Скрипт-слушатель для приёма логов Spark-драйвера через сокет.

Использование:
    python log_listener.py [--port PORT] [--timeout SECONDS] [--exit-on-disconnect]

Опции:
    --port PORT             Порт для прослушивания (по умолчанию: 9999)
    --timeout SECONDS       Таймаут ожидания подключения в секундах (по умолчанию: 60)
    --exit-on-disconnect    Завершиться после отключения драйвера (по умолчанию: ждать новые подключения)
"""

import argparse
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


# PID-файл для возможности убить слушатель из другого процесса
PID_FILE = Path(__file__).parent / ".log_listener.pid"


def save_pid():
    """Сохраняет PID текущего процесса в файл."""
    PID_FILE.write_text(str(os.getpid()))


def remove_pid():
    """Удаляет PID-файл."""
    if PID_FILE.exists():
        PID_FILE.unlink()


def timestamp():
    """Возвращает текущее время в формате HH:MM:SS."""
    return datetime.now().strftime("%H:%M:%S")


def log_info(msg: str):
    """Выводит информационное сообщение."""
    print(f"[{timestamp()}] [INFO] {msg}", flush=True)


def log_error(msg: str):
    """Выводит сообщение об ошибке."""
    print(f"[{timestamp()}] [ERROR] {msg}", file=sys.stderr, flush=True)


def handle_client(client_socket: socket.socket, client_address: tuple, exit_event: threading.Event):
    """Обрабатывает подключение клиента и выводит логи."""
    log_info(f">>> ДРАЙВЕР ПОДКЛЮЧИЛСЯ: {client_address[0]}:{client_address[1]} <<<")
    print("=" * 60, flush=True)
    
    try:
        buffer = ""
        while not exit_event.is_set():
            try:
                # Устанавливаем таймаут на чтение, чтобы можно было проверить exit_event
                client_socket.settimeout(1.0)
                data = client_socket.recv(4096)
                
                if not data:
                    # Клиент отключился
                    break
                
                # Декодируем и выводим логи
                text = data.decode("utf-8", errors="replace")
                buffer += text
                
                # Выводим построчно
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    print(line, flush=True)
                    
            except socket.timeout:
                continue
            except ConnectionResetError:
                break
                
    except Exception as e:
        log_error(f"Ошибка при обработке клиента: {e}")
    finally:
        # Выводим оставшийся буфер
        if buffer:
            print(buffer, flush=True)
        
        client_socket.close()
        print("=" * 60, flush=True)
        log_info(f">>> ДРАЙВЕР ОТКЛЮЧИЛСЯ: {client_address[0]}:{client_address[1]} <<<")


def run_listener(port: int, timeout: int, exit_on_disconnect: bool):
    """Запускает слушатель на указанном порту."""
    save_pid()
    
    exit_event = threading.Event()
    connection_received = threading.Event()
    
    def signal_handler(signum, frame):
        log_info("Получен сигнал завершения")
        exit_event.set()
        remove_pid()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind(("0.0.0.0", port))
        server_socket.listen(1)
        server_socket.settimeout(1.0)  # Таймаут для проверки exit_event
        
        log_info(f"Слушатель запущен на порту {port}")
        log_info(f"Таймаут ожидания подключения: {timeout} сек")
        log_info(f"Режим: {'завершиться после отключения' if exit_on_disconnect else 'ждать новые подключения'}")
        log_info("Ожидание подключения драйвера...")
        
        start_time = time.time()
        
        while not exit_event.is_set():
            # Проверяем таймаут ожидания первого подключения
            if not connection_received.is_set():
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    log_error(f"Таймаут {timeout} сек истёк, подключение не получено")
                    remove_pid()
                    sys.exit(1)
            
            try:
                client_socket, client_address = server_socket.accept()
                connection_received.set()
                
                # Обрабатываем клиента в текущем потоке (драйвер один)
                handle_client(client_socket, client_address, exit_event)
                
                if exit_on_disconnect:
                    log_info("Режим exit-on-disconnect: завершаемся")
                    break
                else:
                    log_info("Ожидание нового подключения...")
                    
            except socket.timeout:
                continue
        
        log_info("Слушатель завершён успешно")
        remove_pid()
        sys.exit(0)
        
    except OSError as e:
        log_error(f"Не удалось запустить слушатель: {e}")
        remove_pid()
        sys.exit(1)
    finally:
        server_socket.close()


def main():
    parser = argparse.ArgumentParser(description="Слушатель логов Spark-драйвера")
    parser.add_argument("--port", type=int, default=9999, help="Порт для прослушивания (по умолчанию: 9999)")
    parser.add_argument("--timeout", type=int, default=60, help="Таймаут ожидания подключения в секундах (по умолчанию: 60)")
    parser.add_argument("--exit-on-disconnect", action="store_true", help="Завершиться после отключения драйвера")
    
    args = parser.parse_args()
    
    run_listener(args.port, args.timeout, args.exit_on_disconnect)


if __name__ == "__main__":
    main()
