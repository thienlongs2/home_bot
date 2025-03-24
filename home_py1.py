import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from fastapi import FastAPI
import asyncio
from datetime import datetime

# Khởi tạo FastAPI
app = FastAPI()

# Khởi tạo MT5
if not mt5.initialize():
    print("Khởi tạo thất bại")
    mt5.shutdown()
    exit()
print("Đã kết nối với MT5")
mau_tien = "GBPUSD"

# Biến lưu trữ tín hiệu hiện tại
current_signal = {"signal": None, "current_price": None, "magic_number": 12345, "timestamp": None}


# Hàm tính toán Supertrend
def tinh_supertrend(df, chu_ky=10, he_so=2.0):
    df['hl2'] = (df['high'] + df['low']) / 2
    df['tr'] = np.maximum.reduce([df['high'] - df['low'],
                                  abs(df['high'] - df['close'].shift(1)),
                                  abs(df['low'] - df['close'].shift(1))])
    df['atr'] = df['tr'].rolling(window=chu_ky).mean()
    df['bang_tren'] = df['hl2'] - (he_so * df['atr'])
    df['bang_duoi'] = df['hl2'] + (he_so * df['atr'])
    df['xu_huong'] = np.where(df['close'] > df['bang_duoi'], 1, -1)
    return df


# Hàm lấy dữ liệu từ MT5
def lay_du_lieu(khung_thoi_gian, so_nen=100):
    du_lieu = mt5.copy_rates_from_pos(mau_tien, khung_thoi_gian, 0, so_nen)
    if du_lieu is None:
        print(f"Lỗi: Không lấy được dữ liệu {mau_tien} - Khung {khung_thoi_gian}")
        return pd.DataFrame()
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df[['time', 'open', 'high', 'low', 'close']]


# Cập nhật tín hiệu
def update_signal(signal, current_price=None, magic_number=12345):
    global current_signal
    print(f"DEBUG: Gửi tín hiệu mới - {signal} | Giá: {current_price} | Magic: {magic_number}")
    current_signal = {
        "signal": signal,
        "current_price": current_price,
        "magic_number": magic_number,
        "timestamp": datetime.now().isoformat()
    }
    print(f"Cập nhật tín hiệu: {current_signal}")


# Endpoint để lấy tín hiệu
@app.get("/get_signal")
async def get_signal():
    return current_signal


# Chiến lược giao dịch
async def kiem_tra_chien_luoc():
    print("Hàm kiem_tra_chien_luoc() đã bắt đầu chạy...")
    vi_tri = None
    gia_vao = 0
    magic_number = 12345

    while True:
        try:
            print("Đang kiểm tra chiến lược giao dịch...")

            # Lấy dữ liệu H4 và M15
            du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, 100)
            du_lieu_m15 = lay_du_lieu(mt5.TIMEFRAME_M15, 100)
            if du_lieu_h4.empty or du_lieu_m15.empty:
                print("Lỗi: Không lấy được dữ liệu từ MT5!")
                await asyncio.sleep(60)
                continue

                # Tính toán Supertrend
            du_lieu_h4 = tinh_supertrend(du_lieu_h4)
            du_lieu_m15['time_h4'] = du_lieu_m15['time'].dt.floor('4h')
            du_lieu_h4.set_index('time', inplace=True)
            du_lieu_m15 = du_lieu_m15.merge(du_lieu_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
            # du_lieu_m15['xu_huong'].fillna(method='ffill', inplace=True)
            du_lieu_m15['xu_huong'] = du_lieu_m15['xu_huong'].ffill()

            xu_huong_h4 = du_lieu_m15['xu_huong'].iloc[-1]
            gia_hien_tai = du_lieu_m15['close'].iloc[-1]

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

            elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 12 or loi_nhuan_pip <= -7):
                update_signal("close", gia_hien_tai, magic_number)
                vi_tri = None

            elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 12 or loi_nhuan_pip <= -7):
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
