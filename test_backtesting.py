import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import pandas_ta as ta
from backtesting import Backtest, Strategy
import matplotlib.pyplot as plt

# Khởi tạo kết nối MT5
if not mt5.initialize():
    print("Khởi tạo thất bại")
    mt5.shutdown()
    exit()

print("Đã kết nối với MT5")
MUAO_TIEN = "GBPUSD"

# Lấy dữ liệu từ MT5
def lay_du_lieu(khung_thoi_gian, ngay_bat_dau, ngay_ket_thuc):
    du_lieu = mt5.copy_rates_range(MUAO_TIEN, khung_thoi_gian, ngay_bat_dau, ngay_ket_thuc)
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close']]
    df.set_index('time', inplace=True)
    return df

# Định nghĩa chiến lược cho Backtesting
class SupertrendStrategy(Strategy):
    risk_percent = 0.05
    pip_risk = 70
    pip_target = 120
    pip_stop = -70
    du_lieu_h4 = None  # Biến lớp chứa dữ liệu H4

    def init(self):
        if SupertrendStrategy.du_lieu_h4 is None:
            raise ValueError("Dữ liệu H4 chưa được gán trước khi chạy backtest.")

        # Tính toán Supertrend trên H4
        supertrend = ta.supertrend(SupertrendStrategy.du_lieu_h4['high'], 
                                   SupertrendStrategy.du_lieu_h4['low'], 
                                   SupertrendStrategy.du_lieu_h4['close'], 
                                   length=10, multiplier=2)
        SupertrendStrategy.du_lieu_h4['supertrend'] = supertrend['SUPERT_10_2.0']
        SupertrendStrategy.du_lieu_h4['xu_huong'] = supertrend['SUPERTd_10_2.0']

        # Merge dữ liệu H4 vào dữ liệu M15
        merged_data = self.data.df.copy()
        merged_data['time_h4'] = merged_data.index.floor('4h')
        merged_data = merged_data.merge(SupertrendStrategy.du_lieu_h4[['xu_huong', 'supertrend']],
                                        left_on='time_h4', right_index=True, how='left')
        merged_data[['xu_huong', 'supertrend']] = merged_data[['xu_huong', 'supertrend']].ffill()
        merged_data.drop(columns=['time_h4'], inplace=True)

        # Chuyển dữ liệu thành chỉ báo
        self.xu_huong = self.I(lambda x: x, merged_data['xu_huong'])
        self.supertrend = self.I(lambda x: x, merged_data['supertrend'])

    def next(self):
        # Điều kiện vào lệnh
        if not self.position:  # Nếu không có vị thế
            if self.xu_huong[-1] == 1 and self.supertrend[-1] > 0:  # Mua
                self.buy()
            elif self.xu_huong[-1] == -1 and self.supertrend[-1] > 0:  # Bán
                self.sell()
        else:  # Nếu đang có vị thế
            if self.position.is_long and (self.xu_huong[-1] == -1 or self.position.pl < self.pip_stop):
                self.position.close()
            elif self.position.is_short and (self.xu_huong[-1] == 1 or self.position.pl < self.pip_stop):
                self.position.close()

# Backtest chiến lược
def backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000):
    # Lấy dữ liệu H4 và M15
    du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, ngay_bat_dau, ngay_ket_thuc)
    du_lieu_m15 = lay_du_lieu(mt5.TIMEFRAME_M15, ngay_bat_dau, ngay_ket_thuc)
    
    # Lưu dữ liệu vào class strategy
    SupertrendStrategy.du_lieu_h4 = du_lieu_h4  
    
    # Chuyển dữ liệu M15 sang format phù hợp
    du_lieu_m15.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)
    
    # Tạo và chạy backtest
    bt = Backtest(du_lieu_m15, SupertrendStrategy, cash=von_ban_dau, commission=0.0, exclusive_orders=True)
    stats = bt.run()
    bt.plot()

    print("\n=== Kết quả Backtest ===")
    print(stats)

# Chạy backtest
if __name__ == "__main__":
    ngay_bat_dau = datetime(2024, 8, 9)
    ngay_ket_thuc = datetime(2025, 3, 26)
    backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000)

    # Đóng kết nối MT5
    mt5.shutdown()
