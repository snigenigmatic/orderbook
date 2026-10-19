#include "orderbook/fifo_book.hpp"

#include <algorithm>
#include <iterator>

PriceLevel* FifoOrderBook::find_level(Side side, Price price)
{
    if (side == Side::Bid)
    {
        auto it = bids_.find(price);
        return it == bids_.end() ? nullptr : &it->second;
    }
    auto it = asks_.find(price);
    return it == asks_.end() ? nullptr : &it->second;
}

const PriceLevel* FifoOrderBook::find_level(Side side, Price price) const
{
    if (side == Side::Bid)
    {
        auto it = bids_.find(price);
        return it == bids_.end() ? nullptr : &it->second;
    }
    auto it = asks_.find(price);
    return it == asks_.end() ? nullptr : &it->second;
}

PriceLevel& FifoOrderBook::level_for(Side side, Price price)
{
    return side == Side::Bid ? bids_[price] : asks_[price];
}

void FifoOrderBook::erase_level_if_empty(Side side, Price price)
{
    if (side == Side::Bid)
    {
        auto it = bids_.find(price);
        if (it != bids_.end() && it->second.queue.empty())
            bids_.erase(it);
    }
    else
    {
        auto it = asks_.find(price);
        if (it != asks_.end() && it->second.queue.empty())
            asks_.erase(it);
    }
}

void FifoOrderBook::shrink(Locator& loc, Volume volume)
{
    PriceLevel* level = find_level(loc.side, loc.price);
    QueueNode& node = *loc.node;
    Volume taken = std::min(volume, node.volume);
    node.volume -= taken;
    if (!node.own)
        level->visible -= taken;

    if (node.volume <= 0)
    {
        Side side = loc.side;
        Price price = loc.price;
        OrderId id = node.order_id;
        level->queue.erase(loc.node);
        index_.erase(id);
        erase_level_if_empty(side, price);
    }
}

void FifoOrderBook::on_add(OrderId order_id, Side side, Price price, Volume volume)
{
    if (volume <= 0)
        return;
    if (index_.count(order_id))
        on_delete(order_id);

    PriceLevel& level = level_for(side, price);
    level.queue.push_back(QueueNode{order_id, ++seq_, volume, false});
    level.visible += volume;
    index_[order_id] = Locator{side, price, std::prev(level.queue.end())};
}

void FifoOrderBook::on_modify(OrderId order_id, Volume new_volume)
{
    auto it = index_.find(order_id);
    if (it == index_.end())
        return;

    Volume current = it->second.node->volume;
    if (new_volume < current)
    {
        shrink(it->second, current - new_volume);
    }
    else if (new_volume > current)
    {
        Side side = it->second.side;
        Price price = it->second.price;
        bool own = it->second.node->own;
        on_delete(order_id);
        if (own)
            add_own(order_id, side, price, new_volume);
        else
            on_add(order_id, side, price, new_volume);
    }
}

void FifoOrderBook::on_delete(OrderId order_id)
{
    auto it = index_.find(order_id);
    if (it == index_.end())
        return;
    shrink(it->second, it->second.node->volume);
}

void FifoOrderBook::on_execute(OrderId order_id, Volume volume)
{
    execute(order_id, volume);
}

bool FifoOrderBook::cancel_partial(OrderId order_id, Volume volume)
{
    auto it = index_.find(order_id);
    if (it == index_.end())
        return false;
    shrink(it->second, volume);
    return true;
}

ExecResult FifoOrderBook::execute(OrderId order_id, Volume volume)
{
    ExecResult result;
    auto it = index_.find(order_id);
    if (it == index_.end())
        return result;

    result.found = true;
    result.side = it->second.side;
    result.price = it->second.price;
    result.seq = it->second.node->seq;
    result.volume = std::min(volume, it->second.node->volume);
    shrink(it->second, volume);
    return result;
}

bool FifoOrderBook::contains(OrderId order_id) const
{
    return index_.count(order_id) > 0;
}

OrderInfo FifoOrderBook::locate(OrderId order_id) const
{
    OrderInfo info;
    auto it = index_.find(order_id);
    if (it == index_.end())
        return info;
    info.found = true;
    info.side = it->second.side;
    info.price = it->second.price;
    info.seq = it->second.node->seq;
    info.volume = it->second.node->volume;
    return info;
}

