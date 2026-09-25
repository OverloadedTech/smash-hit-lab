#pragma once
#include "state.hpp"

namespace shdev {
Json readLocalJson(const std::string &path, size_t limit = 4 * 1024 * 1024);
void saveLocalJson(const std::string &path, const Json &value);
}
