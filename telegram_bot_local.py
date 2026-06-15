import os
import base64
import io
import json
import re
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
WEATHER_APP_BASE_URL = os.getenv("WEATHER_APP_BASE_URL", "https://grudproject-weather-app.hf.space").rstrip("/")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", os.getenv("RENDER_BOT_URL", "")).strip().rstrip("/")

YOLO_CAMERA_URL = "https://huggingface.co/spaces/grudproject/yolo26-tomato-disease"
WEATHER_APP_URL = "https://huggingface.co/spaces/grudproject/Weather_app"

SETTINGS_FILE = os.getenv("TELEGRAM_SETTINGS_FILE", "/tmp/smart_greenhouse_telegram_settings.json")
HISTORY_FILE = os.getenv("TELEGRAM_HISTORY_FILE", "/tmp/smart_greenhouse_telegram_history.json")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment variables")
if not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_CHAT_ID in environment variables")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# ==========================================================
# FILE HELPERS
# ==========================================================
def load_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Could not read {path}:", repr(e))
    return default


def save_json_file(path, data):
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Could not write {path}:", repr(e))
        return False


# ==========================================================
# LANGUAGE SETTINGS
# ==========================================================
def get_chat_lang(chat_id=None):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    data = load_json_file(SETTINGS_FILE, {})
    lang = data.get(chat_id, {}).get("language", "en")
    return "ar" if lang == "ar" else "en"


def set_chat_lang(chat_id, lang):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    lang = "ar" if lang == "ar" else "en"
    data = load_json_file(SETTINGS_FILE, {})
    old = data.get(chat_id, {})
    old["language"] = lang
    data[chat_id] = old
    save_json_file(SETTINGS_FILE, data)
    return lang


def is_ar(chat_id=None):
    return get_chat_lang(chat_id) == "ar"


# ==========================================================
# MESSAGE HISTORY FOR CLEAR CHAT BUTTON
# ==========================================================
def remember_message(chat_id, message_id):
    if not message_id:
        return
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    data = load_json_file(HISTORY_FILE, {})
    ids = data.get(chat_id, [])
    if message_id not in ids:
        ids.append(message_id)
    data[chat_id] = ids[-300:]  # keep last 300 bot messages only
    save_json_file(HISTORY_FILE, data)