void FifoOrderBook::clear_visible()
{
    auto wipe = [this](auto& levels)
    {
        for (auto level = levels.begin(); level != levels.end();)
        {
            auto& queue = level->second.queue;
            for (auto node = queue.begin(); node != queue.end();)
            {
                if (node->own)
                {
                    ++node;
                    continue;
                }
                if (node->order_id != kGhostId)
                    index_.erase(node->order_id);
                node = queue.erase(node);
            }
            level->second.visible = 0;
            level = queue.empty() ? levels.erase(level) : std::next(level);
        }
    };
    wipe(bids_);
    wipe(asks_);
}

uint64_t FifoOrderBook::add_own(OrderId order_id, Side side, Price price, Volume volume)
{
    PriceLevel& level = level_for(side, price);
    uint64_t seq = ++seq_;
    level.queue.push_back(QueueNode{order_id, seq, volume, true});
    index_[order_id] = Locator{side, price, std::prev(level.queue.end())};
    return seq;
}

bool FifoOrderBook::reduce_own(OrderId order_id, Volume volume)
{
    return cancel_partial(order_id, volume);
}

bool FifoOrderBook::remove_own(OrderId order_id)
{
    if (!contains(order_id))
        return false;
    on_delete(order_id);
    return true;
}

Volume FifoOrderBook::queue_ahead(OrderId order_id) const
{
    auto it = index_.find(order_id);
    if (it == index_.end())
        return -1;

    const PriceLevel* level = find_level(it->second.side, it->second.price);
    Volume ahead = 0;
    for (auto node = level->queue.begin(); node != it->second.node; ++node)
    {
        if (!node->own)
            ahead += node->volume;
    }
    return ahead;
}

Volume FifoOrderBook::set_level_visible(Side side, Price price, Volume target)
{
    PriceLevel* existing = find_level(side, price);
    Volume current = existing ? existing->visible : 0;
    Volume diff = target - current;
    if (diff == 0)
        return 0;

    if (diff > 0)
    {
        PriceLevel& level = level_for(side, price);
        if (!level.queue.empty() && level.queue.front().order_id == kGhostId && !level.queue.front().own)
            level.queue.front().volume += diff;
        else
            level.queue.push_front(QueueNode{kGhostId, 0, diff, false});
        level.visible += diff;
        return diff;
    }

    PriceLevel& level = *existing;
    Volume need = -diff;

    if (!level.queue.empty() && level.queue.front().order_id == kGhostId && !level.queue.front().own)
    {
        Volume taken = std::min(need, level.queue.front().volume);
        level.queue.front().volume -= taken;
        level.visible -= taken;
        need -= taken;
        if (level.queue.front().volume <= 0)
            level.queue.pop_front();
    }

    auto node = level.queue.end();
    while (need > 0 && node != level.queue.begin())
    {
        --node;
        if (node->own)
            continue;
        Volume taken = std::min(need, node->volume);
        node->volume -= taken;
        level.visible -= taken;
        need -= taken;
        if (node->volume <= 0)
        {
            if (node->order_id != kGhostId)
                index_.erase(node->order_id);
            node = level.queue.erase(node);
        }
    }

    erase_level_if_empty(side, price);
    return diff;
}

Volume FifoOrderBook::visible_at(Side side, Price price) const
{
    const PriceLevel* level = find_level(side, price);
    return level ? level->visible : 0;
}

std::vector<std::pair<Price, Volume>> FifoOrderBook::depth(Side side, size_t levels) const
{
    std::vector<std::pair<Price, Volume>> out;
    out.reserve(levels);
    auto collect = [&](const auto& book)
    {
        for (const auto& [price, level] : book)
        {
            if (out.size() >= levels)
                break;
            if (level.visible > 0)
                out.emplace_back(price, level.visible);
        }
    };
    if (side == Side::Bid)
        collect(bids_);
    else
        collect(asks_);
    return out;
}

std::vector<Price> FifoOrderBook::visible_prices(Side side, size_t max_levels) const
{
    std::vector<Price> out;
    for (const auto& [price, volume] : depth(side, max_levels))
        out.push_back(price);
    return out;
}

bool FifoOrderBook::has_bid() const
{
    for (const auto& [price, level] : bids_)
        if (level.visible > 0)
            return true;
    return false;
}

bool FifoOrderBook::has_ask() const
{
    for (const auto& [price, level] : asks_)
        if (level.visible > 0)
            return true;
    return false;
}

Price FifoOrderBook::best_bid() const
{
    for (const auto& [price, level] : bids_)
        if (level.visible > 0)
            return price;
    return 0;
}

Price FifoOrderBook::best_ask() const
{
    for (const auto& [price, level] : asks_)
        if (level.visible > 0)
            return price;
    return 0;
}
