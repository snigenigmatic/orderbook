#pragma once
#include "fifo_book.hpp"
#include "lobster.hpp"

#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <vector>

struct BacktestConfig
{
    double order_latency = 0.001;
    double bar_seconds = 10.0;
    double session_start = 34200.0;
    double session_end = 57600.0;
    int64_t maker_rebate = 20;
    bool reconcile = true;
};

enum class OwnStatus : uint8_t
{
    Pending,
    Active,
    Filled,
    Cancelled,
    Rejected
};

struct OwnOrder
{
    OrderId id;
    Side side;
    Price price;
    Volume quantity;
    Volume remaining;
    uint64_t seq;
    double submitted_at;
    double active_at;
    Volume queue_at_entry;
    OwnStatus status;
    bool cancel_requested;
};

struct Fill
{
    double time;
    OrderId order_id;
    Side side;
    Price price;
    Volume volume;
    Volume queue_at_entry;
    double resting_seconds;
    Price mid_at_fill;
};

struct Bars
{
    std::vector<double> end_time;
    std::vector<double> mid;
    std::vector<double> spread;
    std::vector<double> realized_var;
    std::vector<double> ofi;
    std::vector<double> volume;
    std::vector<double> trades;
    std::vector<double> imbalance;
};

struct ReplayStats
{
    uint64_t messages = 0;
    uint64_t unknown_orders = 0;
    uint64_t hidden_executions = 0;
    uint64_t halts = 0;
    uint64_t reconcile_events = 0;
    uint64_t reconcile_levels = 0;
    int64_t reconcile_volume = 0;
    std::vector<uint64_t> reconcile_by_level;
};

class Backtester
{
public:
    Backtester(const std::string& message_path, const std::string& orderbook_path, BacktestConfig config);
    Backtester(std::vector<LobsterMessage> messages, LobsterSnapshots snapshots, BacktestConfig config);

    bool run_until(double t);
    void run_to_end();

    OrderId submit(Side side, Price price, Volume quantity);
    bool cancel(OrderId order_id);

    std::vector<Fill> take_fills();
    std::vector<OwnOrder> open_orders() const;
    const OwnOrder* order(OrderId order_id) const;
    Volume queue_ahead(OrderId order_id) const;

    const FifoOrderBook& book() const { return book_; }
    const Bars& bars() const { return bars_; }
    const ReplayStats& stats() const { return stats_; }
    const BacktestConfig& config() const { return config_; }

    double now() const { return now_; }
    size_t cursor() const { return cursor_; }
    size_t message_count() const { return messages_.size(); }
    bool done() const { return cursor_ >= messages_.size(); }

    Volume position() const { return position_; }
    int64_t cash() const { return cash_; }
    int64_t rebates() const { return rebates_; }
    Volume traded_volume() const { return traded_volume_; }

    double mid() const;

    std::vector<uint64_t> process_ticks;
    bool record_latency = false;

private:
    struct Action
    {
        double effective;
        OrderId order_id;
        bool is_cancel;
    };

    std::vector<LobsterMessage> messages_;
    LobsterSnapshots snapshots_;
    BacktestConfig config_;
    FifoOrderBook book_;

    size_t cursor_ = 0;
    double now_ = 0.0;
    OrderId next_own_id_ = (OrderId{1} << 62);

    std::deque<Action> actions_;
    std::map<OrderId, OwnOrder> own_;
    std::set<OrderId> open_ids_;
    std::vector<Fill> fills_;

    Volume position_ = 0;
    int64_t cash_ = 0;
    int64_t rebates_ = 0;
    Volume traded_volume_ = 0;

    ReplayStats stats_;
    Bars bars_;

    double bar_end_ = 0.0;
    double bar_mid_last_ = std::numeric_limits<double>::quiet_NaN();
    double bar_spread_area_ = 0.0;
    double bar_spread_time_ = 0.0;
    double bar_last_time_ = 0.0;
    double bar_last_spread_ = std::numeric_limits<double>::quiet_NaN();
    double bar_rv_ = 0.0;
    double bar_ofi_ = 0.0;
    double bar_volume_ = 0.0;
    double bar_trades_ = 0.0;
    Price prev_bid_px_ = 0;
    Price prev_ask_px_ = 0;
    Volume prev_bid_sz_ = 0;
    Volume prev_ask_sz_ = 0;

    void process(const LobsterMessage& m, size_t row);
    void apply_actions_until(double t);
    void apply_action(const Action& a);
    void reconcile(size_t row);
    void remove_unknown(Side side, Price price, Volume volume);
    void handle_trade(Side resting_side, Price price, Volume volume, uint64_t seq, double t);
    void check_crossing_add(Side side, Price price, Volume volume, double t);
    void fill_own(OwnOrder& o, Volume volume, Price price, double t);
    void update_bars(double t, bool is_trade, Volume trade_volume);
    void close_bars_until(double t);
};
