#include <gtest/gtest.h>
#include "orderbook/backtest.hpp"
#include "orderbook/fifo_book.hpp"
#include "orderbook/orderbook_map.hpp"
#include "orderbook/orderbook_vector.hpp"

TEST(FifoOrderBook, QueueAheadTracksCancelsInFront)
{
    FifoOrderBook book;
    book.on_add(1, Side::Bid, 100, 100);
    book.on_add(2, Side::Bid, 100, 50);
    book.add_own(1000, Side::Bid, 100, 30);
    book.on_add(3, Side::Bid, 100, 70);

    EXPECT_EQ(book.queue_ahead(1000), 150);
    EXPECT_EQ(book.visible_at(Side::Bid, 100), 220);

    book.on_delete(1);
    EXPECT_EQ(book.queue_ahead(1000), 50);

    book.cancel_partial(2, 20);
    EXPECT_EQ(book.queue_ahead(1000), 30);

    book.on_delete(3);
    EXPECT_EQ(book.queue_ahead(1000), 30);
}

TEST(FifoOrderBook, VolumeIncreaseLosesPriority)
{
    FifoOrderBook book;
    book.on_add(1, Side::Ask, 101, 10);
    book.add_own(1000, Side::Ask, 101, 5);
    EXPECT_EQ(book.queue_ahead(1000), 10);

    book.on_modify(1, 40);
    EXPECT_EQ(book.queue_ahead(1000), 0);
    EXPECT_EQ(book.visible_at(Side::Ask, 101), 40);
}

TEST(FifoOrderBook, OwnOrdersAreInvisible)
{
    FifoOrderBook book;
    book.add_own(1000, Side::Bid, 105, 10);
    EXPECT_FALSE(book.has_bid());
    EXPECT_TRUE(book.depth(Side::Bid, 5).empty());
}

TEST(FifoOrderBook, GhostVolumeGoesToFrontOfQueue)
{
    FifoOrderBook book;
    book.on_add(1, Side::Bid, 100, 100);
    book.add_own(1000, Side::Bid, 100, 10);
    book.set_level_visible(Side::Bid, 100, 400);
    EXPECT_EQ(book.visible_at(Side::Bid, 100), 400);
    EXPECT_EQ(book.queue_ahead(1000), 400);

    book.set_level_visible(Side::Bid, 100, 150);
    EXPECT_EQ(book.visible_at(Side::Bid, 100), 150);
    EXPECT_EQ(book.queue_ahead(1000), 150);
}

TEST(FifoOrderBook, ExecuteReportsPrioritySequence)
{
    FifoOrderBook book;
    book.on_add(7, Side::Ask, 200, 30);
    ExecResult r = book.execute(7, 10);
    EXPECT_TRUE(r.found);
    EXPECT_EQ(r.price, 200);
    EXPECT_EQ(r.volume, 10);
    EXPECT_EQ(book.visible_at(Side::Ask, 200), 20);
    EXPECT_FALSE(book.execute(99, 1).found);
}

TEST(OriginalBooks, ExecuteRemovesFilledLevels)
{
    OrderBookMap map_book;
    OrderBookVector vector_book;
    for (OrderBookBase* book : {static_cast<OrderBookBase*>(&map_book), static_cast<OrderBookBase*>(&vector_book)})
    {
        book->on_add(1, Side::Bid, 100, 10);
        book->on_add(2, Side::Bid, 99, 10);
        book->on_execute(1, 4);
        EXPECT_EQ(book->best_bid(), 100);
        book->on_execute(1, 6);
        EXPECT_EQ(book->best_bid(), 99);
    }
}

namespace
{

LobsterMessage msg(double t, LobsterEvent type, OrderId id, Volume size, Price price, int8_t dir)
{
    return LobsterMessage{t, type, id, size, price, dir};
}

BacktestConfig test_config()
{
    BacktestConfig c;
    c.order_latency = 0.001;
    c.reconcile = false;
    c.maker_rebate = 0;
    return c;
}

}

TEST(Backtester, FillsOnlyWhenExecutionsReachOurQueuePosition)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000100, -1),
        msg(34200.3, LobsterEvent::ExecuteVisible, 1, 60, 1000000, 1),
        msg(34200.4, LobsterEvent::Submit, 3, 10, 1000000, 1),
        msg(34200.5, LobsterEvent::ExecuteVisible, 1, 40, 1000000, 1),
        msg(34200.6, LobsterEvent::ExecuteVisible, 3, 10, 1000000, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());

    bt.run_until(34200.2);
    OrderId id = bt.submit(Side::Bid, 1000000, 50);

    bt.run_until(34200.35);
    EXPECT_EQ(bt.queue_ahead(id), 40);
    EXPECT_EQ(bt.position(), 0);

    bt.run_until(34200.55);
    EXPECT_EQ(bt.queue_ahead(id), 0);
    EXPECT_EQ(bt.position(), 0);

    bt.run_until(34200.7);
    EXPECT_EQ(bt.position(), 10);
    EXPECT_EQ(bt.cash(), -10 * 1000000);

    auto fills = bt.take_fills();
    ASSERT_EQ(fills.size(), 1u);
    EXPECT_EQ(fills[0].queue_at_entry, 100);
    EXPECT_EQ(fills[0].volume, 10);
}

TEST(Backtester, TradeThroughOurPriceFillsUs)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000300, -1),
        msg(34200.5, LobsterEvent::ExecuteVisible, 1, 25, 1000000, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    bt.submit(Side::Bid, 1000100, 40);
    bt.run_to_end();
    EXPECT_EQ(bt.position(), 25);
}