def clear_remembered_messages(chat_id=None):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    data = load_json_file(HISTORY_FILE, {})
    ids = data.get(chat_id, [])
    deleted = 0
    errors = []

    for message_id in list(ids):
        js = tg_post("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=15)
        if js.get("ok"):
            deleted += 1
        else:
            errors.append(js)

    data[chat_id] = []
    save_json_file(HISTORY_FILE, data)
    return deleted, errors


# ==========================================================
# TELEGRAM API
# ==========================================================
def tg_post(method, data=None, files=None, timeout=30):
    url = f"{TG_API}/{method}"
    r = requests.post(url, data=data or {}, files=files, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "description": r.text}


def tg_get(method, params=None, timeout=30):
    url = f"{TG_API}/{method}"
    r = requests.get(url, params=params or {}, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "description": r.text}


def set_telegram_webhook():
    if not PUBLIC_BASE_URL:
        return {"ok": False, "description": "PUBLIC_BASE_URL is missing"}
    return tg_post(
        "setWebhook",
        {"url": f"{PUBLIC_BASE_URL}/telegram-webhook", "drop_pending_updates": "true"},
        timeout=30,
    )


def get_webhook_info():
    return tg_get("getWebhookInfo", timeout=30)


def answer_callback_query(callback_query_id, text=""):
    data = {"callback_query_id": callback_query_id}
    if text:
        data["text"] = text[:190]
    return tg_post("answerCallbackQuery", data, timeout=30)


# ==========================================================
# TEXT CLEANING AND ARABIC CONVERSION
# ==========================================================
def remove_farmer_unfriendly_lines(text):
    lines = str(text).splitlines()
    cleaned = []
    remove_contains = [
        "loaded from Arduino Cloud",
        "Loaded from Arduino Cloud",
        "Source:",
        "source:",
        "diseaseHistory",
        "Publish results",
        "arduinoPublishResults",
        "Update result:",
        "raw",
        "script",
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if any(x in stripped for x in remove_contains):
            continue
        # Replace a technical phrase if it appears inside a useful line.
        line = line.replace("Weather Warning", "Weather Alert")
        line = line.replace("WEATHER WARNING", "WEATHER ALERT")
        cleaned.append(line)

    return "\n".join(cleaned).strip()


AR_REPLACEMENTS = {
    # titles
    "Smart Greenhouse Bot is running.": "بوت البيت البلاستيكي الذكي يعمل الآن.",
    "Choose one of the buttons below:": "اختر أحد الأزرار التالية:",
    "SMART GREENHOUSE REPORT": "تقرير البيت البلاستيكي الذكي",
    "CURRENT GREENHOUSE READINGS REPORT": "تقرير قراءات البيت البلاستيكي الحالية",
    "SENSOR DANGER ALERT": "تنبيه خطير من المستشعرات",
    "SENSOR WARNING REPORT": "تقرير تحذيري من المستشعرات",
    "NODE SENSOR + MATCHED DISEASE SUMMARY": "ملخص قراءات العقدة والمرض المطابق",
    "DAILY FARMER PRIORITIES": "أولويات المزارع اليومية",
    "LATEST DISEASE STATUS": "آخر حالة مرضية",
    "AI TOMATO DISEASE DETECTION ALERT": "تنبيه كشف أمراض البندورة بالذكاء الاصطناعي",
    "WEATHER INFO": "معلومات الطقس",
    "WEATHER ALERT": "تنبيه الطقس",
    "WEATHER RISK": "مخاطر الطقس",
    "GREENHOUSE WEATHER REPORT": "تقرير طقس البيت البلاستيكي",

    # labels
    "Report Time": "وقت التقرير",
    "Update Time": "وقت التحديث",
    "Last Update": "آخر تحديث",
    "Greenhouse": "البيت البلاستيكي",
    "Node": "العقدة",
    "Status": "الحالة",
    "Sensor readings": "قراءات المستشعرات",
    "Sensor recommendations": "توصيات المستشعرات",
    "Recommendations": "التوصيات",
    "Disease result": "نتيجة المرض",
    "Disease actions": "إجراءات المرض",
    "Matched disease": "المرض المطابق",
    "Most Disease": "أكثر مرض ظاهر",
    "All Diseases": "جميع الأمراض",
    "Disease Counts": "عدد الأمراض",
    "Confidence": "نسبة الثقة",
    "Images": "الصور",
    "Total": "المجموع",
    "Infected": "مصابة",
    "Healthy": "سليمة",
    "No Detection": "لا يوجد كشف",
    "Disease Detected": "تم اكتشاف مرض",
    "No Disease Detected": "لم يتم اكتشاف مرض",
    "Disease LED": "مؤشر المرض",
    "ON": "تشغيل",
    "OFF": "إيقاف",

    # sensors
    "Air Temp": "حرارة الهواء",
    "Air Temperature": "حرارة الهواء",
    "Air Humidity": "رطوبة الهواء",
    "Soil Moisture": "رطوبة التربة",
    "Soil Temp": "حرارة التربة",
    "Soil Temperature": "حرارة التربة",
    "Soil EC": "ملوحة/توصيل التربة EC",
    "Soil pH": "حموضة التربة pH",
    "Light": "الإضاءة",
    "LDR": "الإضاءة",

    # statuses
    "Dangerous": "خطير",
    "Warning": "تحذير",
    "Good": "جيد",
    "Normal": "طبيعي",
    "High": "مرتفع",
    "Low": "منخفض",
    "Very High": "مرتفع جدًا",
    "Very Low": "منخفض جدًا",
    "Critical": "حرج",
    "Safe": "آمن",

    # disease names
    "Early_Blight": "اللفحة المبكرة",
    "Early Blight": "اللفحة المبكرة",
    "Late_Blight": "اللفحة المتأخرة",
    "Late Blight": "اللفحة المتأخرة",
    "Leaf_Mold": "عفن الأوراق",
    "Leaf Mold": "عفن الأوراق",
    "Septoria": "تبقع سبتوريا",
    "Bacterial_Spot": "التبقع البكتيري",
    "Bacterial Spot": "التبقع البكتيري",
    "Spider_Mites": "العناكب الحمراء",
    "Spider Mites": "العناكب الحمراء",
    "Leaf_Mites": "أكاروسات الأوراق",
    "Leaf Mites": "أكاروسات الأوراق",
    "Mosaic_Virus": "فيروس الموزاييك",
    "Mosaic Virus": "فيروس الموزاييك",
    "Yellow_Leaf_Curl_Virus": "فيروس تجعد واصفرار الأوراق",
    "Yellow Leaf Curl Virus": "فيروس تجعد واصفرار الأوراق",
    "No_Detection": "لا يوجد كشف",

    # common action sentences
    "Inspect nodes with": "افحص أولًا العقد التي حالتها",
    "If disease matches a node, apply disease actions on that node first.": "إذا كان المرض مطابقًا لعقدة معينة، طبّق إجراءات المرض على تلك العقدة أولًا.",
    "Correct abnormal pH/EC because plant stress can worsen disease impact.": "صحّح قيم pH و EC غير الطبيعية لأن إجهاد النبات قد يزيد تأثير المرض.",
    "Keep tomato leaves dry and improve ventilation when humidity is high.": "حافظ على جفاف أوراق البندورة وحسّن التهوية عند ارتفاع الرطوبة.",
    "Clean tools after removing infected leaves.": "نظّف الأدوات بعد إزالة الأوراق المصابة.",
    "Move the camera closer to the tomato leaves.": "قرّب الكاميرا من أوراق البندورة.",
    "Make sure the plant leaf fills most of the image.": "تأكد أن الورقة تملأ معظم الصورة.",
    "Use good lighting and avoid strong glare or shadow.": "استخدم إضاءة جيدة وتجنب الوهج أو الظلال القوية.",
    "Hold the phone steady and keep the image focused.": "ثبّت الهاتف جيدًا واجعل الصورة واضحة.",
    "Retake the image and run detection again.": "أعد التقاط الصورة وشغّل الكشف مرة أخرى.",
    "Tomato disease camera": "كاميرا كشف أمراض البندورة",
    "Weather App": "تطبيق الطقس",
    "Unknown command. Send /help to see available commands.": "الأمر غير معروف. أرسل /ابدأ لعرض الخيارات.",
}


# Extra Arabic replacements to avoid mixed English/Arabic farmer messages.
AR_EXTRA_REPLACEMENTS = {
    "TOMATO DISEASE REPORT": "تقرير أمراض البندورة",
    "Disease Report": "تقرير الأمراض",
    "Date": "التاريخ",
    "node update": "وقت تحديث العقدة",
    "Node update": "وقت تحديث العقدة",
    "Disease update": "وقت تحديث المرض",
    "matched disease result": "نتيجة المرض المطابق",
    "Matched disease result": "نتيجة المرض المطابق",
    "Detected": "تم الكشف عن",
    "Most likely": "الأكثر احتمالًا",
    "images": "صور",
    "image": "صورة",
    "img": "صورة",
    "total": "المجموع",
    "infected": "مصابة",
    "healthy": "سليمة",
    "no detection": "لا يوجد كشف",
    "Weather Alert": "تنبيه الطقس",
    "Weather actions": "إجراءات الطقس",
    "Weather Risk Forecast": "توقعات مخاطر الطقس",
    "SUMMARY": "ملخص",
    "Temp": "الحرارة",
    "Humidity": "الرطوبة",
    "Wind": "الرياح",
    "Risk": "الخطر",
    "Action": "الإجراء",
    "Stable": "مستقر",
    "No major outside weather risk for tomato plants is expected.": "لا يُتوقع وجود خطر طقس خارجي كبير على نباتات البندورة.",
    "Continue normal monitoring and ventilation.": "استمر بالمراقبة والتهوية الطبيعية.",
    "high humidity may increase disease risk if leaves stay wet.": "الرطوبة المرتفعة قد تزيد خطر الأمراض إذا بقيت الأوراق مبللة.",
    "Ventilate during suitable hours.": "قم بالتهوية خلال الساعات المناسبة.",
    "Follow the forecast advice and continue monitoring tomato plants.": "اتبع توصيات الطقس واستمر بمراقبة نباتات البندورة.",
    "Air": "حرارة الهواء",
    "Humidity": "الرطوبة",
    "Soil moisture": "رطوبة التربة",
    "Soil temp": "حرارة التربة",
    "High Risk": "خطر مرتفع",
    "Risk": "خطر",
    "and irrigation": "والري",
    "first": "أولًا",
    "or": "أو",
    "result": "نتيجة",
    "Matched sensor interpretation": "تفسير المستشعرات المرتبطة بالمرض",
    "pH/EC problems stress plants but do not directly cause fungal/viral disease.": "مشكلات pH و EC تُجهد النبات، لكنها لا تسبب الأمراض الفطرية أو الفيروسية بشكل مباشر.",
    "Remove infected lower leaves.": "أزل الأوراق السفلية المصابة.",
    "Remove infected lower leaves and old plant debris.": "أزل الأوراق السفلية المصابة وبقايا النبات القديمة.",
    "Remove old plant debris.": "أزل بقايا النباتات القديمة.",
    "Keep leaves dry.": "حافظ على جفاف الأوراق.",
    "Improve airflow.": "حسّن حركة الهواء.",
    "Improve airflow around this node.": "حسّن حركة الهواء حول هذه العقدة.",
    "Use mulch to reduce splash.": "استخدم الغطاء العضوي لتقليل تطاير التربة.",
    "Use mulch to reduce soil splash.": "استخدم الغطاء العضوي لتقليل تطاير التربة.",
    "Avoid overhead irrigation.": "تجنّب الري من الأعلى.",
    "Avoid overhead watering.": "تجنّب الري من الأعلى.",
    "Scattered clouds": "غيوم متفرقة",
    "scattered clouds": "غيوم متفرقة",
    "few clouds": "غيوم قليلة",
    "clear sky": "سماء صافية",
    "broken clouds": "غيوم متقطعة",
    "overcast clouds": "غيوم كثيفة",
    "light rain": "أمطار خفيفة",
    "moderate rain": "أمطار متوسطة",
    "Leaf Spot": "تبقع الأوراق",
    "Septoria Leaf Spot": "تبقع سبتوريا",
}



# Strong Arabic dictionary used for any message coming from Weather App or YOLO App.
# It is applied safely using English word boundaries, so words like Monitor/Correct/Information
# are not broken by small replacements such as "or" or "ON".
ARABIC_FULL_REPLACEMENTS = {
    # Main titles
    "TOMATO DISEASE REPORT": "🦠 تقرير أمراض البندورة",
    "AI TOMATO DISEASE DETECTION ALERT": "🦠 تنبيه كشف أمراض البندورة بالذكاء الاصطناعي",
    "CURRENT GREENHOUSE READINGS REPORT": "📊 تقرير قراءات البيت البلاستيكي الحالية",
    "SENSOR DANGER ALERT": "🚨 تنبيه خطير من المستشعرات",
    "SENSOR WARNING REPORT": "⚠️ تقرير تحذيري من المستشعرات",
    "SMART GREENHOUSE REPORT": "📋 تقرير البيت البلاستيكي الذكي",
    "GREENHOUSE WEATHER REPORT": "🌤 تقرير طقس البيت البلاستيكي",
    "WEATHER INFORMATION": "🌤 معلومات الطقس",
    "WEATHER INFO": "🌤 معلومات الطقس",
    "WEATHER UPDATED": "✅ تم تحديث الطقس",
    "Tomato Weather Risk": "مخاطر الطقس على البندورة",
    "TOMATO WEATHER RISK": "مخاطر الطقس على البندورة",
    "Weather Risk Forecast": "توقعات مخاطر الطقس",
    "WEATHER RISK FORECAST": "توقعات مخاطر الطقس",
    "Weather Risk": "مخاطر الطقس",
    "Weather Alert": "تنبيه الطقس",
    "Weather Warning": "تنبيه الطقس",
    "Weather Status": "حالة الطقس",
    "Weather actions": "إجراءات الطقس",
    "Farmer procedures": "إجراءات المزارع",
    "QUICK TIPS": "نصائح سريعة",
    "SENSOR STATUS BY NODE": "حالة المستشعرات حسب العقدة",
    "WARNINGS BY NODE": "التحذيرات حسب العقدة",
    "NODE SENSOR + MATCHED DISEASE SUMMARY": "ملخص قراءات العقد والمرض المطابق",
    "DAILY FARMER PRIORITIES": "أولويات المزارع اليومية",
    "LATEST DISEASE STATUS": "آخر حالة مرضية",
    "Disease Report": "تقرير الأمراض",

    # Labels
    "Latest Greenhouse": "آخر بيت بلاستيكي",
    "Latest Live Node": "آخر عقدة مباشرة",
    "Sensor Thing Last Update": "آخر تحديث لقراءات المستشعرات",
    "Report Time": "وقت التقرير",
    "Update Time": "وقت التحديث",
    "Updated": "وقت التحديث",
    "Last Update": "آخر تحديث",
    "Date": "التاريخ",
    "Greenhouse": "البيت البلاستيكي",
    "Node": "العقدة",
    "node update": "وقت تحديث العقدة",
    "Node update": "وقت تحديث العقدة",
    "Disease update": "وقت تحديث المرض",
    "Status": "الحالة",
    "Disease Status": "حالة المرض",
    "Disease result": "نتيجة المرض",
    "Matched disease result": "نتيجة المرض المطابق",
    "matched disease result": "نتيجة المرض المطابق",
    "Detected": "تم الكشف عن",
    "Most likely": "الأكثر احتمالًا",
    "Most Disease": "أكثر مرض ظاهر",
    "All Diseases": "جميع الأمراض",
    "Disease Counts": "عدد الأمراض",
    "Confidence": "نسبة الثقة",
    "Images": "الصور",
    "images": "الصور",
    "image": "صورة",
    "img": "صورة",
    "Total": "المجموع",
    "total": "المجموع",
    "Infected": "مصابة",
    "infected": "مصابة",
    "Healthy": "سليمة",
    "healthy": "سليمة",
    "No Detection": "لا يوجد كشف",
    "no detection": "لا يوجد كشف",
    "Disease Detected": "تم اكتشاف مرض",
    "No Disease Detected": "لم يتم اكتشاف مرض",
    "Disease LED": "مؤشر المرض",
    "Problem": "المشكلة",
    "Action": "الإجراء",
    "Risk": "الخطر",
    "SUMMARY": "ملخص",

    # Sensors and weather
    "Sensor readings": "قراءات المستشعرات",
    "Sensor recommendations": "توصيات المستشعرات",
    "Recommendations": "التوصيات",
    "Air Temp": "حرارة الهواء",
    "Air Temperature": "حرارة الهواء",
    "Outside Temperature": "درجة الحرارة الخارجية",
    "Outside Humidity": "الرطوبة الخارجية",
    "Temperature": "درجة الحرارة",
    "Humidity": "الرطوبة",
    "Air Humidity": "رطوبة الهواء",
    "Wind Speed": "سرعة الرياح",
    "Wind": "الرياح",
    "Soil Moisture": "رطوبة التربة",
    "Soil moisture": "رطوبة التربة",
    "Soil Temp": "حرارة التربة",
    "Soil temp": "حرارة التربة",
    "Soil Temperature": "حرارة التربة",
    "Soil EC": "ملوحة/توصيل التربة EC",
    "Soil pH": "حموضة التربة pH",
    "Light": "الإضاءة",
    "LDR": "الإضاءة",

    # Status words
    "Dangerous": "خطير",
    "Warning": "تحذير",
    "Good": "جيد",
    "Normal": "طبيعي",
    "Stable": "مستقر",
    "High Risk": "خطر مرتفع",
    "Very High": "مرتفع جدًا",
    "Very Low": "منخفض جدًا",
    "High": "مرتفع",
    "Low": "منخفض",
    "Critical": "حرج",
    "Safe": "آمن",
    "ON": "تشغيل",
    "OFF": "إيقاف",

    # Disease names
    "Early_Blight": "اللفحة المبكرة",
    "Early Blight": "اللفحة المبكرة",
    "Late_Blight": "اللفحة المتأخرة",
    "Late Blight": "اللفحة المتأخرة",
    "Leaf_Mold": "عفن الأوراق",
    "Leaf Mold": "عفن الأوراق",
    "Septoria Leaf Spot": "تبقع سبتوريا",
    "Septoria": "تبقع سبتوريا",
    "Bacterial_Spot": "التبقع البكتيري",
    "Bacterial Spot": "التبقع البكتيري",
    "Spider_Mites": "العناكب الحمراء",
    "Spider Mites": "العناكب الحمراء",
    "Leaf_Mites": "أكاروسات الأوراق",
    "Leaf Mites": "أكاروسات الأوراق",
    "Mosaic_Virus": "فيروس الموزاييك",
    "Mosaic Virus": "فيروس الموزاييك",
    "Yellow_Leaf_Curl_Virus": "فيروس تجعد واصفرار الأوراق",
    "Yellow Leaf Curl Virus": "فيروس تجعد واصفرار الأوراق",
    "Leaf Spot": "تبقع الأوراق",
    "No_Detection": "لا يوجد كشف",

    # Weather descriptions
    "scattered clouds": "غيوم متفرقة",
    "Scattered clouds": "غيوم متفرقة",
    "few clouds": "غيوم قليلة",
    "Few clouds": "غيوم قليلة",
    "clear sky": "سماء صافية",
    "Clear sky": "سماء صافية",
    "broken clouds": "غيوم متقطعة",
    "Broken clouds": "غيوم متقطعة",
    "overcast clouds": "غيوم كثيفة",
    "Overcast clouds": "غيوم كثيفة",
    "light rain": "أمطار خفيفة",
    "moderate rain": "أمطار متوسطة",

    # Common procedures and sentences
    "Monitor EC and irrigation": "راقب قيمة EC ونظام الري",
    "Monitor EC": "راقب قيمة EC",
    "Correct pH carefully": "صحّح قيمة pH بحذر",
    "Adjust pH gradually": "عدّل قيمة pH تدريجيًا",
    "High salinity/nutrient level": "ارتفاع الملوحة أو مستوى المغذيات",
    "high salinity/nutrient level": "ارتفاع الملوحة أو مستوى المغذيات",
    "Alkaline soil": "تربة قلوية",
    "Remove infected lower leaves and old plant debris.": "أزل الأوراق السفلية المصابة وبقايا النبات القديمة.",
    "Remove infected lower leaves.": "أزل الأوراق السفلية المصابة.",
    "Remove old plant debris.": "أزل بقايا النباتات القديمة.",
    "Keep leaves dry.": "حافظ على جفاف الأوراق.",
    "Keep tomato leaves dry and improve ventilation when humidity is high.": "حافظ على جفاف أوراق البندورة وحسّن التهوية عند ارتفاع الرطوبة.",
    "Improve airflow around this node.": "حسّن حركة الهواء حول هذه العقدة.",
    "Improve airflow.": "حسّن حركة الهواء.",
    "Improve ventilation": "حسّن التهوية.",
    "Use mulch to reduce soil splash.": "استخدم الغطاء العضوي لتقليل تطاير التربة.",
    "Use mulch to reduce splash.": "استخدم الغطاء العضوي لتقليل تطاير التربة.",
    "Avoid overhead irrigation.": "تجنّب الري من الأعلى.",
    "Avoid overhead watering.": "تجنّب الري من الأعلى.",
    "Clean tools after removing infected leaves.": "نظّف الأدوات بعد إزالة الأوراق المصابة.",
    "Inspect lower leaves for spots or mold.": "افحص الأوراق السفلية بحثًا عن بقع أو عفن.",
    "Inspect lower leaves for spots or mold": "افحص الأوراق السفلية بحثًا عن بقع أو عفن",
    "Ventilate during suitable hours.": "قم بالتهوية خلال الساعات المناسبة.",
    "Continue normal monitoring and ventilation.": "استمر بالمراقبة والتهوية الطبيعية.",
    "Follow the forecast advice and continue monitoring tomato plants.": "اتبع توصيات الطقس واستمر بمراقبة نباتات البندورة.",
    "High humidity may increase disease risk if leaves stay wet.": "الرطوبة المرتفعة قد تزيد خطر الأمراض إذا بقيت الأوراق مبللة.",
    "high humidity may increase disease risk if leaves stay wet.": "الرطوبة المرتفعة قد تزيد خطر الأمراض إذا بقيت الأوراق مبللة.",
    "No major outside weather risk for tomato plants is expected.": "لا يُتوقع وجود خطر طقس خارجي كبير على نباتات البندورة.",
    "pH/EC problems stress plants but do not directly cause fungal/viral disease.": "مشكلات pH و EC تُجهد النبات، لكنها لا تسبب الأمراض الفطرية أو الفيروسية بشكل مباشر.",
    "Inspect nodes with": "افحص أولًا العقد التي حالتها",
    "If disease matches a node, apply disease actions on that node first.": "إذا كان المرض مطابقًا لعقدة معينة، طبّق إجراءات المرض على تلك العقدة أولًا.",
    "Correct abnormal pH/EC because plant stress can worsen disease impact.": "صحّح قيم pH و EC غير الطبيعية لأن إجهاد النبات قد يزيد تأثير المرض.",
    "Move the camera closer to the tomato leaves.": "قرّب الكاميرا من أوراق البندورة.",
    "Make sure the plant leaf fills most of the image.": "تأكد أن الورقة تملأ معظم الصورة.",
    "Use good lighting and avoid strong glare or shadow.": "استخدم إضاءة جيدة وتجنب الوهج أو الظلال القوية.",
    "Hold the phone steady and keep the image focused.": "ثبّت الهاتف جيدًا واجعل الصورة واضحة.",
    "Retake the image and run detection again.": "أعد التقاط الصورة وشغّل الكشف مرة أخرى.",
}



# V20 extra phrases: YOLO automatic messages, Weather App messages, and mixed English lines.
ARABIC_YOLO_WEATHER_EXTRA = {
    "Greenhouse / Plastic House": "البيت البلاستيكي",
    "Plastic House": "البيت البلاستيكي",
    "Crop": "المحصول",
    "Tomato": "البندورة",
    "DISEASE RESULT": "نتيجة المرض",
    "Disease Result": "نتيجة المرض",
    "Average Confidence": "متوسط نسبة الثقة",
    "Average": "متوسط",
    "Total Images": "إجمالي الصور",
    "Infected Images": "الصور المصابة",
    "Healthy Images": "الصور السليمة",
    "No Detection Images": "صور بدون كشف",
    "Disease Counts": "عدد الأمراض",
    "SENSOR MATCH STATUS": "حالة مطابقة المستشعرات",
    "Sensor Match Status": "حالة مطابقة المستشعرات",
    "No matched sensor link was added.": "لم تتم إضافة ربط مطابق مع قراءات المستشعرات.",
    "The system checked both": "فحص النظام المصدرين التاليين",
    "allNodesData history": "سجل قراءات جميع العقد",
    "latest live sensor variables": "آخر قراءات مباشرة من المستشعرات",
    "Sensor readings are linked to the disease alert only when the selected image greenhouse/plastic-house ID and node ID both match the sensor record.": "يتم ربط قراءات المستشعرات بتنبيه المرض فقط عندما يتطابق رقم البيت البلاستيكي ورقم العقدة في الصورة مع سجل المستشعرات.",
    "Sensor readings are linked to the disease alert only when the selected image greenhouse/plastic-house ID and node ID both match the sensor record": "يتم ربط قراءات المستشعرات بتنبيه المرض فقط عندما يتطابق رقم البيت البلاستيكي ورقم العقدة في الصورة مع سجل المستشعرات",
    "Latest live sensor record": "آخر سجل مباشر للمستشعرات",
    "SCIENTIFIC INFORMATION FOR ALL DETECTED DISEASES": "معلومات علمية عن الأمراض المكتشفة",
    "Scientific Information For All Detected Diseases": "معلومات علمية عن الأمراض المكتشفة",
    "Disease 1": "المرض 1",
    "Disease 2": "المرض 2",
    "Disease 3": "المرض 3",
    "Definition": "التعريف",
    "Causes / Spread": "الأسباب وطريقة الانتشار",
    "Main Symptoms": "الأعراض الرئيسية",
    "Related sensor indicators": "المؤشرات المرتبطة بالمستشعرات",
    "Critical sensor readings": "قراءات المستشعرات الحرجة",
    "Not linked because greenhouse/plastic-house ID and node ID did not both match the sensor record.": "غير مرتبط لأن رقم البيت البلاستيكي ورقم العقدة لا يتطابقان مع سجل المستشعرات.",
    "Not linked because greenhouse/plastic-house ID and node ID did not both match the sensor record": "غير مرتبط لأن رقم البيت البلاستيكي ورقم العقدة لا يتطابقان مع سجل المستشعرات",
    "FARMER ACTIONS BASED ON DETECTED DISEASES AND CRITICAL SENSOR READINGS": "إجراءات المزارع بناءً على الأمراض المكتشفة وقراءات المستشعرات الحرجة",
    "Farmer Actions Based On Detected Diseases And Critical Sensor Readings": "إجراءات المزارع بناءً على الأمراض المكتشفة وقراءات المستشعرات الحرجة",
    "Tomato Disease Image Result": "نتيجة صورة مرض البندورة",
    "Improve spacing and greenhouse ventilation.": "حسّن المسافات بين النباتات وتهوية البيت البلاستيكي.",
    "Avoid overhead watering and keep leaves dry.": "تجنّب الري من الأعلى وحافظ على جفاف الأوراق.",
    "Monitor nearby tomato plants and apply suitable treatment if infection spreads.": "راقب نباتات البندورة القريبة وطبّق العلاج المناسب إذا انتشرت الإصابة.",
    "Sensor readings were not linked because greenhouse/plastic-house ID and node ID did not both match; verify the selected node and sensor source.": "لم يتم ربط قراءات المستشعرات لأن رقم البيت البلاستيكي ورقم العقدة لا يتطابقان مع سجل المستشعرات؛ تأكد من العقدة المختارة ومصدر القراءات.",
    "sensor readings were not linked because greenhouse/plastic-house ID and node ID did not both match; verify the selected node and sensor source.": "لم يتم ربط قراءات المستشعرات لأن رقم البيت البلاستيكي ورقم العقدة لا يتطابقان مع سجل المستشعرات؛ تأكد من العقدة المختارة ومصدر القراءات.",
    "Keep leaves dry; avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
    "Keep leaves dry؛ avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
    "keep leaves dry; avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
    "A common fungal tomato disease, mainly caused by Alternaria species. It usually starts on older lower leaves and may spread to stems and fruits.": "مرض فطري شائع في البندورة، تسببه غالبًا فطريات Alternaria. يبدأ عادةً على الأوراق السفلية القديمة وقد ينتشر إلى السيقان والثمار.",
    "Survives in infected plant debris, soil, and volunteer tomato plants. It spreads through splashing water, rain, overhead irrigation, wind, and contaminated tools.": "يبقى في بقايا النباتات المصابة والتربة ونباتات البندورة المتطوعة. ينتشر عبر تناثر الماء والأمطار والري من الأعلى والرياح والأدوات الملوثة.",
    "Dark brown circular spots, often with a target or bull's-eye pattern. Leaves may turn yellow, dry, and fall.": "بقع دائرية بنية داكنة، غالبًا بشكل حلقات تشبه الهدف. قد تصفر الأوراق ثم تجف وتسقط.",
    "air humidity, air temperature, soil moisture, soil pH/EC as stress factors": "رطوبة الهواء، حرارة الهواء، رطوبة التربة، و pH/EC كعوامل إجهاد للنبات",
    "Air humidity, air temperature, soil moisture, soil pH/EC as stress factors": "رطوبة الهواء، حرارة الهواء، رطوبة التربة، و pH/EC كعوامل إجهاد للنبات",
    "as stress factors": "كعوامل إجهاد للنبات",
    "detected images": "الصور التي تم الكشف فيها",
    "Detected images": "الصور التي تم الكشف فيها",
    "Weather Information": "معلومات الطقس",
    "INFORMATION": "معلومات",
    "Outside temperature": "درجة الحرارة الخارجية",
    "Outside humidity": "الرطوبة الخارجية",
    "Weather status": "حالة الطقس",
    "Weather Status": "حالة الطقس",
    "Tomato Weather Risk": "مخاطر الطقس على البندورة",
    "High humidity": "رطوبة مرتفعة",
    "high humidity": "رطوبة مرتفعة",
    "Inspect lower leaves for spots or mold.": "افحص الأوراق السفلية بحثًا عن بقع أو عفن.",
}



# V21 extra cleanup for remaining mixed Weather/Yolo text.
ARABIC_V21_EXTRA_REPLACEMENTS = {
    "Very high humidity can support fungal diseases such as Leaf Mold, Late Blight, and Septoria.": "الرطوبة العالية جدًا قد تساعد على انتشار أمراض فطرية مثل عفن الأوراق واللفحة المتأخرة وتبقع سبتوريا.",
    "very high humidity can support fungal diseases such as Leaf Mold, Late Blight, and Septoria.": "الرطوبة العالية جدًا قد تساعد على انتشار أمراض فطرية مثل عفن الأوراق واللفحة المتأخرة وتبقع سبتوريا.",
    "Very High humidity can support fungal diseases such as Leaf Mold, Late Blight, and Septoria.": "الرطوبة العالية جدًا قد تساعد على انتشار أمراض فطرية مثل عفن الأوراق واللفحة المتأخرة وتبقع سبتوريا.",
    "Improve ventilation when safe.": "حسّن التهوية عندما يكون ذلك آمنًا.",
    "Improve ventilation when safe": "حسّن التهوية عندما يكون ذلك آمنًا",
    "when safe": "عندما يكون ذلك آمنًا",
    "when Safe": "عندما يكون ذلك آمنًا",
    "Keep leaves dry; avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
    "Keep leaves dry؛ avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
    "Keep leaves dry; avoid overhead watering": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى",
    "No matched sensor link was added.": "لم تتم إضافة ربط مطابق مع قراءات المستشعرات.",
    "The system checked both:": "فحص النظام المصدرين التاليين:",
    "Sensor readings are linked to the disease alert only when the selected image greenhouse/plastic-house ID and node ID both match the sensor record.": "يتم ربط قراءات المستشعرات بتنبيه المرض فقط عندما يتطابق رقم البيت البلاستيكي ورقم العقدة في الصورة مع سجل المستشعرات.",
    "Latest live sensor record:": "آخر سجل مباشر للمستشعرات:",
    "Greenhouse / Plastic House": "البيت البلاستيكي",
    "Greenhouse/plastic-house": "البيت البلاستيكي",
    "greenhouse/plastic-house": "البيت البلاستيكي",
    "selected image": "الصورة المختارة",
    "latest live sensor variables": "آخر قراءات مباشرة من المستشعرات",
    "allNodesData history": "سجل قراءات جميع العقد",
    "Average Confidence": "متوسط نسبة الثقة",
    "Total Images": "إجمالي الصور",
    "Infected Images": "الصور المصابة",
    "Healthy Images": "الصور السليمة",
    "No Detection Images": "صور بدون كشف",
}



# V22 complete Arabic phrases from YOLO app.py and weather_app.py.
# These are exact disease/scientific/procedure strings so Arabic mode is not mixed with English.
ARABIC_COMPLETE_APP_PHRASES = {
    # Headings and sensor match
    "MATCHED SENSOR READINGS": "قراءات المستشعرات المطابقة",
    "Matched Sensor Readings": "قراءات المستشعرات المطابقة",
    "Check range": "تحقق من المجال",
    "Check sensor/nutrients": "تحقق من المستشعر أو المغذيات",
    "No critical matched sensor reading for": "لا توجد قراءة مستشعرات حرجة مطابقة لـ",
    "was found at this time.": "في هذا الوقت.",
    "Simple advice: continue monitoring the plant and keep greenhouse conditions stable.": "نصيحة بسيطة: استمر بمراقبة النبات وحافظ على استقرار ظروف البيت البلاستيكي.",
    "Adjust the greenhouse environment according to the critical readings above.": "عدّل بيئة البيت البلاستيكي حسب القراءات الحرجة المذكورة أعلاه.",
    "Stabilize Air Temperature using ventilation, shading, or heating/cooling as needed.": "ثبّت حرارة الهواء باستخدام التهوية أو التظليل أو التدفئة/التبريد حسب الحاجة.",
    "Stabilize air temperature using ventilation, shading, or heating/cooling as needed.": "ثبّت حرارة الهواء باستخدام التهوية أو التظليل أو التدفئة/التبريد حسب الحاجة.",
    "Check and correct Soil pH gradually toward the tomato-safe range.": "افحص حموضة التربة pH وصحّحها تدريجيًا نحو المجال الآمن للبندورة.",
    "Check and correct soil pH gradually toward the tomato-safe range.": "افحص حموضة التربة pH وصحّحها تدريجيًا نحو المجال الآمن للبندورة.",
    "Check nutrient solution/salinity and recalibrate the EC sensor if EC is zero or abnormal.": "افحص محلول التغذية والملوحة، وأعد معايرة مستشعر EC إذا كانت القراءة صفرًا أو غير طبيعية.",
    "Reduce humidity by increasing ventilation and avoiding water on leaves.": "خفّض الرطوبة بزيادة التهوية وتجنّب وصول الماء إلى الأوراق.",

    # YOLO disease definitions, causes, symptoms, sensor relations
    "A common fungal tomato disease, mainly caused by Alternaria species. It usually starts on older lower leaves and may spread to stems and fruits.": "مرض فطري شائع في البندورة، تسببه غالبًا فطريات Alternaria. يبدأ عادةً على الأوراق السفلية القديمة وقد ينتشر إلى السيقان والثمار.",
    "Survives in infected plant debris, soil, and volunteer tomato plants. It spreads through splashing water, rain, overhead irrigation, wind, and contaminated tools.": "يبقى في بقايا النباتات المصابة والتربة ونباتات البندورة المتطوعة. ينتشر عبر تناثر الماء والأمطار والري من الأعلى والرياح والأدوات الملوثة.",
    "Dark brown circular spots, often with a target or bull's-eye pattern. Leaves may turn yellow, dry, and fall.": "بقع دائرية بنية داكنة، غالبًا بشكل حلقات تشبه الهدف. قد تصفر الأوراق ثم تجف وتسقط.",
    "Warm air temperature, high humidity, wet leaves, and high soil moisture may support disease development and spread. Abnormal pH or EC may stress the plant but does not directly cause the disease.": "قد تساعد حرارة الهواء الدافئة والرطوبة العالية وابتلال الأوراق وارتفاع رطوبة التربة على تطور المرض وانتشاره. أما اضطراب pH أو EC فيُجهد النبات لكنه لا يسبب المرض مباشرة.",

    "A very destructive tomato disease caused by Phytophthora infestans. It can spread quickly under favorable cool, wet, and humid conditions.": "مرض مدمر جدًا يصيب البندورة وتسببه Phytophthora infestans. ينتشر بسرعة عند توفر ظروف باردة نسبيًا ورطبة ومشبعة بالرطوبة.",
    "Spreads through wind, infected plant material, rain splash, and very humid conditions.": "ينتشر عبر الرياح والمواد النباتية المصابة ورذاذ المطر والظروف عالية الرطوبة.",
    "Irregular water-soaked lesions, pale or yellowish edges, white cotton-like growth under leaves in high humidity, dark stem lesions, and brown greasy fruit spots.": "تظهر بقع غير منتظمة مشبعة بالماء، وحواف باهتة أو صفراء، ونمو أبيض قطني أسفل الأوراق عند ارتفاع الرطوبة، إضافة إلى بقع داكنة على الساق وبقع بنية دهنية على الثمار.",
    "Very high air humidity, cool-to-mild temperature, high moisture, and wet leaves may strongly increase risk. Soil pH and EC are indirect plant-stress factors.": "الرطوبة العالية جدًا، والحرارة الباردة إلى المعتدلة، وارتفاع الرطوبة، وابتلال الأوراق تزيد الخطر بشكل كبير. أما pH و EC فهما عوامل إجهاد غير مباشرة للنبات.",

    "Tiny pest organisms that feed on tomato leaves and tissues. They are pests, not fungal or bacterial diseases.": "كائنات آفات صغيرة تتغذى على أوراق وأنسجة البندورة. هي آفات وليست أمراضًا فطرية أو بكتيرية.",
    "Can enter through infected seedlings, nearby plants, workers, tools, wind, or plant contact. They spread faster when plants are stressed, warm, and dry.": "قد تدخل عبر الشتلات المصابة أو النباتات القريبة أو العمال أو الأدوات أو الرياح أو ملامسة النباتات. تنتشر بسرعة أكبر عندما تكون النباتات مجهدة والجو دافئًا وجافًا.",
    "Yellowing, curling, dry or brittle leaves, distortion, bronzing or russeting on leaves, stems, or fruits.": "اصفرار وتجعد وجفاف أو هشاشة في الأوراق، وتشوهات، وظهور لون برونزي أو بني محمر على الأوراق أو السيقان أو الثمار.",
    "High air temperature, low humidity, and low soil moisture may increase plant stress and make mite damage worse. High EC or abnormal pH may also weaken plants.": "ارتفاع حرارة الهواء وانخفاض الرطوبة وانخفاض رطوبة التربة قد تزيد إجهاد النبات وتفاقم ضرر الأكاروسات. كما أن ارتفاع EC أو اضطراب pH قد يضعف النباتات.",

    "A fungal tomato disease caused by Passalora fulva. It is especially common in greenhouses and mainly affects leaves.": "مرض فطري يصيب البندورة وتسببه Passalora fulva. ينتشر خاصة في البيوت البلاستيكية ويؤثر أساسًا في الأوراق.",
    "The fungus survives in crop debris, greenhouse surfaces, and soil. It spreads by spores and becomes severe with high humidity and poor ventilation.": "يبقى الفطر في بقايا المحصول وعلى أسطح البيت البلاستيكي وفي التربة. ينتشر بالأبواغ ويشتد عند ارتفاع الرطوبة وضعف التهوية.",
    "Pale green or yellow spots on upper leaf surfaces, with olive-green, gray, or brown mold growth on leaf undersides. Leaves may curl, dry, and fall.": "تظهر بقع خضراء باهتة أو صفراء على السطح العلوي للأوراق، مع نمو عفن زيتوني أو رمادي أو بني على السطح السفلي. قد تلتف الأوراق وتجف وتسقط.",
    "High air humidity, especially above 85–90%, and greenhouse temperatures around 20–25°C may support leaf mold. High soil moisture may indirectly raise humidity.": "الرطوبة العالية، خاصة فوق 85–90%، وحرارة البيت البلاستيكي حول 20–25°C قد تساعد على عفن الأوراق. كما أن ارتفاع رطوبة التربة قد يرفع الرطوبة بشكل غير مباشر.",

    "A viral tomato disease, commonly related to Tomato mosaic virus or Tobacco mosaic virus. Infected plants cannot be cured.": "مرض فيروسي يصيب البندورة ويرتبط غالبًا بفيروس موزاييك البندورة أو فيروس موزاييك التبغ. النباتات المصابة لا يمكن شفاؤها.",
    "Spreads through infected seeds, transplants, plant residues, hands, tools, clothing, and plant handling activities.": "ينتشر عبر البذور والشتلات وبقايا النباتات المصابة، وكذلك عبر الأيدي والأدوات والملابس وعمليات التعامل مع النبات.",
    "Light and dark green mosaic patterns, curled or narrow leaves, deformation, stunting, poor growth, and uneven fruit ripening.": "تظهر أنماط موزاييك خضراء فاتحة وداكنة، مع أوراق ملتفة أو ضيقة، وتشوه، وتقزم، وضعف في النمو، ونضج غير منتظم للثمار.",
    "The sensors do not directly cause mosaic virus. Abnormal temperature, moisture, pH, or EC can stress plants and make symptoms stronger or confused with nutrient problems.": "المستشعرات لا تسبب فيروس الموزاييك مباشرة. لكن اضطراب الحرارة أو الرطوبة أو pH أو EC قد يجهد النبات ويجعل الأعراض أقوى أو تختلط مع مشكلات التغذية.",

    "A fungal tomato disease caused by Septoria lycopersici. It mainly damages leaves and can cause severe defoliation.": "مرض فطري يصيب البندورة وتسببه Septoria lycopersici. يضر الأوراق بشكل أساسي وقد يسبب تساقطًا شديدًا للأوراق.",
    "Survives on infected debris, weeds, stakes, cages, and tools. It spreads by splashing water from rain or overhead irrigation.": "يبقى على البقايا المصابة والأعشاب والدعامات والأقفاص والأدوات. ينتشر عبر تناثر الماء الناتج عن المطر أو الري من الأعلى.",
    "Small circular spots on lower leaves with dark borders and gray or tan centers. Tiny black fruiting bodies may appear inside spots. Leaves yellow, dry, and fall.": "بقع دائرية صغيرة على الأوراق السفلية ذات حواف داكنة ومراكز رمادية أو بنية فاتحة. قد تظهر أجسام ثمرية سوداء صغيرة داخل البقع. تصفر الأوراق وتجف وتسقط.",
    "Warm air temperature, high humidity, long leaf wetness, and high soil moisture increase risk by supporting infection and splash dispersal.": "حرارة الهواء الدافئة والرطوبة العالية وبقاء الأوراق مبللة لفترة طويلة وارتفاع رطوبة التربة تزيد الخطر لأنها تدعم العدوى وانتشار الرذاذ.",

    "Small sap-sucking pests, commonly two-spotted spider mites, that damage tomato leaves by feeding on plant cells.": "آفات صغيرة ماصة للعصارة، غالبًا العنكبوت الأحمر ذو البقعتين، تضر أوراق البندورة بتغذيتها على خلايا النبات.",
    "Increase rapidly in hot, dry, and dusty conditions, especially when plants suffer drought stress or natural predators are reduced.": "تزداد بسرعة في الظروف الحارة والجافة والمغبرة، خاصة عندما تعاني النباتات من إجهاد الجفاف أو يقل وجود الأعداء الحيوية.",
    "Tiny yellow or white stippling spots, bronzing, drying leaves, leaf fall, and fine webbing on leaf undersides or between plant parts.": "نقاط صفراء أو بيضاء صغيرة، واصفرار أو برونزية، وجفاف الأوراق وتساقطها، ووجود خيوط دقيقة أسفل الأوراق أو بين أجزاء النبات.",
    "High air temperature, low humidity, and low soil moisture are strong warning signs. High EC, abnormal pH, or stressful soil temperature may weaken the plant.": "ارتفاع حرارة الهواء وانخفاض الرطوبة وانخفاض رطوبة التربة مؤشرات تحذيرية قوية. كما أن ارتفاع EC أو اضطراب pH أو حرارة التربة المجهدة قد تضعف النبات.",

    "A serious viral tomato disease, commonly Tomato Yellow Leaf Curl Virus, that can greatly reduce growth and yield.": "مرض فيروسي خطير يصيب البندورة، ويعرف غالبًا بفيروس تجعد واصفرار أوراق البندورة، ويمكن أن يقلل النمو والإنتاج بشكل كبير.",
    "Mainly transmitted by whiteflies. It can also enter through infected seedlings or infected host plants.": "ينتقل أساسًا بواسطة الذباب الأبيض، وقد يدخل أيضًا عبر الشتلات المصابة أو النباتات العائلة المصابة.",
    "Young leaves become small, yellow, and curled upward. Plants become stunted, shoots grow upright, and fruit set is reduced.": "تصبح الأوراق الحديثة صغيرة وصفراء وملتفة للأعلى. تتقزم النباتات وتنمو الأفرع للأعلى ويقل عقد الثمار.",
    "Sensors do not directly cause the virus, but warm temperature may support whitefly activity. Low moisture, abnormal pH, or high EC can increase plant stress.": "المستشعرات لا تسبب الفيروس مباشرة، لكن الحرارة الدافئة قد تدعم نشاط الذباب الأبيض. كما أن انخفاض الرطوبة واضطراب pH أو ارتفاع EC قد يزيد إجهاد النبات.",

    "A bacterial tomato disease caused by Xanthomonas species. It can affect leaves, stems, flowers, and fruits.": "مرض بكتيري يصيب البندورة وتسببه أنواع Xanthomonas. يمكن أن يؤثر في الأوراق والسيقان والأزهار والثمار.",
    "May come from infected seeds, transplants, crop debris, and volunteer plants. It spreads by splashing water, overhead irrigation, handling, and wounds.": "قد يأتي من البذور أو الشتلات أو بقايا المحصول أو النباتات المتطوعة المصابة. ينتشر عبر تناثر الماء والري من الأعلى والملامسة والجروح.",
    "Small dark water-soaked leaf spots that become brown or black, sometimes with yellow halos. Fruits may develop raised, rough, scabby, or dark spots.": "بقع ورقية صغيرة داكنة مشبعة بالماء تصبح بنية أو سوداء، وأحيانًا مع هالات صفراء. قد تظهر على الثمار بقع مرتفعة أو خشنة أو قشرية أو داكنة.",
    "Warm air temperature, high humidity, high soil moisture, and wet conditions may support spread. pH and EC mainly affect plant stress, not direct bacterial infection.": "حرارة الهواء الدافئة والرطوبة العالية وارتفاع رطوبة التربة والظروف الرطبة قد تدعم الانتشار. يؤثر pH و EC غالبًا في إجهاد النبات، وليس في العدوى البكتيرية مباشرة.",

    # Sensor reason texts from YOLO app.py
    "High humidity can support leaf wetness and Early Blight spread.": "الرطوبة العالية قد تساعد على بقاء الأوراق مبللة وانتشار اللفحة المبكرة.",
    "Warm temperature can favor Early Blight development.": "الحرارة الدافئة قد تساعد على تطور اللفحة المبكرة.",
    "High moisture can increase humidity and water splash around lower leaves.": "ارتفاع الرطوبة قد يزيد رطوبة الجو وتناثر الماء حول الأوراق السفلية.",
    "Abnormal pH can stress tomato plants and increase disease severity.": "اضطراب pH قد يجهد نباتات البندورة ويزيد شدة المرض.",
    "Abnormal EC can indicate nutrient/salinity stress or sensor calibration issue.": "اضطراب EC قد يدل على إجهاد غذائي/ملحي أو مشكلة في معايرة المستشعر.",
    "Very high humidity is a major Late Blight warning signal.": "الرطوبة العالية جدًا مؤشر تحذيري مهم للّفحة المتأخرة.",
    "Cool-to-mild temperature can be favorable for Late Blight when humidity is high.": "الحرارة الباردة إلى المعتدلة قد تكون مناسبة للّفحة المتأخرة عند ارتفاع الرطوبة.",
    "High moisture can support wet conditions and disease spread.": "ارتفاع الرطوبة قد يدعم الظروف الرطبة وانتشار المرض.",
    "Very high humidity is the most important Leaf Mold risk factor.": "الرطوبة العالية جدًا هي أهم عامل خطر لعفن الأوراق.",
    "This greenhouse temperature range can support Leaf Mold when humidity is high.": "هذا المجال من حرارة البيت البلاستيكي قد يدعم عفن الأوراق عند ارتفاع الرطوبة.",
    "High moisture can increase humidity around tomato plants.": "ارتفاع رطوبة التربة قد يزيد الرطوبة حول نباتات البندورة.",
    "High humidity and leaf wetness can support Septoria infection.": "الرطوبة العالية وابتلال الأوراق قد يدعمان عدوى تبقع سبتوريا.",
    "This temperature range can be favorable for Septoria development.": "هذا المجال الحراري قد يكون مناسبًا لتطور تبقع سبتوريا.",
    "High moisture increases splash dispersal from soil or lower leaves.": "الرطوبة العالية تزيد انتشار الرذاذ من التربة أو الأوراق السفلية.",
    "High humidity and wet leaves can support Bacterial Spot spread.": "الرطوبة العالية وابتلال الأوراق قد يدعمان انتشار التبقع البكتيري.",
    "Warm temperature can be favorable for Bacterial Spot development.": "الحرارة الدافئة قد تكون مناسبة لتطور التبقع البكتيري.",
    "High moisture can increase splash spread and leaf wetness.": "الرطوبة العالية قد تزيد انتشار الرذاذ وابتلال الأوراق.",
    "High temperature can support mite activity and faster reproduction.": "ارتفاع الحرارة قد يدعم نشاط الأكاروسات وتكاثرها بسرعة.",
    "Low humidity can favor mite problems and dry plant stress.": "انخفاض الرطوبة قد يساعد على مشاكل الأكاروسات وإجهاد الجفاف.",
    "Low soil moisture stresses tomato plants and can make mite damage worse.": "انخفاض رطوبة التربة يجهد نباتات البندورة وقد يزيد ضرر الأكاروسات.",
    "Abnormal EC can increase plant stress.": "اضطراب EC قد يزيد إجهاد النبات.",
    "Abnormal pH can increase plant stress.": "اضطراب pH قد يزيد إجهاد النبات.",
    "Warm temperature can support whitefly activity, which spreads this virus.": "الحرارة الدافئة قد تدعم نشاط الذباب الأبيض الذي ينقل هذا الفيروس.",
    "Low moisture can weaken infected tomato plants.": "انخفاض الرطوبة قد يضعف نباتات البندورة المصابة.",
    "Abnormal temperature can stress plants and make viral symptoms stronger.": "اضطراب الحرارة قد يجهد النباتات ويجعل الأعراض الفيروسية أقوى.",
    "Abnormal moisture can stress tomato plants and confuse symptoms with nutrient problems.": "اضطراب الرطوبة قد يجهد نباتات البندورة ويجعل الأعراض تختلط مع مشكلات التغذية.",
    "Abnormal pH can cause nutrient stress and stronger symptoms.": "اضطراب pH قد يسبب إجهادًا غذائيًا وأعراضًا أقوى.",
    "Abnormal EC can indicate nutrient/salinity stress or calibration issue.": "اضطراب EC قد يدل على إجهاد غذائي/ملحي أو مشكلة معايرة.",

    # Weather app.py disease basic advice
    "Remove infected leaves quickly.": "أزل الأوراق المصابة بسرعة.",
    "Keep foliage dry.": "حافظ على جفاف المجموع الخضري.",
    "Avoid working with wet plants.": "تجنّب العمل على النباتات وهي مبللة.",
    "Inspect leaf undersides.": "افحص السطح السفلي للأوراق.",
    "Reduce plant stress.": "قلّل إجهاد النبات.",
    "Remove badly damaged leaves.": "أزل الأوراق المتضررة بشدة.",
    "Use safe mite control if needed.": "استخدم مكافحة آمنة للأكاروسات عند الحاجة.",
    "Reduce humidity.": "خفّض الرطوبة.",
    "Remove infected leaves.": "أزل الأوراق المصابة.",
    "Avoid wetting leaves.": "تجنّب تبليل الأوراق.",
    "Remove strongly infected plants.": "أزل النباتات شديدة الإصابة.",
    "Disinfect tools.": "عقّم الأدوات.",
    "Control insects.": "كافح الحشرات.",
    "Do not touch healthy plants after infected plants.": "لا تلمس النباتات السليمة بعد لمس النباتات المصابة.",
    "Check leaf undersides.": "افحص السطح السفلي للأوراق.",
    "Reduce heat and dry stress.": "قلّل إجهاد الحرارة والجفاف.",
    "Remove damaged leaves.": "أزل الأوراق المتضررة.",
    "Control whiteflies.": "كافح الذباب الأبيض.",
    "Remove severely infected plants.": "أزل النباتات شديدة الإصابة.",
    "Use insect-proof netting if possible.": "استخدم شبكًا مانعًا للحشرات إذا أمكن.",
    "Avoid moving infected material.": "تجنّب نقل المواد النباتية المصابة.",
    "Use disease-free seeds and seedlings.": "استخدم بذورًا وشتلات خالية من المرض.",
    "Remove infected debris.": "أزل بقايا النباتات المصابة.",
    "Disinfect tools and avoid working with wet plants.": "عقّم الأدوات وتجنّب العمل على النباتات وهي مبللة.",
    "Continue normal monitoring.": "استمر بالمراقبة الطبيعية.",
    "Keep regular irrigation and ventilation.": "حافظ على انتظام الري والتهوية.",
    "Retake clearer close leaf images.": "أعد التقاط صور قريبة وواضحة للأوراق.",
    "Use good lighting.": "استخدم إضاءة جيدة.",
}



# V23 strict Arabic dictionary for remaining source-app text.
ARABIC_V23_STRICT_PHRASES = {
    # Report remaining mixed phrases
    "Keep foliage dry and improve ventilation.": "حافظ على جفاف المجموع الخضري وحسّن التهوية.",
    "Keep foliage dry and improve airflow.": "حافظ على جفاف المجموع الخضري وحسّن حركة الهواء.",
    "Keep foliage dry and improve greenhouse ventilation.": "حافظ على جفاف المجموع الخضري وحسّن تهوية البيت البلاستيكي.",
    "Keep foliage dry and": "حافظ على جفاف المجموع الخضري و",
    "Keep foliage dry": "حافظ على جفاف المجموع الخضري",
    "Avoid handling plants while wet.": "تجنّب التعامل مع النباتات وهي مبللة.",
    "Avoid handling plants while wet": "تجنّب التعامل مع النباتات وهي مبللة",
    "Avoid working with plants when leaves are wet.": "تجنّب العمل على النباتات عندما تكون الأوراق مبللة.",
    "Avoid working with wet plants.": "تجنّب العمل على النباتات وهي مبللة.",
    "Inspect leaf undersides for mites/webbing.": "افحص السطح السفلي للأوراق بحثًا عن الأكاروسات أو الخيوط العنكبوتية.",
    "Inspect leaf undersides for mites or webbing.": "افحص السطح السفلي للأوراق بحثًا عن الأكاروسات أو الخيوط العنكبوتية.",
    "Inspect the underside of leaves regularly.": "افحص السطح السفلي للأوراق بانتظام.",
    "Remove heavily damaged leaves.": "أزل الأوراق شديدة الضرر.",
    "Remove badly damaged leaves.": "أزل الأوراق شديدة الضرر.",
    "Remove badly damaged leaves and use safe mite control if infestation increases.": "أزل الأوراق شديدة الضرر واستخدم مكافحة آمنة للأكاروسات إذا زادت الإصابة.",
    "Use safe mite control if needed.": "استخدم مكافحة آمنة للأكاروسات عند الحاجة.",
    "Use biological control or suitable miticide if infestation is severe.": "استخدم المكافحة الحيوية أو مبيد أكاروسات مناسب إذا كانت الإصابة شديدة.",
    "Use biological control or proper miticide if needed.": "استخدم المكافحة الحيوية أو مبيد أكاروسات مناسب عند الحاجة.",
    "Preserve beneficial insects.": "حافظ على الحشرات النافعة.",
    "Wash mites off plants when possible.": "اغسل الأكاروسات عن النباتات عندما يكون ذلك ممكنًا.",
    "Avoid drought stress and reduce dust.": "تجنّب إجهاد الجفاف وقلّل الغبار.",
    "Isolate affected plants and remove heavily infested leaves.": "اعزل النباتات المصابة وأزل الأوراق شديدة الإصابة.",
    "Keep the greenhouse clean.": "حافظ على نظافة البيت البلاستيكي.",
    "Avoid drought stress.": "تجنّب إجهاد الجفاف.",

    # Disease-specific report phrases from Weather App
    "No critical matched sensor driver was found now; continue disease-specific control and monitoring.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
    "No critical matched sensor driver was found now": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن",
    "continue disease-specific control and monitoring.": "استمر بتطبيق إجراءات المرض والمراقبة.",
    "disease-specific control and monitoring": "إجراءات المرض والمراقبة",
    "critical matched sensor driver": "قراءة مستشعرات حرجة مرتبطة بالمرض",
    "Critical matched sensor driver": "قراءة مستشعرات حرجة مرتبطة بالمرض",
    "driver": "مؤشر",
    "Scientific procedures:": "إجراءات علمية:",
    "Matched sensor warnings that can support disease risk or plant stress:": "تحذيرات المستشعرات المطابقة التي قد تدعم خطر المرض أو إجهاد النبات:",
    "Meaning:": "المعنى:",
    "Farmer action:": "إجراء المزارع:",

    # Late blight scientific/action text
    "Remove infected plants or leaves quickly.": "أزل النباتات أو الأوراق المصابة بسرعة.",
    "Remove infected leaves quickly and isolate severe plants.": "أزل الأوراق المصابة بسرعة واعزل النباتات شديدة الإصابة.",
    "Increase ventilation and reduce humidity.": "زِد التهوية وخفّض الرطوبة.",
    "Avoid wetting tomato leaves.": "تجنّب تبليل أوراق البندورة.",
    "Remove volunteer tomatoes or potatoes.": "أزل نباتات البندورة أو البطاطا المتطوعة.",
    "Apply protective treatment if late blight risk is high.": "طبّق علاجًا وقائيًا إذا كان خطر اللفحة المتأخرة مرتفعًا.",

    # Leaf mites / spider mites text
    "Tiny pest organisms that feed on tomato leaves and tissues. They are pests, not fungal or bacterial diseases.": "كائنات آفات صغيرة تتغذى على أوراق وأنسجة البندورة. هي آفات وليست أمراضًا فطرية أو بكتيرية.",
    "Can enter through infected seedlings, nearby plants, workers, tools, wind, or plant contact. They spread faster when plants are stressed, warm, and dry.": "قد تدخل عبر الشتلات المصابة أو النباتات القريبة أو العمال أو الأدوات أو الرياح أو ملامسة النباتات. تنتشر بسرعة أكبر عندما تكون النباتات مجهدة والجو دافئًا وجافًا.",
    "Yellowing, curling, dry or brittle leaves, distortion, bronzing or russeting on leaves, stems, or fruits.": "اصفرار وتجعد وجفاف أو هشاشة في الأوراق، وتشوهات، وظهور لون برونزي أو بني محمر على الأوراق أو السيقان أو الثمار.",
    "High air temperature, low humidity, and low soil moisture may increase plant stress and make mite damage worse. High EC or abnormal pH may also weaken plants.": "ارتفاع حرارة الهواء وانخفاض الرطوبة وانخفاض رطوبة التربة قد يزيد إجهاد النبات ويجعل ضرر الأكاروسات أسوأ. كما أن ارتفاع EC أو اضطراب pH قد يضعف النباتات.",
    "Small sap-sucking pests, commonly two-spotted spider mites, that damage tomato leaves by feeding on plant cells.": "آفات صغيرة ماصة للعصارة، غالبًا العنكبوت الأحمر ذو البقعتين، تضر أوراق البندورة بتغذيتها على خلايا النبات.",
    "Increase rapidly in hot, dry, and dusty conditions, especially when plants suffer drought stress or natural predators are reduced.": "تزداد بسرعة في الظروف الحارة والجافة والمغبرة، خاصة عندما تعاني النباتات من إجهاد الجفاف أو يقل وجود الأعداء الحيوية.",
    "Tiny yellow or white stippling spots, bronzing, drying leaves, leaf fall, and fine webbing on leaf undersides or between plant parts.": "نقاط صفراء أو بيضاء صغيرة، واصفرار أو برونزية، وجفاف الأوراق وتساقطها، ووجود خيوط دقيقة أسفل الأوراق أو بين أجزاء النبات.",
    "High air temperature, low humidity, and low soil moisture are strong warning signs. High EC, abnormal pH, or stressful soil temperature may weaken the plant.": "ارتفاع حرارة الهواء وانخفاض الرطوبة وانخفاض رطوبة التربة مؤشرات تحذيرية قوية. كما أن ارتفاع EC أو اضطراب pH أو حرارة التربة المجهدة قد تضعف النبات.",

    # Leaf mold and other source strings
    "Improve ventilation and reduce humidity.": "حسّن التهوية وخفّض الرطوبة.",
    "Increase plant spacing and prune dense foliage.": "زِد المسافة بين النباتات وقم بتقليم النمو الكثيف.",
    "Clean greenhouse surfaces after the season.": "نظّف أسطح البيت البلاستيكي بعد انتهاء الموسم.",
    "Avoid wet leaves and plant crowding.": "تجنّب ابتلال الأوراق وازدحام النباتات.",
    "Reduce humidity and increase ventilation.": "خفّض الرطوبة وزِد التهوية.",
    "Improve airflow and reduce leaf wetness.": "حسّن حركة الهواء وقلّل ابتلال الأوراق.",
    "Disinfect tools and remove infected leaves.": "عقّم الأدوات وأزل الأوراق المصابة.",
    "Control whiteflies immediately.": "كافح الذباب الأبيض فورًا.",
    "Use insect-proof netting when possible.": "استخدم شبكًا مانعًا للحشرات عند الإمكان.",
    "Do not move infected plant material between nodes.": "لا تنقل مواد نباتية مصابة بين العقد.",
    "Disinfect tools and hands after handling infected plants.": "عقّم الأدوات واليدين بعد التعامل مع النباتات المصابة.",
    "Control insects and avoid touching healthy plants after infected ones.": "كافح الحشرات وتجنّب لمس النباتات السليمة بعد النباتات المصابة.",

    # Critical sensor reason phrases
    "Cool-to-mild temperature can be favorable for Late Blight when humidity is high.": "الحرارة الباردة إلى المعتدلة قد تكون مناسبة للّفحة المتأخرة عند ارتفاع الرطوبة.",
    "High moisture can support wet conditions and disease spread.": "ارتفاع الرطوبة قد يدعم الظروف الرطبة وانتشار المرض.",
    "High humidity and leaf wetness can support Septoria infection.": "الرطوبة العالية وابتلال الأوراق قد يدعمان عدوى تبقع سبتوريا.",
    "This temperature range can be favorable for Septoria development.": "هذا المجال الحراري قد يكون مناسبًا لتطور تبقع سبتوريا.",
    "High moisture increases splash dispersal from soil or lower leaves.": "ارتفاع الرطوبة يزيد انتشار الرذاذ من التربة أو الأوراق السفلية.",
    "High humidity and wet leaves can support Bacterial Spot spread.": "الرطوبة العالية وابتلال الأوراق قد يدعمان انتشار التبقع البكتيري.",
    "Warm temperature can be favorable for Bacterial Spot development.": "الحرارة الدافئة قد تكون مناسبة لتطور التبقع البكتيري.",
    "High moisture can increase splash spread and leaf wetness.": "ارتفاع الرطوبة قد يزيد انتشار الرذاذ وابتلال الأوراق.",
    "High temperature can support mite activity and faster reproduction.": "ارتفاع الحرارة قد يدعم نشاط الأكاروسات وتكاثرها بسرعة.",
    "Low humidity can favor mite problems and dry plant stress.": "انخفاض الرطوبة قد يساعد على مشاكل الأكاروسات وإجهاد الجفاف.",
    "Low soil moisture stresses tomato plants and can make mite damage worse.": "انخفاض رطوبة التربة يجهد نباتات البندورة وقد يزيد ضرر الأكاروسات.",
    "Warm temperature can support whitefly activity, which spreads this virus.": "الحرارة الدافئة قد تدعم نشاط الذباب الأبيض الذي ينقل هذا الفيروس.",
    "Low moisture can weaken infected tomato plants.": "انخفاض الرطوبة قد يضعف نباتات البندورة المصابة.",
    "Abnormal temperature can stress plants and make viral symptoms stronger.": "اضطراب الحرارة قد يجهد النباتات ويجعل الأعراض الفيروسية أقوى.",
    "Abnormal moisture can stress tomato plants and confuse symptoms with nutrient problems.": "اضطراب الرطوبة قد يجهد نباتات البندورة ويجعل الأعراض تختلط مع مشاكل التغذية.",
    "Abnormal pH can cause nutrient stress and stronger symptoms.": "اضطراب pH قد يسبب إجهادًا غذائيًا وأعراضًا أقوى.",
}



# V24 exact phrases from the latest report output.
ARABIC_V24_LATEST_REPORT_PHRASES = {
    "Keep foliage dry and improve ventilation.": "حافظ على جفاف المجموع الخضري وحسّن التهوية.",
    "Avoid handling plants while wet.": "تجنّب التعامل مع النباتات وهي مبللة.",
    "Inspect leaf undersides for mites/webbing.": "افحص السطح السفلي للأوراق بحثًا عن الأكاروسات أو الخيوط العنكبوتية.",
    "Remove heavily damaged leaves.": "أزل الأوراق شديدة الضرر.",
    "No critical matched sensor driver was found now; continue disease-specific control and monitoring.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
    "No critical matched sensor driver was found now": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن",
}


def safe_english_replace(text, replacements):
    # Replace full English words/phrases only. This prevents:
    # Monitor -> Monitأو, Correct -> Cأوrect, INFORMATION -> INFORMATIتشغيل.
    for en in sorted(replacements, key=len, reverse=True):
        ar = replacements[en]
        pattern = r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])"
        text = re.sub(pattern, ar, text, flags=re.IGNORECASE)
    return text


