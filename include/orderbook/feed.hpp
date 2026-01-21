#pragma once
#include "messages.hpp"
#include <vector>

class Feed {
public:
    explicit Feed(size_t count);

    const std::vector<Message>& messages() const;

private:
    std::vector<Message> messages_;
};
