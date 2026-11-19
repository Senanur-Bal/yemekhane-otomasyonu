import json
import os
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import bcrypt
import redis
from flask import Flask, jsonify, request, session
from flask_session import Session

from veri import (
    alerjen_seceneklerini_getir,
    bakiye_yukle,
    kullanici_alerjen_secimlerini_getir,
    kullanici_alerjen_secimlerini_kaydet,
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

redis_oturum = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    db=int(os.getenv("REDIS_DB", "0")),
)

app.config.update(
    SESSION_TYPE="redis",
    SESSION_REDIS=redis_oturum,
    SESSION_KEY_PREFIX="oturum:",
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

Session(app)
app.logger.setLevel("INFO")

ISTANBUL = ZoneInfo("Europe/Istanbul")
MENU_CACHE_SURUM_ANAHTARI = "menu:cache_version"
MENU_CACHE_SURUMU = "2"


def menu_onbellek_anahtari(yemekhane_id, tarih, ogun_id):
    return f"menu:{yemekhane_id}:{tarih}:{ogun_id}"


def menu_onbellek_suresi(tarih):
    simdi = datetime.now(ISTANBUL)
    menu_gunu = date.fromisoformat(str(tarih))
    gun_sonu = datetime.combine(
        menu_gunu + timedelta(days=1),
        datetime_time.min,
        tzinfo=ISTANBUL,
    )
    return max(0, int((gun_sonu - simdi).total_seconds()))


def menu_liste_onbellek_anahtari():
    bugun = datetime.now(ISTANBUL).date().isoformat()
    return f"menu:liste:{bugun}"


def eski_menu_onbelleklerini_temizle():
    """
    Eski menü önbelleği yapısını ilk istekte Redis'ten temizler.
    oturum:* anahtarlarına dokunmaz.
    """
    try:
        surum = redis_oturum.get(MENU_CACHE_SURUM_ANAHTARI)

        if isinstance(surum, bytes):
            surum = surum.decode("utf-8")

        if surum == MENU_CACHE_SURUMU:
            return

        anahtarlar = list(redis_oturum.scan_iter(match="menu:*"))
        korunacak = MENU_CACHE_SURUM_ANAHTARI.encode("utf-8")
        eski_anahtarlar = [
            anahtar
            for anahtar in anahtarlar
            if anahtar != korunacak
        ]

        if eski_anahtarlar:
            redis_oturum.delete(*eski_anahtarlar)

        redis_oturum.set(
            MENU_CACHE_SURUM_ANAHTARI,
            MENU_CACHE_SURUMU,
        )
        app.logger.info(
            "MENU_CACHE eski menü kayıtları temizlendi; "
            "önbellek sürümü %s etkin.",
            MENU_CACHE_SURUMU,
        )
    except Exception:
        app.logger.exception("Eski menü önbelleği temizlenemedi.")


def redis_json_oku(anahtar):
    icerik = redis_oturum.get(anahtar)

    if icerik is None:
        return None

    return json.loads(icerik)


def redis_json_yaz(anahtar, veri, saniye):
    if saniye > 0:
        redis_oturum.set(
            anahtar,
            json.dumps(veri, ensure_ascii=False),
            ex=saniye,
        )


def menu_onbellek_temizle(
    yemekhane_id=None,
    tarih=None,
    ogun_id=None,
    menu_id=None,
):
    silinecek_anahtarlar = [menu_liste_onbellek_anahtari()]

    if (
        yemekhane_id is not None
        and tarih is not None
        and ogun_id is not None
    ):
        silinecek_anahtarlar.append(
            menu_onbellek_anahtari(
                yemekhane_id,
                tarih,
                ogun_id,
            )
        )

    if menu_id is not None:
        silinecek_anahtarlar.append(f"menu:id:{menu_id}")

    try:
        redis_oturum.delete(*silinecek_anahtarlar)
    except Exception:
        app.logger.exception("Menü önbelleği temizlenemedi.")


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
    eski_menu_onbelleklerini_temizle()
    liste_anahtari = menu_liste_onbellek_anahtari()

    try:
        onbellek = redis_json_oku(liste_anahtari)

        if onbellek is not None:
            app.logger.info("MENU_CACHE HIT: %s", liste_anahtari)
            return jsonify({"menuler": onbellek})
    except Exception:
        app.logger.exception("Menü önbelleği okunamadı.")

    try:
        menuler = menu_doluluklerini_getir()
    except Exception:
        app.logger.exception("Menü dolulukları okunamadı.")
        return jsonify({
            "hata": "Menüler şu anda alınamıyor.",
        }), 503

    try:
        for menu in menuler:
            anahtar = menu_onbellek_anahtari(
                menu["yemekhane_id"],
                menu["tarih"],
                menu["ogun_id"],
            )
            sure = menu_onbellek_suresi(menu["tarih"])

            if sure > 0:
                redis_json_yaz(anahtar, {"liste": menu}, sure)
                redis_oturum.set(
                    f"menu:id:{menu['menu_id']}",
                    anahtar,
                    ex=sure,
                )

        bugun = datetime.now(ISTANBUL).date().isoformat()
        liste_suresi = menu_onbellek_suresi(bugun)
        redis_json_yaz(liste_anahtari, menuler, liste_suresi)
        app.logger.info(
            "MENU_CACHE MISS: menüler mysql-replica üzerinden okundu."
        )
    except Exception:
        app.logger.exception("Menü önbelleğine yazılamadı.")

    return jsonify({"menuler": menuler})


@app.get("/api/menuler/<int:menu_id>")
def menu_detayi(menu_id):
    eski_menu_onbelleklerini_temizle()
    id_anahtari = f"menu:id:{menu_id}"
    menu_anahtari = None

    try:
        menu_anahtari = redis_oturum.get(id_anahtari)

        if isinstance(menu_anahtari, bytes):
            menu_anahtari = menu_anahtari.decode("utf-8")

        if menu_anahtari:
            onbellek = redis_json_oku(menu_anahtari)

            if onbellek and onbellek.get("detay") is not None:
                app.logger.info("MENU_CACHE HIT: %s", menu_anahtari)
                return jsonify(onbellek["detay"])
    except Exception:
        app.logger.exception("Menü ayrıntısı önbelleği okunamadı.")

    try:
        yemekler = menu_detayini_getir(menu_id)

        if not yemekler:
            return jsonify({
                "hata": "Menü bulunamadı.",
            }), 404

        ilk_yemek = yemekler[0]
        menu = {
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
        }
        yanit = {
            "menu": menu,
            "yemekler": yemekler,
        }

        menu_anahtari = menu_onbellek_anahtari(
            ilk_yemek["yemekhane_id"],
            ilk_yemek["tarih"],
            ilk_yemek["ogun_id"],
        )

        try:
            sure = menu_onbellek_suresi(ilk_yemek["tarih"])
            onbellek = redis_json_oku(menu_anahtari) or {}
            onbellek["detay"] = yanit
            redis_json_yaz(menu_anahtari, onbellek, sure)

            if sure > 0:
                redis_oturum.set(
                    id_anahtari,
                    menu_anahtari,
                    ex=sure,
                )

            app.logger.info(
                "MENU_CACHE MISS: menu_id=%s mysql-replica üzerinden okundu.",
                menu_id,
            )
        except Exception:
            app.logger.exception("Menü ayrıntısı önbelleğe yazılamadı.")

        return jsonify(yanit)
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
    session.permanent = True
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


@app.get("/api/profil/alerjenler")
def profil_alerjenlerini_getir():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Alerjen tercihlerinizi görmek için giriş yapmalısınız.",
        }), 401

    try:
        return jsonify({
            "alerjenler": alerjen_seceneklerini_getir(),
            "secilen_alerjenler": kullanici_alerjen_secimlerini_getir(
                kullanici["id"]
            ),
        })
    except Exception:
        app.logger.exception("Profil alerjenleri okunamadı.")
        return jsonify({
            "hata": "Alerjen tercihleri şu anda alınamıyor.",
        }), 503


