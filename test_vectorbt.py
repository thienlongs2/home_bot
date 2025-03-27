import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import vectorbt as vbt
import pandas_ta as ta
import matplotlib.pyplot as plt

# Khởi tạo kết nối MT5
if not mt5.initialize():
    print("Khởi tạo thất bại")
    mt5.shutdown()
    exit()

print("Đã kết nối với MT5")
mau_tien = "GBPUSD"

# Lấy dữ liệu từ MT5
def lay_du_lieu(khung_thoi_gian, ngay_bat_dau, ngay_ket_thuc):
    du_lieu = mt5.copy_rates_range(mau_tien, khung_thoi_gian, ngay_bat_dau, ngay_ket_thuc)
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close']]
    df.set_index('time', inplace=True)
    return df

# Backtest chiến lược sử dụng VectorBT
def backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000, risk_percent=0.05):
    # Lấy dữ liệu H4 và M15
    du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, ngay_bat_dau, ngay_ket_thuc)
    du_lieu_m15 = lay_du_lieu(mt5.TIMEFRAME_M5, ngay_bat_dau, ngay_ket_thuc)

    # Lưu dữ liệu gốc
    du_lieu_h4.reset_index().to_csv("du_lieu_H4.csv", index=False, encoding="utf-8")
    du_lieu_m15.reset_index().to_csv("du_lieu_m15.csv", index=False, encoding="utf-8")
    print("Dữ liệu đã được lưu thành công.")

    # Tính Supertrend trên H4
    supertrend = ta.supertrend(du_lieu_h4['high'], du_lieu_h4['low'], du_lieu_h4['close'], length=10, multiplier=2)
    du_lieu_h4['supertrend'] = supertrend['SUPERT_10_2.0']
    du_lieu_h4['xu_huong'] = supertrend['SUPERTd_10_2.0']

    # Kết hợp dữ liệu H4 vào M15
    du_lieu_m15['time_h4'] = du_lieu_m15.index.floor('4h')
    du_lieu_m15 = du_lieu_m15.merge(du_lieu_h4[['xu_huong', 'supertrend']],
                                    left_on='time_h4', right_index=True, how='left')
    du_lieu_m15[['xu_huong', 'supertrend']] = du_lieu_m15[['xu_huong', 'supertrend']].ffill()
    du_lieu_m15.drop(columns=['time_h4'], inplace=True)

    # Tính tín hiệu vào lệnh và thoát lệnh
    # Tín hiệu mua: xu_huong == 1 và supertrend > 0
    buy_signals = (du_lieu_m15['xu_huong'] == 1) & (du_lieu_m15['supertrend'] > 0)
    # Tín hiệu bán: xu_huong == -1 và supertrend > 0
    sell_signals = (du_lieu_m15['xu_huong'] == -1) & (du_lieu_m15['supertrend'] > 0)

    # Tính lợi nhuận pip để xác định điều kiện thoát lệnh
    entries = pd.Series(False, index=du_lieu_m15.index)
    exits = pd.Series(False, index=du_lieu_m15.index)
    position = 0  # 0: không có vị trí, 1: buy, -1: sell
    gia_vao = 0
    for i in range(len(du_lieu_m15)):
        if position == 0:  # Không có vị trí
            if buy_signals.iloc[i]:
                entries.iloc[i] = True
                position = 1
                gia_vao = du_lieu_m15['close'].iloc[i]
            elif sell_signals.iloc[i]:
                entries.iloc[i] = True
                position = -1
                gia_vao = du_lieu_m15['close'].iloc[i]
        else:  # Đang có vị trí
            if position == 1:  # Đang mua
                loi_nhuan_pip = (du_lieu_m15['close'].iloc[i] - gia_vao) * 10000
                if (du_lieu_m15['xu_huong'].iloc[i] == -1) or (loi_nhuan_pip >= 120) or (loi_nhuan_pip <= -70):
                    exits.iloc[i] = True
                    position = 0
            elif position == -1:  # Đang bán
                loi_nhuan_pip = (gia_vao - du_lieu_m15['close'].iloc[i]) * 10000
                if (du_lieu_m15['xu_huong'].iloc[i] == 1) or (loi_nhuan_pip >= 120) or (loi_nhuan_pip <= -70):
                    exits.iloc[i] = True
                    position = 0

    # Tính khối lượng giao dịch
    pip_risk = 70
    pip_value = 0.0001 * 100000
    khoi_luong = (von_ban_dau * risk_percent) / (pip_risk * pip_value)
    khoi_luong = max(0.01, np.floor(khoi_luong * 100) / 100)

    # Tạo portfolio với VectorBT, chỉ định tần suất là 5 phút (M15)
    portfolio = vbt.Portfolio.from_signals(
        close=du_lieu_m15['close'],
        entries=entries,
        exits=exits,
        size=khoi_luong,
        direction='both',  # Hỗ trợ cả mua và bán
        fees=0.0,  # Không tính phí giao dịch
        init_cash=von_ban_dau,
        freq='5min'  # Chỉ định tần suất là 5 phút
    )

    # Tính các chỉ số hiệu suất
    stats = portfolio.stats()
    # In toàn bộ stats để kiểm tra các chỉ số có sẵn
    print("Các chỉ số có sẵn trong stats:")
    print(stats)

    thang = portfolio.trades.winning.count()
    thua = portfolio.trades.losing.count()
    ty_le_thang = (thang / (thang + thua) * 100) if (thang + thua) > 0 else 0
    loi_nhuan_thang_trung_binh = portfolio.trades.winning.pnl.mean() if thang > 0 else 0
    loi_nhuan_thua_trung_binh = portfolio.trades.losing.pnl.mean() if thua > 0 else 0
    lenh_loi_nhuan_lon_nhat = portfolio.trades.pnl.max() if portfolio.trades.count() > 0 else 0
    lenh_thua_lo_lon_nhat = portfolio.trades.pnl.min() if portfolio.trades.count() > 0 else 0
    # drawdown_max = stats['Max Drawdown [%]']  # Sửa tên chỉ số
    tong_loi_nhuan = portfolio.total_profit()

    if 'Max Drawdown [%]' in stats:
        drawdown_max = stats['Max Drawdown [%]']
    else:
        drawdown_max = None  # Hoặc giá trị mặc định

    # In kết quả
    print("\n=== Kết quả Backtest ===")
    print(f"Risk per trade: {risk_percent*100:.2f}%")
    print(f"Vốn ban đầu: {von_ban_dau:.2f} USD")
    print(f"Vốn cuối kỳ: {portfolio.value()[-1]:.2f} USD")
    print(f"Tổng lợi nhuận: {tong_loi_nhuan:.2f} USD")
    print(f"Số lệnh thắng: {thang}")
    print(f"Số lệnh thua: {thua}")
    print(f"Tỷ lệ thắng: {ty_le_thang:.2f}%")
    print(f"Số giao dịch: {thang + thua}")
    print(f"Lệnh có lợi nhuận lớn nhất: {lenh_loi_nhuan_lon_nhat:.2f} USD")
    print(f"Lệnh thua lỗ lớn nhất: {lenh_thua_lo_lon_nhat:.2f} USD")
    print(f"Lợi nhuận trung bình khi thắng: {loi_nhuan_thang_trung_binh:.2f} USD")
    print(f"Lỗ trung bình khi thua: {loi_nhuan_thua_trung_binh:.2f} USD")
    print(f"Drawdown tối đa: {drawdown_max:.2f} USD")
    print(f"Sharpe Ratio: {stats['Sharpe Ratio']:.2f}")
    print(f"Sortino Ratio: {stats['Sortino Ratio']:.2f}")
    print(f"Calmar Ratio: {stats['Calmar Ratio']:.2f}")

    # Vẽ biểu đồ vốn
    portfolio.plot().show()

    # Vẽ biểu đồ lợi nhuận theo tháng
    monthly_returns = portfolio.returns.resample('M').sum()
    plt.figure(figsize=(12, 6))
    monthly_returns.plot(kind='bar', color=['green' if x > 0 else 'red' for x in monthly_returns])
    plt.title('Lợi nhuận theo Tháng')
    plt.xlabel('Tháng')
    plt.ylabel('Lợi nhuận (USD)')
    plt.axhline(y=0, color='black', linestyle='--')
    plt.xticks(rotation=45)
    plt.grid(axis='y')
    plt.tight_layout()
    plt.show()

# Chạy backtest
if __name__ == "__main__":
    ngay_bat_dau = datetime(2024, 8, 9)
    ngay_ket_thuc = datetime(2025, 3, 26)
    backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000, risk_percent=0.05)

    # Đóng kết nối MT5
    mt5.shutdown()