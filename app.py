import streamlit as st
import asyncio
import threading
import time
import os
from datetime import datetime
import logging
from telethon import TelegramClient, events

# Konfigurasi halaman Streamlit
st.set_page_config(
    page_title="Telegram Channel Forwarder",
    page_icon="📱",
    layout="wide"
)

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_forwarder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Kredeensial dan konfigurasi tetap
API_ID = 28690093
API_HASH = "aa512841e37c5ccb5a8ac494395bb373"
PHONE_NUMBER = "+6285161054271"
SOURCE_CHANNEL_ID = -1002626068320
TARGET_CHANNEL_ID = -1002694678122

# File untuk menyimpan kode verifikasi
VERIFICATION_CODE_FILE = "verification_code.txt"
LOG_FILE = "bot_logs.txt"

# Inisialisasi session state
if 'running' not in st.session_state:
    st.session_state['running'] = False
if 'total_forwarded' not in st.session_state:
    st.session_state['total_forwarded'] = 0
if 'log_messages' not in st.session_state:
    st.session_state['log_messages'] = []

# Fungsi untuk menyimpan log ke file
def write_log(message, is_error=False):
    try:
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().strftime("%H:%M:%S")
            f.write(f"{timestamp} - {'ERROR' if is_error else 'INFO'} - {message}\n")
    except Exception as e:
        logger.error(f"Gagal menulis log ke file: {str(e)}")

# Fungsi untuk membaca log dari file
def read_logs():
    logs = []
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                for line in f.readlines():
                    parts = line.strip().split(" - ", 2)
                    if len(parts) == 3:
                        timestamp, level, message = parts
                        logs.append({
                            'time': timestamp,
                            'message': message,
                            'error': level == 'ERROR'
                        })
    except Exception as e:
        logger.error(f"Gagal membaca log dari file: {str(e)}")
    return logs

# Fungsi untuk mendapatkan kode verifikasi
def code_callback():
    logger.info("Menunggu kode verifikasi...")
    # Hapus file kode verifikasi jika ada
    if os.path.exists(VERIFICATION_CODE_FILE):
        os.remove(VERIFICATION_CODE_FILE)
    
    # Tulis pesan ke log
    write_log("Bot membutuhkan kode verifikasi. Silakan masukkan kode verifikasi di Telegram.")
    
    # Tunggu hingga kode verifikasi dimasukkan
    while not os.path.exists(VERIFICATION_CODE_FILE):
        time.sleep(1)
    
    # Baca kode verifikasi
    with open(VERIFICATION_CODE_FILE, "r") as f:
        code = f.read().strip()
    
    # Hapus file setelah dibaca
    os.remove(VERIFICATION_CODE_FILE)
    
    write_log(f"Kode verifikasi diterima: {code}")
    return code

# Fungsi untuk menjalankan client Telethon
async def run_client():
    try:
        # Buat client
        client = TelegramClient('telegram_forwarder_session', API_ID, API_HASH)
        
        # Event handler untuk pesan baru
        @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def handler(event):
            try:
                message = event.message
                
                # Kirim ulang pesan dengan format "Sent By Lian Analyst"
                if message.text:
                    custom_text = f"Sent By Lian Analyst\n\n{message.text}"
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                elif message.media:
                    await client.send_file(
                        TARGET_CHANNEL_ID, 
                        message.media,
                        caption="Sent By Lian Analyst" + (f"\n\n{message.text}" if message.text else "")
                    )
                
                # Log info pesan
                message_preview = message.text[:50] + "..." if message.text and len(message.text) > 50 else "Media atau pesan tanpa teks"
                log_msg = f"Pesan berhasil dikirim ulang: {message_preview}"
                logger.info(log_msg)
                write_log(log_msg)
                
            except Exception as e:
                error_msg = f"Error saat mengirim pesan: {str(e)}"
                logger.error(error_msg)
                write_log(error_msg, True)
        
        # Jalankan client
        write_log("Memulai client Telegram...")
        await client.start(PHONE_NUMBER, code_callback=code_callback)
        
        log_msg = f"Bot berhasil diaktifkan. Memantau channel: {SOURCE_CHANNEL_ID}"
        logger.info(log_msg)
        write_log(log_msg)
        
        # Jalankan hingga dihentikan
        await client.run_until_disconnected()
        
    except Exception as e:
        error_msg = f"Error saat menjalankan client: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)

