from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def load_dotenv_file() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_dotenv_file()


def normalize_api_key(value: str, placeholders: set[str]) -> str:
    cleaned = value.strip()
    return "" if cleaned in placeholders else cleaned


HOST = os.environ.get("BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.environ.get("BACKEND_PORT", "4000") or "4000")
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"
USERS_PATH = DATA_DIR / "users.json"
DOCS_PATH = DATA_DIR / "documents.json"
HISTORIES_PATH = DATA_DIR / "histories.json"
OPENAI_API_KEY = normalize_api_key(
    os.environ.get("OPENAI_API_KEY", ""),
    {"", "sk-your-key-here"},
)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5").strip() or "gpt-5"
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "45") or "45")
SITE_FETCH_TIMEOUT_SECONDS = float(os.environ.get("SITE_FETCH_TIMEOUT_SECONDS", "2.5") or "2.5")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower() or "auto"
GEMINI_API_KEY = normalize_api_key(
    os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", ""),
    {"", "your-gemini-key-here"},
)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "45") or "45")
GOOGLE_CLOUD_VISION_API_KEY = normalize_api_key(
    os.environ.get("GOOGLE_CLOUD_VISION_API_KEY", "") or os.environ.get("GOOGLE_VISION_API_KEY", ""),
    {"", "your-google-cloud-vision-api-key-here"},
)
GOOGLE_TRANSLATE_API_KEY = normalize_api_key(
    os.environ.get("GOOGLE_TRANSLATE_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", ""),
    {"", "your-google-translate-api-key-here", "your-google-api-key-here"},
)
GOOGLE_CLOUD_VISION_BASE_URL = os.environ.get(
    "GOOGLE_CLOUD_VISION_BASE_URL",
    "https://vision.googleapis.com/v1",
).rstrip("/")
GOOGLE_CLOUD_VISION_TIMEOUT_SECONDS = float(
    os.environ.get("GOOGLE_CLOUD_VISION_TIMEOUT_SECONDS", "35") or "35"
)
GOOGLE_TRANSLATE_BASE_URL = os.environ.get(
    "GOOGLE_TRANSLATE_BASE_URL",
    "https://translation.googleapis.com/language/translate/v2",
).rstrip("/")
GOOGLE_TRANSLATE_TIMEOUT_SECONDS = float(
    os.environ.get("GOOGLE_TRANSLATE_TIMEOUT_SECONDS", "30") or "30"
)
SOSMEDICA_SITE_URL = os.environ.get("SOSMEDICA_SITE_URL", "https://sosmedica.mn").rstrip("/")

DEFAULT_PROMPTS = [
    "Triage-ийн улаан ангилалд ямар тохиолдол багтдаг вэ?",
    "Хэвтэн эмчлүүлэхийн өмнө ямар шалгалтууд хийх ёстой вэ?",
    "Халдвар хамгааллын үндсэн дүрмийг нэгтгээд өгөөч.",
    "Дүрс оношилгооны өмнөх бэлтгэлийг товч тайлбарла.",
]

DEFAULT_DOCUMENT_FOLDERS = [
    "Өвчтөний мэдээлэл",
    "Ажилчдын мэдээлэл",
    "Эмнэлгийн мэдээлэл",
    "Ерөнхий",
]

SEED_DOCUMENTS = [
    {
        "id": str(uuid4()),
        "title": "Triage_Guide_2026.md",
        "source": "System seed",
        "summary": "Яаралтай тусламжийн шатлал, улаан/шар/ногоон ангиллын ерөнхий заавар.",
        "content": "Улаан ангилалд амьсгалын дутагдал, зүрхний тогтворгүй байдал, шок орно. Шар ангилалд ойрын үнэлгээ шаардлагатай тогтвортой боловч эрсдэлтэй тохиолдлууд хамаарна. Ногоон ангилалд хүлээлгэж болох хөнгөн шинж тэмдэгтэй тохиолдол орно.",
        "tags": ["triage", "emergency", "classification"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    },
    {
        "id": str(uuid4()),
        "title": "Admission_Checklist.txt",
        "source": "System seed",
        "summary": "Хэвтэн эмчлүүлэхийн өмнөх бүртгэл, зөвшөөрөл, даатгалын шалгах хуудас.",
        "content": "Хэвтэн эмчлүүлэхийн өмнө иргэний үнэмлэх, даатгалын мэдээлэл, эмийн харшлын асуумж, зөвшөөрлийн маягтыг баталгаажуулна. Өвчтөнд хоол, эмийн зааврыг урьдчилан тайлбарлана.",
        "tags": ["admission", "checklist", "insurance"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    },
    {
        "id": str(uuid4()),
        "title": "Infection_Control_Policy.json",
        "source": "System seed",
        "summary": "Гар ариутгал, хамгаалах хэрэгсэл, тусгаарлалтын дэглэмийн үндсэн бодлого.",
        "content": "Өвчтөнтэй хүрэлцэхийн өмнө болон дараа гар ариутгана. Дуслын халдварын сэжигтэй үед маск, нүдний хамгаалалт хэрэглэнэ. Өндөр эрсдэлтэй орчинд нэг удаагийн бээлий, халат заавал хэрэглэнэ.",
        "tags": ["infection", "ppe", "policy"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    },
    {
        "id": str(uuid4()),
        "title": "Radiology_Preparation.csv",
        "source": "System seed",
        "summary": "Дүрс оношилгооны өмнөх бэлтгэл, өлөн ирэх эсэх, тодосгогч бодисын асуумж.",
        "content": "Тодосгогч бодистой шинжилгээний өмнө бөөрний үзүүлэлт болон харшлын түүхийг асууна. Зарим шинжилгээнд 6-8 цаг өлөн байх шаардлагатай. Жирэмсний эрсдэлийг асуумжаар тодруулна.",
        "tags": ["radiology", "contrast", "preparation"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    },
]

SEED_USERS = [
    {
        "id": str(uuid4()),
        "email": "admin@sosmedica.mn",
        "password": "admin123",
        "role": "admin",
        "name": "System Admin",
    },
    {
        "id": str(uuid4()),
        "email": "staff@sosmedica.mn",
        "password": "staff123",
        "role": "staff",
        "name": "Clinical Staff",
    },
]
