import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime

# Khởi tạo kết nối MT5
if not mt5.initialize():
    print("Khởi tạo thất bại")
    mt5.shutdown()
    exit()
print("Đã kết nối với MT5")

mau_tien = "GBPUSD"


def lay_du_lieu(symbol, khung_thoi_gian, so_nen):
    du_lieu = mt5.copy_rates_from_pos(symbol, khung_thoi_gian, 0, so_nen)
    if du_lieu is None or len(du_lieu) == 0:
        print(f"Không lấy được dữ liệu {symbol} khung {khung_thoi_gian}")
        return None
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df[['time', 'open', 'high', 'low', 'close']]


def backtest_chien_luoc(von_ban_dau=1000, risk_percent=0.05):
    von = von_ban_dau
    du_lieu_h4 = lay_du_lieu(mau_tien, mt5.TIMEFRAME_H4, 500)
    if du_lieu_h4 is None or du_lieu_h4.empty:
        print("Lỗi: Không có dữ liệu H4!")
        return

    du_lieu_m30 = lay_du_lieu(mau_tien, mt5.TIMEFRAME_M5, 50000)
    if du_lieu_m30 is None or du_lieu_m30.empty:
        print("Lỗi: Không có dữ liệu M30!")
        return

    du_lieu_m5 = lay_du_lieu(mau_tien, mt5.TIMEFRAME_M5, 50000)
    if du_lieu_m5 is None or du_lieu_m5.empty:
        print("Lỗi: Không có dữ liệu M5!")
        return

    # Tính Supertrend trên H4
    supertrend = ta.supertrend(du_lieu_h4['high'], du_lieu_h4['low'], du_lieu_h4['close'], length=10, multiplier=2)
    du_lieu_h4['xu_huong'] = supertrend['SUPERTd_10_2.0']

    # Tính EMA(12) và EMA(25) trên M30
    du_lieu_m30['EMA12'] = ta.ema(du_lieu_m30['close'], length=12)
    du_lieu_m30['EMA25'] = ta.ema(du_lieu_m30['close'], length=25)

    # Đồng bộ dữ liệu M5 với H4 và M30
    du_lieu_m5['time_h4'] = du_lieu_m5['time'].dt.floor('4h')
    du_lieu_m5['time_m30'] = du_lieu_m5['time'].dt.floor('30min')

    du_lieu_h4.set_index('time', inplace=True)
    du_lieu_m30.set_index('time', inplace=True)

    du_lieu_m5 = du_lieu_m5.merge(du_lieu_h4[['xu_huong']], left_on='time_h4', right_index=True, how='left')
    du_lieu_m5 = du_lieu_m5.merge(du_lieu_m30[['EMA12', 'EMA25']], left_on='time_m30', right_index=True, how='left')

    du_lieu_m5[['xu_huong', 'EMA12', 'EMA25']] = du_lieu_m5[['xu_huong', 'EMA12', 'EMA25']].ffill()

    vi_tri, gia_vao, thoi_gian_vao = None, 0, None
    giao_dich, thang, thua = [], 0, 0
    von_cao_nhat, drawdown_max = von_ban_dau, 0

    for i in range(1, len(du_lieu_m5)):
        xu_huong_h4 = du_lieu_m5['xu_huong'].iloc[i]
        ema12 = du_lieu_m5['EMA12'].iloc[i]
        ema25 = du_lieu_m5['EMA25'].iloc[i]
        gia_hien_tai = du_lieu_m5['close'].iloc[i]
        thoi_gian_hien_tai = du_lieu_m5['time'].iloc[i]

        if pd.isna(xu_huong_h4) or pd.isna(ema12) or pd.isna(ema25):
            continue

        pip_risk = 70
        pip_value = 0.0001 * 100000
        khoi_luong = (von * risk_percent) / (pip_risk * pip_value)

        loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000 if vi_tri == 'buy' else (gia_vao - gia_hien_tai) * 10000

        if vi_tri is None and xu_huong_h4 != 0:
            if xu_huong_h4 == 1 and ema12 > ema25:
                vi_tri, gia_vao, thoi_gian_vao = 'buy', gia_hien_tai, thoi_gian_hien_tai
            elif xu_huong_h4 == -1 and ema12 < ema25:
                vi_tri, gia_vao, thoi_gian_vao = 'sell', gia_hien_tai, thoi_gian_hien_tai

        elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            loi_nhuan_gd = (gia_hien_tai - gia_vao) * khoi_luong * 100000
            von += loi_nhuan_gd
            giao_dich.append([thoi_gian_vao, thoi_gian_hien_tai, 'Mua', gia_vao, gia_hien_tai, loi_nhuan_gd])
            thang += loi_nhuan_gd > 0
            thua += loi_nhuan_gd <= 0
            vi_tri = None
            von_cao_nhat = max(von_cao_nhat, von)
            drawdown_max = max(drawdown_max, von_cao_nhat - von)

        elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            loi_nhuan_gd = (gia_vao - gia_hien_tai) * khoi_luong * 100000
            von += loi_nhuan_gd
            giao_dich.append([thoi_gian_vao, thoi_gian_hien_tai, 'Bán', gia_vao, gia_hien_tai, loi_nhuan_gd])
            thang += loi_nhuan_gd > 0
            thua += loi_nhuan_gd <= 0
            vi_tri = None
            von_cao_nhat = max(von_cao_nhat, von)
            drawdown_max = max(drawdown_max, von_cao_nhat - von)
    ty_le_thang = thang / (thang + thua) * 100 if (thang + thua) > 0 else 0
    df_giao_dich = pd.DataFrame(giao_dich, columns=['Thời gian vào', 'Thời gian ra', 'Loại', 'Giá vào', 'Giá ra',
                                                    'Lợi nhuận (USD)'])
    df_giao_dich.to_excel('ket_qua_backtest.xlsx', index=False)
    print(f"Vốn cuối kỳ: {von:.2f} USD | Tỷ lệ thắng: {ty_le_thang:.2f}%")
    print(f"Số giao dịch: {thang + thua}")
    print(f"Tổng lợi nhuận: {von - von_ban_dau:.2f} USD")
    print(f"Drawdown tối đa: {drawdown_max:.2f} USD")
    print(
        f"Lợi nhuận trung bình mỗi giao dịch: {(von - von_ban_dau) / (thang + thua) if (thang + thua) > 0 else 0:.2f} USD")

if __name__ == "__main__":
    backtest_chien_luoc(1000)
