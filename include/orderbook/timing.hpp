#pragma once
#include <cstdint>
#include <chrono>

inline uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()
    ).count();
}

// #if defined(__x86_64__) || defined(_M_X64)
// #ifdef _MSC_VER
// #include <intrin.h>
// static inline uint64_t rdtsc()
// {
//     return __rdtsc();
// }
// #else
// static inline uint64_t rdtsc()
// {
//     uint32_t lo, hi;
//     asm volatile("rdtsc" : "=a"(lo), "=d"(hi));
//     return (static_cast<uint64_t>(hi) << 32) | lo;
// }
// #endif
// #else
// #error "rdtsc only supported on x86_64"
// #endif
