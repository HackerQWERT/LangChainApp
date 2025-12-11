import os
import sys
import json
from datetime import datetime, timedelta

# 确保能导入 app.tools.flight
# 假设此脚本在项目根目录，app 文件夹也在根目录
sys.path.append(os.getcwd())

try:
    # 额外导入 GoogleSearch 以便测试原生高级功能
    from serpapi import GoogleSearch
    from app.infras.func import lookup_airport_code, search_flights
except ImportError:
    print("❌ 错误：无法导入 flight 模块或 serpapi。请确保安装了 google-search-results 且路径正确。")
    exit(1)


def run_test():
    # ==========================================
    # ⚠️ 请在这里填入你的 SerpApi Key 用于测试
    # 或者设置环境变量 export SERPAPI_API_KEY="你的key"
    # ==========================================
    api_key = os.getenv("SERPAPI_API_KEY") or "你的_SERPAPI_KEY_粘贴在这里"

    # 临时设置环境变量供 tool 使用
    os.environ["SERPAPI_API_KEY"] = api_key

    if api_key == "你的_SERPAPI_KEY_粘贴在这里":
        print("⚠️ 警告：你还没有设置 API Key，请求可能会失败。")
        print("请在脚本中填入 Key 或设置环境变量 SERPAPI_API_KEY")
        print("-" * 50)

    print("🚀 开始手动测试航班工具...\n")

    # ==========================================
    # 1. 测试查询机场代码
    # ==========================================
    city = "Beijing"
    print(f"1️⃣ Testing lookup_airport_code('{city}')...")
    origin_code = lookup_airport_code.invoke(city)
    print(f"👉 Result: {origin_code}\n")

    destination_city = "Tokyo"
    print(f"Testing lookup_airport_code('{destination_city}')...")
    dest_code = lookup_airport_code.invoke(destination_city)
    print(f"👉 Result: {dest_code}\n")

    if "not found" in origin_code or "not found" in dest_code:
        print("❌ 机场代码获取失败，停止后续测试。")
    else:
        # ==========================================
        # 2. 测试普通单程查询 (Existing Tool)
        # ==========================================
        future_date = (datetime.now() + timedelta(days=30)
                       ).strftime("%Y-%m-%d")

        print(
            f"2️⃣ Testing search_flights('{origin_code}', '{dest_code}', '{future_date}')...")
        print("⏳ 请求 Google Flights 数据中 (可能需要几秒钟)...")

        try:
            # 调用工具
            flight_data_json = search_flights.invoke({
                "origin": origin_code,
                "destination": dest_code,
                "date": future_date
            })

            # 尝试解析 JSON 以便漂亮打印
            parsed = json.loads(flight_data_json)
            print("\n✅ [单程] 成功获取数据 (前1条示例)：")
            print(json.dumps(parsed[:1], indent=2,
                  ensure_ascii=False))  # 只打印第一条省空间
        except Exception as e:
            print(f"\n❌ 单程测试错误: {e}")

    # ==========================================
    # 3. 测试高级多城市搜索 (基于您的参考代码)
    # ==========================================
    print("\n3️⃣ Testing Multi-City Search (Raw SerpApi Call)...")
    print("⏳ 正在请求多程航班 (CDG -> NRT -> LAX -> AUS)...")

    # 构造 multi_city_json 对象
    # 注意：这里使用 Python 列表，然后 dumps 成字符串，比手动拼字符串更安全
    multi_city_itinerary = [
        {
            "departure_id": "CDG",
            "arrival_id": "NRT",
            "date": "2025-12-12"
        },
        {
            "departure_id": "NRT",
            "arrival_id": "LAX,SEA",  # 支持多个目的地筛选
            "date": "2025-12-18"
        },
        {
            "departure_id": "LAX,SEA",
            "arrival_id": "AUS",
            "date": "2025-12-26",
            "times": "8,18,9,23"  # 指定时间段
        }
    ]

    params = {
        "engine": "google_flights",
        "multi_city_json": json.dumps(multi_city_itinerary),
        "type": "3",  # 3 代表 Multi-city
        "currency": "USD",
        "hl": "en",
        "api_key": api_key
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        # 打印多程搜索结果中的最佳航班
        best_flights = results.get("best_flights", [])
        if best_flights:
            print(f"\n✅ [多程] 成功获取 {len(best_flights)} 条联程方案！")
            # 打印第一条方案的概要
            first_option = best_flights[0]
            print(f"💰 总价: {first_option.get('price')}")
            print(f"⏱️ 总时长: {first_option.get('total_duration')} min")
            print("✈️ 航段详情:")
            for flight in first_option.get("flights", []):
                dep = flight.get("departure_airport", {})
                arr = flight.get("arrival_airport", {})
                print(
                    f"   - {flight.get('airline')} ({flight.get('flight_number')}): {dep.get('id')} -> {arr.get('id')}")
        else:
            print("\n⚠️ API 返回成功，但没有找到符合条件的最佳航班 (best_flights 为空)。")
            # 有时可能在 other_flights 里
            print(
                f"Other flights count: {len(results.get('other_flights', []))}")

    except Exception as e:
        print(f"\n❌ 多程测试错误: {e}")


if __name__ == "__main__":
    run_test()
