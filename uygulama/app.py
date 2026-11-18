from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/api/")
def ana_sayfa():
    return jsonify({
        "ok": True,
        "mesaj": "Yemekhane Otomasyonu - Flask uygulaması çalışıyor."
    })


@app.errorhandler(404)
def bulunamadi(_hata):
    return jsonify({"hata": "API adresi bulunamadı."}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)