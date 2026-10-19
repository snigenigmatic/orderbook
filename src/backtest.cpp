#include "orderbook/backtest.hpp"
#include "orderbook/timing.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <unordered_set>

namespace
{
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
}

Backtester::Backtester(const std::string& message_path, const std::string& orderbook_path, BacktestConfig config)
    : Backtester(load_lobster_messages(message_path),
                 orderbook_path.empty() ? LobsterSnapshots{} : load_lobster_snapshots(orderbook_path),
                 config)
{
}

Backtester::Backtester(std::vector<LobsterMessage> messages, LobsterSnapshots snapshots, BacktestConfig config)
    : messages_(std::move(messages)), snapshots_(std::move(snapshots)), config_(config)
{
    bar_end_ = config_.session_start + config_.bar_seconds;
    bar_last_time_ = config_.session_start;
    now_ = messages_.empty() ? config_.session_start : messages_.front().time;
}

bool Backtester::run_until(double t)
{
    while (cursor_ < messages_.size() && messages_[cursor_].time <= t)
    {
        const LobsterMessage& m = messages_[cursor_];
        apply_actions_until(m.time);
        process(m, cursor_);
        ++cursor_;
    }
    apply_actions_until(t);
    if (std::isfinite(t) && t > now_)
        now_ = t;
    close_bars_until(std::min(t, config_.session_end));
    return !done();
}

void Backtester::run_to_end()
{
    run_until(std::numeric_limits<double>::infinity());
    close_bars_until(config_.session_end);
}

OrderId Backtester::submit(Side side, Price price, Volume quantity)
{
    OrderId id = next_own_id_++;
    OwnOrder o{};
    o.id = id;
    o.side = side;
    o.price = price;
    o.quantity = quantity;
    o.remaining = quantity;
    o.submitted_at = now_;
    o.queue_at_entry = -1;
    o.status = OwnStatus::Pending;
    own_.emplace(id, o);
    open_ids_.insert(id);
    actions_.push_back(Action{now_ + config_.order_latency, id, false});
    return id;
}

bool Backtester::cancel(OrderId order_id)
{
    auto it = own_.find(order_id);
    if (it == own_.end())
        return false;
    OwnOrder& o = it->second;
    if (o.cancel_requested || (o.status != OwnStatus::Pending && o.status != OwnStatus::Active))
        return false;
    o.cancel_requested = true;
    actions_.push_back(Action{now_ + config_.order_latency, order_id, true});
    return true;
}

std::vector<Fill> Backtester::take_fills()
{
    std::vector<Fill> out;
    out.swap(fills_);
    return out;
}

std::vector<OwnOrder> Backtester::open_orders() const
{
    std::vector<OwnOrder> out;
    out.reserve(open_ids_.size());
    for (OrderId id : open_ids_)
        out.push_back(own_.at(id));
    return out;
}

const OwnOrder* Backtester::order(OrderId order_id) const
{
    auto it = own_.find(order_id);
    return it == own_.end() ? nullptr : &it->second;
}

Volume Backtester::queue_ahead(OrderId order_id) const
{
    return book_.queue_ahead(order_id);
}

double Backtester::mid() const
{
    if (!book_.has_bid() || !book_.has_ask())
        return kNaN;
    return 0.5 * static_cast<double>(book_.best_bid() + book_.best_ask());
}

void Backtester::apply_actions_until(double t)
{
    while (!actions_.empty() && actions_.front().effective <= t)
    {
        Action a = actions_.front();
        actions_.pop_front();
        apply_action(a);
    }
}

void Backtester::apply_action(const Action& a)
{
    OwnOrder& o = own_.at(a.order_id);

    if (a.is_cancel)
    {
        if (o.status == OwnStatus::Active)
        {
            book_.remove_own(o.id);
            o.status = OwnStatus::Cancelled;
            open_ids_.erase(o.id);
        }
        else if (o.status == OwnStatus::Pending)
        {
            o.status = OwnStatus::Cancelled;
            open_ids_.erase(o.id);
        }
        return;
    }

    if (o.status != OwnStatus::Pending)
        return;

    bool crosses = o.side == Side::Bid
                       ? (book_.has_ask() && o.price >= book_.best_ask())
                       : (book_.has_bid() && o.price <= book_.best_bid());
    if (crosses)
    {
        o.status = OwnStatus::Rejected;
        open_ids_.erase(o.id);
        return;
    }

    o.seq = book_.add_own(o.id, o.side, o.price, o.remaining);
    o.status = OwnStatus::Active;
    o.active_at = a.effective;
    o.queue_at_entry = book_.queue_ahead(o.id);
}

