#pragma once
#include "orderbook_base.hpp"

#include <cstdint>
#include <functional>
#include <list>
#include <map>
#include <unordered_map>
#include <utility>
#include <vector>

struct QueueNode
{
    OrderId order_id;
    uint64_t seq;
    Volume volume;
    bool own;
};

struct PriceLevel
{
    Volume visible = 0;
    std::list<QueueNode> queue;
};

struct ExecResult
{
    bool found = false;
    Side side = Side::Bid;
    Price price = 0;
    uint64_t seq = 0;
    Volume volume = 0;
};

class FifoOrderBook : public OrderBookBase
{
public:
    static constexpr OrderId kGhostId = 0;

    void on_add(OrderId order_id, Side side, Price price, Volume volume) override;
    void on_modify(OrderId order_id, Volume new_volume) override;
    void on_delete(OrderId order_id) override;
    void on_execute(OrderId order_id, Volume volume) override;

    Price best_bid() const override;
    Price best_ask() const override;

    bool has_bid() const;
    bool has_ask() const;

    bool cancel_partial(OrderId order_id, Volume volume);
    ExecResult execute(OrderId order_id, Volume volume);
    bool contains(OrderId order_id) const;

    uint64_t add_own(OrderId order_id, Side side, Price price, Volume volume);
    bool reduce_own(OrderId order_id, Volume volume);
    bool remove_own(OrderId order_id);
    Volume queue_ahead(OrderId order_id) const;

    Volume set_level_visible(Side side, Price price, Volume target);
    Volume visible_at(Side side, Price price) const;
    std::vector<std::pair<Price, Volume>> depth(Side side, size_t levels) const;
    std::vector<Price> visible_prices(Side side, size_t max_levels) const;

    size_t order_count() const { return index_.size(); }
    uint64_t next_seq() const { return seq_ + 1; }

private:
    using BidLevels = std::map<Price, PriceLevel, std::greater<Price>>;
    using AskLevels = std::map<Price, PriceLevel, std::less<Price>>;

    struct Locator
    {
        Side side;
        Price price;
        std::list<QueueNode>::iterator node;
    };

    BidLevels bids_;
    AskLevels asks_;
    std::unordered_map<OrderId, Locator> index_;
    uint64_t seq_ = 0;

    PriceLevel* find_level(Side side, Price price);
    const PriceLevel* find_level(Side side, Price price) const;
    PriceLevel& level_for(Side side, Price price);
    void erase_level_if_empty(Side side, Price price);
    void shrink(Locator& loc, Volume volume);
};
