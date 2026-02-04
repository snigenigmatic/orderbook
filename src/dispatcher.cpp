#include "orderbook/dispatcher.hpp"
#include "orderbook/timing.hpp"

void Dispatcher::run(
    OrderBookBase &book,
    const Feed &feed,
    LatencyRecorder &recorder)
{
    for (const auto &msg : feed.messages())
    {
        uint64_t start = now_ns();

        switch (msg.type)
        {
        case MessageType::Add:
            book.on_add(
                msg.add.order_id,
                msg.add.side,
                msg.add.price,
                msg.add.volume);
            break;

        case MessageType::Modify:
            book.on_modify(
                msg.modify.order_id,
                msg.modify.new_volume);
            break;

        case MessageType::Delete:
            book.on_delete(msg.del.order_id);
            break;
        }

        uint64_t end = now_ns();
        recorder.record(end - start);
    }
}
