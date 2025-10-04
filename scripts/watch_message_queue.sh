#!/bin/bash
# Simple watcher for the LangGraph message queue
# Refreshes the last few entries from messages.db

DB_PATH="messages.db"
if [[ ! -f "$DB_PATH" ]]; then
  echo "messages.db not found at $DB_PATH"
  exit 1
fi

while true; do
  clear
  sqlite3 "$DB_PATH" "SELECT id, status, retry_count, created_at FROM messages ORDER BY datetime(created_at) DESC LIMIT 5;"
  sleep 1
done
