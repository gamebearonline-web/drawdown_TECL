import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


STATE_PATH = Path(".state/drawdown_state.json")

MENTION_ID = os.getenv("MENTION_ID", "BiscuitBlueBear")

# あなた指定のルール（下落率はマイナスの小数）
RULES = {
    "TQQQ": [-0.30, -0.55, -0.75],
    "SOXL": [-0.45, -0.65, -0.85],
    "TECL": [-0.25, -0.50, -0.75],
}

# 直近1年（約252営業日）高値基準
LOOKBACK_TRADING_DAYS = 252

# 取得余裕（252営業日を確実に含むため、カレンダー日数で多め）
HISTORY_PERIOD = "2y"  # 2年取って末尾252営業日で判定


@dataclass
class Snapshot:
    last_date: str
    last_close: float
    peak_date: str
    peak_value: float
    drawdown: float  # negative


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "symbols": {},
    }


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return res.stdout.strip()


def fetch_snapshot(symbol: str) -> Snapshot:
    df = yf.download(
        symbol,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="column",   # ★重要
    )

    if df is None or df.empty:
        raise RuntimeError(f"Failed to fetch data for {symbol}")

    # --- ここが修正ポイント ---
    if "Close" not in df.columns:
        raise RuntimeError(f"'Close' column not found for {symbol}: {df.columns}")

    close = df["Close"].dropna()

    if len(close) < 60:
        raise RuntimeError(f"Not enough data for {symbol}: {len(close)} rows")

    tail = close.iloc[-LOOKBACK_TRADING_DAYS:]

    peak_value = float(tail.max())
    peak_date = tail.idxmax().date().isoformat()

    last_value = float(tail.iloc[-1])
    last_date = tail.index[-1].date().isoformat()

    dd = (last_value / peak_value) - 1.0

    return Snapshot(
        last_date=last_date,
        last_close=last_value,
        peak_date=peak_date,
        peak_value=peak_value,
        drawdown=dd,
    )



def decide_level(drawdown: float, levels: list[float]) -> int | None:
    """
    levels: [-0.30, -0.55, -0.75] のような降順（浅い→深い）
    return: 到達した最深レベル番号(1..3) or None
    """
    hit = None
    for i, th in enumerate(levels, start=1):
        if drawdown <= th:
            hit = i
    return hit


def create_issue(symbol: str, level: int, snap: Snapshot, threshold: float) -> None:
    # Issueタイトルは重複回避しやすいように、ピーク日を含める（ピーク更新で別Issueになる）
    title = f"[DD Alert] {symbol} L{level} since {snap.peak_date} (<= {threshold*100:.0f}%)"
    body = (
        f"@{MENTION_ID}\n\n"
        f"**{symbol}** が直近1年高値から所定の下落率に到達しました。\n\n"
        f"- Level: **L{level}**（閾値 {threshold*100:.0f}%）\n"
        f"- Peak (1Y): **{snap.peak_value:.2f}** on {snap.peak_date}\n"
        f"- Last: **{snap.last_close:.2f}** on {snap.last_date}\n"
        f"- Drawdown: **{snap.drawdown*100:.2f}%**\n\n"
        f"Rule:\n"
        f"- {symbol}: {', '.join([f'{x*100:.0f}%' for x in RULES[symbol]])}\n"
    )

    # gh CLI を使ってIssue作成（GitHub通知が飛ぶ）
    # labelsは任意
    run(["gh", "issue", "create", "--title", title, "--body", body, "--label", "drawdown-alert"])


def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    changed = False

    for symbol, levels in RULES.items():
        snap = fetch_snapshot(symbol)
        hit_level = decide_level(snap.drawdown, levels)

        sym_state = state["symbols"].get(symbol, {})
        last_peak_date = sym_state.get("peak_date")
        last_notified_level = int(sym_state.get("notified_level", 0) or 0)

        # ピーク日が変わった（＝高値更新で基準が変化）なら、通知レベルをリセット
        if last_peak_date != snap.peak_date:
            last_notified_level = 0

        # 到達レベルが上がったら通知（例：L1未通知→L1到達、L1通知済→L2到達）
        if hit_level is not None and hit_level > last_notified_level:
            threshold = levels[hit_level - 1]
            create_issue(symbol, hit_level, snap, threshold)
            sym_state["notified_level"] = hit_level
            changed = True

        # 状態更新
        sym_state.update({
            "updated_at": now,
            "last_date": snap.last_date,
            "last_close": snap.last_close,
            "peak_date": snap.peak_date,
            "peak_value": snap.peak_value,
            "drawdown": snap.drawdown,
        })
        state["symbols"][symbol] = sym_state

    save_state(state)

    # Actionsのログにも出す
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
