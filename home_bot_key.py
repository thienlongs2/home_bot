import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import json
import sqlite3
from fastapi import FastAPI
import asyncio
from datetime import datetime, timedelta
import uvicorn
import logging

logging.basicConfig(
    filename='trading_debug.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    encoding='utf-8'  # Thêm mã hóa UTF-8
)
app = FastAPI()
STATE_FILE = "current_signal.json"

def init_db():
    conn = sqlite3.connect("trading_history.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal TEXT,
            entry_price REAL,
            close_price REAL,
            profit_pip REAL,
            magic_number INTEGER,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.warning('File current_signal trống hoặc lỗi')
        return {"signal": None, "current_price": None, "magic_number": 12345, "timestamp": None}

def save_trade_to_db(signal, entry_price, close_price, profit_pip, magic_number, timestamp):
    conn = sqlite3.connect("trading_history.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (signal, entry_price, close_price, profit_pip, magic_number, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (signal, entry_price, close_price, profit_pip, magic_number, timestamp))
    conn.commit()
    conn.close()

current_signal = load_state()
logging.info(f'Trạng thái lệnh hiện tại: {current_signal}')

if not mt5.initialize():
    logging.error(f"Khởi tạo MT5 thất bại: {mt5.last_error()}")
    mt5.shutdown()
    exit()
logging.info("Đã kết nối với MT5")
mau_tien = "GBPUSD"

def update_signal(signal, current_price=None, magic_number=12345):
    global current_signal
    new_timestamp = datetime.now().isoformat()
    if current_signal["signal"] is not None and current_signal["signal"] != "close" and signal != "close":
        logging.info("Giữ nguyên tín hiệu cũ vì chưa đóng lệnh")
        return
    if signal == "close" and current_signal["signal"] in ["buy", "sell"]:
        entry_price = current_signal["current_price"]
        close_price = current_price
        profit_pip = (close_price - entry_price) * 10000 if current_signal["signal"] == "buy" else (entry_price - close_price) * 10000
        save_trade_to_db(current_signal["signal"], entry_price, close_price, profit_pip, magic_number, new_timestamp)
    current_signal = {"signal": signal, "current_price": current_price, "magic_number": magic_number, "timestamp": new_timestamp}
    save_state(current_signal)
    current_signal = load_state()
    logging.info(f"Cập nhật tín hiệu: {current_signal}")

@app.get("/get_signal")
async def get_signal():
    return current_signal

def tinh_supertrend(df, chu_ky=10, he_so=2.0):
    df['hl2'] = (df['high'] + df['low']) / 2
    df['tr'] = np.maximum.reduce([df['high'] - df['low'], abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))])
    df['atr'] = df['tr'].rolling(window=chu_ky).mean()
    df['bang_tren'] = df['hl2'] - (he_so * df['atr'])
    df['bang_duoi'] = df['hl2'] + (he_so * df['atr'])
    df['bang_tren'] = np.where(df['close'].shift(1) > df['bang_tren'].shift(1), np.maximum(df['bang_tren'], df['bang_tren'].shift(1)), df['bang_tren'])
    df['bang_duoi'] = np.where(df['close'].shift(1) < df['bang_duoi'].shift(1), np.minimum(df['bang_duoi'], df['bang_duoi'].shift(1)), df['bang_duoi'])
    df['xu_huong'] = 1
    for i in range(1, len(df)):
        if df['xu_huong'].iloc[i-1] == -1 and df['close'].iloc[i] > df['bang_duoi'].iloc[i-1]:
            df.loc[df.index[i], 'xu_huong'] = 1
            logging.info(f"Chuyển xu hướng sang 1 tại {df['time'].iloc[i]}, Close={df['close'].iloc[i]}, Bang_duoi={df['bang_duoi'].iloc[i-1]}")
        elif df['xu_huong'].iloc[i-1] == 1 and df['close'].iloc[i] < df['bang_tren'].iloc[i-1]:
            df.loc[df.index[i], 'xu_huong'] = -1
            logging.info(f"Chuyển xu hướng sang -1 tại {df['time'].iloc[i]}, Close={df['close'].iloc[i]}, Bang_tren={df['bang_tren'].iloc[i-1]}")
        else:
            df.loc[df.index[i], 'xu_huong'] = df['xu_huong'].iloc[i-1]
    return df