def arabic_final_cleanup(text):
    # Fix outputs produced by older versions if they appear in the message.
    fixes = {
        "Monitأو EC والري": "راقب قيمة EC ونظام الري",
        "Monitأو EC": "راقب قيمة EC",
        "Cأوrect pH carefully": "صحّح قيمة pH بحذر",
        "Sensأو Thing": "قراءات المستشعرات",
        "معلومات الطقسRMATIتشغيل": "🌤 معلومات الطقس",
        "Outside الحرارةerature": "درجة الحرارة الخارجية",
        "Outside الرطوبة": "الرطوبة الخارجية",
        "الرياح Speed": "سرعة الرياح",
        "Weather الحالة": "حالة الطقس",
        "Tomato Weather خطر": "مخاطر الطقس على البندورة",
        "Farmer procedures": "إجراءات المزارع",
        "مرتفع humidity may increase disease risk if leaves stay wet.": "الرطوبة المرتفعة قد تزيد خطر الأمراض إذا بقيت الأوراق مبللة.",
        "Inspect lower leaves fأو spots أو mold.": "افحص الأوراق السفلية بحثًا عن بقع أو عفن.",
        "Latest البيت البلاستيكي": "آخر بيت بلاستيكي",
        "Latest Live العقدة": "آخر عقدة مباشرة",
        "العقدة update": "وقت تحديث العقدة",
        "المرض المطابق نتيجة": "نتيجة المرض المطابق",
        "مخاطر الطقس ملخص": "ملخص مخاطر الطقس",
        "تحذير first": "تحذير أولًا",
        "خطير أو 🟡 تحذير أولًا.": "خطير أو 🟡 تحذير.",
        "تبقع سبتوريا تبقع الأوراق": "تبقع سبتوريا",
        "✅ تم تحديث الطقسRMATIتشغيل": "✅ تم تحديث الطقس",
    }
    for bad, good in fixes.items():
        text = text.replace(bad, good)


    # Extra V20 cleanup for mixed English that may arrive from Weather App or YOLO App.
    extra_fixes = {
        "Keep leaves dry؛ avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
        "Keep leaves dry; avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
        "🏠 البيت البلاستيكي / Plastic House": "🏠 البيت البلاستيكي",
        "🍅 Crop: Tomato": "🍅 المحصول: البندورة",
        "🚨 DISEASE RESULT": "🚨 نتيجة المرض",
        "Average نسبة الثقة": "متوسط نسبة الثقة",
        "🌿 SENSOR MATCH STATUS": "🌿 حالة مطابقة المستشعرات",
        "⚪ No matched sensor link was added.": "⚪ لم تتم إضافة ربط مطابق مع قراءات المستشعرات.",
        "The system checked both:": "فحص النظام المصدرين التاليين:",
        "1️⃣ allNodesData history": "1️⃣ سجل قراءات جميع العقد",
        "2️⃣ latest live sensor variables": "2️⃣ آخر قراءات مباشرة من المستشعرات",
        "قراءات المستشعرات are linked to the disease alert only when the selected صورة greenhouse/plastic-house ID and node ID both match the sensor record.": "يتم ربط قراءات المستشعرات بتنبيه المرض فقط عندما يتطابق رقم البيت البلاستيكي ورقم العقدة في الصورة مع سجل المستشعرات.",
        "Latest live sensor record:": "آخر سجل مباشر للمستشعرات:",
        "📚 SCIENTIFIC INFORMATION FOR ALL DETECTED DISEASES": "📚 معلومات علمية عن الأمراض المكتشفة",
        "📌 Definition:": "📌 التعريف:",
        "🧬 Causes / Spread:": "🧬 الأسباب وطريقة الانتشار:",
        "🔎 Main Symptoms:": "🔎 الأعراض الرئيسية:",
        "📡 Related sensor indicators:": "📡 المؤشرات المرتبطة بالمستشعرات:",
        "📊 حرج sensor readings:": "📊 قراءات المستشعرات الحرجة:",
        "⚪ Not linked because greenhouse/plastic-house ID and node ID did not both match the sensor record.": "⚪ غير مرتبط لأن رقم البيت البلاستيكي ورقم العقدة لا يتطابقان مع سجل المستشعرات.",
        "👨‍🌾 FARMER ACTIONS BASED تشغيل DETECTED DISEASES AND CRITICAL SENSOR READINGS": "👨‍🌾 إجراءات المزارع بناءً على الأمراض المكتشفة وقراءات المستشعرات الحرجة",
        "• Improve spacing and greenhouse ventilation.": "• حسّن المسافات بين النباتات وتهوية البيت البلاستيكي.",
        "• Avoid overhead watering and keep leaves dry.": "• تجنّب الري من الأعلى وحافظ على جفاف الأوراق.",
        "• Monitor nearby tomato plants and apply suitable treatment if infection spreads.": "• راقب نباتات البندورة القريبة وطبّق العلاج المناسب إذا انتشرت الإصابة.",
        "• قراءات المستشعرات were not linked because greenhouse/plastic-house ID and node ID did not both match؛ verify the selected node and sensor source.": "• لم يتم ربط قراءات المستشعرات لأن رقم البيت البلاستيكي ورقم العقدة لا يتطابقان مع سجل المستشعرات؛ تأكد من العقدة المختارة ومصدر القراءات.",
        "🖼 Tomato Disease Image Result": "🖼 نتيجة صورة مرض البندورة",
        "A common fungal tomato disease, mainly caused by Alternaria species. It usually starts on older lower leaves and may spread to stems and fruits.": "مرض فطري شائع في البندورة، تسببه غالبًا فطريات Alternaria. يبدأ عادةً على الأوراق السفلية القديمة وقد ينتشر إلى السيقان والثمار.",
        "Survives in مصابة plant debris, soil, and volunteer tomato plants. It spreads through splashing water, rain, overhead irrigation, wind, and contaminated tools.": "يبقى في بقايا النباتات المصابة والتربة ونباتات البندورة المتطوعة. ينتشر عبر تناثر الماء والأمطار والري من الأعلى والرياح والأدوات الملوثة.",
        "Dark brown circular spots, often with a target أو bull's-eye pattern. Leaves may turn yellow, dry, and fall.": "بقع دائرية بنية داكنة، غالبًا بشكل حلقات تشبه الهدف. قد تصفر الأوراق ثم تجف وتسقط.",
        "رطوبة الهواء, حرارة الهواء, رطوبة التربة, حموضة التربة pH/EC as stress factors": "رطوبة الهواء، حرارة الهواء، رطوبة التربة، و pH/EC كعوامل إجهاد للنبات.",
        "تم الكشف عن الصور": "الصور التي تم الكشف فيها",
        "المجموع الصور": "إجمالي الصور",
        "مصابة الصور": "الصور المصابة",
        "سليمة الصور": "الصور السليمة",
        "لا يوجد كشف الصور": "صور بدون كشف",
    }
    for bad, good in extra_fixes.items():
        text = text.replace(bad, good)

    # Remove duplicated leading emojis/titles caused by source title + translation title.
    text = re.sub(r"^(📋)\s+\1\s+", r"\1 ", text, flags=re.MULTILINE)
    text = re.sub(r"^(🦠)\s+\1\s+", r"\1 ", text, flags=re.MULTILINE)
    text = re.sub(r"^(🌤)\s+\1\s+", r"\1 ", text, flags=re.MULTILINE)

    # Clean remaining common English punctuation/labels.
    text = text.replace("Problem:", "المشكلة:")
    text = text.replace("Action:", "الإجراء:")
    text = text.replace("Detected:", "تم الكشف عن:")
    text = text.replace("Most likely:", "الأكثر احتمالًا:")
    text = text.replace("images:", "عدد الصور:")
    text = text.replace("— الصور:", "— عدد الصور:")
    text = text.replace("— images:", "— عدد الصور:")
    text = text.replace("total ", "المجموع ")
    text = text.replace("infected ", "مصابة ")
    text = text.replace("healthy ", "سليمة ")
    text = text.replace("no detection ", "لا يوجد كشف ")
    text = text.replace(" ;", "؛")
    text = text.replace("; ", "؛ ")
    text = text.replace(" → ", " ← ")

    # Arabic tidy-up.
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # V21 exact cleanup for remaining mixed Arabic/English phrases.
    v21_fixes = {
        "Very رطوبة مرتفعة can support fungal diseases such as عفن الأوراق, اللفحة المتأخرة, and تبقع سبتوريا.": "الرطوبة العالية جدًا قد تساعد على انتشار أمراض فطرية مثل عفن الأوراق واللفحة المتأخرة وتبقع سبتوريا.",
        "Very الرطوبة المرتفعة can support fungal diseases such as عفن الأوراق, اللفحة المتأخرة, and تبقع سبتوريا.": "الرطوبة العالية جدًا قد تساعد على انتشار أمراض فطرية مثل عفن الأوراق واللفحة المتأخرة وتبقع سبتوريا.",
        "حسّن التهوية. when آمن.": "حسّن التهوية عندما يكون ذلك آمنًا.",
        "حسّن التهوية. عندما يكون ذلك آمنًا.": "حسّن التهوية عندما يكون ذلك آمنًا.",
        "حافظ على جفاف الأوراق؛ avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
        "Keep leaves dry؛ avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
        "Keep leaves dry; avoid overhead watering.": "حافظ على جفاف الأوراق؛ وتجنّب الري من الأعلى.",
        "📋 📋": "📋",
        "🦠 🦠": "🦠",
        "🌤 🌤": "🌤",
    }
    for bad, good in v21_fixes.items():
        text = text.replace(bad, good)


    # V22 cleanup for remaining mixed phrases from disease/weather source apps.
    v22_fixes = {
        "🌿 MATCHED قراءات المستشعرات": "🌿 قراءات المستشعرات المطابقة",
        "🟢 Check range": "🟢 تحقق من المجال",
        "🔴 High الخطر": "🔴 خطر مرتفع",
        "🟡 Check sensor/nutrients": "🟡 تحقق من المستشعر أو المغذيات",
        "Remove مصابة plants أو leaves quickly.": "أزل النباتات أو الأوراق المصابة بسرعة.",
        "Apply protective treatment if اللفحة المتأخرة الخطر is مرتفع.": "طبّق علاجًا وقائيًا إذا كان خطر اللفحة المتأخرة مرتفعًا.",
        "Increase ventilation and reduce الرطوبة.": "زِد التهوية وخفّض الرطوبة.",
        "Avoid wetting البندورة leaves.": "تجنّب تبليل أوراق البندورة.",
        "Remove volunteer tomatoes أو potatoes.": "أزل نباتات البندورة أو البطاطا المتطوعة.",
        "Wash mites إيقاف plants when possible.": "اغسل الأكاروسات عن النباتات عندما يكون ذلك ممكنًا.",
        "Use biological control أو proper miticide if needed.": "استخدم المكافحة الحيوية أو مبيد أكاروسات مناسب عند الحاجة.",
        "Avoid drought stress and reduce dust.": "تجنّب إجهاد الجفاف وقلّل الغبار.",
        "Preserve beneficial insects.": "حافظ على الحشرات النافعة.",
        "Inspect leaf undersides.": "افحص السطح السفلي للأوراق.",
        "Check leaf undersides.": "افحص السطح السفلي للأوراق.",
        "Cool-to-mild درجة الحرارة can be favorable for اللفحة المتأخرة when الرطوبة is مرتفع.": "الحرارة الباردة إلى المعتدلة قد تكون مناسبة للّفحة المتأخرة عند ارتفاع الرطوبة.",
        "Abnormal EC can increase plant stress.": "اضطراب EC قد يزيد إجهاد النبات.",
        "Abnormal pH can increase plant stress.": "اضطراب pH قد يزيد إجهاد النبات.",
        "Small sap-sucking pests, commonly two-spotted العناكب الحمراء, that damage البندورة leaves by feeding تشغيل plant cells.": "آفات صغيرة ماصة للعصارة، غالبًا العنكبوت الأحمر ذو البقعتين، تضر أوراق البندورة بتغذيتها على خلايا النبات.",
        "Increase rapidly in hot, dry, and dusty conditions, especially when plants suffer drought stress أو natural predators are reduced.": "تزداد بسرعة في الظروف الحارة والجافة والمغبرة، خاصة عندما تعاني النباتات من إجهاد الجفاف أو يقل وجود الأعداء الحيوية.",
        "Tiny yellow أو white stippling spots, bronzing, drying leaves, leaf fall, and fine webbing تشغيل leaf undersides أو between plant parts.": "نقاط صفراء أو بيضاء صغيرة، واصفرار أو برونزية، وجفاف الأوراق وتساقطها، ووجود خيوط دقيقة أسفل الأوراق أو بين أجزاء النبات.",
        "A very destructive البندورة disease caused by Phytophthora infestans. It can spread quickly under favorable cool, wet, and humid conditions.": "مرض مدمر جدًا يصيب البندورة وتسببه Phytophthora infestans. ينتشر بسرعة عند توفر ظروف باردة نسبيًا ورطبة ومشبعة بالرطوبة.",
        "Spreads through الرياح, مصابة plant material, rain splash, and very humid conditions.": "ينتشر عبر الرياح والمواد النباتية المصابة ورذاذ المطر والظروف عالية الرطوبة.",
        "Irregular water-soaked lesions, pale أو yellowish edges, white cotton-like growth under leaves in رطوبة مرتفعة, dark stem lesions, and brown greasy fruit spots.": "تظهر بقع غير منتظمة مشبعة بالماء، وحواف باهتة أو صفراء، ونمو أبيض قطني أسفل الأوراق عند ارتفاع الرطوبة، إضافة إلى بقع داكنة على الساق وبقع بنية دهنية على الثمار.",
        "حرارة الهواء, رطوبة الهواء, رطوبة التربة, ملوحة/توصيل التربة EC/pH كعوامل إجهاد للنبات": "حرارة الهواء، رطوبة الهواء، رطوبة التربة، و EC/pH كعوامل إجهاد للنبات.",
        "رطوبة الهواء, حرارة الهواء, رطوبة التربة": "رطوبة الهواء، حرارة الهواء، رطوبة التربة.",
        "حرارة الهواء, رطوبة الهواء, رطوبة التربة, حموضة التربة pH/EC كعوامل إجهاد للنبات": "حرارة الهواء، رطوبة الهواء، رطوبة التربة، و pH/EC كعوامل إجهاد للنبات.",
        "حسّن التهوية..": "حسّن التهوية.",
        "🖼 🖼": "🖼",
    }
    for bad, good in v22_fixes.items():
        text = text.replace(bad, good)


    # V23 final strict cleanup for phrases that can become partially translated.
    v23_fixes = {
        "Keep foliage dry and حسّن التهوية.": "حافظ على جفاف المجموع الخضري وحسّن التهوية.",
        "Keep foliage dry and حسّن حركة الهواء.": "حافظ على جفاف المجموع الخضري وحسّن حركة الهواء.",
        "Avoid handling plants while wet.": "تجنّب التعامل مع النباتات وهي مبللة.",
        "Inspect leaf undersides for mites/webbing.": "افحص السطح السفلي للأوراق بحثًا عن الأكاروسات أو الخيوط العنكبوتية.",
        "Remove heavily damaged leaves.": "أزل الأوراق شديدة الضرر.",
        "No حرج matched sensor driver was found now؛ continue disease-specific control and monitoring.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        "No حرج matched sensor مؤشر was found now؛ continue disease-specific control and monitoring.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        "No حرج matched sensor مؤشر was found now؛ استمر بتطبيق إجراءات المرض والمراقبة.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        "No critical matched sensor driver was found now؛ continue disease-specific control and monitoring.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        "لا توجد قراءة مستشعرات حرجة مرتبطة بالمرض was found now؛ استمر بتطبيق إجراءات المرض والمراقبة.": "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        "🟢 Check range": "🟢 تحقق من المجال",
        "Check range": "تحقق من المجال",
        "حسّن التهوية..": "حسّن التهوية.",
        "حافظ على جفاف الأوراق..": "حافظ على جفاف الأوراق.",
        "أزل الأوراق السفلية المصابة..": "أزل الأوراق السفلية المصابة.",
        "آمن mite control": "مكافحة آمنة للأكاروسات",
        "safe mite control": "مكافحة آمنة للأكاروسات",
        "mite": "أكاروسات",
        "mites": "أكاروسات",
        "webbing": "الخيوط العنكبوتية",
        "foliage": "المجموع الخضري",
        "plant crowding": "ازدحام النباتات",
    }
    for bad, good in v23_fixes.items():
        text = text.replace(bad, good)

    # Translate any remaining common English fragments without damaging IDs/units.
    fragment_fixes = {
        "Keep foliage dry": "حافظ على جفاف المجموع الخضري",
        "Avoid handling plants while wet": "تجنّب التعامل مع النباتات وهي مبللة",
        "Inspect leaf undersides": "افحص السطح السفلي للأوراق",
        "Remove heavily damaged leaves": "أزل الأوراق شديدة الضرر",
        "Remove badly damaged leaves": "أزل الأوراق شديدة الضرر",
        "Use safe mite control": "استخدم مكافحة آمنة للأكاروسات",
        "Improve airflow": "حسّن حركة الهواء",
        "Improve ventilation": "حسّن التهوية",
        "Reduce humidity": "خفّض الرطوبة",
        "Avoid wetting leaves": "تجنّب تبليل الأوراق",
        "Avoid wetting tomato leaves": "تجنّب تبليل أوراق البندورة",
        "Remove infected leaves quickly": "أزل الأوراق المصابة بسرعة",
        "Continue monitoring": "استمر بالمراقبة",
        "Inspect plants manually": "افحص النباتات يدويًا",
    }
    for bad, good in fragment_fixes.items():
        text = re.sub(r"(?<![A-Za-z])" + re.escape(bad) + r"(?![A-Za-z])", good, text, flags=re.IGNORECASE)


    # V24 strict last pass: catch any remaining partially translated mixed phrases.
    text = re.sub(
        r"No\s+[^\n]*?(?:critical|حرج)[^\n]*?matched\\s+sensor[^\n]*?(?:driver|مؤشر)?[^\n]*?found\\s+now[^\n]*",
        "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Keep\\s+foliage\\s+dry\\s*(?:and|و)?\\s*(?:حسّن\\s+التهوية|improve\\s+ventilation|improve\\s+airflow)?\\.*",
        "حافظ على جفاف المجموع الخضري وحسّن التهوية.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Avoid\\s+handling\\s+plants\\s+while\\s+wet\\.*",
        "تجنّب التعامل مع النباتات وهي مبللة.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Inspect\\s+leaf\\s+undersides\\s+for\\s+mites\\s*/\\s*webbing\\.*",
        "افحص السطح السفلي للأوراق بحثًا عن الأكاروسات أو الخيوط العنكبوتية.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Remove\\s+heavily\\s+damaged\\s+leaves\\.*",
        "أزل الأوراق شديدة الضرر.",
        text,
        flags=re.IGNORECASE,
    )


    # V25 direct final fix for exact partially-translated sentence.
    text = text.replace(
        "No حرج matched sensor مؤشر was found now؛ استمر بتطبيق إجراءات المرض والمراقبة.",
        "لا توجد قراءة مستشعرات حرجة مرتبطة مباشرة بهذا المرض الآن؛ استمر بتطبيق إجراءات المرض والمراقبة."
    )

    # Normalize spacing after mixed replacements.
    text = text.replace(" و حسّن", " وحسّن")
    text = text.replace("..", ".")
    text = re.sub(r" +\\n", "\\n", text)
    text = re.sub(r"\\n{3,}", "\\n\\n", text)

    return text.strip()



