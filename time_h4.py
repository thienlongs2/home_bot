import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pandas as pd
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def ket_noi_mt5():
    """Khởi tạo và kiểm tra kết nối với MT5."""
    if not mt5.initialize():
        logging.error("Không thể kết nối với MetaTrader5")
        return False
    logging.info("Kết nối với MetaTrader5 thành công")

    tick = mt5.symbol_info_tick("EURUSD")
    if tick:
        server_time = datetime.fromtimestamp(tick.time)
        logging.info(f"Thời gian server MT5: {server_time}")
    else:
        logging.warning("Không lấy được thời gian server từ tick data")
    return True


def lay_du_lieu_mt5(mau_tien, khung_thoi_gian=mt5.TIMEFRAME_H4, so_nen=100, do_tre_toi_da=3600):
    """
    Lấy dữ liệu từ MT5 và kiểm tra độ trễ.

    Args:
        mau_tien (str): Cặp tiền, ví dụ 'EURUSD'
        khung_thoi_gian: Khung thời gian (default: H4)
        so_nen (int): Số nến cần lấy (default: 100)
        do_tre_toi_da (int): Độ trễ tối đa cho phép (giây, default: 1 giờ)

    Returns:
        pd.DataFrame: DataFrame chứa dữ liệu nến hoặc None nếu thất bại
    """
    if not ket_noi_mt5():
        return None

    # Lấy dữ liệu theo số lượng nến từ thời điểm hiện tại
    du_lieu = mt5.copy_rates_from_pos(mau_tien, khung_thoi_gian, 0, so_nen)
    if du_lieu is None or len(du_lieu) == 0:
        logging.error(f"Không lấy được dữ liệu {khung_thoi_gian} cho {mau_tien}")
        return None

    # Chuyển đổi thành DataFrame
    df = pd.DataFrame(du_lieu)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # Kiểm tra thời gian nến cuối cùng
    thoi_gian_nen_cuoi = df['time'].iloc[-1]
    do_tre = (datetime.utcnow() - thoi_gian_nen_cuoi).total_seconds()
    khung_ten = 'H4' if khung_thoi_gian == mt5.TIMEFRAME_H4 else 'M15'

    # Nếu độ trễ vượt quá ngưỡng, ghi log cảnh báo
    if do_tre > do_tre_toi_da:
        logging.warning(f"Dữ liệu {khung_ten} bị trễ quá mức: {do_tre:.2f} giây (tối đa: {do_tre_toi_da} giây)")
    else:
        logging.info(f"Thời gian nến cuối cùng {khung_ten}: {thoi_gian_nen_cuoi}, Độ trễ: {do_tre:.2f} giây")

    return df


def main():
    """Hàm chính để chạy chương trình."""
    mau_tien = "EURUSD"

    # Lấy dữ liệu H4 và M15 (100 nến, độ trễ tối đa 1 giờ cho H4, 15 phút cho M15)
    df_h4 = lay_du_lieu_mt5(mau_tien, mt5.TIMEFRAME_H4, 100, 3600)  # 1 giờ
    df_m15 = lay_du_lieu_mt5(mau_tien, mt5.TIMEFRAME_M15, 100, 900)  # 15 phút

    # Kiểm tra và in thông tin
    if df_h4 is not None:
        logging.info(f"Dữ liệu H4: {len(df_h4)} nến")
        print("Dữ liệu H4 (5 dòng cuối):")
        print(df_h4.tail())
    if df_m15 is not None:
        logging.info(f"Dữ liệu M15: {len(df_m15)} nến")
        print("Dữ liệu M15 (5 dòng cuối):")
        print(df_m15.tail())

    mt5.shutdown()
    logging.info("Ngắt kết nối MT5")


if __name__ == "__main__":
    main()