import os
from datetime import date
from decimal import Decimal, InvalidOperation

import bcrypt
from flask import Flask, jsonify, request, session

from veri import (
    bakiye_yukle,
    kullanici_bakiye_ve_hareketleri_getir,
    kullanici_degerlendirme_menuleri_getir,
    kullanici_eposta_ile_getir,
    kullanici_rezervasyonlarini_getir,
    menu_degerlendir,
    menu_detayini_getir,
    menu_doluluklerini_getir,
    rezervasyon_iptal_et,
    rezervasyon_yap,
    yonetici_form_verilerini_getir,
    yonetici_menu_olustur,
    yonetici_raporlarini_getir,
)

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "yerel-gelistirme-anahtari-degistir",
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def yonetici_hata_yaniti():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Bu işlem için giriş yapmalısınız."
        }), 401

    if kullanici.get("rol") != "yonetici":
        return jsonify({
            "hata": "Bu işlem yalnızca yöneticilere açıktır."
        }), 403

    return None


@app.get("/api/")
def ana_sayfa():
    return jsonify({
        "ok": True,
        "mesaj": "Yemekhane Otomasyonu - Flask uygulaması çalışıyor.",
    })


@app.get("/api/menuler")
def menu_dolulukleri():
    try:
        return jsonify({
            "menuler": menu_doluluklerini_getir(),
        })
    except Exception:
        app.logger.exception("Menü dolulukları okunamadı.")
        return jsonify({
            "hata": "Menüler şu anda alınamıyor.",
        }), 503


@app.get("/api/menuler/<int:menu_id>")
def menu_detayi(menu_id):
    try:
        yemekler = menu_detayini_getir(menu_id)

        if not yemekler:
            return jsonify({
                "hata": "Menü bulunamadı.",
            }), 404

        ilk_yemek = yemekler[0]

        return jsonify({
            "menu": {
                "id": menu_id,
                "tarih": ilk_yemek["tarih"],
                "yemekhane_id": ilk_yemek["yemekhane_id"],
                "yemekhane": ilk_yemek["yemekhane"],
                "ogun_id": ilk_yemek["ogun_id"],
                "ogun": ilk_yemek["ogun"],
                "rezervasyon_son": ilk_yemek["rezervasyon_son"],
                "ogrenci_fiyati": ilk_yemek["ogrenci_fiyati"],
                "personel_fiyati": ilk_yemek["personel_fiyati"],
                "toplam_kalori": sum(
                    yemek["kalori"] for yemek in yemekler
                ),
            },
            "yemekler": yemekler,
        })
    except Exception:
        app.logger.exception("Menü ayrıntısı okunamadı.")
        return jsonify({
            "hata": "Menü ayrıntısı şu anda alınamıyor.",
        }), 503


@app.post("/api/giris")
def giris():
    gelen = request.get_json(silent=True) or request.form
    eposta = (gelen.get("eposta") or "").strip().lower()
    sifre = gelen.get("sifre") or ""

    if not eposta or not sifre:
        return jsonify({
            "hata": "E-posta ve şifre zorunludur.",
        }), 400

    try:
        kullanici = kullanici_eposta_ile_getir(eposta)
    except Exception:
        app.logger.exception("Kullanıcı bilgisi okunamadı.")
        return jsonify({
            "hata": "Giriş şu anda yapılamıyor.",
        }), 503

    if not kullanici or not kullanici["aktif"]:
        return jsonify({
            "hata": "E-posta veya şifre hatalı.",
        }), 401

    try:
        sifre_dogru = bcrypt.checkpw(
            sifre.encode("utf-8"),
            kullanici["sifre_hash"].encode("utf-8"),
        )
    except (ValueError, TypeError):
        sifre_dogru = False

    if not sifre_dogru:
        return jsonify({
            "hata": "E-posta veya şifre hatalı.",
        }), 401

    session.clear()
    session["kullanici"] = {
        "id": kullanici["id"],
        "ad": kullanici["ad"],
        "soyad": kullanici["soyad"],
        "eposta": kullanici["eposta"],
        "rol": kullanici["rol"],
    }

    return jsonify({
        "ok": True,
        "kullanici": session["kullanici"],
    })


@app.get("/api/oturum")
def oturum():
    return jsonify({
        "oturum_acik": "kullanici" in session,
        "kullanici": session.get("kullanici"),
    })


@app.get("/api/bakiye")
def bakiye_ve_hareketler():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Bakiyeyi görmek için giriş yapmalısınız.",
        }), 401

    try:
        sonuc = kullanici_bakiye_ve_hareketleri_getir(
            kullanici["id"]
        )

        if sonuc is None:
            return jsonify({
                "hata": "Kullanıcı bulunamadı.",
            }), 404

        return jsonify(sonuc)
    except Exception:
        app.logger.exception("Bakiye ve hareketler okunamadı.")
        return jsonify({
            "hata": "Bakiye bilgisi şu anda alınamıyor.",
        }), 503


