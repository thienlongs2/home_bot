import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from fastapi import FastAPI
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

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
current_signal = {"signal": None, "magic_number": 12345, "timestamp": None}

# Tính toán Supertrend
def tinh_supertrend(df, chu_ky=10, he_so=2.0):
    df['hl2'] = (df['high'] + df['low']) / 2
    df['tr'] = np.maximum.reduce([df['high'] - df['low'],
                                  abs(df['high'] - df['close'].shift(1)),
                                  abs(df['low'] - df['close'].shift(1))])
    df['atr'] = df['tr'].rolling(window=chu_ky).mean()
    df['bang_tren'] = df['hl2'] - (he_so * df['atr'])
    df['bang_duoi'] = df['hl2'] + (he_so * df['atr'])
    df['bang_tren'] = np.where(df['close'].shift(1) > df['bang_tren'].shift(1),
                               np.maximum(df['bang_tren'], df['bang_tren'].shift(1)),
                               df['bang_tren'])
    df['bang_duoi'] = np.where(df['close'].shift(1) < df['bang_duoi'].shift(1),
                               np.minimum(df['bang_duoi'], df['bang_duoi'].shift(1)),
                               df['bang_duoi'])
    df['xu_huong'] = 1
    df['xu_huong'] = np.where((df['xu_huong'].shift(1) == -1) & (df['close'] > df['bang_duoi'].shift(1)), 1,
                              np.where((df['xu_huong'].shift(1) == 1) & (df['close'] < df['bang_tren'].shift(1)), -1,
                                       df['xu_huong'].shift(1)))
    return df

# Lấy dữ liệu từ MT5
def lay_du_lieu(khung_thoi_gian, so_nen=100):
    du_lieu = mt5.copy_rates_from_pos(mau_tien, khung_thoi_gian, 0, so_nen)
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close']]
    return df

# Cập nhật tín hiệu
def update_signal(signal, magic_number=12345):
    global current_signal
    current_signal = {
        "signal": signal,
        "magic_number": magic_number,
        "timestamp": datetime.now().isoformat()
    }
    print(f"Cập nhật tín hiệu: {current_signal}")

# Endpoint để client lấy tín hiệu
@app.get("/get_signal")
async def get_signal():
    return current_signal

# Chiến lược giao dịch
async def kiem_tra_chien_luoc():
    vi_tri = None
    gia_vao = 0
    magic_number = 12345

    while True:
        # Lấy dữ liệu H4 và M15
        du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, 100)
        du_lieu_m15 = lay_du_lieu(mt5.TIMEFRAME_M15, 100)
        du_lieu_h4 = tinh_supertrend(du_lieu_h4)
        du_lieu_h4 = tinh_supertrend(du_lieu_h4)
        du_lieu_m15['time_h4'] = du_lieu_m15['time'].dt.floor('4h')
        du_lieu_h4.set_index('time', inplace=True)
        du_lieu_m15 = du_lieu_m15.merge(du_lieu_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
        # du_lieu_m15['xu_huong'].fillna(method='ffill', inplace=True)
        du_lieu_m15.loc[:, 'xu_huong'] = du_lieu_m15['xu_huong'].ffill()

        xu_huong_h4 = du_lieu_m15['xu_huong'].iloc[-1]
        gia_hien_tai = du_lieu_m15['close'].iloc[-1]

        if vi_tri == 'buy':
            loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000
        elif vi_tri == 'sell':
            loi_nhuan_pip = (gia_vao - gia_hien_tai) * 10000
        else:
            loi_nhuan_pip = 0

        # Điều kiện vào lệnh Buy
        if vi_tri is None and xu_huong_h4 == 1:
            vi_tri = 'buy'
            gia_vao = gia_hien_tai
            update_signal("buy", magic_number)

        # Điều kiện vào lệnh Sell
        elif vi_tri is None and xu_huong_h4 == -1:
            vi_tri = 'sell'
            gia_vao = gia_hien_tai
            update_signal("sell", magic_number)

        # Điều kiện đóng lệnh
        elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            update_signal("close", magic_number)
            vi_tri = None

        elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            update_signal("close", magic_number)
            vi_tri = None

        await asyncio.sleep(900)  # Chờ 15 phút

# Sử dụng Lifespan để thay thế on_event
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động chiến lược khi server bắt đầu
    task = asyncio.create_task(kiem_tra_chien_luoc())
    yield
    # Dọn dẹp khi server tắt (nếu cần)
    task.cancel()

# Gán lifespan vào app
app.lifespan = lifespan

# Chạy server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)