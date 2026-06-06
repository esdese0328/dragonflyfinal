from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import uuid  #用來產生亂數的Task ID
from database import init_db, DB_NAME  #引入資料庫檔案
from datetime import datetime, timezone, timedelta

#啟動時初始化資料庫
init_db()

app = FastAPI(title="Dragonfly Scheduler API")

#定義API規格
class TaskCreateModel(BaseModel):
    task_name: str

class TaskResponseModel(BaseModel):
    task_id: str
    task_name: str
    status: str
    worker_id: Optional[str] = None
    retry_count: int = 0
    duration: Optional[float] = None
    completed_at: Optional[str] = None
    progress: int = 0

class TaskAssign(BaseModel):
    worker_id: str

class WorkerCreateModel(BaseModel):
    worker_name: str

class WorkerResponseModel(BaseModel):
    worker_id: str
    worker_name: str
    status: str
    last_heartbeat: str

#實作API邏輯
#建立任務
@app.post("/creat_task", response_model=TaskResponseModel)
def create_task(task: TaskCreateModel):
    #產生獨一無二的任務ID
    new_task_id = str(uuid.uuid4()) 
    
    #連線資料庫並寫入資料
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (task_id, task_name, status, retry_count)
        VALUES (?, ?, ?, ?)
    ''', (new_task_id, task.task_name, 'pending', 0))
    
    conn.commit()
    conn.close()

    #回傳建立好的任務資訊
    return {
        "task_id": new_task_id,
        "task_name": task.task_name,
        "status": "pending",
        "retry_count": 0,
        "duration": None,
        "completed_at": None,
        "progress": 0
    }

#查詢任務狀態
@app.get("/get_tasks", response_model=List[TaskResponseModel])
def get_tasks(status: Optional[str] = None):
    conn = sqlite3.connect(DB_NAME)
    #讓SQLite回傳字典格式
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()

    #根據有沒有傳入status來決定SQL語法
    if status:
        cursor.execute('SELECT * FROM tasks WHERE status = ?', (status,))
    else:
        cursor.execute('SELECT * FROM tasks')
        
    rows = cursor.fetchall()
    conn.close()

    #把撈出來的資料整理成API回傳格式
    result = []
    for row in rows:
        result.append({
            "task_id": row["task_id"],
            "task_name": row["task_name"],
            "status": row["status"],
            "worker_id": row["worker_id"],
            "retry_count": row["retry_count"],
            "duration": row["duration"],
            "completed_at": row["completed_at"],
            "progress": row["progress"]
        })
    return result

#指派任務給worker
@app.put("/tasks/{task_id}/assign")
def assign_task(task_id: str, payload: TaskAssign):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    #填入worker_id，並將狀態改為downloading
    cursor.execute('''
        UPDATE tasks 
        SET worker_id = ?, status = 'downloading'
        WHERE task_id = ?
    ''', (payload.worker_id, task_id))
    
    conn.commit()
    conn.close()
    
    return {"message": f"Task {task_id} assigned to {payload.worker_id}"}

#更新任務進度
class TaskProgressUpdate(BaseModel):
    progress: int
    duration: Optional[float] = None

@app.put("/tasks/{task_id}/progress")
def update_task_progress(task_id: str, payload: TaskProgressUpdate):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    #若進度到達100，則自動更新為 completed 並記錄完成時間
    if payload.progress >= 100:
        tz_utc_8 = timezone(timedelta(hours=8))
        current_time = datetime.now(tz_utc_8).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            UPDATE tasks 
            SET progress = 100, status = 'completed', completed_at = ?, duration = ?
            WHERE task_id = ?
        ''', (current_time, payload.duration, task_id))
    else:
        cursor.execute('''
            UPDATE tasks 
            SET progress = ?
            WHERE task_id = ?
        ''', (payload.progress, task_id))
        
    conn.commit()
    conn.close()
    return {"message": f"Task {task_id} progress updated to {payload.progress}"}

#建立Worker
@app.post("/create_worker", response_model=WorkerResponseModel)
def create_worker(worker: WorkerCreateModel):
    new_worker_id = str(uuid.uuid4()) 
    #last_heartbeat存入當下時間戳記
    tz_utc_8 = timezone(timedelta(hours=8))
    current_time = datetime.now(tz_utc_8).strftime("%Y-%m-%d %H:%M:%S")    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
                   INSERT INTO workers (worker_id, worker_name, status, last_heartbeat)
                   VALUES (?, ?, ?, ?)
    ''', (new_worker_id, worker.worker_name, 'pending', current_time))
    
    conn.commit()
    conn.close()

    return {
        "worker_id": new_worker_id,
        "worker_name": worker.worker_name,
        "status": 'pending',
        "last_heartbeat": current_time
    }

#查詢Worker狀態
@app.get("/get_workers", response_model=List[WorkerResponseModel])
def get_workers():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM workers')
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "worker_id": row["worker_id"],
            "worker_name": row["worker_name"],
            "status": row["status"],
            "last_heartbeat": row["last_heartbeat"]
        })
    return result

#Worker last_heartbeat更新
@app.put("/workers/{worker_id}/heartbeat")
def update_worker_heartbeat(worker_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    tz_utc_8 = timezone(timedelta(hours=8))
    current_time = datetime.now(tz_utc_8).strftime("%Y-%m-%d %H:%M:%S")    
    cursor.execute('''
        UPDATE workers 
        SET last_heartbeat = ?
        WHERE worker_id = ?
    ''', (current_time, worker_id))
    
    conn.commit()
    conn.close()
    
    return {"message": f"Heartbeat updated for worker {worker_id}"}

#任務失敗重新排程 (Retry)
@app.put("/tasks/{task_id}/retry")
def retry_task(task_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tasks
        SET retry_count = retry_count + 1, status = 'pending', worker_id = NULL
        WHERE task_id = ?
    ''', (task_id,))

    conn.commit()
    conn.close()

    return {"message": f"Task {task_id} set to retry"}

#任務永久失敗 (供 Scheduler 在 retry 次數用盡時呼叫)
@app.put("/tasks/{task_id}/fail")
def fail_task(task_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tasks
        SET status = 'failed'
        WHERE task_id = ?
    ''', (task_id,))

    conn.commit()
    conn.close()

    return {"message": f"Task {task_id} marked as failed"}