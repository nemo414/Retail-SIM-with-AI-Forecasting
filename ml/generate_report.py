"""Generate EDA, forecast comparison, and inventory planning report artifacts."""

from pathlib import Path
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from statsmodels.tsa.api import ExponentialSmoothing

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "agregasi_harian.csv"
OUTPUT_DIR = ROOT / "docs" / "ml"

FEATURES = [
    "produk_id",
    "day_of_week",
    "is_weekend",
    "day_of_month",
    "is_awal_bulan",
    "month",
    "lag_1",
    "lag_7",
    "lag_14",
    "rolling_mean_7",
    "rolling_mean_28",
]
MODEL_PARAMS = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
}


def load_daily_data() -> pd.DataFrame:
    raw = pd.read_csv(INPUT_PATH)
    raw.columns = raw.columns.str.strip().str.lower()
    raw["tanggal"] = pd.to_datetime(raw["tanggal"])
    if "qty" not in raw.columns:
        raw = raw.rename(columns={"total_qty": "qty"})

    dates = pd.date_range(raw["tanggal"].min(), raw["tanggal"].max(), freq="D")
    products = sorted(raw["produk_id"].unique())
    grid = pd.MultiIndex.from_product(
        [dates, products], names=["tanggal", "produk_id"]
    ).to_frame(index=False)
    daily = grid.merge(raw[["tanggal", "produk_id", "qty"]], how="left")
    daily["qty"] = daily["qty"].fillna(0)
    return daily.sort_values(["produk_id", "tanggal"]).reset_index(drop=True)


def add_features(daily: pd.DataFrame) -> pd.DataFrame:
    featured = daily.copy()
    featured["day_of_week"] = featured["tanggal"].dt.dayofweek
    featured["is_weekend"] = featured["day_of_week"].isin([5, 6]).astype(int)
    featured["day_of_month"] = featured["tanggal"].dt.day
    featured["is_awal_bulan"] = (featured["day_of_month"] <= 5).astype(int)
    featured["month"] = featured["tanggal"].dt.month
    grouped = featured.groupby("produk_id")["qty"]
    featured["lag_1"] = grouped.shift(1)
    featured["lag_7"] = grouped.shift(7)
    featured["lag_14"] = grouped.shift(14)
    featured["rolling_mean_7"] = grouped.transform(
        lambda values: values.shift(1).rolling(7).mean()
    )
    featured["rolling_mean_28"] = grouped.transform(
        lambda values: values.shift(1).rolling(28).mean()
    )
    return featured


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = actual - predicted
    positive = actual > 0
    return {
        "MAPE (%)": float(np.mean(np.abs(error[positive] / actual[positive])) * 100)
        if np.any(positive)
        else 0.0,
        "RMSE": float(np.sqrt(np.mean(error**2))),
        "MAE": float(np.mean(np.abs(error))),
    }


def save_table_png(
    table: pd.DataFrame, output_path: Path, title: str, numeric_columns: list[str]
) -> None:
    displayed = table.copy()
    for column in numeric_columns:
        displayed[column] = displayed[column].map(lambda value: f"{value:.2f}")
    if "terpilih" in displayed.columns:
        displayed["terpilih"] = displayed["terpilih"].map({True: "Ya", False: "Tidak"})

    row_height = 0.32
    figure_height = max(3.5, row_height * (len(displayed) + 2))
    fig, ax = plt.subplots(figsize=(14, figure_height))
    ax.axis("off")
    rendered = ax.table(
        cellText=displayed.values,
        colLabels=displayed.columns,
        cellLoc="center",
        loc="center",
    )
    rendered.auto_set_font_size(False)
    rendered.set_fontsize(8)
    rendered.scale(1, 1.35)
    for (row, column), cell in rendered.get_celld().items():
        cell.set_edgecolor("#d9e2ec")
        if row == 0:
            cell.set_facecolor("#176b87")
            cell.set_text_props(color="white", weight="bold")
        elif row % 2 == 0:
            cell.set_facecolor("#f2f6f8")
    ax.set_title(title, pad=18, weight="bold")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def save_eda_charts(daily: pd.DataFrame) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    daily_total = daily.groupby("tanggal", as_index=False)["qty"].sum()
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(daily_total["tanggal"], daily_total["qty"], color="#176b87", linewidth=1.5)
    ax.set(title="EDA 1 - Total Permintaan Harian", xlabel="Tanggal", ylabel="Qty")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "eda_1_total_harian.png", dpi=160)
    plt.close(fig)

    product_totals = (
        daily.groupby("produk_id", as_index=False)["qty"]
        .sum()
        .sort_values("qty", ascending=False)
        .head(10)
        .sort_values("qty")
    )
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(product_totals["produk_id"].astype(str), product_totals["qty"], color="#e07a5f")
    ax.set(title="EDA 2 - 10 Produk dengan Penjualan Tertinggi", xlabel="Total Qty", ylabel="Produk ID")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "eda_2_produk_terlaris.png", dpi=160)
    plt.close(fig)

    weekday = daily.assign(hari=daily["tanggal"].dt.day_name())
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday_avg = weekday.groupby("hari")["qty"].mean().reindex(weekday_order)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar([day[:3] for day in weekday_avg.index], weekday_avg.values, color="#3a7d44")
    ax.set(title="EDA 3 - Rata-rata Permintaan per Hari", xlabel="Hari", ylabel="Rata-rata Qty")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "eda_3_pola_hari_mingguan.png", dpi=160)
    plt.close(fig)


