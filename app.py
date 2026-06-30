import streamlit as st
import requests
import datetime
import pytz
import folium
from streamlit_folium import st_folium
import matplotlib.pyplot as plt
import pandas as pd

# 画面を横いっぱいに広く使う設定
st.set_page_config(layout="wide", page_title="赤川花火 リアルタイム交通量マップ")

st.title("🚗 赤川花火 リアルタイム交通量マップ")
st.caption("※サイトを開いた（またはリロードした）瞬間の最新データをJARTIC APIから取得して表示します。")

# --- 設定項目 ---
OBSERVATION_POINT_CODES = ["2110491", "2110488"]
API_URL = "https://api.jartic-open-traffic.org/geoserver"
PCU_THRESHOLD = 30

def fetch_point_data(observation_code, target_time):
    time_code = target_time.strftime(f"%Y%m%d%H{(target_time.minute // 5) * 5:02d}")
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "t_travospublic_measure_5m",
        "srsName": "EPSG:4326",
        "outputFormat": "application/json",
        "cql_filter": f"道路種別='3' AND 時間コード={time_code} AND 常時観測点コード='{observation_code}'"
    }
    try:
        response = requests.get(API_URL, params=params, timeout=10)
        data = response.json()
        if data.get("numberMatched", 0) > 0:
            feature = data["features"][0]
            props = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"][0]

            u_small = props.get("上り・小型交通量") or 0
            u_large = props.get("上り・大型交通量") or 0
            u_unknown = props.get("上り・車種判別不能交通量") or 0
            d_small = props.get("下り・小型交通量") or 0
            d_large = props.get("下り・大型交通量") or 0
            d_unknown = props.get("下り・車種判別不能交通量") or 0

            u_pcu = u_small + u_unknown + (u_large * 1.7)
            d_pcu = d_small + d_unknown + (d_large * 1.7)

            return {
                "display_time": target_time.strftime("%H:%M"),
                "lat": lat,
                "lon": lon,
                "u_pcu": u_pcu,
                "d_pcu": d_pcu,
                "timestamp": target_time.strftime("%Y-%m-%d %H:%M")
            }
    except:
        pass
    return None

# データ取得開始
jst = pytz.timezone('Asia/Tokyo')
now_jst = datetime.datetime.now(jst)

data_points = []
all_charts_data = {}

# スピナー（読み込み中アニメーション）を表示しながらデータを集計
with st.spinner("JARTICから最新の交通データを取得中..."):
    for code in OBSERVATION_POINT_CODES:
        chart_data = []
        latest_info = None

        # 過去60分（5分刻み×12回分）のデータを遡って取得
        for i in range(12, -1, -1):
            target_time = now_jst - datetime.timedelta(minutes=25 + (i * 5))
            res = fetch_point_data(code, target_time)
            if res:
                chart_data.append({
                    'Time': res['display_time'],
                    '上り交通量 (pcu)': res['u_pcu'],
                    '下り交通量 (pcu)': res['d_pcu']
                })
                latest_info = res

        if latest_info:
            latest_info['code'] = code
            data_points.append(latest_info)
            if chart_data:
                all_charts_data[code] = pd.DataFrame(chart_data)

if not data_points:
    st.error("現在、JARTIC APIからデータを取得できません。しばらく時間を置いてから再度お試しください。")
else:
    # 画面を2カラム（左：地図、右：グラフ）に分割
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("📍 現在の混雑マップ")
        avg_lat = sum(p['lat'] for p in data_points) / len(data_points)
        avg_lon = sum(p['lon'] for p in data_points) / len(data_points)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=13)

        for point in data_points:
            popup_html = f"""
            <h4>地点コード: {point['code']}</h4>
            <p>更新時刻: {point['timestamp']}</p>
            <p><b>上り:</b> {point['u_pcu']:.1f} pcu/5m<br><b>下り:</b> {point['d_pcu']:.1f} pcu/5m</p>
            """
            is_congested = point['u_pcu'] >= PCU_THRESHOLD or point['d_pcu'] >= PCU_THRESHOLD
            color = 'red' if is_congested else 'blue'

            folium.Marker(
                [point['lat'], point['lon']],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"地点 {point['code']}",
                icon=folium.Icon(color=color, icon="info-sign")
            ).add_to(m)

        # 地図をStreamlit上に描画
        st_folium(m, width="100%", height=500, returned_objects=[])

    with col2:
        st.subheader("📊 直近60分の交通量推移")
        for code, df_chart in all_charts_data.items():
            st.write(f"**地点コード: {code}**")
            # Streamlit標準の綺麗な折れ線グラフで表示
            st.line_chart(df_chart.set_index('Time'))