void Backtester::process(const LobsterMessage& m, size_t row)
{
    uint64_t start = record_latency ? now_ticks() : 0;

    now_ = m.time;
    close_bars_until(std::min(m.time, config_.session_end));

    Side side = lobster_side(m.direction);
    bool is_trade = false;
    Volume trade_volume = 0;
    ++stats_.messages;

    switch (m.type)
    {
    case LobsterEvent::Submit:
        if (!open_ids_.empty())
            check_crossing_add(side, m.price, m.size, m.time);
        book_.on_add(m.order_id, side, m.price, m.size);
        break;

    case LobsterEvent::PartialCancel:
        if (!book_.cancel_partial(m.order_id, m.size))
            remove_unknown(side, m.price, m.size);
        break;

    case LobsterEvent::Delete:
        if (!book_.contains(m.order_id))
            remove_unknown(side, m.price, m.size);
        else
            book_.on_delete(m.order_id);
        break;

    case LobsterEvent::ExecuteVisible:
    {
        ExecResult r = book_.execute(m.order_id, m.size);
        if (!r.found)
            remove_unknown(side, m.price, m.size);
        handle_trade(side, m.price, m.size, r.found ? r.seq : 0, m.time);
        is_trade = true;
        trade_volume = m.size;
        break;
    }

    case LobsterEvent::ExecuteHidden:
        ++stats_.hidden_executions;
        handle_trade(side, m.price, m.size, std::numeric_limits<uint64_t>::max(), m.time);
        is_trade = true;
        trade_volume = m.size;
        break;

    case LobsterEvent::FillNotice:
    {
        OrderInfo info = book_.locate(m.order_id);
        Side resting = info.found ? info.side : side;
        handle_trade(resting, m.price, m.size, info.found ? info.seq : 0, m.time);
        is_trade = true;
        trade_volume = m.size;
        break;
    }

    case LobsterEvent::Clear:
        book_.clear_visible();
        break;

    case LobsterEvent::Modify:
    {
        OrderInfo info = book_.locate(m.order_id);
        if (info.found && info.price == m.price && m.size <= info.volume)
        {
            book_.on_modify(m.order_id, m.size);
        }
        else
        {
            if (info.found)
                book_.on_delete(m.order_id);
            if (!open_ids_.empty())
                check_crossing_add(side, m.price, m.size, m.time);
            book_.on_add(m.order_id, side, m.price, m.size);
        }
        break;
    }

    case LobsterEvent::Cross:
        break;

    case LobsterEvent::Halt:
        ++stats_.halts;
        break;
    }

    if (config_.reconcile && row < snapshots_.rows)
        reconcile(row);

    update_bars(m.time, is_trade, trade_volume);

    if (record_latency)
        process_ticks.push_back(now_ticks() - start);
}

void Backtester::remove_unknown(Side side, Price price, Volume volume)
{
    ++stats_.unknown_orders;
    Volume current = book_.visible_at(side, price);
    if (current > 0)
        book_.set_level_visible(side, price, std::max<Volume>(0, current - volume));
}