async def kiem_tra_chien_luoc():
    logging.info("Bắt đầu kiểm tra chiến lược giao dịch...")
    current_state = load_state()
    vi_tri = current_state["signal"] if current_state["signal"] in ["buy", "sell"] else None
    gia_vao = current_state["current_price"] if vi_tri else 0
    magic_number = current_state["magic_number"]

    while True:
        try:
            if not mt5.terminal_info():
                logging.error("Mất kết nối với MT5, đang thử khởi động lại...")
                mt5.shutdown()
                if not mt5.initialize():
                    logging.error(f"Khởi tạo lại MT5 thất bại: {mt5.last_error()}")
                    await asyncio.sleep(10)
                    continue
                logging.info("Đã kết nối lại với MT5")

            end_time = datetime.now()
            start_time = end_time - timedelta(hours=200 * 4)
            du_lieu_h4 = mt5.copy_rates_range(mau_tien, mt5.TIMEFRAME_H4, start_time, end_time)
            du_lieu_m15 = mt5.copy_rates_range(mau_tien, mt5.TIMEFRAME_M15, start_time, end_time)
            if du_lieu_h4 is None or du_lieu_m15 is None or len(du_lieu_h4) == 0:
                logging.error("Không lấy được dữ liệu từ MT5!")
                await asyncio.sleep(5)
                continue

            df_h4 = pd.DataFrame(du_lieu_h4)
            df_m15 = pd.DataFrame(du_lieu_m15)
            df_h4['time'] = pd.to_datetime(df_h4['time'], unit='s')
            df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')

            thoi_gian_nen_cuoi = df_h4['time'].iloc[-1]
            thoi_gian_hien_tai = datetime.now()
            do_tre = (thoi_gian_hien_tai - thoi_gian_nen_cuoi).total_seconds()
            logging.info(f"Thời gian nến cuối H4: {thoi_gian_nen_cuoi}, Độ trễ: {do_tre:.2f} giây")
            if do_tre > 300:
                logging.warning("Dữ liệu H4 bị trễ, có thể ảnh hưởng đến tín hiệu!")

            logging.info("Dữ liệu H4 (5 nến cuối):")
            logging.info(df_h4[['time', 'open', 'high', 'low', 'close']].tail(5).to_string())
            df_h4 = tinh_supertrend(df_h4, chu_ky=10, he_so=2.0)
            logging.info("Supertrend H4 (5 nến cuối):")
            logging.info(df_h4[['time', 'close', 'bang_tren', 'bang_duoi', 'xu_huong']].tail(5).to_string())

            df_m15['time_h4'] = df_m15['time'].dt.floor('4h')
            df_h4.set_index('time', inplace=True)
            df_m15 = df_m15.merge(df_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
            df_m15['xu_huong'] = df_m15['xu_huong'].ffill()
            xu_huong_h4 = df_m15['xu_huong'].iloc[-1]
            logging.info(f"Xu hướng H4 hiện tại: {xu_huong_h4}")

            tick = mt5.symbol_info_tick(mau_tien)
            if tick is None:
                logging.error("Không lấy được tick data từ MT5!")
                await asyncio.sleep(5)
                continue
            gia_hien_tai = (tick.bid + tick.ask) / 2

            if vi_tri == 'buy':
                loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000
                logging.info(f"Buy: {gia_vao:.5f}, Current: {gia_hien_tai:.5f}, TP/SL: {loi_nhuan_pip:.2f} pip")
            elif vi_tri == 'sell':
                loi_nhuan_pip = (gia_vao - gia_hien_tai) * 10000
                logging.info(f"Sell: {gia_vao:.5f}, Current: {gia_hien_tai:.5f}, TP/SL: {loi_nhuan_pip:.2f} pip")
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
            elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 3 or loi_nhuan_pip <= -3):
                update_signal("close", gia_hien_tai, magic_number)
                vi_tri = None
            elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 3 or loi_nhuan_pip <= -3):
                update_signal("close", gia_hien_tai, magic_number)
                vi_tri = None

            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Lỗi trong chiến lược: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(kiem_tra_chien_luoc())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)