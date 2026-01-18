#!/usr/bin/env bash
# Скрипт для остановки log_listener.py где бы он ни был запущен

BASEDIR=$(dirname "$0")
PID_FILE="$BASEDIR/.log_listener.pid"

# Способ 1: Через PID-файл
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Убиваем слушатель с PID $PID (из PID-файла)"
        kill "$PID" 2>/dev/null
        rm -f "$PID_FILE"
        exit 0
    else
        echo "Процесс $PID не существует, удаляем устаревший PID-файл"
        rm -f "$PID_FILE"
    fi
fi

# Способ 2: Поиск по имени процесса
PIDS=$(pgrep -f "log_listener.py" 2>/dev/null)

if [ -n "$PIDS" ]; then
    echo "Найдены процессы log_listener.py: $PIDS"
    for PID in $PIDS; do
        echo "Убиваем процесс $PID"
        kill "$PID" 2>/dev/null
    done
    echo "Готово"
    exit 0
fi

echo "Процесс log_listener.py не найден"
exit 0
