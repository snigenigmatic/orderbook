# Low Latency Order Book

A C++ project implementing a low-latency order book. Inspiration from the CPPCon 2024 talk ['When Nanoseconds Matter'](https://youtu.be/sX2nF1fW7kI?si=DKKSbIE9MrRW_i24) by [David Gross](https://david-grs.github.io/about/)

## Structure

- `include/orderbook/`: Public header files.
- `src/`: Source files.
- `tests/`: Unit tests.
- `build/`: Build directory.

## Build

```bash
mkdir build
cd build
cmake ..
cmake --build . --config Release
```
## Results

> **Note on Normalization:**
> *   **x64 (Ryzen 8945HS):** Measured in CPU cycles. Converted using estimated ~5.0 GHz (Divide by 5).
> *   **ARM (Apple M2):** Measured in 24 MHz timer ticks. Converted using 41.67 ns per tick (Multiply by 41.67).

### x64 (Ryzen 8945HS)

| Metric | Map (Cycles) | Map (ns) | Vector (Cycles) | Vector (ns) |
| :--- | :--- | :--- | :--- | :--- |
| **p50** | 560 | **112** | 600 | **120** |
| **p90** | 1800 | **360** | 2000 | **400** |
| **p99** | 3440 | **688** | 3520 | **704** |
| **p99.9**| 5440 | **1088** | 5640 | **1128** |

### ARM (Apple M2)

| Metric | Map (Ticks) | Map (ns) | Vector (Ticks) | Vector (ns) |
| :--- | :--- | :--- | :--- | :--- |
| **p50** | 42 | **1,750** | 42 | **1,750** |
| **p90** | 84 | **3,500** | 125 | **5,209** |
| **p99** | 167 | **6,959** | 375 | **15,626** |
| **p99.9**| 1167 | **48,629** | 625 | **26,044** |