#pragma once
#include <cstdint>

using OrderId = uint64_t;
using Price   = int64_t;
using Volume  = int64_t;

enum class Side : uint8_t {
    Bid,
    Ask
};

enum class MessageType : uint8_t {
    Add,
    Modify,
    Delete
};

struct AddOrderMsg {
    OrderId order_id;
    Side side;
    Price price;
    Volume volume;
};

struct ModifyOrderMsg {
    OrderId order_id;
    Volume new_volume;
};

struct DeleteOrderMsg {
    OrderId order_id;
};

struct Message {
    MessageType type;
    union {
        AddOrderMsg add;
        ModifyOrderMsg modify;
        DeleteOrderMsg del;
    };
};
