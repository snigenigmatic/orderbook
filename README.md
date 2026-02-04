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
- x64
```bash
Map order book
Latency (cycles)
  p50: 560
  p90: 1800
  p99: 3440
  p99.9: 5440

Vector order book
Latency (cycles)
  p50: 600
  p90: 2000
  p99: 3520
  p99.9: 5640
  ```

- ARM
```bash
Map order book
Latency (cycles)
  p50: 42
  p90: 84
  p99: 167
  p99.9: 1167

Vector order book
Latency (cycles)
  p50: 42
  p90: 125
  p99: 375
  p99.9: 625
  ```