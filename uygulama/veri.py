import os

import pymysql
from pymysql.cursors import DictCursor


def _baglanti_ac(yazma=False, autocommit=True):
    return pymysql.connect(
        host=os.getenv(
            "DB_YAZMA_HOST" if yazma else "DB_OKUMA_HOST",
            "mysql-primary" if yazma else "mysql-replica",
        ),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_KULLANICI", "yemekhane_app"),
        password=os.getenv("DB_SIFRE", ""),
        database=os.getenv("DB_ADI", "yemekhane"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
        autocommit=autocommit,
    )


def menu_doluluklerini_getir():
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    menu_id,
                    DATE_FORMAT(tarih, '%Y-%m-%d') AS tarih,
                    yemekhane_id,
                    yemekhane,
                    ogun_id,
                    ogun,
                    kapasite,
                    rezerve,
                    bos_yer,
                    doluluk_yuzde,
                    DATE_FORMAT(
                        rezervasyon_son,
                        '%Y-%m-%d %H:%i:%s'
                    ) AS rezervasyon_son
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


def menu_detayini_getir(menu_id):
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    menu_id,
                    tarih,
                    yemekhane_id,
                    yemekhane,
                    ogun_id,
                    ogun,
                    ogun_sira,
                    rezervasyon_son,
                    ogrenci_fiyati,
                    personel_fiyati,
                    yemek_id,
                    yemek,
                    kategori_id,
                    kategori,
                    kategori_sira,
                    kalori,
                    vejetaryen,
                    alerjenler,
                    alerjen_idler
                FROM v_menu_detay
                WHERE menu_id = %s
                ORDER BY kategori_sira, yemek
            """, (menu_id,))
            yemekler = imlec.fetchall()

        for yemek in yemekler:
            yemek["tarih"] = yemek["tarih"].isoformat()
            yemek["rezervasyon_son"] = yemek["rezervasyon_son"].strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            yemek["ogrenci_fiyati"] = float(yemek["ogrenci_fiyati"])
            yemek["personel_fiyati"] = float(yemek["personel_fiyati"])
            yemek["vejetaryen"] = bool(yemek["vejetaryen"])
            yemek["alerjenler"] = (
                yemek["alerjenler"].split(", ")
                if yemek["alerjenler"]
                else []
            )
            yemek["alerjen_idler"] = (
                [int(deger) for deger in yemek["alerjen_idler"].split(",")]
                if yemek["alerjen_idler"]
                else []
            )

        return yemekler
    finally:
        baglanti.close()


def kullanici_eposta_ile_getir(eposta):
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    id,
                    ad,
                    soyad,
                    eposta,
                    sifre_hash,
                    rol,
                    bakiye,
                    aktif
                FROM kullanicilar
                WHERE eposta = %s
                LIMIT 1
            """, (eposta,))
            return imlec.fetchone()
    finally:
        baglanti.close()


def rezervasyon_yap(kullanici_id, menu_id):
    baglanti = _baglanti_ac(yazma=True)

    try:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "CALL sp_rezervasyon_yap(%s, %s)",
                (kullanici_id, menu_id),
            )
            return imlec.fetchone()
    finally:
        baglanti.close()


def kullanici_rezervasyonlarini_getir(kullanici_id):
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    r.id AS rezervasyon_id,
                    r.menu_id,
                    r.durum,
                    r.ucret,
                    DATE_FORMAT(m.tarih, '%%Y-%%m-%%d') AS tarih,
                    yh.ad AS yemekhane,
                    o.ad AS ogun,
                    DATE_FORMAT(
                        TIMESTAMP(m.tarih, o.son_saat),
                        '%%Y-%%m-%%d %%H:%%i:%%s'
                    ) AS rezervasyon_son
                FROM rezervasyonlar r
                JOIN menuler m ON m.id = r.menu_id
                JOIN yemekhaneler yh ON yh.id = m.yemekhane_id
                JOIN ogunler o ON o.id = m.ogun_id
                WHERE r.kullanici_id = %s
                ORDER BY m.tarih DESC, o.sira DESC
                LIMIT 100
            """, (kullanici_id,))
            return imlec.fetchall()
    finally:
        baglanti.close()


def rezervasyon_iptal_et(kullanici_id, rezervasyon_id):
    baglanti = _baglanti_ac(yazma=True)

    try:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "CALL sp_rezervasyon_iptal(%s, %s)",
                (kullanici_id, rezervasyon_id),
            )
            return imlec.fetchone()
    finally:
        baglanti.close()


def kullanici_bakiye_ve_hareketleri_getir(kullanici_id):
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT bakiye
                FROM kullanicilar
                WHERE id = %s
                LIMIT 1
            """, (kullanici_id,))
            kullanici = imlec.fetchone()

            if not kullanici:
                return None

            imlec.execute("""
                SELECT
                    tur,
                    tutar,
                    rezervasyon_id,
                    aciklama,
                    DATE_FORMAT(
                        olusturma,
                        '%%Y-%%m-%%d %%H:%%i:%%s'
                    ) AS olusturma
                FROM bakiye_hareketleri
                WHERE kullanici_id = %s
                ORDER BY id DESC
                LIMIT 100
            """, (kullanici_id,))
            hareketler = imlec.fetchall()

        return {
            "bakiye": float(kullanici["bakiye"]),
            "hareketler": [
                {
                    **hareket,
                    "tutar": float(hareket["tutar"]),
                }
                for hareket in hareketler
            ],
        }
    finally:
        baglanti.close()


