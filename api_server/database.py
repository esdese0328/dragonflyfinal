import sqlite3

#資料庫檔案名稱
DB_NAME = "scheduler.db"

def init_db():
    #連線到SQLite，如果檔案不存在會自動建立
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    #1.建立Tasks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            task_name TEXT NOT NULL,
            status TEXT NOT NULL,
            worker_id TEXT,
            retry_count INTEGER DEFAULT 0,
            duration REAL,
            completed_at TIMESTAMP,
            progress INTEGER DEFAULT 0
        )
    ''')

    #2.建立Workers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            worker_id TEXT PRIMARY KEY,
            worker_name TEXT NOT NULL,
            status TEXT NOT NULL,
            last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    #儲存變更並關閉連線
    conn.commit()
    conn.close()
    print("Database initialized successfully.")