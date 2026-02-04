#pragma once
#include <cstdint>
#include <chrono>

// Return unit label for the timestamp source.
static inline constexpr const char *timing_unit()
{
#if defined(__x86_64__) || defined(_M_X64)
    return "cycles";
#else
    return "ns";
#endif
}

#if defined(__x86_64__) || defined(_M_X64)
#ifdef _MSC_VER
#include <intrin.h>
static inline uint64_t now_ticks()
{
    return __rdtsc();
}
#else
static inline uint64_t now_ticks()
{
    uint32_t lo, hi;
    asm volatile("rdtsc" : "=a"(lo), "=d"(hi));
    return (static_cast<uint64_t>(hi) << 32) | lo;
}
#endif
#else
static inline uint64_t now_ticks()
{
    // Fallback for non-x86 platforms: steady_clock in nanoseconds.
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}
#endif

// Unified timestamp accessor used throughout the codebase.
// On x86/x64 this returns TSC cycles; elsewhere it returns nanoseconds.
static inline uint64_t now_ns()
{
    return now_ticks();
}
