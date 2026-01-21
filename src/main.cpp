#include "orderbook/orderbook_map.hpp"
#include "orderbook/orderbook_vector.hpp"
#include "orderbook/feed.hpp"
#include "orderbook/dispatcher.hpp"
#include "orderbook/latency.hpp"
#include <iostream>

int main() {
    constexpr size_t kMessages = 1'000'000;

    Feed feed(kMessages);

    {
        std::cout << "\nMap order book\n";
        OrderBookMap book;
        LatencyRecorder rec(kMessages);
        Dispatcher::run(book, feed, rec);
        rec.report();
    }

    {
        std::cout << "\nVector order book\n";
        OrderBookVector book;
        LatencyRecorder rec(kMessages);
        Dispatcher::run(book, feed, rec);
        rec.report();
    }
}
