import logging
import json
import psycopg2
import re
import os
import google.generativeai as genai
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler


genai.configure(api_key="AIzaSyBMbwNjTK4ke8lkeWZqRhEA_eUKotpW4Hg") 
model = genai.GenerativeModel('gemini-1.5-flash')
# --- Configuration ---
ADMIN_ID = 7051052390  # Admin Thura ၏ ID
DB_URL = "postgresql://postgres.woarnfonejhleuktaidy:LA9kKT2XTIaQ9F4E@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"


# State များကို ကွင်းစကွင်းပိတ် ( ) ဖြင့် အုပ်ပေးရန် လိုအပ်ပါသည်
(CHOOSING_ACTION, CHOOSING_CAT, ADD_NAME_INPUT, ADD_IB_DISPLAY_TEXT, NAV_ADD, CHOOSING_PT_TYPE, NAV_PT, WAIT_PT_CONTENT, 
EDIT_MMB_NAME_INPUT, EDIT_TYPE_CHOOSE, NAV_EDIT, EDIT_IB_ACTION, EDIT_IB_NAME_INPUT, EDIT_DT_INPUT, EDIT_PT_TYPE_CHOOSE, EDIT_PT_NAV, WAIT_EDIT_PT_CONTENT, NAV_DEL, DEL_CONFIRM, WAIT_WM_CONTENT, CHOOSE_REQ_TYPE, WAIT_REQ_TEXT, WAIT_QTY, CONFIRM_ORDER, WAIT_REQUIREMENT, WAIT_MAIL_INFO, WAIT_PAYMENT_SLIP, SETUP_PAYMENT_INFO) = range(28)


# မြန်မာဂဏန်း ပြောင်းလဲခြင်းနှင့် စာသားသန့်စင်ခြင်း
def clean_and_normalize(text):
    burmese_digits = "၀၁၂၃၄၅၆၇၈၉"
    english_digits = "0123456789"
    table = str.maketrans(burmese_digits, english_digits)
    text = text.translate(table).lower()
    # မလိုလားအပ်သော စာသားများ ဖယ်ထုတ်ခြင်း
    stop_words = ["ဝယ်မယ်", "ယူမယ်", "ပါ", "ရှင်", "ခင်ဗျာ", "ဗျ", "uc", "diamond"]
    for word in stop_words:
        text = text.replace(word, "")
    return text.strip()

# PT စာသားထဲမှ စျေးနှုန်းနှင့် ပမာဏများကို အလိုအလျောက် ခွဲထုတ်ခြင်း
async def parse_pt_logic(text):
    prompt = f"Convert this price list into JSON. Identify Categories, Quantities, and Prices. Rule: Last number is the price. Return ONLY JSON.\nList:\n{text}"
    try:
        response = await model.generate_content_async(prompt)
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_json)
    except: return {}

async def save_pt_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    btn_id = context.user_data.get('target_btn_id')
    parsed_data = await parse_pt_logic(msg.text) if msg.text else {}
    db_query("UPDATE buttons SET content_msg_id=%s, content_chat_id=%s, parsed_data=%s WHERE id=%s", 
             (msg.message_id, msg.chat_id, json.dumps(parsed_data), btn_id))
    await update.message.reply_text(f"✅ AI မှ စျေးနှုန်း ({len(parsed_data)}) အုပ်စု ခွဲခြားမှတ်သားပြီးပါပြီ။")
    return await ask_req_type(update, context)

# handle_user_click သို့မဟုတ် Inline Click ထဲတွင် PT ပြပြီးနောက် ဤခလုတ်ကို ထည့်ပါ
async def show_buy_button(update, context, btn_id):
    kb = [[InlineKeyboardButton("🛒 ဝယ်ယူမည်", callback_data=f"buy_{btn_id}")]]
    await update.effective_message.reply_text("အထက်ပါ စျေးနှုန်းများဖြင့် ဝယ်ယူလိုပါက 'ဝယ်ယူမည်' ကို နှိပ်ပါရှင် -", 
                                             reply_markup=InlineKeyboardMarkup(kb))

# "ဝယ်ယူမည်" ကို နှိပ်လိုက်သောအခါ
async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['order_btn_id'] = int(query.data.split("_")[1])
    await query.edit_message_text("ဝယ်ယူမည့် ပမာဏ သို့မဟုတ် အမျိုးအစားကို ပို့ပေးပါရှင်။ (ဥပမာ- 1800)")
    return WAIT_QTY
    

# UC ပေါင်းစပ်တွက်ချက်ပေးသည့် Greedy Algorithm
def get_combination(target, items):
    sorted_items = sorted(items.keys(), reverse=True)
    res, total, current = [], 0, target
    for item in sorted_items:
        while current >= item:
            res.append(item); current -= item; total += items[item]
    return (res, total) if current == 0 else (None, 0)


def init_db():
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        
        # ၁။ Settings Table (Welcome Message နှင့် အထွေထွေ Setting များအတွက်)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, 
                value TEXT, 
                chat_id BIGINT
            )
        """)

        # ၂။ Buttons Table (Menu, PT နှင့် Requirement များအတွက်)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buttons (
                id SERIAL PRIMARY KEY, 
                name TEXT, 
                parent_id INTEGER, 
                type TEXT, 
                content_msg_id BIGINT, 
                content_chat_id BIGINT, 
                display_text TEXT
            )
        """)

        # ၃။ ရှိပြီးသား Table ထဲသို့ Requirement Column များ အလိုအလျောက် ထည့်ခြင်း
        # ဤအပိုင်းက Thura ကြုံနေရတဲ့ "Column does not exist" error ကို ဖြေရှင်းပေးပါလိမ့်မယ်
        cursor.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS req_type TEXT")
        cursor.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS req_text TEXT")
        cursor.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS parsed_data JSONB")

        # ၄။ Orders Table (User ဝယ်ယူမှုများနှင့် Slip များ မှတ်တမ်းတင်ရန် - အသစ်ထည့်ထားသည်)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                btn_id INTEGER,
                slip_msg_id BIGINT,
                status TEXT DEFAULT 'pending',
                user_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database Tables အားလုံး အဆင်သင့်ဖြစ်ပါပြီ။")
    except Exception as e:
        print(f"❌ Database Initialization Error: {e}")

# --- DB Helper ---
def db_query(query, params=(), fetch=False):
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = cursor.fetchall() if fetch else None
    conn.commit()
    cursor.close()
    conn.close()
    return res

# --- Filter for Universal Interruption ---
class MainMenuFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text: return False
        admin_btns = ["⚙️ Setup လုပ်မည်", "📝 Welcome Message ပြင်မည်", "👀 User အနေနဲ့ ကြည့်မည်", "🔙 Admin View သို့ ပြန်သွားမည်"]
        if message.text in admin_btns: return True
        btns = db_query("SELECT name FROM buttons WHERE type='main'", fetch=True)
        return message.text in [b[0] for b in btns]

mmb_filter = MainMenuFilter()
# --- Keyboard Helpers ---
def get_admin_kb():
    # Admin Panel အတွက် ခလုတ်များ (၂ တန်းခွဲ၍ သေသပ်အောင် စီစဉ်ထားသည်)
    btns = [
        ["⚙️ Setup လုပ်မည်", "📝 Welcome Message ပြင်မည်"],
        ["💰 Payment Info ပြင်မည်", "👀 User အနေနဲ့ ကြည့်မည်"]
    ]
    return ReplyKeyboardMarkup(btns, resize_keyboard=True)

def get_user_kb(is_admin_view=False):
    # Main Menu ခလုတ်များကို DB မှ ဆွဲထုတ်ခြင်း
    main_btns = db_query("SELECT name FROM buttons WHERE type='main'", fetch=True)
    kb = [ [b[0] for b in main_btns[i:i+2]] for i in range(0, len(main_btns), 2) ]
    if is_admin_view:
        kb.append(["🔙 Admin View သို့ ပြန်သွားမည်"]) # Admin အတွက် Back Button
    return ReplyKeyboardMarkup(kb, resize_keyboard=True) if kb else ReplyKeyboardRemove()

