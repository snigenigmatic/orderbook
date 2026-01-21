#include <gtest/gtest.h>
#include "orderbook/orderbook_vector.hpp"

// Test fixture for OrderBookVector
class OrderBookVectorTest : public ::testing::Test
{
protected:
    OrderBookVector book;

    // Helper to setup some state if needed
    void SetUp() override
    {
        // Code to run before each test
    }
};

TEST_F(OrderBookVectorTest, IsEmptyInitially)
{
    // Assuming 0 or some sentinel value means empty/no price.
    // Based on typical order book behavior, best_bid might be 0 or MIN_INT, best_ask MAX_INT.
    // Let's just check if adding something works for now.
    // Note: You might need to check your implementation of empty state return values.
    EXPECT_EQ(book.best_bid(), 0);
    EXPECT_EQ(book.best_ask(), 0);
}

TEST_F(OrderBookVectorTest, AddOrderUpdatesBestBid)
{
    book.on_add(1, Side::Bid, 100, 10);
    EXPECT_EQ(book.best_bid(), 100);
}

TEST_F(OrderBookVectorTest, AddOrderUpdatesBestAsk)
{
    book.on_add(2, Side::Ask, 105, 10);
    EXPECT_EQ(book.best_ask(), 105);
}

TEST_F(OrderBookVectorTest, BestPricesReflectTopMap)
{
    book.on_add(1, Side::Bid, 100, 10);
    book.on_add(2, Side::Bid, 101, 10); // Better price

    EXPECT_EQ(book.best_bid(), 101);
}
