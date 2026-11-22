"""Fixed lists shared by the API and the seed script."""

APP_VERSION = "0.1.0"

# (id, course code or None, name)
SUBJECTS = [
    ("s1", "CMSC310", "Computer Architecture and Organization"),
    ("s2", "CMSC306", "Networks & Communication"),
    ("s3", "CMSC309", "Software Engineering"),
    ("s4", None, "Automata Theory"),
    ("s5", None, "Machine Learning"),
    ("s6", None, "Data Structures"),
    ("s7", None, "Mathematics"),
    ("s8", None, "General"),
]

CATEGORIES = [
    "Reviewer",
    "Lecture Notes",
    "Presentation",
    "Practice Questions",
    "Assignment",
    "Other",
]

# extension -> fixed content type (never taken from the upload)
ALLOWED_EXTENSIONS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

# extensions that may be shown inline by the preview endpoint
PREVIEW_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp"}

BUFFER_OPTIONS_KB = [64, 256, 1024]

SESSION_COOKIE = "filego_session"
SESSION_IDLE_HOURS = 12
SESSION_ABSOLUTE_DAYS = 7