# --- Start Logic (Admin vs User) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_user_view = context.user_data.get('is_user_view', False)
    
    # ၁။ Admin ဖြစ်ပြီး User View Mode ထဲ မရောက်နေလျှင် (Admin Panel ပြမည်)
    if uid == ADMIN_ID and not is_user_view:
        await update.message.reply_text("မင်္ဂလာပါ Admin Thura။", reply_markup=get_admin_kb())
        return

    # ၂။ User ဘက်မှ မြင်ကွင်း (Welcome Message နှင့် Main Menu ပြမည်)
    welcome_res = db_query("SELECT value, chat_id FROM settings WHERE key='welcome_msg_id'", fetch=True)
    
    if welcome_res:
        # Welcome Message (စာသား/ပုံ) ကို ပို့ပေးခြင်း
        await context.bot.copy_message(
            chat_id=uid, 
            from_chat_id=welcome_res[0][1], 
            message_id=int(welcome_res[0][0])
        )
        await update.message.reply_text("Menu ကို အသုံးပြုနိုင်ပါပြီ။", reply_markup=get_user_kb(is_admin_view=is_user_view))
    else:
        # Welcome Message မရှိသေးလျှင်
        await update.message.reply_text("ဆိုင်ခေတ္တပိတ်ထားပါသည်။", reply_markup=ReplyKeyboardRemove())

async def handle_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    qty_num = re.findall(r'\d+', clean_and_normalize(user_input))
    
    if not qty_num:
        await update.message.reply_text("⚠️ ဝယ်ယူမည့် ပမာဏကို ကိန်းဂဏန်းဖြင့် သေချာစွာ ရိုက်ပို့ပေးပါရှင်။")
        return WAIT_QTY

    target = int(qty_num[0])
    btn_id = context.user_data.get('order_btn_id')
    res = db_query("SELECT parsed_data, name FROM buttons WHERE id=%s", (btn_id,), fetch=True)
    
    # Caching ထဲက data အားလုံးကို ပေါင်းပြီး တွက်ချက်ခြင်း
    p_data = res[0][0]; all_items = {}
    for cat in p_data.values(): all_items.update(cat)
    
    comb, price = get_combination(target, {int(k):v for k,v in all_items.items()})
    if comb:
        context.user_data.update({'order_qty': target, 'order_price': price, 'order_item': res[0][1]})
        kb = [[InlineKeyboardButton("✅ ဟုတ်တယ်", callback_data="conf_yes"), 
               InlineKeyboardButton("❌ မဟုတ်ဘူး", callback_data="conf_no")]]
        await update.message.reply_text(f"🛒 **အတည်ပြုရန်**\nပစ္စည်း: {res[0][1]}\nပမာဏ: {target}\nကျသင့်ငွေ: {price:,} ks\n\nမှန်ကန်ပါသလားရှင်?", 
                                       reply_markup=InlineKeyboardMarkup(kb))
        return CONFIRM_ORDER
    else:
        await update.message.reply_text("❌ ထိုပမာဏကို ဝယ်ယူ၍မရပါ။ စာရင်းထဲရှိ ပမာဏကို ပြန်ရိုက်ပေးပါရှင်။")
        return WAIT_QTY

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "conf_no":
        await query.edit_message_text("ဝယ်ယူမည့် ပမာဏကို ပြန်လည် ပို့ပေးပါရှင် -")
        return WAIT_QTY
    
    # "ဟုတ်တယ်" ဆိုလျှင် Requirement စစ်မည်
    btn_id = context.user_data.get('order_btn_id')
    res = db_query("SELECT req_type, req_text FROM buttons WHERE id=%s", (btn_id,), fetch=True)
    req_type, req_text = res[0]
    
    if req_type == 'choice':
        kb = [[InlineKeyboardButton("🔘 Admin Mail", callback_data="mail_admin"),
               InlineKeyboardButton("🔘 ကိုယ်ပိုင် Mail", callback_data="mail_user")]]
        await query.edit_message_text("ဝယ်ယူမည့် ပုံစံကို ရွေးချယ်ပေးပါရှင် -", reply_markup=InlineKeyboardMarkup(kb))
        return WAIT_MAIL_INFO
    else:
        await query.edit_message_text(f"📝 {req_text if req_text else 'အချက်အလက် ပေးပို့ပါ'}:")
        return WAIT_REQUIREMENT

# Requirement ရပြီးလျှင် Payment Info (Copy Message) ပြသခြင်း
async def show_payment(update, context):
    pay_res = db_query("SELECT value, chat_id FROM settings WHERE key='payment_info_id'", fetch=True)
    if pay_res:
        await context.bot.copy_message(chat_id=update.effective_chat.id, 
                                      from_chat_id=pay_res[0][1], message_id=int(pay_res[0][0]))
    await update.message.reply_text("ငွေလွှဲပြီးပါက 'ပြေစာ (Slip)' ကို ဤနေရာတွင် ပုံရိုက်ပို့ပေးပါဗျ -")
    return WAIT_PAYMENT_SLIP

