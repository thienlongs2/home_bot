import sqlite3

conn = sqlite3.connect("trading_history.db")
cursor = conn.cursor()
cursor.execute("SELECT * FROM trades")
rows = cursor.fetchall()
for row in rows:
    print(row)
conn.close()