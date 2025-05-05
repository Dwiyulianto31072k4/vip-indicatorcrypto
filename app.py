import streamlit as st
import asyncio
import threading
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ForwardMessagesRequest
import logging
import time
import os
from datetime import datetime

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

# Inisialisasi session state
if 'running' not in st.session_state:
    st.session_state.running = False
if 'client' not in st.session_state:
    st.session_state.client = None
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = []
if 'total_forwarded' not in st.session_state:
    st.session_state.total_forwarded = 0
if 'verification_needed' not in st.session_state:
    st.session_state.verification_needed = False
if 'verification_code' not in st.session_state:
    st.session_state.verification_code = ""

# Fungsi untuk menangani verifikasi
def code_callback():
    if st.session_state.code_input:
        st.session_state.verification_code = st.session_state.code_input
        st.session_state.verification_needed = False
        st.session_state.log_messages.append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'message': "Kode verifikasi telah dimasukkan. Menghubungkan kembali...",
            'error': False
        })

# Fungsi untuk menjalankan client Telethon
async def run_client():
    # Ambil kredensial dari secrets
    api_id = st.secrets["API_ID"]
    api_hash = st.secrets["API_HASH"]
    phone = st.secrets["PHONE_NUMBER"]
    source_id = st.secrets["SOURCE_CHANNEL_ID"]
    target_id = st.secrets["TARGET_CHANNEL_ID"]
    
    # Buat client
    client = TelegramClient('telegram_forwarder_session', api_id, api_hash)
    
    # Fungsi untuk menangani kode verifikasi
    async def code_callback():
        while st.session_state.verification_needed:
            if st.session_state.verification_code:
                code = st.session_state.verification_code
                st.session_state.verification_code = ""
                return code
            await asyncio.sleep(1)
        return None
    
    @client.on(events.NewMessage(chats=source_id))
    async def handler(event):
        try:
            # Forward pesan ke channel tujuan
            await client(ForwardMessagesRequest(
                from_peer=source_id,
                id=[event.message.id],
                to_peer=target_id,
                with_my_score=True,
            ))
            
            # Update counter dan log
            st.session_state.total_forwarded += 1
            
            # Log info pesan
            message_preview = event.message.text[:50] + "..." if event.message.text and len(event.message.text) > 50 else "Media atau pesan tanpa teks"
            log_msg = f"Pesan berhasil diforward: {message_preview}"
            logger.info(log_msg)
            
            # Update log di UI
            st.session_state.log_messages.append({
                'time': datetime.now().strftime("%H:%M:%S"),
                'message': log_msg,
                'error': False
            })
            
        except Exception as e:
            error_msg = f"Error saat forward pesan: {str(e)}"
            logger.error(error_msg)
            st.session_state.log_messages.append({
                'time': datetime.now().strftime("%H:%M:%S"),
                'message': error_msg,
                'error': True
            })
    
    # Jalankan client
    try:
        st.session_state.verification_needed = True
        await client.start(phone, code_callback=code_callback)
        st.session_state.verification_needed = False
        logger.info(f"Bot telah aktif! Memantau channel ID: {source_id}")
        st.session_state.log_messages.append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'message': f"Bot berhasil diaktifkan. Memantau channel: {source_id}",
            'error': False
        })
        
        # Simpan client di session state
        st.session_state.client = client
        
        # Jalankan hingga dihentikan
        await client.run_until_disconnected()
    except Exception as e:
        error_msg = f"Error saat menjalankan client: {str(e)}"
        logger.error(error_msg)
        st.session_state.log_messages.append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'message': error_msg,
            'error': True
        })
        st.session_state.running = False

# Fungsi untuk menjalankan client dalam thread terpisah
def start_client_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_client())

# Fungsi untuk menghentikan client
async def stop_client():
    if st.session_state.client:
        await st.session_state.client.disconnect()
        st.session_state.client = None

def stop_client_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(stop_client())

# UI Streamlit
st.title("Telegram Channel Forwarder")
st.markdown("Aplikasi untuk meneruskan pesan dari channel sumber ke channel tujuan Anda.")

# Tampilkan status dan statistik
st.subheader("Status & Statistik")
col1, col2 = st.columns(2)
with col1:
    status = "🟢 **Running**" if st.session_state.running else "🔴 **Stopped**"
    st.markdown(f"**Bot Status:** {status}")
with col2:
    st.markdown(f"**Total Pesan Diteruskan:** {st.session_state.total_forwarded}")

# Tampilkan area untuk memasukkan kode verifikasi jika dibutuhkan
if st.session_state.verification_needed and st.session_state.running:
    st.warning("Telegram meminta kode verifikasi. Silakan cek pesan di Telegram Anda dan masukkan kode di bawah ini.")
    st.text_input("Kode Verifikasi", key="code_input", on_change=code_callback)

# Tombol start/stop
col1, col2 = st.columns(2)
with col1:
    if not st.session_state.running:
        if st.button("Start Forwarding", use_container_width=True):
            # Jalankan client di thread terpisah
            thread = threading.Thread(target=start_client_thread)
            thread.daemon = True
            thread.start()
            
            st.session_state.running = True
            st.session_state.log_messages.append({
                'time': datetime.now().strftime("%H:%M:%S"),
                'message': "Bot starting...",
                'error': False
            })
with col2:
    if st.session_state.running:
        if st.button("Stop Forwarding", use_container_width=True):
            # Hentikan client
            stop_client_thread()
            st.session_state.running = False
            st.session_state.verification_needed = False
            st.session_state.log_messages.append({
                'time': datetime.now().strftime("%H:%M:%S"),
                'message': "Bot stopped!",
                'error': False
            })

# Tampilkan log aktivitas
st.subheader("Log Aktivitas")
log_container = st.container()
with log_container:
    # Tabel log dengan scrolling
    if st.session_state.log_messages:
        for log in reversed(st.session_state.log_messages[-10:]):
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
       - Lihat bagian "Log Aktivitas" untuk memantau proses forwarding
       - Log juga disimpan di file `telegram_forwarder.log`
    
    4. **Troubleshooting**:
       - Jika error, restart aplikasi
       - Pastikan akun Anda memiliki akses ke kedua channel
    """)

# Auto-refresh halaman setiap 10 detik jika bot sedang berjalan
if st.session_state.running:
    time.sleep(10)
    st.rerun()
