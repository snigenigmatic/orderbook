#pragma once
#include "order.hpp"
#include "orderbook_base.hpp"

#include <map>
#include <unordered_map>

class OrderBookMap : public OrderBookBase
{
public:
    std::map<Price, Volume, std::greater<Price>> bids_;
    std::map<Price, Volume, std::less<Price>> asks_;

    void on_add(
        OrderId order_id,
        Side side,
        Price price,
        Volume volume) override;

    void on_modify(
        OrderId order_id,
        Volume new_volume) override;

    void on_delete(
        OrderId order_id) override;

    Price best_bid() const override;
    Price best_ask() const override;

private:
    struct OrderRef
    {
        Side side;
        Price price;
        Volume volume;
    };

    std::unordered_map<OrderId, OrderRef> orders_;
};