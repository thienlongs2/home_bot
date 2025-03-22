import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header
import uvicorn
import time
import threading

# Khởi tạo kết nối MT5
if not mt5.initialize():
    print("Khởi tạo thất bại")
    mt5.shutdown()
    exit()
print("Đã kết nối với MT5")

mau_tien = "GBPUSD"
MAGIC_NUMBER = 123456

file_path=r"C:\\Users\\DELL\\OneDrive\\Máy tính\\fw_tele\\test_botfx\\secret_keys.txt"
def load_secret_keys(file_path):
    try:
        with open(file_path, "r") as f:
            keys = [line.strip() for line in f if line.strip()]
        print(f"Đã tải {len(keys)} SecretKey từ {file_path}")
        return keys
    except Exception as e:
        print(f"Lỗi khi đọc file: {e}")
        return []


ALLOWED_SECRET_KEYS = load_secret_keys("secret_keys.txt")
authenticated_clients = {}
app = FastAPI()


def tinh_supertrend(df, chu_ky=10, he_so=2.0):
    df['hl2'] = (df['high'] + df['low']) / 2
    df['tr'] = np.maximum.reduce([
        df['high'] - df['low'],
        abs(df['high'] - df['close'].shift(1)),
        abs(df['low'] - df['close'].shift(1))
    ])
    df['atr'] = df['tr'].rolling(window=chu_ky).mean()
    df['bang_tren'] = df['hl2'] - (he_so * df['atr'])
    df['bang_duoi'] = df['hl2'] + (he_so * df['atr'])
    df['xu_huong'] = np.where(df['close'] > df['bang_duoi'], 1, -1)
    return df


def lay_du_lieu(khung_thoi_gian, so_nen=100):
    du_lieu = mt5.copy_rates_from_pos(mau_tien, khung_thoi_gian, 0, so_nen)
    if du_lieu is None:
        return pd.DataFrame()
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df[['time', 'open', 'high', 'low', 'close']]


def is_weekend():
    now = datetime.utcnow()
    return now.weekday() in [5, 6] or (now.weekday() == 4 and now.hour >= 22)


last_time_m15 = None
vi_tri = None
gia_vao = 0


def generate_signal():
    global last_time_m15, vi_tri, gia_vao
    while True:
        try:
            du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, 100)
            du_lieu_m15 = lay_du_lieu(mt5.TIMEFRAME_M15, 100)
            if du_lieu_m15.empty or du_lieu_h4.empty:
                time.sleep(10)
                continue

            current_time_m15 = du_lieu_m15['time'].iloc[-1]
            if last_time_m15 == current_time_m15:
                time.sleep(10)
                continue
            last_time_m15 = current_time_m15

            du_lieu_h4 = tinh_supertrend(du_lieu_h4)
            du_lieu_m15['time_h4'] = du_lieu_m15['time'].dt.floor('4h')
            du_lieu_h4.set_index('time', inplace=True)
            du_lieu_m15 = du_lieu_m15.merge(du_lieu_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
            du_lieu_m15['xu_huong'].fillna(method='ffill', inplace=True)

            xu_huong_h4 = du_lieu_m15['xu_huong'].iloc[-1]
            gia_hien_tai = du_lieu_m15['close'].iloc[-1]
            khoi_luong = 0.05
            signal = None

            if vi_tri == 'buy' and (xu_huong_h4 == -1 or (gia_hien_tai - gia_vao) * 10000 >= 120 or (
                    gia_hien_tai - gia_vao) * 10000 <= -70):
                signal = f"CLOSE_BUY,{MAGIC_NUMBER}"
                vi_tri, gia_vao = None, 0
            elif vi_tri == 'sell' and (xu_huong_h4 == 1 or (gia_vao - gia_hien_tai) * 10000 >= 120 or (
                    gia_vao - gia_hien_tai) * 10000 <= -70):
                signal = f"CLOSE_SELL,{MAGIC_NUMBER}"
                vi_tri, gia_vao = None, 0

            if vi_tri is None and not is_weekend():
                if xu_huong_h4 == 1:
                    signal = f"BUY,{gia_hien_tai},{khoi_luong},{MAGIC_NUMBER}"
                    vi_tri, gia_vao = 'buy', gia_hien_tai
                elif xu_huong_h4 == -1:
                    signal = f"SELL,{gia_hien_tai},{khoi_luong},{MAGIC_NUMBER}"
                    vi_tri, gia_vao = 'sell', gia_hien_tai

            if signal:
                print(f"{datetime.now()} - Tín hiệu: {signal}")
            time.sleep(10)
        except Exception as e:
            print(f"Lỗi: {e}")
            time.sleep(10)


@app.get("/authenticate")
async def authenticate(client_id: str, secret_key: str = Header(...)):
    if secret_key not in ALLOWED_SECRET_KEYS:
        raise HTTPException(status_code=401, detail="SecretKey không hợp lệ")
    authenticated_clients[client_id] = secret_key
    return {"status": "AUTH_OK", "client_id": client_id}


@app.get("/signal")
async def get_signal(client_id: str, secret_key: str = Header(...)):
    if client_id not in authenticated_clients or authenticated_clients[client_id] != secret_key:
        raise HTTPException(status_code=401, detail="Chưa xác thực hoặc SecretKey không đúng")
    return {"signal": f"{vi_tri.upper()},{gia_vao},0.05,{MAGIC_NUMBER}" if vi_tri else None}


if __name__ == "__main__":
    signal_thread = threading.Thread(target=generate_signal, daemon=True)
    signal_thread.start()
    uvicorn.run(app, host="127.0.0.1", port=8000)