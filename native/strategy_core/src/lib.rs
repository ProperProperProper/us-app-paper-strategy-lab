#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Candle {
    pub time_ns: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct Features {
    pub ema_fast: f64,
    pub ema_slow: f64,
    pub prior_high: f64,
    pub atr14: f64,
    pub regime_ema: f64,
    pub slow_drift: f64,
    pub regime_drift: f64,
    pub log_slope: f64,
    pub recent_peak: f64,
}

const MINUTE_NS: i64 = 60 * 1_000_000_000;
const DAY_NS: i64 = 24 * 60 * MINUTE_NS;

fn valid(c: &Candle) -> bool {
    c.time_ns.is_positive()
        && c.open.is_finite()
        && c.high.is_finite()
        && c.low.is_finite()
        && c.close.is_finite()
        && c.volume.is_finite()
        && c.open > 0.0
        && c.high > 0.0
        && c.low > 0.0
        && c.close > 0.0
        && c.volume >= 0.0
        && c.high >= c.open.max(c.close)
        && c.low <= c.open.min(c.close)
        && c.high >= c.low
}

#[no_mangle]
pub unsafe extern "C" fn strategy_validate(candles: *const Candle, len: usize) -> i32 {
    if candles.is_null() || len == 0 {
        return 0;
    }
    let rows = std::slice::from_raw_parts(candles, len);
    let mut previous = None;
    for row in rows {
        if !valid(row) || previous.is_some_and(|stamp| row.time_ns <= stamp) {
            return 0;
        }
        previous = Some(row.time_ns);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn strategy_aggregate(
    input: *const Candle,
    len: usize,
    interval_minutes: i32,
    output: *mut Candle,
    capacity: usize,
) -> isize {
    if input.is_null() || output.is_null() || len == 0 || capacity == 0 {
        return -1;
    }
    if !(interval_minutes == 10
        || interval_minutes == 20
        || interval_minutes == 30
        || interval_minutes == 40
        || interval_minutes == 50
        || interval_minutes == 60
        || interval_minutes == 70)
    {
        return -1;
    }
    let rows = std::slice::from_raw_parts(input, len);
    if strategy_validate(input, len) == 0 {
        return -2;
    }
    if interval_minutes == 10 {
        let count = len.min(capacity);
        std::ptr::copy_nonoverlapping(rows.as_ptr(), output, count);
        return count as isize;
    }
    let interval = interval_minutes as i64;
    let expected = (interval / 10) as usize;
    let mut written = 0usize;
    let mut i = 0usize;
    while i < rows.len() {
        let day = rows[i].time_ns.div_euclid(DAY_NS);
        let minute_of_day = rows[i].time_ns.rem_euclid(DAY_NS) / MINUTE_NS;
        let minutes_from_open = minute_of_day - 570;
        let bucket = ((minutes_from_open + interval - 1).div_euclid(interval) - 1).max(0);
        let mut end = i + 1;
        while end < rows.len() {
            let next_day = rows[end].time_ns.div_euclid(DAY_NS);
            let next_minute = rows[end].time_ns.rem_euclid(DAY_NS) / MINUTE_NS;
            let next_bucket = ((next_minute - 570 + interval - 1).div_euclid(interval) - 1).max(0);
            if next_day != day || next_bucket != bucket {
                break;
            }
            end += 1;
        }
        if end - i == expected {
            if written >= capacity {
                return -3;
            }
            let first = rows[i];
            let last = rows[end - 1];
            let mut high = first.high;
            let mut low = first.low;
            let mut volume = 0.0;
            for row in &rows[i..end] {
                high = high.max(row.high);
                low = low.min(row.low);
                volume += row.volume;
            }
            (*output.add(written)) = Candle {
                time_ns: day * DAY_NS + (570 + (bucket + 1) * interval) * MINUTE_NS,
                open: first.open,
                high,
                low,
                close: last.close,
                volume,
            };
            written += 1;
        }
        i = end;
    }
    written as isize
}

fn ema(values: &[f64], span: usize, out: &mut [f64]) {
    let alpha = 2.0 / (span as f64 + 1.0);
    if values.is_empty() { return; }
    out[0] = values[0];
    for i in 1..values.len() {
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1];
    }
}

fn rolling_max(values: &[f64], end_exclusive: usize, window: usize) -> f64 {
    if end_exclusive < window { return f64::NAN; }
    values[end_exclusive - window..end_exclusive]
        .iter().copied().fold(f64::NEG_INFINITY, f64::max)
}

fn regression_slope(values: &[f64], end_exclusive: usize, window: usize) -> f64 {
    if end_exclusive < window { return f64::NAN; }
    let n = window as f64;
    let mean_x = (n - 1.0) / 2.0;
    let mean_y = values[end_exclusive - window..end_exclusive].iter().sum::<f64>() / n;
    let denominator = (0..window).map(|i| {
        let dx = i as f64 - mean_x;
        dx * dx
    }).sum::<f64>();
    if denominator == 0.0 { return f64::NAN; }
    let numerator = values[end_exclusive - window..end_exclusive].iter().enumerate().map(|(i, value)| {
        (i as f64 - mean_x) * (*value - mean_y)
    }).sum::<f64>();
    numerator / denominator
}

#[no_mangle]
pub unsafe extern "C" fn strategy_features(
    input: *const Candle,
    len: usize,
    fast: usize,
    slow: usize,
    lookback: usize,
    regime_span: usize,
    slope_window: usize,
    slope_lag: usize,
    output: *mut Features,
    capacity: usize,
) -> isize {
    if input.is_null() || output.is_null() || len == 0 || capacity < len || fast == 0 || slow == 0 || lookback == 0 || regime_span == 0 || slope_window == 0 || slope_lag == 0 {
        return -1;
    }
    let rows = std::slice::from_raw_parts(input, len);
    if strategy_validate(input, len) == 0 { return -2; }
    let closes: Vec<f64> = rows.iter().map(|r| r.close).collect();
    let highs: Vec<f64> = rows.iter().map(|r| r.high).collect();
    let mut fast_ema = vec![f64::NAN; len];
    let mut slow_ema = vec![f64::NAN; len];
    let mut regime_ema = vec![f64::NAN; len];
    ema(&closes, fast, &mut fast_ema);
    ema(&closes, slow, &mut slow_ema);
    ema(&closes, regime_span, &mut regime_ema);
    let mut true_ranges = vec![0.0; len];
    let logs: Vec<f64> = closes.iter().map(|value| value.max(1e-12).ln()).collect();
    for i in 0..len {
        let previous = if i == 0 { closes[0] } else { closes[i - 1] };
        true_ranges[i] = (rows[i].high - rows[i].low)
            .max((rows[i].high - previous).abs())
            .max((rows[i].low - previous).abs());
    }
    for i in 0..len {
        let start = i.saturating_sub(13);
        let count = i - start + 1;
        let atr = true_ranges[start..=i].iter().sum::<f64>() / count as f64;
        let slow_drift = if i >= slope_lag { slow_ema[i] / slow_ema[i - slope_lag] - 1.0 } else { f64::NAN };
        let regime_drift = if i >= slope_lag { regime_ema[i] / regime_ema[i - slope_lag] - 1.0 } else { f64::NAN };
        let log_slope = regression_slope(&logs, i + 1, slope_window);
        // Match pandas: shift(1).rolling(window).max() at row i uses the
        // preceding `window` values and excludes the current candle.
        let prior_high = rolling_max(&highs, i, lookback);
        let recent_peak = rolling_max(&closes, i, slope_window * 2);
        (*output.add(i)) = Features { ema_fast: fast_ema[i], ema_slow: slow_ema[i], prior_high, atr14: atr, regime_ema: regime_ema[i], slow_drift, regime_drift, log_slope, recent_peak };
    }
    len as isize
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_bad_ohlc() {
        let row = Candle { time_ns: 1, open: 10.0, high: 9.0, low: 9.0, close: 10.0, volume: 1.0 };
        assert!(!valid(&row));
    }
}
