#pragma once
#include "messages.hpp"

#include <cstdint>
#include <string>
#include <vector>

enum class LobsterEvent : int8_t
{
    Submit = 1,
    PartialCancel = 2,
    Delete = 3,
    ExecuteVisible = 4,
    ExecuteHidden = 5,
    Cross = 6,
    Halt = 7,
    FillNotice = 8,
    Clear = 9,
    Modify = 10
};

struct LobsterMessage
{
    double time;
    LobsterEvent type;
    OrderId order_id;
    Volume size;
    Price price;
    int8_t direction;
};

inline Side lobster_side(int8_t direction)
{
    return direction > 0 ? Side::Bid : Side::Ask;
}

struct LobsterSnapshots
{
    size_t levels = 0;
    size_t rows = 0;
    std::vector<int64_t> data;

    static constexpr int64_t kEmptyAsk = 9999999999LL;
    static constexpr int64_t kEmptyBid = -9999999999LL;

    int64_t ask_price(size_t row, size_t level) const { return data[row * levels * 4 + level * 4 + 0]; }
    int64_t ask_size(size_t row, size_t level) const { return data[row * levels * 4 + level * 4 + 1]; }
    int64_t bid_price(size_t row, size_t level) const { return data[row * levels * 4 + level * 4 + 2]; }
    int64_t bid_size(size_t row, size_t level) const { return data[row * levels * 4 + level * 4 + 3]; }
};

std::vector<LobsterMessage> load_lobster_messages(const std::string& path);
LobsterSnapshots load_lobster_snapshots(const std::string& path);