def to_arabic_text(text):
    text = remove_farmer_unfriendly_lines(text)

    # First translate exact/common phrases safely.
    merged = {}
    try:
        merged.update(AR_REPLACEMENTS)
    except Exception:
        pass
    try:
        merged.update(AR_EXTRA_REPLACEMENTS)
    except Exception:
        pass
    merged.update(ARABIC_FULL_REPLACEMENTS)
    merged.update(ARABIC_YOLO_WEATHER_EXTRA)
    merged.update(ARABIC_V21_EXTRA_REPLACEMENTS)
    merged.update(ARABIC_COMPLETE_APP_PHRASES)
    merged.update(ARABIC_V23_STRICT_PHRASES)
    merged.update(ARABIC_V24_LATEST_REPORT_PHRASES)

    text = safe_english_replace(text, merged)

    # Extra regex translations for phrases that may vary.
    regex_replacements = [
        (r"Monitor EC and irrigation", "راقب قيمة EC ونظام الري"),
        (r"Monitor EC", "راقب قيمة EC"),
        (r"Correct pH carefully", "صحّح قيمة pH بحذر"),
        (r"High humidity may increase disease risk if leaves stay wet\.?", "الرطوبة المرتفعة قد تزيد خطر الأمراض إذا بقيت الأوراق مبللة."),
        (r"Inspect lower leaves for spots or mold\.?", "افحص الأوراق السفلية بحثًا عن بقع أو عفن."),
        (r"High salinity/nutrient level", "ارتفاع الملوحة أو مستوى المغذيات"),
        (r"Alkaline soil", "تربة قلوية"),
    ]
    for pat, repl in regex_replacements:
        text = re.sub(pat, repl, text)

    return arabic_final_cleanup(text)


