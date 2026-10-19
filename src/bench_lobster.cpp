#include "orderbook/backtest.hpp"
#include "orderbook/latency.hpp"

#include <algorithm>
#include <chrono>
#include <iomanip>
#include <iostream>

int main(int argc, char** argv)
{
    if (argc < 2)
    {
        std::cerr << "usage: bench_lobster <message.csv> [orderbook.csv]\n";
        return 1;
    }

    std::string message_path = argv[1];
    std::string orderbook_path = argc > 2 ? argv[2] : "";

    auto t0 = std::chrono::steady_clock::now();
    auto messages = load_lobster_messages(message_path);
    LobsterSnapshots snapshots = orderbook_path.empty() ? LobsterSnapshots{} : load_lobster_snapshots(orderbook_path);
    auto t1 = std::chrono::steady_clock::now();

    BacktestConfig config;
    config.reconcile = !orderbook_path.empty();
    size_t count = messages.size();
    Backtester bt(std::move(messages), std::move(snapshots), config);
    bt.record_latency = true;
    bt.process_ticks.reserve(count);

    auto t2 = std::chrono::steady_clock::now();
    bt.run_to_end();
    auto t3 = std::chrono::steady_clock::now();

    double load_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double replay_ms = std::chrono::duration<double, std::milli>(t3 - t2).count();
    const ReplayStats& s = bt.stats();

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "messages          " << s.messages << "\n";
    std::cout << "load ms           " << load_ms << "\n";
    std::cout << "replay ms         " << replay_ms << "\n";
    std::cout << "msgs per second   " << (s.messages / (replay_ms / 1000.0)) << "\n";
    std::cout << "unknown order ids " << s.unknown_orders << "\n";
    std::cout << "hidden executions " << s.hidden_executions << "\n";
    std::cout << "reconcile events  " << s.reconcile_events << " ("
              << (100.0 * s.reconcile_events / std::max<uint64_t>(1, s.messages)) << "% of messages)\n";
    std::cout << "fixes by level    ";
    for (uint64_t c : s.reconcile_by_level)
        std::cout << c << " ";
    std::cout << "\n";
    std::cout << "bars              " << bt.bars().end_time.size() << "\n\n";

    LatencyRecorder recorder(bt.process_ticks.size());
    for (uint64_t ticks : bt.process_ticks)
        recorder.record(ticks);
    std::cout << "Per-message processing, incl. reconcile\n";
    recorder.report();
    return 0;
}
