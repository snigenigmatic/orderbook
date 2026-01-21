#pragma once
#include "order.hpp"
#include "orderbook_base.hpp"

#include <vector>
#include <unordered_map>

class OrderBookVector : public OrderBookBase
{
public:
    void on_add(OrderId, Side, Price, Volume) override;
    void on_modify(OrderId, Volume) override;
    void on_delete(OrderId) override;

    Price best_bid() const override;
    Price best_ask() const override;

private:
    using Level = std::pair<Price, Volume>;

    std::vector<Level> bids_;
    std::vector<Level> asks_;

    struct OrderRef
    {
        Side side;
        Price price;
        Volume volume;
    };

    std::unordered_map<OrderId, OrderRef> orders_;

    static void add_level(
        std::vector<Level> &levels,
        Price price,
        Volume volume,
        bool is_bid);

    static void remove_level(
        std::vector<Level> &levels,
        Price price,
        Volume volume);
};