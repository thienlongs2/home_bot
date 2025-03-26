import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta
import pytz

# Kết nối với MetaTrader 5
mt5.initialize()

# Lấy dữ liệu GBP/USD (GU)
symbol = "GBPUSD"
timeframe = mt5.TIMEFRAME_H4  # Khung thời gian H4
num_bars = 500  # Lấy 500 nến gần nhất
bars = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars)

# Đóng kết nối MT5
mt5.shutdown()

# Kiểm tra dữ liệu
if bars is None or len(bars) == 0:
    raise ValueError("Không có dữ liệu từ MT5. Hãy kiểm tra kết nối và thông tin symbol.")

# Chuyển đổi dữ liệu về DataFrame
df = pd.DataFrame(bars)

# Kiểm tra và sửa lỗi về thời gian
df['time'] = pd.to_datetime(df['time'], unit='s')
print("Dữ liệu trước khi chuyển đổi múi giờ:")
print(df[['time', 'close']].head(10))

# Chuyển đổi múi giờ phù hợp với broker
timezone = pytz.timezone("Etc/UTC")  # Thay đổi nếu broker có múi giờ khác
df['time'] = df['time'].dt.tz_localize('UTC').dt.tz_convert(timezone)

# Sắp xếp dữ liệu theo thời gian
df = df.sort_values(by='time').reset_index(drop=True)

# Tính toán chỉ báo Supertrend
df[['supertrend', 'supertrend_direction']] = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)[['SUPERT_10_3.0', 'SUPERTd_10_3.0']]

# Tính toán EMA 12 và EMA 25
df['ema_12'] = ta.ema(df['close'], length=12)
df['ema_25'] = ta.ema(df['close'], length=25)

# Xác định tín hiệu giao dịch
df['signal'] = df['supertrend_direction'].diff()

# Xác định điểm cắt EMA
df['ema_cross'] = df['ema_12'] - df['ema_25']
df['ema_signal'] = df['ema_cross'].diff()

# Thêm bộ lọc ATR và RSI
df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
df['rsi'] = ta.rsi(df['close'], length=14)

# Điều kiện lọc tín hiệu theo EMA, ATR và RSI
def filter_signal(row):
    if row['signal'] == 2 and row['ema_signal'] > 0 and row['rsi'] > 50:
        return "BUY"
    elif row['signal'] == -2 and row['ema_signal'] < 0 and row['rsi'] < 50:
        return "SELL"
    else:
        return "HOLD"

df['trade_signal'] = df.apply(filter_signal, axis=1)

# In 10 tín hiệu mới nhất
print("Dữ liệu sau khi xử lý:")
print(df[['time', 'close', 'supertrend', 'ema_12', 'ema_25', 'rsi', 'atr', 'trade_signal']].tail(10))
