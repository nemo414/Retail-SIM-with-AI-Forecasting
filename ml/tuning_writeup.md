# Dokumentasi Peningkatan Model Prediksi Permintaan

## 1. Tujuan

Model awal menggunakan XGBoost untuk memprediksi permintaan setiap produk selama 14 hari. Hasil awal belum konsisten mengungguli baseline Holt-Winters, sehingga evaluasi dan proses tuning perlu diperketat.

File `predict3.py` dibuat sebagai eksperimen lanjutan tanpa mengubah `predict.py` dan `predict2.py`.

## 2. Masalah pada evaluasi sebelumnya

Hasil XGBoost sebelumnya dibandingkan dengan baseline menggunakan periode evaluasi yang berbeda. Karena itu, angka tersebut belum menjadi perbandingan yang sepenuhnya adil.

Pada versi ini, semua model menggunakan pembagian waktu yang sama:

| Bagian     | Periode                     |
| ---------- | --------------------------- |
| Train      | September 2025 - April 2026 |
| Validation | Mei 2026 - Juni 2026        |
| Test       | Juli 2026 - Agustus 2026    |

Validation digunakan untuk memilih parameter dan model. Test hanya digunakan untuk evaluasi final.

## 3. Feature engineering

Selain fitur kalender, model menggunakan:

- lag 1, 2, 3, 7, 14, 21, dan 28 hari;
- rolling mean 3, 7, 14, dan 28 hari;
- rolling standard deviation 7 dan 28 hari;
- rolling minimum dan maksimum 7 hari;
- tren rolling 7 hari dibandingkan rolling 28 hari;
- representasi siklus hari dalam minggu menggunakan sinus dan cosinus.

Semua fitur rolling dan lag hanya memakai data sebelum tanggal target. Hal ini mencegah data leakage.

## 4. Model yang dibandingkan

`predict3.py` membandingkan tiga pendekatan:

1. XGBoost dengan beberapa kandidat hyperparameter.
2. Holt-Winters dengan pola musiman mingguan.
3. Ensemble sederhana berupa rata-rata prediksi XGBoost dan Holt-Winters.

Kandidat XGBoost mencakup variasi jumlah estimator, kedalaman pohon, learning rate, minimum child weight, subsampling, column sampling, dan regularisasi. Salah satu kandidat juga menggunakan objective Pseudo-Huber agar lebih tahan terhadap outlier.

## 5. Pemilihan model

Parameter XGBoost dipilih berdasarkan MAE validation. Setelah parameter terbaik ditemukan, XGBoost dilatih ulang menggunakan data train dan validation, lalu diuji pada test.

Selain evaluasi global, model terbaik dipilih per produk berdasarkan MAE validation. Dengan demikian, produk yang lebih cocok menggunakan Holt-Winters tidak dipaksa menggunakan XGBoost.

## 6. Metrik

- **MAE**: rata-rata kesalahan absolut dalam satuan unit.
- **RMSE**: memberi penalti lebih besar pada kesalahan ekstrem.
- **MAPE**: persentase kesalahan untuk nilai aktual yang lebih besar dari nol.
- **WAPE**: kesalahan absolut dibandingkan total permintaan.

Model final harus dinilai dari test set yang sama. Model tidak dianggap lebih baik hanya karena memperoleh skor validation yang lebih rendah.

## 7. Output eksperimen

Saat dijalankan dengan mode CSV, file berikut dibuat di folder `output`:

- `tuning_v3.csv`: hasil kandidat XGBoost dan model pembanding pada validation.
- `evaluation_v3.csv`: evaluasi final XGBoost, Holt-Winters, dan ensemble pada test.
- `evaluation_per_produk_v3.csv`: evaluasi model per produk.
- `hasil_prediksi_job_<id>_v3.csv`: prediksi 14 hari.
- `rekomendasi_job_<id>_v3.csv`: safety stock, reorder point, dan jumlah pemesanan.

## 8. Cara menjalankan

```powershell
& "$HOME\anaconda3\python.exe" predict3.py --job 4 --csv
```

## 9. Hasil eksekusi pada dataset

Hasil tuning pada validation:

| Model                    |    MAE |   RMSE |     WAPE |
| ------------------------ | -----: | -----: | -------: |
| XGBoost kandidat terbaik | 3.2254 | 4.6978 | 25.5320% |
| Holt-Winters             | 3.2445 | 4.6708 | 25.6829% |
| Ensemble                 | 3.1642 | 4.5789 | 25.0479% |

Hasil evaluasi final pada test set yang sama:

| Model         |    MAE |   RMSE |     MAPE |     WAPE |
| ------------- | -----: | -----: | -------: | -------: |
| XGBoost tuned | 3.3087 | 4.8115 | 36.1932% | 26.0910% |
| Holt-Winters  | 3.3116 | 4.7668 | 35.5114% | 26.1139% |
| Ensemble      | 3.2650 | 4.7245 | 35.4956% | 25.7466% |

Ensemble menjadi model global terbaik karena memperoleh MAE dan WAPE paling rendah pada test set. RMSE-nya belum paling rendah, sehingga masih ada beberapa kesalahan besar yang perlu diperhatikan.

Kandidat objective Pseudo-Huber tidak dipilih karena menghasilkan MAE `70.5780` dan WAPE `558.6888%` pada validation. Ini menunjukkan objective tersebut tidak cocok untuk konfigurasi dan data saat ini.

## 10. Interpretasi hasil

Hasil final perlu dibaca dari `evaluation_v3.csv`, bukan dari hasil tuning saja. Model yang dipilih sebaiknya memiliki MAE dan RMSE rendah serta WAPE yang sesuai dengan kebutuhan inventori.

Output produksi menggunakan model pemenang validation untuk setiap produk. Status ini dicatat pada kolom `model` dan `model_terpilih` agar keputusan model dapat ditelusuri.

## 11. Batasan dan pengembangan berikutnya

Dataset belum memuat promosi, harga, stok aktual, hari libur, dan lead time supplier yang berubah-ubah. Faktor-faktor tersebut dapat meningkatkan kualitas forecast dan simulasi biaya persediaan pada tahap berikutnya.
