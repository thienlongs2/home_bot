import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import json
import asyncio
from datetime import datetime
import uvicorn
from fastapi import FastAPI, HTTPException
import logging
import pandas_ta as ta
from typing import Optional, Dict

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Trading Signal System")

# Biến toàn cục
current_signal: Dict = {
    "signal": "none",
    "gia_hien_tai": None,
    "magic_number": 12345,
    "timestamp": datetime.now().isoformat()
}
# SYMBOL = "GBPUSD"
SYMBOL = "AUDUSD"


# Khởi tạo MT5
def initialize_mt5():
    if not mt5.initialize():
        logger.error(f"Khởi tạo MT5 thất bại: {mt5.last_error()}")
        mt5.shutdown()
        raise Exception("Không thể kết nối MT5")
    logger.info("Đã kết nối với MT5")


# Cập nhật tín hiệu
def update_signal(signal: str, gia_hien_tai: Optional[float] = None, magic_number: int = 12345):
    global current_signal
    current_signal = {
        "signal": signal,
        "gia_hien_tai": gia_hien_tai,
        "magic_number": magic_number,
        "timestamp": datetime.now().isoformat()
    }
    logger.info(f"Cập nhật tín hiệu: {current_signal}")


# Lấy dữ liệu từ MT5
def get_data(timeframe: int, bars: int = 150) -> pd.DataFrame:
    try:
        rates = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, bars)
        if rates is None:
            raise ValueError("Không thể lấy dữ liệu")
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df[['time', 'open', 'high', 'low', 'close']]
    except Exception as e:
        logger.error(f"Lỗi khi lấy dữ liệu: {str(e)}")
        return pd.DataFrame()


# API endpoint để lấy tín hiệu
@app.get("/get_signal")
async def get_current_signal():
    return current_signal


# Logic chiến lược giao dịch
async def trading_strategy():
    logger.info("Bắt đầu kiểm tra chiến lược giao dịch...")
    position: Optional[str] = None
    entry_price: float = 0.0

    while True:
        try:
            # Lấy dữ liệu H4
            df_h4 = get_data(mt5.TIMEFRAME_H4, 100)
            if df_h4.empty:
                await asyncio.sleep(5)
                continue

            # Tính Supertrend
            supertrend = ta.supertrend(df_h4['high'], df_h4['low'], df_h4['close'],
                                       length=10, multiplier=2)
            df_h4['supertrend'] = supertrend['SUPERT_10_2.0']
            df_h4['trend'] = supertrend['SUPERTd_10_2.0']

            # Lấy giá hiện tại
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                logger.error("Không lấy được tick data")
                await asyncio.sleep(5)
                continue
            current_price = (tick.bid + tick.ask) / 2

            # Tính lợi nhuận
            profit_pips = 0
            if position == 'buy':
                profit_pips = (current_price - entry_price) * 10000
                logger.info(f"Buy - Entry: {entry_price:.5f}, Current: {current_price:.5f}, "
                            f"P/L: {profit_pips:.2f} pips")
            elif position == 'sell':
                profit_pips = (entry_price - current_price) * 10000
                logger.info(f"Sell - Entry: {entry_price:.5f}, Current: {current_price:.5f}, "
                            f"P/L: {profit_pips:.2f} pips")

            # Logic giao dịch
            current_trend = df_h4['trend'].iloc[-1]

            if position is None:
                if current_trend == 1:  # Buy signal
                    position = 'buy'
                    entry_price = current_price
                    update_signal("buy", entry_price)
                elif current_trend == -1:  # Sell signal
                    position = 'sell'
                    entry_price = current_price
                    update_signal("sell", entry_price)

            elif position == 'buy':
                if current_trend == -1 or profit_pips >= 30 or profit_pips <= -30:
                    update_signal("close", current_price)
                    position = None
                    logger.info(f"Closed Buy position - P/L: {profit_pips:.2f} pips")

            elif position == 'sell':
                if current_trend == 1 or profit_pips >= 30 or profit_pips <= -30:
                    update_signal("close", current_price)
                    position = None
                    logger.info(f"Closed Sell position - P/L: {profit_pips:.2f} pips")

            await asyncio.sleep(5)  # Kiểm tra mỗi 5 giây

        except Exception as e:
            logger.error(f"Lỗi trong chiến lược: {str(e)}")
            await asyncio.sleep(5)


# Sự kiện khởi động
@app.on_event("startup")
async def startup():
    try:
        initialize_mt5()
        asyncio.create_task(trading_strategy())
    except Exception as e:
        logger.error(f"Lỗi khởi động: {str(e)}")
        raise HTTPException(status_code=500, detail="Không thể khởi động hệ thống")


# Sự kiện tắt
@app.on_event("shutdown")
def shutdown():
    mt5.shutdown()
    logger.info("Đã ngắt kết nối MT5")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)