@app.put("/api/profil/alerjenler")
def profil_alerjenlerini_guncelle():
    kullanici = session.get("kullanici")

    if not kullanici:
        return jsonify({
            "hata": "Alerjen tercihlerinizi kaydetmek için giriş yapmalısınız.",
        }), 401

    veri = request.get_json(silent=True)

    if not isinstance(veri, dict):
        return jsonify({
            "hata": "Alerjen tercihleri geçersiz.",
        }), 400

    alerjen_idleri = veri.get("alerjen_idleri")

    if not isinstance(alerjen_idleri, list):
        return jsonify({
            "hata": "Alerjen seçimleri liste olmalıdır.",
        }), 400

    if any(isinstance(deger, bool) for deger in alerjen_idleri):
        return jsonify({
            "hata": "Geçersiz alerjen seçimi.",
        }), 400

    try:
        secilen_idler = kullanici_alerjen_secimlerini_kaydet(
            kullanici["id"],
            alerjen_idleri,
        )
        return jsonify({
            "ok": True,
            "mesaj": "Alerjen tercihleriniz kaydedildi.",
            "secilen_alerjen_idleri": secilen_idler,
        })
    except ValueError as hata:
        return jsonify({"hata": str(hata)}), 400
    except Exception:
        app.logger.exception("Profil alerjenleri kaydedilemedi.")
        return jsonify({
            "hata": "Alerjen tercihleri kaydedilemedi.",
        }), 400


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

    porsiyon = veri.get("porsiyon", "tam")

    if porsiyon not in ("tam", "yarim"):
        return jsonify({
            "hata": "Tam veya yarım porsiyon seçmelisiniz.",
        }), 400

    try:
        sonuc = rezervasyon_yap(
            kullanici["id"],
            menu_id,
            porsiyon,
        )
        menu_onbellek_temizle()

        return jsonify({
            "ok": True,
            "mesaj": "Rezervasyon oluşturuldu.",
            "rezervasyon": sonuc,
        }), 201
    except Exception:
        app.logger.exception("Rezervasyon oluşturulamadı.")
        return jsonify({
            "hata": (
                "Rezervasyon yapılamadı. Porsiyon, bakiye, kapasite ve "
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

        menu_onbellek_temizle()

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

        menu_onbellek_temizle(
            yemekhane_id,
            tarih,
            ogun_id,
            sonuc.get("menu_id"),
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