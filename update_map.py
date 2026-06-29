import requests
import datetime
import pytz
import folium
import matplotlib.pyplot as plt
import pandas as pd
import os

# --- 設定項目 ---
OBSERVATION_POINT_CODES = ["2110491", "2110488"]
API_URL = "https://api.jartic-open-traffic.org/geoserver"
PCU_THRESHOLD = 30

def fetch_point_data(observation_code, target_time):
    """指定された時間のデータをJARTIC APIから取得する"""
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

            # PCU計算
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
    except Exception as e:
        print(f"データ取得エラー ({observation_code}, {time_code}): {e}")
    return None

def main():
    jst = pytz.timezone('Asia/Tokyo')
    now_jst = datetime.datetime.now(jst)

    data_points = []
    
    # グラフ用フォルダの作成
    os.makedirs("charts", exist_ok=True)

    for code in OBSERVATION_POINT_CODES:
        chart_data = []
        latest_info = None

        # 過去60分（5分刻み×12回分）のデータを遡って取得
        print(f"地点 {code} のデータを取得中...")
        for i in range(12, -1, -1):
            # 25分前を基準に、さらに過去へ遡る
            target_time = now_jst - datetime.timedelta(minutes=25 + (i * 5))
            res = fetch_point_data(code, target_time)
            
            if res:
                chart_data.append({
                    'Time': res['display_time'],
                    'Upstream PCU': res['u_pcu'],
                    'Downstream PCU': res['d_pcu']
                })
                # 一番最後のループ（最新のデータ）をマップ表示用にする
                latest_info = res

        if not latest_info:
            print(f"地点 {code} の直近データが取得できませんでした。")
            continue

        # 1. グラフの生成と保存
        if chart_data:
            df_chart = pd.DataFrame(chart_data)
            fig, ax = plt.subplots(figsize=(10, 4))
            df_chart.plot(x='Time', y=['Upstream PCU', 'Downstream PCU'], kind='bar', ax=ax, rot=45)
            ax.set_title(f'Observation Point {code} - 60min PCU Trends')
            ax.set_ylabel('PCU (pcu/5m)')
            ax.set_xlabel('Time')
            
            # 値のパディング（数字がはみ出ないように）
            for container in ax.containers:
                for i, v in enumerate(container.get_children()):
                    ax.annotate(f"{df_chart[container.get_label()].iloc[i]:.1f}",
                                xy=(v.get_x() + v.get_width() / 2, v.get_height()),
                                xytext=(0, 3), textcoords="offset points",
                                ha='center', va='bottom', fontsize=7)
            
            plt.tight_layout()
            # 各地点ごとのグラフを画像として保存
            plt.savefig(f"charts/chart_{code}.png")
            plt.close()

        # マッププロット用リストに追加
        latest_info['code'] = code
        data_points.append(latest_info)

    if not data_points:
        print("表示可能なデータがありません。処理を終了します。")
        return

    # 2. Foliumマップの生成
    avg_lat = sum(p['lat'] for p in data_points) / len(data_points)
    avg_lon = sum(p['lon'] for p in data_points) / len(data_points)
    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=13)

    for point in data_points:
        # HTMLポップアップ内に生成したグラフ画像を埋め込む
        popup_html = f"""
        <h4>地点コード: {point['code']}</h4>
        <p>更新時刻: {point['timestamp']}</p>
        <p><b>上り:</b> {point['u_pcu']:.1f} pcu/5m<br><b>下り:</b> {point['d_pcu']:.1f} pcu/5m</p>
        <img src="charts/chart_{point['code']}.png" width="400">
        """
        
        # 閾値を超えていたらピンの色を赤にする
        is_congested = point['u_pcu'] >= PCU_THRESHOLD or point['d_pcu'] >= PCU_THRESHOLD
        color = 'red' if is_congested else 'blue'

        folium.Marker(
            [point['lat'], point['lon']],
            popup=folium.Popup(popup_html, max_width=450),
            tooltip=f"地点 {point['code']} (上り:{point['u_pcu']:.1f} / 下り:{point['d_pcu']:.1f})",
            icon=folium.Icon(color=color, icon="info-sign")
        ).add_to(m)

    # 最後に index.html として出力
    m.save("index.html")
    print("index.html とグラフの生成が完了しました。")

if __name__ == "__main__":
    main()
