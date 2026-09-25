#pragma once
#include <algorithm>
#include <cmath>
#include <limits>

namespace shdev {
constexpr float PI = 3.14159265358979323846f;
struct Vec3 {
    float x = 0, y = 0, z = 0;
    Vec3 operator+(Vec3 b) const { return {x + b.x, y + b.y, z + b.z}; }
    Vec3 operator-(Vec3 b) const { return {x - b.x, y - b.y, z - b.z}; }
    Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }
    Vec3 operator/(float s) const { return *this * (1.f / s); }
    Vec3 mul(Vec3 b) const { return {x * b.x, y * b.y, z * b.z}; }
    float dot(Vec3 b) const { return x * b.x + y * b.y + z * b.z; }
    Vec3 cross(Vec3 b) const { return {y * b.z - z * b.y, z * b.x - x * b.z, x * b.y - y * b.x}; }
    float length() const { return std::sqrt(dot(*this)); }
    Vec3 normalized() const {
        float n = length();
        return n > 1e-7f ? *this / n : Vec3{};
    }
    bool finite() const { return std::isfinite(x) && std::isfinite(y) && std::isfinite(z); }
};
struct Quat {
    float x = 0, y = 0, z = 0, w = 1;
    Quat operator*(Quat b) const {
        return {w * b.x + x * b.w + y * b.z - z * b.y, w * b.y - x * b.z + y * b.w + z * b.x,
                w * b.z + x * b.y - y * b.x + z * b.w, w * b.w - x * b.x - y * b.y - z * b.z};
    }
    Quat inverse() const { return {-x, -y, -z, w}; }
    Quat normalized() const {
        float n = std::sqrt(x * x + y * y + z * z + w * w);
        return n > 1e-8f ? Quat{x / n, y / n, z / n, w / n} : Quat{};
    }
    Vec3 rotate(Vec3 v) const {
        Vec3 u{x, y, z};
        Vec3 t = u.cross(v) * 2;
        return v + t * w + u.cross(t);
    }
    static Quat axis(Vec3 a, float r) {
        float s = std::sin(r / 2);
        return {a.x * s, a.y * s, a.z * s, std::cos(r / 2)};
    }
    static Quat euler(Vec3 r) {
        return (axis({0, 1, 0}, r.y) * axis({1, 0, 0}, r.x) * axis({0, 0, 1}, r.z)).normalized();
    }
    Vec3 euler() const {
        // Inverse of Y * X * Z, with a stable pole convention.
        const float r12 = 2 * (y * z - w * x);
        float rx = std::asin(std::clamp(-r12, -1.f, 1.f));
        if (std::abs(std::cos(rx)) < 1e-5f)
            return {rx, std::atan2(-2 * (x * z - w * y), 1 - 2 * (y * y + z * z)), 0};
        return {rx, std::atan2(2 * (x * z + w * y), 1 - 2 * (x * x + y * y)),
                std::atan2(2 * (x * y + w * z), 1 - 2 * (x * x + z * z))};
    }
};
struct Transform {
    Vec3 position;
    Quat rotation;
};
struct Mat4 {
    float v[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    static Mat4 from(Transform t) {
        Mat4 m;
        Vec3 x = t.rotation.rotate({1, 0, 0}), y = t.rotation.rotate({0, 1, 0}),
             z = t.rotation.rotate({0, 0, 1});
        m.v[0] = x.x;
        m.v[1] = x.y;
        m.v[2] = x.z;
        m.v[4] = y.x;
        m.v[5] = y.y;
        m.v[6] = y.z;
        m.v[8] = z.x;
        m.v[9] = z.y;
        m.v[10] = z.z;
        m.v[12] = t.position.x;
        m.v[13] = t.position.y;
        m.v[14] = t.position.z;
        return m;
    }
};
struct Bounds {
    Vec3 min{INFINITY, INFINITY, INFINITY}, max{-INFINITY, -INFINITY, -INFINITY};
    void add(Vec3 p) {
        min = {std::min(min.x, p.x), std::min(min.y, p.y), std::min(min.z, p.z)};
        max = {std::max(max.x, p.x), std::max(max.y, p.y), std::max(max.z, p.z)};
    }
    Vec3 center() const { return (min + max) * .5f; }
    bool valid() const {
        return min.finite() && max.finite() && min.x <= max.x && min.y <= max.y && min.z <= max.z;
    }
};
inline float rayTriangle(Vec3 o, Vec3 d, Vec3 a, Vec3 b, Vec3 c) {
    Vec3 e1 = b - a, e2 = c - a, p = d.cross(e2);
    float det = e1.dot(p);
    if (std::abs(det) < 1e-7f)
        return INFINITY;
    float inv = 1 / det;
    Vec3 t = o - a;
    float u = t.dot(p) * inv;
    if (u < 0 || u > 1)
        return INFINITY;
    Vec3 q = t.cross(e1);
    float v = d.dot(q) * inv;
    if (v < 0 || u + v > 1)
        return INFINITY;
    float distance = e2.dot(q) * inv;
    return distance > .005f ? distance : INFINITY;
}
inline bool rayBounds(Vec3 o, Vec3 d, Bounds b, float limit = INFINITY) {
    float lo = 0, hi = limit;
    float oo[] = {o.x, o.y, o.z}, dd[] = {d.x, d.y, d.z}, mn[] = {b.min.x, b.min.y, b.min.z},
          mx[] = {b.max.x, b.max.y, b.max.z};
    for (int i = 0; i < 3; i++) {
        if (std::abs(dd[i]) < 1e-8f) {
            if (oo[i] < mn[i] || oo[i] > mx[i])
                return false;
        } else {
            float a = (mn[i] - oo[i]) / dd[i], z = (mx[i] - oo[i]) / dd[i];
            if (a > z)
                std::swap(a, z);
            lo = std::max(lo, a);
            hi = std::min(hi, z);
            if (lo > hi)
                return false;
        }
    }
    return true;
}
} // namespace shdev