def evaluate_and_save(featured: pd.DataFrame) -> pd.DataFrame:
    train = featured[featured["tanggal"] <= "2026-06-30"]
    test = featured[
        (featured["tanggal"] >= "2026-07-01")
        & (featured["tanggal"] <= "2026-08-31")
    ].copy()
    model = xgb.XGBRegressor(**MODEL_PARAMS)
    model.fit(train[FEATURES], train["qty"])
    test["xgb_pred"] = np.maximum(0, model.predict(test[FEATURES]))

    rows = []
    for product_id in sorted(test["produk_id"].unique()):
        test_product = test[test["produk_id"] == product_id]
        actual = test_product["qty"].to_numpy()
        xgb_score = metrics(actual, test_product["xgb_pred"].to_numpy())
        history = train[train["produk_id"] == product_id].set_index("tanggal")["qty"]
        try:
            holt_pred = ExponentialSmoothing(
                history, seasonal="add", seasonal_periods=7
            ).fit().forecast(len(test_product)).to_numpy()
        except Exception:
            holt_pred = np.repeat(history.tail(7).mean(), len(test_product))
        holt_score = metrics(actual, np.maximum(0, holt_pred))
        selected = "XGBoost" if xgb_score["MAE"] <= holt_score["MAE"] else "Holt-Winters"
        rows.extend(
            [
                {"produk_id": int(product_id), "model": "XGBoost", **xgb_score, "terpilih": selected == "XGBoost"},
                {"produk_id": int(product_id), "model": "Holt-Winters", **holt_score, "terpilih": selected == "Holt-Winters"},
            ]
        )

    evaluation = pd.DataFrame(rows)
    evaluation.to_csv(OUTPUT_DIR / "tabel_metrik_mape_rmse_mae.csv", index=False)
    save_table_png(
        evaluation,
        OUTPUT_DIR / "tabel_metrik_mape_rmse_mae.png",
        "Tabel MAPE, RMSE, dan MAE",
        ["MAPE (%)", "RMSE", "MAE"],
    )
    return test


def save_actual_vs_predicted(test: pd.DataFrame) -> None:
    products = (
        test.groupby("produk_id")["qty"].sum().sort_values(ascending=False).head(3).index.tolist()
    )
    fig, axes = plt.subplots(len(products), 1, figsize=(12, 3.2 * len(products)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, product_id in zip(axes, products):
        sample = test[test["produk_id"] == product_id]
        ax.plot(sample["tanggal"], sample["qty"], label="Aktual", color="#176b87")
        ax.plot(sample["tanggal"], sample["xgb_pred"], label="Prediksi XGBoost", color="#e07a5f", linestyle="--")
        ax.set_ylabel("Qty")
        ax.set_title(f"Produk {product_id}")
        ax.legend(loc="upper right")
    axes[-1].set_xlabel("Tanggal")
    fig.suptitle("Aktual vs Prediksi XGBoost - 3 Produk Teratas (Test Set)", y=1.01)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "aktual_vs_prediksi_3_produk.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def save_ss_rop_table(daily: pd.DataFrame) -> None:
    train = daily[daily["tanggal"] <= "2026-06-30"]
    stats = train.groupby("produk_id")["qty"].agg(rata_rata_harian="mean", std_harian="std").reset_index()
    lead_time = 3
    stats["lead_time_hari"] = lead_time
    stats["safety_stock"] = np.ceil(1.65 * stats["std_harian"] * np.sqrt(lead_time)).astype(int)
    stats["reorder_point"] = np.ceil(stats["rata_rata_harian"] * lead_time + stats["safety_stock"]).astype(int)
    example = stats.head(5).round({"rata_rata_harian": 2, "std_harian": 2})
    example.to_csv(OUTPUT_DIR / "tabel_contoh_ss_rop.csv", index=False)
    save_table_png(
        example,
        OUTPUT_DIR / "tabel_contoh_ss_rop.png",
        "Contoh Perhitungan Safety Stock dan Reorder Point",
        ["rata_rata_harian", "std_harian"],
    )


def main() -> None:
    daily = load_daily_data()
    save_eda_charts(daily)
    test = evaluate_and_save(add_features(daily).dropna().reset_index(drop=True))
    save_actual_vs_predicted(test)
    save_ss_rop_table(daily)
    print(f"Laporan tersimpan di: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
