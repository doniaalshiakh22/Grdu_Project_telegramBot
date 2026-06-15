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


def to_arabic_text(text):
    text = remove_farmer_unfriendly_lines(text)

    # Keep units, numbers, IDs, and symbols. Translate labels and repeated scientific wording.
    # Longer phrases first to avoid partial replacement problems.
    for en in sorted(AR_REPLACEMENTS, key=len, reverse=True):
        text = text.replace(en, AR_REPLACEMENTS[en])

    for en in sorted(AR_EXTRA_REPLACEMENTS, key=len, reverse=True):
        text = text.replace(en, AR_EXTRA_REPLACEMENTS[en])

    # Additional line-level cleanup for common English report lines.
    line_replacements = [
        (r"No sensor readings were found", "لم يتم العثور على قراءات مستشعرات"),
        (r"No matched disease image result for this node", "لا توجد نتيجة صورة مرض مطابقة لهذه العقدة"),
        (r"Capture tomato leaf images if symptoms are visible", "التقط صورًا لأوراق البندورة إذا ظهرت أعراض واضحة"),
        (r"Check irrigation", "افحص نظام الري"),
        (r"Improve ventilation", "حسّن التهوية"),
        (r"Monitor EC", "راقب قيمة EC"),
        (r"Correct pH carefully", "صحّح قيمة pH بحذر"),
        (r"Adjust pH gradually", "عدّل قيمة pH تدريجيًا"),
        (r"Remove infected leaves", "أزل الأوراق المصابة"),
        (r"Avoid overhead watering", "تجنّب الري من الأعلى"),
        (r"Increase airflow", "زِد حركة الهواء"),
        (r"Check underside of leaves", "افحص الجهة السفلية للأوراق"),
        (r"Control whiteflies", "كافح الذباب الأبيض"),
        (r"Use clean tools", "استخدم أدوات نظيفة"),
        (r"Keep leaves dry", "حافظ على جفاف الأوراق"),
        (r"Monitor the plant", "راقب النبات"),
    ]
    for pat, repl in line_replacements:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)

    text = text.replace("— صور:", "— عدد الصور:")
    text = text.replace("— images:", "— عدد الصور:")
    text = text.replace("; ", "؛ ")
    text = text.replace(" ;", "؛")
    text = text.replace(" → ", " ← ")

    return text.strip()


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
            "text": part
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
