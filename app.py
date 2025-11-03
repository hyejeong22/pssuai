# -*- coding: utf-8 -*-
import os, json, datetime, traceback
from functools import wraps
import requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, make_response
)

from db_config import get_connection
from dotenv import load_dotenv

load_dotenv()


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-.env")
app.config.update(
    SESSION_COOKIE_NAME="pssuai_admin",
    JSON_AS_ASCII=False,
)

REMOTE_BASE   = os.getenv("REMOTE_BASE", "http://api.pssuai.com").rstrip("/")
REMOTE_ACCESS = f"{REMOTE_BASE}/access-events"
REMOTE_QR     = f"{REMOTE_BASE}/qr-events"
REMOTE_RESIDENTS = f"{REMOTE_BASE}/residents"
REMOTE_RESIDENTS_FALLBACK = f"{REMOTE_BASE}/registrations?status=approved"


def _normalize_charset(value: str) -> str:
    if not value:
        return "application/json; charset=utf-8"
    v = value.strip()
    low = v.lower()
    if "application/json" in low and "charset" not in low:
        return "application/json; charset=utf-8"
    # 다양한 표기 보정: UTF8, UTF-8, Utf-8 등 → utf-8
    v = v.replace("UTF8", "utf-8").replace("UTF-8", "utf-8").replace("Utf-8", "utf-8")
    return v

def passthrough_response(r):
    """requests.Response -> Flask Response (청크/인코딩 헤더 제거, utf-8 고정)"""
    body = r.content  # 전부 다 받은 뒤 전달
    resp = make_response(body, r.status_code)

    # 원격 헤더 중 브라우저가 싫어하는 것들은 제외
    skip = {"transfer-encoding", "content-encoding", "content-length", "connection"}
    for k, v in r.headers.items():
        kl = k.lower()
        if kl in skip:
            continue
        if kl == "content-type":
            # charset 보정
            lv = v.lower()
            if "application/json" in lv and "charset" not in lv:
                v = "application/json; charset=utf-8"
        resp.headers[k] = v

    # content-type이 없으면 기본 JSON로
    if not any(h.lower() == "content-type" for h in resp.headers.keys()):
        resp.headers["Content-Type"] = "application/json; charset=utf-8"

    # 길이는 우리가 다시 계산
    resp.headers["Content-Length"] = str(len(body))
    return resp
# ─────────────────────────────────────────
# 간단 로그인 (환경변수로 계정 관리)
# ─────────────────────────────────────────
ADMIN_ID  = os.getenv("ADMIN_ID", "admin")
ADMIN_PW  = os.getenv("ADMIN_PW", "admin1234")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uid = request.form.get("username", "").strip()
        pw  = request.form.get("password", "").strip()
        if uid == ADMIN_ID and pw == ADMIN_PW:
            session["admin"] = {"id": uid, "login_at": datetime.datetime.utcnow().isoformat()}
            return redirect(url_for("admin"))
        return render_template("login.html", error="아이디 또는 비밀번호가 올바르지 않습니다.")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────
# 대시보드
# ─────────────────────────────────────────
@app.route("/")
@login_required
def admin():
    return render_template("admin.html")

# ─────────────────────────────────────────
# 프록시 API (프론트에서 호출)
#  - 외부 데이터를 그대로 전달 + (옵션) MySQL에 동기 저장
# ─────────────────────────────────────────
def fetch_remote(url, timeout=20):
    try:
        r = requests.get(url, timeout=timeout)
        text = r.text or ""
        
        if r.ok:
            try:
                data = r.json()
            except Exception:
                data = json.loads(text)

            # --- 🌟 이 부분이 수정됩니다 🌟 ---
            rows = data
            if isinstance(data, dict):
                if "rows" in data:
                    rows = data["rows"]
                elif "qr_events" in data: # 👈 추가: qr_events 키를 처리
                    rows = data["qr_events"]
                elif "access_events" in data: # 👈 추가: access_events 키를 처리
                    rows = data["access_events"]

            if not isinstance(rows, list):
                # 의도치 않은 포맷 방어 (여전히 리스트가 아니면 에러 반환)
                return {"_error": True, "_status": r.status_code, "_body": f"Unexpected JSON shape: {type(data)}"}
            
            return rows  # ✅ 항상 list 반환
            # --- 🌟 수정 끝 🌟 ---
        else:
            return {"_error": True, "_status": r.status_code, "_body": text[:2000]}
    except Exception as e:
        return {"_error": True, "_status": "EXC", "_body": str(e)[:2000]}

