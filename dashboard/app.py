import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import time

# 設定頁面資訊
st.set_page_config(
    page_title="Dragonfly System Dashboard",
    layout="wide"
)

# API Server 網址，支援從環境變數讀取
API_URL = os.getenv("API_URL", "http://api_server:8000")

def fetch_data(endpoint):
    try:
        response = requests.get(f"{API_URL}/{endpoint}", timeout=2)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"連線至 {endpoint} 失敗: {e}")
    return []

# 建立自動重新整理的按鈕區塊
st.sidebar.title("設定")
auto_refresh = st.sidebar.checkbox("自動更新 (每2秒)", value=False)

col1, col2 = st.columns([10, 1])
with col1:
    st.title(" Dragonfly 系統狀態監控")
with col2:
    if st.button("手動整理"):
        st.rerun()

# 取得資料
tasks_data = fetch_data("get_tasks")
workers_data = fetch_data("get_workers")

df_tasks = pd.DataFrame(tasks_data)
df_workers = pd.DataFrame(workers_data)

st.markdown("---")

# 總覽數據 (Metrics)
st.subheader("系統總覽")
m1, m2, m3, m4, m5 = st.columns(5)

total_tasks = len(df_tasks) if not df_tasks.empty else 0
completed_tasks = len(df_tasks[df_tasks['status'] == 'completed']) if not df_tasks.empty else 0
failed_tasks = len(df_tasks[df_tasks['status'] == 'failed']) if not df_tasks.empty else 0
online_workers = len(df_workers) if not df_workers.empty else 0
total_retries = int(df_tasks['retry_count'].sum()) if not df_tasks.empty and 'retry_count' in df_tasks.columns else 0

m1.metric("總任務數", total_tasks)
m2.metric("已完成任務", completed_tasks)
m3.metric("失敗任務", failed_tasks)
m4.metric("線上 Worker 數", online_workers)
m5.metric("觸發 Retry 總數", total_retries)

st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["任務清單", "Worker 狀態", "圖表分析", "故障恢復紀錄"])

with tab1:
    st.subheader("任務明細")
    if not df_tasks.empty:
        display_df = df_tasks[['task_id', 'task_name', 'status', 'worker_id', 'progress', 'retry_count', 'duration', 'completed_at']]
        st.dataframe(
            display_df, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "progress": st.column_config.ProgressColumn(
                    "下載進度",
                    help="目前的下載完成度",
                    format="%d%%",
                    min_value=0,
                    max_value=100,
                )
            }
        )
    else:
        st.info("目前沒有任何任務。")

with tab2:
    st.subheader("Worker 狀態")
    if not df_workers.empty:
        st.dataframe(df_workers, use_container_width=True, hide_index=True)
    else:
        st.info("目前沒有連線中的 Worker")

with tab3:
    st.subheader("任務狀態分佈")
    if not df_tasks.empty:
        status_counts = df_tasks['status'].value_counts().reset_index()
        status_counts.columns = ['狀態', '數量']
        fig = px.pie(status_counts, names='狀態', values='數量', hole=0.3, color_discrete_sequence=px.colors.sequential.Teal)
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("效能分析 Benchmark (curl vs dfget)")
        df_valid_duration = df_tasks.dropna(subset=['duration'])
        if not df_valid_duration.empty:
            # 篩選包含 curl 或 dfget 的任務
            df_bench = df_valid_duration[df_valid_duration['task_name'].str.contains('curl|dfget', case=False, na=False)].copy()
            if not df_bench.empty:
                df_bench['tool'] = df_bench['task_name'].apply(lambda x: 'curl' if 'curl' in x.lower() else 'dfget')
                fig_bench = px.box(df_bench, x='tool', y='duration', color='tool', points='all',
                                   labels={'duration': '耗時 (秒)', 'tool': '下載工具'},
                                   color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_bench, use_container_width=True)
            else:
                st.info("尚未有包含 '[curl]' 或 '[dfget]' 關鍵字的 Benchmark 測試資料。")

            df_cache = df_valid_duration[
                df_valid_duration['task_name'].str.contains(
                    'first-download|cached-download', case=False, na=False
                )
            ].copy()
            if not df_cache.empty:
                df_cache['download_type'] = df_cache['task_name'].apply(
                    lambda x: 'cached-download' if 'cached-download' in x.lower() else 'first-download'
                )
                st.subheader("Dragonfly 快取下載比較")
                fig_cache = px.bar(
                    df_cache,
                    x='download_type',
                    y='duration',
                    color='download_type',
                    text='duration',
                    labels={'duration': '耗時 (秒)', 'download_type': '下載類型'},
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                st.plotly_chart(fig_cache, use_container_width=True)

                first = df_cache[df_cache['download_type'] == 'first-download']['duration'].iloc[-1:]
                cached = df_cache[df_cache['download_type'] == 'cached-download']['duration'].iloc[-1:]
                if not first.empty and not cached.empty and cached.iloc[0] > 0:
                    st.metric("Dragonfly 快取加速倍數", f"{first.iloc[0] / cached.iloc[0]:.2f}x")

            st.subheader("個別下載耗時")
            fig2 = px.bar(df_valid_duration, x='task_name', y='duration', color='status',
                          labels={'duration': '耗時 (秒)', 'task_name': '任務名稱'},
                          color_discrete_sequence=px.colors.sequential.Teal)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("目前尚無下載耗時數據。")
    else:
        st.info("目前沒有任何任務以供分析。")

with tab4:
    st.subheader("故障恢復紀錄 (Fault Recovery Log)")
    if not df_tasks.empty and 'retry_count' in df_tasks.columns:
        df_retry = df_tasks[df_tasks['retry_count'] > 0]
        if not df_retry.empty:
            display_retry = df_retry[['task_id', 'task_name', 'retry_count', 'status', 'completed_at']]
            st.dataframe(display_retry.sort_values(by='retry_count', ascending=False), use_container_width=True, hide_index=True)
        else:
            st.success("系統穩定，目前尚無任何任務發生重試 (Retry)。")
    else:
        st.info("目前沒有任何任務。")

if auto_refresh:
    time.sleep(2)
    st.rerun()