@app.post("/api/bakiye/yukle")
def bakiye_yukle_api():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Bakiye yüklemek için giriş yapmalısınız.",
        }), 401

    veri = request.get_json(silent=True) or {}

    if not isinstance(veri, dict):
        return jsonify({
            "hata": "Geçerli bir yükleme tutarı gönderin.",
        }), 400

    try:
        tutar = Decimal(str(veri.get("tutar", "")))

        if not tutar.is_finite() or tutar < 10 or tutar > 1000:
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({
            "hata": "Yükleme tutarı 10 ile 1000 TL arasında olmalıdır.",
        }), 400

    try:
        sonuc = bakiye_yukle(kullanici["id"], tutar)

        if sonuc and sonuc.get("bakiye") is not None:
            sonuc["bakiye"] = float(sonuc["bakiye"])

        return jsonify({
            "ok": True,
            "mesaj": "Bakiye yüklendi.",
            "sonuc": sonuc,
        }), 201
    except Exception:
        app.logger.exception("Bakiye yüklenemedi.")
        return jsonify({
            "hata": "Bakiye yüklenemedi.",
        }), 400


@app.get("/api/degerlendirmelerim")
def degerlendirme_menulerim():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Değerlendirmeler için giriş yapmalısınız.",
        }), 401

    try:
        menuler = kullanici_degerlendirme_menuleri_getir(
            kullanici["id"]
        )
        return jsonify({"menuler": menuler})
    except Exception:
        app.logger.exception("Değerlendirme menüleri okunamadı.")
        return jsonify({
            "hata": "Değerlendirme menüleri şu anda alınamıyor.",
        }), 503


@app.post("/api/degerlendirmeler")
def degerlendirme_ekle():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Değerlendirme yapmak için giriş yapmalısınız.",
        }), 401

    veri = request.get_json(silent=True) or {}

    if not isinstance(veri, dict):
        return jsonify({
            "hata": "Geçerli değerlendirme bilgisi gönderin.",
        }), 400

    try:
        menu_id = int(veri.get("menu_id"))
        ham_puan = veri.get("puan")

        if isinstance(ham_puan, bool):
            raise ValueError

        puan = int(ham_puan)

        if menu_id <= 0 or puan < 1 or puan > 5:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "hata": "Menü seçin ve 1 ile 5 arasında puan verin.",
        }), 400

    yorum = veri.get("yorum", "")

    if yorum is None:
        yorum = ""

    if not isinstance(yorum, str):
        return jsonify({
            "hata": "Yorum metin olmalıdır.",
        }), 400

    yorum = yorum.strip()

    if len(yorum) > 500:
        return jsonify({
            "hata": "Yorum en fazla 500 karakter olabilir.",
        }), 400

    try:
        sonuc = menu_degerlendir(
            kullanici["id"],
            menu_id,
            puan,
            yorum or None,
        )

        return jsonify({
            "ok": True,
            "mesaj": "Değerlendirmeniz kaydedildi.",
            "degerlendirme": sonuc,
        }), 201
    except ValueError as hata:
        return jsonify({"hata": str(hata)}), 400
    except Exception:
        app.logger.exception("Değerlendirme kaydedilemedi.")
        return jsonify({
            "hata": "Değerlendirme kaydedilemedi.",
        }), 400


@app.post("/api/rezervasyonlar")
def rezervasyon_olustur():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Rezervasyon için giriş yapmalısınız.",
        }), 401

    veri = request.get_json(silent=True) or {}

    if not isinstance(veri, dict):
        return jsonify({
            "hata": "Geçerli bir menü seçmelisiniz.",
        }), 400

    try:
        menu_id = int(veri.get("menu_id"))

        if menu_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "hata": "Geçerli bir menü seçmelisiniz.",
        }), 400

    try:
        sonuc = rezervasyon_yap(kullanici["id"], menu_id)

        return jsonify({
            "ok": True,
            "mesaj": "Rezervasyon oluşturuldu.",
            "rezervasyon": sonuc,
        }), 201
    except Exception:
        app.logger.exception("Rezervasyon oluşturulamadı.")
        return jsonify({
            "hata": (
                "Rezervasyon yapılamadı. Bakiye, kapasite ve "
                "rezervasyon süresini kontrol edin."
            ),
        }), 400


