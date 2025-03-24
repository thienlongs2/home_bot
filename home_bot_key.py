import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import json
from fastapi import FastAPI, Depends, HTTPException, Query
import asyncio
from datetime import datetime

# Khởi tạo FastAPI
app = FastAPI()

# File lưu trạng thái lệnh
STATE_FILE = "current_signal.json"


# Hàm lưu trạng thái lệnh vào file
def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# Hàm tải trạng thái lệnh từ file
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"signal": None, "current_price": None, "magic_number": 12345, "timestamp": None}


# Biến lưu trạng thái lệnh hiện tại
current_signal = load_state()

# Đảm bảo MT5 khởi tạo thành công
if not mt5.initialize():
    print(f"Khởi tạo MT5 thất bại: {mt5.last_error()}")
    mt5.shutdown()
    exit()
print("Đã kết nối với MT5")
mau_tien = "GBPUSD"


# Hàm cập nhật tín hiệu (chỉ thay đổi khi có tín hiệu close hoặc chưa có tín hiệu nào)
def update_signal(signal, current_price=None, magic_number=12345):
    global current_signal
    new_timestamp = datetime.now().isoformat()

    # Nếu đã có tín hiệu trước đó và chưa có tín hiệu close, giữ nguyên tín hiệu cũ
    if current_signal["signal"] is not None and current_signal["signal"] != "close" and signal != "close":
        return

    current_signal = {
        "signal": signal,
        "current_price": current_price,
        "magic_number": magic_number,
        "timestamp": new_timestamp
    }
    save_state(current_signal)
    print(f"Cập nhật tín hiệu: {current_signal}")


# Endpoint lấy tín hiệu
@app.get("/get_signal")
async def get_signal():
    return current_signal


# Hàm kiểm tra chiến lược giao dịch
async def kiem_tra_chien_luoc():
    print("Bắt đầu kiểm tra chiến lược giao dịch...")
    vi_tri = None
    gia_vao = 0
    magic_number = 12345

    while True:
        try:
            du_lieu_h4 = mt5.copy_rates_from_pos(mau_tien, mt5.TIMEFRAME_H4, 0, 100)
            du_lieu_m15 = mt5.copy_rates_from_pos(mau_tien, mt5.TIMEFRAME_M15, 0, 100)
            if du_lieu_h4 is None or du_lieu_m15 is None:
                print("Lỗi: Không lấy được dữ liệu từ MT5!")
                await asyncio.sleep(60)
                continue

            df_h4 = pd.DataFrame(du_lieu_h4)
            df_m15 = pd.DataFrame(du_lieu_m15)
            df_h4['time'] = pd.to_datetime(df_h4['time'], unit='s')
            df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
            df_h4['hl2'] = (df_h4['high'] + df_h4['low']) / 2
            df_h4['tr'] = np.maximum.reduce([df_h4['high'] - df_h4['low'],
                                             abs(df_h4['high'] - df_h4['close'].shift(1)),
                                             abs(df_h4['low'] - df_h4['close'].shift(1))])
            df_h4['atr'] = df_h4['tr'].rolling(window=10).mean()
            df_h4['bang_duoi'] = df_h4['hl2'] + (2.0 * df_h4['atr'])
            df_h4['xu_huong'] = np.where(df_h4['close'] > df_h4['bang_duoi'], 1, -1)
            df_m15['time_h4'] = df_m15['time'].dt.floor('4h')
            df_h4.set_index('time', inplace=True)
            df_m15 = df_m15.merge(df_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
            df_m15['xu_huong'] = df_m15['xu_huong'].ffill()

            xu_huong_h4 = df_m15['xu_huong'].iloc[-1]
            gia_hien_tai = df_m15['close'].iloc[-1]

            if vi_tri == 'buy':
                loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000
            elif vi_tri == 'sell':
                loi_nhuan_pip = (gia_vao - gia_hien_tai) * 10000
            else:
                loi_nhuan_pip = 0

            if vi_tri is None and xu_huong_h4 == 1:
                vi_tri = 'buy'
                gia_vao = gia_hien_tai
                update_signal("buy", gia_hien_tai, magic_number)
            elif vi_tri is None and xu_huong_h4 == -1:
                vi_tri = 'sell'
                gia_vao = gia_hien_tai
                update_signal("sell", gia_hien_tai, magic_number)
            elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
                update_signal("close", gia_hien_tai, magic_number)
                vi_tri = None
            elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
                update_signal("close", gia_hien_tai, magic_number)
                vi_tri = None

            await asyncio.sleep(90)
        except Exception as e:
            print(f"Lỗi trong chiến lược: {e}")
            await asyncio.sleep(60)


# Lifespan FastAPI
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(kiem_tra_chien_luoc())


# Chạy server FastAPI
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