# ────────────────────────────────────────────────
# 📦 Access Events (세대주 출입기록)
# ────────────────────────────────────────────────
@app.route("/api/access-events", methods=["GET"])
@login_required
def api_access_events():
    try:
        data = fetch_remote(REMOTE_ACCESS)

        # 원격 에러면 DB 폴백
        if isinstance(data, dict) and data.get("_error"):
            fallback = []
            try:
                fallback = get_recent_from_mysql("access_events", 500)
            except Exception:
                pass

            return jsonify({
                "ok": False,
                "error": f"access-events remote failed ({data.get('_status')}): "
                         f"{data.get('_body')[:300]}",
                "rows": fallback  # 폴백 데이터(있으면 표시는 됨)
            }), 502

        # 정상 응답
        if os.getenv("SYNC_TO_DB", "false").lower() == "true":
            sync_to_mysql("access_events", data)

        return jsonify({"ok": True, "rows": data})

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"access-events fetch failed: {e}",
            "rows": []
        }), 500


# ────────────────────────────────────────────────
# 📦 QR Events (방문자 QR 출입기록)
# ────────────────────────────────────────────────
@app.route("/api/qr-events", methods=["GET"])
@login_required
def api_qr_events():
    try:
        data = fetch_remote(REMOTE_QR)

        if isinstance(data, dict) and data.get("_error"):
            fallback = []
            try:
                fallback = get_recent_from_mysql("qr_events", 500)
            except Exception:
                pass

            return jsonify({
                "ok": False,
                "error": f"qr-events remote failed ({data.get('_status')}): "
                         f"{data.get('_body')[:300]}",
                "rows": fallback
            }), 502

        if os.getenv("SYNC_TO_DB", "false").lower() == "true":
            sync_to_mysql("qr_events", data)

        return jsonify({"ok": True, "rows": data})

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"qr-events fetch failed: {e}",
            "rows": []
        }), 500

@app.route("/external/residents", methods=["GET"])
@login_required
def external_residents_list():
    try:
        UA = {"User-Agent": "pssuai-admin/1.0"}
        # /residents 없으면 /registrations?status=approved 로 폴백
        for url in [f"{REMOTE_BASE}/residents",
                    f"{REMOTE_BASE}/registrations?status=approved"]:
            r = requests.get(url, timeout=30, headers=UA)
            app.logger.info(f"[residents-list] {url} -> {r.status_code}")
            if r.status_code != 404:
                return passthrough_response(r)
        return passthrough_response(r)  # 마지막 404라도 그대로 전달
    except Exception as e:
        app.logger.exception("external_residents_list error")
        return jsonify({"ok": False, "proxy": True, "error": str(e)}), 502


def remote_delete_resident(resident_id: int):
    # 필요에 따라 아래 경로를 /registrations/<id> 로 바꾸세요.
    url = f"{REMOTE_BASE}/residents/{resident_id}"
    try:
        r = requests.delete(url, timeout=15)
        # 200/204면 성공. 404는 '이미 삭제'로 간주해도 무방
        return r.status_code in (200, 204, 404), r.status_code
    except Exception as e:
        return False, str(e)
    
 # ─────────────────────────────────────────
