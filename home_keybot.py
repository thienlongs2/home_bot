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
import pytz

# Cấu hình logging
logging.basicConfig(
    filename='trading_debug.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    encoding='utf-8'
)

app = FastAPI()
STATE_FILE = "current_signal.json"
SYMBOL = "EURUSD"

# Khởi tạo kết nối MT5
if not mt5.initialize():
    logging.error(f"Khởi tạo MT5 thất bại: {mt5.last_error()}")
    mt5.shutdown()
    exit()

# Khởi tạo cơ sở dữ liệu
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

# Lưu và tải trạng thái tín hiệu
def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"signal": None, "current_price": None, "magic_number": 12345, "timestamp": None}

# Lưu giao dịch vào cơ sở dữ liệu
def save_trade_to_db(signal, entry_price, close_price, profit_pip, magic_number, timestamp):
    conn = sqlite3.connect("trading_history.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (signal, entry_price, close_price, profit_pip, magic_number, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (signal, entry_price, close_price, profit_pip, magic_number, timestamp))
    conn.commit()
    conn.close()

# Cập nhật tín hiệu
current_signal = load_state()

def update_signal(signal, current_price=None, magic_number=12345):
    global current_signal
    new_timestamp = datetime.now(pytz.UTC).isoformat()
    if current_signal["signal"] is not None and current_signal["signal"] != "close" and signal != "close":
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

# API lấy tín hiệu
@app.get("/get_signal")
async def get_signal():
    return current_signal


def tinh_supertrend(df, chu_ky=10, he_so=2.0):
    if len(df) < chu_ky:
        logging.error(f"Dữ liệu không đủ {chu_ky} nến để tính Supertrend! Số nến: {len(df)}")
        return None

    df = df.copy()  # Đảm bảo không làm thay đổi df gốc
    df['hl2'] = (df['high'] + df['low']) / 2
    
    df['tr'] = np.maximum.reduce([
        df['high'] - df['low'], 
        abs(df['high'] - df['close'].shift(1).fillna(0)),  
        abs(df['low'] - df['close'].shift(1).fillna(0))
    ])
    
    # Sử dụng ffill() thay vì fillna(method='ffill')
    df['atr'] = df['tr'].rolling(window=chu_ky).mean().ffill()

    # Tính toán dải trên và dải dưới cơ bản
    df['bang_tren'] = df['hl2'] - (he_so * df['atr'])
    df['bang_duoi'] = df['hl2'] + (he_so * df['atr'])

    # Điều chỉnh dải theo quy tắc của Supertrend
    df['bang_tren'] = np.where(df['close'].shift(1) > df['bang_tren'].shift(1), 
                               np.maximum(df['bang_tren'], df['bang_tren'].shift(1)), 
                               df['bang_tren'])
    df['bang_duoi'] = np.where(df['close'].shift(1) < df['bang_duoi'].shift(1), 
                               np.minimum(df['bang_duoi'], df['bang_duoi'].shift(1)), 
                               df['bang_duoi'])
    
    # Khởi tạo xu hướng ban đầu
    df['xu_huong'] = np.nan
    df.loc[df.index[0], 'xu_huong'] = 1  # Giả định ban đầu là xu hướng tăng
    # Khởi tạo Supertrend ban đầu dựa trên xu hướng tăng: dùng dải dưới
    df['supertrend'] = df['bang_duoi']
    
    # Cập nhật xu hướng theo giá hiện tại so với dải (dùng giá hiện tại của dải)
   
    for i in range(1, len(df)):
        prev_trend = df.loc[df.index[i-1], 'xu_huong']
        
        if prev_trend == 1 and df.loc[df.index[i], 'close'] < df.loc[df.index[i-1], 'supertrend']:
            df.loc[df.index[i], 'xu_huong'] = -1
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i], 'bang_tren']  # Chuyển sang dải trên
        elif prev_trend == -1 and df.loc[df.index[i], 'close'] > df.loc[df.index[i-1], 'supertrend']:
            df.loc[df.index[i], 'xu_huong'] = 1
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i], 'bang_duoi']  # Chuyển sang dải dưới
        else:
            df.loc[df.index[i], 'xu_huong'] = prev_trend
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i-1], 'supertrend']

    
    # Gán Supertrend dựa trên xu hướng hiện tại:
    # Nếu xu hướng tăng => Supertrend = dải dưới, nếu giảm => Supertrend = dải trên
    df['supertrend'] = np.where(df['xu_huong'] == 1, df['bang_duoi'], df['bang_tren'])

    return df




