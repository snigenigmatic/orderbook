#include "orderbook/latency.hpp"
#include <algorithm>
#include <iostream>

LatencyRecorder::LatencyRecorder(size_t capacity) {
    samples_.reserve(capacity);
}

void LatencyRecorder::record(uint64_t cycles) {
    samples_.push_back(cycles);
}

void LatencyRecorder::report() const {
    if (samples_.empty()) return;

    std::vector<uint64_t> sorted = samples_;
    std::sort(sorted.begin(), sorted.end());

    auto pct = [&](double p) {
        size_t idx = static_cast<size_t>(p * sorted.size());
        if (idx >= sorted.size()) idx = sorted.size() - 1;
        return sorted[idx];
    };

    std::cout << "Latency (cycles)\n";
    std::cout << "  p50: " << pct(0.50) << "\n";
    std::cout << "  p90: " << pct(0.90) << "\n";
    std::cout << "  p99: " << pct(0.99) << "\n";
    std::cout << "  p99.9: " << pct(0.999) << "\n";
}
