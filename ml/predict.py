import argparse
import os
import sys
import pandas as pd
import numpy as np
import xgboost as xgb
from sqlalchemy import create_engine, text
from datetime import timedelta

# ==========================================
# 1. PARSER ARGUMEN CLI (--job <id>)
# ==========================================
parser = argparse.ArgumentParser(description="Script Prediksi Permintaan SIM Ritel")
parser.add_argument('--job', type=int, required=True, help='ID Job Prediksi dari Backend')
parser.add_argument('--csv', action='store_true', help='Gunakan dataset CSV lokal, tanpa koneksi MySQL')
parser.add_argument('--input-csv', default='dataset_sim_ritel/agregasi_harian.csv', help='Path dataset agregasi harian')
parser.add_argument('--output-dir', default='output', help='Folder output saat menggunakan mode CSV')
args = parser.parse_args()
job_id = args.job

# KONEKSI DATABASE (Sesuaikan dengan .env / setting lokal)
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = os.getenv('DB_PASS', '')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '3306')
DB_NAME = os.getenv('DB_NAME', 'sim_ritel')

DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = None

try:
    # ==========================================
    # 2. AMBIL DATA HISTORI TRANSALSI FROM DB
    # ==========================================
    if args.csv:
        df_raw = pd.read_csv(args.input_csv)
        if 'qty' not in df_raw.columns:
            if 'total_qty' in df_raw.columns:
                df_raw = df_raw.rename(columns={'total_qty': 'qty'})
            else:
                raise ValueError("CSV harus memiliki kolom 'qty' atau 'total_qty'.")
        if not {'tanggal', 'produk_id'}.issubset(df_raw.columns):
            raise ValueError("CSV harus memiliki kolom 'tanggal' dan 'produk_id'.")
    else:
        engine = create_engine(DATABASE_URL)

        # Update status job_prediksi menjadi 'berjalan'
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE job_prediksi SET status = 'berjalan', mulai = NOW() WHERE id = :job_id"),
                {'job_id': job_id}
            )

        query = """
            SELECT DATE(p.tanggal) as tanggal, dp.produk_id, SUM(dp.qty) as qty
            FROM detail_penjualan dp
            JOIN penjualan p ON dp.penjualan_id = p.id
            GROUP BY DATE(p.tanggal), dp.produk_id
            ORDER BY tanggal ASC
        """
        df_raw = pd.read_sql(query, con=engine)

    df_raw['tanggal'] = pd.to_datetime(df_raw['tanggal'])
    
    if df_raw.empty:
        raise ValueError("Data transaksi historis kosong di database.")

    # ==========================================
    # 3. PREPROCESSING & GRID (Sama seperti Notebook)
    # ==========================================
    semua_tanggal = pd.date_range(start=df_raw['tanggal'].min(), end=df_raw['tanggal'].max(), freq='D')
    semua_produk = df_raw['produk_id'].unique()
    grid = pd.MultiIndex.from_product([semua_tanggal, semua_produk], names=['tanggal', 'produk_id']).to_frame().reset_index(drop=True)

    df = pd.merge(grid, df_raw, on=['tanggal', 'produk_id'], how='left')
    df['qty'] = df['qty'].fillna(0)
    df = df.sort_values(['produk_id', 'tanggal']).reset_index(drop=True)

    # Feature Engineering
    df['day_of_week'] = df['tanggal'].dt.dayofweek
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
    df['day_of_month'] = df['tanggal'].dt.day
    df['is_awal_bulan'] = (df['day_of_month'] <= 5).astype(int)
    df['month'] = df['tanggal'].dt.month

    df['lag_1'] = df.groupby('produk_id')['qty'].shift(1)
    df['lag_7'] = df.groupby('produk_id')['qty'].shift(7)
    df['lag_14'] = df.groupby('produk_id')['qty'].shift(14)
    df['rolling_mean_7'] = df.groupby('produk_id')['qty'].transform(lambda x: x.shift(1).rolling(7).mean())
    df['rolling_mean_28'] = df.groupby('produk_id')['qty'].transform(lambda x: x.shift(1).rolling(28).mean())

    df_clean = df.dropna().reset_index(drop=True)

    features = ['produk_id', 'day_of_week', 'is_weekend', 'day_of_month', 
                'is_awal_bulan', 'month', 'lag_1', 'lag_7', 'lag_14', 
                'rolling_mean_7', 'rolling_mean_28']

    # Latih Model Global XGBoost
    model = xgb.XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    model.fit(df_clean[features], df_clean['qty'])

    # ==========================================
    # 4. PREDIKSI 14 HARI KE DEPAN & SIMPAN HASIL
    # ==========================================
    list_hasil_prediksi = []
    list_rekomendasi = []
    
    tanggal_terakhir = df['tanggal'].max()

    for pid in semua_produk:
        df_p = df[df['produk_id'] == pid].copy()
        histori_qty = df_p['qty'].tolist()
        
        # Cek jika histori kurang dari 60 hari -> Fallback Moving Average
        if len(df_p) < 60:
            avg_qty = df_p['qty'].tail(7).mean()
            nama_model = 'Moving Average'
        else:
            nama_model = 'XGBoost'

        # Prediksi 14 Hari
        for i in range(1, 15):
            tgl_pred = tanggal_terakhir + timedelta(days=i)
            
            if nama_model == 'XGBoost':
                # Gunakan hasil prediksi sebelumnya untuk membentuk lag hari berikutnya.
                fitur_prediksi = {
                    'produk_id': pid,
                    'day_of_week': tgl_pred.dayofweek,
                    'is_weekend': int(tgl_pred.dayofweek in [5, 6]),
                    'day_of_month': tgl_pred.day,
                    'is_awal_bulan': int(tgl_pred.day <= 5),
                    'month': tgl_pred.month,
                    'lag_1': histori_qty[-1],
                    'lag_7': histori_qty[-7],
                    'lag_14': histori_qty[-14],
                    'rolling_mean_7': np.mean(histori_qty[-7:]),
                    'rolling_mean_28': np.mean(histori_qty[-28:]),
                }
                
                pred_qty = max(0, float(model.predict(pd.DataFrame([fitur_prediksi])[features])[0]))
            else:
                pred_qty = max(0, float(avg_qty))

            histori_qty.append(pred_qty)

            list_hasil_prediksi.append({
                'job_id': job_id,
                'produk_id': int(pid),
                'tanggal_prediksi': tgl_pred.strftime('%Y-%m-%d'),
                'qty_prediksi': round(pred_qty, 2),
                'model': nama_model
            })

        # Hitung SS & ROP
        std_harian = df_p['qty'].std()
        mean_harian = df_p['qty'].mean()
        lead_time = 3  # hari
        
        ss = int(np.ceil(1.65 * std_harian * np.sqrt(lead_time)))
        rop = int(np.ceil((mean_harian * lead_time) + ss))
        total_pred_14_hari = sum([p['qty_prediksi'] for p in list_hasil_prediksi if p['produk_id'] == pid])
        
        list_rekomendasi.append({
            'job_id': job_id,
            'produk_id': int(pid),
            'safety_stock': ss,
            'reorder_point': rop,
            'qty_saran': int(np.ceil(total_pred_14_hari)),
            'tanggal_pesan': (tanggal_terakhir + timedelta(days=1)).strftime('%Y-%m-%d'),
            'status': 'baru'
        })

    # ==========================================
    # 5. WRITE KE DATABASE & UPDATE STATUS JOB
    # ==========================================
    df_hasil = pd.DataFrame(list_hasil_prediksi)
    df_rekom = pd.DataFrame(list_rekomendasi)

    if args.csv:
        os.makedirs(args.output_dir, exist_ok=True)
        df_hasil.to_csv(os.path.join(args.output_dir, f'hasil_prediksi_job_{job_id}.csv'), index=False)
        df_rekom.to_csv(os.path.join(args.output_dir, f'rekomendasi_job_{job_id}.csv'), index=False)
    else:
        df_hasil.to_sql('hasil_prediksi', con=engine, if_exists='append', index=False)
        df_rekom.to_sql('rekomendasi', con=engine, if_exists='append', index=False)

        # Update job_prediksi -> Selesai
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE job_prediksi SET status = 'selesai', selesai = NOW() WHERE id = :job_id"),
                {'job_id': job_id}
            )
    print(f"Job {job_id} Berhasil Dijalankan.")

except Exception as e:
    # Tangkap error dan update status job_prediksi -> Gagal (Error handling elegan)
    error_msg = str(e)
    if engine is not None:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE job_prediksi SET status = 'gagal', selesai = NOW(), pesan_error = :err WHERE id = :job_id"),
                    {'job_id': job_id, 'err': error_msg}
                )
        except Exception:
            pass
    print(f"Job {job_id} Gagal: {error_msg}")
    sys.exit(1)