def localized_text(text, chat_id=None, translate=True):
    text = remove_farmer_unfriendly_lines(text)
    if translate and is_ar(chat_id):
        return to_arabic_text(text)
    return text


# ==========================================================
# LOCALIZED BUTTONS AND START SETTINGS
# ==========================================================
def main_menu_text(chat_id=None):
    if is_ar(chat_id):
        return "🌿 البيت البلاستيكي الذكي\n\nاختر أحد الأزرار التالية:"
    return "🌿 Smart Greenhouse\n\nChoose one of the buttons below:"


def main_menu_keyboard(chat_id=None):
    if is_ar(chat_id):
        return {
            "inline_keyboard": [
                [
                    {"text": "🌿 القراءات", "callback_data": "/readings"},
                    {"text": "📋 التقرير", "callback_data": "/report"},
                ],
                [
                    {"text": "🌤 الطقس", "callback_data": "/weather"},
                    {"text": "🦠 الأمراض", "callback_data": "/disease"},
                ],
                [
                    {"text": "📷 الكاميرا", "url": YOLO_CAMERA_URL},
                    {"text": "🔄 تحديث الطقس", "callback_data": "/update_weather"},
                ],
            ]
        }

    return {
        "inline_keyboard": [
            [
                {"text": "🌿 Readings", "callback_data": "/readings"},
                {"text": "📋 Report", "callback_data": "/report"},
            ],
            [
                {"text": "🌤 Weather", "callback_data": "/weather"},
                {"text": "🦠 Disease", "callback_data": "/disease"},
            ],
            [
                {"text": "📷 Camera", "url": YOLO_CAMERA_URL},
                {"text": "🔄 Update Weather", "callback_data": "/update_weather"},
            ],
        ]
    }