void Backtester::reconcile(size_t row)
{
    bool touched = false;
    const size_t levels = snapshots_.levels;
    if (stats_.reconcile_by_level.size() != levels)
        stats_.reconcile_by_level.assign(levels, 0);

    for (Side side : {Side::Ask, Side::Bid})
    {
        std::unordered_set<Price> truth;
        size_t valid = 0;
        Price worst = 0;

        for (size_t k = 0; k < levels; ++k)
        {
            Price px = side == Side::Ask ? snapshots_.ask_price(row, k) : snapshots_.bid_price(row, k);
            Volume sz = side == Side::Ask ? snapshots_.ask_size(row, k) : snapshots_.bid_size(row, k);
            if (px == LobsterSnapshots::kEmptyAsk || px == LobsterSnapshots::kEmptyBid || sz <= 0)
                break;
            truth.insert(px);
            worst = px;
            ++valid;
            Volume diff = book_.set_level_visible(side, px, sz);
            if (diff != 0)
            {
                ++stats_.reconcile_by_level[k];
                touched = true;
                ++stats_.reconcile_levels;
                stats_.reconcile_volume += std::llabs(diff);
            }
        }

        bool bounded = valid == levels;
        for (const auto& [px, vol] : book_.depth(side, levels * 2 + 4))
        {
            if (bounded)
            {
                bool inside = side == Side::Ask ? px <= worst : px >= worst;
                if (!inside)
                    break;
            }
            if (truth.count(px))
                continue;
            Volume diff = book_.set_level_visible(side, px, 0);
            if (diff != 0)
            {
                ++stats_.reconcile_by_level[levels - 1];
                touched = true;
                ++stats_.reconcile_levels;
                stats_.reconcile_volume += std::llabs(diff);
            }
        }
    }

    if (touched)
        ++stats_.reconcile_events;
}

void Backtester::check_crossing_add(Side side, Price price, Volume volume, double t)
{
    Side resting = side == Side::Ask ? Side::Bid : Side::Ask;
    std::vector<OwnOrder*> hit;
    for (OrderId id : open_ids_)
    {
        OwnOrder& o = own_.at(id);
        if (o.status != OwnStatus::Active || o.side != resting)
            continue;
        bool crossed = resting == Side::Bid ? o.price >= price : o.price <= price;
        if (crossed)
            hit.push_back(&o);
    }
    if (hit.empty())
        return;

    std::sort(hit.begin(), hit.end(), [resting](const OwnOrder* a, const OwnOrder* b)
    {
        if (a->price != b->price)
            return resting == Side::Bid ? a->price > b->price : a->price < b->price;
        return a->seq < b->seq;
    });

    Volume left = volume;
    for (OwnOrder* o : hit)
    {
        if (left <= 0)
            break;
        Volume q = std::min(left, o->remaining);
        fill_own(*o, q, o->price, t);
        left -= q;
    }
}

void Backtester::handle_trade(Side resting_side, Price price, Volume volume, uint64_t seq, double t)
{
    if (open_ids_.empty())
        return;

    std::vector<OwnOrder*> eligible;
    for (OrderId id : open_ids_)
    {
        OwnOrder& o = own_.at(id);
        if (o.status != OwnStatus::Active || o.side != resting_side)
            continue;
        bool better = resting_side == Side::Bid ? o.price > price : o.price < price;
        bool same_and_ahead = o.price == price && o.seq < seq;
        if (better || same_and_ahead)
            eligible.push_back(&o);
    }
    if (eligible.empty())
        return;

    std::sort(eligible.begin(), eligible.end(), [resting_side](const OwnOrder* a, const OwnOrder* b)
    {
        if (a->price != b->price)
            return resting_side == Side::Bid ? a->price > b->price : a->price < b->price;
        return a->seq < b->seq;
    });

    Volume left = volume;
    for (OwnOrder* o : eligible)
    {
        if (left <= 0)
            break;
        Volume q = std::min(left, o->remaining);
        fill_own(*o, q, o->price, t);
        left -= q;
    }
}

void Backtester::fill_own(OwnOrder& o, Volume volume, Price price, double t)
{
    if (volume <= 0)
        return;

    Price mid_now = 0;
    if (book_.has_bid() && book_.has_ask())
        mid_now = (book_.best_bid() + book_.best_ask()) / 2;

    o.remaining -= volume;
    book_.reduce_own(o.id, volume);

    if (o.side == Side::Bid)
    {
        position_ += volume;
        cash_ -= price * volume;
    }
    else
    {
        position_ -= volume;
        cash_ += price * volume;
    }
    rebates_ += config_.maker_rebate * volume;
    traded_volume_ += volume;

    fills_.push_back(Fill{t, o.id, o.side, price, volume, o.queue_at_entry, t - o.active_at, mid_now});

    if (o.remaining <= 0)
    {
        o.status = OwnStatus::Filled;
        open_ids_.erase(o.id);
    }
}

