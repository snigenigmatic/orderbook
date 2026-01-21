#include "orderbook/orderbook_vector.hpp"
#include <algorithm>

void OrderBookVector::add_level(
    std::vector<Level> &levels,
    Price price,
    Volume volume,
    bool is_bid)
{
    auto it = std::lower_bound(
        levels.begin(),
        levels.end(),
        price,
        [is_bid](const Level &lvl, Price p)
        {
            return is_bid ? (lvl.first > p) : (lvl.first < p);
        });

    if (it != levels.end() && it->first == price)
    {
        it->second += volume;
    }
    else
    {
        levels.insert(it, {price, volume});
    }
}

void OrderBookVector::remove_level(
    std::vector<Level> &levels,
    Price price,
    Volume volume)
{
    auto it = std::find_if(
        levels.begin(),
        levels.end(),
        [price](const Level &lvl)
        {
            return lvl.first == price;
        });

    if (it == levels.end())
        return;
    it->second -= volume;
    if (it->second <= 0)
    {
        levels.erase(it);
    }
}

void OrderBookVector::on_add(
    OrderId order_id,
    Side side,
    Price price,
    Volume volume)
{
    if (side == Side::Bid)
    {
        add_level(bids_, price, volume, true);
    }
    else
    {
        add_level(asks_, price, volume, false);
    }

    orders_.emplace(order_id, OrderRef{side, price, volume});
}

void OrderBookVector::on_modify(
    OrderId order_id,
    Volume new_volume)
{
    auto it = orders_.find(order_id);
    if (it == orders_.end())
        return;

    auto &ref = it->second;
    Volume delta = new_volume - ref.volume;

    if (ref.side == Side::Bid)
    {
        add_level(bids_, ref.price, delta, true);
    }
    else
    {
        add_level(asks_, ref.price, delta, false);
    }

    ref.volume = new_volume;
}

void OrderBookVector::on_delete(OrderId order_id)
{
    auto it = orders_.find(order_id);
    if (it == orders_.end())
        return;

    auto &ref = it->second;

    if (ref.side == Side::Bid)
    {
        remove_level(bids_, ref.price, ref.volume);
    }
    else
    {
        remove_level(asks_, ref.price, ref.volume);
    }

    orders_.erase(it);
}

Price OrderBookVector::best_bid() const
{
    return bids_.empty() ? 0 : bids_.front().first;
}

Price OrderBookVector::best_ask() const
{
    return asks_.empty() ? 0 : asks_.front().first;
}
