#include "orderbook/feed.hpp"
#include <random>

Feed::Feed(size_t count) {
    messages_.reserve(count);

    std::mt19937_64 rng(42);
    OrderId next_id = 1;

    for (size_t i = 0; i < count; ++i) {
        Message msg{};
        uint64_t r = rng() % 3;

        if (r == 0 || next_id < 10) {
            msg.type = MessageType::Add;
            msg.add.order_id = next_id++;
            msg.add.side = (rng() & 1) ? Side::Bid : Side::Ask;
            msg.add.price = 100 + (rng() % 50);
            msg.add.volume = 1 + (rng() % 10);
        } else if (r == 1) {
            msg.type = MessageType::Modify;
            msg.modify.order_id = 1 + (rng() % (next_id - 1));
            msg.modify.new_volume = 1 + (rng() % 20);
        } else {
            msg.type = MessageType::Delete;
            msg.del.order_id = 1 + (rng() % (next_id - 1));
        }

        messages_.push_back(msg);
    }
}

const std::vector<Message>& Feed::messages() const {
    return messages_;
}
