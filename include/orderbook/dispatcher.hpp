#pragma once
#include "orderbook_base.hpp"
#include "feed.hpp"
#include "latency.hpp"

class Dispatcher {
public:
    static void run(
        OrderBookBase& book,
        const Feed& feed,
        LatencyRecorder& recorder
    );
};
