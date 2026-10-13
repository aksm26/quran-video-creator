"""App language. Keys are the English texts; each row lists the translation in ORDER's languages.

A key with no translation falls back to English and is recorded in MISSING (a test keeps that empty).
Each language also names the Quran translation selected for it by default."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    translation_id: int | None  # the Quran.com translation selected by default for it (None: no translation)
    rtl: bool = False


# The app's languages, each with the Quran translation it picks by default. Their names are not stored here: they
# come from config/language_names.py, in the language the app is currently using.
LANGUAGES: dict[str, Language] = {
    "en": Language(20),  # Saheeh International
    "ar": Language(None, True),  # the Arabic text itself needs no translation
    "ur": Language(234, True),
    "fr": Language(31),
    "es": Language(83),
    "id": Language(33),
    "tr": Language(77),
    "pt": Language(103),
    "de": Language(27),
    "ru": Language(45),
    "it": Language(153),
    "nl": Language(235),
    "fa": Language(29, True),
    "ms": Language(39),
    "hi": Language(122),
    "bn": Language(161),
    "zh": Language(56),
    "ja": Language(35),
}
ORDER = ("ar", "ur", "fr", "es", "id", "tr")  # the languages of STRINGS below

_ABOUT_DATA = "Text, translations, reciters and word timing come from Quran.com / Quran.Foundation (Content API v4). Audio comes from quranicaudio.com. The Arabic is shown exactly as the API returns it."

STRINGS: dict[str, tuple[str, ...]] = {
    "About": ("حول", "تعارف", "À propos", "Acerca de", "Tentang", "Hakkında"),
    "Language": ("اللغة", "زبان", "Langue", "Idioma", "Bahasa", "Dil"),
    "System": ("النظام", "سسٹم", "Système", "Sistema", "Sistem", "Sistem"),
    "Light": ("فاتح", "روشن", "Clair", "Claro", "Terang", "Açık"),
    "Dark": ("داكن", "تاریک", "Sombre", "Oscuro", "Gelap", "Koyu"),
    "Recitation": ("التلاوة", "تلاوت", "Récitation", "Recitación", "Bacaan", "Kıraat"),
    "Reciter": ("القارئ", "قاری", "Récitateur", "Recitador", "Qari", "Okuyucu"),
    "Surah": ("السورة", "سورت", "Sourate", "Sura", "Surah", "Sure"),
    "From verse": ("من الآية", "آیت سے", "Du verset", "Desde el versículo", "Dari ayat", "Başlangıç ayeti"),
    "To verse": ("إلى الآية", "آیت تک", "Au verset", "Hasta el versículo", "Sampai ayat", "Bitiş ayeti"),
    "{n} verses": ("{n} آية", "{n} آیات", "{n} versets", "{n} versículos", "{n} ayat", "{n} ayet"),
    "Full verse": ("الآية كاملة", "پوری آیت", "Verset entier", "Versículo completo", "Ayat penuh", "Ayetin tamamı"),
    "Cut at stop signs": ("التقطيع عند علامات الوقف", "وقف کی علامات پر تقسیم", "Couper aux signes d'arrêt", "Cortar en los signos de pausa", "Potong di tanda waqaf", "Vakıf işaretlerinde böl"),
    "Quran font": ("خط المصحف", "قرآنی فونٹ", "Police du Coran", "Fuente del Corán", "Font Al-Qur'an", "Kur'an yazı tipi"),
    "Highlight": ("التمييز", "نمایاں", "Surlignage", "Resaltado", "Sorotan", "Vurgu"),
    "None": ("بلا", "کوئی نہیں", "Aucun", "Ninguno", "Tidak ada", "Yok"),
    "Word by word": ("كلمة بكلمة", "لفظ بہ لفظ", "Mot par mot", "Palabra por palabra", "Kata demi kata", "Kelime kelime"),
    "Keep recited words": ("إبقاء الكلمات المتلوة", "پڑھے گئے الفاظ برقرار رکھیں", "Garder les mots récités", "Mantener las palabras recitadas", "Pertahankan kata yang dibaca", "Okunan kelimeleri koru"),
    "Highlight fade": ("ظهور تدريجي للتمييز", "نمایاں کا بتدریج اجاگر ہونا", "Surlignage progressif", "Resaltado gradual", "Sorotan bertahap", "Yumuşak vurgu"),
    "Words": ("الكلمات", "الفاظ", "Mots", "Palabras", "Kata", "Kelimeler"),
    "All words shown": ("إظهار كل الكلمات", "تمام الفاظ دکھائیں", "Tous les mots affichés", "Todas las palabras visibles", "Semua kata ditampilkan", "Tüm kelimeler görünür"),
    "Words appear as recited": ("تظهر الكلمات مع التلاوة", "تلاوت کے ساتھ الفاظ ظاہر ہوں", "Les mots apparaissent à la récitation", "Las palabras aparecen al recitarse", "Kata muncul saat dibaca", "Kelimeler okundukça görünür"),
    "One word at a time": ("كلمة واحدة في كل مرة", "ایک وقت میں ایک لفظ", "Un mot à la fois", "Una palabra a la vez", "Satu kata setiap kali", "Her seferinde bir kelime"),
    "Surah name": ("اسم السورة", "سورت کا نام", "Nom de la sourate", "Nombre de la sura", "Nama surah", "Sure adı"),
    "Surah name size": ("حجم اسم السورة", "سورت کے نام کا سائز", "Taille du nom de la sourate", "Tamaño del nombre de la sura", "Ukuran nama surah", "Sure adı boyutu"),
    "Opening Basmala": ("البسملة الافتتاحية", "ابتدائی بسم اللہ", "Basmala d'ouverture", "Basmala inicial", "Basmalah pembuka", "Açılış Besmelesi"),
    "Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah.": ("تتطلب الآية 1 من سورة غير الفاتحة والتوبة.", "فاتحہ اور توبہ کے علاوہ کسی سورت کی آیت 1 درکار ہے۔", "Nécessite le verset 1 d'une sourate autre qu'Al-Fatiha et At-Tawba.", "Requiere el versículo 1 de una sura distinta de Al-Fatiha y At-Tawba.", "Perlu ayat 1 dari surah selain Al-Fatihah dan At-Taubah.", "Fâtiha ve Tevbe dışındaki bir surenin 1. ayeti gerekir."),
    "Look": ("المظهر", "ظاہری شکل", "Apparence", "Aspecto", "Tampilan", "Görünüm"),
    "Translation": ("الترجمة", "ترجمہ", "Traduction", "Traducción", "Terjemahan", "Meal"),
    "Translation width": ("عرض الترجمة", "ترجمے کی چوڑائی", "Largeur de la traduction", "Ancho de la traducción", "Lebar terjemahan", "Meal genişliği"),
    "Themes": ("السمات", "تھیمز", "Thèmes", "Temas", "Tema", "Temalar"),
    "Custom": ("مخصص", "حسبِ ضرورت", "Perso", "Personal", "Kustom", "Özel"),
    "Text width": ("عرض النص", "متن کی چوڑائی", "Largeur du texte", "Ancho del texto", "Lebar teks", "Metin genişliği"),
    "Background dim": ("تعتيم الخلفية", "پس منظر مدھم", "Assombrir le fond", "Atenuar el fondo", "Redupkan latar", "Arka plan karartma"),
    "Background image or video": ("صورة أو فيديو للخلفية", "پس منظر کی تصویر یا ویڈیو", "Image ou vidéo d'arrière-plan", "Imagen o video de fondo", "Gambar atau video latar", "Arka plan görseli veya videosu"),
    "Choose": ("اختيار", "منتخب کریں", "Choisir", "Elegir", "Pilih", "Seç"),
    "Clear": ("مسح", "ہٹائیں", "Effacer", "Quitar", "Hapus", "Temizle"),
    "If the video is shorter": ("إذا كان الفيديو أقصر", "اگر ویڈیو چھوٹی ہو", "Si la vidéo est plus courte", "Si el video es más corto", "Jika video lebih pendek", "Video daha kısaysa"),
    "Loop": ("تكرار", "دہرائیں", "Boucle", "Repetir", "Ulangi", "Döngü"),
    "Freeze": ("تثبيت الإطار الأخير", "آخری فریم روکیں", "Figer", "Congelar", "Bekukan", "Dondur"),
    "Output": ("الإخراج", "آؤٹ پٹ", "Sortie", "Salida", "Keluaran", "Çıktı"),
    "Quality": ("الجودة", "معیار", "Qualité", "Calidad", "Kualitas", "Kalite"),
    "Very low": ("منخفضة جداً", "بہت کم", "Très basse", "Muy baja", "Sangat rendah", "Çok düşük"),
    "Arabic": ("النص العربي", "عربی متن", "Arabe", "Árabe", "Arab", "Arapça"),
    "Include Arabic text": ("إظهار النص العربي", "عربی متن شامل کریں", "Inclure le texte arabe", "Incluir el texto árabe", "Sertakan teks Arab", "Arapça metni ekle"),
    "Layout": ("التخطيط", "ترتیب", "Mise en page", "Diseño", "Tata letak", "Düzen"),
    "Very high": ("عالية جداً", "بہت اعلیٰ", "Très élevée", "Muy alta", "Sangat tinggi", "Çok yüksek"),
    "High": ("عالية", "اعلیٰ", "Élevée", "Alta", "Tinggi", "Yüksek"),
    "Medium": ("متوسطة", "درمیانہ", "Moyenne", "Media", "Sedang", "Orta"),
    "Low": ("منخفضة", "کم", "Basse", "Baja", "Rendah", "Düşük"),
    "Save to": ("حفظ في", "یہاں محفوظ کریں", "Enregistrer dans", "Guardar en", "Simpan ke", "Kaydedilecek yer"),
    "Browse": ("استعراض", "براؤز", "Parcourir", "Examinar", "Telusuri", "Gözat"),
    "Instagram and Facebook feed": ("خلاصة إنستغرام وفيسبوك", "انسٹاگرام اور فیس بک فیڈ", "Fil Instagram et Facebook", "Feed de Instagram y Facebook", "Feed Instagram dan Facebook", "Instagram ve Facebook akışı"),
    "Instagram feed": ("خلاصة إنستغرام", "انسٹاگرام فیڈ", "Fil Instagram", "Feed de Instagram", "Feed Instagram", "Instagram akışı"),
    "Export": ("تصدير", "برآمد", "Exporter", "Exportar", "Ekspor", "Dışa aktar"),
    "Cancel": ("إلغاء", "منسوخ", "Annuler", "Cancelar", "Batal", "İptal"),
    "Loading…": ("جارٍ التحميل…", "لوڈ ہو رہا ہے…", "Chargement…", "Cargando…", "Memuat…", "Yükleniyor…"),
    "Exporting…": ("جارٍ التصدير…", "برآمد ہو رہا ہے…", "Exportation…", "Exportando…", "Mengekspor…", "Dışa aktarılıyor…"),
    "Estimated time: {t}": ("الوقت المتوقع: {t}", "تخمینی وقت: {t}", "Durée estimée : {t}", "Tiempo estimado: {t}", "Perkiraan waktu: {t}", "Tahmini süre: {t}"),
    "{t} left": ("متبقي {t}", "{t} باقی", "{t} restantes", "{t} restantes", "{t} lagi", "{t} kaldı"),
    "Cancelled": ("أُلغي", "منسوخ ہو گیا", "Annulé", "Cancelado", "Dibatalkan", "İptal edildi"),
    "Preview": ("معاينة", "پیش منظر", "Aperçu", "Vista previa", "Pratinjau", "Önizleme"),
    "hour": ("ساعة", "گھنٹہ", "heure", "hora", "jam", "saat"),
    "hours": ("ساعة", "گھنٹے", "heures", "horas", "jam", "saat"),
    "minute": ("دقيقة", "منٹ", "minute", "minuto", "menit", "dakika"),
    "minutes": ("دقيقة", "منٹ", "minutes", "minutos", "menit", "dakika"),
    "second": ("ثانية", "سیکنڈ", "seconde", "segundo", "detik", "saniye"),
    "seconds": ("ثانية", "سیکنڈ", "secondes", "segundos", "detik", "saniye"),
    "Done": ("تم", "مکمل", "Terminé", "Listo", "Selesai", "Bitti"),
    "Saved {n} video(s) to": ("تم حفظ {n} فيديو في", "{n} ویڈیو(ز) یہاں محفوظ ہوئیں:", "{n} vidéo(s) enregistrée(s) dans", "{n} video(s) guardado(s) en", "{n} video disimpan di", "{n} video şuraya kaydedildi:"),
    "Open folder": ("فتح المجلد", "فولڈر کھولیں", "Ouvrir le dossier", "Abrir carpeta", "Buka folder", "Klasörü aç"),
    "Export failed": ("فشل التصدير", "برآمد ناکام", "Échec de l'exportation", "Error al exportar", "Ekspor gagal", "Dışa aktarma başarısız"),
    "Tick at least one format.": ("اختر صيغة واحدة على الأقل.", "کم از کم ایک فارمیٹ منتخب کریں۔", "Cochez au moins un format.", "Marca al menos un formato.", "Centang setidaknya satu format.", "En az bir biçim seçin."),
    "Can't use that folder.": ("لا يمكن استخدام هذا المجلد.", "یہ فولڈر استعمال نہیں ہو سکتا۔", "Impossible d'utiliser ce dossier.", "No se puede usar esa carpeta.", "Folder itu tidak dapat digunakan.", "Bu klasör kullanılamıyor."),
    "Can't load": ("تعذر التحميل", "لوڈ نہیں ہو سکا", "Chargement impossible", "No se pudo cargar", "Tidak dapat memuat", "Yüklenemedi"),
    "Retry": ("إعادة المحاولة", "دوبارہ کوشش کریں", "Réessayer", "Reintentar", "Coba lagi", "Yeniden dene"),
    "Close": ("إغلاق", "بند کریں", "Fermer", "Cerrar", "Tutup", "Kapat"),
    "Can't reach Quran.com. Check your connection.": ("تعذر الوصول إلى Quran.com. تحقق من اتصالك.", "Quran.com تک رسائی نہیں ہو سکی۔ اپنا کنکشن چیک کریں۔", "Impossible de joindre Quran.com. Vérifiez votre connexion.", "No se puede acceder a Quran.com. Revisa tu conexión.", "Tidak dapat menjangkau Quran.com. Periksa koneksi Anda.", "Quran.com'a ulaşılamıyor. Bağlantınızı kontrol edin."),
    "Encoding failed.": ("فشل الترميز.", "انکوڈنگ ناکام ہوئی۔", "L'encodage a échoué.", "Falló la codificación.", "Penyandian gagal.", "Kodlama başarısız oldu."),
    "Unexpected error.": ("خطأ غير متوقع.", "غیر متوقع خرابی۔", "Erreur inattendue.", "Error inesperado.", "Kesalahan tak terduga.", "Beklenmeyen hata."),
    "Custom themes": ("سمات مخصصة", "حسبِ ضرورت تھیمز", "Thèmes personnalisés", "Temas personalizados", "Tema kustom", "Özel temalar"),
    "Name": ("الاسم", "نام", "Nom", "Nombre", "Nama", "Ad"),
    "Background": ("الخلفية", "پس منظر", "Arrière-plan", "Fondo", "Latar", "Arka plan"),
    "Save theme": ("حفظ السمة", "تھیم محفوظ کریں", "Enregistrer le thème", "Guardar tema", "Simpan tema", "Temayı kaydet"),
    "Delete": ("حذف", "حذف کریں", "Supprimer", "Eliminar", "Hapus", "Sil"),
    "That name is taken.": ("هذا الاسم مستخدم.", "یہ نام پہلے سے موجود ہے۔", "Ce nom est déjà pris.", "Ese nombre ya existe.", "Nama itu sudah dipakai.", "Bu ad zaten kullanılıyor."),
    "Enter a name.": ("أدخل اسماً.", "نام درج کریں۔", "Saisissez un nom.", "Escribe un nombre.", "Masukkan nama.", "Bir ad girin."),
    "Recitation videos with the Arabic synced to the reciter.": ("مقاطع تلاوة بنص عربي متزامن مع القارئ.", "عربی متن کے ساتھ ہم آہنگ تلاوت کی ویڈیوز۔", "Vidéos de récitation avec l'arabe synchronisé au récitateur.", "Videos de recitación con el árabe sincronizado con el recitador.", "Video bacaan dengan teks Arab yang selaras dengan qari.", "Arapça metnin okuyucuyla eşlendiği kıraat videoları."),
    "Data and audio": ("البيانات والصوت", "ڈیٹا اور آڈیو", "Données et audio", "Datos y audio", "Data dan audio", "Veri ve ses"),
    _ABOUT_DATA: ("النص والترجمات والقراء وتوقيت الكلمات من Quran.com / Quran.Foundation (واجهة المحتوى v4). الصوت من quranicaudio.com. يُعرض النص العربي تماماً كما تعيده الواجهة.", "متن، تراجم، قاری اور الفاظ کا وقت Quran.com / Quran.Foundation (Content API v4) سے آتے ہیں۔ آڈیو quranicaudio.com سے ہے۔ عربی متن بالکل ویسا دکھایا جاتا ہے جیسا API دیتا ہے۔", "Le texte, les traductions, les récitateurs et le minutage des mots viennent de Quran.com / Quran.Foundation (API de contenu v4). L'audio vient de quranicaudio.com. L'arabe est affiché exactement comme l'API le renvoie.", "El texto, las traducciones, los recitadores y la sincronización de palabras provienen de Quran.com / Quran.Foundation (API de contenido v4). El audio proviene de quranicaudio.com. El árabe se muestra exactamente como lo devuelve la API.", "Teks, terjemahan, qari, dan waktu kata berasal dari Quran.com / Quran.Foundation (Content API v4). Audio berasal dari quranicaudio.com. Teks Arab ditampilkan persis seperti yang diberikan API.", "Metin, mealler, okuyucular ve kelime zamanlaması Quran.com / Quran.Foundation'dan (Content API v4) gelir. Ses quranicaudio.com'dan gelir. Arapça metin, API'nin verdiği haliyle gösterilir."),
    "Fonts": ("الخطوط", "فونٹس", "Polices", "Fuentes", "Font", "Yazı tipleri"),
    "Icons": ("الأيقونات", "آئیکنز", "Icônes", "Iconos", "Ikon", "Simgeler"),
    "Video": ("الفيديو", "ویڈیو", "Vidéo", "Video", "Video", "Video"),
    "FFmpeg, bundled through imageio-ffmpeg.": ("FFmpeg، مرفق عبر imageio-ffmpeg.", "FFmpeg، imageio-ffmpeg کے ذریعے شامل۔", "FFmpeg, fourni via imageio-ffmpeg.", "FFmpeg, incluido mediante imageio-ffmpeg.", "FFmpeg, disertakan melalui imageio-ffmpeg.", "FFmpeg, imageio-ffmpeg ile birlikte gelir."),
}
ABOUT_DATA = _ABOUT_DATA

NEUTRAL = {"", "Reels, Shorts, TikTok", "YouTube"}  # names that are not translated
current = "en"
MISSING: set[str] = set()


def _build_table() -> dict[str, dict[str, str]]:
    """{language: {English text: translation}} from the three data tables."""
    from .i18n_more import ORDER_B, ROWS_ALL, ROWS_B
    long = {"@data": ABOUT_DATA}
    table: dict[str, dict[str, str]] = {code: {} for code in LANGUAGES if code != "en"}
    for key, row in STRINGS.items():
        for code, text in zip(ORDER, row):
            table[code][key] = text
    for key, row in ROWS_B.items():
        for code, text in zip(ORDER_B, row):
            table[code][long.get(key, key)] = text
    for key, row in ROWS_ALL.items():
        for code, text in zip(ORDER + ORDER_B, row):
            table[code][long.get(key, key)] = text
    return table


TABLE = _build_table()


def set_language(code: str) -> None:
    global current
    current = code if code in LANGUAGES else "en"


def is_rtl() -> bool:
    return LANGUAGES[current].rtl


def tr(key: str) -> str:
    if current == "en" or key in NEUTRAL:
        return key
    text = TABLE[current].get(key)
    if text is None:
        MISSING.add(key)
        return key
    return text


def reciter_name(reciter_id: int, name: str) -> str:
    """The reciter's name in the script used by the current language, where we have it; else the API's spelling."""
    from .i18n_more import RECITER_NAMES
    return RECITER_NAMES.get(current, {}).get(reciter_id, name)