def bakiye_yukle(kullanici_id, tutar):
    baglanti = _baglanti_ac(yazma=True)

    try:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "CALL sp_bakiye_yukle(%s, %s)",
                (kullanici_id, tutar),
            )
            return imlec.fetchone()
    finally:
        baglanti.close()


def menu_degerlendir(kullanici_id, menu_id, puan, yorum):
    baglanti = _baglanti_ac(yazma=True)

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT id
                FROM rezervasyonlar
                WHERE kullanici_id = %s
                  AND menu_id = %s
                  AND durum = 'kullanildi'
                LIMIT 1
            """, (kullanici_id, menu_id))

            if not imlec.fetchone():
                raise ValueError(
                    "Yalnızca kullandığınız menüyü değerlendirebilirsiniz."
                )

            imlec.execute("""
                INSERT INTO degerlendirmeler
                    (kullanici_id, menu_id, puan, yorum)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    puan = VALUES(puan),
                    yorum = VALUES(yorum)
            """, (kullanici_id, menu_id, puan, yorum))

            return {
                "menu_id": menu_id,
                "puan": puan,
                "yorum": yorum,
            }
    finally:
        baglanti.close()


def kullanici_degerlendirme_menuleri_getir(kullanici_id):
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    m.id AS menu_id,
                    DATE_FORMAT(m.tarih, '%%Y-%%m-%%d') AS tarih,
                    yh.ad AS yemekhane,
                    o.ad AS ogun,
                    d.puan,
                    d.yorum
                FROM rezervasyonlar r
                JOIN menuler m ON m.id = r.menu_id
                JOIN yemekhaneler yh ON yh.id = m.yemekhane_id
                JOIN ogunler o ON o.id = m.ogun_id
                LEFT JOIN degerlendirmeler d
                    ON d.menu_id = m.id
                   AND d.kullanici_id = r.kullanici_id
                WHERE r.kullanici_id = %s
                  AND r.durum = 'kullanildi'
                ORDER BY m.tarih DESC, o.sira DESC
                LIMIT 100
            """, (kullanici_id,))
            return imlec.fetchall()
    finally:
        baglanti.close()


def yonetici_raporlarini_getir():
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT
                    d.menu_id,
                    DATE_FORMAT(d.tarih, '%Y-%m-%d') AS tarih,
                    d.yemekhane,
                    d.ogun,
                    d.kapasite,
                    d.rezerve,
                    d.bos_yer,
                    d.doluluk_yuzde,
                    p.oy_sayisi,
                    p.ortalama_puan
                FROM v_menu_doluluk d
                JOIN v_menu_puan p ON p.menu_id = d.menu_id
                ORDER BY d.tarih DESC, d.ogun_id, d.yemekhane_id
                LIMIT 100
            """)
            raporlar = imlec.fetchall()

        for rapor in raporlar:
            rapor["doluluk_yuzde"] = float(rapor["doluluk_yuzde"])
            if rapor["ortalama_puan"] is not None:
                rapor["ortalama_puan"] = float(rapor["ortalama_puan"])

        return raporlar
    finally:
        baglanti.close()


def yonetici_form_verilerini_getir():
    baglanti = _baglanti_ac()

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                SELECT id, ad
                FROM yemekhaneler
                ORDER BY ad
            """)
            yemekhaneler = imlec.fetchall()

            imlec.execute("""
                SELECT id, ad
                FROM ogunler
                ORDER BY sira
            """)
            ogunler = imlec.fetchall()

            imlec.execute("""
                SELECT
                    y.id,
                    y.ad,
                    y.kategori_id,
                    k.ad AS kategori,
                    y.kalori,
                    y.vejetaryen
                FROM yemekler y
                JOIN yemek_kategorileri k ON k.id = y.kategori_id
                ORDER BY k.sira, y.ad
            """)
            yemekler = imlec.fetchall()

        for yemek in yemekler:
            yemek["vejetaryen"] = bool(yemek["vejetaryen"])

        return {
            "yemekhaneler": yemekhaneler,
            "ogunler": ogunler,
            "yemekler": yemekler,
        }
    finally:
        baglanti.close()


def yonetici_menu_olustur(
    yemekhane_id,
    tarih,
    ogun_id,
    ogrenci_fiyati,
    personel_fiyati,
    yemek_idleri,
):
    if not yemek_idleri:
        raise ValueError("Menüye en az bir yemek eklemelisiniz.")

    baglanti = _baglanti_ac(yazma=True, autocommit=False)

    try:
        with baglanti.cursor() as imlec:
            imlec.execute("""
                INSERT INTO menuler (
                    yemekhane_id,
                    tarih,
                    ogun_id,
                    ogrenci_fiyati,
                    personel_fiyati
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                yemekhane_id,
                tarih,
                ogun_id,
                ogrenci_fiyati,
                personel_fiyati,
            ))

            menu_id = imlec.lastrowid

            imlec.executemany("""
                INSERT INTO menu_yemekleri (menu_id, yemek_id)
                VALUES (%s, %s)
            """, [
                (menu_id, yemek_id)
                for yemek_id in yemek_idleri
            ])

        baglanti.commit()
        return {"menu_id": menu_id}
    except Exception:
        baglanti.rollback()
        raise
    finally:
        baglanti.close()