# Lấy dữ liệu H4 và M15
def get_data(timeframe, symbol, num_bars=100):
    if not mt5.symbol_select(symbol, True):
        logging.error(f"Không thể chọn {symbol} để đồng bộ dữ liệu!")
        return None

    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars)
    if rates is None or len(rates) == 0:
        logging.error(f"Không lấy được dữ liệu từ MT5!")
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

    last_candle_time = df['time'].iloc[-1]
    thoi_gian_hien_tai = datetime.now(pytz.UTC)
    time_diff = (thoi_gian_hien_tai - last_candle_time).total_seconds()
    if timeframe == mt5.TIMEFRAME_H4 and time_diff > 4 * 3600 + 300:
        logging.warning(f"Dữ liệu H4 không cập nhật! Nến cuối: {last_candle_time}")
        end_time = thoi_gian_hien_tai
        start_time = end_time - timedelta(hours=num_bars * 4)
        rates = mt5.copy_rates_range(symbol, timeframe, start_time, end_time)
        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

    return df

# Kiểm tra chiến lược
async def kiem_tra_chien_luoc():
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

            df_h4 = get_data(mt5.TIMEFRAME_H4, SYMBOL, 100)
            df_m15 = get_data(mt5.TIMEFRAME_M15, SYMBOL, 100)
            if df_h4 is None or df_m15 is None:
                await asyncio.sleep(5)
                continue

            df_h4 = tinh_supertrend(df_h4, chu_ky=10, he_so=2.0)
            if df_h4 is None:
                logging.error("Không tính được Supertrend cho H4!")
                await asyncio.sleep(5)
                continue

            df_m15['time_h4'] = df_m15['time'].dt.floor('4h')
            df_h4.set_index('time', inplace=True)
            df_m15 = df_m15.merge(df_h4[['xu_huong', 'supertrend']], left_on='time_h4', right_index=True, how='left')
            df_m15['xu_huong'] = df_m15['xu_huong'].ffill()
            df_m15['supertrend'] = df_m15['supertrend'].ffill()
            xu_huong_h4 = df_m15['xu_huong'].iloc[-1]
            supertrend_h4 = df_m15['supertrend'].iloc[-1]

            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                logging.error("Không lấy được tick data từ MT5!")
                await asyncio.sleep(5)
                continue
            gia_hien_tai = (tick.bid + tick.ask) / 2

            # Log để kiểm tra
            logging.info(f"Close: {df_h4['close'].iloc[-1]}, Supertrend: {supertrend_h4}, Xu huong: {xu_huong_h4}, Gia hien tai: {gia_hien_tai}")

            if vi_tri == 'buy':
                loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000
                if xu_huong_h4 == -1 or gia_hien_tai < supertrend_h4 or loi_nhuan_pip >= 3 or loi_nhuan_pip <= -3:
                    update_signal("close", gia_hien_tai, magic_number)
                    vi_tri = None
            elif vi_tri == 'sell':
                loi_nhuan_pip = (gia_vao - gia_hien_tai) * 10000
                if xu_huong_h4 == 1 or gia_hien_tai > supertrend_h4 or loi_nhuan_pip >= 3 or loi_nhuan_pip <= -3:
                    update_signal("close", gia_hien_tai, magic_number)
                    vi_tri = None
            elif vi_tri is None:
                if xu_huong_h4 == 1 and gia_hien_tai > supertrend_h4:
                    vi_tri = 'buy'
                    gia_vao = gia_hien_tai
                    update_signal("buy", gia_hien_tai, magic_number)
                elif xu_huong_h4 == -1 and gia_hien_tai < supertrend_h4:
                    vi_tri = 'sell'
                    gia_vao = gia_hien_tai
                    update_signal("sell", gia_hien_tai, magic_number)

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