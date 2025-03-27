import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
import pandas_ta as ta

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
    return df

# Backtest chiến lược
def backtest_chien_luoc(ngay_bat_dau, ngay_ket_thuc, von_ban_dau=1000, risk_percent=0.05):
    # Lấy dữ liệu H4 và M15
    du_lieu_h4 = lay_du_lieu(mt5.TIMEFRAME_H4, ngay_bat_dau, ngay_ket_thuc)
    du_lieu_m15 = lay_du_lieu(mt5.TIMEFRAME_M5, ngay_bat_dau, ngay_ket_thuc)

    du_lieu_h4.to_csv("du_lieu_H4.csv", index=False, encoding="utf-8")
    du_lieu_m15.to_csv("du_lieu_m15.csv", index=False, encoding="utf-8")
    print("Dữ liệu đã được lưu thành công.")

    # Tính Supertrend
    supertrend = ta.supertrend(du_lieu_h4['high'], du_lieu_h4['low'], du_lieu_h4['close'], length=10, multiplier=2)
    du_lieu_h4['supertrend'] = supertrend['SUPERT_10_2.0']
    du_lieu_h4['xu_huong'] = supertrend['SUPERTd_10_2.0']

    # Kết hợp dữ liệu H4 vào M15
    du_lieu_m15['time_h4'] = du_lieu_m15['time'].dt.floor('4h')
    du_lieu_h4.set_index('time', inplace=True)
    du_lieu_m15 = du_lieu_m15.merge(du_lieu_h4[['xu_huong', 'supertrend']],
                                  left_on='time_h4', right_index=True, how='left')
    du_lieu_m15[['xu_huong', 'supertrend']] = du_lieu_m15[['xu_huong', 'supertrend']].ffill()

    # Thêm các cột mới vào du_lieu_m15
    du_lieu_m15['vi_tri'] = None  # buy, sell, hold buy, hold sell, close
    du_lieu_m15['khoang_cach_supertrend'] = 0.0  # Khoảng cách giữa close và supertrend
    du_lieu_m15['gia_vao_lenh'] = 0.0  # Giá vào lệnh
    du_lieu_m15['gia_thoat_lenh'] = 0.0  # Giá thoát lệnh
    du_lieu_m15['volume'] = 0.0  # Volume (lot size) vào lệnh
    du_lieu_m15['loi_nhuan_pip'] = 0.0  # Lợi nhuận tính bằng pip
    du_lieu_m15['loi_nhuan_usd'] = 0.0  # Lợi nhuận tính bằng USD
    du_lieu_m15['ly_do'] = None  # Lý do cho hành động buy/hold/sell/close

    # Biến theo dõi giao dịch
    von = von_ban_dau
    vi_tri = None
    gia_vao = 0
    trailing_stop = 0
    khoi_luong = 0
    loi_nhuan = []
    thang = 0
    thua = 0
    duong_von = [von]
    thoi_gian = [du_lieu_m15['time'].iloc[0]]
    loi_nhuan_thang = []
    loi_nhuan_thua = []
    so_du = []
    thoi_gian_so_du = []
    drawdown_max = 0
    peak = von_ban_dau  # Theo dõi đỉnh cao nhất của vốn
    loi_nhuan_theo_thang = []

    # Duyệt qua từng nến M15
    for i in range(1, len(du_lieu_m15)):
        xu_huong_h4 = du_lieu_m15['xu_huong'].iloc[i]
        supertrend_value = du_lieu_m15['supertrend'].iloc[i]
        gia_hien_tai = du_lieu_m15['close'].iloc[i]
        du_lieu_m15.at[i, 'gia_hien_tai'] = gia_hien_tai


        # Tính khoảng cách giữa giá close và Supertrend
        khoang_cach = gia_hien_tai - supertrend_value
        du_lieu_m15.at[i, 'khoang_cach_supertrend'] = khoang_cach

        # Tính lot size dựa trên rủi ro % vốn
        pip_risk = 70
        pip_value = 0.0001 * 100000
        khoi_luong_tinh_toan = (von * risk_percent) / (pip_risk * pip_value)
        khoi_luong_tinh_toan = max(0.01, np.floor(khoi_luong_tinh_toan * 100) / 100)

        # Tính lợi nhuận pip
        if vi_tri == 'buy':
            loi_nhuan_pip = (gia_hien_tai - gia_vao) * 10000
            du_lieu_m15.at[i, 'vi_tri'] = 'hold buy'
            du_lieu_m15.at[i, 'ly_do'] = 'Đang giữ lệnh mua'
            du_lieu_m15.at[i, 'gia_vao_lenh'] = gia_vao
            du_lieu_m15.at[i, 'volume'] = khoi_luong
        elif vi_tri == 'sell':
            loi_nhuan_pip = (gia_vao - gia_hien_tai) * 10000
            du_lieu_m15.at[i, 'vi_tri'] = 'hold sell'
            du_lieu_m15.at[i, 'ly_do'] = 'Đang giữ lệnh bán'
            du_lieu_m15.at[i, 'gia_vao_lenh'] = gia_vao
            du_lieu_m15.at[i, 'volume'] = khoi_luong
        else:
            loi_nhuan_pip = 0
            du_lieu_m15.at[i, 'vi_tri'] = None
            du_lieu_m15.at[i, 'ly_do'] = 'Không có vị trí'
            du_lieu_m15.at[i, 'gia_vao_lenh'] = 0.0
            du_lieu_m15.at[i, 'volume'] = 0.0

        du_lieu_m15.at[i, 'loi_nhuan_pip'] = loi_nhuan_pip

        # Điều kiện mua: Chỉ dựa vào Supertrend H4
        if vi_tri is None and xu_huong_h4 == 1 and supertrend_value > 0:
            vi_tri = 'buy'
            gia_vao = gia_hien_tai
            trailing_stop = gia_vao - 0.0070
            khoi_luong = khoi_luong_tinh_toan
            du_lieu_m15.at[i, 'vi_tri'] = 'buy'
            du_lieu_m15.at[i, 'volume'] = khoi_luong
            du_lieu_m15.at[i, 'gia_vao_lenh'] = gia_vao
            du_lieu_m15.at[i, 'ly_do'] = 'Mua: Xu hướng H4 tăng & Supertrend > 0'
            print(f"{du_lieu_m15['time'].iloc[i]} - Mua tại {gia_vao}")

        # Điều kiện bán: Chỉ dựa vào Supertrend H4
        elif vi_tri is None and xu_huong_h4 == -1 and supertrend_value > 0:
            vi_tri = 'sell'
            gia_vao = gia_hien_tai
            trailing_stop = gia_vao + 0.0070
            khoi_luong = khoi_luong_tinh_toan
            du_lieu_m15.at[i, 'vi_tri'] = 'sell'
            du_lieu_m15.at[i, 'volume'] = khoi_luong
            du_lieu_m15.at[i, 'gia_vao_lenh'] = gia_vao
            du_lieu_m15.at[i, 'ly_do'] = 'Bán: Xu hướng H4 giảm & Supertrend > 0'
            print(f"{du_lieu_m15['time'].iloc[i]} - Bán tại {gia_vao}")

        # Thoát lệnh mua
        elif vi_tri == 'buy' and (xu_huong_h4 == -1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            loi_nhuan_giao_dich = (gia_hien_tai - gia_vao) * khoi_luong * 100000
            von += loi_nhuan_giao_dich
            loi_nhuan.append(loi_nhuan_giao_dich)
            loi_nhuan_theo_thang.append((du_lieu_m15['time'].iloc[i], loi_nhuan_giao_dich))
            if xu_huong_h4 == -1:
                ly_do = 'Đóng mua: Xu hướng H4 đảo chiều giảm'
            elif loi_nhuan_pip >= 120:
                ly_do = 'Đóng mua: Chạm mục tiêu lợi nhuận 120 pip'
            else:
                ly_do = 'Đóng mua: Chạm mức cắt lỗ -70 pip'
            print(f"{du_lieu_m15['time'].iloc[i]} - Đóng mua tại {gia_hien_tai}, Lợi nhuận: {loi_nhuan_giao_dich:.2f} ({loi_nhuan_pip:.1f} pip)")
            if loi_nhuan_giao_dich > 0:
                thang += 1
                loi_nhuan_thang.append(loi_nhuan_giao_dich)
            else:
                thua += 1
                loi_nhuan_thua.append(loi_nhuan_giao_dich)
            # du_lieu_m15.at[i, 'gia_thoat_lenh'] = gia_hien_tai
            du_lieu_m15.at[i, 'loi_nhuan_usd'] = loi_nhuan_giao_dich
            du_lieu_m15.at[i, 'vi_tri'] = 'close'
            du_lieu_m15.at[i, 'volume'] = khoi_luong
            du_lieu_m15.at[i, 'ly_do'] = ly_do
            vi_tri = None
            khoi_luong = 0
            trailing_stop = 0
            duong_von.append(von)
            thoi_gian.append(du_lieu_m15['time'].iloc[i])

        # Thoát lệnh bán
        elif vi_tri == 'sell' and (xu_huong_h4 == 1 or loi_nhuan_pip >= 120 or loi_nhuan_pip <= -70):
            loi_nhuan_giao_dich = (gia_vao - gia_hien_tai) * khoi_luong * 100000
            von += loi_nhuan_giao_dich
            loi_nhuan.append(loi_nhuan_giao_dich)
            loi_nhuan_theo_thang.append((du_lieu_m15['time'].iloc[i], loi_nhuan_giao_dich))
            if xu_huong_h4 == 1:
                ly_do = 'Đóng bán: Xu hướng H4 đảo chiều tăng'
            elif loi_nhuan_pip >= 120:
                ly_do = 'Đóng bán: Chạm mục tiêu lợi nhuận 120 pip'
            else:
                ly_do = 'Đóng bán: Chạm mức cắt lỗ -70 pip'
            print(f"{du_lieu_m15['time'].iloc[i]} - Đóng bán tại {gia_hien_tai}, Lợi nhuận: {loi_nhuan_giao_dich:.2f} ({loi_nhuan_pip:.1f} pip)")
            if loi_nhuan_giao_dich > 0:
                thang += 1
                loi_nhuan_thang.append(loi_nhuan_giao_dich)
            else:
                thua += 1
                loi_nhuan_thua.append(loi_nhuan_giao_dich)
            # du_lieu_m15.at[i, 'gia_thoat_lenh'] = gia_hien_tai
            du_lieu_m15.at[i, 'loi_nhuan_usd'] = loi_nhuan_giao_dich
            du_lieu_m15.at[i, 'vi_tri'] = 'close'
            du_lieu_m15.at[i, 'volume'] = khoi_luong
            du_lieu_m15.at[i, 'ly_do'] = ly_do
            vi_tri = None
            khoi_luong = 0
            trailing_stop = 0
            duong_von.append(von)
            thoi_gian.append(du_lieu_m15['time'].iloc[i])

        # Cập nhật số dư và drawdown
        if vi_tri is not None:
            if vi_tri == 'buy':
                so_du_hien_tai = von + (gia_hien_tai - gia_vao) * khoi_luong * 100000
                du_lieu_m15.at[i, 'loi_nhuan_usd'] = (gia_hien_tai - gia_vao) * khoi_luong * 100000
            else:  # sell
                so_du_hien_tai = von + (gia_vao - gia_hien_tai) * khoi_luong * 100000
                du_lieu_m15.at[i, 'loi_nhuan_usd'] = (gia_vao - gia_hien_tai) * khoi_luong * 100000
        else:
            so_du_hien_tai = von

        so_du.append(so_du_hien_tai)
        thoi_gian_so_du.append(du_lieu_m15['time'].iloc[i])
        duong_von.append(von)
        thoi_gian.append(du_lieu_m15['time'].iloc[i])

        # Cập nhật đỉnh cao nhất và tính drawdown
        peak = max(peak, so_du_hien_tai)
        drawdown = peak - so_du_hien_tai
        drawdown_max = max(drawdown_max, drawdown)

    # Lưu dữ liệu M15 với các cột mới
    du_lieu_m15.to_csv("du_lieu_meger.csv", index=False, encoding="utf-8")
    du_lieu_m15.to_excel("du_lieu_meger_excel.xlsx", index=False)

    print("Dữ liệu M15 với các thông tin giao dịch và lý do đã được lưu vào 'du_lieu_meger.csv'.")

    # Tính toán kết quả
    tong_loi_nhuan = sum(loi_nhuan) if loi_nhuan else 0
    ty_le_thang = thang / (thang + thua) * 100 if (thang + thua) > 0 else 0
    loi_nhuan_thang_trung_binh = sum(loi_nhuan_thang) / len(loi_nhuan_thang) if loi_nhuan_thang else 0
    loi_nhuan_thua_trung_binh = sum(loi_nhuan_thua) / len(loi_nhuan_thua) if loi_nhuan_thua else 0
    lenh_loi_nhuan_lon_nhat = max(loi_nhuan) if loi_nhuan else 0
    lenh_thua_lo_lon_nhat = min(loi_nhuan) if loi_nhuan else 0

    # In kết quả
    print("\n=== Kết quả Backtest ===")
    print(f"Risk per trade: {risk_percent*100:.2f}%")
    print(f"Vốn ban đầu: {von_ban_dau:.2f} USD")
    print(f"Vốn cuối kỳ: {von:.2f} USD")
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

    # Chuẩn bị văn bản cho biểu đồ
    thong_so = (
        f"Risk per trade: {risk_percent*100:.2f}%\n"
        f"Vốn ban đầu: {von_ban_dau:.2f} USD\n"
        f"Vốn cuối kỳ: {von:.2f} USD\n"
        f"Tổng lợi nhuận: {tong_loi_nhuan:.2f} USD\n"
        f"Số lệnh thắng: {thang}\n"
        f"Số lệnh thua: {thua}\n"
        f"Tỷ lệ thắng: {ty_le_thang:.2f}%\n"
        f"Số giao dịch: {thang + thua}\n"
        f"Lệnh lợi nhuận lớn nhất: {lenh_loi_nhuan_lon_nhat:.2f} USD\n"
        f"Lệnh thua lỗ lớn nhất: {lenh_thua_lo_lon_nhat:.2f} USD\n"
        f"Lợi nhuận TB khi thắng: {loi_nhuan_thang_trung_binh:.2f} USD\n"
        f"Lỗ TB khi thua: {loi_nhuan_thua_trung_binh:.2f} USD\n"
        f"Drawdown tối đa: {drawdown_max:.2f} USD"
    )

    # Tính lợi nhuận theo tháng
    df_loi_nhuan = pd.DataFrame(loi_nhuan_theo_thang, columns=['time', 'loi_nhuan'])
    df_loi_nhuan['month'] = df_loi_nhuan['time'].dt.to_period('M')
    loi_nhuan_thang = df_loi_nhuan.groupby('month')['loi_nhuan'].sum()

    # Vẽ biểu đồ vốn
    plt.figure(figsize=(12, 6))
    plt.plot(thoi_gian, duong_von, label='Đường vốn (Equity Curve)', color='blue')
    plt.plot(thoi_gian_so_du, so_du, label='Số dư (Balance with Open Positions)', color='green', linestyle='--')
    plt.axhline(y=von_ban_dau, color='red', linestyle='--', label='Vốn ban đầu')

    # Thêm hộp văn bản chứa thông số
    plt.text(0.02, 0.98, thong_so, transform=plt.gca().transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.title('Biểu đồ Lãi/Lỗ của Chiến lược (Supertrend H4)')
    plt.xlabel('Thời gian')
    plt.ylabel('Vốn (USD)')
    plt.legend()
    plt.grid()
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

    # Vẽ biểu đồ lợi nhuận theo tháng
    plt.figure(figsize=(12, 6))
    loi_nhuan_thang.plot(kind='bar', color=['green' if x > 0 else 'red' for x in loi_nhuan_thang])
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