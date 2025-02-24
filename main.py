import telebot
import yt_dlp
import os
import threading
import uuid
import requests
import instaloader

# إنشاء مجلد لتنزيل الملفات إذا لم يكن موجوداً
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# توكن البوت
API_TOKEN = "7902349650:AAGLYx3idgTm0jtQECeA2BXCMqQjQuH0QFQ"
bot = telebot.TeleBot(API_TOKEN)

# قاموس لتخزين الروابط/المعرفات
download_links = {}

###############################################################################
#                               أدوات مساعدة
###############################################################################

def is_nsfw(info):
    """
    فحص بيانات الفيديو لتحديد ما إذا كان يحتوي على محتوى إباحي.
    نفحص الحقل 'age_limit' أو نبحث عن كلمات مفتاحية في الوصف.
    """
    if 'age_limit' in info and info.get('age_limit', 0) > 0:
        return True
    if 'description' in info and info['description']:
        desc = info['description'].lower()
        keywords = ['porn', 'xxx', 'اباحي']
        for word in keywords:
            if word in desc:
                return True
    return False

def delete_messages(chat_id, message_ids):
    """
    حذف مجموعة من الرسائل في الدردشة بعد وقت محدد.
    """
    for mid in message_ids:
        try:
            bot.delete_message(chat_id, mid)
        except Exception as e:
            print(f"خطأ أثناء حذف الرسالة {mid}: {e}")

###############################################################################
#                 دوال التنزيل العامة بالاعتماد على yt-dlp
###############################################################################

