import requests
import time

def get_ai_advice(api_key, ai_model, mode, data_payload, context_data):
    """Send analysis prompt to Google Gemini AI"""
    if not api_key or api_key.strip() == "":
        return "Please enter your Google Gemini API Key for AI analysis."

    temp = context_data.get("temp", "Unknown")
    cond = context_data.get("cond", "Unknown")
    hvac = context_data.get("hvac", "Normal")
    expected_km_per_1 = context_data.get("expected_km_per_1", 2.1)

    prompt = ""

    if mode == "weather" and data_payload:
        w_temp = data_payload.get('temp', temp)
        w_cond = data_payload.get('cond', cond)
        prompt = (
            f"EXTREME WEATHER WARNING: Outdoor temperature is {w_temp}C, weather: {w_cond}. "
            f"Act as a VinFast vehicle AI expert, write ONE very concise sentence (under 40 words) "
            "advising the driver on how to adjust the AC and drive for maximum safety and battery efficiency right now."
        )
    elif mode == "anomaly" and data_payload:
        dist = round(data_payload.get('dist', 0), 2)
        spd = round(data_payload.get('speed', 0), 1)
        prompt = (
            f"BATTERY DRAIN WARNING: Vehicle just dropped 1% battery but only traveled {dist}km "
            f"(manufacturer ideal rated efficiency is {expected_km_per_1} km/1%). "
            f"Current average speed: {spd}km/h. AC load: {hvac}. "
            "Act as the onboard AI Advisor, write ONE very concise sentence (under 40 words) "
            "analyzing the cause of high battery drain (speed or AC) and provide urgent advice."
        )
    else: # Trip mode
        dist = data_payload.get('dist', 0) if data_payload else context_data.get("trip_dist", 0.0)
        drop = data_payload.get('drop', 0) if data_payload else 0
        
        if dist < 0.05: 
            return f"System waiting... Current trip ({dist}km) is too short to analyze."

        actual_km_per_1 = round(dist / drop, 2) if drop > 0 else dist
        spd = context_data.get("trip_avg_speed", 0)
        
        prompt = (
            f"Act as an EV analysis engineer. The completed trip was {round(dist,2)}km long, consuming {round(drop,1)}% battery. "
            f"Actual efficiency: {actual_km_per_1} km / 1% battery. (Manufacturer rated: {expected_km_per_1} km / 1%). "
            f"Average speed {spd}km/h. Environment: {temp}°C, {cond}. AC load: {hvac}. "
            "Write 1 concise paragraph (under 50 words) evaluating whether this trip efficiency was excellent, average, or poor "
            "and provide 1 tip."
        )

    clean_key = api_key.strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{ai_model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": clean_key}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for attempt in range(3):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=30)
            if res.status_code == 200:
                ai_text = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return ai_text.replace("*", "").strip() if ai_text else "Google AI did not return any content."
            elif res.status_code == 403: return "Error 403: API Key is invalid or Generative Language API is not enabled."
            elif res.status_code == 404: return f"Error 404: Model '{ai_model}' does not exist or is locked."
            elif res.status_code == 400: return "Error 400: Invalid API Key format."
            elif res.status_code in [503, 429]:
                if attempt < 2: 
                    time.sleep(3)
                    continue
                return f"Google AI is overloaded (Error {res.status_code})."
            else:
                return f"Google reported error {res.status_code}"
        except requests.exceptions.RequestException:
            if attempt < 2:
                time.sleep(3)
                continue
            return "Local network error: Cannot connect to Google AI."
            
    return "Unknown error contacting AI."