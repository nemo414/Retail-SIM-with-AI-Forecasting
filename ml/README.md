# ML Demand Forecasting

Folder ini berisi notebook eksperimen dan script produksi prediksi permintaan.

## Tanggung jawab

Pipeline Python:

1. Membaca histori penjualan dari `detail_penjualan`.
2. Membuat grid tanggal-produk dan mengisi hari tanpa transaksi dengan `qty = 0`.
3. Membuat fitur kalender, lag, dan rolling mean.
4. Melatih model global XGBoost.
5. Membandingkan XGBoost dengan baseline Holt-Winters pada test set.
6. Memprediksi permintaan 14 hari ke depan.
7. Menulis `hasil_prediksi`, `evaluasi_model`, dan `rekomendasi`.
8. Mengubah status `job_prediksi` menjadi `selesai` atau `gagal`.

## Struktur file

- `01_eksperimen.ipynb`: eksperimen, EDA, feature engineering, evaluasi, dan grafik.
- `predict.py`: script produksi yang dipanggil Express.
- `requirements.txt`: dependensi Python.

## Pembagian data eksperimen

| Bagian     | Periode                     |
| ---------- | --------------------------- |
| Train      | September 2025 - April 2026 |
| Validation | Mei 2026 - Juni 2026        |
| Test       | Juli 2026 - Agustus 2026    |

Data test tidak digunakan untuk tuning. MAPE dihitung hanya pada hari dengan penjualan aktual lebih besar dari nol.

## Model dan fitur

Model produksi menggunakan XGBoost dengan parameter:

```text
n_estimators=300
max_depth=4
learning_rate=0.03
subsample=0.8
colsample_bytree=0.8
```

Fitur yang digunakan:

- `produk_id`
- `day_of_week`, `is_weekend`, `day_of_month`, `is_awal_bulan`, `month`
- `lag_1`, `lag_7`, `lag_14`
- `rolling_mean_7`, `rolling_mean_28`

Jika histori produk kurang dari 60 hari, script menggunakan moving average 7 hari.

## Menjalankan dari root repository

Instal dependensi:

```powershell
python -m pip install -r ml/requirements.txt
```

Jalankan mode produksi menggunakan database:

```powershell
python ml/predict.py --job <id>
```

Mode CSV untuk eksperimen lokal:

```powershell
python ml/predict.py --job 1 --csv --input-csv data/agregasi_harian.csv --output-dir ml/output
```

Mode database membutuhkan environment berikut:

```text
DB_USER
DB_PASS
DB_HOST
DB_PORT
DB_NAME
```

Express menjalankan command produksi tanpa `--csv`:

```text
python ml/predict.py --job <id>
```

## Output database

Python menjadi satu-satunya penulis untuk:

- `hasil_prediksi`
- `evaluasi_model`
- `rekomendasi`

Kolom `terpilih` pada `evaluasi_model` menandai model dengan MAE lebih rendah per produk. Rekomendasi hanya dibuat ketika stok produk kurang dari atau sama dengan reorder point.

## Menjalankan notebook

Buka `01_eksperimen.ipynb` dari root repository dan jalankan ulang seluruh cell. Notebook menghasilkan tabel metrik, grafik aktual versus prediksi, serta contoh safety stock dan reorder point.

## Catatan integrasi

Schema database dikelola oleh Prisma dan tidak diubah oleh folder ini. Jika ada kebutuhan kolom baru, ajukan perubahan kepada pemilik schema sebelum mengubah kode Python.
