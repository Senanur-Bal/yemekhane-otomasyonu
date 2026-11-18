import os

import pymysql
from pymysql.cursors import DictCursor


def menu_doluluklerini_getir():
    baglanti = pymysql.connect(
        host=os.getenv("DB_OKUMA_HOST", "mysql-replica"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_KULLANICI", "yemekhane_app"),
        password=os.getenv("DB_SIFRE", ""),
        database=os.getenv("DB_ADI", "yemekhane"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        autocommit=True,
    )

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    menu_id,
                    DATE_FORMAT(tarih, '%%Y-%%m-%%d') AS tarih,
                    yemekhane_id,
                    yemekhane,
                    ogun_id,
                    ogun,
                    kapasite,
                    rezerve,
                    bos_yer,
                    doluluk_yuzde,
                    DATE_FORMAT(rezervasyon_son, '%%Y-%%m-%%d %%H:%%i:%%s')
                        AS rezervasyon_son
                FROM v_menu_doluluk
                ORDER BY tarih, ogun_id, yemekhane_id
                LIMIT 100
            """)
            menuler = imlec.fetchall()

        for menu in menuler:
            menu["doluluk_yuzde"] = float(menu["doluluk_yuzde"])

        return menuler
    finally:
        baglanti.close()