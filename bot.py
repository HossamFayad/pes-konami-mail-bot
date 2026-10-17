import os
import time
import threading
import telebot
from telebot import types
from datetime import datetime

from database import (
    init_db,
    save_account,
    get_active_account,
    set_active_account,
    clear_active_account,
    get_user_accounts,
    get_account_by_id,
    get_all_active_monitored_accounts,
    is_admin,
    add_admin,
    get_all_accounts_admin,
    get_bot_stats,
    set_prompt_state,
    get_prompt_state,
    clear_prompt_state
)
from mail_service import MailService

BOT_TOKEN = os.getenv("BOT_TOKEN", "8773865112:AAEfK4wken0OxfKEgxvIRTkTkJC8i01K0qQ")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)

# In-memory tracking of seen message IDs to prevent duplicate alerts
seen_message_ids = set()

# In-memory tracking of chat message IDs to allow cleaning the screen per user
user_chat_messages = {}

# Admin prompt state: telegram_id -> state string (e.g. "waiting_admin_id")
admin_prompt_state = {}

def track_msg(chat_id: int, msg_id: int):
    if chat_id not in user_chat_messages:
        user_chat_messages[chat_id] = []
    if msg_id not in user_chat_messages[chat_id]:
        user_chat_messages[chat_id].append(msg_id)

def send_and_track(chat_id: int, text: str, **kwargs):
    try:
        msg = bot.send_message(chat_id, text, **kwargs)
        track_msg(chat_id, msg.message_id)
        return msg
    except Exception as e:
        print(f"[SendError] {e}")
        try:
            import re
            plain = re.sub(r'<[^<]+?>', '', text)
            msg = bot.send_message(chat_id, plain)
            track_msg(chat_id, msg.message_id)
            return msg
        except Exception as e2:
            print(f"[SendFallbackError] {e2}")
            return None

def safe_answer(call_id: str, text: str = None, show_alert: bool = False):
    try:
        bot.answer_callback_query(call_id, text=text, show_alert=show_alert)
    except Exception:
        pass

