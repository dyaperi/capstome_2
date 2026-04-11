import numpy as np
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


def analyze_sentiment(text: str, rating: int | None = None) -> tuple[str, float]:
    analyzer = SentimentIntensityAnalyzer()
    score = analyzer.polarity_scores(text or "")["compound"]
    if rating is not None:
        score = (score + ((float(rating) - 3.0) / 2.0)) / 2.0
    if score >= 0.25:
        return "positive", score
    if score <= -0.25:
        return "negative", score
    return "neutral", score


def forecast_values(series: pd.Series, periods: int = 14) -> list[float]:
    clean = series.dropna()
    if len(clean) < 7:
        return []
    y = clean.values
    x = np.arange(len(y))
    coef = np.polyfit(x, y, 1)
    trend = np.polyval(coef, x)
    seasonal_window = min(7, len(y))
    seasonal = y[-seasonal_window:] - trend[-seasonal_window:]
    future = np.arange(len(y), len(y) + periods)
    values = np.polyval(coef, future) + np.resize(seasonal, periods)
    return np.maximum(values, 0).tolist()


def campaign_roi(spend: float, revenue_generated: float) -> float:
    if spend <= 0:
        return 0.0
    return ((revenue_generated - spend) / spend) * 100
