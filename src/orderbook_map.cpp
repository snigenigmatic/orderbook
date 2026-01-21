#include "orderbook/orderbook_map.hpp"

void OrderBookMap::on_add(
    OrderId order_id,
    Side side,
    Price price,
    Volume volume)
{
    if (side == Side::Bid)
    {
        auto [it, inserted] = bids_.try_emplace(price, volume);
        if (!inserted)
        {
            it->second += volume;
        }
    }
    else
    {
        auto [it, inserted] = asks_.try_emplace(price, volume);
        if (!inserted)
        {
            it->second += volume;
        }
    }

    orders_.emplace(order_id, OrderRef{side, price, volume});
}

void OrderBookMap::on_modify(
    OrderId order_id,
    Volume new_volume)
{
    auto it = orders_.find(order_id);
    if (it == orders_.end())
        return;

    auto &ref = it->second;

    if (ref.side == Side::Bid)
    {
        auto level_it = bids_.find(ref.price);
        if (level_it != bids_.end())
        {
            level_it->second += (new_volume - ref.volume);
        }
    }
    else
    {
        auto level_it = asks_.find(ref.price);
        if (level_it != asks_.end())
        {
            level_it->second += (new_volume - ref.volume);
        }
    }

    ref.volume = new_volume;
}

void OrderBookMap::on_delete(OrderId order_id)
{
    auto it = orders_.find(order_id);
    if (it == orders_.end())
        return;

    auto &ref = it->second;

    if (ref.side == Side::Bid)
    {
        auto level_it = bids_.find(ref.price);
        if (level_it != bids_.end())
        {
            level_it->second -= ref.volume;
            if (level_it->second <= 0)
            {
                bids_.erase(level_it);
            }
        }
    }
    else
    {
        auto level_it = asks_.find(ref.price);
        if (level_it != asks_.end())
        {
            level_it->second -= ref.volume;
            if (level_it->second <= 0)
            {
                asks_.erase(level_it);
            }
        }
    }

    orders_.erase(it);
}

Price OrderBookMap::best_bid() const
{
    return bids_.empty() ? 0 : bids_.begin()->first;
}

Price OrderBookMap::best_ask() const
{
    return asks_.empty() ? 0 : asks_.begin()->first;
}
