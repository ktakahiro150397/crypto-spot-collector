import pandas as pd


def append_dates_with_nearest(df: pd.DataFrame, column_name: str, dates: list[str]) -> pd.DataFrame:
    """ DataFrameに最も近い日付を追加するヘルパー関数 """

    # マージ用のdfを作成
    dates_df = pd.to_datetime(dates)
    targets_df = pd.DataFrame({
        "key": dates_df,
        "value": dates_df
    }).sort_values(by="key")

    df_timestamps = df[["timestamp"]].reset_index().sort_values(by="timestamp")
    merged_df = pd.merge_asof(
        targets_df,
        df_timestamps,
        left_on="key",
        right_on="timestamp",
        direction="nearest"
    )

    print("-------merged_df--------")
    print(merged_df)

    # 元のdfに新しい列を追加
    df[column_name] = pd.NaT
    df.loc[merged_df["index"], column_name] = merged_df["value"].values

    print("-------df--------")
    print(df)

    return df
