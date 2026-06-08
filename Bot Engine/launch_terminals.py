import os
import sys
import subprocess
import logging
import tempfile

# Tambah folder 'Bot Engine' ke dalam system path supaya boleh import modul
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trade_management.supabase_sync import SupabaseSync
import system_settings
import config

logging.basicConfig(level=logging.INFO, format="%(message)s")

def create_mt5_config(acc_id, login, password, server):
    """Bina fail .ini sementara untuk auto sign-in MT5"""
    temp_dir = tempfile.gettempdir()
    config_path = os.path.join(temp_dir, f"{acc_id}_mt5_startup.ini")
    
    # Format konfigurasi MT5 (baris demi baris penting)
    ini_content = f"""[Common]
Login={login}
Password={password}
Server={server}
"""
    with open(config_path, "w") as f:
        f.write(ini_content)
        
    return config_path

def main():
    print("Menyemak laluan (path) MT5 di Supabase (Master & Individu)...")
    
    # 1. Segarkan tetapan dari .env & system_settings di Supabase
    system_settings.fetch_and_apply_system_settings()
    
    supabase = SupabaseSync()
    if not supabase.enabled:
        print("Supabase tidak diaktifkan. Tidak dapat mengambil tetapan MT5.")
        return
        
    # Gunakan dictionary untuk simpan data unik setiap path terminal
    terminals_to_launch = {}
    
    # 2. Ambil Master MT5 Path
    master_path = getattr(config, "MASTER_MT5_PATH", config.MT5_PATH)
    if master_path and os.path.exists(master_path):
        terminals_to_launch[master_path] = {"id": "master", "path": master_path}
    elif master_path:
        print(f"Amaran: Master MT5 Path ({master_path}) tidak wujud di PC ini.")
        
    # 3. Ambil MT5 Path untuk Akaun Individu beserta Login Detail
    try:
        enabled_accounts = supabase.fetch_all_enabled_accounts()
        for acc_id in enabled_accounts:
            acc_data = supabase.fetch_account_settings(acc_id)
            if acc_data and acc_data.get("mt5_path"):
                acc_path = acc_data.get("mt5_path")
                
                if not acc_path.strip():
                    continue
                    
                if os.path.exists(acc_path):
                    # Simpan data login jika ia individu
                    terminals_to_launch[acc_path] = {
                        "id": acc_id,
                        "path": acc_path,
                        "login": acc_data.get("mt5_login", ""),
                        "password": acc_data.get("mt5_password", ""),
                        "server": acc_data.get("mt5_server", "")
                    }
                else:
                    print(f"Amaran: MT5 Path untuk {acc_id} ({acc_path}) tidak wujud.")
    except Exception as e:
        print(f"Ralat mendapatkan tetapan individu: {e}")
        
    if not terminals_to_launch:
        print("Tiada laluan MT5 baharu yang ditemui untuk dilancarkan.")
        return
        
    print(f"Bersedia melancarkan {len(terminals_to_launch)} terminal MT5...\n")
    for path, data in terminals_to_launch.items():
        cmd = [path]
        
        # Jika ada maklumat login, bina fail .ini dan jalankan menggunakan /config
        if data.get("login") and data.get("password") and data.get("server"):
            print(f" -> Melancarkan: {path} (Auto-Login untuk akaun: {data['login']})")
            config_file = create_mt5_config(
                data["id"], 
                data["login"], 
                data["password"], 
                data["server"]
            )
            cmd.append(f"/config:{config_file}")
        else:
            print(f" -> Melancarkan: {path} (Tanpa Auto-Login)")
            
        try:
            # Gunakan subprocess.Popen supaya skrip ini terus berjalan di background
            subprocess.Popen(cmd)
        except Exception as e:
            print(f"Gagal melancarkan {path}: {e}")

if __name__ == "__main__":
    main()