# Fungsi untuk menjalankan client dalam thread terpisah
def start_client_thread():
    try:
        write_log("Memulai client dalam thread terpisah...")
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_client())
    except Exception as e:
        error_msg = f"Error dalam thread: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)

# Fungsi untuk menyimpan kode verifikasi
def save_verification_code():
    if st.session_state.code_input:
        try:
            with open(VERIFICATION_CODE_FILE, "w") as f:
                f.write(st.session_state.code_input)
            st.success("Kode verifikasi dikirim!")
        except Exception as e:
            st.error(f"Gagal menyimpan kode verifikasi: {str(e)}")

# UI Streamlit
st.title("Telegram Channel Forwarder")
st.markdown("Aplikasi untuk meneruskan pesan dari channel sumber ke channel tujuan Anda.")

# Kolom untuk kode verifikasi
if st.session_state['running']:
    st.text_input("Masukkan Kode Verifikasi dari Telegram (jika diminta):", 
                  key="code_input", 
                  on_change=save_verification_code)

# Tampilkan status dan statistik
st.subheader("Status & Statistik")
col1, col2 = st.columns(2)
with col1:
    status = "🟢 **Running**" if st.session_state['running'] else "🔴 **Stopped**"
    st.markdown(f"**Bot Status:** {status}")
with col2:
    # Update total forwarded dari log
    forwarded_count = 0
    for log in read_logs():
        if "Pesan berhasil dikirim ulang" in log['message']:
            forwarded_count += 1
    st.session_state['total_forwarded'] = forwarded_count
    st.markdown(f"**Total Pesan Dikirim:** {st.session_state['total_forwarded']}")

# Tombol start/stop
col1, col2 = st.columns(2)
with col1:
    if not st.session_state['running']:
        if st.button("Start Forwarding", use_container_width=True):
            # Buat file log jika belum ada
            if not os.path.exists(LOG_FILE):
                with open(LOG_FILE, "w") as f:
                    f.write("")
            
            # Jalankan client di thread terpisah
            thread = threading.Thread(target=start_client_thread, daemon=True)
            thread.start()
            
            st.session_state['running'] = True
            write_log("Bot starting...")
            st.rerun()
with col2:
    if st.session_state['running']:
        if st.button("Stop Forwarding", use_container_width=True):
            # Hentikan client - tidak ada cara langsung untuk menghentikan thread
            # Hanya tandai sebagai tidak berjalan
            st.session_state['running'] = False
            write_log("Bot stopped!")
            st.rerun()

# Tampilkan log aktivitas
st.subheader("Log Aktivitas")
log_container = st.container()
with log_container:
    # Baca log dari file
    logs = read_logs()
    # Tampilkan 10 log terakhir
    if logs:
        for log in reversed(logs[-10:]):
            timestamp = log.get('time', '')
            message = log.get('message', '')
            is_error = log.get('error', False)
            
            if is_error:
                st.error(f"{timestamp} - {message}")
            else:
                st.info(f"{timestamp} - {message}")

# Tambahkan cara penggunaan
with st.expander("Cara Penggunaan"):
    st.markdown("""
    ### Cara Menggunakan Aplikasi Ini:
    
    1. **Menjalankan Bot**:
       - Klik "Start Forwarding" untuk memulai
       - Pertama kali, Anda mungkin diminta memasukkan kode verifikasi
       - Klik "Stop Forwarding" untuk menghentikan bot
    
    2. **Kode Verifikasi**:
       - Saat pertama kali dijalankan, Telegram akan mengirimkan kode verifikasi ke nomor telepon Anda
       - Masukkan kode tersebut pada kolom "Kode Verifikasi" yang muncul
    
    3. **Melihat Log**:
       - Lihat bagian "Log Aktivitas" untuk memantau proses pengiriman pesan
       - Log juga disimpan di file `telegram_forwarder.log`
    
    4. **Format Pesan**:
       - Semua pesan akan dikirim dengan format "Sent By Lian Analyst" di awal pesan
    
    5. **Troubleshooting**:
       - Jika error, restart aplikasi
       - Pastikan akun Anda memiliki akses ke kedua channel
    """)

# Auto-refresh halaman setiap 5 detik
time.sleep(5)
st.rerun()
