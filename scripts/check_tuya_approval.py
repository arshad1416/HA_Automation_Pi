#!/usr/bin/env python3
import json, requests, time, hmac, hashlib, base64, urllib.request

def check_tuya():
    try:
        with open("/opt/homeassistant/.storage/core.config_entries", "r") as f:
            entries = json.load(f)["data"]["entries"]

        client_id = None
        client_secret = None
        for e in entries:
            if e.get("domain") == "localtuya":
                data = e.get("data", {})
                client_id = data.get("client_id")
                client_secret = data.get("client_secret")
                break

        if not client_id or not client_secret:
            print("No Tuya credentials found")
            return False

        t = str(int(time.time() * 1000))
        method = "GET"
        url_path = "/v1.0/token?grant_type=1"
        body_sha = hashlib.sha256(b"").hexdigest()
        string_to_sign = method + "\n" + body_sha + "\n\n" + url_path
        str_for_hmac = client_id + t + string_to_sign
        sign = hmac.new(client_secret.encode("utf-8"), str_for_hmac.encode("utf-8"), hashlib.sha256).hexdigest().upper()

        headers = {"client_id": client_id, "sign": sign, "t": t, "sign_method": "HMAC-SHA256"}
        r = requests.get("https://openapi.tuyaus.com/v1.0/token?grant_type=1", headers=headers).json()
        token = r.get("result", {}).get("access_token")
        if not token:
            print("Token request failed:", r)
            return False

        t2 = str(int(time.time() * 1000))
        endpoint = "/v1.0/devices/eb01644e61c9df9fa5argy"
        string_to_sign2 = "GET" + "\n" + body_sha + "\n\n" + endpoint
        str_for_hmac2 = client_id + token + t2 + string_to_sign2
        sign2 = hmac.new(client_secret.encode("utf-8"), str_for_hmac2.encode("utf-8"), hashlib.sha256).hexdigest().upper()
        headers2 = {"client_id": client_id, "access_token": token, "sign": sign2, "t": t2, "sign_method": "HMAC-SHA256"}

        res = requests.get("https://openapi.tuyaus.com" + endpoint, headers=headers2).json()
        print("Tuya check result:", res.get("success"), res.get("msg"))
        if res.get("success"):
            print("APPROVED! Tuya API is active!")
            notify_ha("🎉 Tuya Cloud API Approved!", "Tuya IoT Core extension is active. Real-time state push restored.")
            return True
        return False
    except Exception as e:
        print("Check error:", e)
        return False

def notify_ha(title, message):
    try:
        with open("/opt/homeassistant/.storage/auth", "r") as f:
            auth_data = json.load(f)
        tokens = auth_data.get("data", {}).get("refresh_tokens", [])
        llat = [t for t in tokens if t.get("token_type") == "long_lived_access_token"]
        token_obj = llat[0]
        refresh_token = token_obj["id"]
        jwt_key = token_obj["jwt_key"]
        user_id = token_obj["user_id"]

        header = json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8")
        now = int(time.time())
        payload = json.dumps({"iss": refresh_token, "iat": now, "exp": now + 300, "sub": user_id}).encode("utf-8")
        def b64url(d): return base64.urlsafe_b64encode(d).rstrip(b"=").decode("utf-8")

        token_str = b64url(header) + "." + b64url(payload)
        sig = hmac.new(jwt_key.encode("utf-8"), token_str.encode("utf-8"), hashlib.sha256).digest()
        jwt = token_str + "." + b64url(sig)

        headers = {"Authorization": "Bearer " + jwt, "Content-Type": "application/json"}
        url = "http://localhost:8123/api/services/notify/mobile_app_cph2655"
        body = json.dumps({"title": title, "message": message}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        urllib.request.urlopen(req)

        url_reload = "http://localhost:8123/api/config/config_entries/entry/01KSC806BJV15G6FY4MQ3PCBM2/reload"
        req_reload = urllib.request.Request(url_reload, data=json.dumps({}).encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req_reload)
    except Exception as e:
        print("Notify error:", e)

if __name__ == "__main__":
    check_tuya()