async def handle_slip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    full_name = f"[{user.full_name}](tg://user?id={user.id})"
    username = f"@{user.username}" if user.username else "Username မရှိပါ"
    
    order_info = (f"🔔 **Order အသစ်!**\n"
                  f"👤 Customer: [{user.full_name}](tg://user?id={user.id})\n"
                  f"🏷️ Username: {username}\n"
                  f"🆔 User ID: `{user.id}`\n---\n"
                  f"📦 Item: {context.user_data['order_item']}\n"
                  f"🔢 Qty: {context.user_data['order_qty']}\n"
                  f"💰 Total: {context.user_data['order_price']:,} ks\n"
                  f"📝 Info: {context.user_data.get('user_req', 'Choice: ' + context.user_data.get('mail_choice', ''))}")
    
    kb = [[InlineKeyboardButton("✅ Accept", callback_data=f"ord_acc_{user.id}"),
           InlineKeyboardButton("❌ Reject", callback_data=f"ord_rej_{user.id}")]]
    
    # Admin ဆီ Slip နှင့် အချက်အလက်ပို့ခြင်း
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, 
                                 caption=order_info, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Order တင်ပြီးပါပြီ။ Admin မှ စစ်ဆေးပြီး အကြောင်းပြန်ပေးပါလိမ့်မည်။")
    return ConversationHandler.END

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.split("_")[1]
    context.user_data['cat'] = cat
    action = context.user_data.get('action')

    if action == "add":
        if cat == "main":
            context.user_data['target_parent_id'] = None
            await query.edit_message_text("Main Menu ခလုတ်အသစ်အတွက် နာမည်ပေးပါ -")
            return ADD_NAME_INPUT
        elif cat == "inline":
            return await show_add_navigation(query, context, p_id=None)
        elif cat == "pt":
            kb = [[InlineKeyboardButton("Main Menu (MMB) ထဲမှာထည့်မည်", callback_data="pttype_mmb")],
                  [InlineKeyboardButton("Inline Button (IB) ထဲမှာထည့်မည်", callback_data="pttype_ib")]]
            await query.edit_message_text("ဘယ်နေရာမှာ PT ထည့်မှာလဲ?", reply_markup=InlineKeyboardMarkup(kb))
            return CHOOSING_PT_TYPE
            
    elif action == "edit":
        if cat == "main":
            btns = db_query("SELECT id, name FROM buttons WHERE type='main'", fetch=True)
            kb = [[InlineKeyboardButton(b[1], callback_data=f"editmmb_{b[0]}")] for b in btns]
            await query.edit_message_text("နာမည်ပြင်လိုသော Main Menu ခလုတ်ကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
            return NAV_EDIT
        elif cat == "inline":
            kb = [[InlineKeyboardButton("📝 Display Text (DT) ပြင်မည်", callback_data="edtype_dt")],
                  [InlineKeyboardButton("✏️ Inline Button (IB) နာမည်ပြင်မည်", callback_data="edtype_name")]]
            await query.edit_message_text("Inline Button အပိုင်းမှာ ဘာကိုပြင်မှာလဲ?", reply_markup=InlineKeyboardMarkup(kb))
            return EDIT_TYPE_CHOOSE
        elif cat == "pt": # PT ပြင်ဆင်ခြင်းအတွက် လမ်းကြောင်းသစ်
            kb = [[InlineKeyboardButton("🔘 Main Menu (MMB) က PT ကိုပြင်မည်", callback_data="edpttype_mmb")],
                  [InlineKeyboardButton("📑 Inline Button (IB) က PT ကိုပြင်မည်", callback_data="edpttype_ib")]]
            await query.edit_message_text("ဘယ်နေရာက PT ကို ပြင်မှာလဲ?", reply_markup=InlineKeyboardMarkup(kb))
            return EDIT_PT_TYPE_CHOOSE
    
    if action == "del":
        if cat == "main": # MMB ဖျက်သိမ်းခြင်း လမ်းကြောင်း
            btns = db_query("SELECT id, name FROM buttons WHERE type='main'", fetch=True)
            kb = [[InlineKeyboardButton(b[1], callback_data=f"delnav_{b[0]}")] for b in btns]
            kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_cat")])
            await query.edit_message_text("ဖျက်သိမ်းလိုသော Main Menu ခလုတ်ကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
            return NAV_DEL
        elif cat == "inline": # IB ဖျက်သိမ်းခြင်း လမ်းကြောင်း (Filtering ပါဝင်သည်)
            context.user_data['del_mode'] = 'ib'
            # IB ရှိသော MMB များကိုသာ ပြမည်
            btns = db_query("SELECT id, name FROM buttons WHERE type='main' AND id IN (SELECT DISTINCT parent_id FROM buttons WHERE parent_id IS NOT NULL)", fetch=True)
            kb = [[InlineKeyboardButton(b[1], callback_data=f"delnav_{b[0]}")] for b in btns]
            kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_cat")])
            await query.edit_message_text("Inline Button များရှိသည့် MMB ကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
            return NAV_DEL
        elif cat == "pt": # PT ဖျက်သိမ်းခြင်း လမ်းကြောင်း
            context.user_data['del_mode'] = 'pt'
            btns = db_query("SELECT id, name FROM buttons WHERE type='main'", fetch=True)
            kb = [[InlineKeyboardButton(b[1], callback_data=f"delnav_{b[0]}")] for b in btns]
            kb.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_cat")])
            await query.edit_message_text("PT ဖျက်လိုသည့် ခလုတ်လမ်းကြောင်းကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
            return NAV_DEL
            
    return CHOOSING_CAT
    
async def show_add_navigation(query, context, p_id=None):
    context.user_data['target_parent_id'] = p_id
    cat = context.user_data.get('cat')
    
    # SQL Query: PT (content_msg_id) ရှိနေသော ခလုတ်များကို ဖယ်ထုတ်၍ ရှာပါသည်
    if p_id is None:
        # Root Level: PT မရှိသော MMB များကိုသာ ပြမည်
        btns = db_query("SELECT id, name FROM buttons WHERE parent_id IS NULL AND content_msg_id IS NULL", fetch=True)
    else:
        # Drill-down Level: PT မရှိသော IB များကိုသာ ပြမည်
        btns = db_query("SELECT id, name FROM buttons WHERE parent_id=%s AND content_msg_id IS NULL", (p_id,), fetch=True)

    kb = [[InlineKeyboardButton(f"📁 {b[1]}", callback_data=f"sel_{b[0]}")] for b in btns]
    
    # Thura မှာထားသည့်အတိုင်း Root မှာ "ဒီနေရာမှာထည့်မည်" ကို ဖုံးထားပါမည်
    # p_id ရှိမှသာ (MMB တစ်ခုခုထဲ ရောက်မှသာ) IB ထည့်ရန် ခလုတ်ကို ပြပါမည်
    if p_id is not None:
        kb.append([InlineKeyboardButton("📍 ဒီနေရာမှာထည့်မည်", callback_data="here")])

    # Back Logic
    if p_id is None:
        kb.append([InlineKeyboardButton("🔙 Back to Category", callback_data="back_to_cat")])
    else:
        res = db_query("SELECT parent_id FROM buttons WHERE id=%s", (p_id,), fetch=True)
        back_id = res[0][0] if res else None
        back_data = f"sel_{back_id}" if back_id else "nav_root"
        kb.append([InlineKeyboardButton("🔙 Back", callback_data=back_data)])

    text = "ဘယ်နေရာမှာ ထည့်မှာလဲ?" if btns or p_id else "⚠️ IB ထည့်ရန် သင့်တော်သော MMB မရှိပါ။ (အားလုံးတွင် PT ရှိနေသည်)"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return NAV_ADD

async def handle_add_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_cat":
        return await handle_action(update, context) # Category Menu သို့ ပြန်သွားခြင်း
        
    data = query.data

    if data == "here":
        await query.edit_message_text("ခလုတ်နာမည်ပေးပါ -")
        return ADD_NAME_INPUT

    if data == "nav_root":
        return await show_add_navigation(query, context, p_id=None)
        
    if data.startswith("sel_"):
        btn_id = int(data.split("_")[1])
        context.user_data['target_parent_id'] = btn_id
        
        # Thura ၏ မူလ Logic: အောက်မှာ IB ရှိ/မရှိ စစ်ဆေးခြင်း
        children = db_query("SELECT id FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)
        if not children:
            # IB လုံးဝမရှိသေးလျှင် DT အရင်တောင်းမည် (Thura ၏ မူလ code အတိုင်း)
            await query.edit_message_text("Inline Button တွေနဲ့အတူပြရမယ့် Display Text ကို ပေးပါ -")
            return ADD_IB_DISPLAY_TEXT
        else:
            # ရှိပြီးသားဆိုလျှင် အထဲအဆင့်ဆင့် ထပ်ဝင်မည်
            return await show_add_navigation(query, context, p_id=btn_id)

# --- Toggle View Mode Logic ---
async def toggle_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "👀 User အနေနဲ့ ကြည့်မည်":
        context.user_data['is_user_view'] = True
        await update.message.reply_text("User မြင်ကွင်းသို့ ပြောင်းလဲထားသည်။", reply_markup=get_user_kb(is_admin_view=True))
    elif text == "🔙 Admin View သို့ ပြန်သွားမည်":
        context.user_data['is_user_view'] = False
        await update.message.reply_text("Admin Panel သို့ ပြန်ရောက်ပါပြီ။", reply_markup=get_admin_kb())

async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("➕ အသစ်ထည့်မည်", callback_data="act_add")],
        [InlineKeyboardButton("📝 ပြင်ဆင်မည်", callback_data="act_edit")],
        [InlineKeyboardButton("🗑 ဖျက်သိမ်းမည်", callback_data="act_del")]
    ]
    await update.message.reply_text("ဘာလုပ်လိုပါသလဲ?", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSING_ACTION

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # query.data ရှိလျှင် action ကို update လုပ်မည်၊ မရှိလျှင် user_data ထဲကအတိုင်း သုံးမည်
    if query.data.startswith("act_"):
        action = query.data.split("_")[1]
        context.user_data['action'] = action
    else:
        action = context.user_data.get('action')

    kb = [[InlineKeyboardButton("🔘 Main Menu Button", callback_data="cat_main")],
          [InlineKeyboardButton("📑 Inline Button", callback_data="cat_inline")],
          [InlineKeyboardButton("🔤 Prize Text (စာသား/ပုံ)", callback_data="cat_pt")]]
    
    # action အလိုက် စာသားပြောင်းလဲခြင်း
    act_text = "အသစ်ထည့်ရန်" if action == "add" else "ပြင်ဆင်ရန်" if action == "edit" else "ဖျက်သိမ်းရန်"
    await query.edit_message_text(f"{act_text} အမျိုးအစား ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSING_CAT
    
async def save_ib_display_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    p_id = context.user_data.get('target_parent_id')
    db_query("UPDATE buttons SET display_text=%s WHERE id=%s", (text, p_id))
    await update.message.reply_text(f"Display Text မှတ်သားပြီးပါပြီ။\n\nအခု အဲ့ဒီအောက်မှာပြမယ့် ခလုတ်နာမည်ပေးပါ -")
    return ADD_NAME_INPUT

async def save_new_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    p_id = context.user_data.get('target_parent_id')
    cat = context.user_data.get('cat')
    btn_type = 'main' if cat == 'main' else 'inline'
    
    db_query("INSERT INTO buttons (name, parent_id, type) VALUES (%s, %s, %s)", (name, p_id, btn_type))
    await update.message.reply_text(f"✅ '{name}' ခလုတ်ကို သိမ်းဆည်းပြီးပါပြီ။", reply_markup=get_admin_kb())
    return ConversationHandler.END    

async def handle_pt_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pt_type = query.data.split("_")[1]
    context.user_data['pt_type'] = pt_type # 'mmb' သို့မဟုတ် 'ib'
    return await show_pt_navigation(query, context, p_id=None)

async def show_pt_navigation(query, context, p_id=None):
    btns = db_query("SELECT id, name FROM buttons WHERE parent_id" + (" IS NULL" if p_id is None else "=%s"), 
                   (() if p_id is None else (p_id,)), fetch=True)
    kb = [[InlineKeyboardButton(b[1], callback_data=f"ptnav_{b[0]}")] for b in btns]
    
    # Back Logic: အပြင်ဆုံးဆိုလျှင် Category Menu သို့၊ အထဲရောက်နေလျှင် Parent ဆီသို့
    if p_id is None:
        kb.append([InlineKeyboardButton("🔙 Back to Category", callback_data="back_to_cat")])
    else:
        res = db_query("SELECT parent_id FROM buttons WHERE id=%s", (p_id,), fetch=True)
        back_id = res[0][0] if res else None
        back_data = f"ptnav_{back_id}" if back_id else "ptnav_root" # ptnav_root ဟု ပြင်ထားသည်
        kb.append([InlineKeyboardButton("🔙 Back", callback_data=back_data)])

    await query.edit_message_text("PT ထည့်လိုသည့် ခလုတ်ကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
    return NAV_PT

async def handle_pt_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "back_to_cat":
        action = context.user_data.get('action')
        kb = [
            [InlineKeyboardButton("🔘 Main Menu Button", callback_data="cat_main")],
            [InlineKeyboardButton("📑 Inline Button", callback_data="cat_inline")],
            [InlineKeyboardButton("🔤 Prize Text (စာသား/ပုံ)", callback_data="cat_pt")]
        ]
        await query.edit_message_text(f"{'အသစ်ထည့်ရန်' if action == 'add' else 'ပြင်ဆင်ရန်'} အမျိုးအစား ရွေးပါ -", 
                                     reply_markup=InlineKeyboardMarkup(kb))
        return CHOOSING_CAT
    if query.data == "ptnav_root": 
        return await show_pt_navigation(query, context, p_id=None)
    
    btn_id = int(query.data.split("_")[1])
    context.user_data['target_btn_id'] = btn_id
    pt_type = context.user_data.get('pt_type')
    
    # ဤခလုတ်အောက်တွင် နောက်ထပ် IB ရှိ၊ မရှိ စစ်ဆေးခြင်း
    children = db_query("SELECT id FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)

    if pt_type == "mmb":
        if children: # MMB အောက်မှာ IB ရှိနေလျှင် PT ထည့်ခွင့်မပြု
            await query.edit_message_text("❌ ဤ MMB အောက်တွင် IB များ ရှိနေသောကြောင့် PT ထည့်၍မရပါ။")
            return ConversationHandler.END
        else:
            await query.edit_message_text("အိုကေ၊ ဤ MMB အတွက်ပြမည့် စျေးနှုန်းစာသား သို့မဟုတ် ပုံကို ပို့ပေးပါ (Premium Emoji ရပါသည်) -")
            return WAIT_PT_CONTENT
    else: # IB လမ်းကြောင်းဖြစ်လျှင်
        if children: # နောက်ထပ် IB ရှိနေသေးလျှင် အထဲထပ်ဝင်မည်
            return await show_pt_navigation(query, context, p_id=btn_id)
        else: # Leaf Node (အဆုံးသတ်) ရောက်လျှင် PT တောင်းမည်
            await query.edit_message_text("အိုကေ၊ ဤ IB အတွက်ပြမည့် စျေးနှုန်းစာသား သို့မဟုတ် ပုံကို ပို့ပေးပါ -")
            return WAIT_PT_CONTENT

# PT သိမ်းပြီးလျှင် Requirement မေးခွန်းသို့ လွှဲပေးမည့် function
async def ask_req_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("⌨️ စာသားဖြင့်တောင်းမည် (Game ID စသည်)", callback_data="reqtype_text")],
        [InlineKeyboardButton("🔘 ရွေးချယ်မှုဖြင့်တောင်းမည် (Admin/User Mail)", callback_data="reqtype_choice")]
    ]
    text = "✅ PT သိမ်းဆည်းပြီးပါပြီ။\n\nဒီပစ္စည်းအတွက် ငွေလွှဲပြီးရင် User ဆီက အချက်အလက် ဘယ်လိုတောင်းမလဲ?"
    
    # Message အမျိုးအစားအလိုက် (Text သို့မဟုတ် Callback) တုံ့ပြန်ပုံ ညှိထားသည်
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSE_REQ_TYPE

async def handle_req_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    req_type = query.data.split("_")[1]
    btn_id = context.user_data.get('target_btn_id')
    
    if req_type == "text":
        context.user_data['temp_req_type'] = 'text'
        await query.edit_message_text("User ဆီက ဘာတောင်းမလဲ? (ဥပမာ - 'Game ID နှင့် Server ပို့ပေးပါ' စသဖြင့် ရေးပေးပါ) -")
        return WAIT_REQ_TEXT
    else:
        # Choice ဆိုလျှင် Code ထဲတွင် Hardcode လုပ်ထားသဖြင့် စာသားတောင်းရန် မလိုပါ
        db_query("UPDATE buttons SET req_type='choice', req_text=NULL WHERE id=%s", (btn_id,))
        await query.edit_message_text("✅ 'ရွေးချယ်မှုစနစ်' သတ်မှတ်ပြီးပါပြီ။ (User အား Admin Mail/User Mail ရွေးခိုင်းပါမည်)", reply_markup=get_admin_kb())
        return ConversationHandler.END

async def save_req_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req_text = update.message.text
    btn_id = context.user_data.get('target_btn_id')
    db_query("UPDATE buttons SET req_type='text', req_text=%s WHERE id=%s", (req_text, btn_id))
    await update.message.reply_text(f"✅ Requirement စာသားကို '{req_text}' အဖြစ် သတ်မှတ်ပြီးပါပြီ။", reply_markup=get_admin_kb())
    return ConversationHandler.END

# --- Edit Logic Parts ---
async def handle_edit_type_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_sub_type'] = query.data.split("_")[1] # 'dt' သို့မဟုတ် 'name'
    return await show_edit_navigation(query, context, p_id=None)

async def show_edit_navigation(query, context, p_id=None):
    btns = db_query("SELECT id, name FROM buttons WHERE parent_id" + (" IS NULL" if p_id is None else "=%s"), 
                   (() if p_id is None else (p_id,)), fetch=True)
    kb = [[InlineKeyboardButton(b[1], callback_data=f"ednav_{b[0]}")] for b in btns]

    # Back Logic: Edit Flow အတွက်လည်း အဆင့်ဆင့် ပြန်ဆုတ်နိုင်ရမည်
    if p_id is None:
        kb.append([InlineKeyboardButton("🔙 Back to Category", callback_data="back_to_cat")])
    else:
        res = db_query("SELECT parent_id FROM buttons WHERE id=%s", (p_id,), fetch=True)
        back_id = res[0][0] if res else None
        back_data = f"ednav_{back_id}" if back_id else "ednav_root"
        kb.append([InlineKeyboardButton("🔙 Back", callback_data=back_data)])

    await query.edit_message_text("ပြင်ဆင်လိုသော ခလုတ်လမ်းကြောင်းကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
    return NAV_EDIT

async def handle_edit_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "back_to_cat":
        action = context.user_data.get('action')
        kb = [
            [InlineKeyboardButton("🔘 Main Menu Button", callback_data="cat_main")],
            [InlineKeyboardButton("📑 Inline Button", callback_data="cat_inline")],
            [InlineKeyboardButton("🔤 Prize Text (စာသား/ပုံ)", callback_data="cat_pt")]
        ]
        await query.edit_message_text(f"{'အသစ်ထည့်ရန်' if action == 'add' else 'ပြင်ဆင်ရန်'} အမျိုးအစား ရွေးပါ -", 
                                     reply_markup=InlineKeyboardMarkup(kb))
        return CHOOSING_CAT
    if query.data == "ednav_root": 
        return await show_edit_navigation(query, context, p_id=None)
    
    btn_id = int(query.data.split("_")[1])
    context.user_data['target_btn_id'] = btn_id
    
    # ၁။ MMB နာမည်ပြင်ခြင်းလမ်းကြောင်းဖြစ်လျှင်
    if context.user_data.get('cat') == "main":
        await query.edit_message_text("ခလုတ်အတွက် နာမည်အသစ် ပေးပါ -")
        return EDIT_MMB_NAME_INPUT

    # ၂။ IB/DT အတွက် Check Logic
    children = db_query("SELECT id, name FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)
    res = db_query("SELECT content_msg_id, display_text, name FROM buttons WHERE id=%s", (btn_id,), fetch=True)
    has_pt = res[0][0] if res else None
    curr_dt = res[0][1] if res else ""
    curr_name = res[0][2] if res else ""

    # Gatekeeper: PT ရှိလျှင် သို့မဟုတ် အလွတ်ဖြစ်လျှင် ရပ်မည်
    if has_pt:
        await query.edit_message_text(f"❌ '{curr_name}' သည် PT ထည့်ထားသော နေရာဖြစ်၍ ပြင်ဆင်၍မရပါ။")
        return ConversationHandler.END
    if not children and not has_pt:
        await query.edit_message_text(f"❌ '{curr_name}' အောက်တွင် ဘာမှမရှိသောကြောင့် ပြင်ဆင်၍မရပါ။")
        return ConversationHandler.END

    # ၃။ လမ်းကြောင်းအလိုက် ဆက်သွားခြင်း
    sub_type = context.user_data.get('edit_sub_type')
    if sub_type == "dt": # Display Text ပြင်မည့်အပိုင်း
        kb = [[InlineKeyboardButton(f"📁 {b[1]}", callback_data=f"ednav_{b[0]}")] for b in children]
        kb.append([InlineKeyboardButton("📝 ဤအဆင့်၏ DT ကိုပြင်မည်", callback_data=f"do_edit_dt_{btn_id}")])
        await query.edit_message_text(f"လက်ရှိ DT: {curr_dt if curr_dt else 'မရှိသေးပါ'}\n\nဘယ်အဆင့်ကို ဆက်သွားမလဲ သို့မဟုတ် DT ပြင်မလား?", reply_markup=InlineKeyboardMarkup(kb))
        return NAV_EDIT
    else: # IB Name ပြင်မည့်အပိုင်း
        kb = [[InlineKeyboardButton(b[1], callback_data=f"edprompt_{b[0]}")] for b in children]
        await query.edit_message_text("ပြင်ဆင်လိုသည့် Inline Button ကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
        return NAV_EDIT

async def handle_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # IB Name အတွက် "ပြင်မည်" သို့မဟုတ် "ဆက်ဝင်မည်" မေးခြင်း
    query = update.callback_query
    await query.answer()
    btn_id = int(query.data.split("_")[1])
    context.user_data['target_btn_id'] = btn_id
    
    res = db_query("SELECT name, display_text FROM buttons WHERE id=%s", (btn_id,), fetch=True)
    name, dt = res[0]
    
    kb = [[InlineKeyboardButton("✏️ နာမည်ပြင်မည်", callback_data=f"do_edit_name_{btn_id}"),
           InlineKeyboardButton("📂 ဆက်ဝင်မည်", callback_data=f"ednav_{btn_id}")]]
    await query.edit_message_text(f"ခလုတ်: {name}\nDT: {dt if dt else 'မရှိပါ'}\n\nဘာလုပ်လိုပါသလဲ?", reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_IB_ACTION

# --- PT Edit Flow Logic (Filtering & Drill-down) ---

async def handle_edit_pt_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_pt_mode'] = query.data.split("_")[1] # 'mmb' သို့မဟုတ် 'ib'
    return await show_edit_pt_navigation(query, context, p_id=None)

async def show_edit_pt_navigation(query, context, p_id=None):
    mode = context.user_data.get('edit_pt_mode')
    
    if p_id is None: # Root Level (MMB ရွေးချယ်မှု)
        if mode == "mmb":
            # PT ရှိသော MMB များကိုသာ ပြမည် (IB ရှိသော MMB များကို ဖုံးထားမည်)
            btns = db_query("SELECT id, name FROM buttons WHERE type='main' AND content_msg_id IS NOT NULL", fetch=True)
        else:
            # အောက်တွင် IB ရှိသော MMB များကိုသာ ပြမည်
            btns = db_query("SELECT id, name FROM buttons WHERE type='main' AND id IN (SELECT DISTINCT parent_id FROM buttons WHERE parent_id IS NOT NULL)", fetch=True)
    else: # Drill-down Level (IB များ ရွေးချယ်မှု)
        # အောက်တွင် IB ထပ်ရှိသော ခလုတ် သို့မဟုတ် PT ရှိပြီးသား ခလုတ်များကိုသာ ပြမည်
        btns = db_query("""SELECT id, name FROM buttons WHERE parent_id=%s AND 
                           (id IN (SELECT DISTINCT parent_id FROM buttons WHERE parent_id IS NOT NULL) 
                            OR content_msg_id IS NOT NULL)""", (p_id,), fetch=True)

    kb = [[InlineKeyboardButton(b[1], callback_data=f"edptnav_{b[0]}")] for b in btns]
    
    # Back Logic: Unified Back
    if p_id is None:
        kb.append([InlineKeyboardButton("🔙 Back to Category", callback_data="back_to_cat")])
    else:
        res = db_query("SELECT parent_id FROM buttons WHERE id=%s", (p_id,), fetch=True)
        back_id = res[0][0] if res else None
        back_data = f"edptnav_{back_id}" if back_id else "edptnav_root"
        kb.append([InlineKeyboardButton("🔙 Back", callback_data=back_data)])

    text = "ပြင်ဆင်လိုသော PT ရှိသည့် ခလုတ်ကို ရွေးပါ -" if btns else "⚠️ ပြင်ဆင်ရန် PT ရှိသော ခလုတ် မတွေ့ပါ။"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_PT_NAV

async def handle_edit_pt_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_cat": # Common Back Handler
        action = context.user_data.get('action')
        kb = [[InlineKeyboardButton("🔘 Main Menu Button", callback_data="cat_main")],
              [InlineKeyboardButton("📑 Inline Button", callback_data="cat_inline")],
              [InlineKeyboardButton("🔤 Prize Text (စာသား/ပုံ)", callback_data="cat_pt")]]
        await query.edit_message_text(f"ပြင်ဆင်ရန် အမျိုးအစား ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
        return CHOOSING_CAT

    if query.data == "edptnav_root":
        return await show_edit_pt_navigation(query, context, p_id=None)

    btn_id = int(query.data.split("_")[1])
    context.user_data['target_btn_id'] = btn_id
    
    res = db_query("SELECT content_msg_id, content_chat_id, name FROM buttons WHERE id=%s", (btn_id,), fetch=True)
    c_msg, c_chat, name = res[0]
    
    # Check if it has child IBs
    children = db_query("SELECT id FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)
    
    if children: # Folder ဖြစ်နေလျှင် အထဲဆက်ဝင်မည်
        return await show_edit_pt_navigation(query, context, p_id=btn_id)
    else: # Leaf Node (PT ရှိသောနေရာ) ရောက်လျှင် Preview ပြပြီး စာသားတောင်းမည်
        await query.message.reply_text(f"📍 '{name}' ၏ လက်ရှိ PT မှာ အောက်ပါအတိုင်း ဖြစ်သည် -")
        await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=c_chat, message_id=c_msg)
        await query.message.reply_text("စာသားအသစ် သို့မဟုတ် ပုံအသစ်ကို ပို့ပေးပါ -")
        return WAIT_EDIT_PT_CONTENT

# --- Delete Flow Logic (Cascading & Confirmation) ---

async def show_del_navigation(query, context, p_id=None):
    mode = context.user_data.get('del_mode')
    
    # Filtering Logic: IB Mode ဆိုလျှင် IB ရှိသော ခလုတ်များကိုသာ ပြမည်
    if mode == 'ib':
        btns = db_query("SELECT id, name FROM buttons WHERE parent_id" + (" IS NULL" if p_id is None else "=%s") + 
                       " AND (id IN (SELECT DISTINCT parent_id FROM buttons WHERE parent_id IS NOT NULL) OR type='inline')", 
                       (() if p_id is None else (p_id,)), fetch=True)
    else: # PT သို့မဟုတ် MMB Mode
        btns = db_query("SELECT id, name FROM buttons WHERE parent_id" + (" IS NULL" if p_id is None else "=%s"), 
                       (() if p_id is None else (p_id,)), fetch=True)

    kb = [[InlineKeyboardButton(f"📁 {b[1]}" if db_query("SELECT id FROM buttons WHERE parent_id=%s", (b[0],), fetch=True) else b[1], 
                                 callback_data=f"delnav_{b[0]}")] for b in btns]
    
    # Back Logic: အပြင်ဆုံးဆိုလျှင် Category Menu သို့၊ အထဲရောက်နေလျှင် Parent ဆီသို့
    if p_id is None:
        kb.append([InlineKeyboardButton("🔙 Back to Category", callback_data="back_to_cat")])
    else:
        res = db_query("SELECT parent_id FROM buttons WHERE id=%s", (p_id,), fetch=True)
        back_id = res[0][0] if res else None
        back_data = f"delnav_{back_id}" if back_id is not None else "delnav_root"
        kb.append([InlineKeyboardButton("🔙 Back", callback_data=back_data)])

    await query.edit_message_text("ဖျက်သိမ်းလိုသော လမ်းကြောင်းကို ရွေးပါ -", reply_markup=InlineKeyboardMarkup(kb))
    return NAV_DEL

async def handle_del_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Back to Category Menu logic
    if query.data in ["back_to_cat", "delnav_root"]:
        return await handle_action(update, context)

    btn_id = int(query.data.split("_")[1])
    context.user_data['target_btn_id'] = btn_id
    cat = context.user_data.get('cat')
    
    res = db_query("SELECT name, content_msg_id, content_chat_id, type FROM buttons WHERE id=%s", (btn_id,), fetch=True)
    name, c_msg, c_chat, b_type = res[0]
    children = db_query("SELECT id FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)

    # Thura မှာထားသည့်အတိုင်း IB Mode မှာ MMB ဆိုလျှင် တန်းဝင်မည်
    if cat == "inline" and b_type == "main":
        return await show_del_navigation(query, context, p_id=btn_id)

    if cat == "main":
        kb = [[InlineKeyboardButton("🗑 ဤ MMB ကို ဖျက်မည်", callback_data=f"do_del_btn_{btn_id}")],
              [InlineKeyboardButton("🔙 Back", callback_data="delnav_root")]] # Back Button ထည့်ထားသည်
        await query.edit_message_text(f"ခလုတ်: {name}\n\n⚠️ ဖျက်မှာ သေချာပါသလား?", reply_markup=InlineKeyboardMarkup(kb))
    
    elif cat == "inline":
        if children:
            kb = [[InlineKeyboardButton("📂 အထဲသို့ ဆက်ဝင်မည်", callback_data=f"delnav_into_{btn_id}")],
                  [InlineKeyboardButton("🗑 ဤ Folder ကို ဖျက်မည်", callback_data=f"do_del_btn_{btn_id}")],
                  [InlineKeyboardButton("🔙 Back", callback_data=f"delnav_back_to_{btn_id}")]]
            await query.edit_message_text(f"Folder: {name}\n\nဘာလုပ်လိုပါသလဲ?", reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("🗑 ဤ IB ကို ဖျက်မည်", callback_data=f"do_del_btn_{btn_id}")],
                  [InlineKeyboardButton("🔙 Back", callback_data=f"delnav_back_to_{btn_id}")]]
            await query.edit_message_text(f"Inline Button: {name}\n\nဖျက်မှာ သေချာပါသလား?", reply_markup=InlineKeyboardMarkup(kb))
            
    elif cat == "pt":
        if children:
            return await show_del_navigation(query, context, p_id=btn_id)
        else:
            if c_msg:
                await query.message.reply_text(f"📍 '{name}' ၏ လက်ရှိ PT Preview -")
                await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=c_chat, message_id=c_msg)
                kb = [[InlineKeyboardButton("🗑 ဤ PT ကို ဖျက်မည်", callback_data=f"do_del_pt_{btn_id}")],
                      [InlineKeyboardButton("🔙 Back", callback_data=f"delnav_back_to_{btn_id}")]]
                await query.message.reply_text("ဤ PT ကို ဖျက်မှာ သေချာပါသလား?", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await query.edit_message_text(f"⚠️ '{name}' တွင် ဖျက်ရန် PT မရှိပါ။")
                return ConversationHandler.END
    return DEL_CONFIRM

async def execute_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "confirm_del_no":
        await query.edit_message_text("❌ ပယ်ဖျက်လိုက်ပါသည်။")
        return ConversationHandler.END

    if data.startswith("delnav_into_"):
        new_id = int(data.split("_")[2])
        return await show_del_navigation(query, context, p_id=new_id)

    # Prompt အဆင့်မှ ရှေ့အဆင့် (Parent) သို့ ပြန်ဆုတ်ခြင်း
    if data.startswith("delnav_back_to_"):
        curr_id = int(data.split("_")[3])
        res = db_query("SELECT parent_id FROM buttons WHERE id=%s", (curr_id,), fetch=True)
        p_id = res[0][0] if res else None
        return await show_del_navigation(query, context, p_id=p_id)

    # Delete Executions (Recursive / PT Only)
    btn_id = context.user_data.get('target_btn_id')
    if data.startswith("do_del_btn_"):
        delete_sql = """
            WITH RECURSIVE button_tree AS (
                SELECT id FROM buttons WHERE id = %s
                UNION ALL
                SELECT b.id FROM buttons b INNER JOIN button_tree bt ON b.parent_id = bt.id
            )
            DELETE FROM buttons WHERE id IN (SELECT id FROM button_tree)
        """
        db_query(delete_sql, (btn_id,))
        await query.edit_message_text("✅ အမြစ်ပြတ် ဖျက်သိမ်းပြီးပါပြီ။")
        return ConversationHandler.END

    if data.startswith("do_del_pt_"):
        db_query("UPDATE buttons SET content_msg_id = NULL, content_chat_id = NULL WHERE id = %s", (btn_id,))
        await query.edit_message_text("✅ PT ကို ရှင်းလင်းပြီးပါပြီ။")
        return ConversationHandler.END

async def save_edit_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Update logic အားလုံးကို တစ်နေရာတည်းတွင် ကိုင်တွယ်ခြင်း
    new_text = update.message.text
    btn_id = context.user_data.get('target_btn_id')
    state = context.user_data.get('edit_state_type')

    if state == "mmb_name" or state == "ib_name":
        # ဒီနေရာမှာ အကွာအဝေး (Spaces) ကို သေချာညှိပေးထားပါတယ်
        db_query("UPDATE buttons SET name=%s WHERE id=%s", (new_text, btn_id))
        await update.message.reply_text(f"✅ နာမည်ကို '{new_text}' အဖြစ် ပြောင်းလဲပြီးပါပြီ။", reply_markup=get_admin_kb())
    elif state == "dt":
        db_query("UPDATE buttons SET display_text=%s WHERE id=%s", (new_text, btn_id))
        await update.message.reply_text(f"✅ Display Text ကို ပြင်ဆင်ပြီးပါပြီ။", reply_markup=get_admin_kb())
    
    return ConversationHandler.END


async def save_edit_pt_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    chat_id = update.message.chat_id
    btn_id = context.user_data.get('target_btn_id')
    db_query("UPDATE buttons SET content_msg_id=%s, content_chat_id=%s WHERE id=%s", (msg_id, chat_id, btn_id))
    # Edit လုပ်ပြီးလျှင်လည်း Requirement ပြန်ပြင်မလား မေးမည်
    return await ask_req_type(update, context)
    
async def handle_mail_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    choice = "Admin Mail" if query.data == "mail_admin" else "User Mail"
    context.user_data['mail_choice'] = choice
    
    if query.data == "mail_user":
        await query.edit_message_text("📧 ကိုယ်ပိုင် Mail ဖြင့် ဝယ်ယူရန် သင်၏ Email နှင့် Password ကို ပေးပို့ပေးပါရှင် -")
        return WAIT_MAIL_INFO
    else:
        return await show_payment(update, context)

async def save_user_req(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_req'] = update.message.text
    return await show_payment(update, context)

async def save_mail_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_req'] = f"User Mail Info: {update.message.text}"
    return await show_payment(update, context)

async def setup_payment_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("💰 User ဝယ်ယူသည့်အခါ ပြသပေးမည့် Payment Info (စာသား/ပုံ/QR) ကို ပို့ပေးပါ -")
    return SETUP_PAYMENT_INFO

async def save_payment_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    chat_id = update.message.chat_id
    db_query("INSERT INTO settings (key, value, chat_id) VALUES ('payment_info_id', %s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, chat_id=EXCLUDED.chat_id", (str(msg_id), chat_id))
    await update.message.reply_text("✅ Payment Info သိမ်းဆည်းပြီးပါပြီ။", reply_markup=get_admin_kb())
    return ConversationHandler.END


async def handle_user_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    if user_input in ["⚙️ Setup လုပ်မည်", "👀 User အနေနဲ့ ကြည့်မည်", "🔙 Admin View သို့ ပြန်သွားမည်"]: return

    # ၁။ Context-Aware: User ရောက်နေတဲ့ နေရာကို မှတ်သားခြင်း
    last_pt_id = context.user_data.get('last_pt_id')
    
    # ၂။ ခလုတ်နာမည်နဲ့ အတိအကျတူရင် (မူလ Logic)
    btn_res = db_query("SELECT id, display_text, content_msg_id, content_chat_id, parsed_data FROM buttons WHERE name=%s", (user_input,), fetch=True)
    
    if btn_res:
        btn_id, display_text, c_msg, c_chat, p_data = btn_res[0]
        # PT (စာသား/ပုံ) ရှိလျှင် ပြမည်
        if c_msg:
            context.user_data['last_pt_id'] = btn_id
            await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=c_chat, message_id=c_msg)
            # PT ပြပြီးနောက် 'ဝယ်ယူမည်' ခလုတ်ကို ချက်ချင်းပြရန် ဤနေရာတွင် return ပြောင်းလိုက်သည်
            return await show_buy_button(update, context, btn_id)
        
        # အောက်မှာ IB (ခလုတ်များ) ရှိလျှင် ဆက်ပြမည် (မူလ Logic ကို အချောသပ်ထားသည်)
        children = db_query("SELECT id, name FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)
        if children:
            kb = [[InlineKeyboardButton(b[1], callback_data=f"user_sel_{b[0]}")] for b in children]
            text = display_text if display_text else f"**{user_input}** အမျိုးအစားများကို ရွေးချယ်ပေးပါရှင် -"
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
            return

# ၃။ ဂဏန်းရိုက်လာရင် (Smart Calculation & Closest Match)
    clean_val = clean_and_normalize(user_input)
    if clean_val.isdigit() and last_pt_id:
        target = int(clean_val)
        res = db_query("SELECT parsed_data FROM buttons WHERE id=%s", (last_pt_id,), fetch=True)
        
        if res and res[0][0]:
            p_data = res[0][0]
            # Database ထဲမှာ စျေးနှုန်း data ရှိ/မရှိ အရင်စစ်ပါမယ်
            if not p_data or not any(p_data.values()):
                await update.message.reply_text("❌ ဤ App အတွက် စျေးနှုန်းစာရင်း သိမ်းဆည်းထားခြင်း မရှိသေးပါရှင်။ (Setup တွင် PT ကို ပြန်သိမ်းပေးပါ)")
                return

            items = list(p_data.values())[0]
            comb, price = get_combination(target, {int(k):v for k,v in items.items()})
            
            if comb:
                summary = "\n".join([f"✅ {q} Unit" for q in comb])
                await update.message.reply_text(f"🛒 **Order Summary**\n{summary}\n---\n💰 **Total: {price:,} ks**\n\nငွေလွှဲပြေစာ ပို့ပေးပါဗျ။")
                return
            else:
                available_qtys = sorted([int(k) for k in items.keys()])
                # စျေးနှုန်းစာရင်း အမှန်တကယ် ရှိမှသာ min() ကို တွက်ပါမယ်
                if not available_qtys:
                    await update.message.reply_text("❌ စျေးနှုန်းစာရင်း မရှိသေးပါရှင်။")
                    return
                
                lower = max([q for q in available_qtys if q < target], default=min(available_qtys))
                upper = min([q for q in available_qtys if q > target], default=max(available_qtys))
                await update.message.reply_text(
                    f"❌ **{user_input} ဝယ်ယူလို့မရပါဗျ။**\n\nအနီးစပ်ဆုံး ဝယ်ယူနိုင်သည် -\n"
                    f"• {lower} Unit\n• {upper} Unit\n\nကျေးဇူးပြု၍ ပမာဏကို ပြန်ရိုက်ပေးပါရှင်။"
                )
                return

    # ၄။ ဘာနဲ့မှ မကိုက်ညီပါက Fuzzy Match (စာလုံးပေါင်းအမှား) စစ်ဆေးခြင်း
    from difflib import get_close_matches
    all_btns = db_query("SELECT name FROM buttons", fetch=True)
    btn_names = [b[0] for b in all_btns]
    matches = get_close_matches(user_input, btn_names, n=1, cutoff=0.6)
    
    if matches:
        await update.message.reply_text(f"💡 သင်ဆိုလိုတာ '{matches[0]}' လားဟင်? ခလုတ်ကို ပြန်နှိပ်ပေးပါရှင်။")

async def handle_user_inline_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("user_sel_"):
        btn_id = int(query.data.split("_")[2])
        btn_res = db_query("SELECT id, display_text, content_msg_id, content_chat_id, name FROM buttons WHERE id=%s", (btn_id,), fetch=True)
        
        if btn_res:
            b_id, display_text, c_msg, c_chat, name = btn_res[0]
            
            # PT (Content) ရှိလျှင် copy_message ဖြင့် အရင်ပို့မည်
            if c_msg and c_chat:
                await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=c_chat, message_id=c_msg)
                try:
                    await query.delete_message()
                except Exception:
                    pass
                # PT ပြပြီးနောက် 'ဝယ်ယူမည်' ခလုတ်ကို ပြရန် b_id ဖြင့် ခေါ်လိုက်သည်
                return await show_buy_button(update, context, b_id)
            
            # PT မရှိမှသာ အထဲအဆင့်ဆင့် ထပ်ပြမည်
            children = db_query("SELECT id, name FROM buttons WHERE parent_id=%s", (btn_id,), fetch=True)
            kb = [[InlineKeyboardButton(b[1], callback_data=f"user_sel_{b[0]}")] for b in children]
            text = display_text if display_text else name
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
            
async def prepare_dt_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("DT စာသားအသစ် ပို့ပေးပါ -")
    context.user_data['edit_state_type'] = 'dt'
    return EDIT_DT_INPUT

async def prepare_ib_name_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("နာမည်အသစ် ပို့ပေးပါ -")
    context.user_data['edit_state_type'] = 'ib_name'
    return EDIT_IB_NAME_INPUT


async def wm_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin က ခလုတ်နှိပ်လိုက်လျှင် စတင်တောင်းဆိုမည်
    await update.message.reply_text("Welcome Message အဖြစ် ပြမည့် စာသား သို့မဟုတ် ပုံ (Media) ကို ပို့ပေးပါ -")
    return WAIT_WM_CONTENT

async def save_wm_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    chat_id = update.message.chat_id
    
    # settings table ထဲတွင် key='welcome_msg_id' ဖြင့် Overwrite လုပ်ခြင်း
    db_query("""INSERT INTO settings (key, value, chat_id) VALUES ('welcome_msg_id', %s, %s) 
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, chat_id=EXCLUDED.chat_id""", 
             (str(msg_id), chat_id))
    
    # ၁။ အောင်မြင်ကြောင်း အရင်ပြောမည်
    await update.message.reply_text("✅ Welcome Message ကို အသစ်လဲလှယ် သိမ်းဆည်းပြီးပါပြီ။")
    
    # ၂။ Thura မှာထားသည့်အတိုင်း copy_message ဖြင့် Preview ပြမည်
    await update.message.reply_text("📍 လက်ရှိ ပြသမည့် Welcome Message Preview -")
    await context.bot.copy_message(
        chat_id=update.effective_chat.id, 
        from_chat_id=chat_id, 
        message_id=msg_id
    )
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Admin Panel သို့ ပြန်ရောက်ပါပြီ။", reply_markup=get_admin_kb())
    return ConversationHandler.END

# --- Main App (Render Webhook Version) ---
def main():
    init_db() 
    
    # Render အတွက် လိုအပ်သော Environment Variables များယူခြင်း
    TOKEN = "8694614458:AAGVQV8SBA9dWstKkNb7broqOqdLzeTnmuo"
    URL = os.environ.get('RENDER_EXTERNAL_URL') # Render က ပေးမည့် URL
    PORT = int(os.environ.get('PORT', 8080))    # Render က ပေးမည့် Port

    app = Application.builder().token(TOKEN).build()
    
    # ၁။ ConversationHandler (ဦးနှောက်အပိုင်း)
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^⚙️ Setup လုပ်မည်$"), setup_entry),
            MessageHandler(filters.Regex("^📝 Welcome Message ပြင်မည်$"), wm_entry),
            MessageHandler(filters.Regex("^(👀 User အနေနဲ့ ကြည့်မည်|🔙 Admin View သို့ ပြန်သွားမည်)$"), toggle_view),
            MessageHandler(filters.Regex("^💰 Payment Info ပြင်မည်$"), setup_payment_entry),
            CallbackQueryHandler(start_order, pattern="^buy_"),
            MessageHandler(mmb_filter, handle_user_click)
        ],
        states={
            CHOOSING_ACTION: [
                CallbackQueryHandler(handle_action, pattern="^act_"),
                CallbackQueryHandler(setup_payment_entry, pattern="^act_payinfo")
            ],
            CHOOSING_CAT: [CallbackQueryHandler(handle_category)],
            NAV_ADD: [CallbackQueryHandler(handle_add_navigation)],
            CHOOSING_PT_TYPE: [CallbackQueryHandler(handle_pt_type)],
            NAV_PT: [CallbackQueryHandler(handle_pt_navigation)],
            WAIT_PT_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, save_pt_content)],
            ADD_NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_button)],
            ADD_IB_DISPLAY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_ib_display_text)],
            EDIT_TYPE_CHOOSE: [CallbackQueryHandler(handle_edit_type_choose)],
            NAV_EDIT: [
                CallbackQueryHandler(handle_edit_navigation, pattern="^ednav_"),
                CallbackQueryHandler(handle_edit_navigation, pattern="^editmmb_"),
                CallbackQueryHandler(handle_edit_prompt, pattern="^edprompt_"),
                CallbackQueryHandler(prepare_dt_edit, pattern="^do_edit_dt_")
            ],
            EDIT_IB_ACTION: [
                CallbackQueryHandler(prepare_ib_name_edit, pattern="^do_edit_name_"),
                CallbackQueryHandler(handle_edit_navigation, pattern="^ednav_")
            ],
            EDIT_MMB_NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: (c.user_data.update({'edit_state_type': 'mmb_name'}), save_edit_final(u, c))[1])],
            EDIT_IB_NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_final)],
            EDIT_DT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_final)],
            EDIT_PT_TYPE_CHOOSE: [CallbackQueryHandler(handle_edit_pt_type)],
            EDIT_PT_NAV: [CallbackQueryHandler(handle_edit_pt_navigation)],
            WAIT_EDIT_PT_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, save_edit_pt_final)],
            NAV_DEL: [CallbackQueryHandler(handle_del_navigation)],
            DEL_CONFIRM: [CallbackQueryHandler(execute_delete)],
            WAIT_WM_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, save_wm_content)],
            CHOOSE_REQ_TYPE: [CallbackQueryHandler(handle_req_type, pattern="^reqtype_")],
            WAIT_REQ_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_req_text)],
            WAIT_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity)],
            CONFIRM_ORDER: [CallbackQueryHandler(handle_confirmation, pattern="^conf_")],
            WAIT_REQUIREMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_user_req)],
            WAIT_MAIL_INFO: [
                CallbackQueryHandler(handle_mail_choice, pattern="^mail_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_mail_info)
            ],
            WAIT_PAYMENT_SLIP: [MessageHandler(filters.PHOTO, handle_slip)],
            SETUP_PAYMENT_INFO: [MessageHandler(filters.ALL & ~filters.COMMAND, save_payment_setup)],
        },
        allow_reentry=True,
        fallbacks=[CommandHandler("start", start)],
        per_chat=True
    )

    # ၂။ Handlers များ ချိတ်ဆက်ခြင်း
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^(👀 User အနေနဲ့ ကြည့်မည်|🔙 Admin View သို့ ပြန်သွားမည်)$"), toggle_view))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_click))
    app.add_handler(CallbackQueryHandler(handle_user_inline_click, pattern="^user_sel_"))
    
    # ၃။ Webhook စနစ် (Web App Mode) ဖြင့် Run ခြင်း
    if URL:
        print(f"🚀 Render Web App စတင်နေပါပြီ... URL: {URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{URL}/{TOKEN}"
        )
    else:
        # Local (Termux) မှာဆိုရင် Polling နဲ့ပဲ Run မည်
        print("🤖 Local Polling စတင်နေပါပြီ...")
        app.run_polling()

if __name__ == "__main__":
    main()