def settings_text():
    return (
        "🌐 Please choose your language:\n"
        "الرجاء اختيار لغتك:\n\n"
        "🧹 Clear old bot messages if needed.\n"
        "امسح رسائل البوت القديمة عند الحاجة."
    )


def settings_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "English", "callback_data": "set_lang_en"},
                {"text": "العربية", "callback_data": "set_lang_ar"},
            ],
            [
                {"text": "🧹 Clear old chat", "callback_data": "clear_chat"},
                {"text": "🧹 مسح المحادثة القديمة", "callback_data": "clear_chat"},
            ],
        ]
    }


def start_farming_text(chat_id=None):
    if is_ar(chat_id):
        return (
            "✅ تم اختيار اللغة العربية.\n\n"
            "مرحبًا بك في نظام البيت البلاستيكي الذكي.\n\n"
            "يساعد هذا النظام على مراقبة بيئة زراعة البندورة باستخدام مستشعرات مرتبطة بـ ESP32 و LoRa، "
            "ثم يعرض القراءات والتنبيهات عبر Telegram. كما يستخدم نموذج ذكاء اصطناعي لفحص صور أوراق البندورة "
            "واكتشاف الأمراض مبكرًا، مع تقديم توصيات واضحة للمزارع.\n\n"
            "اضغط على الزر التالي للبدء:"
        )

    return (
        "✅ English selected.\n\n"
        "Welcome to the Smart Greenhouse Monitoring System.\n\n"
        "This system monitors tomato greenhouse conditions using ESP32 and LoRa sensor readings, "
        "then sends readings and alerts through Telegram. It also uses an AI model to analyze tomato leaf images "
        "for early disease detection and gives clear farmer recommendations.\n\n"
        "Press the button below to begin:"
    )


