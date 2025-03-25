import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt

# Khởi tạo kết nối MT5
if not mt5.initialize():
    print("Khởi tạo thất bại")
    mt5.shutdown()
    exit()

print("Đã kết nối với MT5")
mau_tien = "GBPUSD"

# Tính toán Supertrend
def tinh_supertrend(df, chu_ky=10, he_so=2.0):
    df['hl2'] = (df['high'] + df['low']) / 2
    df['tr'] = np.maximum.reduce([df['high'] - df['low'],
                                  abs(df['high'] - df['close'].shift(1)),
                                  abs(df['low'] - df['close'].shift(1))])
    df['atr'] = df['tr'].rolling(window=chu_ky).mean()

    df['bang_tren'] = df['hl2'] - (he_so * df['atr'])
    df['bang_duoi'] = df['hl2'] + (he_so * df['atr'])
    df['bang_tren'] = df['bang_tren'].fillna(method='bfill')
    df['bang_duoi'] = df['bang_duoi'].fillna(method='bfill')

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
    df['xu_huong'] = df['xu_huong'].fillna(1)
    return df

# Lấy dữ liệu từ MT5
def lay_du_lieu(khung_thoi_gian, ngay_bat_dau, ngay_ket_thuc):
    du_lieu = mt5.copy_rates_range(mau_tien, khung_thoi_gian, ngay_bat_dau, ngay_ket_thuc)
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close']]
    return df

# Backtest chiến lược
def backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000, risk_percent=0.05):
    du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, ngay_bat_dau, ngay_ket_thuc)
    du_lieu_m1 = lay_du_lieu(mt5.TIMEFRAME_M1, ngay_bat_dau, ngay_ket_thuc)

    du_lieu_h4 = tinh_supertrend(du_lieu_h4)
    du_lieu_m1['time_h4'] = du_lieu_m1['time'].dt.floor('4h')
    du_lieu_h4.set_index('time', inplace=True)
    du_lieu_m1 = du_lieu_m1.merge(du_lieu_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
    du_lieu_m1.loc[:, 'xu_huong'] = du_lieu_m1['xu_huong'].ffill()

    von = von_ban_dau
    vi_tri = None
    gia_vao = 0
    thoi_gian_vao = None  # Thêm biến để lưu thời gian vào lệnh
    trailing_stop = 0
    loi_nhuan = []
    thang = 0
    thua = 0
    duong_von = [von]
    thoi_gian = [du_lieu_m1['time'].iloc[0]]
    giao_dich = []  # Danh sách lưu dữ liệu giao dịch

    for i in range(1, len(du_lieu_m1)):
        xu_huong_h4 = du_lieu_m1['xu_huong'].iloc[i]
        gia_hien_tai = du_lieu_m1['close'].iloc[i]
        thoi_gian_hien_tai = du_lieu_m1['time'].iloc[i]

        pip_risk = 70
        pip_value = 0.0001 * 100000
        khoi_luong = (von * risk_percent) / (pip_risk * pip_value)

        if vi_tri == 'buy':
            loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000
        elif vi_tri == 'sell':
            loi_nhuan_pip = (gia_vao - gia_hien_tai) * 10000

        if vi_tri is None and xu_huong_h4 == 1:
            vi_tri = 'buy'
            gia_vao = gia_hien_tai
            thoi_gian_vao = thoi_gian_hien_tai  # Lưu thời gian vào lệnh
            trailing_stop = gia_vao - 0.0070
            print(f"{thoi_gian_hien_tai} - Mua tại {gia_vao}")

        elif vi_tri is None and xu_huong_h4 == -1:
            vi_tri = 'sell'
            gia_vao = gia_hien_tai
            thoi_gian_vao = thoi_gian_hien_tai  # Lưu thời gian vào lệnh
            trailing_stop = gia_vao + 0.0070
            print(f"{thoi_gian_hien_tai} - Bán tại {gia_vao}")

        elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            loi_nhuan_giao_dich = (gia_hien_tai - gia_vao) * khoi_luong * 100000
            von += loi_nhuan_giao_dich
            loi_nhuan.append(loi_nhuan_giao_dich)
            print(f"{thoi_gian_hien_tai} - Đóng mua tại {gia_hien_tai}, Lợi nhuận: {loi_nhuan_giao_dich:.2f} ({loi_nhuan_pip:.1f} pip)")
            giao_dich.append([thoi_gian_vao, thoi_gian_hien_tai, 'Mua', gia_vao, gia_hien_tai, loi_nhuan_giao_dich, loi_nhuan_pip])
            if loi_nhuan_giao_dich > 0:
                thang += 1
            else:
                thua += 1
            vi_tri = None
            thoi_gian_vao = None
            trailing_stop = 0
            duong_von.append(von)
            thoi_gian.append(thoi_gian_hien_tai)

        elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            loi_nhuan_giao_dich = (gia_vao - gia_hien_tai) * khoi_luong * 100000
            von += loi_nhuan_giao_dich
            loi_nhuan.append(loi_nhuan_giao_dich)
            print(f"{thoi_gian_hien_tai} - Đóng bán tại {gia_hien_tai}, Lợi nhuận: {loi_nhuan_giao_dich:.2f} ({loi_nhuan_pip:.1f} pip)")
            giao_dich.append([thoi_gian_vao, thoi_gian_hien_tai, 'Bán', gia_vao, gia_hien_tai, loi_nhuan_giao_dich, loi_nhuan_pip])
            if loi_nhuan_giao_dich > 0:
                thang += 1
            else:
                thua += 1
            vi_tri = None
            thoi_gian_vao = None
            trailing_stop = 0
            duong_von.append(von)
            thoi_gian.append(thoi_gian_hien_tai)

    # Tính toán kết quả
    tong_loi_nhuan = sum(loi_nhuan) if loi_nhuan else 0
    ty_le_thang = thang / (thang + thua) * 100 if (thang + thua) > 0 else 0

    print("\n=== Kết quả Backtest ===")
    print(f"Vốn ban đầu: {von_ban_dau:.2f} USD")
    print(f"Vốn cuối kỳ: {von:.2f} USD")
    print(f"Tổng lợi nhuận: {tong_loi_nhuan:.2f} USD")
    print(f"Số lệnh thắng: {thang}")
    print(f"Số lệnh thua: {thua}")
    print(f"Tỷ lệ thắng: {ty_le_thang:.2f}%")

    # Lưu dữ liệu giao dịch vào DataFrame
    df_giao_dich = pd.DataFrame(giao_dich, columns=['Thời gian vào', 'Thời gian ra', 'Loại', 'Giá vào', 'Giá ra', 'Lợi nhuận (USD)', 'Pip'])

    # Xuất ra file Excel
    df_giao_dich.to_excel('ket_qua_backtest.xlsx', index=False)
    print("Đã lưu kết quả vào file 'ket_qua_backtest.xlsx'")

# Chạy backtest
if __name__ == "__main__":
    ngay_bat_dau = datetime(2025, 3, 1)
    ngay_ket_thuc = datetime(2025, 3, 25)
    backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000)