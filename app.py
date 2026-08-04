import streamlit as st
import streamlit.components.v1 as components
import requests
import datetime
import pytz
import folium
from streamlit_folium import st_folium
import pandas as pd

# 画面を横いっぱいに広く使う設定
# 画面を横いっぱいに広く使う設定
st.set_page_config(layout="wide", page_title="2026年赤川花火 リアルタイム渋滞情報マップ")

# 5分（300,000ミリ秒）ごとにブラウザを自動リロードする魔法のコード 🧙‍♂️
components.html("""
    <script>
        setTimeout(function(){
            window.location.reload();
        }, 300000);
    </script>
""", height=0)

st.title("🚗 2026年赤川花火 リアルタイム渋滞情報マップ【試験中】")
st.caption("※サイトを開いた（またはリロードした）瞬間の最新データをJARTIC APIから取得して表示します。")
st.write("赤川花火大会当日の国道112号・国道47号等の混雑をリアルタイムで確認できる渋滞状況予測・モニターマップです。")

# --- 設定項目 ---
POINT_MAP = {
    "2110491": "国道112号 湯殿山IC",
    "2110488": "国道112号 月山湖",
    "2110440": "国道47号 立川町",
    "2110437": "国道47号 戸沢古口",
    "2110194": "国道7号 小波渡",
    "2110193": "国道7号 青山南",
    "4110030": "国道7号 府屋"
}
OBSERVATION_POINT_CODES = list(POINT_MAP.keys())
API_URL = "https://api.jartic-open-traffic.org/geoserver"

def get_congestion_status(u_pcu, d_pcu):
    max_pcu = max(u_pcu, d_pcu)
    if max_pcu >= 60:
        return "🚨 渋滞しています", "red"
    elif max_pcu >= 40:
        return "⚠️ 渋滞の予兆があります", "orange"
    else:
        return "🟢 渋滞は発生していません", "green"

# 【超高速化の肝】引数を時間コード（文字列）にすることで、キャッシュの的中率を100%にします
@st.cache_data(ttl=300)
def fetch_point_data_by_code(observation_code, time_code, display_time_str):
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
        response = requests.get(API_URL, params=params, timeout=3) # タイムアウトを3秒に短縮して詰まりを防止
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
                "display_time": display_time_str,
                "lat": lat,
                "lon": lon,
                "u_pcu": u_pcu,
                "d_pcu": d_pcu,
                "timestamp": f"{time_code[:4]}-{time_code[4:6]}-{time_code[6:8]} {time_code[8:10]}:{time_code[10:12]}"
            }
    except:
        pass
    return None

# --- 時間の固定化処理 ---
jst = pytz.timezone('Asia/Tokyo')
now_jst = datetime.datetime.now(jst)

# 現在時刻を「直近の5分刻みのキリの良い時間」に強制的に切り捨てます（例: 13:03 ➔ 13:00）
base_time = now_jst.replace(minute=(now_jst.minute // 5) * 5, second=0, microsecond=0)

data_points = []
all_charts_data = {}

with st.spinner("JARTICから最新の交通データを高速解析中..."):
    for code in OBSERVATION_POINT_CODES:
        chart_data = []
        latest_info = None

        # 固定されたbase_timeから過去13回分の時間コードのリストを一発で作る
        for i in range(12, -1, -1):
            target_time = base_time - datetime.timedelta(minutes=25 + (i * 5))
            time_code = target_time.strftime("%Y%m%d%H%M")
            display_time_str = target_time.strftime("%H:%M")
            
            # キャッシュが確実にヒットする関数を呼び出し
            res = fetch_point_data_by_code(code, time_code, display_time_str)
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
    st.error("現在、JARTIC APIの混雑、またはデータ更新時間帯のため一時的にデータを取得できません。リロードをお試しください。")
else:
    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("📍 現在の混雑マップ")
        avg_lat = sum(p['lat'] for p in data_points) / len(data_points)
        avg_lon = sum(p['lon'] for p in data_points) / len(data_points)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=10) # 地点が増えたので少し広域(10)にズームアウト

        for point in data_points:
            status_text, color = get_congestion_status(point['u_pcu'], point['d_pcu'])

            popup_html = f"""
            <div style="font-size: 14px; width: 220px;">
                <h4 style="margin: 0 0 5px 0; color: #333;">{point['name']}</h4>
                <p style="margin: 0 0 10px 0; font-size: 11px; color: #666;">（コード: {point['code']} / 更新: {point['timestamp']}）</p>
                <hr style="margin: 5px 0; border: 0; border-top: 1px solid #ccc;">
                <p style="margin: 5px 0;"><b>上り交通量:</b> {point['u_pcu']:.1f} pcu/5m</p>
                <p style="margin: 5px 0;"><b>下り交通量:</b> {point['d_pcu']:.1f} pcu/5m</p>
            </div>
            """
            
            folium.Marker(
                [point['lat'], point['lon']],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.DivIcon(
                    icon_size=(160, 48),
                    icon_anchor=(80, 24),
                    html=f"""
                    <div style="
                        font-size: 11px; 
                        font-weight: bold; 
                        padding: 5px; 
                        background-color: rgba(255, 255, 255, 0.95); 
                        border: 2px solid {color}; 
                        border-radius: 4px;
                        box-shadow: 2px 2px 5px rgba(0,0,0,0.2);
                        text-align: center;
                        width: 160px;
                        cursor: pointer;
                        line-height: 1.3;
                    ">
                        📌 {point['name']}<br>
                        <span style="color: {color}; font-size: 10px;">{status_text}</span>
                    </div>
                    """
                )
            ).add_to(m)

        st_folium(m, width="100%", height=600, returned_objects=[])

    with col2:
        st.subheader("📊 直近60分の交通量推移")
        for code, df_chart in all_charts_data.items():
            st.write(f"📈 **{POINT_MAP[code]}**")
            st.line_chart(df_chart.set_index('Time'))