def start_farming_keyboard(chat_id=None):
    if is_ar(chat_id):
        return {"inline_keyboard": [[{"text": "🌿 ابدأ الزراعة الذكية", "callback_data": "start_farming"}]]}
    return {"inline_keyboard": [[{"text": "🌿 Start Smart Farming", "callback_data": "start_farming"}]]}


def project_intro_text(chat_id=None):
    if is_ar(chat_id):
        return (
            "🌿 مرحبًا بك في نظام البيت البلاستيكي الذكي.\n\n"
            "يساعد هذا النظام على مراقبة بيئة زراعة البندورة باستخدام مستشعرات مرتبطة بـ ESP32 و LoRa، "
            "ثم يعرض القراءات والتنبيهات عبر Telegram. كما يستخدم نموذج ذكاء اصطناعي لفحص صور أوراق البندورة "
            "واكتشاف الأمراض مبكرًا، مع تقديم توصيات واضحة للمزارع.\n\n"
            "اختر الخدمة التي تريدها من الأزرار التالية:"
        )

    return (
        "🌿 Welcome to the Smart Greenhouse Monitoring System.\n\n"
        "This system monitors tomato greenhouse conditions using ESP32 and LoRa sensor readings, "
        "then sends readings and alerts through Telegram. It also uses an AI model to analyze tomato leaf images "
        "for early disease detection and gives clear farmer recommendations.\n\n"
        "Choose the service you need from the buttons below:"
    )


