#pragma once
#include <cstddef>
#include <string_view>
#include "shape.h"

// Owns the shapes it holds.
class Registry {
public:
    Registry();
    ~Registry();
    void add(Shape* s);
    double total_area() const;
    std::string_view label() const;
    void dump() const;

private:
    Shape** items_;
    std::size_t count_;
    char* label_;
};