TEST(Backtester, HiddenExecutionAtOurPriceFillsDisplayedOrder)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000300, -1),
        msg(34200.5, LobsterEvent::ExecuteHidden, 0, 15, 1000200, -1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    bt.submit(Side::Ask, 1000200, 40);
    bt.run_to_end();
    EXPECT_EQ(bt.position(), -15);
}

TEST(Backtester, MarketableAddAgainstOurQuoteFillsUs)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000300, -1),
        msg(34200.5, LobsterEvent::Submit, 3, 30, 1000100, -1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    bt.submit(Side::Bid, 1000100, 20);
    bt.run_to_end();
    EXPECT_EQ(bt.position(), 20);
}

TEST(Backtester, PostOnlyRejectsCrossingOrders)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000100, -1),
        msg(34200.9, LobsterEvent::Submit, 3, 1, 999900, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    OrderId id = bt.submit(Side::Bid, 1000100, 10);
    bt.run_to_end();
    EXPECT_EQ(bt.order(id)->status, OwnStatus::Rejected);
}

TEST(Backtester, LatencyDelaysActivationAndCancels)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000300, -1),
        msg(34200.2005, LobsterEvent::ExecuteHidden, 0, 50, 1000100, 1),
        msg(34200.3, LobsterEvent::ExecuteHidden, 0, 50, 1000100, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    OrderId id = bt.submit(Side::Bid, 1000100, 10);
    bt.run_until(34200.25);
    EXPECT_EQ(bt.order(id)->status, OwnStatus::Active);
    EXPECT_EQ(bt.position(), 0);
    bt.cancel(id);
    bt.run_to_end();
    EXPECT_EQ(bt.order(id)->status, OwnStatus::Cancelled);
    EXPECT_EQ(bt.position(), 0);
}

TEST(Backtester, FillNoticeUsesPriorityWithoutRemovingVolume)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000300, -1),
        msg(34200.4, LobsterEvent::Submit, 3, 50, 1000000, 1),
        msg(34200.5, LobsterEvent::FillNotice, 1, 100, 1000000, 1),
        msg(34200.5, LobsterEvent::PartialCancel, 1, 100, 1000000, 1),
        msg(34200.6, LobsterEvent::FillNotice, 3, 30, 1000000, 1),
        msg(34200.6, LobsterEvent::PartialCancel, 3, 30, 1000000, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    OrderId id = bt.submit(Side::Bid, 1000000, 40);
    bt.run_until(34200.55);
    EXPECT_EQ(bt.position(), 0);
    EXPECT_EQ(bt.queue_ahead(id), 0);
    EXPECT_EQ(bt.book().visible_at(Side::Bid, 1000000), 50);
    bt.run_to_end();
    EXPECT_EQ(bt.position(), 30);
    EXPECT_EQ(bt.book().visible_at(Side::Bid, 1000000), 20);
}

TEST(Backtester, ModifyFollowsDatabentoPriorityRules)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 9, 100, 1000300, -1),
        msg(34200.4, LobsterEvent::Modify, 1, 60, 1000000, 1),
        msg(34200.5, LobsterEvent::Modify, 2, 150, 1000000, 1),
        msg(34200.6, LobsterEvent::Modify, 1, 60, 999900, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    OrderId id = bt.submit(Side::Bid, 1000000, 10);
    bt.run_until(34200.45);
    EXPECT_EQ(bt.queue_ahead(id), 160);
    bt.run_until(34200.55);
    EXPECT_EQ(bt.queue_ahead(id), 60);
    bt.run_to_end();
    EXPECT_EQ(bt.queue_ahead(id), 0);
    EXPECT_EQ(bt.book().visible_at(Side::Bid, 999900), 60);
}

TEST(Backtester, ClearWipesMarketButKeepsOwnOrders)
{
    std::vector<LobsterMessage> msgs = {
        msg(34200.1, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(34200.1, LobsterEvent::Submit, 2, 100, 1000300, -1),
        msg(34200.5, LobsterEvent::Clear, 0, 0, 0, 0),
        msg(34200.6, LobsterEvent::Submit, 3, 70, 1000000, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34200.2);
    OrderId id = bt.submit(Side::Bid, 1000000, 10);
    bt.run_to_end();
    EXPECT_FALSE(bt.book().has_ask());
    EXPECT_EQ(bt.book().visible_at(Side::Bid, 1000000), 70);
    EXPECT_EQ(bt.queue_ahead(id), 0);
}

TEST(Backtester, PreMarketEventsBuildBookButNotBars)
{
    std::vector<LobsterMessage> msgs = {
        msg(30000.0, LobsterEvent::Submit, 1, 100, 1000000, 1),
        msg(30000.0, LobsterEvent::Submit, 2, 100, 1000400, -1),
        msg(31000.0, LobsterEvent::Submit, 3, 100, 1000200, -1),
        msg(31000.5, LobsterEvent::FillNotice, 3, 100, 1000200, -1),
        msg(31000.5, LobsterEvent::PartialCancel, 3, 100, 1000200, -1),
        msg(34205.0, LobsterEvent::Submit, 4, 100, 999900, 1),
    };
    Backtester bt(msgs, LobsterSnapshots{}, test_config());
    bt.run_until(34215.0);
    ASSERT_EQ(bt.bars().end_time.size(), 1u);
    EXPECT_DOUBLE_EQ(bt.bars().volume[0], 0.0);
    EXPECT_DOUBLE_EQ(bt.bars().realized_var[0], 0.0);
    EXPECT_DOUBLE_EQ(bt.bars().spread[0], 400.0);
}