# Main Keyboard Markup
def get_main_menu_markup(telegram_id: int = None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_new = types.InlineKeyboardButton("🎲 إنشاء إيميل كونامي جديد", callback_data="btn_new_email")
    btn_inbox = types.InlineKeyboardButton("📬 فحص الرسائل والكود", callback_data="btn_check_inbox")
    btn_handover = types.InlineKeyboardButton("📋 كارت التسليم للمشتري", callback_data="btn_handover")
    btn_archive = types.InlineKeyboardButton("📂 أرشيف حساباتي", callback_data="btn_archive")
    btn_clean = types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen")
    btn_guide = types.InlineKeyboardButton("ℹ️ شرح ربط كونامي", callback_data="btn_guide")
    
    markup.add(btn_new)
    markup.add(btn_inbox, btn_handover)
    markup.add(btn_archive, btn_clean)
    markup.add(btn_guide)
    
    # If the user is an authorized admin, display the Admin Panel button
    if telegram_id and is_admin(telegram_id):
        markup.add(types.InlineKeyboardButton("👑 لوحة تحكم إدارة المتجر", callback_data="btn_admin_panel"))
        
    return markup

def show_admin_panel(telegram_id: int, message_id: int = None):
    stats = get_bot_stats()
    text = (
        "👑 <b>لوحة تحكم إدارة المتجر (Admin Control Panel)</b> 🛡️\n\n"
        "📊 <b>إحصائيات المتجر الشاملة:</b>\n"
        f"• إجمالي إيميلات كونامي المنشأة: <b>{stats['total_accounts']}</b> حساب\n"
        f"• إجمالي المستخدمين في البوت: <b>{stats['total_users']}</b> مستخدم\n\n"
        "🔒 <b>مستوى الأمان مفعّل:</b> المستخدمون العاديون لا يستطيعون رؤية أو فتح سوى الإيميلات التي ولدوها بأنفسهم لمنع سرقة الحسابات.\n\n"
        "👇 <b>اختر الإجراء الإداري:</b>"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🌐 أرشيف كل حسابات المتجر (شامل الكل)", callback_data="btn_admin_all_accs"),
        types.InlineKeyboardButton("➕ إضافة أدمن جديد (صاحبك)", callback_data="btn_admin_add_prompt"),
        types.InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="btn_main_menu")
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id=telegram_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    send_and_track(telegram_id, text, reply_markup=markup)

@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    telegram_id = message.chat.id
    track_msg(telegram_id, message.message_id)
    
    active = get_active_account(telegram_id)
    active_info = "لا يوجد إيميل نشط حالياً."
    if active:
        active_info = f"<code>{active['email']}</code>"
        
    text = (
        "⚽ <b>مرحباً بك في بوت بريد بيس موبايل (PES & Konami ID)</b> 🎮\n\n"
        "📌 البوت مصمم خصيصاً لمتاجر بيع أكونتات eFootball لإنشاء إيميلات دائمة، "
        "واستقبال أكواد تفعيل كونامي (OTP) بلمسة واحدة!\n\n"
        f"📧 <b>الحساب النشط حالياً:</b>\n{active_info}\n\n"
        "👇 <b>اختر الإجراء المطلوب من القائمة:</b>"
    )
    send_and_track(telegram_id, text, reply_markup=get_main_menu_markup(telegram_id))

@bot.message_handler(commands=['admin'])
def handle_admin_command(message):
    telegram_id = message.chat.id
    track_msg(telegram_id, message.message_id)
    if not is_admin(telegram_id):
        send_and_track(telegram_id, "⛔ عذراً، هذا الأمر مخصص لمدير المتجر فقط.")
        return
    show_admin_panel(telegram_id)

@bot.message_handler(commands=['addadmin'])
def handle_addadmin_command(message):
    telegram_id = message.chat.id
    track_msg(telegram_id, message.message_id)
    if not is_admin(telegram_id):
        send_and_track(telegram_id, "⛔ عذراً، هذا الأمر مخصص لمدير المتجر فقط.")
        return
    parts = message.text.split()
    if len(parts) > 1 and parts[1].strip().isdigit():
        new_id = int(parts[1].strip())
        add_admin(new_id, telegram_id)
        text = (
            f"✅ <b>تم إضافة الأدمن الجديد بنجاح!</b> 👑\n\n"
            f"👤 <b>الآيدي:</b> <code>{new_id}</code>\n\n"
            "أصبح يملك الآن كامل صلاحيات لوحة التحكم والوصول لأرشيف جميع حسابات المتجر."
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👑 لوحة الإدارة", callback_data="btn_admin_panel"))
        send_and_track(telegram_id, text, reply_markup=markup)
    else:
        send_and_track(telegram_id, "⚠️ <b>طريقة الاستخدام:</b>\nاكتب: <code>/addadmin 123456789</code>\n(استبدل الأرقام بآيدي صاحبك)")

@bot.message_handler(func=lambda msg: True)
def handle_text_messages(message):
    telegram_id = message.chat.id
    track_msg(telegram_id, message.message_id)
    
    # Check if admin is currently submitting a new Admin Telegram ID
    current_state = get_prompt_state(telegram_id) or admin_prompt_state.get(telegram_id)
    if is_admin(telegram_id) and current_state == "waiting_admin_id":
        clear_prompt_state(telegram_id)
        admin_prompt_state[telegram_id] = None
        new_id_text = message.text.strip()
        if new_id_text.isdigit():
            new_id = int(new_id_text)
            add_admin(new_id, telegram_id)
            text = (
                f"✅ <b>تم إضافة الأدمن الجديد بنجاح!</b> 👑\n\n"
                f"👤 <b>الآيدي:</b> <code>{new_id}</code>\n\n"
                "أصبح يملك الآن كامل صلاحيات لوحة التحكم والوصول لأرشيف جميع حسابات المتجر."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("👑 العودة للوحة الإدارة", callback_data="btn_admin_panel"))
            send_and_track(telegram_id, text, reply_markup=markup)
            return
        else:
            send_and_track(telegram_id, "⚠️ خطأ: يرجى إرسال رقم آيدي تليجرام صحيح (أرقام فقط)!\nأو استخدم الأمر المباشر:\n<code>/addadmin 123456789</code>")
            return

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    telegram_id = call.message.chat.id
    track_msg(telegram_id, call.message.message_id)
    data = call.data
    
    if data == "btn_main_menu":
        safe_answer(call.id)
        clear_prompt_state(telegram_id)
        admin_prompt_state[telegram_id] = None
        active = get_active_account(telegram_id)
        active_info = f"<code>{active['email']}</code>" if active else "لا يوجد إيميل نشط حالياً."
        text = (
            "⚽ <b>القائمة الرئيسية لبوت بيس موبايل</b> 🎮\n\n"
            f"📧 <b>الحساب النشط:</b>\n{active_info}\n\n"
            "👇 اختر الإجراء المطلوب:"
        )
        try:
            bot.edit_message_text(text, chat_id=telegram_id, message_id=call.message.message_id, reply_markup=get_main_menu_markup(telegram_id))
        except Exception:
            send_and_track(telegram_id, text, reply_markup=get_main_menu_markup(telegram_id))
        return

    elif data == "btn_admin_panel":
        safe_answer(call.id)
        clear_prompt_state(telegram_id)
        admin_prompt_state[telegram_id] = None
        if not is_admin(telegram_id):
            safe_answer(call.id, "⛔ ليس لديك صلاحية المدير!", show_alert=True)
            return
        show_admin_panel(telegram_id, call.message.message_id)
        return

    elif data == "btn_admin_add_prompt":
        safe_answer(call.id)
        if not is_admin(telegram_id):
            return
        set_prompt_state(telegram_id, "waiting_admin_id")
        admin_prompt_state[telegram_id] = "waiting_admin_id"
        text = (
            "➕ <b>إضافة أدمن جديد للمتجر:</b>\n\n"
            "أرسل الآن في الشات <b>رقم الآيدي (Telegram ID)</b> الخاص بصاحبك وسأقوم بإعطائه كامل الصلاحيات فوراً.\n\n"
            "💡 <i>(يمكنه معرفة الآيدي الخاص به بسهولة من بوت: @userinfobot)</i>\n\n"
            "أو يمكنك كتابة الأمر المباشر:\n<code>/addadmin 123456789</code>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 إلغاء والعودة", callback_data="btn_admin_panel"))
        send_and_track(telegram_id, text, reply_markup=markup)
        return

    elif data == "btn_admin_all_accs":
        safe_answer(call.id)
        if not is_admin(telegram_id):
            return
        all_accounts = get_all_accounts_admin(limit=15)
        if not all_accounts:
            safe_answer(call.id, "لا توجد أي حسابات منشأة حتى الآن!", show_alert=True)
            return
            
        text = "🌐 <b>أرشيف كل حسابات المتجر الشامل (Admin View):</b>\n\nاضغط على أي إيميل لفتحه وفحص رسائله وأكواد التفعيل:"
        markup = types.InlineKeyboardMarkup(row_width=1)
        for acc in all_accounts:
            btn_title = f"📧 {acc['email']} (👤 {acc['telegram_id']})"
            markup.add(types.InlineKeyboardButton(btn_title, callback_data=f"switch_{acc['id']}"))
            
        markup.add(types.InlineKeyboardButton("🔙 العودة للوحة الإدارة", callback_data="btn_admin_panel"))
        send_and_track(telegram_id, text, reply_markup=markup)
        return

    elif data == "btn_clean_screen":
        safe_answer(call.id, "جاري تنظيف الشاشة وتجهيز الجلسة...")
        
        # 1. Reset active account in DB so state is fresh (archive remains 100% safe)
        clear_active_account(telegram_id)
        
        # 2. Delete all previous messages in chat
        msg_ids_to_delete = list(user_chat_messages.get(telegram_id, []))
        if call.message.message_id not in msg_ids_to_delete:
            msg_ids_to_delete.append(call.message.message_id)
            
        for mid in msg_ids_to_delete:
            try:
                bot.delete_message(telegram_id, mid)
            except Exception:
                pass
                
        user_chat_messages[telegram_id] = []
        
        # 3. Send fresh, clean welcome message ready for next client
        fresh_text = (
            "✨ <b>تم إنهاء الجلسة وتنظيف الشاشة بنجاح!</b> 🧹\n\n"
            "🔒 <b>ملاحظة أمان:</b> جميع الإيميلات السابقة محفوظة بأمان في الأرشيف (📂) ولن تضيع أبداً.\n\n"
            "جاهز الآن للبدء مع العميل الجديد 👇"
        )
        send_and_track(telegram_id, fresh_text, reply_markup=get_main_menu_markup(telegram_id))
        return

    elif data == "btn_new_email":
        safe_answer(call.id, "جاري إنشاء إيميل دائم جديد...")
        acc_data = MailService.create_account(prefix="pes")
        
        if not acc_data:
            send_and_track(telegram_id, "⚠️ عذراً، حدث خطأ أثناء الاتصال بالخادم. يرجى المحاولة مرة أخرى بعد لحظات.")
            return
            
        save_account(
            telegram_id=telegram_id,
            email=acc_data["email"],
            password=acc_data["password"],
            account_id=acc_data["account_id"],
            token=acc_data["token"],
            note=f"أكونت {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        text = (
            "✅ <b>تم إنشاء إيميل كونامي جديد بنجاح!</b> 🎮\n\n"
            "📧 <b>البريد الإلكتروني:</b> (اضغط للنسخ)\n"
            f"<code>{acc_data['email']}</code>\n\n"
            "🔐 <b>كلمة مرور البريد:</b> (اضغط للنسخ)\n"
            f"<code>{acc_data['password']}</code>\n\n"
            "🌐 <b>موقع فتح البريد دائماً:</b>\n"
            "https://mail.tm\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>حالة البوت:</b> يستمع تلقائياً لصندوق الوارد الآن!\n"
            "أول ما تطلب كود تفعيل كونامي من اللعبة، هينزل إشعار فوري هنا بالكود المكون من 6 أرقام."
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📬 فحص الرسائل والكود", callback_data="btn_check_inbox"),
            types.InlineKeyboardButton("📋 كارت التسليم للمشتري", callback_data="btn_handover")
        )
        markup.add(types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen"))
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
        send_and_track(telegram_id, text, reply_markup=markup)

    elif data == "btn_check_inbox":
        active = get_active_account(telegram_id)
        if not active:
            safe_answer(call.id, "لا يوجد إيميل نشط! قم بتوليد إيميل أولاً.", show_alert=True)
            return
            
        safe_answer(call.id, "جاري فحص صندوق الوارد...")
        messages = MailService.get_messages(active["token"])
        
        if not messages:
            text = (
                f"📭 <b>صندوق الوارد فارغ حتى الآن!</b>\n\n"
                f"📧 الإيميل النشط: <code>{active['email']}</code>\n\n"
                "💡 تأكد أنك طلبت إرسال كود التفعيل من لعبة eFootball أو موقع كونامي، "
                "والكود سيظهر هنا تلقائياً خلال ثوانٍ معدودة."
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("🔄 تحديث الصندوق الآن", callback_data="btn_check_inbox"))
            markup.add(types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen"))
            markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
            send_and_track(telegram_id, text, reply_markup=markup)
            return

        # Show latest messages
        text = f"📬 <b>الرسائل الواردة لـ:</b> <code>{active['email']}</code>\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for idx, msg in enumerate(messages[:5], 1):
            msg_id = msg.get("id")
            subject = msg.get("subject", "بدون عنوان")
            sender = msg.get("from", {}).get("address", "غير معروف")
            
            # Fetch message detail to extract code
            detail = MailService.get_message_detail(active["token"], msg_id)
            otp_code = None
            if detail:
                intro = detail.get("intro", "")
                text_content = detail.get("text", "")
                html_content = "".join(detail.get("html", [])) if isinstance(detail.get("html"), list) else detail.get("html", "")
                otp_code = MailService.extract_otp(subject, f"{intro}\n{text_content}", html_content)
                
            text += f"📨 <b>الرسالة {idx}:</b>\n"
            text += f"👤 <b>من:</b> {sender}\n"
            text += f"📝 <b>الموضوع:</b> {subject}\n"
            if otp_code:
                text += f"🔑 <b>كود التفعيل:</b> <code>{otp_code}</code> <i>(اضغط للنسخ)</i>\n"
            text += "─────────────────\n"
            
            markup.add(types.InlineKeyboardButton(f"📖 قراءة تفاصيل رسالة ({idx})", callback_data=f"read_{msg_id}"))
            
        markup.add(types.InlineKeyboardButton("🔄 تحديث", callback_data="btn_check_inbox"))
        markup.add(types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen"))
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
        send_and_track(telegram_id, text, reply_markup=markup)

    elif data.startswith("read_"):
        active = get_active_account(telegram_id)
        if not active:
            return
            
        # SECURITY CHECK: Only owner or admin can read messages
        if str(active.get("telegram_id")) != str(telegram_id) and not is_admin(telegram_id):
            safe_answer(call.id, "⛔ ليس لديك صلاحية قراءة رسائل هذا الإيميل!", show_alert=True)
            return
            
        msg_id = data.replace("read_", "")
        detail = MailService.get_message_detail(active["token"], msg_id)
        if not detail:
            safe_answer(call.id, "تعذر جلب تفاصيل الرسالة.", show_alert=True)
            return
            
        subject = detail.get("subject", "")
        sender = detail.get("from", {}).get("address", "")
        text_body = detail.get("text", "لا يوجد محتوى نصي")[:1500]
        
        otp_code = MailService.extract_otp(subject, text_body)
        otp_banner = f"\n\n🔥 <b>كود التفعيل المستخرج:</b> <code>{otp_code}</code>\n" if otp_code else ""
        
        text = (
            f"📨 <b>تفاصيل الرسالة:</b>\n"
            f"👤 <b>من:</b> {sender}\n"
            f"📝 <b>الموضوع:</b> {subject}\n"
            f"{otp_banner}\n"
            f"📄 <b>نص الرسالة:</b>\n"
            f"<pre>{text_body}</pre>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 رجوع للوارد", callback_data="btn_check_inbox"))
        send_and_track(telegram_id, text, reply_markup=markup)

    elif data == "btn_handover":
        active = get_active_account(telegram_id)
        if not active:
            safe_answer(call.id, "قم بتوليد إيميل أولاً لإنشاء كارت المشتري!", show_alert=True)
            return
            
        card_text = (
            "🎮 <b>بيانات حساب كونامي الرسمي (Konami ID)</b> 🎮\n\n"
            "📧 <b>البريد الإلكتروني:</b>\n"
            f"<code>{active['email']}</code>\n\n"
            "🔐 <b>كلمة مرور البريد:</b>\n"
            f"<code>{active['password']}</code>\n\n"
            "🌐 <b>رابط الدخول لصندوق البريد واستلام الرسائل:</b>\n"
            "https://mail.tm\n\n"
            "⚠️ <i>ملاحظة للمشتري: يمكنك الدخول إلى الرابط أعلاه في أي وقت باستخدام الإيميل والباسورد لاستلام أي كود تفعيل أو تغيير كلمة مرور حسابك في لعبة بيس موبايل. مبروك عليك الحساب!</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen"))
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
        send_and_track(telegram_id, card_text, reply_markup=markup)

    elif data == "btn_archive":
        # Regular users only see their own accounts!
        accounts = get_user_accounts(telegram_id, limit=8)
        if not accounts:
            safe_answer(call.id, "لم تقم بإنشاء أي إيميلات بعد!", show_alert=True)
            return
            
        text = "📂 <b>أرشيف حسابات كونامي الخاصة بك:</b>\n\nاضغط على أي إيميل لجعله الحساب النشط وفحص رسائله:"
        markup = types.InlineKeyboardMarkup(row_width=1)
        for acc in accounts:
            btn_title = f"📧 {acc['email']}"
            markup.add(types.InlineKeyboardButton(btn_title, callback_data=f"switch_{acc['id']}"))
            
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
        send_and_track(telegram_id, text, reply_markup=markup)

    elif data.startswith("switch_"):
        acc_id = int(data.replace("switch_", ""))
        acc = get_account_by_id(acc_id)
        if acc:
            # STRICT SECURITY CHECK: Only owner of account or authorized Admin can switch/access!
            if str(acc.get("telegram_id")) != str(telegram_id) and not is_admin(telegram_id):
                safe_answer(call.id, "⛔ هذا الحساب ليس ملكك ولا يمكنك فتحه!", show_alert=True)
                return
                
            set_active_account(telegram_id, acc_id)
            safe_answer(call.id, "تم تفعيل الحساب بنجاح!")
            text = (
                f"✅ <b>تم التحويل إلى الإيميل:</b>\n<code>{acc['email']}</code>\n\n"
                f"🔐 كلمة المرور: <code>{acc['password']}</code>\n\n"
                "يمكنك الآن فحص رسائله أو استخراج كود التفعيل."
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("📬 فحص الرسائل", callback_data="btn_check_inbox"))
            markup.add(types.InlineKeyboardButton("📋 كارت المشتري", callback_data="btn_handover"))
            markup.add(types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen"))
            markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
            send_and_track(telegram_id, text, reply_markup=markup)

    elif data == "btn_guide":
        guide_text = (
            "ℹ️ <b>دليل ربط أكونت بيس موبايل بـ Konami ID:</b> 🎮\n\n"
            "1. افتح لعبة <b>eFootball</b> واذهب إلى: الإعدادات (Settings) ⬅️ ربط البيانات (Data Link).\n"
            "2. اختر <b>Link KONAMI ID</b> وستفتح لك صفحة كونامي الرسمية في المتصفح.\n"
            "3. اضغط على <b>Register (تسجيل حساب جديد)</b>.\n"
            "4. انسخ الإيميل والباسورد المولدين من البوت وضعهما في الخانات المطلوبة.\n"
            "5. ستطلب منك كونامي إدخال <b>كود التفعيل (6 أرقام)</b> المرسل للبريد.\n"
            "6. ارجع للبوت فوراً، اضغط 'فحص الرسائل والكود' وسيظهر كود التفعيل في ثانية!\n"
            "7. انسخ الكود بلمسة واحدة وضعه في المتصفح.. ومبروك تم ربط الأكونت بنجاح! 🏆"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="btn_main_menu"))
        send_and_track(telegram_id, guide_text, reply_markup=markup)

# Background Listener Thread for Auto OTP Push Notification (for local mode)
def background_mail_listener():
    print("[Listener] Background mail polling thread started...")
    while True:
        try:
            active_accounts = get_all_active_monitored_accounts()
            for acc in active_accounts:
                telegram_id = acc["telegram_id"]
                token = acc["token"]
                email = acc["email"]
                
                if not token:
                    continue
                    
                messages = MailService.get_messages(token)
                for msg in messages:
                    msg_id = msg.get("id")
                    unique_key = f"{email}_{msg_id}"
                    
                    if unique_key not in seen_message_ids:
                        seen_message_ids.add(unique_key)
                        
                        detail = MailService.get_message_detail(token, msg_id)
                        subject = msg.get("subject", "رسالة جديدة")
                        sender = msg.get("from", {}).get("address", "")
                        
                        intro = detail.get("intro", "") if detail else ""
                        text_content = detail.get("text", "") if detail else ""
                        html_content = "".join(detail.get("html", [])) if (detail and isinstance(detail.get("html"), list)) else (detail.get("html", "") if detail else "")
                        
                        otp_code = MailService.extract_otp(subject, f"{intro}\n{text_content}", html_content)
                        
                        if otp_code:
                            alert = (
                                "🚨 <b>وصل كود تفعيل كونامي الآن!</b> 🚨\n\n"
                                f"🔑 <b>كود التفعيل:</b> (اضغط للنسخ)\n"
                                f"<code>{otp_code}</code>\n\n"
                                f"📧 <b>الإيميل:</b> <code>{email}</code>\n"
                                f"📝 <b>الموضوع:</b> {subject}\n"
                                f"👤 <b>من:</b> {sender}\n\n"
                                "⚡ <i>انسخ الكود وضعه فوراً في صفحة التفعيل في اللعبة!</i>"
                            )
                        else:
                            alert = (
                                "📬 <b>وصلت رسالة جديدة للبريد!</b>\n\n"
                                f"📧 <b>الإيميل:</b> <code>{email}</code>\n"
                                f"📝 <b>الموضوع:</b> {subject}\n"
                                f"👤 <b>من:</b> {sender}\n\n"
                                f"📄 <b>المحتوى:</b>\n{intro[:300]}"
                            )
                            
                        markup = types.InlineKeyboardMarkup(row_width=1)
                        markup.add(types.InlineKeyboardButton("📖 قراءة التفاصيل كاملة", callback_data=f"read_{msg_id}"))
                        markup.add(types.InlineKeyboardButton("🧹 إنهاء وتجهيز لعميل جديد", callback_data="btn_clean_screen"))
                        
                        try:
                            send_and_track(telegram_id, alert, reply_markup=markup)
                        except Exception as send_err:
                            print(f"[Listener] Error sending alert to {telegram_id}: {send_err}")
                            
        except Exception as e:
            print(f"[Listener] Loop exception: {e}")
            
        time.sleep(4)

def start_bot():
    init_db()
    listener_thread = threading.Thread(target=background_mail_listener, daemon=True)
    listener_thread.start()
    
    print("=" * 50)
    print("[+] PES Konami Mail Bot is running...")
    print(f"[+] Bot Username: @{bot.get_me().username}")
    print("=" * 50)
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    start_bot()
