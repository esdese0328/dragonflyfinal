import time
import requests
import random
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")

def get_tasks():
    try:
        response = requests.get(f"{API_URL}/get_tasks")
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return []

def get_workers():
    try:
        response = requests.get(f"{API_URL}/get_workers")
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return []

def create_worker(name):
    try:
        response = requests.post(f"{API_URL}/create_worker", json={"worker_name": name})
        return response.json().get("worker_id")
    except:
        pass
    return None

def heartbeat(worker_id):
    try:
        requests.put(f"{API_URL}/workers/{worker_id}/heartbeat")
    except:
        pass

def update_progress(task_id, new_progress):
    try:
        payload = {"progress": new_progress}
        if new_progress >= 100:
            payload["duration"] = round(random.uniform(5.0, 45.0), 1)
        requests.put(f"{API_URL}/tasks/{task_id}/progress", json=payload)
        print(f"Task {task_id} progress -> {new_progress}%")
    except Exception as e:
        print(f"Error updating task {task_id}: {e}")

def assign_task(task_id, worker_id):
    try:
        requests.put(f"{API_URL}/tasks/{task_id}/assign", json={"worker_id": worker_id})
        print(f"Task {task_id} assigned to {worker_id}")
    except:
        pass

def create_task(name):
    try:
        requests.post(f"{API_URL}/creat_task", json={"task_name": name})
        print(f"Created new task: {name}")
    except:
        pass

def retry_task(task_id):
    try:
        requests.put(f"{API_URL}/tasks/{task_id}/retry")
        print(f"Task {task_id} failed and is retrying...")
    except Exception as e:
        print(f"Error retrying task {task_id}: {e}")

if __name__ == "__main__":
    print("Starting Simulate Worker...")
    
    # 確認是否有 Worker，沒有就建立
    existing_workers = get_workers()
    worker_ids = [w['worker_id'] for w in existing_workers]
    
    if not worker_ids:
        for i in range(1, 4):
            wid = create_worker(f"SimWorker-Node-{i}")
            if wid:
                worker_ids.append(wid)
    
    create_task("Simulated Video Download (10GB)")
    create_task("Simulated Model Weights (5GB)")
    
    while True:
        tasks = get_tasks()
        active_tasks = [t for t in tasks if t['status'] in ('pending', 'downloading')]
        
        # 發送心跳
        for wid in worker_ids:
            heartbeat(wid)
            
        if not active_tasks:
            # 如果沒有任務，偶爾隨機產生一個新任務
            if random.random() < 0.2:
                tools = ["[curl]", "[dfget]"]
                sizes = ["100MB", "500MB", "1GB"]
                create_task(f"{random.choice(tools)} {random.choice(sizes)} Data {random.randint(100, 999)}")
        
        for task in active_tasks:
            task_id = task['task_id']
            status = task['status']
            progress = task.get('progress', 0)
            
            if status == 'pending':
                # 隨機分配給其中一個 Worker
                if worker_ids:
                    assign_task(task_id, random.choice(worker_ids))
            elif status == 'downloading':
                # 有一點機率任務會失敗 (測試 Fault Recovery)
                if random.random() < 0.05:
                    retry_task(task_id)
                    continue

                increment = random.randint(5, 15)
                new_progress = min(100, progress + increment)
                update_progress(task_id, new_progress)
                
        time.sleep(2)