# ✨ 원격 삭제 함수 (residents → 없으면 registrations도 시도)
# ─────────────────────────────────────────
def remote_delete_resident(resident_id: int):
    base = REMOTE_BASE  # http://api.pssuai.com (현재 환경)
    for path in (f"/residents/{resident_id}", f"/registrations/{resident_id}"):
        url = f"{base}{path}"
        try:
            r = requests.delete(url, timeout=15)
            if r.status_code in (200, 204):             # 성공
                return True, {"path": path, "status": r.status_code}
            if r.status_code == 404:                     # 없음 → 다음 후보 시도
                continue
            return False, {"path": path, "status": r.status_code, "body": r.text[:200]}
        except Exception as e:
            # 네트워크 예외 발생 → 다음 후보 시도
            continue
    # 둘 다 실패(또는 둘 다 404)
    return False, {"status": "not_found_both"}

# ─────────────────────────────────────────
# ✨ 삭제 라우트
# ─────────────────────────────────────────
@app.route("/admin/residents/<int:rid>", methods=["DELETE", "OPTIONS"], endpoint="admin_delete_resident")
@login_required
def admin_delete_resident(rid):
    if request.method == "OPTIONS":
        return ("", 204)

    remote_ok, remote_info = remote_delete_resident(rid)

    affected = 0
    try:
        conn = get_connection(); cur = conn.cursor()
        cur.execute("DELETE FROM residents WHERE id=%s", (rid,))
        affected = cur.rowcount
        conn.commit()
    except Exception as e:
        return jsonify(ok=False, remote_ok=remote_ok, error=str(e)), 500
    finally:
        try: cur.close(); conn.close()
        except: pass

    # 로컬에 없어도 성공 처리
    return jsonify(ok=True, remote_ok=remote_ok, affected=affected, remote_info=remote_info), 200


# MySQL 동기 저장 (선택)
#  - schema.sql에 맞춰 간단 업서트 구현
# ─────────────────────────────────────────
def sync_to_mysql(kind, rows):
    conn = get_connection()
    cur = conn.cursor()

    if kind == "access_events":
        sql = """
        INSERT INTO access_events
        (id, name, phone, unit, device_id, event_time, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          name=VALUES(name),
          phone=VALUES(phone),
          unit=VALUES(unit),
          device_id=VALUES(device_id),
          event_time=VALUES(event_time),
          raw_json=VALUES(raw_json),
          updated_at=CURRENT_TIMESTAMP
        """
        params = []
        for r in rows:
            params.append((
                r.get("id"), r.get("name"), r.get("phone"), r.get("unit"),
                r.get("device_id"), r.get("event_time"),
                json.dumps(r, ensure_ascii=False)
            ))
        if params:
            cur.executemany(sql, params)
            conn.commit()

    elif kind == "qr_events":
        sql = """
        INSERT INTO qr_events
        (id, visitor_name, visitor_phone, host_unit, qr_id, event_time, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          visitor_name=VALUES(visitor_name),
          visitor_phone=VALUES(visitor_phone),
          host_unit=VALUES(host_unit),
          qr_id=VALUES(qr_id),
          event_time=VALUES(event_time),
          raw_json=VALUES(raw_json),
          updated_at=CURRENT_TIMESTAMP
        """
        params = []
        for r in rows:
            params.append((
                r.get("id"), r.get("visitor_name") or r.get("name"),
                r.get("visitor_phone") or r.get("phone"),
                r.get("host_unit") or r.get("unit"),
                r.get("qr_id") or r.get("qrCode") or r.get("qr_code"),
                r.get("event_time"),
                json.dumps(r, ensure_ascii=False)
            ))
        if params:
            cur.executemany(sql, params)
            conn.commit()

    cur.close()
    conn.close()

def get_recent_from_mysql(table, limit=500):
    conn = get_connection()
    cur = conn.cursor()
    if table == "access_events":
        cur.execute("SELECT * FROM access_events ORDER BY event_time DESC, id DESC LIMIT %s", (limit,))
    else:
        cur.execute("SELECT * FROM qr_events ORDER BY event_time DESC, id DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

@app.route("/health/db")
def health_db():
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
        conn.close()
        return {"ok": True, "db": row["ok"]}, 200
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


# =========================
# 라우트 맵 확인 (디버깅용)
# =========================
print("== URL MAP ==")
for r in app.url_map.iter_rules():
    print(r, "->", r.methods)

# =========================
# 앱 실행
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