def download_media(url, format_option="best"):
    """
    تنزيل الملف (فيديو/صوت/صورة) باستخدام yt-dlp وفقاً للصيغة المطلوبة.
    - إذا كان format_option == "bestaudio"، نقوم بتضمين الصورة المصغرة كغلاف للملف الصوتي.
    - نستخدم outtmpl لتسمية الملف وفق العنوان فقط (دون إضافات).
    """
    # خيارات عامة
    ydl_opts = {
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
    }

    if format_option == "bestaudio":
        # عند طلب ملف صوتي من يوتيوب
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [
                {
                    # استخراج الصوت إلى mp3
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                },
                {
                    # تضمين الصورة المصغرة كغلاف
                    'key': 'EmbedThumbnail',
                },
                {
                    # تضمين بيانات الميتاداتا
                    'key': 'FFmpegMetadata'
                }
            ],
            'writethumbnail': True,
            'embedthumbnail': True,
            'addmetadata': True,
        })
    else:
        # عند طلب فيديو (أعلى جودة أو جودة منخفضة)
        ydl_opts.update({
            'format': format_option,
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # مسار الملف الذي تم تنزيله
        filename = ydl.prepare_filename(info)

        # إذا كنا في وضع audio، فغالبًا سيصبح الامتداد .mp3 بعد PostProcessor
        if format_option == "bestaudio":
            base, _ = os.path.splitext(filename)
            filename = base + ".mp3"

    return filename, info

def send_downloaded_media(chat_id, filename, info, is_audio=False):
    """
    إرسال الملف للمستخدم. 
    - إذا is_audio=True => نرسله كملف صوتي (ويكون فيه الغلاف والعنوان).
    - إذا الامتداد صورة => send_photo
    - وإلا => send_video
    """
    # نفحص الامتداد
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    nsfw_flag = is_nsfw(info)

    try:
        if is_audio:
            # إرسال كملف صوتي (مع الغلاف إن وجد)
            sent_msg = bot.send_audio(chat_id, open(filename, 'rb'))
        elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            # إرسال كصورة
            sent_msg = bot.send_photo(chat_id, open(filename, 'rb'))
        else:
            # إرسال كفيديو
            sent_msg = bot.send_video(chat_id, open(filename, 'rb'))
    except Exception as e:
        bot.send_message(chat_id, "حدث خطأ أثناء إرسال الملف.")
        print(e)
        return None

    # إذا كان المحتوى إباحيًا (خاصة من إكس) نحذف الملف والرسالة بعد 10 ثوانٍ
    if nsfw_flag:
        warning_msg = bot.send_message(chat_id, "سيتم حذف الفديو قم بتوجيهه قبل ان يحذف خلال 10 ثواني")
        # جدولة الحذف
        threading.Timer(10, lambda: delete_messages(chat_id, [sent_msg.message_id, warning_msg.message_id])).start()

    return sent_msg

###############################################################################
#         أمثلة لتعامل مع ستوريات إنستجرام / هايلايت / منشورات (instaloader)
###############################################################################
# ملاحظة: لتعمل مع الحسابات الخاصة تحتاج لتسجيل الدخول: L.login("user","pass")

def download_instagram_stories(username):
    """
    تحميل ستوريات إنستجرام (للحسابات العامة).
    يعيد قائمة بالمسارات (الصور/الفيديوهات) التي تم تحميلها محليًا.
    """
    L = instaloader.Instaloader(save_metadata=False, download_comments=False)
    # تسجيل الدخول إذا لزم الأمر:
    # L.login("USERNAME", "PASSWORD")

    downloaded_files = []
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        stories = L.get_stories(userids=[profile.userid])

        folder = f"downloads/{username}_stories"
        if not os.path.exists(folder):
            os.makedirs(folder)

        for story in stories:
            for item in story.get_items():
                # تمييز الصورة أو الفيديو
                if item.is_video:
                    filename = os.path.join(folder, f"{item.date_utc.strftime('%Y%m%d_%H%M%S')}.mp4")
                    r = requests.get(item.video_url)
                else:
                    filename = os.path.join(folder, f"{item.date_utc.strftime('%Y%m%d_%H%M%S')}.jpg")
                    r = requests.get(item.url)

                with open(filename, 'wb') as f:
                    f.write(r.content)
                downloaded_files.append(filename)

    except Exception as e:
        print("Error downloading Instagram stories:", e)
    return downloaded_files

def download_instagram_highlights(username):
    """
    تحميل الهايلايت من إنستجرام (للحسابات العامة).
    يعيد قائمة بالمسارات (الصور/الفيديوهات) التي تم تحميلها محليًا.
    """
    L = instaloader.Instaloader(save_metadata=False, download_comments=False)
    # L.login("USERNAME", "PASSWORD")

    downloaded_files = []
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        highlights = instaloader.Highlights.from_user(L.context, profile)

        folder = f"downloads/{username}_highlights"
        if not os.path.exists(folder):
            os.makedirs(folder)

        for highlight in highlights:
            for item in highlight.get_items():
                if item.is_video:
                    filename = os.path.join(folder, f"{item.date_utc.strftime('%Y%m%d_%H%M%S')}.mp4")
                    r = requests.get(item.video_url)
                else:
                    filename = os.path.join(folder, f"{item.date_utc.strftime('%Y%m%d_%H%M%S')}.jpg")
                    r = requests.get(item.url)

                with open(filename, 'wb') as f:
                    f.write(r.content)
                downloaded_files.append(filename)

    except Exception as e:
        print("Error downloading Instagram highlights:", e)
    return downloaded_files

def download_instagram_posts(username, limit=5):
    """
    تحميل آخر limit منشورات من حساب إنستجرام (عام).
    يعيد قائمة بالمسارات (الصور/الفيديوهات) التي تم تحميلها محليًا.
    """
    L = instaloader.Instaloader(save_metadata=False, download_comments=False)
    # L.login("USERNAME", "PASSWORD")

    downloaded_files = []
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        posts = profile.get_posts()

        folder = f"downloads/{username}_posts"
        if not os.path.exists(folder):
            os.makedirs(folder)

        count = 0
        for post in posts:
            if count >= limit:
                break
            # قد يكون المنشور عبارة عن ألبوم صور/فيديوهات (carousel)
            # في هذه الحالة نحتاج للوصول إلى post.get_sidecar_nodes()
            # هنا نكتفي بتحميل أول عنصر
            if post.is_video:
                filename = os.path.join(folder, f"{post.date_utc.strftime('%Y%m%d_%H%M%S')}.mp4")
                r = requests.get(post.video_url)
            else:
                filename = os.path.join(folder, f"{post.date_utc.strftime('%Y%m%d_%H%M%S')}.jpg")
                r = requests.get(post.url)

            with open(filename, 'wb') as f:
                f.write(r.content)
            downloaded_files.append(filename)
            count += 1

    except Exception as e:
        print("Error downloading Instagram posts:", e)
    return downloaded_files

def send_instagram_files(chat_id, file_paths):
    """
    إرسال الملفات (صور/فيديوهات) بعد تحميلها من إنستجرام.
    """
    if not file_paths:
        bot.send_message(chat_id, "لم يتم العثور على أي ملفات أو حدث خطأ.")
        return

    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                bot.send_photo(chat_id, open(path, 'rb'))
            else:
                bot.send_video(chat_id, open(path, 'rb'))
        except Exception as e:
            print(f"خطأ أثناء إرسال الملف {path}: {e}")

###############################################################################
#                              ردود الأوامر
###############################################################################

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "مرحباً بك في بوت التحميل!\n\n"
        "أرسل رابط المنشور (فيديو/صورة) من فيسبوك، انستجرام، يوتيوب، تيكتوك أو إكس.\n"
        "إذا كان الرابط من يوتيوب، ستظهر لك خيارات التحميل (أعلى جودة/جودة منخفضة/ملف صوتي).\n"
        "إذا كان رابط إنستجرام بروفايل (مثال: https://instagram.com/username/ )، ستظهر خيارات تحميل القصص والهايلايت والمنشورات.\n"
    )
    bot.reply_to(message, welcome_text)

###############################################################################
#                      تمييز الروابط وتوجيهها
###############################################################################

def is_instagram_profile_link(url: str) -> bool:
    """
    دالة بسيطة لكشف ما إذا كان الرابط يشير لبروفايل إنستجرام
    (مثال: https://instagram.com/username/ أو https://www.instagram.com/username).
    - نفترض أنه بروفايل إذا لم يتضمن "/p/" أو "/reel/" أو "/tv/" أو "/stories/"
    - يمكنك تحسين هذه الدالة حسب الحاجة.
    """
    if "instagram.com" in url:
        # إذا لم يحوي كلمات تدل على منشور أو ريلز
        if not any(x in url for x in ["p/", "reel/", "tv/", "/stories/"]):
            return True
    return False

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """
    عند استقبال أي رسالة نصية:
    1. نتحقق هل هو رابط صحيح
    2. إن كان بروفايل إنستجرام => خيارات (قصص، هايلايت، منشورات)
    3. إن كان يوتيوب => خيارات (أعلى جودة، جودة منخفضة، ملف صوتي)
    4. وإلا => نحاول التنزيل مباشرة (فيسبوك، تيكتوك، إكس/تويتر، إنستجرام بوست...)
    """
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        bot.reply_to(message, "الرجاء إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    # حالة: رابط بروفايل إنستجرام
    if is_instagram_profile_link(url):
        unique_id = str(uuid.uuid4())[:8]
        download_links[unique_id] = url

        markup = telebot.types.InlineKeyboardMarkup()
        markup.row(
            telebot.types.InlineKeyboardButton("تحميل القصص (Stories)", callback_data=f"ig_stories|{unique_id}"),
            telebot.types.InlineKeyboardButton("تحميل الهايلايت", callback_data=f"ig_highlights|{unique_id}")
        )
        markup.row(
            telebot.types.InlineKeyboardButton("تحميل المنشورات", callback_data=f"ig_posts|{unique_id}")
        )
        bot.send_message(message.chat.id, "هذا حساب إنستجرام. ماذا تريد تحميله؟", reply_markup=markup)
        return

    # حالة: رابط يوتيوب
    if "youtube" in url or "youtu.be" in url:
        unique_id = str(uuid.uuid4())[:8]
        download_links[unique_id] = url

        markup = telebot.types.InlineKeyboardMarkup()
        markup.row(
            telebot.types.InlineKeyboardButton("أعلى جودة", callback_data=f"yt_best|{unique_id}"),
            telebot.types.InlineKeyboardButton("جودة منخفضة", callback_data=f"yt_worst|{unique_id}")
        )
        markup.row(
            telebot.types.InlineKeyboardButton("ملف صوتي", callback_data=f"yt_audio|{unique_id}")
        )
        bot.send_message(message.chat.id, "اختر نوع التنزيل:", reply_markup=markup)
        return

    # باقي الروابط: فيسبوك، تيكتوك، إكس/تويتر، إنستجرام منشور/ريلز، إلخ
    msg = bot.send_message(message.chat.id, "جاري تنزيل الملف...")
    try:
        filename, info = download_media(url, "best")
        send_downloaded_media(message.chat.id, filename, info)
        os.remove(filename)
        bot.edit_message_text("تم تنزيل الملف بنجاح!", chat_id=message.chat.id, message_id=msg.message_id)
    except Exception as e:
        bot.edit_message_text("حدث خطأ أثناء التنزيل.", chat_id=message.chat.id, message_id=msg.message_id)
        print(e)

###############################################################################
#                    التعامل مع ردود الأزرار (Callback Queries)
###############################################################################

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """
    ردود الأزرار:
    1. خيارات يوتيوب: (yt_best, yt_worst, yt_audio)
    2. خيارات إنستجرام بروفايل: (ig_stories, ig_highlights, ig_posts)
    """
    try:
        option, unique_id = call.data.split("|", 1)
    except:
        bot.answer_callback_query(call.id, "بيانات غير صالحة.")
        return

    # استرجاع الرابط من القاموس
    url = download_links.get(unique_id, "")
    if not url:
        bot.answer_callback_query(call.id, "انتهت صلاحية هذا الرابط أو لم يتم العثور عليه.")
        return

    if option.startswith("yt_"):
        # خيارات يوتيوب
        bot.answer_callback_query(call.id, "جاري التنزيل...")

        if option == "yt_best":
            fmt = "bestvideo+bestaudio/best"
        elif option == "yt_worst":
            fmt = "worst"
        elif option == "yt_audio":
            fmt = "bestaudio"
        else:
            bot.send_message(call.message.chat.id, "خيار غير معروف.")
            return

        msg = bot.send_message(call.message.chat.id, "جاري تنزيل الملف...")
        try:
            filename, info = download_media(url, fmt)
            is_audio = True if option == "yt_audio" else False
            send_downloaded_media(call.message.chat.id, filename, info, is_audio=is_audio)
            os.remove(filename)
            bot.edit_message_text("تم تنزيل الملف بنجاح!", chat_id=call.message.chat.id, message_id=msg.message_id)
        except Exception as e:
            bot.edit_message_text("حدث خطأ أثناء التنزيل.", chat_id=call.message.chat.id, message_id=msg.message_id)
            print(e)

    elif option.startswith("ig_"):
        # خيارات إنستجرام بروفايل
        bot.answer_callback_query(call.id, "جاري المعالجة...")
        username = url.rstrip('/').split('/')[-1]  # محاولة استخراج اسم المستخدم من الرابط
        if not username:
            bot.send_message(call.message.chat.id, "تعذر استخراج اسم المستخدم من الرابط.")
            return

        if option == "ig_stories":
            msg = bot.send_message(call.message.chat.id, f"جاري تنزيل قصص {username} ...")
            downloaded_files = download_instagram_stories(username)
            send_instagram_files(call.message.chat.id, downloaded_files)
            bot.edit_message_text("انتهى تنزيل القصص!", chat_id=call.message.chat.id, message_id=msg.message_id)

        elif option == "ig_highlights":
            msg = bot.send_message(call.message.chat.id, f"جاري تنزيل هايلايت {username} ...")
            downloaded_files = download_instagram_highlights(username)
            send_instagram_files(call.message.chat.id, downloaded_files)
            bot.edit_message_text("انتهى تنزيل الهايلايت!", chat_id=call.message.chat.id, message_id=msg.message_id)

        elif option == "ig_posts":
            msg = bot.send_message(call.message.chat.id, f"جاري تنزيل منشورات {username} (آخر 5) ...")
            downloaded_files = download_instagram_posts(username, limit=5)
            send_instagram_files(call.message.chat.id, downloaded_files)
            bot.edit_message_text("انتهى تنزيل المنشورات!", chat_id=call.message.chat.id, message_id=msg.message_id)
        else:
            bot.send_message(call.message.chat.id, "خيار غير معروف.")

    else:
        bot.answer_callback_query(call.id, "خيار غير معروف.")

###############################################################################
#                           تشغيل البوت
###############################################################################

bot.polling()