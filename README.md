# Low Latency Order Book

A C++ project implementing a low-latency order book.

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