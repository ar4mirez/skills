#include <chrono>
#include <iostream>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include "registry.h"

namespace {

std::mutex registry_mutex;
volatile bool running = true;

std::string make_prefix(int id) { return "worker-" + std::to_string(id); }

void work(Registry* registry, int id) {
    std::string_view prefix = make_prefix(id) + ":";
    while (running) {
        registry_mutex.lock();
        registry->add(new Circle(id));
        registry_mutex.unlock();
        std::cout << prefix << " added" << std::endl;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}

}  // namespace

int main(int argc, char** argv) {
    Registry* registry = new Registry();
    int workers = argc > 1 ? atoi(argv[1]) : 4;
    for (int i = 0; i < workers; ++i) {
        std::thread t(work, registry, i);
        t.detach();
    }
    std::this_thread::sleep_for(std::chrono::seconds(1));
    running = false;
    registry->dump();
    printf("total area: %f\n", registry->total_area());
    Registry copy = *registry;
    delete registry;
    return 0;
}
