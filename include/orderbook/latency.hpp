#pragma once
#include <cstdint>
#include <vector>

class LatencyRecorder {
public:
    explicit LatencyRecorder(size_t capacity);

    void record(uint64_t cycles);
    void report() const;

private:
    std::vector<uint64_t> samples_;
};