REMOVE_KEYBOARD = {"remove_keyboard": True, "selective": False}


# ==========================================================
# SEND HELPERS
# ==========================================================
def send_message(text, reply_markup=None, chat_id=None, timeout=30, translate=True, remember=True):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    text = localized_text(str(text), chat_id=chat_id, translate=translate)

    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or [""]
    ok_all = True
    errors = []

    for idx, part in enumerate(chunks):
        data = {
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": "true"
        }

        # Attach buttons to the last chunk only, so long reports do not repeat the keyboard payload.
        if reply_markup is not None and idx == len(chunks) - 1:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

        js = tg_post("sendMessage", data, timeout=timeout)
        if js.get("ok"):
            try:
                if remember:
                    remember_message(chat_id, js.get("result", {}).get("message_id"))
            except Exception:
                pass
        else:
            ok_all = False
            errors.append(js)
            print("sendMessage error:", js)

    return ok_all, errors


def send_photo_data_url(data_url, caption="", chat_id=None):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    try:
        if not data_url:
            return False, "Empty image"

        encoded = data_url.split(",", 1)[1] if "," in data_url else data_url
        image_bytes = base64.b64decode(encoded)
        bio = io.BytesIO(image_bytes)
        bio.name = "yolo_result.jpg"

        caption = localized_text(str(caption)[:1024], chat_id=chat_id, translate=True)

        js = tg_post(
            "sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": ("yolo_result.jpg", bio, "image/jpeg")},
            timeout=60,
        )

        if js.get("ok"):
            remember_message(chat_id, js.get("result", {}).get("message_id"))
            return True, "OK"
        return False, js
    except Exception as e:
        return False, str(e)


def send_remove_keyboard(chat_id=None):
    # Remove old phone Reply Keyboard without showing a visible confirmation message.
    # Telegram requires remove_keyboard to be attached to a message, so we send a tiny
    # temporary message and delete it immediately when possible.
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    js = tg_post(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": "⌨️",
            "reply_markup": json.dumps(REMOVE_KEYBOARD, ensure_ascii=False),
        },
        timeout=30,
    )

    if js.get("ok"):
        message_id = js.get("result", {}).get("message_id")
        if message_id:
            tg_post("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=15)
        return True, []

    return False, [js]


def send_main_menu(chat_id=None):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    return send_message(main_menu_text(chat_id), reply_markup=main_menu_keyboard(chat_id), chat_id=chat_id, translate=False)


def send_settings_menu(chat_id=None):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    # Clear old reply keyboard first, then show settings buttons.
    send_remove_keyboard(chat_id)
    return send_message(settings_text(), reply_markup=settings_keyboard(), chat_id=chat_id, translate=False)


# ==========================================================
# WEATHER APP PROXY
# ==========================================================
def get_json(path, timeout=120):
    url = f"{WEATHER_APP_BASE_URL}{path}"
    r = requests.get(url, timeout=timeout)
    try:
        return r.json()
    except Exception:
        return {"error": r.text, "status_code": r.status_code}


def pretty_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def get_report_message(endpoint, chat_id=None):
    js = get_json(endpoint, timeout=180)
    msg = js.get("message") if isinstance(js, dict) else None
    return localized_text(msg or pretty_json(js), chat_id=chat_id, translate=True)


# ==========================================================
# AUTO ALERTS
# ==========================================================
def ping_weather_check_sensors():
    js = get_json("/check-sensors", timeout=180)
    render_sent = False
    render_errors = []

    if isinstance(js, dict) and js.get("changed") and js.get("shouldSend") and js.get("message"):
        render_sent, render_errors = send_message(js["message"], chat_id=TELEGRAM_CHAT_ID, translate=True)
        menu_sent, menu_errors = send_main_menu(TELEGRAM_CHAT_ID)

        js["render_sent_message"] = render_sent
        js["render_send_errors"] = render_errors
        js["render_sent_menu"] = menu_sent
        js["render_menu_errors"] = menu_errors

    return js


def send_daily_report():
    msg = get_report_message("/send-report", chat_id=TELEGRAM_CHAT_ID)
    ok, errors = send_message(msg, chat_id=TELEGRAM_CHAT_ID, translate=False)
    menu_ok, menu_errors = send_main_menu(TELEGRAM_CHAT_ID)
    return {"sent": ok, "errors": errors, "menu_sent": menu_ok, "menu_errors": menu_errors}


def send_yolo_alert_payload(payload):
    message = payload.get("message", "")
    if not message:
        message = "🦠 AI TOMATO DISEASE DETECTION ALERT\n\n" + json.dumps(payload.get("final_summary", {}), ensure_ascii=False, indent=2)

    ok_msg, msg_errors = send_message(message, chat_id=TELEGRAM_CHAT_ID, translate=True)

    photos_sent = 0
    photo_errors = []
    images = payload.get("images") or payload.get("prediction_images") or []

    for i, item in enumerate(images, start=1):
        if isinstance(item, dict):
            img = item.get("image", "")
            caption = item.get("caption", f"YOLO annotated image {i}")
        else:
            img = str(item)
            caption = f"YOLO annotated image {i}"

        ok, err = send_photo_data_url(img, caption, chat_id=TELEGRAM_CHAT_ID)
        if ok:
            photos_sent += 1
        else:
            photo_errors.append({"image": i, "error": str(err)})

    menu_sent, menu_errors = send_main_menu(TELEGRAM_CHAT_ID)

    return {
        "message_sent": ok_msg,
        "message_errors": msg_errors,
        "photos_sent": photos_sent,
        "photos_total": len(images),
        "photo_errors": photo_errors,
        "menu_sent": menu_sent,
        "menu_errors": menu_errors,
    }


# ==========================================================
# COMMANDS AND CALLBACKS
# ==========================================================
def normalize_command(text):
    text = (text or "").strip()
    if text in ["/ابدأ", "ابدأ", "إبدأ", "/إبدأ"]:
        return "/start"
    if text in ["تحديث الطقس", "/تحديث_الطقس"]:
        return "/update_weather"
    if text in ["القراءات", "/القراءات"]:
        return "/readings"
    if text in ["التقرير", "/التقرير"]:
        return "/report"
    if text in ["الطقس", "/الطقس"]:
        return "/weather"
    if text in ["الأمراض", "الامراض", "/الأمراض", "/الامراض"]:
        return "/disease"
    if text in ["الكاميرا", "/الكاميرا"]:
        return "/camera"
    return text


def handle_command(text, chat_id=None):
    chat_id = str(chat_id or TELEGRAM_CHAT_ID)
    text = normalize_command(text)

    if text in ["/start", "/help"]:
        return "__SHOW_SETTINGS__"

    if text in ["/remove_keyboard", "/clear_keyboard"]:
        return "__CLEAR_KEYBOARD__"

    if text == "/readings":
        return get_report_message("/send-readings", chat_id=chat_id)

    if text == "/report":
        return get_report_message("/send-report", chat_id=chat_id)

    if text == "/weather":
        js = get_json("/weather")
        if isinstance(js, dict) and js.get("message"):
            return localized_text(js["message"], chat_id=chat_id, translate=True)
        return localized_text("🌤 WEATHER INFO\n\n" + pretty_json(js), chat_id=chat_id, translate=True)

    if text == "/disease":
        js = get_json("/disease")
        if isinstance(js, dict) and js.get("message"):
            return localized_text(js["message"], chat_id=chat_id, translate=True)
        return localized_text("🦠 LATEST DISEASE STATUS\n\n" + pretty_json(js), chat_id=chat_id, translate=True)

    if text == "/camera":
        if is_ar(chat_id):
            return "📷 كاميرا كشف أمراض البندورة:\n" + YOLO_CAMERA_URL
        return "📷 Tomato disease camera:\n" + YOLO_CAMERA_URL

    if text == "/update_weather":
        update_result = get_json("/update-weather", timeout=180)
        if isinstance(update_result, dict) and update_result.get("message"):
            msg = localized_text(update_result["message"], chat_id=chat_id, translate=True)
            if is_ar(chat_id):
                return msg + "\n\n🔗 تطبيق الطقس:\n" + WEATHER_APP_URL
            return msg + "\n\n🔗 Weather App:\n" + WEATHER_APP_URL

        if is_ar(chat_id):
            return "🌤 تطبيق الطقس:\n" + WEATHER_APP_URL
        return "🌤 Weather App:\n" + WEATHER_APP_URL

    if text == "/daily":
        if is_ar(chat_id):
            return "📅 يتم إرسال التقرير اليومي تلقائيًا في الساعة 8:00 صباحًا."
        return "Daily report is automatic at 8:00 AM."

    if text == "/history":
        if is_ar(chat_id):
            return "سجلّ النتائج مدمج داخل زر الأمراض."
        return "History is included in /disease."

    if is_ar(chat_id):
        return "الأمر غير معروف. أرسل /ابدأ لفتح الإعدادات."
    return "Unknown command. Send /start to open settings."


def handle_callback(callback, chat_id):
    callback_id = callback.get("id", "")
    data = callback.get("data", "")

    answer_callback_query(callback_id)

    if data == "set_lang_en":
        set_chat_lang(chat_id, "en")
        return send_message(start_farming_text(chat_id), reply_markup=start_farming_keyboard(chat_id), chat_id=chat_id, translate=False)

    if data == "set_lang_ar":
        set_chat_lang(chat_id, "ar")
        return send_message(start_farming_text(chat_id), reply_markup=start_farming_keyboard(chat_id), chat_id=chat_id, translate=False)

    if data == "start_farming":
        return send_main_menu(chat_id)

    if data == "clear_chat":
        deleted, errors = clear_remembered_messages(chat_id)
        if is_ar(chat_id):
            msg = f"🧹 تم مسح رسائل البوت المحفوظة.\nعدد الرسائل المحذوفة: {deleted}\n\nأرسل /ابدأ لتغيير اللغة أو بدء الاستخدام."
        else:
            msg = f"🧹 Saved bot messages were cleared.\nDeleted messages: {deleted}\n\nSend /start to change language or begin again."
        return send_message(msg, chat_id=chat_id, translate=False)

    # Normal command callback from inline menu.
    reply = handle_command(data, chat_id=chat_id)
    if reply == "__SHOW_SETTINGS__":
        return send_settings_menu(chat_id)
    if reply == "__CLEAR_KEYBOARD__":
        return send_remove_keyboard(chat_id)

    ok, errors = send_message(reply, chat_id=chat_id, translate=False)
    menu_ok, menu_errors = send_main_menu(chat_id)
    return ok and menu_ok, errors + menu_errors


def handle_telegram_update(update):
    # Inline button press
    callback = update.get("callback_query")
    if callback:
        msg = callback.get("message") or {}
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))

        if chat_id != str(TELEGRAM_CHAT_ID):
            return {"ignored": True, "chat_id": chat_id, "type": "callback_query"}

        ok, errors = handle_callback(callback, chat_id)

        return {
            "ignored": False,
            "type": "callback_query",
            "callback_data": callback.get("data", ""),
            "sent": ok,
            "errors": errors,
        }

    # Normal typed message
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if chat_id != str(TELEGRAM_CHAT_ID):
        return {"ignored": True, "chat_id": chat_id, "type": "message"}

    text = msg.get("text", "")
    reply = handle_command(text, chat_id=chat_id)

    # /start or /ابدأ opens language/settings screen.
    if reply == "__SHOW_SETTINGS__":
        ok, errors = send_settings_menu(chat_id)
        return {
            "ignored": False,
            "type": "message",
            "command": text,
            "settings_sent": ok,
            "errors": errors,
        }

    if reply == "__CLEAR_KEYBOARD__":
        ok, errors = send_remove_keyboard(chat_id)
        return {
            "ignored": False,
            "type": "message",
            "command": text,
            "clear_keyboard_sent": ok,
            "errors": errors,
        }

    ok, errors = send_message(reply, chat_id=chat_id, translate=False)
    menu_ok, menu_errors = send_main_menu(chat_id)

    return {
        "ignored": False,
        "type": "message",
        "command": text,
        "reply_sent": ok,
        "errors": errors,
        "menu_sent": menu_ok,
        "menu_errors": menu_errors,
    }
