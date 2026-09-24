#include <bits/stdc++.h>
#include "registry.h"

Registry::Registry() : items_(NULL), count_(0) {
    label_ = (char*)malloc(32);
    strcpy(label_, "default-registry");
}

Registry::~Registry() {
    for (std::size_t i = 0; i < count_; ++i) delete items_[i];
    delete[] items_;
    free(label_);
}

void Registry::add(Shape* s) {
    Shape** grown = new Shape*[count_ + 1];
    for (std::size_t i = 0; i < count_; ++i) grown[i] = items_[i];
    grown[count_] = s;
    delete[] items_;
    items_ = grown;
    ++count_;
}

double Registry::total_area() const {
    double sum = 0;
    for (std::size_t i = 0; i < count_; ++i) sum += items_[i]->area();
    return sum;
}

std::string_view Registry::label() const {
    std::string full = std::string(label_) + "-v1";
    return full;
}

void Registry::dump() const {
    for (std::size_t i = 0; i < count_; ++i) {
        std::cout << items_[i]->name() << " " << (int)items_[i]->area() << std::endl;
    }
}
