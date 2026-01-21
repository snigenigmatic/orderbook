#pragma once
#include "messages.hpp"

class OrderBookBase
{
public:
    virtual ~OrderBookBase() = default;

    virtual void on_add(
        OrderId order_id,
        Side side,
        Price price,
        Volume volume) = 0;

    virtual void on_modify(
        OrderId order_id,
        Volume new_volume) = 0;

    virtual void on_delete(
        OrderId order_id) = 0;

    virtual Price best_bid() const = 0;
    virtual Price best_ask() const = 0;
};