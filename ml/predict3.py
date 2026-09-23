import argparse
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import xgboost as xgb
from sqlalchemy import create_engine, text
from statsmodels.tsa.api import ExponentialSmoothing


FEATURES = [
    'produk_id', 'day_of_week', 'is_weekend', 'day_of_month', 'is_awal_bulan',
    'month', 'week_of_year', 'day_sin', 'day_cos', 'lag_1', 'lag_2', 'lag_3',
    'lag_7', 'lag_14', 'lag_21', 'lag_28', 'rolling_mean_3', 'rolling_mean_7',
    'rolling_mean_14', 'rolling_mean_28', 'rolling_std_7', 'rolling_std_28',
    'rolling_min_7', 'rolling_max_7', 'trend_7_28',
]


def metrics(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = actual - predicted
    positive = actual > 0
    return {
        'MAE': np.mean(np.abs(error)),
        'RMSE': np.sqrt(np.mean(error ** 2)),
        'MAPE': np.mean(np.abs(error[positive] / actual[positive])) * 100
        if np.any(positive) else np.nan,
        'WAPE': np.sum(np.abs(error)) / np.sum(actual) * 100
        if np.sum(actual) else np.nan,
    }


def load_csv(path):
    raw = pd.read_csv(path)
    raw.columns = raw.columns.str.strip().str.lower()
    if 'qty' not in raw.columns and 'total_qty' in raw.columns:
        raw = raw.rename(columns={'total_qty': 'qty'})
    required = {'tanggal', 'produk_id', 'qty'}
    if not required.issubset(raw.columns):
        raise ValueError(f'CSV harus memiliki kolom {sorted(required)}.')
    raw['tanggal'] = pd.to_datetime(raw['tanggal'])
    raw = raw.groupby(['tanggal', 'produk_id'], as_index=False)['qty'].sum()
    dates = pd.date_range(raw['tanggal'].min(), raw['tanggal'].max(), freq='D')
    products = np.sort(raw['produk_id'].unique())
    grid = pd.MultiIndex.from_product(
        [dates, products], names=['tanggal', 'produk_id']
    ).to_frame(index=False)
    data = grid.merge(raw, on=['tanggal', 'produk_id'], how='left')
    data['qty'] = data['qty'].fillna(0).astype(float)
    return data.sort_values(['produk_id', 'tanggal']).reset_index(drop=True)


def make_features(data):
    result = data.copy()
    grouped = result.groupby('produk_id')['qty']
    result['day_of_week'] = result['tanggal'].dt.dayofweek
    result['is_weekend'] = result['day_of_week'].isin([5, 6]).astype(int)
    result['day_of_month'] = result['tanggal'].dt.day
    result['is_awal_bulan'] = (result['day_of_month'] <= 5).astype(int)
    result['month'] = result['tanggal'].dt.month
    result['week_of_year'] = result['tanggal'].dt.isocalendar().week.astype(int)
    result['day_sin'] = np.sin(2 * np.pi * result['day_of_week'] / 7)
    result['day_cos'] = np.cos(2 * np.pi * result['day_of_week'] / 7)
    for lag in [1, 2, 3, 7, 14, 21, 28]:
        result[f'lag_{lag}'] = grouped.shift(lag)
    for window in [3, 7, 14, 28]:
        result[f'rolling_mean_{window}'] = grouped.transform(
            lambda values: values.shift(1).rolling(window, min_periods=window).mean()
        )
    for window in [7, 28]:
        result[f'rolling_std_{window}'] = grouped.transform(
            lambda values: values.shift(1).rolling(window, min_periods=window).std()
        )
    result['rolling_min_7'] = grouped.transform(
        lambda values: values.shift(1).rolling(7, min_periods=7).min()
    )
    result['rolling_max_7'] = grouped.transform(
        lambda values: values.shift(1).rolling(7, min_periods=7).max()
    )
    result['trend_7_28'] = result['rolling_mean_7'] - result['rolling_mean_28']
    return result


def make_xgb(params):
    return xgb.XGBRegressor(
        objective=params.pop('objective', 'reg:squarederror'),
        random_state=42,
        n_jobs=4,
        **params,
    )


def fit_holt(history):
    try:
        return ExponentialSmoothing(
            history.astype(float), seasonal='add', seasonal_periods=7
        ).fit(optimized=True)
    except Exception:
        return None


def holt_predictions(data, start, end):
    result = {}
    for product_id in sorted(data['produk_id'].unique()):
        history = data[
            (data['produk_id'] == product_id) & (data['tanggal'] < start)
        ].set_index('tanggal')['qty']
        horizon = int((pd.Timestamp(end) - pd.Timestamp(start)).days + 1)
        model = fit_holt(history)
        if model is None:
            prediction = np.repeat(history.tail(7).mean(), horizon)
        else:
            prediction = model.forecast(horizon).to_numpy()
        result[product_id] = np.maximum(0, prediction)
    return result


def recursive_xgb(model, history, product_id, last_date, horizon):
    values = history.astype(float).tolist()
    predictions = []
    for step in range(1, horizon + 1):
        date = last_date + timedelta(days=step)
        weekday = date.dayofweek
        row = {
            'produk_id': product_id, 'day_of_week': weekday,
            'is_weekend': int(weekday in [5, 6]), 'day_of_month': date.day,
            'is_awal_bulan': int(date.day <= 5), 'month': date.month,
            'week_of_year': int(date.isocalendar().week),
            'day_sin': np.sin(2 * np.pi * weekday / 7),
            'day_cos': np.cos(2 * np.pi * weekday / 7),
            'lag_1': values[-1], 'lag_2': values[-2], 'lag_3': values[-3],
            'lag_7': values[-7], 'lag_14': values[-14], 'lag_21': values[-21],
            'lag_28': values[-28], 'rolling_mean_3': np.mean(values[-3:]),
            'rolling_mean_7': np.mean(values[-7:]),
            'rolling_mean_14': np.mean(values[-14:]),
            'rolling_mean_28': np.mean(values[-28:]),
            'rolling_std_7': np.std(values[-7:], ddof=1),
            'rolling_std_28': np.std(values[-28:], ddof=1),
            'rolling_min_7': np.min(values[-7:]),
            'rolling_max_7': np.max(values[-7:]),
            'trend_7_28': np.mean(values[-7:]) - np.mean(values[-28:]),
        }
        prediction = max(0, float(model.predict(pd.DataFrame([row])[FEATURES])[0]))
        predictions.append(prediction)
        values.append(prediction)
    return np.asarray(predictions)


def evaluate_by_product(actual, predictions):
    rows = []
    for product_id in sorted(actual['produk_id'].unique()):
        actual_product = actual[actual['produk_id'] == product_id]['qty'].to_numpy()
        rows.append({'produk_id': product_id, **metrics(actual_product, predictions[product_id])})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description='Tuning dan evaluasi model demand v3')
    parser.add_argument('--job', type=int, required=True)
    parser.add_argument('--csv', action='store_true')
    parser.add_argument('--input-csv', default='dataset_sim_ritel/agregasi_harian.csv')
    parser.add_argument('--output-dir', default='output')
    args = parser.parse_args()
    engine = None

    try:
        if args.csv:
            data = load_csv(args.input_csv)
        else:
            user = os.getenv('DB_USER', 'root')
            password = os.getenv('DB_PASS', '')
            host = os.getenv('DB_HOST', 'localhost')
            port = os.getenv('DB_PORT', '3306')
            name = os.getenv('DB_NAME', 'sim_ritel')
            engine = create_engine(f'mysql+mysqlconnector://{user}:{password}@{host}:{port}/{name}')
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE job_prediksi SET status='berjalan', mulai=NOW() WHERE id=:job_id"),
                    {'job_id': args.job},
                )
            query = """
                SELECT DATE(p.tanggal) AS tanggal, dp.produk_id, SUM(dp.qty) AS qty
                FROM detail_penjualan dp
                JOIN penjualan p ON dp.penjualan_id = p.id
                GROUP BY DATE(p.tanggal), dp.produk_id
                ORDER BY tanggal ASC
            """
            data = pd.read_sql(query, con=engine)
            data['tanggal'] = pd.to_datetime(data['tanggal'])
            data = load_csv(args.input_csv) if args.csv else data

        features = make_features(data).dropna().reset_index(drop=True)
        train = features[features['tanggal'] < '2026-05-01']
        validation = features[
            (features['tanggal'] >= '2026-05-01') & (features['tanggal'] <= '2026-06-30')
        ]
        test = features[
            (features['tanggal'] >= '2026-07-01') & (features['tanggal'] <= '2026-08-31')
        ]
        candidates = [
            {'n_estimators': 300, 'max_depth': 3, 'learning_rate': 0.03,
             'min_child_weight': 3, 'subsample': 0.8, 'colsample_bytree': 0.8,
             'reg_alpha': 0.05, 'reg_lambda': 1.5},
            {'n_estimators': 500, 'max_depth': 4, 'learning_rate': 0.03,
             'min_child_weight': 3, 'subsample': 0.8, 'colsample_bytree': 0.8,
             'reg_alpha': 0.05, 'reg_lambda': 1.5},
            {'n_estimators': 400, 'max_depth': 5, 'learning_rate': 0.02,
             'min_child_weight': 5, 'subsample': 0.85, 'colsample_bytree': 0.9,
             'reg_alpha': 0.1, 'reg_lambda': 2.0},
            {'objective': 'reg:pseudohubererror', 'n_estimators': 400,
             'max_depth': 3, 'learning_rate': 0.03, 'min_child_weight': 3,
             'subsample': 0.85, 'colsample_bytree': 0.9,
             'reg_alpha': 0.1, 'reg_lambda': 2.0},
        ]
        tuning_rows = []
        best_params = None
        best_mae = float('inf')
        for index, params in enumerate(candidates, start=1):
            model = make_xgb(params.copy())
            model.fit(train[FEATURES], train['qty'], verbose=False)
            prediction = np.maximum(0, model.predict(validation[FEATURES]))
            score = metrics(validation['qty'], prediction)
            tuning_rows.append({'candidate': index, **score, 'params': str(params)})
            if score['MAE'] < best_mae:
                best_mae = score['MAE']
                best_params = params.copy()

        validation_data = data[(data['tanggal'] >= '2026-05-01') & (data['tanggal'] <= '2026-06-30')]
        validation_holt = holt_predictions(data, '2026-05-01', '2026-06-30')
        validation_holt_array = np.concatenate([
            validation_holt[product_id] for product_id in sorted(validation_data['produk_id'].unique())
        ])
        validation_xgb = make_xgb(best_params.copy())
        validation_xgb.fit(train[FEATURES], train['qty'], verbose=False)
        validation_xgb_array = np.maximum(0, validation_xgb.predict(validation[FEATURES]))
        validation_ensemble = (validation_xgb_array + validation_holt_array) / 2
        tuning_rows.extend([
            {'candidate': 'Holt-Winters', **metrics(validation['qty'], validation_holt_array), 'params': 'seasonal=add, period=7'},
            {'candidate': 'Ensemble', **metrics(validation['qty'], validation_ensemble), 'params': 'mean(XGBoost, Holt-Winters)'},
        ])

        train_val = features[features['tanggal'] <= '2026-06-30']
        final_xgb = make_xgb(best_params.copy())
        final_xgb.fit(train_val[FEATURES], train_val['qty'], verbose=False)
        test_prediction_xgb = np.maximum(0, final_xgb.predict(test[FEATURES]))
        test_data = data[(data['tanggal'] >= '2026-07-01') & (data['tanggal'] <= '2026-08-31')]
        test_holt = holt_predictions(data, '2026-07-01', '2026-08-31')
        test_holt_array = np.concatenate([
            test_holt[product_id] for product_id in sorted(test_data['produk_id'].unique())
        ])
        test_ensemble = (test_prediction_xgb + test_holt_array) / 2
        evaluation_rows = [
            {'model': 'XGBoost tuned', **metrics(test['qty'], test_prediction_xgb)},
            {'model': 'Holt-Winters', **metrics(test['qty'], test_holt_array)},
            {'model': 'Ensemble', **metrics(test['qty'], test_ensemble)},
        ]

        validation_by_product = validation.copy()
        validation_by_product['xgb'] = validation_xgb_array
        validation_by_product['holt'] = validation_holt_array
        validation_by_product['ensemble'] = validation_ensemble
        winners = {}
        for product_id, group in validation_by_product.groupby('produk_id'):
            scores = {
                name: metrics(group['qty'], group[name])['MAE']
                for name in ['xgb', 'holt', 'ensemble']
            }
            winners[product_id] = min(scores, key=scores.get)

        test_by_product = test.copy()
        test_by_product['xgb'] = test_prediction_xgb
        test_by_product['holt'] = test_holt_array
        test_by_product['ensemble'] = test_ensemble
        per_product_rows = []
        for product_id, group in test_by_product.groupby('produk_id'):
            winner = winners[product_id]
            row = {'produk_id': product_id, 'model_terpilih_validation': winner}
            for name in ['xgb', 'holt', 'ensemble']:
                row[f'{name}_MAE'] = metrics(group['qty'], group[name])['MAE']
            per_product_rows.append(row)

        full_model = make_xgb(best_params.copy())
        full_model.fit(features[FEATURES], features['qty'], verbose=False)
        last_date = data['tanggal'].max()
        prediction_rows = []
        recommendation_rows = []
        for product_id in sorted(data['produk_id'].unique()):
            history = data[data['produk_id'] == product_id].set_index('tanggal')['qty']
            xgb_forecast = recursive_xgb(full_model, history, product_id, last_date, 14)
            holt_model = fit_holt(history)
            holt_forecast = (
                np.maximum(0, holt_model.forecast(14).to_numpy())
                if holt_model is not None else np.repeat(history.tail(7).mean(), 14)
            )
            model_name = winners[product_id]
            selected = {'xgb': xgb_forecast, 'holt': holt_forecast,
                        'ensemble': (xgb_forecast + holt_forecast) / 2}[model_name]
            for day, quantity in enumerate(selected, start=1):
                prediction_rows.append({
                    'job_id': args.job, 'produk_id': int(product_id),
                    'tanggal_prediksi': (last_date + timedelta(days=day)).strftime('%Y-%m-%d'),
                    'qty_prediksi': round(float(quantity), 2),
                    'model': f'{model_name}-selected-by-validation',
                })
            std_qty = history.std()
            safety_stock = int(np.ceil(1.65 * std_qty * np.sqrt(3)))
            recommendation_rows.append({
                'job_id': args.job, 'produk_id': int(product_id),
                'safety_stock': safety_stock,
                'reorder_point': int(np.ceil(history.mean() * 3 + safety_stock)),
                'qty_saran': int(np.ceil(selected.sum())),
                'tanggal_pesan': (last_date + timedelta(days=1)).strftime('%Y-%m-%d'),
                'status': 'baru', 'model_terpilih': model_name,
            })

        os.makedirs(args.output_dir, exist_ok=True)
        pd.DataFrame(tuning_rows).to_csv(os.path.join(args.output_dir, 'tuning_v3.csv'), index=False)
        pd.DataFrame(evaluation_rows).to_csv(os.path.join(args.output_dir, 'evaluation_v3.csv'), index=False)
        pd.DataFrame(per_product_rows).to_csv(os.path.join(args.output_dir, 'evaluation_per_produk_v3.csv'), index=False)
        result = pd.DataFrame(prediction_rows)
        recommendation = pd.DataFrame(recommendation_rows)
        if args.csv:
            result.to_csv(os.path.join(args.output_dir, f'hasil_prediksi_job_{args.job}_v3.csv'), index=False)
            recommendation.to_csv(os.path.join(args.output_dir, f'rekomendasi_job_{args.job}_v3.csv'), index=False)
        else:
            result.to_sql('hasil_prediksi', con=engine, if_exists='append', index=False)
            recommendation.to_sql('rekomendasi', con=engine, if_exists='append', index=False)
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE job_prediksi SET status='selesai', selesai=NOW() WHERE id=:job_id"),
                    {'job_id': args.job},
                )
        print('Hasil tuning validation:')
        print(pd.DataFrame(tuning_rows)[['candidate', 'MAE', 'RMSE', 'WAPE']].round(4).to_string(index=False))
        print('\nEvaluasi final test:')
        print(pd.DataFrame(evaluation_rows).round(4).to_string(index=False))
        print(f'Job {args.job} berhasil. {len(result)} prediksi dibuat.')
    except Exception as error:
        if engine is not None:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("UPDATE job_prediksi SET status='gagal', selesai=NOW(), pesan_error=:error WHERE id=:job_id"),
                        {'job_id': args.job, 'error': str(error)},
                    )
            except Exception:
                pass
        print(f'Job {args.job} gagal: {error}')
        sys.exit(1)


if __name__ == '__main__':
    main()