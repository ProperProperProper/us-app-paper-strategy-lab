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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_bad_ohlc() {
        let row = Candle { time_ns: 1, open: 10.0, high: 9.0, low: 9.0, close: 10.0, volume: 1.0 };
        assert!(!valid(&row));
    }
}
