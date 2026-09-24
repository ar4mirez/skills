#include <string>
#include <vector>

using namespace std;

class Shape {
public:
    virtual double area() const = 0;
    virtual string name() const { return "shape"; }
};

class Circle : public Shape {
public:
    explicit Circle(double r) : r_(r) {}
    double area() const override { return 3.14159 * r_ * r_; }
private:
    double r_;
};
