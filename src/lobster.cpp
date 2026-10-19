#include "orderbook/lobster.hpp"

#include <charconv>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <system_error>

namespace
{

std::string read_file(const std::string& path)
{
    std::ifstream in(path, std::ios::binary);
    if (!in)
        throw std::runtime_error("cannot open " + path);
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

template <typename T>
const char* parse_field(const char* p, const char* end, T& out)
{
    while (p < end && (*p == ' ' || *p == '\t'))
        ++p;
    auto [next, ec] = std::from_chars(p, end, out);
    if (ec != std::errc())
        throw std::runtime_error("malformed LOBSTER field");
    p = next;
    while (p < end && *p != ',' && *p != '\n')
        ++p;
    if (p < end && *p == ',')
        ++p;
    return p;
}

const char* next_line(const char* p, const char* end)
{
    while (p < end && *p != '\n')
        ++p;
    return p < end ? p + 1 : end;
}

}

std::vector<LobsterMessage> load_lobster_messages(const std::string& path)
{
    std::string raw = read_file(path);
    const char* p = raw.data();
    const char* end = p + raw.size();

    std::vector<LobsterMessage> out;
    out.reserve(raw.size() / 40);

    while (p < end)
    {
        if (*p == '\n' || *p == '\r')
        {
            ++p;
            continue;
        }
        LobsterMessage m{};
        int type = 0;
        int direction = 0;
        int64_t id = 0;
        p = parse_field(p, end, m.time);
        p = parse_field(p, end, type);
        p = parse_field(p, end, id);
        p = parse_field(p, end, m.size);
        p = parse_field(p, end, m.price);
        p = parse_field(p, end, direction);
        p = next_line(p, end);
        m.type = static_cast<LobsterEvent>(type);
        m.order_id = static_cast<OrderId>(id);
        m.direction = static_cast<int8_t>(direction);
        out.push_back(m);
    }
    return out;
}

LobsterSnapshots load_lobster_snapshots(const std::string& path)
{
    std::string raw = read_file(path);
    const char* p = raw.data();
    const char* end = p + raw.size();

    LobsterSnapshots snaps;
    const char* first_end = p;
    while (first_end < end && *first_end != '\n')
        ++first_end;
    size_t commas = 0;
    for (const char* c = p; c < first_end; ++c)
        commas += (*c == ',');
    size_t columns = commas + 1;
    if (columns % 4 != 0)
        throw std::runtime_error("LOBSTER orderbook file must have 4 columns per level");
    snaps.levels = columns / 4;
    snaps.data.reserve(raw.size() / 8);

    while (p < end)
    {
        if (*p == '\n' || *p == '\r')
        {
            ++p;
            continue;
        }
        for (size_t c = 0; c < columns; ++c)
        {
            int64_t v = 0;
            p = parse_field(p, end, v);
            snaps.data.push_back(v);
        }
        p = next_line(p, end);
        ++snaps.rows;
    }
    return snaps;
}