@app.get("/api/rezervasyonlar")
def rezervasyonlarimi_getir():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Rezervasyonlarınızı görmek için giriş yapmalısınız.",
        }), 401

    try:
        rezervasyonlar = kullanici_rezervasyonlarini_getir(
            kullanici["id"]
        )

        for rezervasyon in rezervasyonlar:
            rezervasyon["ucret"] = float(rezervasyon["ucret"])

        return jsonify({
            "rezervasyonlar": rezervasyonlar,
        })
    except Exception:
        app.logger.exception("Rezervasyonlar okunamadı.")
        return jsonify({
            "hata": "Rezervasyonlar şu anda alınamıyor.",
        }), 503


@app.delete("/api/rezervasyonlar/<int:rezervasyon_id>")
def rezervasyon_iptal(rezervasyon_id):
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Rezervasyonu iptal etmek için giriş yapmalısınız.",
        }), 401

    try:
        sonuc = rezervasyon_iptal_et(
            kullanici["id"],
            rezervasyon_id,
        )

        if sonuc:
            for alan in ("iade", "bakiye"):
                if sonuc.get(alan) is not None:
                    sonuc[alan] = float(sonuc[alan])

        return jsonify({
            "ok": True,
            "mesaj": "Rezervasyon iptal edildi.",
            "sonuc": sonuc,
        })
    except Exception:
        app.logger.exception("Rezervasyon iptal edilemedi.")
        return jsonify({
            "hata": (
                "Rezervasyon iptal edilemedi. "
                "İptal süresi dolmuş olabilir."
            ),
        }), 400


@app.get("/api/yonetici/raporlar")
def yonetici_raporlari():
    hata_yaniti = yonetici_hata_yaniti()

    if hata_yaniti:
        return hata_yaniti

    try:
        return jsonify({
            "raporlar": yonetici_raporlarini_getir(),
        })
    except Exception:
        app.logger.exception("Yönetici raporları alınamadı.")
        return jsonify({
            "hata": "Raporlar şu anda alınamıyor.",
        }), 503


@app.get("/api/yonetici/form-verileri")
def yonetici_form_verileri():
    hata_yaniti = yonetici_hata_yaniti()

    if hata_yaniti:
        return hata_yaniti

    try:
        return jsonify(yonetici_form_verilerini_getir())
    except Exception:
        app.logger.exception("Yönetici form seçenekleri alınamadı.")
        return jsonify({
            "hata": "Form seçenekleri şu anda alınamıyor.",
        }), 503


@app.post("/api/yonetici/menuler")
def yonetici_menu_ekle():
    hata_yaniti = yonetici_hata_yaniti()

    if hata_yaniti:
        return hata_yaniti

    veri = request.get_json(silent=True)

    if not isinstance(veri, dict):
        return jsonify({
            "hata": "Menü bilgileri geçersiz.",
        }), 400

    try:
        yemekhane_id = int(veri.get("yemekhane_id"))
        ogun_id = int(veri.get("ogun_id"))
        tarih = veri.get("tarih")
        yemek_idleri = veri.get("yemek_idleri")

        if not isinstance(tarih, str):
            raise ValueError

        date.fromisoformat(tarih)

        if not isinstance(yemek_idleri, list) or not yemek_idleri:
            raise ValueError

        yemek_idleri = list(dict.fromkeys(
            int(yemek_id) for yemek_id in yemek_idleri
        ))

        ogrenci_fiyati = Decimal(str(veri.get("ogrenci_fiyati")))
        personel_fiyati = Decimal(str(veri.get("personel_fiyati")))

        if (
            yemekhane_id <= 0
            or ogun_id <= 0
            or any(yemek_id <= 0 for yemek_id in yemek_idleri)
            or not ogrenci_fiyati.is_finite()
            or not personel_fiyati.is_finite()
            or ogrenci_fiyati < 0
            or personel_fiyati < 0
        ):
            raise ValueError

    except (TypeError, ValueError, InvalidOperation):
        return jsonify({
            "hata": "Tarih, fiyat ve menü seçimlerini kontrol edin.",
        }), 400

    try:
        sonuc = yonetici_menu_olustur(
            yemekhane_id,
            tarih,
            ogun_id,
            ogrenci_fiyati,
            personel_fiyati,
            yemek_idleri,
        )

        return jsonify({
            "ok": True,
            "mesaj": "Menü oluşturuldu.",
            "menu": sonuc,
        }), 201
    except Exception:
        app.logger.exception("Yönetici menü oluşturamadı.")
        return jsonify({
            "hata": (
                "Menü oluşturulamadı. Aynı tarih, yemekhane ve öğün için "
                "zaten menü bulunup bulunmadığını kontrol edin."
            ),
        }), 400


@app.post("/api/cikis")
def cikis():
    session.clear()
    return jsonify({"ok": True})


@app.errorhandler(404)
def bulunamadi(_hata):
    return jsonify({
        "hata": "API adresi bulunamadı.",
    }), 404


@app.errorhandler(500)
def sunucu_hatasi(_hata):
    return jsonify({
        "hata": "Sunucu hatası.",
    }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)