void Backtester::update_bars(double t, bool is_trade, Volume trade_volume)
{
    bool in_session = t >= config_.session_start && t <= config_.session_end;
    bool two_sided = book_.has_bid() && book_.has_ask();
    if (!in_session)
    {
        if (two_sided)
        {
            Price bb = book_.best_bid();
            Price ba = book_.best_ask();
            bar_last_spread_ = static_cast<double>(ba - bb);
            bar_last_time_ = std::max(bar_last_time_, config_.session_start);
            bar_mid_last_ = 0.5 * static_cast<double>(ba + bb);
            prev_bid_px_ = bb;
            prev_ask_px_ = ba;
            prev_bid_sz_ = book_.visible_at(Side::Bid, bb);
            prev_ask_sz_ = book_.visible_at(Side::Ask, ba);
        }
        return;
    }
    if (two_sided)
    {
        Price bb = book_.best_bid();
        Price ba = book_.best_ask();
        Volume bs = book_.visible_at(Side::Bid, bb);
        Volume as = book_.visible_at(Side::Ask, ba);
        double spread = static_cast<double>(ba - bb);
        double mid = 0.5 * static_cast<double>(ba + bb);

        if (!std::isnan(bar_last_spread_))
        {
            double dt = std::max(0.0, t - bar_last_time_);
            bar_spread_area_ += bar_last_spread_ * dt;
            bar_spread_time_ += dt;
        }
        bar_last_spread_ = spread;
        bar_last_time_ = t;

        if (!std::isnan(bar_mid_last_) && mid > 0 && bar_mid_last_ > 0)
        {
            double r = std::log(mid / bar_mid_last_);
            bar_rv_ += r * r;
        }
        bar_mid_last_ = mid;

        if (prev_bid_px_ != 0 && prev_ask_px_ != 0)
        {
            double e = 0.0;
            if (bb >= prev_bid_px_)
                e += static_cast<double>(bs);
            if (bb <= prev_bid_px_)
                e -= static_cast<double>(prev_bid_sz_);
            if (ba <= prev_ask_px_)
                e -= static_cast<double>(as);
            if (ba >= prev_ask_px_)
                e += static_cast<double>(prev_ask_sz_);
            bar_ofi_ += e;
        }
        prev_bid_px_ = bb;
        prev_ask_px_ = ba;
        prev_bid_sz_ = bs;
        prev_ask_sz_ = as;
    }

    if (is_trade)
    {
        bar_volume_ += static_cast<double>(trade_volume);
        bar_trades_ += 1.0;
    }
}

void Backtester::close_bars_until(double t)
{
    while (t >= bar_end_ && bar_end_ <= config_.session_end + 1e-9)
    {
        if (!std::isnan(bar_last_spread_))
        {
            double dt = std::max(0.0, bar_end_ - bar_last_time_);
            bar_spread_area_ += bar_last_spread_ * dt;
            bar_spread_time_ += dt;
        }

        double spread = bar_spread_time_ > 0 ? bar_spread_area_ / bar_spread_time_ : bar_last_spread_;
        double imbalance = kNaN;
        if (prev_bid_sz_ + prev_ask_sz_ > 0)
            imbalance = static_cast<double>(prev_bid_sz_ - prev_ask_sz_) / static_cast<double>(prev_bid_sz_ + prev_ask_sz_);

        bars_.end_time.push_back(bar_end_);
        bars_.mid.push_back(bar_mid_last_);
        bars_.spread.push_back(spread);
        bars_.realized_var.push_back(bar_rv_);
        bars_.ofi.push_back(bar_ofi_);
        bars_.volume.push_back(bar_volume_);
        bars_.trades.push_back(bar_trades_);
        bars_.imbalance.push_back(imbalance);

        bar_spread_area_ = 0.0;
        bar_spread_time_ = 0.0;
        bar_rv_ = 0.0;
        bar_ofi_ = 0.0;
        bar_volume_ = 0.0;
        bar_trades_ = 0.0;
        bar_last_time_ = std::max(bar_last_time_, bar_end_);
        bar_end_ += config_.bar_seconds;
    }
}
