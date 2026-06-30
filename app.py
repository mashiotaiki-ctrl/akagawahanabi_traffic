import streamlit as st
import requests
import datetime
import pytz
import folium
from streamlit_folium import st_folium
import pandas as pd

# 画面を横いっぱいに広く使う設定
st.set_page_config(layout="wide", page_title="赤川花火 リアルタイム交通量マップ")

st.title("🚗 赤川花火 リアルタイム交通量マップ")
st.caption("※サイトを開いた（またはリロードした）瞬間の最新データをJARTIC APIから取得して表示します。")

# --- 設定項目 ---
# 地点コードと日本語名のマッピング
POINT_MAP = {
    "2110491": "国道112号 湯殿山IC付近",
    "2110488": "国道112号 寒河江ダム付近"
}
OBSERVATION_POINT_CODES = list(POINT_MAP.keys())
API_URL = "https://api.jartic-open-traffic.org/geoserver"

# 渋滞判定の関数
def get_congestion_status(u_pcu, d_pcu):
    max_pcu = max(u_pcu, d_pcu)
    if max_pcu >= 60:
        return "🚨 渋滞しています", "red"
    elif max_pcu >= 40:
        return "⚠️ 渋滞の予兆があります", "orange"
    else:
        return "🟢 渋滞は発生していません", "green"

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
            latest_info['name'] = POINT_MAP[code]
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
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=11)

        for point in data_points:
            # 渋滞ステータスと色の決定
            status_text, color = get_congestion_status(point['u_pcu'], point['d_pcu'])

            # ① 地点名を押したときに出る詳しいポップアップ（クリックで開く）
            popup_html = f"""
            <div style="font-size: 14px; width: 220px;">
                <h4 style="margin: 0 0 5px 0; color: #333;">{point['name']}</h4>
                <p style="margin: 0 0 10px 0; font-size: 11px; color: #666;">（コード: {point['code']} / 更新: {point['timestamp']}）</p>
                <hr style="margin: 5px 0; border: 0; border-top: 1px solid #ccc;">
                <p style="margin: 5px 0;"><b>上り交通量:</b> {point['u_pcu']:.1f} pcu/5m</p>
                <p style="margin: 5px 0;"><b>下り交通量:</b> {point['d_pcu']:.1f} pcu/5m</p>
            </div>
            """
            
            # ② マップ上に「常時表示」されるテキスト用吹き出し（Tooltipの永久表示化）
            # HTMLとCSSを使って見やすいミニ看板を作成
            tooltip_html = f"""
            <div style="
                font-size: 12px; 
                font-weight: bold; 
                padding: 4px 8px; 
                background-color: white; 
                border: 2px solid {color}; 
                border-radius: 4px;
                box-shadow: 2px 2px 5px rgba(0,0,0,0.2);
                white-space: nowrap;
            ">
                📌 {point['name']}<br>
                <span style="color: {color};">{status_text}</span>
            </div>
            """
            
# 常時表示するための特殊設定を施したTooltipオブジェクト
            permanent_tooltip = folium.Tooltip(
                tooltip_html,
                permanent=True,
                direction="top",
                offset=(0, -35),  # 👈 ここを追加！吹き出しを上に35ピクセル持ち上げます
                style="background: transparent; border: none; box-shadow: none;"  # 👈 余計な外枠を消すおまじない
            )

            # ピンを地図に追加
            folium.Marker(
                [point['lat'], point['lon']],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=permanent_tooltip,
                icon=folium.Icon(color=color, icon="info-sign")
            ).add_to(m)

        # 地図をStreamlit上に描画
        st_folium(m, width="100%", height=600, returned_objects=[])

    with col2:
        st.subheader("📊 直近60分の交通量推移")
        for code, df_chart in all_charts_data.items():
            st.write(f"📈 **{POINT_MAP[code]}**")
            # Streamlit標準の折れ線グラフで表示
            st.line_chart(df_chart.set_index('Time'))
