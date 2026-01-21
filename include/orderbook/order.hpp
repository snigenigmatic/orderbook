#pragma once
#include "messages.hpp"

struct Order {
    OrderId order_id;
    Side side;
    Price price;
    Volume volume;
};